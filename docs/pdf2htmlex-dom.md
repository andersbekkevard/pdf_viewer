# pdf2htmlEX output — DOM structure reference

A quick reference for the HTML our overlay lives on top of. Written so a
future session can modify a selector or event target without trial-and-error.

All examples are real, sampled from actual cached conversions (arbitrary
whitespace trimmed).

## High-level skeleton

```html
<html>
<head>
  <title>…</title>
  <style>…</style>            <!-- pdf2htmlEX's own CSS: utility classes, positioning -->
  <script>…</script>          <!-- pdf2htmlEX's runtime (we kill it, see ADR 0002) -->
  <!-- our injection lives here: overlay.css link + overlay.js script -->
</head>
<body>
  <div id="sidebar">
    <div id="outline">…</div>
  </div>
  <div id="page-container">
    <div id="pf1" class="pf w0 h0" data-page-no="1">…</div>
    <div id="pf2" class="pf w0 h0" data-page-no="2">…</div>
    <!-- one .pf per page, in page order -->
  </div>
  <div class="loading-indicator" />  <!-- unused after we kill the runtime -->
</body>
</html>
```

## IDs of note (unique on the page)

| Selector | What it is |
|---|---|
| `#page-container` | The scrollable root. All `.pf` pages are its direct children. Its `scrollTop` is what we manipulate for cursor pin. Its `getBoundingClientRect()` defines the visible viewport. |
| `#sidebar` | Container for the outline (TOC). We hide/show by toggling `body.sidebar-shown`. |
| `#outline` | The TOC itself — nested `<ul><li><a class="l">`. |
| `#pfN` | The Nth page (1-based, **hex**). Page 1 = `#pf1`, page 10 = `#pfa`, page 213 = `#pfd5`. |

## Page numbering (the hex gotcha)

pdf2htmlEX uses **hex** for page IDs and, in the pinned engine output we use,
also stores that same unprefixed hex value in `data-page-no`. Older notes in
this repo assumed `data-page-no` was decimal; that is false for pages like
`#pf140` (`data-page-no="140"`, decimal page 320). Treat the `#pf...` ID as
authoritative. `a.l[data-dest-detail]` values are PDF-native decimal page
targets.

| Page (decimal) | Element ID | `data-page-no` attr |
|---|---|---|
| 1 | `#pf1` | `1` |
| 9 | `#pf9` | `9` |
| 10 | `#pfa` | `a` |
| 21 | `#pf15` | `15` |
| 213 | `#pfd5` | `d5` |
| 797 | `#pf31d` | `31d` |

So to resolve "user typed `:42`" → the element:
```js
document.getElementById('pf' + (42).toString(16))  // "#pf2a"
```

And to get the page number of an element back:
```js
parseInt(el.id.match(/pf([0-9a-f]+)/i)[1], 16)
```

## `.pf` — page frame (outer page wrapper)

```html
<div id="pf1" class="pf w0 h0" data-page-no="1">
  <div class="pc pc1 w0 h0">
    <!-- page content here -->
  </div>
</div>
```

- Always direct child of `#page-container`
- `w0 h0` reference size classes (see "Utility classes" below) — width/height
  of this specific page. Some docs mix page sizes; `w1 h1` etc. may appear.
- The `.pf` itself is always laid out and takes full page space — it's the
  `.pc` inside that our visibility-toggle acts on.
- Our `.pdf2html-force` class is applied/removed here, to the `.pf`, not
  the `.pc`.

## `.pc` — page content (inner content wrapper)

```html
<div class="pc pc1 w0 h0">
  <img class="bi x0 y0 w1 h1" src="…bg1.png" />        <!-- background raster of page -->
  <div class="c x0 y0 w1 h1">                          <!-- canvas wrapper for text -->
    <div class="t m0 x5 h6 y20 ff4 fs3 fc0 sc0 ls3 ws8">EIGHTH EDITION</div>
    <!-- many .t lines per page -->
  </div>
</div>
```

- **This** is the element hidden/shown by our CSS:
  - `.pf > .pc { display: none !important; }` — baseline hidden
  - `.pf.pdf2html-force > .pc { display: block !important; }` — shown when forced
- Contains everything that actually paints: background image (`.bi`),
  canvas group (`.c`), and the text lines (`.t`).
- `pc1` suffix is the page-style index when multiple page sizes coexist.

## `.t` — text line

```html
<div class="t m0 x5 h6 y20 ff4 fs3 fc0 sc0 ls3 ws8">Some text here</div>
```

Every text run. Absolutely positioned inside `.pc`. Text is the `textContent`
of the div (may include `<span>` children for inline style changes).

The class-word salad is pdf2htmlEX's utility-class system (see below). For
our purposes, `.t` elements are:

- What `window.getSelection()` selects when the user drags or runs Vimium
  visual mode
- What `document.elementFromPoint(x, y)` returns when pointing at text
- What `Selection.focusNode.parentElement` returns (usually; sometimes
  it's a nested `<span>` inside a `.t`)

## `.bi` — background image

```html
<img class="bi x0 y0 w1 h1" src="…bg1.png" />
```

The rendered raster of the entire page, drawn behind the text spans.
`.t` elements are overlaid on top, positioned so their visible shapes
align with the raster's glyph outlines. Essentially: visual fidelity
comes from the raster; selectable text comes from the overlaid `.t`
elements.

## `.c` — canvas group

Pure wrapper around all `.t` lines for a page. Rarely useful for overlay
work; mentioned for completeness.

## Outline (TOC) — `#outline > ul > li > a.l`

```html
<div id="outline">
  <ul>
    <li><a class="l" href="#pf15" data-dest-detail='[21,"XYZ",41,781,null]'>Brief Contents</a></li>
    <li><a class="l" href="#pf17" data-dest-detail='[23,"XYZ",41,781,null]'>Table of Contents</a>
      <ul>
        <li><a class="l" href="#pf21" …>Computer Networks and the Internet</a></li>
        <!-- nested sub-chapters -->
      </ul>
    </li>
    …
  </ul>
</div>
```

- Every entry is an `<a class="l">` (class letter L, not I).
- `href="#pfX"` — **hex page ID**. Use the formulae above to convert.
- `data-dest-detail='[page_decimal, "XYZ", x, y, null]'` — the
  PDF-native navigation target. First array element = decimal page
  number (redundant with `href` after conversion but easier to read).
  Format is PDF-internal; we only use array index 0.
- Nesting arbitrary-deep via nested `<ul>`. Top-level entries are
  chapters; nested are sub-sections.
- Our active-chapter highlight adds `.pdf2html-active` to the
  appropriate `a.l`.

## Utility class system (`w0`, `x5`, `ff4`, `fs3`, `fc0`, …)

pdf2htmlEX compresses repeated styles into numbered utility classes
defined at the top of the document's `<style>` block. Common prefixes:

| Prefix | Meaning |
|---|---|
| `w{N}` | width from lookup table (e.g. `w0` might be `816px`) |
| `h{N}` | height |
| `x{N}` | X position |
| `y{N}` | Y position |
| `m{N}` | transform/margin (often `matrix(…)`) |
| `ff{N}` | font-family index |
| `fs{N}` | font-size index |
| `fc{N}` | foreground color |
| `sc{N}` | stroke color |
| `ls{N}` | letter-spacing |
| `ws{N}` | word-spacing |
| `pc{N}` | page-class (on `.pc` — disambiguates docs with mixed page sizes) |

You generally **do not** need to read these. They're pdf2htmlEX's business.
The only time they matter is if you're building a selector like
"all text with font family 7" — then you'd use `.t.ff7`. Rare.

## Runtime globals

| Global | Purpose |
|---|---|
| `window.pdf2htmlEX` | Namespace. We don't touch it. |
| `window.pdf2htmlEX.defaultViewer` | The runtime instance. We neutralize its `render_timer` and replace `.render` with a no-op on load — see ADR 0002 and `killPdf2htmlExRenderLoop` in overlay.js. |

## Common overlay operations and the selectors they use

| Operation | Selector / API |
|---|---|
| Iterate all pages | `container.querySelectorAll('.pf')` |
| Scroll to a specific page | `document.getElementById('pf' + n.toString(16)).scrollIntoView({block:'start'})` |
| Force-show a page | add class `pdf2html-force` to the `.pf` (not the `.pc`) |
| Observe page visibility | IntersectionObserver with `root: #page-container`, observing each `.pf` |
| Find current reading page | `document.elementFromPoint(viewport_center)`, walk up to `.pf` — **zoom-robust**, preferred. |
| Iterate outline entries | `outline.querySelectorAll('a[href^="#pf"]')` — captures `a.l` entries cleanly |
| Get selection's current focus | `window.getSelection().focusNode` → walk to `.t` parent if you need the line element |

## What you should NOT do

- **Don't manipulate inline `.pc.style.display`.** pdf2htmlEX's (killed)
  runtime still sets it occasionally. Stick to adding/removing classes
  on `.pf` and letting CSS `!important` win.
- **Don't use `offsetTop`/`offsetHeight` for "which page is visible?"
  checks.** They go stale on browser zoom. Use IntersectionObserver
  (for continuous tracking) or `elementFromPoint` (for one-off lookups).
  The outline active tracker is an intentional exception; see ADR 0002.
- **Don't assume hex page IDs are padded.** `pf1` is page 1; `pf01`
  does not exist. Always convert via `.toString(16)` / `parseInt(_,16)`.
- **Don't remove pdf2htmlEX's `<style>` block from the head.** All the
  `w0`/`x5`/`ff4` classes reference rules in there. Our overlay CSS
  is additive.
