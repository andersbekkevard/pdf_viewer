# ADR 0010 — Light HTML With External Rasters And Page Text

**Status**: Proposed
**Date**: 2026-05-21

> Implementation is guarded behind `PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT=1`.
> The memory result is promising, but rollout is blocked by known
> image-resolution, selection, and native-search quality bugs.

## Context

Large pdf2htmlEX books can make the browser renderer enormous. The 1,677-page
algorithms book was the forcing case: the canonical HTML was about 498 MB on
disk, and a headless Chrome renderer reached about 13 GB physical footprint in
the repeatable `footprint -p <renderer> -summary` check.

There were two independent causes:

1. pdf2htmlEX embedded every full-page raster as a base64 `data:` URL in the
   HTML, forcing the browser to parse and retain a huge document payload before
   it even decided which pages were visible.
2. The selectable text layer contained millions of glyph/spacer spans. Keeping
   those nodes in the layout tree is what made ADR 0009's native `Cmd-F`
   behavior work, but the memory cost was too high for book-length documents.

## Decision

Keep the canonical pdf2htmlEX output as `<stem>.html`, but generate a derived
`<stem>.light.html` for normal viewing.

The light variant:

- extracts page rasters into `page-images/0001.png`, `0002.png`, ...;
- rewrites page `<img class="bi">` nodes to use `data-pdf2html-src`;
- lets `assets/overlay.js` mount `src` only for the current viewport plus a
  small margin;
- collapses the glyph-level text layer to one transparent
  `.pdf2html-page-text` node per page;
- marks the document with `data-pdf2html-text-flattened="page"` and
  `body.pdf2html-light`.

The daemon adds `/view-light` and `/view-light-raw`. These serve the light
file when it exists and fall back to canonical HTML otherwise. `/view` and
`/view-raw` remain canonical routes. `mappings.tsv` continues to point at the
canonical file only. Broad generation is disabled until the quality blockers
are fixed.

## Rationale

This keeps rollback cheap. If the light variant has a bad edge case, deleting
`<stem>.light.html` or using `/view` immediately returns to the original
pdf2htmlEX behavior. Existing cache rows do not need migration and stale light
files can be rebuilt with `PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT=1
scripts/upgrade-cache.sh --mode=light` for targeted testing.

External page rasters remove the worst HTML payload without changing visual
fidelity: the page raster is still the source of truth for what the user sees.
Lazy mounting prevents native find jumps from keeping hundreds of decoded
page PNGs alive.

Page-level text is the proposed compromise. It keeps native browser find and
copy on real DOM text, but avoids millions of pdf2htmlEX span nodes. The
canonical route remains available when exact line-level text boxes matter.

## Consequences

### Wins

- The algorithms book's light HTML is about 11 MB instead of about 498 MB.
- The same renderer measurement dropped from about 13 GB on canonical HTML to
  about 1.2 GB on light HTML after a native-find jump.
- Normal opens no longer parse hundreds of megabytes of embedded base64.
- Only nearby page rasters have a live `src`; after a far `window.find()` jump,
  the verified loaded raster count stayed at 6 instead of hundreds.

### Accepted Downsides

- Light mode's native `Cmd-F` target is page-level, not exact line-level. It
  still selects real DOM text and scrolls to the owning page, but the raster is
  the visual source and the searchable text node is transparent.
- Drag selection in light mode is coarser than canonical pdf2htmlEX selection.
  The exact text-layout path is the canonical `<stem>.html` route.
- The cache stores extracted page images next to the canonical HTML. Disk usage
  is not reduced; browser memory is.

## Related

- ADR 0009 — Native Cmd-F via `content-visibility: auto`
- `scripts/externalize-page-images.py`
- `assets/overlay.js::mountExternalPageRasters`
- `docs/cache.md`
