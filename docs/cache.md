# Cache design

The cache is the load-bearing piece of `pdf_viewer`. Conversion is slow
(native arm64 pdf2htmlEX, up to ~1–2 min for a textbook; see ADR 0011);
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
├── disabled.json        per-hash custom-viewer disable list
├── visits.db            SQLite event log (hash, ts, kind) — see below
├── <hash>/              one dir per unique document
│   ├── <stem>.html      canonical injected pdf2htmlEX HTML
│   ├── <stem>.light.html
│   │                    derived viewer HTML served by default when present
│   ├── page-images/     externalized full-page rasters for .light.html
│   ├── <stem>.outline.js + fonts/images/...  pdf2htmlEX output assets
│   ├── _source/         downloaded source PDF (remote) or none (local)
│   │   └── document.pdf
│   └── meta.json        pdfinfo fields + conversion provenance (see below)
└── ...
```

`_assets/` being a symlink back into the repo is what lets overlay edits
go live on ⌘⇧R without reconverting anything.

## Canonical vs light HTML

The cache keeps the original pdf2htmlEX output as `<stem>.html`. That file is
the rollback path and the exact text-layout reference. `mappings.tsv` always
points at this canonical file.

When experimental light generation is explicitly enabled, conversions can also
build `<stem>.light.html`:

- full-page raster images are extracted from base64 `data:` URLs into
  `page-images/0001.png`, `0002.png`, ...
- page `<img class="bi">` tags carry `data-pdf2html-src` and only nearby
  pages get a live `src`;
- pdf2htmlEX's glyph-heavy text span DOM is collapsed to one transparent,
  searchable text node per page.

The daemon's `/view-light` and `/view-light-raw` routes serve the light file
when it exists and fall back to canonical HTML when it does not. `/view` and
`/view-raw` remain canonical routes. `scripts/upgrade-cache.sh --mode=light`
is guarded behind `PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT=1` until the known
resolution/search/selection bugs are fixed; it must not be used for broad cache
migration before that.

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

## meta.json: pdfinfo fields + provenance

`<hash>/meta.json` carries two clearly-separated groups of keys, written by
two different owners that **merge** rather than overwrite, so either can run
first and neither clobbers the other:

- **pdfinfo-derived fields** (owner: `scripts/extract-meta.py`, driven by
  `scripts/extract-pdf-meta.sh`): `title`, `author`, `subject`, `keywords`,
  `producer`, `creator`, `pages`, `year`, `created`, `file_size`. Missing
  fields are omitted, not null. A re-run refreshes these and preserves
  everything else.
- **`provenance`** (owner: the *pipeline* — `scripts/write-provenance.py`,
  called from `pdf2html-convert.sh`, both indexers, and `upgrade-cache.sh
  --mode=reconvert`): records which converter produced the HTML.

```jsonc
{
  "pages": 1137,            // pdfinfo-derived
  "file_size": 14190884,
  "provenance": {           // pipeline-derived
    "converter": "native-arm64",   // or "docker-amd64"
    "pdf2htmlex": "0.18.8.rc2",
    "poppler": "24.06.1",          // 0.89.0 for the Docker era
    "converted_at": "2026-06-12",  // ISO date; live conversions only
    "overlay_version": 25,         // OVERLAY_VERSION at injection time
    "backfilled": true             // present only on backfilled entries
  }
}
```

Versions are parsed from the binary at convert time (`pdf2htmlEX --version`),
so reconversions after a toolchain upgrade stay accurate.

`scripts/backfill-provenance.sh` is a one-shot that stamped provenance into
every pre-existing entry using a documented date heuristic: everything cached
before **2026-06-12** is `docker-amd64` (poppler 0.89.0), with the native
2026-06-12 migration entries (hash `aa899dbceecd0cfb` plus any row timestamped
`2026-06-12` in `mappings.tsv`) marked `native-arm64`. Backfilled entries
carry `"backfilled": true` and no `converted_at`. The backfill writes only
`meta.json` and never touches HTML or any other cache file; it is idempotent
(skips entries that already have a `provenance` object).

Answer "which entries are Docker-era" in one command:

```bash
rg -l '"converter": "docker-amd64"' ~/.cache/pdf_viewer/*/meta.json
```

## Cache-miss behavior

The daemon (`daemon/main.py`) is read-only and never invokes Docker
(ADR 0004). Miss handling:

- `GET /view?url=<remote>` / `GET /view-light?url=<remote>` and the
  extension-only `GET /view-raw?<remote>` /
  `GET /view-light-raw?<remote>` → **307 to the original URL** on miss.
  The `*-raw` routes read the entire raw query string as the remote URL so
  signed URLs with `&` parameters are not split into daemon query params.
  Browser opens the native PDF viewer on miss (degraded but present). User
  escalates to HTML by running Raycast-convert; next visit of the same doc
  hits cache.
- `GET /view?path=<local>` → **streams PDF bytes as
  `application/pdf`**. A 307 to `file://` would work in the native
  viewer but Chromium blocks http→file redirects, so we stream
  instead.

## Native fallback / disabled entries

`disabled.json` stores a sorted list of cache-entry hashes whose source PDFs
should bypass the custom HTML viewer. The `:disable` / `:native` palette
command marks the current hash disabled and opens `GET /native?hash=<hash>`,
which serves the source PDF as `application/pdf` when available. For local PDFs
that streams the original file. For remote PDFs it prefers the cached
`_source/*.pdf`; if no cached source exists, it redirects to the original URL
with the `_pdfvw=passthrough` marker.

The extension reads the same state from `/cache-urls`. Active entries install
redirect rules; disabled entries install higher-priority allow rules so future
clicks stay in Chrome/Comet's native PDF viewer. The daemon also honors
disabled state inside `/view*`, so stale extension rules cannot force a
disabled PDF back into the custom viewer.

## Visit tracking

`daemon/visits.py` maintains `visits.db` (SQLite, WAL mode,
`synchronous=NORMAL`). Every `/view` cache hit inserts one row
`(hash, ts, kind)` via a FastAPI `BackgroundTask` — off the response
path, so a broken DB can never break serving. Aggregates computed at
query time; personal-use volume keeps the events table tiny for years.

Powers `/stats`, `/stats/recent`, and the visits-sorted library picker
behind `⌘K` / `:open`.

## Find text

Native browser `Cmd-F` indexes the full document because `.pf` carries
`content-visibility: auto` (see ADR 0009): off-viewport pages skip paint
and layout but their text stays in the DOM. No per-document index file is
generated or fetched; `text.json` files in older cache entries are
orphaned and can be deleted at leisure.

Light HTML changes the text granularity, not the browser-find mechanism:
each page has one transparent DOM text node, so native `Cmd-F` and copy still
operate on real DOM text while avoiding millions of pdf2htmlEX glyph spans.
For exact line-level text boxes, use the canonical `<stem>.html` route.

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
