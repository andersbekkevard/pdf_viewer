# Verification

This project has no standing automated test suite. Agents must still prove
their work with a narrow verification loop before closing a bead.

## Available verification surfaces

- **Codex Browser plugin**: preferred for interactive/local browser checks when
  available. It can open `localhost`, inspect the DOM, press keys, click, type,
  and capture screenshots in the in-app browser.
- **Playwright CLI skill**: terminal fallback for headed browser automation and
  repeatable UI flows. Use the bundled wrapper instead of adding a repo
  dependency:

  ```bash
  export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
  export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"

  "$PWCLI" open http://localhost:7435 --headed
  "$PWCLI" snapshot
  "$PWCLI" press "Meta+F"
  "$PWCLI" screenshot
  ```

- **Manual Comet/Raycast checks**: required when the behavior depends on the
  Comet extension, Vimium, Raycast script commands, or the Comet LLM sidebar.
  Browser automation can support these checks, but it cannot replace a
  Comet-only surface.
- **Daemon probes**: use `curl`, logs, and direct route checks for server/cache
  behavior.

Do not add Playwright, Vitest, or browser-test dependencies to this repo unless
a bead explicitly asks for a durable automated test suite. For ad hoc
automation, use the existing Codex/Playwright tools.

## Session checklist

Before implementation:

```bash
br show <id>
br sync --status
curl -fsS http://localhost:7435/healthz
```

If the daemon is down and the bead needs it:

```bash
uv run --directory daemon main.py
```

For the launchd-managed daemon:

```bash
launchctl kickstart -k gui/$UID/com.anders.pdf_viewer
tail -f ~/.cache/pdf_viewer/log
```

Before closing a bead:

```bash
git diff --check
br comments add <id> --message "Verification: <what was checked and result>"
br close <id> --reason "Completed"
br sync --flush-only
```

If verification is blocked, do not close the bead. Add a comment explaining the
blocker, what was attempted, and the exact missing artifact or user action.

## Overlay smoke test (standard pre-close check for overlay beads)

`scripts/smoke-viewer.sh` is the standard pre-close check for any bead that
touches `assets/overlay.{js,css}`. It is a single command that exits non-zero
on any failure:

```bash
scripts/smoke-viewer.sh
```

It converts `test/fixtures/basic_text.pdf` with the real native pdf2htmlEX
binary into a temp cache entry, injects the live overlay, and runs headless
Chromium (the locally-cached Playwright — no repo dependency) against the real
daemon on `:7435`, asserting: expected `.pf` page count,
`#pdf2html-pageno-current` present, sidebar DOM present,
`pdf2htmlEX.defaultViewer.render_timer === null`, `window.find('Normal')`, zero
console errors, and zero failed `/_assets/` requests. The temp entry is
trap-cleaned on exit. The daemon must already be up — the script never starts
it. Run it green before closing an overlay bead; a richer interactive proof
from the list below is still warranted when the bead changes behavior the smoke
test does not assert.

## Pick the right proof

Use the smallest proof that exercises the changed behavior:

- **Overlay UI / keyboard work**: open a real converted PDF through
  `localhost:7435`, perform the key sequence or pointer action, and confirm the
  visible state with Browser/Playwright screenshot or DOM snapshot.
- **Native browser find**: use a large converted PDF, open native Cmd-F, search
  for text outside the initially visible pages, press Enter through matches, and
  confirm the active highlight is visible on the expected page. Check normal
  reload and hard reload if the bead mentions stale assets.
- **Selection behavior**: use a real converted PDF page, perform the exact drag
  or visual-mode action from the bead, and verify both visible selection and
  copied clipboard/plain-text output when relevant.
- **Daemon/cache behavior**: verify with `curl`, `rg ~/.cache/pdf_viewer`, and
  the daemon logs. A browser check is still needed if the route changes user
  navigation.
- **Conversion/injection behavior**: use a small local PDF fixture or a known
  cached PDF. If conversion itself is exercised, the native pdf2htmlEX binary
  must already be installed (`scripts/install-native-pdf2htmlex.sh`, ADR 0011);
  scripts must not auto-install or auto-build it.
- **Extension redirect behavior**: verify in Comet with the unpacked extension
  loaded. Check both cache hit and passthrough/cache-miss paths when redirects
  change.
- **Memory/performance work**: define the measurement first, run it before and
  after on the same document, and record the numbers in the bead comment.
- **LLM context work**: verify in Comet's LLM sidebar with the exact prompt or
  interaction used. Record what the sidebar could and could not access.
- **Docs-only work**: verify links, command accuracy, `git diff --check`, and
  `br sync --status`.

## Artifacts

- Keep temporary Browser/Playwright output out of commits unless it is useful
  evidence for a review.
- If a screenshot or trace should be kept, store it under `output/playwright/`.
- Do not create new top-level artifact folders.

## Close-out standard

A bead is done only when all three are true:

1. The behavior is implemented or the research question is answered.
2. The owning docs are updated or explicitly not affected.
3. The bead has a verification comment with the command/browser flow and result.

