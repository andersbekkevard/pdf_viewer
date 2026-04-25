# ADR 0008 — Proposed mode-aware extension keygate for Vimium coexistence

**Status**: Proposed
**Date**: 2026-04-24

## Context

The proposed `:finger` mode wants tmux-fingers-style labels: many targets on
the visible PDF page, each selected by typing one or more letter hints.

The current keyboard strategy deliberately avoids fighting Vimium. ADR 0003
routes new feature entrypoints through the command palette unless a key is
known to be safe. This works for mode entry, but it constrains the hint
alphabet once finger mode is active: Vimium can still consume letters such as
`f`, `F`, `g`, `y`, `m`, `o`, and others before the page overlay sees them.

Vimium's pass-through configuration is origin/key based, not mode based. Adding
the full tmux-fingers alphabet to the `localhost:7435` pass-through list would
make finger labels easy, but would also disable Vimium commands on the viewer
even when finger mode is not active.

## Proposal

Investigate a mode-aware keygate inside the existing `extension/` package.

The extension would add a static content script for `http://localhost:7435/*`
with `run_at: "document_start"`. That script would install a capture-phase
`keydown` listener immediately. The listener would normally do nothing, letting
Vimium and the page behave as they do today.

When the overlay enters a mode that needs temporary key ownership, such as
finger mode, it would signal the content script through the shared DOM. Possible
signals:

- a `document.documentElement.dataset.pdf2htmlKeygateMode = "fingers"` flag
- a `CustomEvent("pdf2html-keygate-mode", { detail: { mode: "fingers" } })`
- both, so late content-script reloads can recover the current state

While active, the content script would intercept only an explicit whitelist of
keys needed by that mode, suppress the original event, and forward the key to
the page overlay through another DOM event:

```text
keydown "a"
→ extension content script sees keygate mode = fingers
→ preventDefault() + stopImmediatePropagation()
→ dispatch CustomEvent("pdf2html-keygate-key", { detail: { key: "a", ... } })
→ overlay updates its hint prefix
```

When the overlay exits the mode, it clears the DOM mode flag and dispatches the
mode event again. The content script returns to pass-through behavior.

## Open Question

Can this reliably run before Vimium?

The answer appears to be "not by contract." Vimium also injects a
`document_start` content script and installs capture-phase key listeners on
`window`. Chrome documents `run_at` timing and file order inside one extension,
but not a stable priority API between separate extensions.

Chromium appears to order same-stage content scripts by extension pipeline
order, often correlated with install order. A local setup could probably make
`pdf_viewer` run before Vimium by installing `pdf_viewer` first or reinstalling
Vimium afterward. That is an implementation detail, not a design guarantee.

## Rationale

**Mode-aware pass-through is the desired UX.** The viewer should be able to own
the full hint alphabet only while a mode is active, then hand normal letters
back to Vimium immediately afterward.

**The extension is already part of this system.** Adding a narrowly-scoped
content script to the redirect extension is less invasive than forking Vimium
or requiring a large permanent pass-through list.

**The risk is priority, not capability.** Content scripts can listen for DOM
keyboard events and can communicate with the page through the DOM. The
uncertain part is beating Vimium consistently when both extensions want the
same capture-phase event.

## Consequences

### If accepted later

- Finger mode can use a tmux-fingers-like alphabet without permanently giving
  up Vimium's normal commands on `localhost:7435`.
- The extension grows from a redirect/navigation helper into a small runtime
  interop layer.
- The overlay needs a mode-state contract that the extension can observe.

### Risks

- Ordering may change across Chrome/Comet versions, extension reloads, or
  install order.
- A broken keygate could swallow letters while the user expects Vimium or page
  input to receive them.
- Debugging becomes harder because keyboard ownership is split between the page
  overlay, this extension, and Vimium.

### Guardrails if implemented

- Keep the feature opt-in behind a setting until proven stable.
- Match only `http://localhost:7435/*` and `http://127.0.0.1:7435/*`.
- Intercept only while an explicit mode flag is active.
- Intercept only a per-mode whitelist, never all keys.
- Provide an emergency exit key that is already known to work without the
  keygate, such as `Esc`.
- Log mode transitions and swallowed keys in development builds.

## Current Decision

Do not block V1 finger mode on this. V1 uses the command palette and `Ctrl-f`
for entry, with `Ctrl-f` requiring the normal Vimium pass-through setup. Once
active, V1 still uses a Vimium-safe hint alphabet. Treat this ADR as a proposal
for a later spike if the smaller alphabet feels too constrained.

## Related

- ADR 0003 — Keyboard shortcut design under Vimium
- `docs/keybindings.md` — current Vimium pass-through list
- `extension/manifest.json` — existing MV3 extension
- `assets/overlay.js` — future finger mode entry and mode-state source
