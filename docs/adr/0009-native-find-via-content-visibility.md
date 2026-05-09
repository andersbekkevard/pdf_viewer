# ADR 0009 — Native Cmd-F via `content-visibility: auto`

**Status**: Accepted
**Date**: 2026-05-09
**Supersedes**: [ADR 0007](0007-native-browser-find-shadow-layer.md)

## Context

ADR 0007 added a per-page surrogate text layer (`<hash>/text.json` →
clipped 1×1 px `.pdf2html-find-shadow` nodes under each `.pf`) so Chromium's
native Cmd-F could index pages outside the rolling render window from
ADR 0002. The shadow approach was the cheapest way to keep
`display: none` on offscreen `.pc` elements while still letting native find
"see" their text.

In practice the shadow architecture produced five compounding failures, all
visible to the user as Cmd-F matches that don't exist or land on apparently
blank pages:

1. **Match position is wrong.** The shadow is `position: absolute; top: 0;
   left: 0; width: 1px; height: 1px` inside `.pf`. Native find scrolls the
   match's bounding rect into view, so the user lands at the page's
   top-left corner — not at the line containing the match. The 1 px
   highlight is invisible. The page looks blank.

2. **Shadow text drifts from rendered text.** pdf2htmlEX emits Private Use
   Area glyphs (`U+E000–U+F8FF`) for fonts with no Unicode mapping (one
   real cache entry has 41,206 of them across 106 pages). The shadow
   carries those glyphs verbatim; they're unsearchable by humans but still
   counted in the find-bar total. Ligatures embedded mid-word
   (`pairis` instead of `pairs is`) and per-character `.t` divs for
   inline math (`f`, `(`, `n`, `)` rendered as four separate divs joined
   with `\n`) further desync the shadow from what's visible.

3. **Match count flickers under scroll.** The CSS rule
   `.pf.pdf2html-force > .pdf2html-find-shadow { display: none }` deduplicates
   shadow vs. real text per page in steady state, but during scroll the
   IntersectionObserver toggles `pdf2html-force` on each page that enters
   or leaves the buffer. Chromium recounts find matches on every toggle,
   so the find-bar index drifts.

4. **The selection bridge is best-effort.** When native find lands in a
   shadow node, the overlay listens for `selectionchange`, force-renders
   the page, and tries to map the shadow selection back to a real `.t`
   range via exact `String.indexOf` on a re-extracted page text. CID
   glyphs, ligatures, and line-break differences make the strings
   disagree; the bridge falls through silently and the user is left at
   the 1 px shadow with no real selection.

5. **A 2 MB JSON fetch per open.** `cache: "no-store"` to avoid stale
   page-number maps. Adds latency on every navigation to the largest
   books.

The architecture was fighting the browser. A surrogate cannot beat real
layout-tree text for native find: it's a copy that drifts, it's
positionally wrong by construction, and the bridge that papers over both
is heuristic. The only winning move is to put the real text in the
layout tree.

## Decision

Replace the `display: none` gate on `.pc` with
`content-visibility: auto` on `.pf`, and delete the shadow architecture
in its entirety. Two rules are needed:

```css
.pf {
    content-visibility: auto;
    contain-intrinsic-size: auto 1100px;
}
.pf > .pc { display: block !important; }
```

`content-visibility: auto` skips paint and layout for offscreen subtrees
(the same paint-cost win the old gate provided) but keeps the text in
the layout tree, where Chromium's native find indexes it. When a Cmd-F
match lands on an offscreen page, the browser auto-renders the subtree,
scrolls to the actual line with the standard yellow highlight, and the
user sees the same thing they would see in Chrome's built-in PDF
viewer.

`contain-intrinsic-size: auto <h>` reserves space for unrendered pages
so the scrollbar geometry stays stable as pages enter and leave the
viewport. The `auto` keyword lets the browser remember each page's
last-known size and use it on subsequent renders, which is correct for
the mixed page sizes pdf2htmlEX emits.

**Why the second rule is load-bearing.** pdf2htmlEX's runtime injects
an `@media screen { .pc { display: none } }` stylesheet on init and
then calls `show()` on each page it lazy-renders, which adds the
`.opened` class (CSS: `.pc.opened { display: block }`). We neutralize
that runtime in `killPdf2htmlExRenderLoop`, so `.opened` is never
added to anything past the initial 1–2 pages. Without our positive
`.pf > .pc { display: block !important }`, pages 3 onward stay blank
because pdf2htmlEX's injected hide rule wins. The earlier
`.pf.pdf2html-force > .pc { display: block !important }` rule used
to play this role; ADR 0009 had to replace it with an unconditional
positive rule because there is no longer a per-page `pdf2html-force`
class to gate visibility on.

### What was removed

- `assets/overlay.js`: `mountNativeFindShadowLayer`, `mountFindShadowPages`,
  `mountFindShadowPage`, `mountNativeFindSelectionBridge`,
  `shadowElementForRange`, `nodeElement`, `rangeOffsetInside`,
  `promoteNativeFindShadowSelection`, `occurrenceIndexBefore`,
  `nthIndexOf`, `buildRealPageTextIndex`, `realRangeFromIndex`,
  `scrollRealRangeIntoView`, `scheduleIdle`. Also the
  `IntersectionObserver`-driven `apply()` loop in `mountRenderWindow`,
  `ensurePageRangeRendered`, `registerRenderAllHandler`, the
  `pdf2html-force` filter inside `visiblePageFrames`, the
  `:all` / `:buffer` palette commands, the "Render all pages" / "Render
  buffer" rows in the settings modal, and the `pdf2html-all-input` /
  `pdf2html-buffer-input` hidden inputs.
- `assets/overlay.css`: the `.pf > .pc { display: none !important }`
  baseline (the conditional `.pf.pdf2html-force > .pc { display: block }`
  rule was promoted to an unconditional `.pf > .pc { display: block !important }`
  — see Decision above), and the `.pdf2html-find-shadow` rules.
- `scripts/extract-find-text.py` (the per-page text extractor).
- `text.json` generation in `scripts/pdf2html-convert.sh`,
  `scripts/index-directory.sh`, `scripts/index-directory-parallel.sh`.
- `--mode=text` and the inline text-extract step in
  `scripts/upgrade-cache.sh --mode=reconvert`.

### What was kept

- `killPdf2htmlExRenderLoop` is still required (ADR 0002): pdf2htmlEX's
  built-in render loop fights us regardless of which visibility model
  is in effect.
- The cursor-pin, scrolloff slider, and `:pin` / `:scrolloff` palette
  commands, with their hidden inputs.
- All other overlay features (sidebar, outline tracker, page counter,
  resume position, zoom, thumbnails, slash-search, palette).

## Rationale

**`content-visibility: auto` is the platform answer.** Chromium engineers
designed it specifically for paginated thousand-page documents. It
skips offscreen rendering work (paint and layout) but keeps the box
findable, copyable, and selectable. It is the explicitly recommended
pattern for "long documents we want native browser features to work on";
fighting it with surrogates is reinventing it badly.

**The visible render window stops being a JS concern.** `mountRenderWindow`
is now a CSS rule, not an `IntersectionObserver` plus a per-page class
toggle. There is no observer callback to flicker, no class to thrash,
no per-page DOM write on scroll, no `apply()` loop to short-circuit.
The whole "Render all pages" toggle disappears because there is nothing
to toggle: the browser is doing it.

**ADR 0002's old fear about `contain: layout paint style` does not apply
here.** That earlier experiment applied `contain` unconditionally to
every `.pf`, which forced 797 composite-layer promotions and produced
worse compositor flash than the IntersectionObserver model it was
trying to replace. `content-visibility: auto` is eligibility-driven:
the browser only contains subtrees that are actually offscreen, and
its perf model is built around large paginated content. They are not
the same primitive.

**Native parity falls out for free.** The user wanted Cmd-F to feel
identical to Chrome's built-in PDF viewer: instant, indexes everything,
always highlights. Each of those three properties is automatic the
moment the real text is in the layout tree — no JS in the find loop.

## Consequences

### Wins

- **Cmd-F is correct by construction.** Match count, scroll target, and
  highlight all come from real DOM, so they cannot drift from what's
  rendered.
- **No per-document data fetch on open.** `text.json` is gone; the
  conversion pipeline is one step shorter.
- **~290 LoC of overlay JS deleted**, plus ~30 LoC of CSS, plus the
  Python extractor, plus an upgrade-cache mode, plus two settings rows
  and two palette commands. The viewer is materially simpler.
- **Cross-page selection works without `ensurePageRangeRendered`.** Text
  nodes are always in the DOM, so Vimium-visual `j` over multiple pages
  doesn't need the overlay to force-render anything ahead of the
  selection focus.

### Accepted downsides

- **`text.json` files in existing cache entries are now orphaned.** Cheap
  to leave (≤ 2 MB per book); a future `upgrade-cache.sh` mode can
  garbage-collect them, but doing so is not load-bearing.
- **The "Render all pages" power-user knob is gone.** It existed only to
  widen the find-mode scope, which is no longer a user concern.
- **The `A` quick-toggle is gone.** Same reason. Vimium's keymap reclaims
  the binding.

### Open questions / risks

- **Paint flash at extreme page counts.** ADR 0002's earlier compositor
  finding warrants a real test on the 1677-page algorithms book and
  the 1137-page computer-architecture book. If `content-visibility: auto`
  produces visible flash on fast scroll, fall-back is to tighten
  `contain-intrinsic-size` per page-size class (`pc1`, `pc2`, …)
  rather than re-introduce the gate. Manual eyeball test required.

## Related

- ADR 0001 — pdf2htmlEX as rendering engine
- ADR 0002 — rolling render window and cursor pin (the
  IntersectionObserver-driven gate this ADR replaces is the one from
  ADR 0002 §A)
- ADR 0007 — superseded by this ADR
- `assets/overlay.css` — the `.pf { content-visibility: auto }` rule
- `assets/overlay.js::mountRenderWindow` — now a thin shim that just
  installs the scrolloff/pin hidden inputs
