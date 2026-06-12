# CLAUDE.md / AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

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
  (`file://` or `https://`). Hashes, downloads if remote, runs the native
  arm64 pdf2htmlEX binary (no Docker — ADR 0011), injects the overlay.
  Invoked from a Raycast wrapper.
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
- Full-chain diagnosis (read-only): `scripts/doctor.sh` — one PASS/FAIL/WARN line per link (daemon, _assets symlink, native binary + dylibs, cache writability) with fix hints; exits non-zero iff a required check fails.
- Live tail: `tail -f ~/.cache/pdf_viewer/log`
- Daemon health: `curl localhost:7435/healthz`
- Grep cache index: `rg <query> ~/.cache/pdf_viewer/mappings.tsv`

### Testing
No automated tests. Follow `docs/verification.md` and choose the narrowest
real proof for the changed surface: Browser/Playwright for local viewer UI,
curl/logs for daemon behavior, and Comet/Raycast manual checks for surfaces
that only exist there.

### AI production workflow
- Active work is tracked in Beads (`br`) under `.beads/issues.jsonl`;
  local SQLite files are ignored runtime state.
- Read `docs/ai-production.md` before doing multi-step work. It defines
  the documentation ownership model, bead shape, AFK/HITL labels, and
  session protocol for mostly hands-off agent work.
- Read `docs/verification.md` before closing a bead. Every closed bead needs
  a verification comment with the command/browser flow and result.
- `TODO.md` is legacy intake only. Do not add new tasks there; create or
  update beads instead.
- Treat the generated Beads publish checklist below as a full shipping path,
  not a default requirement. Do not commit, push, or open PRs unless the user
  asks for publication.

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
- **Render-window is now CSS-only.** `.pf { content-visibility: auto }`
  in `assets/overlay.css` lets the browser skip paint+layout for
  offscreen pages while keeping their text in the layout tree, which is
  what makes native Cmd-F work end-to-end. Don't reintroduce
  `.pc { display: none }` gating — Chromium find skips `display:none`
  text and the surrogate-shadow architecture that papered over that
  was deleted in ADR 0009.
- **Don't add unconditional `contain: layout paint style` to `.pf`.**
  ADR 0002 tried it (separate from `content-visibility: auto`) and saw
  797-layer compositor churn on long docs. `content-visibility: auto`'s
  containment is eligibility-driven and is fine; raw `contain` on every
  page is not.
- **`contain-intrinsic-size` reserves space for unrendered pages.**
  Currently `auto 1100px`; the `auto` keyword lets the browser cache
  each page's last-known size for stable scrollbar geometry. Tune per
  page-size class (`pc1`, `pc2`, …) if zoom-induced reflow flashes.
- **`elementFromPoint` is the zoom-robust way to ask "which page is
  visible?".** Don't cache `offsetTop`/`offsetHeight` — they go stale
  on `⌘+`/`⌘-`. The outline-active tracker is an intentional exception
  (wrong highlight is cosmetic).
- **Conversion is a native arm64 pdf2htmlEX binary, not Docker.**
  Installed at `~/.local/opt/pdf2htmlEX/` by
  `scripts/install-native-pdf2htmlex.sh` (copy-only from the v2 build
  tree `~/dev/external/pdf2htmlEX_v2/`). Convert scripts always pass
  `--data-dir` and `--poppler-data-dir` explicitly (baked defaults are
  fragile); they fail fast with "native pdf2htmlEX not installed" if the
  binary is missing. Docker is no longer needed for conversion — see
  ADR 0011. The binary depends on Homebrew dylibs + `/opt/homebrew/share/poppler`
  at runtime; if a `brew upgrade` breaks linkage, rebuild in the v2 tree
  and re-run the installer.
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
- [`docs/ai-production.md`](docs/ai-production.md) — documentation
  ownership and Beads workflow for agent-driven work.
- [`docs/verification.md`](docs/verification.md) — how agents prove behavior
  before closing beads.
- [`docs/pins.md`](docs/pins.md) — pins / markers product intent and
  open interaction questions.
- [`docs/keybindings.md`](docs/keybindings.md) — full key + palette
  registry, Vimium conflicts.
- [`docs/non-goals.md`](docs/non-goals.md) — explicit scope boundaries.
- [`docs/pdf2htmlex-dom.md`](docs/pdf2htmlex-dom.md) — DOM
  conventions of converted HTML. Read before writing any new selector.
- [`docs/adr/`](docs/adr/) — the "why" behind major architectural
  choices (engine, render model, keyboard strategy, compute/daemon
  split, native arm64 pdf2htmlEX, Vimium scroll scoping, scrolloff).

<!-- br-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`/`bd`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View ready issues (open, unblocked, not deferred)
br ready              # or: bd ready

# List and search
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br search "keyword"   # Full-text search

# Create and update
br create --title="..." --description="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once

# Sync with git
br sync --flush-only  # Export DB to JSONL
br sync --status      # Check sync status
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only open, unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always sync before ending session

<!-- end-br-agent-instructions -->
