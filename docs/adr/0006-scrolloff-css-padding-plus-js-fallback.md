# ADR 0006 — Scrolloff: CSS scroll-padding plus JS fallback for programmatic selection

**Status**: Accepted
**Date**: 2026-04-22
**Supersedes**: §B of [ADR 0002](0002-render-window-and-cursor-pin.md) (cursor
pin model — replaced by the layered design below).

## Context

The viewer needs a vim-like `scrolloff` contract: **while text is being
selected, the selection focus never leaves a configurable band of the
viewport.** The slider runs 0-50% of viewport height; 0% = off, 50% = pin to
center.

Four distinct modalities move the selection focus:

1. **Mouse drag.** User clicks and drags past the viewport edge. Chrome
   runs its own drag-past-edge auto-scroll — a dedicated code path that
   continuously scrolls while the mouse stays outside the scroll container.
2. **Native keyboard.** `shift+arrow` extends the selection. Chrome's
   focus-into-view logic scrolls on each keypress.
3. **Programmatic `Element.scrollIntoView` calls** from our own code:
   outline clicks, hash fragment navigation, `:gg` / `:G`, search-next,
   resume-position restoration.
4. **Vimium caret / visual mode.** Vimium's content script moves the
   selection by calling `Selection.modify('extend', 'forward', 'line')` and
   friends — a **programmatic Selection API call**, not a keyboard event
   the browser sees.

Modalities (1)-(3) are all driven inside Blink and converge on the same
scroll-into-view primitive. Modality (4) is fundamentally different: Chrome
does **not** auto-scroll for programmatic Selection API changes. This was
verified experimentally — calling `sel.modify('extend', 'forward', 'line')`
eighty times leaves `scrollTop` at `0`. The engine's stance is "the site
meant exactly this; don't second-guess."

Any solution built around a single mechanism therefore cannot cover all
four. Past attempts:

- **Pure JS `selectionchange` handler** (original design, ADR 0002 §B).
  Covered Vimium but raced with Chrome's native scroll on mouse/keyboard:
  both mechanisms adjusted on every change, each using a slightly different
  baseline, producing perceptible jitter. Also had an `isCollapsed` guard
  that excluded Vimium *caret* mode entirely.
- **Pure CSS `scroll-padding`.** Clean and scales across screen/zoom.
  Works beautifully for (1)-(3) because those paths honor `scroll-padding`.
  Silently no-ops on (4) — Vimium caret/visual felt broken.
- **`Element.scrollIntoView` on the focus's parent node in the JS
  handler.** Respects `scroll-padding` automatically, so would have been
  the cleanest shape. Broke on pdf2htmlEX output: its `.t` text nodes
  have `font-size: 1px` plus a `transform: scale(…)`. `scrollIntoView`
  uses the **untransformed layout rect** — a near-zero box at an
  unrelated position — so scrolls landed up to ~170px from where the
  caret actually renders. `Range.getBoundingClientRect()` returns the
  post-transform **visual rect** and is correct; `Element.scrollIntoView`
  is not.
- **Always-smooth `pc.scrollBy({behavior:'smooth'})`.** Chrome's smooth
  scroll animates over ~300ms. Held `j` in Vimium fires selection updates
  every ~30ms — 10× faster than the animation completes. Each new scroll
  cancels the in-flight one and restarts; net `scrollTop` falls farther
  and farther behind the caret. Most visible at page boundaries where the
  inter-page margin adds to the per-press delta.

## Decision

Two mechanisms, layered. They enforce the **same** contract against the
**same** parameter, but cover disjoint modalities.

### Layer 1 — CSS `scroll-padding` on `#page-container`

`assets/overlay.css`:

```css
#page-container {
    scroll-padding-top:    var(--pdf2html-scrolloff, 25%);
    scroll-padding-bottom: var(--pdf2html-scrolloff, 25%);
}
```

`assets/overlay.js::applyScrollOffStyle()` writes the variable:

- `pinned=false` → `--pdf2html-scrolloff: (fraction × 100)%`
- `pinned=true`  → `--pdf2html-scrolloff: 50%` (safe region collapses to
  a single center line; `block:'nearest'` targeting any small rect puts
  it at center — Vim `scrolloff=999`).

Called from the setters (`__pdf2htmlSetScrollOff`, `__pdf2htmlSetPinned`)
and the settings panel change handlers, so the slider / `:scrolloff N` /
`:pin` all flow through one point.

Covers modalities (1)-(3): Chrome's own scroll-into-view paths honor
`scroll-padding` natively.

### Layer 2 — `selectionchange` handler for programmatic selection

`assets/overlay.js::mountCursorPin()`:

```js
document.addEventListener('selectionchange', function () {
    if (dragging || raf) return;
    raf = requestAnimationFrame(function () {
        // focus Range → visual rect → delta vs band → scrollBy
        ...
    });
});
```

Key properties, each addressing a specific failure of prior attempts:

- **Reads the focus via `Range.getBoundingClientRect()`, not the element.**
  Range rects respect pdf2htmlEX's transform; element rects don't
  (see Context, alternative #3).
- **No `isCollapsed` guard.** Covers Vimium *caret* mode (collapsed) as
  well as *visual* mode (non-collapsed).
- **Same band math as the CSS layer.** The handler computes `delta`
  against `h * scrollOffFraction`, which matches the `scroll-padding`
  percentage. On native paths (where layer 1 has already scrolled), the
  focus is already inside the band and `delta ≈ 0` — the handler
  no-ops. No racing.
- **Suppressed while a mouse button is held** (`mousedown` → `dragging
  = true`, `mouseup` → `false`). Chrome's drag-past-edge auto-scroll is
  a separate code path that does *not* honor `scroll-padding`; if the
  handler also scrolled every drag-update, it would yank the caret
  inward while the user is still holding at the edge to continue
  scrolling, killing the drag-scroll feature.
- **Adaptive smooth / instant.** Keeps `lastScrollTs`; if the previous
  scroll was within `RAPID_WINDOW_MS` (180ms), uses `behavior: 'auto'`
  (instant) so held `j` doesn't accumulate animation debt; otherwise
  uses `behavior: 'smooth'` so isolated jumps animate naturally.
- **rAF-throttled.** At most one scroll per frame regardless of event
  frequency.
- **Zero-rect guard** (`rect.top === 0 && rect.bottom === 0 && rect.left
  === 0`). Collapsed ranges at DOM edges or inside empty text nodes
  sometimes return all-zero rects — treat as "no reliable caret
  position" and bail that frame.

Covers modality (4) exclusively in practice: on (1)-(3), native has
already satisfied the contract and the handler no-ops.

## Rationale

**Why not force a single mechanism.** The four modalities divide cleanly
along a Blink-internal boundary: (1)-(3) flow through Chrome's scroll-into-
view engine; (4) doesn't. No JS configuration bridges that gap — the
engine genuinely doesn't run the code path for programmatic Selection
changes. Conversely, re-implementing native behaviors in JS (mouse drag
past edge, keyboard focus-into-view) would reproduce work the browser
already does correctly — and historically raced with it (ADR 0002 §B).

The layered design gives each mechanism exactly the modality set it fits
and a no-op relationship when they overlap.

**Why `scroll-padding` over `scroll-margin`.** `scroll-margin` is set on
the *target* element; every `.pf` and every selectable child would need
it. `scroll-padding` is set once on the scroll container and applies to
all scroll-into-view operations inside it. One CSS variable, one knob,
every path affected.

**Why the same band math in both layers.** The two enforcers use the
same `scrollOffFraction` input and compute the same safe-region `[margin,
h - margin]`. Consequence: on modalities (1)-(3), when the handler fires
after native has scrolled, it sees the focus already inside the band and
does nothing. If the two layers used different band definitions, the
handler would always "correct" native's work and reintroduce the ADR 0002
jitter.

**Why adaptive smoothness, not one or the other.** Smooth scroll is
desirable for isolated moves (clicking a search result, a single `:gg`)
because it gives the user a sense of motion and location. It is
actively harmful for held-key continuous input because its ~300ms
animation can't complete before the next input arrives, and each new
scroll cancels the in-flight one. The 180ms threshold falls inside a
typical smooth-scroll duration but well above a key-repeat interval, so
a single scroll gets the full animation and a held key degrades cleanly
to instant tracking.

**Why suppress on `mousedown`, not detect "programmatic vs event-driven"
selection changes.** There is no API to distinguish programmatic
Selection changes from event-driven ones. `mousedown` / `mouseup` is a
good-enough proxy for "Chrome's drag-autoscroll might be running" — the
modality we specifically want to leave alone.

**Why CSS variable rather than re-setting `scroll-padding` directly.**
The slider lives in JS; `scroll-padding` lives in CSS. A CSS custom
property is the single handoff point. One `setProperty` call, browser
re-resolves the cascade, all scroll-into-view paths see the new value
next frame.

## Consequences

### Accepted downsides

- **Two enforcers to keep in sync.** If someone changes the band formula
  in one layer but not the other, they drift. Defense: both read the
  same `scrollOffFraction` and `pinned` state; the math is identical in
  one place (`mountCursorPin`) and one CSS rule. Any future change to
  "what is the band" must touch both or neither.
- **During rapid held-key input, focus hovers near the band edge.**
  Instant scroll catches up each frame, but the per-frame selection
  advance means the caret sits close to the band boundary rather than
  at the center of the viewport. Characteristic of tracking any
  continuously-moving target; the same tradeoff applies to Vim's own
  `scrolloff` with fast cursor motion. Tolerable.
- **First selection-change after `mouseup` can still fire the handler.**
  If the user released mid-drag with the caret outside the band, the
  handler will yank it inside on the next `selectionchange`. Small
  one-time jump. Acceptable; the alternative (debouncing after
  mouseup) adds state for a minor polish.
- **Range zero-rect guard silently skips frames.** At DOM edge cases
  the handler does nothing for that frame. Next valid selectionchange
  catches up. Invisible in practice.

### Wins

- Slider is a single knob: changes `--pdf2html-scrolloff` and
  `scrollOffFraction` together; every modality tracks the change
  without touching `localStorage` or reloading.
- Zoom / window-resize is a no-op: `%` values resolve against the live
  scroll-container size; JS math reads live `pc.clientHeight`.
- All native scroll-into-view callers — outline clicks, hash anchors,
  `:gg`/`:G`, search-next, resume-position — honor the scrolloff for
  free via layer 1, no code touched at each call site.
- Vimium caret and visual mode work end-to-end across page boundaries
  without the old mechanism's racing or jitter.

## Related

- [ADR 0002](0002-render-window-and-cursor-pin.md) — original cursor pin
  design. §B superseded by this ADR; §A (render window) stands unchanged.
- [ADR 0005](0005-vimium-scroll-scoping-via-synthetic-activation.md) —
  scoping `j`/`k` scroll target, a different Vimium-interop decision.
- `assets/overlay.js` — `applyScrollOffStyle()`, `mountCursorPin()`
- `assets/overlay.css` — `#page-container { scroll-padding-top/bottom }`
- `docs/pdf2htmlex-dom.md` — transform semantics of `.t` text nodes
  (the reason `Element.scrollIntoView` can't be used in layer 2)
