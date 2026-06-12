"""pdf_viewer daemon — read-only FastAPI service over ~/.cache/pdf_viewer/.

Routes:
    GET    /view?path=<local>   cached HTML or stream the PDF (miss → native viewer)
    GET    /view?url=<remote>   cached HTML or 307 to <remote>  (miss → native viewer)
    GET    /view-raw?<remote>   same as /view?url=, but preserves raw query strings
    GET    /view-light?...      derived light HTML if present, canonical fallback
    GET    /view-light-raw?...  same as /view-light?url= for raw signed URLs
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
import hashlib
import html as _html
import json
import pathlib
import re
import shutil
import time
import urllib.parse
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import visits

CACHE_DIR = pathlib.Path.home() / ".cache" / "pdf_viewer"
REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_DIR / "assets"
DISABLED_FILE = CACHE_DIR / "disabled.json"

app = FastAPI(title="pdf_viewer", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    visits.init()


# -----------------------------------------------------------------------------
# Hash helpers — must match the bash convert scripts byte-for-byte.
# -----------------------------------------------------------------------------

def url_hash(url: str) -> str:
    """sha256(host + path)[:16] — query stripped so signed URLs collide."""
    p = urllib.parse.urlparse(url)
    return hashlib.sha256(f"{p.netloc}{p.path}".encode()).hexdigest()[:16]


_content_hash_cache: dict[tuple[str, int, int], str] = {}


def content_hash(path: pathlib.Path) -> str:
    """sha256(content)[:16], memoized by (abs_path, mtime_ns, size).

    pdf2html-convert.sh uses `shasum -a 256 <file> | head -c 16`. Streaming
    read keeps memory bounded on 40MB textbooks.
    """
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    cached = _content_hash_cache.get(key)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()[:16]
    _content_hash_cache[key] = digest
    return digest


def _mapped_hash_for_path(path: pathlib.Path) -> Optional[str]:
    """Resolve a cached local PDF by mappings.tsv without reading the PDF.

    Cloud-backed files (OneDrive/iCloud) can throw EDEADLK when read from a
    background daemon while the provider is coordinating the file. For cached
    entries, mappings.tsv is the routing source of truth, so prefer it over
    content hashing.
    """
    try:
        resolved = path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        resolved = path.expanduser()
    needle = str(resolved)
    for hash_, mapping in _load_mappings().items():
        if _strip_passthrough(mapping.get("source_ref", "")) == needle:
            return hash_
    return None


def entry_hash_for_path(path: pathlib.Path) -> Optional[str]:
    mapped = _mapped_hash_for_path(path)
    if mapped:
        return mapped
    try:
        return content_hash(path)
    except OSError:
        return None


LIGHT_HTML_SUFFIX = ".light.html"


def is_light_html(path: pathlib.Path) -> bool:
    return path.name.endswith(LIGHT_HTML_SUFFIX)


def first_html(entry_dir: pathlib.Path) -> Optional[pathlib.Path]:
    """Return the canonical HTML for an entry.

    Light variants are derived cache state. They must not become canonical just
    because they sort before/after the original file.
    """
    if not entry_dir.is_dir():
        return None
    matches = sorted(entry_dir.glob("*.html"))
    canonical = [p for p in matches if not is_light_html(p)]
    if canonical:
        return canonical[0]
    return matches[0] if matches else None


def light_html_for(canonical_html: pathlib.Path) -> pathlib.Path:
    if is_light_html(canonical_html):
        return canonical_html
    return canonical_html.with_name(canonical_html.stem + LIGHT_HTML_SUFFIX)


def preferred_html(entry_dir: pathlib.Path) -> Optional[pathlib.Path]:
    canonical = first_html(entry_dir)
    if canonical is None:
        return None
    light = light_html_for(canonical)
    return light if light.is_file() else canonical


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
    map_file = CACHE_DIR / "mappings.tsv"
    if not map_file.is_file():
        return []
    entries = []
    seen: set[str] = set()
    with map_file.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            _ts, source_ref, hash_, _html_path = parts[:4]
            if hash_ in seen:
                continue
            entry_dir = CACHE_DIR / hash_
            if not entry_dir.is_dir() or not list(entry_dir.glob("*.html")):
                continue

            if source_ref.startswith(("http://", "https://")):
                parsed = urllib.parse.urlparse(source_ref)
                entries.append({
                    "kind": "url",
                    "host": parsed.netloc.lower(),
                    "path": parsed.path,
                    "hash": hash_,
                    "disabled": is_entry_disabled(hash_),
                })
                seen.add(hash_)
            elif source_ref.startswith("/"):
                entries.append({
                    "kind": "file",
                    "path": source_ref,
                    "hash": hash_,
                    "disabled": is_entry_disabled(hash_),
                })
                seen.add(hash_)
    return entries


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
        return _view_path(path, background)
    assert url is not None
    return _view_url(url, background)


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
    return _view_url(url, background)


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


def _view_path(path: str, background: BackgroundTasks, light: bool = False):
    try:
        p = pathlib.Path(path).expanduser().resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(404, f"file not found: {path}")
    if not p.is_file():
        raise HTTPException(400, f"not a regular file: {path}")

    hash_ = entry_hash_for_path(p)
    entry = CACHE_DIR / hash_ if hash_ else None
    html = (
        (preferred_html(entry) if light else first_html(entry))
        if entry is not None else None
    )
    if html is not None:
        assert hash_ is not None
        if is_entry_disabled(hash_):
            return FileResponse(
                p,
                media_type="application/pdf",
                filename=p.name,
                content_disposition_type="inline",
            )
        background.add_task(visits.record, hash_, "path")
        return FileResponse(html, media_type="text/html; charset=utf-8")

    # Cache miss. Chromium blocks http→file: redirects, so we can't 307 to
    # file://. Stream the bytes as application/pdf — browser opens native
    # viewer. User can then run Raycast convert to escalate into HTML.
    return FileResponse(
        p,
        media_type="application/pdf",
        filename=p.name,
        content_disposition_type="inline",
    )


PASSTHROUGH_MARKER = "_pdfvw=passthrough"


def _with_passthrough_marker(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(k == "_pdfvw" and v == "passthrough" for k, v in pairs):
        return url
    new_query = (f"{parsed.query}&{PASSTHROUGH_MARKER}"
                 if parsed.query else PASSTHROUGH_MARKER)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _view_url(url: str, background: BackgroundTasks, light: bool = False):
    entry = CACHE_DIR / url_hash(url)
    html = preferred_html(entry) if light else first_html(entry)
    if html is not None:
        if is_entry_disabled(entry.name):
            return RedirectResponse(
                _with_passthrough_marker(_strip_passthrough(url)),
                status_code=307,
            )
        background.add_task(visits.record, entry.name, "url")
        return FileResponse(html, media_type="text/html; charset=utf-8")
    # Cache miss: 307 to the original URL, but tag it with a marker so the
    # browser extension's allow-rule short-circuits the redirect match —
    # otherwise clicks on .pdf links would loop (ext redirects → daemon 307s
    # → ext redirects → ...) until Chromium ERR_TOO_MANY_REDIRECTS.
    return RedirectResponse(_with_passthrough_marker(url), status_code=307)


# -----------------------------------------------------------------------------
# Visit stats — reflective views over visits.db. Read-only; not on hot path.
# -----------------------------------------------------------------------------

def _load_mappings() -> dict[str, dict[str, str]]:
    """hash → {source_ref, name}. One scan per request; file is small."""
    out: dict[str, dict[str, str]] = {}
    map_file = CACHE_DIR / "mappings.tsv"
    if not map_file.is_file():
        return out
    with map_file.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            _ts, source_ref, hash_, html_path = parts[:4]
            out[hash_] = {
                "source_ref": source_ref,
                "name": pathlib.Path(html_path).stem if html_path else hash_,
            }
    return out


def _normalized_search_text(*parts: Optional[str]) -> str:
    text = " ".join(p for p in parts if p)
    text = urllib.parse.unquote(text)
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _library_search_text(name: str, source_ref: Optional[str]) -> str:
    """Search text for `:open`: clean name plus source path/URL context."""
    parts = [name]
    if source_ref:
        parsed = urllib.parse.urlparse(source_ref)
        if parsed.scheme in {"http", "https"}:
            parts.append(parsed.netloc)
            parts.append(parsed.path)
            parts.append(pathlib.PurePosixPath(parsed.path).name)
        else:
            parts.append(source_ref)
            parts.append(pathlib.Path(source_ref).name)
            parts.append(str(pathlib.Path(source_ref).parent))
    return _normalized_search_text(*parts)


_HASH_RE = re.compile(r"^[a-f0-9]{6,32}$")


def _strip_passthrough(url: str) -> str:
    """Remove every `_pdfvw=passthrough` param from a URL's query string.

    Pre-existing convert.sh bug: AppleScript reads the active Comet tab's URL
    *after* the daemon's first 307, so source_refs in mappings.tsv have the
    marker baked in. Redirecting straight to that URL trips the allow/redirect
    race and stacks markers, so we sanitize on the way out.
    """
    parsed = urllib.parse.urlparse(url)
    if not parsed.query:
        return url
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    cleaned = [(k, v) for k, v in pairs if not (k == "_pdfvw" and v == "passthrough")]
    new_query = urllib.parse.urlencode(cleaned)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def _load_disabled_hashes() -> set[str]:
    try:
        data = json.loads(DISABLED_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, dict):
        values = data.get("disabled", [])
    elif isinstance(data, list):
        values = data
    else:
        values = []
    return {
        str(v)
        for v in values
        if isinstance(v, str) and _HASH_RE.match(v)
    }


def _write_disabled_hashes(hashes: set[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DISABLED_FILE.with_suffix(DISABLED_FILE.suffix + ".tmp")
    payload = {"disabled": sorted(hashes)}
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(DISABLED_FILE)


def is_entry_disabled(hash_: str) -> bool:
    return hash_ in _load_disabled_hashes()


def set_entry_disabled(hash_: str, disabled: bool) -> bool:
    if not _HASH_RE.match(hash_):
        raise HTTPException(400, "invalid hash")
    hashes = _load_disabled_hashes()
    before = hash_ in hashes
    if disabled:
        hashes.add(hash_)
    else:
        hashes.discard(hash_)
    if (hash_ in hashes) != before:
        _write_disabled_hashes(hashes)
    return hash_ in hashes


def _entry_source_ref(hash_: str) -> Optional[str]:
    mapping = _load_mappings().get(hash_)
    if not mapping:
        return None
    source_ref = mapping.get("source_ref")
    return _strip_passthrough(source_ref) if source_ref else None


def _entry_html(hash_: str, *, preferred: bool = True) -> Optional[pathlib.Path]:
    entry_dir = CACHE_DIR / hash_
    return preferred_html(entry_dir) if preferred else first_html(entry_dir)


def _require_cached_entry(hash_: str) -> pathlib.Path:
    if not _HASH_RE.match(hash_):
        raise HTTPException(400, "invalid hash")
    html = _entry_html(hash_)
    if html is None:
        raise HTTPException(404, f"no cached PDF viewer entry for hash {hash_}")
    return html


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _viewer_url_for_hash(hash_: str, request: Request) -> str:
    html = _require_cached_entry(hash_)
    return f"{_base_url(request)}/{hash_}/{urllib.parse.quote(html.name)}"


def _file_url_for_path(path: str) -> str:
    return pathlib.Path(path).expanduser().resolve().as_uri()


def _native_browser_url_for_hash(hash_: str, request: Request) -> str:
    _require_cached_entry(hash_)
    source_ref = _entry_source_ref(hash_)
    if source_ref and source_ref.startswith("/"):
        return _file_url_for_path(source_ref)
    if source_ref and source_ref.startswith(("http://", "https://")):
        return _with_passthrough_marker(source_ref)
    return _native_url_for_hash(hash_, request)


def _native_url_for_hash(hash_: str, request: Request) -> str:
    _require_cached_entry(hash_)
    return f"{_base_url(request)}/native?hash={urllib.parse.quote(hash_)}"


def _cached_source_pdf(hash_: str) -> Optional[pathlib.Path]:
    source_dir = CACHE_DIR / hash_ / "_source"
    if not source_dir.is_dir():
        return None
    matches = sorted(source_dir.glob("*.pdf"))
    return matches[0] if matches else None


def _local_path_from_file_url(url: str) -> pathlib.Path:
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    return pathlib.Path(path).expanduser()


def _hash_for_local_path(path: pathlib.Path) -> Optional[str]:
    mapped = _mapped_hash_for_path(path)
    if mapped:
        return mapped
    try:
        resolved = path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        return None
    if not resolved.is_file():
        return None
    try:
        return content_hash(resolved)
    except OSError:
        return None


def _daemon_host(parsed: urllib.parse.ParseResult) -> bool:
    if parsed.scheme not in {"http", "https"}:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return (parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            and port == 7435)


def _hash_for_browser_url(url: str) -> Optional[str]:
    clean_url = _strip_passthrough(url)
    parsed = urllib.parse.urlparse(clean_url)

    if _daemon_host(parsed):
        match = re.match(r"^/([a-f0-9]{6,32})(?:/|$)", parsed.path)
        if match:
            return match.group(1)

        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path == "/native":
            hash_arg = query.get("hash", [None])[0]
            if hash_arg and _HASH_RE.match(hash_arg):
                return hash_arg
        if parsed.path in {"/view", "/view-light", "/native"}:
            path_arg = query.get("path", [None])[0]
            url_arg = query.get("url", [None])[0]
            if path_arg:
                return _hash_for_local_path(pathlib.Path(path_arg))
            if url_arg:
                return url_hash(_strip_passthrough(url_arg))
        if parsed.path in {"/view-raw", "/view-light-raw"} and parsed.query:
            return url_hash(_strip_passthrough(parsed.query))

    if parsed.scheme == "file":
        return _hash_for_local_path(_local_path_from_file_url(clean_url))
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url_hash(clean_url)
    return None


def _native_response_for_hash(hash_: str):
    _require_cached_entry(hash_)
    source_ref = _entry_source_ref(hash_)
    if source_ref and source_ref.startswith("/"):
        path = pathlib.Path(source_ref).expanduser()
        if not path.is_file():
            raise HTTPException(404, f"source PDF not found: {source_ref}")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=path.name,
            content_disposition_type="inline",
        )

    cached_pdf = _cached_source_pdf(hash_)
    if cached_pdf is not None:
        return FileResponse(
            cached_pdf,
            media_type="application/pdf",
            filename=cached_pdf.name,
            content_disposition_type="inline",
        )

    if source_ref and source_ref.startswith(("http://", "https://")):
        return RedirectResponse(_with_passthrough_marker(source_ref), status_code=307)

    raise HTTPException(404, f"no native PDF source for hash {hash_}")


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
    cached_pdf = _cached_source_pdf(hash_for_url)
    if cached_pdf is not None:
        return FileResponse(
            cached_pdf,
            media_type="application/pdf",
            filename=cached_pdf.name,
            content_disposition_type="inline",
        )
    return RedirectResponse(_with_passthrough_marker(url), status_code=307)


class DisabledRequest(BaseModel):
    disabled: bool
    current_url: Optional[str] = None


@app.put("/entry/{hash_}/disabled")
def update_entry_disabled(hash_: str, body: DisabledRequest, request: Request):
    _require_cached_entry(hash_)
    disabled = set_entry_disabled(hash_, body.disabled)
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
    hash_ = _hash_for_browser_url(body.url)
    if not hash_:
        raise HTTPException(404, "could not resolve current tab to a cached PDF")
    _require_cached_entry(hash_)

    disabled = set_entry_disabled(hash_, not is_entry_disabled(hash_))
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
    if not _HASH_RE.match(hash_):
        raise HTTPException(400, "invalid hash")

    map_file = CACHE_DIR / "mappings.tsv"
    source_ref: Optional[str] = None
    mapping_dropped = False
    if map_file.is_file():
        kept: list[str] = []
        with map_file.open(encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4 and parts[2] == hash_:
                    source_ref = _strip_passthrough(parts[1])
                    mapping_dropped = True
                    continue
                kept.append(line if line.endswith("\n") else line + "\n")
        if mapping_dropped:
            tmp = map_file.with_suffix(map_file.suffix + ".tmp")
            tmp.write_text("".join(kept), encoding="utf-8")
            tmp.replace(map_file)

    entry_dir = CACHE_DIR / hash_
    removed_dir = False
    if entry_dir.is_dir():
        # Resolve and re-check parent to defend against symlink shenanigans.
        resolved = entry_dir.resolve()
        if resolved.parent == CACHE_DIR.resolve():
            shutil.rmtree(resolved, ignore_errors=True)
            removed_dir = not resolved.exists()

    visits_deleted = visits.forget(hash_)
    was_disabled = is_entry_disabled(hash_)
    set_entry_disabled(hash_, False)
    if was_disabled:
        _queue_extension_sync_signal(hash_, "mapping-delete")

    if not (mapping_dropped or removed_dir):
        raise HTTPException(404, f"no cache entry for hash {hash_}")

    return {
        "hash": hash_,
        "source_ref": source_ref,
        "mapping_dropped": mapping_dropped,
        "removed_dir": removed_dir,
        "visits_deleted": visits_deleted,
        "disabled": False,
    }


class RenameRequest(BaseModel):
    name: str


_NAME_MAX_LEN = 200


def _sanitize_name(raw: str) -> str:
    """Filename stem from user input. Drop a trailing `.html`, replace path
    separators / control chars with `-`, strip leading dots, cap length.
    Returns '' if nothing usable remains.
    """
    s = (raw or "").strip()
    if s.lower().endswith(".html"):
        s = s[:-5].rstrip()
    s = re.sub(r"[\x00-\x1f/\\]+", "-", s).lstrip(".").strip()
    return s[:_NAME_MAX_LEN]


@app.put("/entry/{hash_}/name")
def rename_entry(hash_: str, body: RenameRequest):
    """Rename a cache entry's HTML file so its search name (`html.stem`)
    becomes `body.name`. Updates mappings.tsv and rewrites the HTML
    `<title>` so a fresh load shows the new name in the tab.

    Hash is anchored to ^[a-f0-9]{6,32}$ so all path joins stay inside
    CACHE_DIR. 409 if another file in the entry already uses the target
    name; no-op (200 with renamed=False) when the name is unchanged.
    """
    if not _HASH_RE.match(hash_):
        raise HTTPException(400, "invalid hash")
    new_name = _sanitize_name(body.name)
    if not new_name:
        raise HTTPException(400, "name is empty after sanitization")

    entry_dir = CACHE_DIR / hash_
    if not entry_dir.is_dir():
        raise HTTPException(404, f"no cache entry for hash {hash_}")
    html = first_html(entry_dir)
    if html is None:
        raise HTTPException(404, f"no html in entry {hash_}")

    old_stem = html.stem
    if old_stem == new_name:
        light = light_html_for(html)
        return {
            "hash": hash_,
            "old_name": old_stem,
            "new_name": new_name,
            "renamed": False,
            "href": f"/{hash_}/{html.name}",
            "canonical_href": f"/{hash_}/{html.name}",
            "light_href": f"/{hash_}/{light.name}" if light.is_file() else None,
        }

    new_path = entry_dir / (new_name + ".html")
    new_light_path = entry_dir / (new_name + LIGHT_HTML_SUFFIX)
    if new_path.exists() or new_light_path.exists():
        raise HTTPException(409, f"name already in use: {new_name}")

    def rewrite_title(path: pathlib.Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
            new_text, n = re.subn(
                r"<title>.*?</title>",
                f"<title>{_html.escape(new_name)}</title>",
                text, count=1, flags=re.DOTALL,
            )
            if n:
                path.write_text(new_text, encoding="utf-8")
        except OSError:
            pass

    # Rewrite <title> in place so the next fresh load shows the new name
    # in the browser tab. The overlay also patches document.title live, so
    # the current tab updates without a reload.
    rewrite_title(html)
    old_light_path = light_html_for(html)
    light_renamed = False
    if old_light_path.is_file():
        rewrite_title(old_light_path)
        old_light_path.rename(new_light_path)
        light_renamed = True

    html.rename(new_path)

    map_file = CACHE_DIR / "mappings.tsv"
    if map_file.is_file():
        new_html_path = str(new_path)
        kept: list[str] = []
        with map_file.open(encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 4 and parts[2] == hash_:
                    parts[3] = new_html_path
                    kept.append("\t".join(parts) + "\n")
                else:
                    kept.append(line if line.endswith("\n") else line + "\n")
        tmp = map_file.with_suffix(map_file.suffix + ".tmp")
        tmp.write_text("".join(kept), encoding="utf-8")
        tmp.replace(map_file)

    # One-off frecency bump: a rename is a strong "I curated this entry"
    # signal, but only the first time. Subsequent renames return 0 so
    # ten edits don't stack to 10× the score. Three effective opens =
    # +12 score now, decaying naturally to +3 after a day.
    boosted = visits.boost(hash_, n=3)

    return {
        "hash": hash_,
        "old_name": old_stem,
        "new_name": new_name,
        "renamed": True,
        "href": f"/{hash_}/{new_path.name}",
        "canonical_href": f"/{hash_}/{new_path.name}",
        "light_href": f"/{hash_}/{new_light_path.name}" if light_renamed else None,
        "light_renamed": light_renamed,
        "frecency_boosted": boosted,
    }


@app.get("/library")
def library():
    """All cached docs, sorted by zoxide-style frecency. Drives `:open`.

    palette command. Joins mappings.tsv (authoritative source ref) with
    visit-derived frecency metrics. Entries whose on-disk dir is gone are
    dropped.
    """
    mappings = _load_mappings()
    scores = visits.all_frecency()
    out = []
    for hash_, m in mappings.items():
        entry_dir = CACHE_DIR / hash_
        html = first_html(entry_dir)
        if html is None:
            continue
        light = light_html_for(html)
        v = scores.get(hash_, {
            "raw_count": 0,
            "rank": 0,
            "last_seen": None,
            "age_multiplier": 0.0,
            "frecency_score": 0.0,
        })
        name = html.stem
        source_ref = m.get("source_ref")
        out.append({
            "hash": hash_,
            "name": name,
            "source_ref": source_ref,
            "search_text": _library_search_text(name, source_ref),
            "href": f"/{hash_}/{html.name}",
            "canonical_href": f"/{hash_}/{html.name}",
            "light_href": f"/{hash_}/{light.name}" if light.is_file() else None,
            "count": v["raw_count"],
            "rank": v["rank"],
            "last_seen": v["last_seen"],
            "age_multiplier": v["age_multiplier"],
            "frecency_score": v["frecency_score"],
        })
    out.sort(key=lambda e: (
        -e["frecency_score"],
        -(e["last_seen"] or 0),
        e["name"].lower(),
    ))
    return out


@app.get("/stats")
def stats():
    s = visits.summary()
    mappings = _load_mappings()
    for row in s["top"]:
        m = mappings.get(row["hash"], {})
        row["name"] = m.get("name", row["hash"])
        row["source_ref"] = m.get("source_ref")
    return s


@app.get("/stats/recent")
def stats_recent(limit: int = Query(100, ge=1, le=1000)):
    rows = visits.recent(limit)
    mappings = _load_mappings()
    for row in rows:
        m = mappings.get(row["hash"], {})
        row["name"] = m.get("name", row["hash"])
        row["source_ref"] = m.get("source_ref")
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
