# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Personal PDF → custom-HTML viewer for keyboard-native (Vimium) workflow. Chrome/Comet's native PDF viewer is a sandboxed surface that browser extensions can't reach, so PDFs must become HTML pages for Vimium to work on them. `pdf2htmlEX` produces visually faithful HTML; we inject a JS/CSS overlay that fixes the UX and add cache + daemon + browser-extension plumbing so this happens automatically.

## Before doing anything

Read `PLAN.md` first. It is the single source of truth: problem statement, locked design decisions, user preferences, phased roadmap with what's done vs next, feature registry (the behavioral contract the overlay must maintain), shortcut map, known gotchas.

For rationale behind major choices, see `docs/ADR/`. The four current ADRs cover: engine choice, rendering model, keyboard strategy under Vimium, and docker-on-demand architecture.

For DOM conventions of pdf2htmlEX's output (class names, hex page IDs, outline link structure, utility class system), see `docs/pdf2htmlex-dom.md`. Read this before writing any new selector against the converted HTML.

## Repo map

```
assets/overlay.{js,css}         # the overlay — all UX behavior (~500 lines JS)
scripts/pdf2html-convert.sh     # phase-1 conversion logic (invoked by the Raycast entrypoint)
docs/ADR/                       # immutable architectural decisions
PLAN.md                         # living plan of record (update as phases complete)
TODO.md                         # brief roadmap index; real detail is in PLAN.md
```

The Raycast entrypoint lives **outside** this repo at `/Users/andersbekkevard/dev/misc/raycast_scripts/other/pdf-viewer-convert.sh` — a 2-line `exec` into `scripts/pdf2html-convert.sh`. Raycast only indexes files under `raycast_scripts/`, which is why the entrypoint must live there.

Runtime cache is at `~/.cache/pdf_viewer/` — see `PLAN.md` §3 for the full layout.

## Testing changes

No automated tests. Verify by running the Raycast shortcut on a local PDF and inspecting behavior in Comet. Logs at `~/.cache/pdf_viewer/log` — `tail -f` to watch live.

Overlay-only changes (most common case): edit `assets/overlay.{js,css}`, ⌘⇧R in an already-open converted-HTML tab. The asset is served live via symlink — no re-conversion needed.

Script/injection changes: delete the relevant `~/.cache/pdf_viewer/<hash>/` entry to force re-conversion on next Raycast run, or bump `OVERLAY_VERSION` in the script to bust the `<script src=...?v=N>` query-string cache.

## Python: always uv

All Python environments, tools, and scripts in this repo use `uv`. **Do not** invoke `pip`, create `venv` / `virtualenv` manually, install CLIs with Homebrew Python, or rely on the system `python3` having packages.

- **Projects** (phase-4 FastAPI daemon and anything like it): `uv init` → `uv add` for deps → `uv run <cmd>` / `uvx <tool>` to execute.
- **CLI tools** (e.g. `marker_single`): `uv tool install --python 3.12 <pkg>`. Pin Python version per-tool — Python 3.14 breaks PyTorch wheels; most tools want 3.12.
- **Stdlib-only shell one-liners** (`python3 -c "import urllib…"` etc. already in `scripts/pdf2html-convert.sh`) are the one acceptable exception to the "always uv" rule — adding `uv run` wraps each call in ~200ms of venv startup for zero benefit when no deps are involved. Anything that needs an import beyond the standard library must go through uv.

`~/.local/bin` (where `uv tool install` puts shims) is on the user's interactive PATH but **not** Raycast's. Scripts invoking uv-installed tools must `export PATH="$HOME/.local/bin:…:$PATH"` explicitly.

## Non-obvious gotchas

- **Raycast silent mode surfaces stderr as macOS notifications.** `scripts/pdf2html-convert.sh` starts with `exec >>"$LOG_FILE" 2>&1` for this reason. Don't remove it.
- **Raycast's shell does not inherit `~/.local/bin` from the user's PATH.** Scripts needing `uv`-installed tools must `export PATH="$HOME/.local/bin:…:$PATH"` explicitly.
- **pdf2htmlEX ships its own render loop that fights our visibility logic.** `assets/overlay.js::killPdf2htmlExRenderLoop` disables it on load (`window.pdf2htmlEX.defaultViewer.render_timer = null`, `render = () => {}`). If rendering goes glitchy after an upgrade, verify this is still succeeding.
- **Class-based `!important` beats pdf2htmlEX's inline style.** The `.pf > .pc { display: none !important }` + `.pf.pdf2html-force > .pc { display: block !important }` pair is the visibility contract. Don't refactor to inline `.style.display` — pdf2htmlEX's leftover runtime would race us.
- **Do NOT add `contain: layout paint style` to `.pf`.** Tried it, caused paint flash on scroll with 797-page docs due to 797-layer compositor churn. See ADR 0002.
- **In render-all mode, `apply()` must short-circuit via the `allForced` flag.** Iterating 797 pages in `classList.contains()` on post-scroll frames forces style recalc and causes visible flash.
- **IntersectionObserver is zoom-robust; cached offsets are not.** Any new logic that needs to know "which page is visible" should use the observer pattern in `mountRenderWindow`, not `offsetTop`/`offsetHeight` reads. The outline tracker is an intentional exception (wrong highlight is cosmetic).
- **Docker daemon is assumed OFF by default.** Scripts that need it fail fast with a clear "Docker daemon not running" error. Do not auto-start Docker from any script — see ADR 0004.
- **Never use Vimium-reserved keys for new overlay shortcuts.** The "Permanently rejected" list in `PLAN.md` §7 is authoritative. When in doubt, add the command to the `:` palette in `runCommand()` instead of inventing a keybinding.
- **Port `7435` and cache `~/.cache/pdf_viewer/` are deliberately different from the old hardcoded script's `7433` / `~/.cache/pdf2html-serve/`.** The old script is preserved for A/B comparison and must not be modified.
