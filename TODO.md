# pdf_viewer — TODO

Roadmap for extending this beyond the phase-1 clean extract.
Items roughly ordered: most immediate → most ambitious.

## Phase 2 — retrofit script for cached HTMLs

When the overlay format changes (new feature, renamed class, etc.), every
already-converted HTML under `~/.cache/pdf_viewer/<hash>/` still points at
`/_assets/overlay.{css,js}?v=N` and picks up the new overlay on next reload —
but only the asset files changed, not the HTML wrappers themselves.

Need a script that can:

- **Mode A — re-inject overlay tags only.** Walk every cached HTML, strip
  existing `<link id="pdf2html-overlay-css">` and `<script id="pdf2html-overlay-js">`
  tags, re-inject fresh ones (with bumped `?v=`). Cheap — no PDF re-conversion.
  Use when you only change `overlay.js` / `overlay.css` shape, or the injection
  template (title, favicon, etc.).
- **Mode B — full re-convert.** Re-run `pdf2htmlEX` from scratch against the
  original PDF (read from `mappings.tsv`). Use when something structural about
  the HTML output needs to change.

Rough interface:

```
pdf_viewer/scripts/upgrade-cache.sh --mode=inject     # mode A
pdf_viewer/scripts/upgrade-cache.sh --mode=reconvert  # mode B, slow
```

## Phase 3 — bulk indexing

`pdf_viewer/scripts/index-directory.sh <dir>` — recursively finds every `*.pdf`
under `<dir>` and runs the conversion, skipping anything already cached.
Idempotent. Intended usage: point at `~/OneDrive/.../Bøker/Pensum/` once to
warm the cache for every textbook you own.

## Phase 4 — FastAPI daemon

Replace the shell script + `python -m http.server` with a proper daemon:

- `server/main.py` — FastAPI app on :7435
- Routes:
  - `GET /view?path=<local>` / `GET /view?url=<https>` — serves cached HTML
    if present; otherwise 307-redirects to the original URL (local PDF in
    Comet's native viewer, or the remote URL directly).
  - `POST /convert?path=…` / `POST /convert?url=…` — runs `pdf2htmlEX`,
    caches, returns 302 to `/view`. Requires Docker running.
  - `POST /index?dir=…` — bulk convert all PDFs under a directory.
- Cache layout unchanged: `~/.cache/pdf_viewer/<hash>/index.html` plus
  sibling metadata (`meta.json` with original filename, source URL, etc.).
- URL cache key: `sha256(host + path)` — drops the query string entirely so
  signed S3/Blackboard URLs with rotating signatures still hit cache.
- Local cache key: `sha256(path + mtime + size)`.

Raycast scripts collapse to two-liners that POST to the daemon.

## Phase 5 — launchd autostart

`launchd/com.anders.pdf_viewer.plist` keeps the daemon alive on login.
`KeepAlive = true` so unexpected crashes restart within a second.

## Phase 6 — browser extension (Comet/Chromium MV3)

Two files:

- `extension/manifest.json`
- `extension/rules.json` — `declarativeNetRequest` rule that redirects any
  `*.pdf$` URL to `http://localhost:7435/view?url=<original>`.

`file://` URLs aren't catchable by `declarativeNetRequest`, so those keep
going through the Raycast script (now a thin wrapper that calls the daemon).

Non-goal: smart detection of PDFs served without `.pdf` suffix (Blackboard's
signed URLs, etc.). Those we convert via explicit Raycast trigger; once
cached, next visit hits the cache.

## Phase 7 — visit tracking

FastAPI makes this trivial. On every `/view` cache hit, increment a counter
in a small SQLite DB. Eventually drives:

- "most-read PDFs" list
- LRU cache eviction when disk bloat becomes real
- Personal stats ("which textbooks am I actually using")

Don't implement until it's needed. ~30 lines when we do.

## Phase 8 — mobile/cross-device (maybe)

Daemon bound to `0.0.0.0` behind Tailscale — read textbooks on iPad from
the same cache. Depends on how much we end up using this. Defer.

## Tiny ideas

- Dark-mode toggle on the page-container background (`#282828` ↔ `#f5f5dc` etc.)
- Export current selection as markdown (annotated reading)
- Per-document notes panel (persisted alongside the cache entry)
- Clickable outline chapters in the cheatsheet
