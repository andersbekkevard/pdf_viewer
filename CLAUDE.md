# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project shape

Personal PDF → custom-HTML viewer for keyboard-native (Vimium) workflow.
Chrome/Comet's native PDF viewer is a sandboxed surface that extensions
can't reach, so PDFs must become HTML for Vimium to work on them.
`pdf2htmlEX` produces pixel-faithful HTML; we inject a JS/CSS overlay
that reshapes the UX, and wrap the whole thing in a cache + daemon +
browser-extension pipeline.

`README.md` is the orientation doc — read it first for workflow and
component overview.

## Architecture (how it all fits together)

Six loosely-coupled parts, each with a narrow job:

- **`assets/overlay.{js,css}`** — all UX behavior (~2.5k LoC JS,
  ~1.2k LoC CSS). Served live at `/_assets/` via a symlink from the
  cache dir, so edits reload on ⌘⇧R without reconversion. This is
  where ~90 % of day-to-day work happens.
- **`scripts/pdf2html-convert.sh`** — single-PDF conversion
  (`file://` or `https://`). Hashes, downloads if remote, runs Docker
  pdf2htmlEX, injects the overlay. Invoked from a Raycast wrapper.
- **`scripts/index-directory.sh`** — recursive folder indexer. Content-
  hashes every PDF and skips anything already cached.
- **`scripts/inject-overlay.py`** — idempotent `<script>`/`<link>`
  injector, shared between fresh conversions and `upgrade-cache.sh`.
- **`daemon/` (FastAPI, uv)** — read-only cache server on port
  **7435**. Routes: `/view?path=` / `/view?url=` / `/<hash>/<file>` /
  `/_assets/*` / `/healthz` / `/stats` / `/library`. Run via launchd
  (`launchd/com.anders.pdf_viewer.plist`). Cache lookup ≈ 1–3 ms.
  **The daemon never touches Docker.**
- **`extension/` (Comet MV3)** — two static `declarativeNetRequest`
  rules redirect `*.pdf` navigations to the daemon, with a
  `_pdfvw=passthrough` marker that breaks the 307 redirect loop on
  cache miss.

Runtime cache: `~/.cache/pdf_viewer/` (see `docs/cache.md`). A
**symlink** from `~/.cache/pdf_viewer/_assets/` back to this repo's
`assets/` is what makes overlay edits go live immediately.

The Raycast entrypoints live in `raycast/pdf-viewer-*.sh`. Raycast is
configured (Settings → Extensions → Script Commands → *Add script
directory*) to index this folder directly — it contains **only**
Raycast-format scripts so Raycast doesn't try to parse unrelated files.
Those entrypoints are deliberately trivial `nohup` forks into
`scripts/*.sh` — all real logic stays in `scripts/`.

## Common tasks

### Overlay changes (90 % of work)
1. Edit `assets/overlay.js` or `assets/overlay.css`.
2. ⌘⇧R in an already-open converted tab — served live via symlink, no
   reconversion needed.

### Script / injection changes
- Trash the relevant cache entry to force re-conversion:
  `trash ~/.cache/pdf_viewer/<hash>/`.
- Or bump `OVERLAY_VERSION` in `scripts/pdf2html-convert.sh` to bust
  the `<script src=…?v=N>` query-string cache.
- Bulk re-inject the overlay over all cached HTML (no Docker, seconds):
  `scripts/upgrade-cache.sh --mode=inject`.

### Running / restarting the daemon
- Dev: `uv run --directory daemon main.py`
- Prod (launchd): `launchctl kickstart -k gui/$UID/com.anders.pdf_viewer`

### Logs & debugging
- Live tail: `tail -f ~/.cache/pdf_viewer/log`
- Daemon health: `curl localhost:7435/healthz`
- Grep cache index: `rg <query> ~/.cache/pdf_viewer/mappings.tsv`

### Testing
No automated tests. Verify by running the Raycast shortcut on a local
PDF and inspecting behavior in Comet.

## Python: always uv

Every Python environment, tool, and script in this repo uses `uv`. Do
not invoke `pip`, create `venv` / `virtualenv` manually, install CLIs
with Homebrew Python, or rely on the system `python3`.

- **Projects** (e.g. `daemon/`): `uv init` → `uv add` → `uv run`.
- **CLI tools** (e.g. `marker_single`): `uv tool install --python 3.12 <pkg>`.
  Pin Python per-tool — 3.14 breaks PyTorch wheels; most tools want 3.12.
- **Stdlib-only shell one-liners** (`python3 -c "import urllib…"` in
  `scripts/pdf2html-convert.sh`) are the one exception — wrapping each
  call in `uv run` adds ~200 ms of venv startup for zero benefit when
  no deps are involved. Anything that imports outside stdlib must go
  through uv.

`~/.local/bin` (where `uv tool install` puts shims) is on the user's
interactive PATH but **not** Raycast's. Scripts invoking uv-installed
tools must `export PATH="$HOME/.local/bin:/opt/homebrew/bin:…:$PATH"`
explicitly.

## Non-obvious gotchas

- **Raycast silent mode surfaces stderr as macOS notifications.**
  `scripts/pdf2html-convert.sh` starts with `exec >>"$LOG_FILE" 2>&1`
  for this reason. Don't remove it.
- **pdf2htmlEX ships its own render loop that fights our visibility
  logic.** `assets/overlay.js::killPdf2htmlExRenderLoop` disables it
  on load (`window.pdf2htmlEX.defaultViewer.render_timer = null`,
  `render = () => {}`). If rendering goes glitchy after an upgrade,
  verify this is still succeeding.
- **Class-based `!important` beats pdf2htmlEX's inline style.** The
  `.pf > .pc { display: none !important }` +
  `.pf.pdf2html-force > .pc { display: block !important }` pair is
  the visibility contract. Don't refactor to inline `.style.display` —
  pdf2htmlEX's leftover runtime would race us.
- **Do NOT add `contain: layout paint style` to `.pf`.** Tried it;
  caused paint flash on scroll with 797-page docs due to 797-layer
  compositor churn. See ADR 0002.
- **In render-all mode, `apply()` must short-circuit via the
  `allForced` flag.** Iterating 797 pages in `classList.contains()`
  on post-scroll frames forces style recalc and causes visible flash.
- **IntersectionObserver is zoom-robust; cached offsets are not.**
  Any new logic that needs to know "which page is visible" should use
  the observer pattern in `mountRenderWindow`, not
  `offsetTop`/`offsetHeight` reads. The outline tracker is an
  intentional exception (wrong highlight is cosmetic).
- **Docker daemon is assumed OFF by default.** Scripts that need it
  fail fast with a clear "Docker daemon not running" error. Do not
  auto-start Docker from any script — see ADR 0004.
- **Vimium reserves many keys; never invent a new overlay keybinding
  without checking `docs/keybindings.md`.** When in doubt, add a
  palette command instead.
- **Custom interactive controls need to be real `<button>` /
  semantic elements (or carry `role=` + `tabindex`), else Vimium F
  can't hint them.** A plain `<div>` with an `addEventListener('click')`
  is invisible to Vimium's detector.
- **Port `7435` and cache `~/.cache/pdf_viewer/` are deliberately
  different from the retired hardcoded script's `7433` /
  `~/.cache/pdf2html-serve/`.** The old script is preserved for A/B
  comparison and must not be modified.

## Further reading

- [`README.md`](README.md) — orientation, workflow, components.
- [`docs/cache.md`](docs/cache.md) — cache layout, hash keys, URL
  normalization, failure modes.
- [`docs/keybindings.md`](docs/keybindings.md) — full key + palette
  registry, Vimium conflicts.
- [`docs/non-goals.md`](docs/non-goals.md) — explicit scope boundaries.
- [`docs/pdf2htmlex-dom.md`](docs/pdf2htmlex-dom.md) — DOM
  conventions of converted HTML. Read before writing any new selector.
- [`docs/adr/`](docs/adr/) — the "why" behind major architectural
  choices (engine, render model, keyboard strategy, docker/daemon
  split, Vimium scroll scoping, scrolloff).
