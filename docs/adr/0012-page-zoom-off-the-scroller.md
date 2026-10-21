# ADR 0012 — Page Zoom Lives on the Pages, Not the Scroller

**Status**: Accepted
**Date**: 2026-10-08

## Context

The overlay auto-fits each document so its first page fills ~85% of the
window width, and `:zoom N` sets a manual multiplier. That zoom was applied as
CSS `zoom` on `#page-container`, which is also the element Vimium scrolls.

In Chromium, a zoomed scroll container measures `scrollTop`, `scrollBy` and
`clientHeight` in its own unzoomed coordinate space. Vimium's `j` asks for a
60 px `scrollBy`, so on screen it moved 60 × zoom px. In a 1440 px-wide window
the auto zoom was about 2.06, and one `j` moved 123 px. A single `d` happened
to stay correct because Vimium sizes it from `clientHeight`, which is in the
same zoomed units. Held `j` and `d` were both too fast, because Vimium
calibrates continuous scrolling toward a fixed speed in those units. The error
grew with window width, and Vimium's scroll-step setting meant something
different in the viewer than on any other page.

The same unit mix affected overlay code. The scrolloff band, caret pin and
search scroll compared `getBoundingClientRect` values (screen px) with
`pc.clientHeight` (zoomed units). The sidebar page shift was multiplied by the
zoom. `e`/`q` page steps applied their 8 px lead-in in zoomed units.

## Decision

Apply the zoom to the pages, not the scroller. `overlay-zoom.js` writes
`--pdf2html-zoom` on `#page-container`, and `overlay.css` applies it as
`zoom` on each `#page-container > .pf`. The scroller is never zoomed, so its
`scrollTop`, `scrollBy` and `clientHeight` are screen pixels. That is the same
unit as `getBoundingClientRect` and the same unit Vimium assumes.

Page positions are derived from rects, in scroller coordinates, by the
document model (`pageExtent`, `scrollToPage`, `mostVisiblePage`,
`viewAnchor`/`restoreViewAnchor` in `overlay-document.js`). A zoomed page's
own `offsetTop`/`offsetHeight` are in page-local units and must not be mixed
with scroller offsets.

pdf2htmlEX's runtime mixes page `offsetTop` with container `scrollTop` for link
navigation and its current-page index. `assets/overlay-pdf2htmlex.js` rebuilds
those entry points on the document model (`view_position`, `scroll_to`,
`cur_page_idx`). pdf2htmlEX's own zoom (`rescale`, bound to Ctrl/Cmd +/−/0) is
routed into the overlay zoom, so there is one zoom system and it persists per
document.

Zoom changes (`:zoom`, the settings slider, auto-fit on resize) keep the
reading position explicitly. They record the page under the viewport top and
the fraction into it, apply the new zoom, and scroll back to that fraction.

## Rationale

- **Fixes the cause, not one consumer.** Vimium cannot know about our zoom.
  With an unzoomed scroller, Vimium's steps, its step-size setting and its
  continuous-scroll calibration behave exactly as on ordinary pages, with no
  key interception.
- **One unit in the scroller.** Overlay code that scrolls by an on-screen
  measurement is correct by default. The remaining zoom quirk, page-local
  `offset*` on `.pf`, is narrow, has one owner, and can be found with
  `rg 'offset(Top|Height)'`.
- **Rejected: intercept `j`/`d` in the overlay** and scale or reimplement
  Vimium's smooth scroll. That duplicates Vimium, breaks its settings and
  conflicts with ADR 0003's coexistence model.
- **Rejected: zoom a wrapper inside the scroller.** pdf2htmlEX treats each
  page's `parentNode` as the scroller (`view_position` reads
  `parentNode.scrollTop`). A wrapper breaks its navigation outright and still
  leaves page offsets in zoomed units.

## Consequences

- `j`, held `j` and `d` scroll the same screen distance as on ordinary web
  pages, independent of window width and zoom.
- The scrolloff band, caret pin and search scroll now compare like units. The
  sidebar shift divides by `--pdf2html-zoom` in CSS because it is applied
  inside the zoomed page.
- The overlay now owns part of pdf2htmlEX's runtime behavior. After a
  pdf2htmlEX upgrade, re-check `Page.view_position`, `Viewer.scroll_to`,
  `update_page_idx` and `rescale` against the adapter.
- Changing the zoom no longer preserves the position as a side effect of
  unchanged `scrollTop` units; the zoom module does it explicitly.
- The outline highlight follows the page counter's `pdf2html-page-change`
  instead of caching page offsets. That removes the stale-offset exception
  `docs/pdf2htmlex-dom.md` used to allow, and follows the reasoning in
  ADR 0002 for preferring live geometry to cached offsets.
- `scripts/verify-overlay.sh` (geometry group) checks these invariants against a
  real cached document.

## Related

- ADR 0002 (render window, outline tracker offsets), ADR 0003 (Vimium
  coexistence), ADR 0005 (Vimium scroll scoping), ADR 0006 (scrolloff)
- `assets/overlay-zoom.js`, `assets/overlay-document.js`,
  `assets/overlay-pdf2htmlex.js`
- `docs/pdf2htmlex-dom.md`, "Zoom and scroll geometry"
