# ADR 0002 — Rolling render window + cursor pin

**Status**: Accepted
**Date**: 2026-04-21

## Context

pdf2htmlEX output for a textbook is large — 797 pages of absolutely
positioned text fills ~40MB of HTML and inflates into a massive DOM once
all pages are rendered. Three competing tensions:

1. **Find-mode performance.** Vimium's `/` (and native `⌘F`) scan all
   rendered text. The more pages are rendered, the slower find is and
   the more irrelevant matches swamp the results.

2. **Cross-page keyboard selection.** A selection extended via Vimium
   visual-mode `j` needs the target text in the DOM to extend into. If
   the target page is hidden, selection stops at the last visible one.

3. **Viewport-follow during selection.** When the user mashes `j` in
   visual mode to select across pages, the viewport needs to follow the
   moving selection focus smoothly — stuttering scrolls are tiring.

pdf2htmlEX ships its own runtime that tries to solve (1) by lazy-rendering
only pages near the viewport. Its window is tiny (±1 page), which makes
(2) and (3) painful: selection can't cross page boundaries, and the
scroll-driven render-timer causes visible flash when pages come/go.

Earlier attempts and their failures:

- **`.pc { display: block !important }` global.** Forces every page
  rendered. Fixes (2)+(3) but destroys (1) — find scans all 797 pages.
- **`contain: layout paint style` on every `.pf`.** Tried to isolate
  paints to reduce flash. On 797 elements this promoted 797 composite
  layers; the compositor reconciliation at scroll-end made the flash
  *worse*, not better.
- **Edge-band viewport follow (`scrollIntoView` when focus leaves
  20%/80%).** Felt jittery — each `j` crossing the band caused a ~30%
  viewport jump back to center. Reading-tiring.
- **`content-visibility: auto`.** Clean and native, but removes fine
  control over what find-mode scans (browser auto-reveals matches).
  Conflicts with our explicit buffer-control UX.

## Decision

Two complementary mechanisms, both implemented in `assets/overlay.js`:

### (A) Rolling render window via IntersectionObserver

- **Neutralize pdf2htmlEX's own render loop** at load time:
  `window.pdf2htmlEX.defaultViewer.render_timer = null`,
  `render = () => {}`. Clears its setTimeout, replaces the method with a
  no-op. Retry with a 20ms-interval poll because the viewer object may
  not exist yet on our first attempt.
- **CSS baseline**: `.pf > .pc { display: none !important }`. Every page
  hidden by default.
- **Opt-in via class**: `.pf.pdf2html-force > .pc { display: block !important }`.
  More-specific rule wins. Specificity is `(0,3,0)` vs `(0,2,0)` —
  browser guarantees correct cascade.
- **IntersectionObserver** with `root: #page-container`, `rootMargin:
  '-20px 0px'`, `threshold: 0`. Maintains a `Set<pageIndex>` of
  currently-visible pages. On any change, schedules an `apply()` via
  `requestAnimationFrame`.
- **`apply()`** picks `first = min(visible)`, `last = max(visible)`,
  computes `from = first - buffer`, `to = last + buffer`, toggles the
  `pdf2html-force` class on pages accordingly. Check-before-toggle
  avoids redundant DOM writes.
- **Render-all fast path.** When the user ticks "Render all pages",
  `apply()` forces every page once, then sets an `allForced` flag. All
  subsequent observer callbacks return immediately — no 797-iteration
  loop per scroll event.
- **Buffer control surfaces in the sidebar**: "Render ±N pages around
  viewport" input, persisted to `localStorage`. Default 10.

### (B) Cursor pin for viewport follow

- Listen to `selectionchange`, rAF-throttle.
- On fire: compute the selection focus's `y` relative to `#page-container`,
  compare to `pinFraction * pc.clientHeight`, scroll by the exact delta.
- Net effect: the cursor stays at a fixed vertical position (default
  50%, configurable 0-100%), the page flows past it. Mimics Vim's
  `scrolloff=999` with `set scrolloff=999` / `:zz`-like behavior.
- Pin fraction persists in `localStorage`.

## Rationale

**IntersectionObserver over cached offsets.** Earlier iterations cached
each page's `offsetTop`/`offsetHeight` at load and did manual overlap
math on scroll. This broke on zoom because offsets went stale. Refreshing
offsets on every resize was expensive on 797 pages (forced layout reads).
IntersectionObserver sidesteps both: the browser maintains intersection
geometry internally and invalidates it automatically when the root
resizes. Less code, fewer bugs.

**Class-based `!important` over inline-style toggling.** pdf2htmlEX's
runtime sets `.pc.style.display` inline. Our class-based rule with
`!important` wins against non-`!important` inline. Using class toggles
instead of direct `.style.display` writes also keeps the browser's
style cascade auditable (easier to debug via devtools).

**Separate fast path for render-all.** The first implementation ran
`apply()` identically whether buffer mode or render-all mode was active.
In render-all, all 797 pages always satisfied `want`, so no DOM mutations
happened — but the `classList.contains()` reads still ran. On a fresh
scroll, style bits are dirty, so even `classList.contains()` triggers a
style recalc for the element. 797 of them on the post-scroll frame
caused a visible flash. The fast path returns on a boolean check.

**Cursor pin over edge-band.** With edge-band, `j` inside the band does
nothing; crossing the band causes a ~30% viewport jump. Reads as
stuttering. With pinning, every `j` scrolls the container by exactly
one line — continuous motion, cursor stationary, page flows. Feels like
reading, not like navigating.

## Consequences

### Accepted downsides

- **Render-all mode inflates find-mode scope.** Unavoidable: pages
  rendered = pages scanned by find. The buffer input is how users trade
  off. When reading a specific chapter, set buffer low and find only
  matches within context; when searching across a whole book, toggle
  render-all and accept the scan cost.

- **IntersectionObserver is post-scroll.** There's a frame or two of
  delay between "page scrolled into view" and "class applied". On a
  fast scroll, you can briefly see a page appear blank before content
  renders. Not visually painful in practice; `rootMargin: '-20px 0px'`
  reduces edge flicker; the browser handles it quickly enough.

- **Outline tracker still uses cached offsets.** The sidebar
  outline-active-tracker does its own page-overlap math with cached
  offsets (not the observer). Acceptable because wrong highlight is
  purely cosmetic; it re-syncs on any meaningful scroll.

- **Cursor pin changes scroll on every selection change.** Normal for
  Vim feel; surprising first time you click a plain cursor in the text
  (no selection → no pin). We guard against collapsed selections to
  avoid surprising pin behavior on a simple click.

### Wins

- Zoom is a no-op: `⌘+`/`⌘-` refactors the layout, observer
  re-evaluates automatically, next scroll is correctly classified.
- Render-all vs buffer is a live toggle with immediate effect; no
  reconversion.
- `20d` (select 20 half-pages in visual mode) works end-to-end — pages
  enter the render window in time, selection extends cleanly, pin keeps
  the cursor anchored.

## Related

- ADR 0001 (pdf2htmlEX choice; provides the output we wrap)
- `assets/overlay.js` — `mountRenderWindow()`, `mountCursorPin()`,
  `killPdf2htmlExRenderLoop()`
- `assets/overlay.css` — the `.pf > .pc` / `.pf.pdf2html-force > .pc`
  pair
- plan.md §6 (feature registry — full behavior list)
