# pdf_viewer — plan of record

Single source of truth for this project. If a future session is unsure what to
build or what was decided, read this first.

**Repo**: `/Users/andersbekkevard/dev/misc/pdf_viewer/`
**Cache**: `~/.cache/pdf_viewer/` — all converted HTML + source PDFs live here
**Port**: `7435` (local http.server; eventually FastAPI daemon)
**Raycast entrypoint (convert)**: `/Users/andersbekkevard/dev/misc/raycast_scripts/other/pdf-viewer-convert.sh`
**Old hardcoded scripts** (kept for A/B reference, DO NOT delete):
- `raycast_scripts/other/pdf2html-convert.sh` (original)

---

## 0. Problem statement

Vimium — the vim-style keyboard navigation extension we rely on for
everything in Comet — **does not work inside Chrome/Comet's native PDF
viewer**. The native viewer is a sandboxed `chrome://pdf` surface that
browser extensions cannot reach. No `j/k` scroll, no `/` find, no visual
mode, no marks. For a keyboard-native workflow, the native PDF viewer is
unusable.

The workaround is to render PDFs as **HTML documents** instead, because
Vimium works natively on any HTML page. Tool of choice: `pdf2htmlEX` —
converts a PDF to pixel-faithful HTML while preserving selectable text.
That gives us feature parity with the PDF visually, plus everything
Vimium does.

**But out-of-the-box pdf2htmlEX output is rough**: dotted retro sidebar,
serif fonts, jittery scroll behavior, no page counter, no reading-mode
niceties. So the product has two axes:

1. **Customize the HTML** until it's the ideal reading surface — dark
   canvas, clean sidebar, render-window control, cursor-pin scrolling,
   outline active tracking, command palette, page counter, etc.
   (Phase 1 done — all of this already lives in `assets/overlay.{js,css}`.)

2. **Make getting into that HTML frictionless** — click any PDF link and
   end up in the custom viewer, with no manual step after first-ever use
   of a given document.

Two mechanisms solve axis 2:

- **Cache (compute-cheap)**: conversion is slow (Docker + pdf2htmlEX on
  Rosetta-emulated amd64, 1–2 min per textbook). Convert **once**, cache
  the HTML output forever. Subsequent opens of the same document are
  pure disk reads.
- **Extension (friction-cheap)**: Comet MV3 redirect rule sends `.pdf$`
  URLs to `http://localhost:7435/view?url=…`. The daemon does the cache
  lookup. On hit → HTML viewer. On miss → 307 back to the original URL,
  browser opens it in the native viewer (unusable but at least present).
  User then decides: "I want this in HTML" → Raycast shortcut triggers
  conversion (Docker must be running for this step); next visit hits cache.

Net effect once fully built:

| Scenario | What happens |
|---|---|
| First time we see a PDF | Native viewer opens (degraded UX, but not broken) |
| User runs Raycast convert | Docker runs, conversion, cache populated |
| All future visits to same doc | Instant HTML viewer, no Docker needed |
| Known-cached docs clicked | Instant HTML viewer, no user action needed |

Docker is the only heavy component. It sits off 23 hours a day; the user
starts it manually before the rare "I want to convert a batch" sessions.

---

## 1. Vision

Open any PDF — local file, online URL, signed link — in a custom HTML viewer
automatically, with vim-friendly navigation, persistent state, and a
docker-on-demand conversion pipeline that never runs unless we ask for it.

End state: click a PDF link anywhere → lands in custom viewer. No thinking.
First-open converts once; every subsequent open is an instant cache hit.

### The two Raycast shortcuts (user-facing interface)

1. **`pdf-viewer-convert`** — converts the PDF corresponding to the current
   Comet tab. Accepts both `file://` paths and `https://` URLs (including
   signed Blackboard/S3 URLs). URL is normalized (strip query), hashed,
   cached. Requires Docker running. Already exists for `file://`; phase 1.5
   adds `https://`.

2. **`pdf-viewer-index-directory`** (phase 3) — prompts for a folder path,
   recursively finds every `*.pdf` under it, converts each, skips already-cached.
   Idempotent. The "warm the cache for all my textbooks in one go" button.
   Requires Docker running.

No other user-facing commands. The browser extension handles everything
else transparently.

---

## 2. Current state (phases 1, 1.5, 2, 3, 4, 5, 6, 7 done)

**What works:**
- Overlay extracted to proper files:
  - `assets/overlay.css` (sectioned, comments)
  - `assets/overlay.js` (module-style, modern JS)
- `scripts/pdf2html-convert.sh` carries the real conversion logic
- Thin Raycast entrypoint at `raycast_scripts/other/pdf-viewer-convert.sh` execs it
- Port **7435**, cache **`~/.cache/pdf_viewer/`**, asset symlink wired
- Local PDFs (`file://*.pdf`) convert and serve correctly, feature parity with
  the old hardcoded script
- **Online URLs (`https://*.pdf`, including signed Blackboard/S3/CloudFront
  URLs)**: host+path hash (query stripped), download to
  `<hash>/_source/document.pdf`, magic-byte check, filename from
  Content-Disposition (RFC 5987) or URL path, then same conversion pipeline.
  Second visit of any signed URL for the same document hits cache, no Docker.
- Old script still works on :7433 for A/B comparison
- **Overlay injection extracted** to `scripts/inject-overlay.py` — shared
  between `pdf2html-convert.sh` (on fresh conversions) and
  `upgrade-cache.sh` (on bulk upgrades).
- **`scripts/upgrade-cache.sh --mode={inject,reconvert}`**:
  - `inject` re-runs the injector on every `<hash>/*.html` — no Docker,
    seconds for the whole cache.
  - `reconvert` re-runs pdf2htmlEX. For https entries it reuses
    `<hash>/_source/*.pdf` (no re-download, since signed URLs often
    can't be refetched); for file entries it uses the original path
    from `mappings.tsv` and skips if missing.
- **`scripts/index-directory.sh <folder>`**: recursive `fd -e pdf`, content-
  hash each PDF, skip if any `*.html` already exists in that hash dir
  (matters when the same book is present under two filenames), otherwise
  run pdf2htmlEX + inject. Mappings upserted on both hit and miss so that
  renaming a PDF refreshes its `source_ref` row. Raycast entrypoint lives
  at `raycast_scripts/other/pdf-viewer-index-directory.sh` and takes a
  single text argument (absolute path or `~/...`). Verified end-to-end on
  a 3-PDF test folder: cold run → 2 converted + 1 skipped (content-hash
  dedup of the duplicate), warm run → 0 converted + 3 skipped.
- **FastAPI daemon** (`daemon/main.py`, uv project): read-only service
  over the cache dir. Routes: `GET /view?path=` / `GET /view?url=` /
  `GET /_assets/*` / `GET /<hash>/<file>` / `GET /healthz`. Cache hit
  ≈1–3ms. `/view?url=` miss → 307 to original URL; `/view?path=` miss →
  streams PDF bytes as `application/pdf` (Chromium blocks http→file:
  redirects, so 307-to-file won't work). Content hashes memoized by
  (path, mtime_ns, size). Daemon never invokes Docker (ADR 0004).
- **launchd autostart**: `launchd/com.anders.pdf_viewer.plist` symlinked
  into `~/Library/LaunchAgents/` (symlink so repo edits propagate on
  reload). LaunchAgent (user-level, no sudo). `RunAtLoad=true`,
  `KeepAlive=true`, `ThrottleInterval=5s`. Verified: kill the daemon,
  launchctl respawns it within seconds; reboot will bring it up on
  login.
- **Comet MV3 extension** (`extension/{manifest.json, rules.json}`):
  static `declarativeNetRequest` rule redirects `^https?://.*\.pdf(\?.*)?$`
  main_frame navigations → `http://localhost:7435/view?url=<original>`.
  Install: open `chrome://extensions` (or `comet://extensions`) → enable
  Developer mode → *Load unpacked* → point at `extension/`.
  Loop-prevention: a second allow-rule short-circuits any URL containing
  `_pdfvw=passthrough`, and the daemon appends that marker to its 307
  Location on cache miss. Without this pair, ext-redirects and 307s
  bounce forever (ERR_TOO_MANY_REDIRECTS). Non-.pdf URLs (e.g.
  Blackboard signed links) are intentionally not intercepted — user
  triggers Raycast-convert manually, next visit hits cache.

- **Visit tracking** (`daemon/visits.py` + `visits.db`): every `/view`
  cache hit inserts one row `(hash, ts, kind)` via FastAPI
  BackgroundTasks — off the response path, can never break serving.
  SQLite WAL, synchronous=NORMAL, schema auto-init at startup. Routes:
  `GET /stats` (totals + top 20 by count, enriched with name/source_ref
  from `mappings.tsv`) and `GET /stats/recent?limit=N` (raw timeline).
  Aggregates computed at query time — at personal-use volume the
  events table stays tiny for years, so no rollup table. LRU eviction
  is intentionally NOT wired up (PLAN §3: "Deferred until cache bloat
  becomes real"); this is observability only.

**What doesn't work yet:**
- Cross-device access over Tailscale (phase 8, optional)

---

## 3. Locked decisions (DO NOT revisit without cause)

### Naming & location
- Product name: `pdf_viewer` (underscore, user preference)
- Repo: `/Users/andersbekkevard/dev/misc/pdf_viewer/`
- Port: `7435` (old: `7433`)
- Old caches at `~/.cache/pdf2html-serve/` and `~/.cache/marker-serve/` are
  NOT migrated — kept intact as reference

### Cache location and layout

The cache is the **load-bearing** piece. Everything that takes time
(downloading, converting) is done once and stored here; every subsequent
read is an instant disk hit.

**Root**: `~/.cache/pdf_viewer/`

```
~/.cache/pdf_viewer/
├── _assets              → symlink to pdf_viewer/assets/ (served at /_assets/*)
├── log                  timestamped convert / download / server events
├── mappings.tsv         pdf-source ↔ hash ↔ html-path index (grep-friendly)
├── <hash>/              one dir per unique document
│   ├── <stem>.html      the injected HTML (served to browser)
│   ├── <stem>.outline.js + fonts/images/...  pdf2htmlEX output assets
│   ├── _source/         (phase 1.5+) downloaded source PDF for remote docs
│   │   └── document.pdf
│   └── meta.json        (phase 4+) source URL/path, display name, timestamps
└── ...
```

**Hash key** determines `<hash>`:
- Local PDF: `sha256(path + mtime + size)[:16]`
- Remote PDF: `sha256(host + path)[:16]`  (query string dropped entirely)

**Deleting a single entry** = `trash ~/.cache/pdf_viewer/<hash>/` and
remove the matching row from `mappings.tsv`.

**Nuking the whole cache** = `trash ~/.cache/pdf_viewer/` — lose nothing
irreplaceable, next open re-converts.

### Engine
- **pdf2htmlEX** is the primary engine (docker,
  `pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64`,
  amd64 via Rosetta on arm64)
- **marker** is a parallel tool for when we need semantic HTML (caret-mode
  navigation, find-across-whole-book). Not integrated into `pdf_viewer` yet;
  lives as a standalone Raycast script.
- Docker daemon runs **only when converting**. No background Docker.

### Cache keys
- Local PDFs: `sha256(path + mtime + size)[:16]` (decided; old script uses
  content hash which is slower but survives moves — re-evaluate when
  building the daemon)
- Online PDFs: `sha256(host + path)[:16]` — **query string stripped entirely**.
  This makes signed URLs (Blackboard, S3, CloudFront, Azure, GCS) hit cache
  across sessions because path usually carries the stable document ID.

### Cache miss behavior (daemon phase)
- On miss: `/view` **307-redirects to the original URL** → native PDF viewer
  handles it. No Docker boot. User runs the convert Raycast shortcut to
  escalate into HTML view; next visit hits cache.

### Indexing
- User-triggered per-directory, recursive.
- One shortcut: points it at a folder → recursive `fd -e pdf` → convert each,
  skip already-cached. No auto-scan of entire home directory.

### URL normalization strategy
Stripped because ephemeral:
- All `X-Amz-*` params
- `X-Blackboard-*` params
- `X-Goog-*` params  
- `Expires`, `Signature`, `response-cache-control`, `response-content-disposition`,
  `response-content-type`
Kept as cache-key basis:
- host + path

Implementation sketch:
```python
from urllib.parse import urlparse
import hashlib
def cache_key(url: str) -> str:
    p = urlparse(url)
    return hashlib.sha256(f"{p.netloc}{p.path}".encode()).hexdigest()[:16]
```

### Display filename for online PDFs
- First try: parse `response-content-disposition` query param (often contains
  real filename e.g. `filename*=UTF-8''sqlite(1).pdf`)
- Fall back: last path segment, add `.pdf` suffix
- Last resort: the hash

### Browser integration
- **Extension (eventual)**: Comet (Chromium MV3). `declarativeNetRequest`
  static rule redirects `.pdf$` URLs → `http://localhost:7435/view?url=…`
- Auth-gated PDFs (paywalls, SharePoint): **explicitly out of scope**
- Non-.pdf URLs that are actually PDFs (Blackboard signed links): user
  triggers Raycast manually; next visit hits cache. Extension won't catch
  them; that's intentional, not a bug.

### Daemon failure mode
- Accept: if daemon is down, tab breaks with `localhost:7435` unreachable.
  Launchd `KeepAlive=true` restarts within a second. No timeout/fallback
  logic in extension. If it bites in practice, revisit.

### Visit tracking
- Implemented in phase 7: SQLite events table at
  `~/.cache/pdf_viewer/visits.db`, written from a BackgroundTask on
  `/view` cache hits. Reflected via `GET /stats` + `GET /stats/recent`.
- Eviction (LRU/prune) intentionally NOT built — add only when cache
  disk use annoys us. The event log is the only missing piece, and
  it's now there, so building a pruner later is just a query.

### Cross-device (Tailscale)
- Out of scope for now. Daemon bound to `127.0.0.1` only. If later needed,
  it's a one-line change + Tailscale front.

---

## 4. User preferences (any future session must honor)

### Communication style
- Extremely concise. Sacrifice grammar for brevity.
- Short bullet lists over prose.
- No excessive politeness or hedging.
- End-of-turn = one or two sentences, never a recap essay.

### Tools
- `Trash` not `rm` for deletions
- `rg` not `grep`, `fd` not `find`
- `uv` for all Python environments (Python 3.12 for marker; 3.14 breaks torch)
- `~/.local/bin` is on PATH for interactive shells but **not** inherited by
  Raycast — scripts must `export PATH="$HOME/.local/bin:…:$PATH"` explicitly.

### User profile
- Vim champion. Uses Vimium daily. Cares deeply about keyboard ergonomics.
- Norwegian, NTNU student. Textbook-heavy reading workflow (the `bok-*`
  focus scripts, `Bøker/Pensum/` directory).
- Apple Silicon (arm64). Comet browser (Chromium-based).

### Leverage
- Use subagents for exploration / parallelizable work. Preserve main context
  for hard thinking.

---

## 5. Phased roadmap

Each phase is a discrete, shippable unit. Complete one before starting the
next. "DoD" = Definition of Done.

### Phase 1 — Clean extract  ✅ DONE
Overlay into `overlay.{js,css}` files, thin Raycast entrypoint, side-by-side
on different port/cache.

**DoD**: New Raycast command converts a local PDF to HTML, overlay served
from repo assets, all existing features work (verified via A/B against old
script).

### Phase 1.5 — Online URL support  ✅ DONE
Extended `scripts/pdf2html-convert.sh` with a scheme-dispatch block: `file://`
and `https?://` both funnel into the same docker conversion stage. See §2 for
behavior summary.

### Phase 2 — Upgrade-cache script  ✅ DONE
`scripts/upgrade-cache.sh --mode={inject,reconvert}`. Shares the injector
with `pdf2html-convert.sh` via `scripts/inject-overlay.py`.

- `inject` walks `~/.cache/pdf_viewer/*/*.html`, re-runs the injector. No
  Docker. Idempotent (strips prior id="pdf2html-*" tags first).
- `reconvert` iterates `mappings.tsv`. https entries mount
  `<hash>/_source/` (no re-download); file entries mount the dirname of the
  original path (skipped if the source no longer exists). `find -maxdepth 1
  ! -name '_source' -delete` clears prior pdf2htmlEX outputs while
  preserving the cached source PDF.

### Phase 3 — Bulk directory indexer  ✅ DONE
`scripts/index-directory.sh <folder>` + Raycast wrapper
`raycast_scripts/other/pdf-viewer-index-directory.sh` (takes a text arg for
the folder path, handles leading `~`). See §2 for behavior summary.

### Phase 4 — FastAPI daemon  ✅ DONE
**Scope narrowed during implementation.** Original phase plan listed
`POST /convert` and `POST /index` endpoints, which contradict ADR 0004
("the daemon never invokes Docker — never"). We followed the ADR: the
daemon is read-only. Conversion stays in Raycast scripts, which is also
where the scary expensive-dependency is kept.

Actual routes (`daemon/main.py`):
- `GET /view?path=<local>` — cache hit serves HTML; miss streams the PDF
  bytes as `application/pdf` because Chromium blocks http→file:
  redirects.
- `GET /view?url=<remote>` — cache hit serves HTML; miss 307s back to
  the original URL so the native viewer handles it.
- `GET /_assets/*` — overlay.{css,js} from the repo assets dir (so edits
  go live on refresh, no restart).
- `GET /<hash>/<file>` — falls through to a StaticFiles mount on
  `~/.cache/pdf_viewer/`, serving cached pdf2htmlEX bundles at the same
  URL the Raycast convert script already points Comet at.
- `GET /healthz` — liveness + entry count.

Content hashes memoized by (path, mtime_ns, size), so repeat requests on
a 40MB textbook re-hash exactly once per process lifetime.

Deferred to later phases (originally lumped into phase 4 but are
genuinely separate work):
- `<hash>/meta.json` per-entry metadata — wait until phase 7 visit
  tracking needs it.

### Phase 5 — launchd autostart  ✅ DONE
`launchd/com.anders.pdf_viewer.plist` (LaunchAgent, user-level, no sudo).
Symlinked into `~/Library/LaunchAgents/` so repo edits propagate on the
next `launchctl kickstart -k gui/$UID/com.anders.pdf_viewer`. Install /
uninstall commands live at the top of the plist file as comments.

### Phase 6 — Browser extension (Comet MV3)  ✅ DONE
Two-rule static `declarativeNetRequest`:
1. Priority-2 `allow` rule matches the `_pdfvw=passthrough` marker — breaks
   the redirect loop between the extension and the daemon's 307 on miss.
2. Priority-1 `redirect` rule matches `^https?://.*\.pdf(\?.*)?$`
   main_frame navigations and rewrites them via `regexSubstitution` into
   `http://localhost:7435/view?url=<original>`. `excludedRequestDomains`
   skips localhost so requests to the daemon itself never match.

The daemon's `_view_url` appends `_pdfvw=passthrough` to the 307 Location
on cache miss so the allow-rule fires.

### Phase 7 — Visit tracking  ✅ DONE (observability only; no eviction)
`daemon/visits.py` maintains `~/.cache/pdf_viewer/visits.db`
(`visits(hash, ts, kind)`, WAL, indexes on hash + ts). Insert happens
from a FastAPI BackgroundTask in `/view` on cache hit — never blocks
response, swallows `sqlite3.Error` so a broken DB can never break
serving.

Routes:
- `GET /stats` — totals, first/last visit, top 20 docs by count,
  enriched via `mappings.tsv` so hashes render as filenames.
- `GET /stats/recent?limit=100` — raw timeline, also enriched.

LRU eviction deliberately NOT implemented. If cache bloat becomes a
real problem, add a `scripts/prune-cache.sh --keep N` that queries the
DB and `trash`es the bottom entries (scary work stays in Raycast
scripts per ADR 0004).

### Phase 8 — Cross-device (optional)  ⏳ NEXT (only if explicit desire)
Bind daemon to `0.0.0.0` behind Tailscale; read PDFs from iPad via same
cache. Defer until explicit desire.

---

## 6. Feature registry (current overlay)

Everything the overlay does right now. **This is the contract** — phase 2
upgrade-cache script must preserve 100% of this.

### Visual
- Canvas background `#282828` (outside pages)
- `#sidebar` restyled: solid `#1e1e1e`, sans-serif, Gemini-style active
  chapter highlight
- Text selection color `#99C1DA`
- ☰ ghost button top-left (18% opacity, 70% on hover)
- Page counter pill top-center (Helvetica/Arial, 12px, dimmed)
- Command palette pill bottom (vim ex-bar style, monospace, dark)
- Cheatsheet modal centered (dark panel, monospace keys in amber)
- Favicon = inline SVG of 📑 emoji

### Behavior
- Sidebar hidden by default (`body:not(.sidebar-shown)` rule)
- pdf2htmlEX's render loop killed on load (via
  `window.pdf2htmlEX.defaultViewer.render_timer = null` + `render = noop`)
- Render window via IntersectionObserver (`rootMargin: '-20px 0px'`, sliver
  protection). Pages outside the window get `display: none !important` via
  the `.pf > .pc` rule; pages inside get `.pdf2html-force` class
- Render-all short-circuit: `allForced` flag, no per-scroll DOM thrash
- Cursor pin / scrolloff: selectionchange → scroll `#page-container` so the
  cursor stays in view. `pinned=true` locks focus to viewport center (Vim
  `scrolloff=999` feel); `pinned=false` only scrolls when cursor enters the
  top/bottom margin of size `scrollOffFraction * viewport_height` (0–50%).
- Outline active tracker: highlights deepest outline entry with
  `target page ≤ current page`, auto-scrolls into view within sidebar
- Page counter uses `document.elementFromPoint` (zoom-robust)
- Title = PDF stem
- Navigate in-place (preserves browser back button)
- Stdio redirected to log (Raycast can't raise notifications from stderr)

### State persistence (localStorage keys)
- `pdf2html-buffer` — render buffer page count (default 10)
- `pdf2html-render-all` — '1' / '0', render-all checkbox state
- `pdf2html-scrolloff` — scrolloff band fraction 0.0-0.5 (default 0.25)
- `pdf2html-pinned` — '1' / '0', pin-to-center toggle (default '1')
- `pdf2html-pageno-hidden` — '1' / '0', page counter visibility
- `pdf2html-position:<hash>` — JSON `{page, ts}` last-visited page per doc;
  restored on reopen unless URL carries a `#pfXX` anchor. Page 1 is not
  resumed (treated as "nothing meaningful to remember").
- `pdf2html-marks:<hash>` — JSON `{<letter>: {page, label, ts}}` persistent
  bookmarks set via `:mark <a-z>`, recalled via `:jump <a-z>`.

---

## 7. Shortcut registry

### Implemented

| Key              | Action                                     |
|------------------|--------------------------------------------|
| `s`              | Toggle sidebar                             |
| `⌘.`             | Toggle sidebar                             |
| `A`              | Toggle render-all pages                    |
| `⌘⇧.`            | Toggle page counter                        |
| `:`              | Open command palette                       |
| `⌘K`             | Quick-open: palette pre-seeded with `:open ` (library picker) |
| `?`              | Toggle cheatsheet (requires Vimium `?` disabled on localhost:7435) |
| `Esc`            | Close palette → close cheatsheet → clear selection |

### Command palette

| Command          | Action                                     |
|------------------|--------------------------------------------|
| `:42`            | Goto page 42                               |
| `:p 42`          | Alias for `:42`                            |
| `:chapter <name>` | Jump to outline chapter; Tab completes against sidebar entries (case-insensitive substring) |
| `:next` / `:prev` | Next chapter / prev chapter (or reset to current-chapter start if > NEAR_THRESHOLD pages in) |
| `:mark <a-z>`    | Persistent bookmark of current page (localStorage, per hash) |
| `:jump <a-z>`    | Jump to a saved mark                       |
| `:clear <a-z>`   | Delete a saved mark                        |
| `:open <doc>` / `:o` | Switch to another cached doc; completes against `/library` (visits-sorted) |
| `:pin`           | Toggle pin-to-center                        |
| `:scrolloff 25` / `:so 25` | Set scrolloff band to 25% (0-50)  |
| `:buffer 20`     | Set render buffer to ±20 pages             |
| `:buf 20`        | Alias for `:buffer`                        |
| `:all`           | Toggle render-all                          |
| `:yank` / `:y`   | Copy "Chapter · p. N" to clipboard         |
| `:counter` / `:num` | Toggle page counter                     |
| `:help` / `:h`   | Open cheatsheet                            |

### Proposed (not implemented)

- `}` / `{` — next / previous chapter (outline walk)
- `Ctrl-o` / `Ctrl-i` — doc-local jumplist
- `zz` — recenter selection on pin

### Permanently rejected (Vimium conflicts)

- `n`, `p`, `o`, `]]`, `[[`, `m`, `'`, `gs`, `ge`, `gg`, `G`, `H`, `L`,
  `gt`, `gT`, `zi/zo/z0`, `r/R` — all have Vimium bindings we rely on
- `gp` — contains `p` (reserved)
- `gn` — contains `n` (reserved)
- `go` — contains `o` (reserved)
- `g?` — `?` handled by our listener; Vimium's `?` disabled by exclusion rule
- `g<letter>` for toggles — "wrong letter family"; `A` used instead

### Vim-ergonomic escape hatch

All numeric-argument commands live in `:` palette rather than `[N]<key>`.
No count-prefix parser.

---

## 8. Known technical gotchas

Things we learned the hard way. Don't re-discover.

### Docker / pdf2htmlEX
- Image tag: `...rc2-master-20200820...` (rc1 was 404 on Docker Hub)
- Needs `--platform linux/amd64` on Apple Silicon
- Perl locale warning: pass `-e LC_ALL=C.UTF-8 -e LANG=C.UTF-8`, also grep
  the stderr stream to hide stragglers
- First run pulls ~1GB image

### Raycast
- Silent mode surfaces stderr as notification toasts. Mitigation:
  `exec >>"$LOG_FILE" 2>&1` at top of script.
- Only indexes files under configured Raycast script directories. The
  product's script lives in `pdf_viewer/scripts/` but must have a thin
  entrypoint in `raycast_scripts/other/`.
- Raycast environment does NOT inherit `~/.local/bin`. Scripts must
  explicitly `export PATH="$HOME/.local/bin:/opt/homebrew/bin:…:$PATH"`
  if they need uv-installed binaries.
- Success sound was manually-added `afplay Glass.aiff`; removed.
  Failure sound `Basso.aiff` retained.

### Browser / Comet
- Favicon cache is persistent. ⌘⇧R sometimes doesn't bust it. Side note:
  SVG-emoji-via-data-URL is fragile in Chromium; a static served file
  (even `.ico`) is more reliable if this becomes an issue.
- Setting tab URL via AppleScript (`set URL of active tab of front window`)
  preserves back-button history vs close+new-tab approach.
- Comet is Chromium-based → accepts Chrome MV3 extensions directly.

### Vimium
- `?` = help. Must add `localhost:7435` to "Keys to pass through" exclusion
  for `?` to reach our overlay.
- `m`, `'` = marks. Use them — don't reimplement bookmarks.
- `/`, `n`, `N` = find. Scoped to rendered DOM, so render buffer controls
  find scope too.
- `gi` = focus first input on page — lands on our render buffer input,
  zero code needed.

### Performance
- `contain: layout paint style` on 797 `.pf` elements caused paint flashes
  (GPU layer juggling). REMOVED. Do not reintroduce naively.
- `classList.contains()` in a 797-iteration loop on every scroll
  IntersectionObserver callback caused paint stalls. Fixed with `allForced`
  fast-path in render-all mode.
- Cached page offsets go stale on zoom. IntersectionObserver sidesteps
  this entirely (browser manages geometry). The outline tracker still uses
  cached offsets — acceptable trade since wrong highlight is cosmetic.
- Rapid selection extension (`j j j` in visual mode): pin-based continuous
  scroll is imperceptibly smoother than edge-band `scrollIntoView` jumps.
  Do not revert.

### JS patterns
- All keyboard listeners must guard on `INPUT`/`TEXTAREA` target to avoid
  intercepting typing inside our own palette, Vimium's find input, etc.
- Escape handler uses capture phase (Vimium also listens for Escape).
  Priority: palette → cheatsheet → clear selection.
- Overlay injection is idempotent (strips prior `id`-tagged tags before
  injecting). Re-running the script retrofits cached HTML.

---

## 9. Open questions

Nothing blocking phase 1.5. For later:

1. Daemon: should the local-file cache key be `path+mtime+size` (fast) or
   `sha256(content)` (robust to moves)? Old script uses content hash.
   Revisit during phase 4.
2. Daemon: does `/index` return progress incrementally (WebSocket) or
   synchronously? Low priority.
3. Extension: if we later want local file interception, we'd need a
   content script, not `declarativeNetRequest` (can't match `file://`).
   Defer until it actually bites.

---

## 10. Non-goals

Explicitly out of scope. If a future me wants to add these, reconsider
carefully first.

- Auth-gated PDF fetching (SharePoint, paywalls). Let the browser download
  them; user drops into Raycast manually.
- Smart auto-detection of PDFs without `.pdf` extension at the extension
  level. Manual Raycast trigger is the escape hatch.
- Fancy PDF annotations / notes in-viewer. Out of scope for viewer; use
  Obsidian if needed.
- Real-time collaboration / multi-user.
- Mobile-native app. Tailscale-to-laptop-daemon is the fallback.
- Exposing a public URL. Always bind to localhost.
- Building against marker in the daemon. Keep it as a separate parallel
  tool unless a compelling use case appears.

---

## 11. How to pick up work (future-me checklist)

1. Read this file top to bottom.
2. Check `pdf_viewer/scripts/pdf2html-convert.sh` to see current state.
3. Check `~/.cache/pdf_viewer/log` for recent behavior.
4. Identify current phase from Section 5. The next phase flagged `⏳ NEXT`
   is the immediate target.
5. Update this file as decisions are made or phases complete.
