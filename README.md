# pdf_viewer

Personal PDF → HTML viewer. Take any PDF (local or online), run it through
`pdf2htmlEX`, inject a custom JS/CSS overlay that adds vim-friendly navigation,
and serve the result from localhost. Page state (render buffer, cursor pin,
page counter visibility, etc.) persists per-browser via `localStorage`.

## Current state (phase 1: clean extract)

The overlay is extracted to proper files:

- `assets/overlay.css` — all custom styling
- `assets/overlay.js` — all runtime behavior (sidebar, pin, render window,
  cheatsheet, command palette, page counter, outline active tracker)

The Raycast script at `scripts/pdf2html-convert.sh` runs `pdf2htmlEX`,
injects `<link>` / `<script>` tags that reference the served assets, and
opens the result in the current Comet tab.

Runs on **port 7435**, cache at **`~/.cache/pdf_viewer/`** — intentionally
different from the old hardcoded script's `7433` / `~/.cache/pdf2html-serve/`
so both can run side-by-side for A/B comparison during migration.

## Workflow

1. Open a local PDF in Comet (`file://…`)
2. Trigger the Raycast script
3. Tab navigates in-place to the converted HTML at `http://localhost:7435/…`

## Architecture — future direction

See `TODO.md`. Short version: this shell+script thing becomes a FastAPI
daemon that handles both local and remote PDFs, a browser extension that
redirects `*.pdf` URLs transparently, and a launchd plist to keep the
daemon alive.

## Layout

```
pdf_viewer/
├── assets/
│   ├── overlay.css        # served at /_assets/overlay.css
│   └── overlay.js         # served at /_assets/overlay.js
├── scripts/
│   └── pdf2html-convert.sh  # Raycast script (phase-1)
├── README.md
└── TODO.md
```

## Shortcuts (inside converted HTML)

| Key       | Action                               |
|-----------|--------------------------------------|
| `s` / `⌘.`| Toggle sidebar                       |
| `A`       | Toggle render-all pages              |
| `⌘⇧.`     | Toggle page counter                  |
| `:`       | Open command palette                 |
| `?`       | Toggle cheatsheet overlay            |
| `Esc`     | Close overlay / clear selection      |

Palette: `:42` (goto), `:pin 30`, `:buffer 20`, `:all`, `:yank`,
`:counter`, `:help`.
