"""pdf_viewer daemon — read-only FastAPI service over ~/.cache/pdf_viewer/.

Routes:
    GET    /view?path=<local>   light HTML by default, canonical/PDF fallback
    GET    /view?url=<remote>   light HTML by default, canonical/remote fallback
    GET    /view-raw?<remote>   same as /view?url=, but preserves raw query strings
    GET    /view-canonical?...  canonical HTML rollback route
    GET    /view-light?...      explicit light HTML, canonical fallback
    GET    /stats               visit totals + top 20 by count (hash → name enriched)
    GET    /stats/recent        raw visit timeline, most-recent first
    GET    /_assets/*           overlay.{css,js} from the repo assets dir
    GET    /<hash>/<file>       cached pdf2htmlEX bundle (html + any sibling files)
    GET    /healthz             liveness probe
    DELETE /mapping/<hash>      drop the mapping row, rmtree the dir, forget visits
    PUT    /entry/<hash>/name   rename a cache entry's HTML file (changes search name)

The daemon never invokes Docker — conversion stays in the Raycast scripts
(ADR 0004). Cache hits are O(hash + sendfile); content-hash lookups for
local PDFs are memoized by (path, mtime_ns, size) so repeat requests on
the same file don't re-hash.

Run:
    uv run --directory daemon main.py                          # dev
    uv run --directory daemon uvicorn main:app \
        --host 127.0.0.1 --port 7435                           # prod / launchd
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import time
import urllib.parse
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import visits
from catalog import (
    CacheCatalog,
    EntryNotFound,
    InvalidCatalogInput,
    NameConflict,
    strip_passthrough,
    url_hash,
    with_passthrough,
)

CACHE_DIR = pathlib.Path.home() / ".cache" / "pdf_viewer"
REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_DIR / "assets"
catalog = CacheCatalog(CACHE_DIR, visits)

app = FastAPI(title="pdf_viewer", version="0.1.0")


def _prefer_light_from_environment() -> bool:
    """Prefer light HTML unless an explicit canonical rollback is requested."""
    value = os.environ.get("PDF_VIEWER_PREFER_LIGHT", "")
    return value.strip().lower() not in {"false", "0", "no", "off"}


@app.on_event("startup")
def _startup() -> None:
    visits.init()


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.get("/cache-urls")
def cache_urls():
    """List every cache entry as a dict for the browser extension.

    Two kinds:
      - {"kind": "url",  "host": ..., "path": ..., "hash": ...}
        → extension matches ^https?://<host><path>(?:\\?.*)?$
      - {"kind": "file", "path": /absolute/path.pdf, "hash": ...}
        → extension matches ^file://<url-encoded path>(?:\\?.*)?$

    In both cases the rule redirects into the /view route. The path kind
    requires the extension manifest to include file:///* host permissions
    AND the user to toggle "Allow access to file URLs" per-extension.
    """
    return catalog.extension_entries()


# -----------------------------------------------------------------------------
# Navigation signals — extension-mediated tab navigation.
#
# The convert script POSTs {from_url, to_url} here when a cache-miss
# conversion finishes. The browser extension long-polls /signal/navigate/wait,
# picks up the signal, and calls chrome.tabs.update(tabId, {url}). That API
# doesn't touch focus at all, which is the whole reason we're going this
# route instead of AppleScript (Apple Events pull Chromium to the front on
# any tab mutation, causing a visible flash even with snapshot+restore).
#
# Signals have a 60s TTL. If the extension is asleep and misses the window,
# the viewer is still in cache — next click on the PDF link hits the static
# redirect rule and opens it anyway.
# -----------------------------------------------------------------------------

_NAV_SIGNAL_TTL_SEC = 60
_pending_nav_signals: list[dict] = []
_nav_signal_event: Optional[asyncio.Event] = None


def _nav_event() -> asyncio.Event:
    # Lazy-init so the event binds to the running loop (FastAPI creates one
    # per process). Accessing asyncio.Event() at import time binds to the
    # wrong loop and `.set()` becomes a no-op for awaiters.
    global _nav_signal_event
    if _nav_signal_event is None:
        _nav_signal_event = asyncio.Event()
    return _nav_signal_event


def _purge_expired_nav_signals() -> None:
    cutoff = time.time() - _NAV_SIGNAL_TTL_SEC
    _pending_nav_signals[:] = [
        s for s in _pending_nav_signals if s["created_at"] >= cutoff
    ]


def _queue_extension_sync_signal(hash_: str, reason: str) -> None:
    _purge_expired_nav_signals()
    _pending_nav_signals.append({
        "type": "sync_rules",
        "hash": hash_,
        "reason": reason,
        "created_at": time.time(),
    })
    _nav_event().set()


class NavigateSignal(BaseModel):
    from_url: str
    to_url: str


def _queue_navigate_signal(from_url: str, to_url: str) -> None:
    _purge_expired_nav_signals()
    _pending_nav_signals.append({
        "type": "navigate",
        "from_url": from_url,
        "to_url": to_url,
        "created_at": time.time(),
    })
    _nav_event().set()


@app.post("/signal/navigate")
async def signal_navigate(sig: NavigateSignal):
    _queue_navigate_signal(sig.from_url, sig.to_url)
    return {"queued": True, "pending": len(_pending_nav_signals)}


@app.get("/signal/navigate/wait")
async def signal_navigate_wait(timeout: float = Query(25.0, ge=0.0, le=60.0)):
    _purge_expired_nav_signals()
    if not _pending_nav_signals:
        ev = _nav_event()
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return []
        ev.clear()
    _purge_expired_nav_signals()
    out = list(_pending_nav_signals)
    _pending_nav_signals.clear()
    return out


@app.get("/healthz")
def healthz():
    entries = 0
    if CACHE_DIR.is_dir():
        entries = sum(
            1 for p in CACHE_DIR.iterdir()
            if p.is_dir() and not p.name.startswith("_")
        )
    return {
        "status": "ok",
        "cache_dir": str(CACHE_DIR),
        "cache_exists": CACHE_DIR.is_dir(),
        "entries": entries,
    }


@app.get("/view")
def view(
    background: BackgroundTasks,
    path: Optional[str] = Query(None, description="absolute local path"),
    url: Optional[str] = Query(None, description="http(s) URL"),
):
    if (path is None) == (url is None):
        raise HTTPException(400, "provide exactly one of: path, url")
    if path is not None:
        return _view_path(path, background, light=_prefer_light_from_environment())
    assert url is not None
    return _view_url(url, background, light=_prefer_light_from_environment())


@app.get("/view-light")
def view_light(
    background: BackgroundTasks,
    path: Optional[str] = Query(None, description="absolute local path"),
    url: Optional[str] = Query(None, description="http(s) URL"),
):
    if (path is None) == (url is None):
        raise HTTPException(400, "provide exactly one of: path, url")
    if path is not None:
        return _view_path(path, background, light=True)
    assert url is not None
    return _view_url(url, background, light=True)


@app.get("/view-canonical")
def view_canonical(
    background: BackgroundTasks,
    path: Optional[str] = Query(None, description="absolute local path"),
    url: Optional[str] = Query(None, description="http(s) URL"),
):
    if (path is None) == (url is None):
        raise HTTPException(400, "provide exactly one of: path, url")
    if path is not None:
        return _view_path(path, background, light=False)
    assert url is not None
    return _view_url(url, background, light=False)


@app.get("/view-raw")
def view_raw(request: Request, background: BackgroundTasks):
    """Remote URL view route for extension redirects.

    declarativeNetRequest regex substitutions cannot percent-encode captures.
    The extension therefore redirects to `/view-raw?<original-url>` and this
    route treats the entire raw query string as the URL, preserving signed
    query strings containing `&`.
    """
    raw_query = request.scope.get("query_string", b"")
    if not raw_query:
        raise HTTPException(400, "missing raw URL query string")
    try:
        url = raw_query.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(400, "raw URL must be ASCII / percent-encoded")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "raw URL must be an absolute http(s) URL")
    return _view_url(url, background, light=_prefer_light_from_environment())


@app.get("/view-light-raw")
def view_light_raw(request: Request, background: BackgroundTasks):
    """Light-variant remote URL route for extension redirects."""
    raw_query = request.scope.get("query_string", b"")
    if not raw_query:
        raise HTTPException(400, "missing raw URL query string")
    try:
        url = raw_query.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(400, "raw URL must be ASCII / percent-encoded")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "raw URL must be an absolute http(s) URL")
    return _view_url(url, background, light=True)


@app.get("/view-canonical-raw")
def view_canonical_raw(request: Request, background: BackgroundTasks):
    """Canonical rollback route preserving raw signed URL queries."""
    raw_query = request.scope.get("query_string", b"")
    if not raw_query:
        raise HTTPException(400, "missing raw URL query string")
    try:
        url = raw_query.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(400, "raw URL must be ASCII / percent-encoded")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "raw URL must be an absolute http(s) URL")
    return _view_url(url, background, light=False)


def _view_path(path: str, background: BackgroundTasks, *, light: bool):
    try:
        p = pathlib.Path(path).expanduser().resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(404, f"file not found: {path}")
    if not p.is_file():
        raise HTTPException(400, f"not a regular file: {path}")

    resolved = catalog.resolve_source(p, prefer_light=light)
    if resolved.representation is not None:
        if resolved.disabled:
            return FileResponse(
                p,
                media_type="application/pdf",
                filename=p.name,
                content_disposition_type="inline",
            )
        background.add_task(visits.record, resolved.hash, "path")
        return FileResponse(resolved.representation.selected, media_type="text/html; charset=utf-8")

    # Cache miss. Chromium blocks http→file: redirects, so we can't 307 to
    # file://. Stream the bytes as application/pdf — browser opens native
    # viewer. User can then run Raycast convert to escalate into HTML.
    return FileResponse(
        p,
        media_type="application/pdf",
        filename=p.name,
        content_disposition_type="inline",
    )


def _view_url(url: str, background: BackgroundTasks, *, light: bool):
    try:
        resolved = catalog.resolve_source(url, prefer_light=light)
    except InvalidCatalogInput as error:
        raise HTTPException(400, str(error)) from error
    if resolved.representation is not None:
        if resolved.disabled:
            return RedirectResponse(
                with_passthrough(strip_passthrough(url)),
                status_code=307,
            )
        background.add_task(visits.record, resolved.hash, "url")
        return FileResponse(resolved.representation.selected, media_type="text/html; charset=utf-8")
    # Cache miss: 307 to the original URL, but tag it with a marker so the
    # browser extension's allow-rule short-circuits the redirect match —
    # otherwise clicks on .pdf links would loop (ext redirects → daemon 307s
    # → ext redirects → ...) until Chromium ERR_TOO_MANY_REDIRECTS.
    return RedirectResponse(with_passthrough(url), status_code=307)


def _require_cached_entry(hash_: str) -> pathlib.Path:
    try:
        return catalog.require_representation(hash_).selected
    except InvalidCatalogInput as error:
        raise HTTPException(400, str(error)) from error
    except EntryNotFound as error:
        raise HTTPException(404, str(error)) from error


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _viewer_url_for_hash(hash_: str, request: Request) -> str:
    html = _require_cached_entry(hash_)
    return f"{_base_url(request)}/{hash_}/{urllib.parse.quote(html.name)}"


def _file_url_for_path(path: str) -> str:
    return pathlib.Path(path).expanduser().resolve().as_uri()


def _native_browser_url_for_hash(hash_: str, request: Request) -> str:
    _require_cached_entry(hash_)
    source_ref = catalog.source_ref(hash_)
    if source_ref and source_ref.startswith("/"):
        return _file_url_for_path(source_ref)
    if source_ref and source_ref.startswith(("http://", "https://")):
        return with_passthrough(source_ref)
    return _native_url_for_hash(hash_, request)


def _native_url_for_hash(hash_: str, request: Request) -> str:
    _require_cached_entry(hash_)
    return f"{_base_url(request)}/native?hash={urllib.parse.quote(hash_)}"


def _native_response_for_hash(hash_: str):
    try:
        native = catalog.native_source(hash_)
    except InvalidCatalogInput as error:
        raise HTTPException(400, str(error)) from error
    except EntryNotFound as error:
        raise HTTPException(404, str(error)) from error
    if native.kind == "url":
        return RedirectResponse(str(native.value), status_code=307)
    path = pathlib.Path(native.value)
    return FileResponse(path, media_type="application/pdf", filename=path.name,
                        content_disposition_type="inline")


@app.get("/native")
def native_pdf(
    hash_: Optional[str] = Query(None, alias="hash"),
    path: Optional[str] = Query(None, description="absolute local path"),
    url: Optional[str] = Query(None, description="http(s) URL"),
):
    provided = [v is not None for v in (hash_, path, url)].count(True)
    if provided != 1:
        raise HTTPException(400, "provide exactly one of: hash, path, url")

    if hash_ is not None:
        return _native_response_for_hash(hash_)
    if path is not None:
        try:
            p = pathlib.Path(path).expanduser().resolve(strict=True)
        except FileNotFoundError:
            raise HTTPException(404, f"file not found: {path}")
        if not p.is_file():
            raise HTTPException(400, f"not a regular file: {path}")
        return FileResponse(
            p,
            media_type="application/pdf",
            filename=p.name,
            content_disposition_type="inline",
        )

    assert url is not None
    hash_for_url = url_hash(url)
    cached_pdf = catalog.cached_source(hash_for_url)
    if cached_pdf is not None:
        return FileResponse(
            cached_pdf,
            media_type="application/pdf",
            filename=cached_pdf.name,
            content_disposition_type="inline",
        )
    return RedirectResponse(with_passthrough(url), status_code=307)


class DisabledRequest(BaseModel):
    disabled: bool
    current_url: Optional[str] = None


@app.put("/entry/{hash_}/disabled")
def update_entry_disabled(hash_: str, body: DisabledRequest, request: Request):
    _require_cached_entry(hash_)
    disabled = catalog.set_disabled(hash_, body.disabled)
    _queue_extension_sync_signal(hash_, "entry-disabled")
    target_url = (
        _native_browser_url_for_hash(hash_, request)
        if disabled else _viewer_url_for_hash(hash_, request)
    )
    extension_navigation_queued = False
    if disabled and body.current_url:
        _queue_navigate_signal(body.current_url, target_url)
        extension_navigation_queued = True
    return {
        "hash": hash_,
        "disabled": disabled,
        "target_url": target_url,
        "native_url": _native_url_for_hash(hash_, request),
        "native_browser_url": _native_browser_url_for_hash(hash_, request),
        "viewer_url": _viewer_url_for_hash(hash_, request),
        "extension_navigation_queued": extension_navigation_queued,
    }


class ExtensionToggleRequest(BaseModel):
    url: str


@app.post("/extension/toggle")
def extension_toggle(body: ExtensionToggleRequest, request: Request):
    hash_ = catalog.hash_for_browser_url(body.url)
    if not hash_:
        raise HTTPException(404, "could not resolve current tab to a cached PDF")
    _require_cached_entry(hash_)

    disabled = catalog.set_disabled(hash_, not catalog.is_disabled(hash_))
    _queue_extension_sync_signal(hash_, "extension-toggle")
    target_url = (
        _native_browser_url_for_hash(hash_, request)
        if disabled else _viewer_url_for_hash(hash_, request)
    )
    return {
        "hash": hash_,
        "disabled": disabled,
        "target_url": target_url,
        "native_url": _native_url_for_hash(hash_, request),
        "native_browser_url": _native_browser_url_for_hash(hash_, request),
        "viewer_url": _viewer_url_for_hash(hash_, request),
    }


@app.delete("/mapping/{hash_}")
def delete_mapping(hash_: str):
    """Wipe a cache entry: drop its mappings.tsv row, rmtree the dir, forget visits.

    Returns {source_ref, removed_dir, mapping_dropped, visits_deleted} so the
    overlay can redirect back to the original URL/path. Idempotent: a missing
    dir or row is not an error — we report what we actually removed.

    Hash is anchored to ^[a-f0-9]{6,32}$ to keep rmtree inside CACHE_DIR.
    """
    was_disabled = catalog.is_disabled(hash_)
    try:
        result = catalog.delete(hash_)
    except InvalidCatalogInput as error:
        raise HTTPException(400, str(error)) from error
    except EntryNotFound as error:
        raise HTTPException(404, str(error)) from error
    if was_disabled:
        _queue_extension_sync_signal(hash_, "mapping-delete")
    return result


class RenameRequest(BaseModel):
    name: str


@app.put("/entry/{hash_}/name")
def rename_entry(hash_: str, body: RenameRequest):
    """Rename a cache entry's HTML file so its search name (`html.stem`)
    becomes `body.name`. Updates mappings.tsv and rewrites the HTML
    `<title>` so a fresh load shows the new name in the tab.

    Hash is anchored to ^[a-f0-9]{6,32}$ so all path joins stay inside
    CACHE_DIR. 409 if another file in the entry already uses the target
    name; no-op (200 with renamed=False) when the name is unchanged.
    """
    try:
        return catalog.rename(hash_, body.name)
    except InvalidCatalogInput as error:
        raise HTTPException(400, str(error)) from error
    except EntryNotFound as error:
        raise HTTPException(404, str(error)) from error
    except NameConflict as error:
        raise HTTPException(409, str(error)) from error


@app.get("/library")
def library():
    """All cached docs, sorted by zoxide-style frecency. Drives `:open`.

    palette command. Joins mappings.tsv (authoritative source ref) with
    visit-derived frecency metrics. Entries whose on-disk dir is gone are
    dropped.
    """
    return catalog.list_entries()


@app.get("/stats")
def stats():
    s = visits.summary()
    mappings = catalog.mappings()
    for row in s["top"]:
        mapping = mappings.get(row["hash"])
        row["name"] = mapping.name if mapping else row["hash"]
        row["source_ref"] = mapping.source_ref if mapping else None
    return s


@app.get("/stats/recent")
def stats_recent(limit: int = Query(100, ge=1, le=1000)):
    rows = visits.recent(limit)
    mappings = catalog.mappings()
    for row in rows:
        mapping = mappings.get(row["hash"])
        row["name"] = mapping.name if mapping else row["hash"]
        row["source_ref"] = mapping.source_ref if mapping else None
    return rows


# -----------------------------------------------------------------------------
# Static mounts. Registered after routes so /view, /healthz take precedence.
# -----------------------------------------------------------------------------

# Overlay assets — repo-backed so edits to overlay.{css,js} go live on refresh.
# StaticFiles already emits ETag + Last-Modified and honors If-None-Match /
# If-Modified-Since (304). We add a short must-revalidate Cache-Control so the
# browser revalidates promptly instead of using its opaque heuristic freshness
# window — this is what lets stale ?v= HTML self-correct without a hard reload.
class _RevalidatingStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers.setdefault("Cache-Control", "max-age=60, must-revalidate")
        return resp


app.mount("/_assets", _RevalidatingStatic(directory=ASSETS_DIR), name="assets")

# The whole cache. Any /<hash>/<file> request (the URL pdf2html-convert.sh
# navigates Comet to) falls through to this mount. `html=False` prevents
# index.html auto-serve at the root.
app.mount("/", StaticFiles(directory=CACHE_DIR, html=False), name="cache")


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7435)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "main:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
