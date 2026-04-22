# Native browser find via shadow text layer

Proposal for making native browser find (`Cmd+F`) index the full PDF text
without forcing the visible render window open across the entire document.

## Context

Today the viewer deliberately hides most page content outside the current
buffer window:

- `.pf > .pc { display: none !important; }`
- `.pf.pdf2html-force > .pc { display: block !important; }`

That design is correct for paint and interaction cost, but it means native
browser find only sees the currently rendered subset of the document. This
is already called out in [ADR 0002](adr/0002-render-window-and-cursor-pin.md):
rendered pages are the pages scanned by find.

The goal here is narrower than "replace all search":

- keep the existing visible render-window model
- make native `Cmd+F` index the entire document
- avoid paying the full cost of rendering every `.pc`
- ideally let browser-find navigation still land on the right visible page

## Chromium behavior that matters

Local probe in Chromium/Comet established the key browser constraint:

- text inside `display: none` is **not** findable by browser find
- text that remains in the DOM/layout tree but is visually hidden via
  clipping / offscreen positioning **is** findable

That means a "hidden searchable layer" is viable, but only if it stays
rendered enough for Chromium's find indexer. A shadow layer implemented
with `display: none` will not work.

## Proposed shape

### Keep the current visible layer

Do not weaken the current render-window contract for `.pc`. The whole point
of the existing model is to control visible DOM and paint work. The shadow
layer should be additive, not a replacement.

### Add a per-page shadow text layer

For each `.pf`, inject a second lightweight text container that exists only
to feed native browser find.

Rough shape:

```html
<div id="pf2a" class="pf" data-page-no="42">
  <div class="pc">…visible pdf2htmlEX page…</div>
  <div class="pdf2html-find-shadow" aria-hidden="true">
    Chapter title…
    Actual page text…
  </div>
</div>
```

Important constraints:

- the shadow layer must live under the page wrapper, not in one giant
  document-global blob
- it must be visually hidden, not `display:none`
- it must not intercept pointer, focus, or selection behavior intended for
  the real PDF text layer

Suggested CSS shape:

```css
.pdf2html-find-shadow {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: pre-wrap;
  pointer-events: none;
}
```

This keeps the content present for browser find while making it visually
inert.

## Why per-page, not one global hidden transcript

Putting the searchable text inside each page wrapper gives native browser
find a location that is naturally associated with the page. That makes it
more likely that browser-find navigation scrolls to the right page, rather
than to some detached hidden transcript appended elsewhere in the document.

One giant transcript at the end of the body is simpler, but the UX would
likely feel wrong: find would be searching "the document", but navigation
would be anchored to an unrelated hidden region.

## Two implementation levels

### V1

### Goal

Prove that native browser find can index the whole PDF without `render-all`.

### Shape

- build plain text for each page
- mount one clipped/offscreen shadow text block per page
- leave native browser find otherwise untouched

### Expected result

This is the fastest path to validating the core idea. It should make
`Cmd+F` count and navigate across the whole document while preserving the
current visible render window.

### Limitations

- the active browser-find match may live in the shadow layer rather than in
  the visible pdf2htmlEX text nodes
- native browser highlight may be invisible or confusing because the match
  lives in the hidden surrogate layer
- scrolling should still land near the correct page, but the match affordance
  may not feel "attached" to the visible text

V1 is the best proof-of-concept, not the best final UX.

### V2

### Goal

Make native browser find feel like it is operating on the visible PDF even
though indexing comes from the shadow layer.

### Shape

In addition to the shadow text, store offset maps per page:

- concatenated plain text for the page
- mapping from text offsets back to source `.t` nodes / text-node offsets

At runtime:

- when browser find moves the selection into the shadow layer, detect that
  via `selectionchange`
- resolve the selected shadow-text span back to the real visible page text
- paint a custom highlight over the real `.pc` text nodes
- force-render that page if it is currently outside the visible buffer

### Expected result

This is the first version likely to feel like the intended UX:

- `Cmd+F` indexes the full document
- native find navigation lands on the right page
- the visible page shows the actual hit
- the render window can remain narrow most of the time

### Cost

This requires more metadata and more runtime bookkeeping than V1, but it is
much more likely to match the intended reading/search experience.

## Recommendation

Build this in two steps:

1. Implement V1 first to validate the Chromium behavior on real textbooks.
2. If that works, continue to V2 rather than stopping at V1.

Reasoning:

- V1 is the lowest-risk technical probe.
- V2 is the version most likely to satisfy the actual UX goal.

In other words:

- V1 is most likely to work quickly
- V2 is most likely to work the way the user wants

## Metadata and cache shape

The cleanest place to derive the shadow text is during conversion or cache
upgrade, not on every document open.

Suggested cache-side artifact:

```json
{
  "version": 1,
  "pages": [
    {
      "page": 1,
      "text": "…plain text for page 1…",
      "runs": [
        {
          "start": 0,
          "end": 12,
          "selector": "#pf1 .t:nth-of-type(1)",
          "nodeOffsetStart": 0,
          "nodeOffsetEnd": 12
        }
      ]
    }
  ]
}
```

V1 only needs `page` + `text`.
V2 needs the offset/run mapping as well.

This fits the current repo model:

- conversion scripts generate the heavy artifacts once
- `upgrade-cache.sh` can backfill old entries
- overlay JS stays focused on runtime behavior

## Risks and open questions

- The shadow layer still adds DOM. It is far cheaper than rendering all
  pdf2htmlEX page content, but it is not free.
- Very large books may require careful text normalization so the shadow text
  matches what browser find and copy/paste users expect.
- The browser does not expose the native find query directly to page JS.
  The reliable sync point is the selection/range after browser find jumps.
- Browser-find scrolling is browser-owned. Per-page shadow placement makes
  the outcome more plausible, but exact behavior needs testing against real
  documents.

## Suggested implementation order

1. Add cache-side per-page plain-text extraction.
2. Mount per-page shadow text blocks in the overlay.
3. Test `Cmd+F` on several real textbooks with the normal narrow buffer.
4. If page navigation works but visible highlighting feels wrong, add V2's
   offset maps and selection-to-visible-highlight sync.

## Related

- [ADR 0001](adr/0001-pdf-to-html-engine-pdf2htmlex.md)
- [ADR 0002](adr/0002-render-window-and-cursor-pin.md)
- [pdf2htmlEX DOM structure reference](pdf2htmlex-dom.md)
- [Cache design](cache.md)
