# ADR 0005 — Vimium scroll scoping via synthetic activation events

**Status**: Accepted
**Date**: 2026-04-22

## Context

The overlay has three scrollable chrome containers besides the PDF itself:
the sidebar body (outline / thumbs), the cheatsheet panel, and the settings
modal. When one of those is open, pressing `j`/`k` should scroll it — not
the PDF behind. When none is open, `j`/`k` should scroll the PDF.

`j`/`k` come from Vimium, not from our overlay (see ADR 0003). So "scope
j/k to the open overlay" means "influence Vimium's choice of scroll
target." The naive assumption is that Vimium follows `document.activeElement`
and that a `.focus()` call is enough.

It isn't. Reading Vimium's `content_scripts/scroller.js`:

```js
let activatedElement = null;
// ...
const eventName = Utils.isFirefox() ? "click" : "DOMActivate";
handler[eventName] = (event) =>
  handlerStack.alwaysContinueBubbling(function () {
    const path = event.deepPath || event.path;
    return activatedElement = path ? path[0] : event.target;
  });
```

Key points:

1. Vimium tracks its **own** `activatedElement`, distinct from
   `document.activeElement`. The source comment is explicit: "activatedElement
   is different from document.activeElement — the latter seems to be reserved
   mostly for input elements."
2. `activatedElement` is updated **only** on `DOMActivate` (Chromium) or
   `click` (Firefox) events.
3. `scrollBy` walks up from `activatedElement` to find the nearest
   scrollable ancestor.

Implication: `.focus()` does nothing for Vimium's scroll routing. We have
to synthesize the activation event.

In addition, pdf2htmlEX's generated HTML has a click handler on the PDF
text layer that materializes a tiny selection range when clicked — whether
the click is user-originated or synthetic. With our custom `::selection`
color (`#99C1DA`), that range reads to the eye as "a blue glow around the
PDF" immediately after our activation fires. It persists until the next
user interaction clears it.

## Decision

Scope Vimium's `j`/`k` by **dispatching synthetic activation events** on
the target scroll container whenever overlay state changes. Route focus
declaratively via MutationObservers on `document.body`:

- `sidebar-shown` class toggles → activate sidebar body on show, activate
  `#page-container` on hide.
- Settings / cheatsheet modal nodes added → activate their body, stash the
  previously-activated element.
- Settings / cheatsheet modal nodes removed → re-activate the stashed
  element (typically the sidebar body) or the PDF scroller if none.

Two activation helpers with different event sets, for different targets:

**Overlay containers (sidebar / settings / cheatsheet body)** —
`activate(el)` fires three events:

```js
el.focus({ preventScroll: true });
el.dispatchEvent(new Event('DOMActivate',  { bubbles: true, cancelable: true }));
el.dispatchEvent(new MouseEvent('click',   { bubbles: true, cancelable: true }));
```

- `focus` for native keyboard nav (Tab, arrow-scroll on the focused element).
- `DOMActivate` for Vimium on Chromium.
- `click` for Vimium on Firefox, and belt-and-braces coverage if Vimium
  ever changes its event choice.
- `outline: none` in CSS on these three selectors hides the focus ring
  that would otherwise appear from the `.focus()` call. Focus is plumbing,
  not a visible affordance.

**PDF scroller (`#page-container`)** — `activateMain()` fires the same two
events, then clears any selection:

```js
el.dispatchEvent(new Event('DOMActivate', ...));
el.dispatchEvent(new MouseEvent('click',  ...));
try {
  const sel = window.getSelection();
  if (sel && sel.rangeCount > 0) sel.removeAllRanges();
} catch (e) {}
```

The explicit `removeAllRanges()` is what kills the blue selection glow
that pdf2htmlEX's text-layer click handler would otherwise leave behind.
`focus()` is intentionally not called on `#page-container` — it's not
focusable by default and calling it there has no benefit.

The containers themselves carry `tabindex="-1"` so `.focus()` is a valid
target (without tabindex, `.focus()` silently no-ops on a `<div>`).

## Rationale

**Why not `.focus()` alone.** It's what the documentation-common intuition
suggests, but Vimium's source is explicit: activation is tracked via
`DOMActivate`/`click`, not focus. Verified in-browser with a DOMActivate
listener probe — focus alone leaves Vimium's `activatedElement` unchanged,
so `j`/`k` keeps scrolling the document.

**Why both DOMActivate and click for overlay containers.** DOMActivate
covers Chromium (what we target); click is the Firefox-path parity for
Vimium, and is defensive against any handler-stack version check that
requires a real click. Dispatching both is cheap and the extra listeners
(if any) are our own.

**Why no click on `#page-container`.** pdf2htmlEX's internal click
handler on the text layer is what produces the selection range. We can't
remove that handler without forking pdf2htmlEX's output. We can't
`stopPropagation` cleanly because the text layer's listener may be on
bubble phase and we'd have to own every possible descendant. Clearing
the selection after the fact is simpler, localized to one function, and
doesn't introduce ordering dependencies. Calling focus on `#page-container`
has no effect (non-focusable) and would add confusion — omitted for clarity.

**Why MutationObservers instead of wrapping call sites.** The sidebar
toggles in 5+ places (keybindings `s` / `⌘.`, floating button, backdrop
click, Escape handler, sidebar close button). Modals close via Esc, their
backdrop, and their toggle keys. Wrapping every call site is fragile —
any new close path forgets to fire activation. An observer on the single
canonical signal (body class flip; modal node added/removed) means new
call sites participate automatically.

**Why stash + restore for modals.** Settings can be opened over an open
sidebar. Without restore, closing settings hands `j`/`k` back to the PDF
(via `activateMain()`), which is wrong — the user expects the sidebar to
regain scroll. Stashing `document.activeElement` at modal-open time and
re-activating it on modal-close keeps the layer stack coherent.

**Why `preventScroll: true` on focus.** The browser would otherwise scroll
the focused element into view, which on the sidebar body does nothing
useful but can visibly jump its scroll position.

**Why `outline: none` on the container bodies.** These elements are
focused as an implementation detail for Vimium routing, not because the
user is navigating to them. Showing a focus ring would be incorrect UX
— focus is internal plumbing here.

**Alternatives rejected:**

- *Wait for Vimium to fix it / expose an API.* Vimium exposes
  `globalThis.Scroller`, but content scripts run in an isolated world so
  our overlay can't reach it. Even if it could, relying on Vimium
  internals would be fragile across versions.
- *Tell users to click inside the sidebar to scroll it.* Violates the
  keyboard-native goal (ADR 0003) — the whole point of overlays is that
  they should not require mouse interaction.
- *Set `e.preventDefault()` on the synthetic click to suppress pdf2htmlEX's
  side-effect.* `preventDefault` on `click` doesn't stop listener
  invocation, only the default action. pdf2htmlEX's selection creation
  is a listener-side effect, not a default action — unaffected by
  `preventDefault`. `stopImmediatePropagation` on capture could work but
  requires us to fire the activation *at* the target with a capture guard
  we install first — more moving parts for the same end state as clearing
  the selection after.
- *Inject a 0×0 invisible marker inside `#page-container` and click that
  instead.* Clean-looking, but the click would still bubble to
  pdf2htmlEX's handler and create the same selection. The problem isn't
  the click target, it's pdf2htmlEX's listener on ancestors.
- *Dispatch only `DOMActivate` on the main scroller (skip click).* Tried
  first; Vimium did not re-scope `j`/`k` to the PDF in practice. Possibly
  due to `isTrusted`-based filtering somewhere in Vimium's handler stack,
  or behavior specific to synthesized DOMActivate vs. the click-derived
  variant. Rather than debug Vimium internals, dispatch both and clean up
  pdf2htmlEX's side-effect.

## Consequences

### Accepted downsides

- **The overlay manually synthesizes events that are normally the user's
  domain.** Synthesized click and DOMActivate are "funky" — future
  readers will reasonably wonder why. This ADR is the answer.
- **We depend on Vimium's current activation mechanism.** If Vimium
  changes to rely on `document.activeElement`, or to a different event
  altogether, this breaks and we'd need to revise. `focus()` is still
  called, so a focus-based Vimium would also work — best-effort
  forward-compat.
- **We depend on pdf2htmlEX's click handler creating a clearable text
  selection, not something else.** If a future pdf2htmlEX upgrade sets
  focus on a .pf or starts a caret blink, `removeAllRanges()` won't help
  and a new workaround is needed.
- **`outline: none` loses the focus ring on the scroll containers.** We
  don't rely on it as UX, but accessibility tooling inspecting focus
  state may report them as unmarked focus targets. Acceptable — these
  are not interactive widgets, they're scroll scopes.

### Wins

- `j`/`k` scope to whichever overlay is open, with no keyboard shortcut
  of our own. Free feature from Vimium, correctly plumbed.
- New overlay scroll containers participate automatically — just give
  them `tabindex="-1"` and an entry in `registerFocusRouting`'s
  observer, no per-call-site changes.
- No change to the existing toggle keys, Esc chain, or palette
  behavior. Purely additive.

### Implicit guarantees

- **Any new overlay scroll container must be routed through
  `registerFocusRouting`.** If it isn't, `j`/`k` will scroll the PDF
  behind it — the exact bug this ADR solves.
- **`activateMain()` must keep clearing any selection.** If a future
  refactor removes that step, the blue glow returns on every sidebar
  close.
- **Never rely on `.focus()` alone for Vimium scroll scoping.** That is
  the *first* thing a reader will try to simplify. Don't.

## Related

- ADR 0003 (keyboard shortcut design under Vimium — this ADR is its
  j/k-scroll-scoping counterpart)
- `assets/overlay.js::registerFocusRouting` — the implementation
- `assets/overlay.css` — `outline: none` rules for the three scroller
  bodies, `::selection` color rule that made the glow visible
- Vimium source: `content_scripts/scroller.js` (upstream:
  github.com/philc/vimium) — `Scroller.init` is the canonical reference
  for the `activatedElement` mechanism
- CLAUDE.md "Non-obvious gotchas" (cross-referenced there too)
