"""pdf_viewer daemon — read-only FastAPI service over ~/.cache/pdf_viewer/.

Routes:
    GET /view?path=<local>   cached HTML or stream the PDF (miss → native viewer)
    GET /view?url=<remote>   cached HTML or 307 to <remote>  (miss → native viewer)
    GET /_assets/*           overlay.{css,js} from the repo assets dir
    GET /<hash>/<file>       cached pdf2htmlEX bundle (html + any sibling files)
    GET /healthz             liveness probe

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

import hashlib
import pathlib
import urllib.parse
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

CACHE_DIR = pathlib.Path.home() / ".cache" / "pdf_viewer"
REPO_DIR = pathlib.Path("/Users/andersbekkevard/dev/misc/pdf_viewer")
ASSETS_DIR = REPO_DIR / "assets"

app = FastAPI(title="pdf_viewer", version="0.1.0")


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


def first_html(entry_dir: pathlib.Path) -> Optional[pathlib.Path]:
    if not entry_dir.is_dir():
        return None
    matches = sorted(entry_dir.glob("*.html"))
    return matches[0] if matches else None


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

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
    path: Optional[str] = Query(None, description="absolute local path"),
    url: Optional[str] = Query(None, description="http(s) URL"),
):
    if (path is None) == (url is None):
        raise HTTPException(400, "provide exactly one of: path, url")
    if path is not None:
        return _view_path(path)
    assert url is not None
    return _view_url(url)


def _view_path(path: str):
    try:
        p = pathlib.Path(path).expanduser().resolve(strict=True)
    except FileNotFoundError:
        raise HTTPException(404, f"file not found: {path}")
    if not p.is_file():
        raise HTTPException(400, f"not a regular file: {path}")

    entry = CACHE_DIR / content_hash(p)
    html = first_html(entry)
    if html is not None:
        return FileResponse(html, media_type="text/html; charset=utf-8")

    # Cache miss. Chromium blocks http→file: redirects, so we can't 307 to
    # file://. Stream the bytes as application/pdf — browser opens native
    # viewer. User can then run Raycast convert to escalate into HTML.
    return FileResponse(p, media_type="application/pdf", filename=p.name)


PASSTHROUGH_MARKER = "_pdfvw=passthrough"


def _view_url(url: str):
    entry = CACHE_DIR / url_hash(url)
    html = first_html(entry)
    if html is not None:
        return FileResponse(html, media_type="text/html; charset=utf-8")
    # Cache miss: 307 to the original URL, but tag it with a marker so the
    # browser extension's allow-rule short-circuits the redirect match —
    # otherwise clicks on .pdf links would loop (ext redirects → daemon 307s
    # → ext redirects → ...) until Chromium ERR_TOO_MANY_REDIRECTS.
    parsed = urllib.parse.urlparse(url)
    new_query = (f"{parsed.query}&{PASSTHROUGH_MARKER}"
                 if parsed.query else PASSTHROUGH_MARKER)
    passthrough = urllib.parse.urlunparse(parsed._replace(query=new_query))
    return RedirectResponse(passthrough, status_code=307)


# -----------------------------------------------------------------------------
# Static mounts. Registered after routes so /view, /healthz take precedence.
# -----------------------------------------------------------------------------

# Overlay assets — repo-backed so edits to overlay.{css,js} go live on refresh.
app.mount("/_assets", StaticFiles(directory=ASSETS_DIR), name="assets")

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
