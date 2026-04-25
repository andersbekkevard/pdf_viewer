# Cache design

The cache is the load-bearing piece of `pdf_viewer`. Conversion is slow
(Docker + pdf2htmlEX on Rosetta-emulated amd64, 1–2 min for a textbook);
every subsequent read is an instant disk hit. This doc captures the
decisions behind the cache — things that aren't obvious from reading the
code.

## Location

`~/.cache/pdf_viewer/` — deliberately different from the retired
hardcoded script's `~/.cache/pdf2html-serve/`, which is preserved intact
as an A/B reference and must not be touched.

## Layout

```
~/.cache/pdf_viewer/
├── _assets              → symlink to pdf_viewer/assets/ (served at /_assets/*)
├── log                  timestamped convert / download / server events
├── mappings.tsv         pdf-source ↔ hash ↔ html-path index (grep-friendly)
├── visits.db            SQLite event log (hash, ts, kind) — see below
├── <hash>/              one dir per unique document
│   ├── <stem>.html      the injected HTML (served to browser)
│   ├── <stem>.outline.js + fonts/images/...  pdf2htmlEX output assets
│   ├── _source/         downloaded source PDF (remote) or none (local)
│   │   └── document.pdf
│   ├── meta.json        source URL/path, display name, timestamps
│   └── text.json        per-page plain text for native Cmd-F shadow indexing
└── ...
```

`_assets/` being a symlink back into the repo is what lets overlay edits
go live on ⌘⇧R without reconverting anything.

## Hash keys

Two different algorithms, picked deliberately:

- **Local PDF**: `sha256(path + mtime + size)[:16]`. Fast — no read of
  the PDF bytes. Trade-off: moving or renaming a file invalidates the
  cache entry. Accepted because bulk-indexing (which *does* content-hash
  to dedupe renames) is the common entry point for local PDFs.
- **Remote PDF**: `sha256(host + path)[:16]`. **Query string stripped
  entirely.** This is what makes signed URLs (Blackboard, S3,
  CloudFront, Azure, GCS) hit cache across sessions — the path carries
  the stable document ID, the query string carries only ephemeral auth
  state.

The `index-directory.sh` path is a special case: it content-hashes the
PDF bytes so that the same book under two filenames dedupes to one
cache entry.

## URL normalization

Stripped as ephemeral:
- All `X-Amz-*` params
- `X-Blackboard-*` params
- `X-Goog-*` params
- `Expires`, `Signature`, `response-cache-control`,
  `response-content-disposition`, `response-content-type`

Kept as cache-key basis: **host + path only**.

## Display filename (remote PDFs)

Resolution order:
1. Parse `response-content-disposition` query param (often contains the
   real filename, e.g. `filename*=UTF-8''sqlite(1).pdf`).
2. Fall back to the last path segment, append `.pdf` if missing.
3. Last resort: the hash itself.

## Cache-miss behavior

The daemon (`daemon/main.py`) is read-only and never invokes Docker
(ADR 0004). Miss handling:

- `GET /view?url=<remote>` and the extension-only
  `GET /view-raw?<remote>` → **307 to the original URL**. `/view-raw`
  reads the entire raw query string as the remote URL so signed URLs with
  `&` parameters are not split into daemon query params. Browser opens the
  native PDF viewer on miss (degraded but present). User escalates to HTML
  by running Raycast-convert; next visit of the same doc hits cache.
- `GET /view?path=<local>` → **streams PDF bytes as
  `application/pdf`**. A 307 to `file://` would work in the native
  viewer but Chromium blocks http→file redirects, so we stream
  instead.

## Visit tracking

`daemon/visits.py` maintains `visits.db` (SQLite, WAL mode,
`synchronous=NORMAL`). Every `/view` cache hit inserts one row
`(hash, ts, kind)` via a FastAPI `BackgroundTask` — off the response
path, so a broken DB can never break serving. Aggregates computed at
query time; personal-use volume keeps the events table tiny for years.

Powers `/stats`, `/stats/recent`, and the visits-sorted library picker
behind `⌘K` / `:open`.

## Find text

`text.json` is extracted from the cached pdf2htmlEX HTML, not the source PDF.
The overlay mounts it as a clipped per-page shadow layer so native browser
`Cmd-F` can index the full document without toggling render-all. Existing
entries can be backfilled without Docker:

```bash
scripts/upgrade-cache.sh --mode=text
```

**LRU eviction is deliberately not implemented.** Add a
`scripts/prune-cache.sh --keep N` when cache bloat actually becomes a
problem. Scary work belongs in Raycast scripts, not the daemon
(ADR 0004).

## Deletion

- **Single entry**: `trash ~/.cache/pdf_viewer/<hash>/` and remove the
  matching row from `mappings.tsv`.
- **Everything**: `trash ~/.cache/pdf_viewer/`. Lose nothing
  irreplaceable; next open re-converts.

## Memoization

The daemon memoizes content-hash lookups by `(path, mtime_ns, size)`,
so repeat requests on a 40 MB textbook re-hash exactly once per daemon
process lifetime.
