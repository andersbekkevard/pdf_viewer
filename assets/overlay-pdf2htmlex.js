// pdf2htmlEX adaptation: everything the overlay changes about pdf2htmlEX's
// emitted DOM and its leftover runtime (`window.pdf2htmlEX.defaultViewer`).
// Re-check this module after a pdf2htmlEX upgrade; docs/pdf2htmlex-dom.md
// lists the runtime entry points it replaces.
import { isInputTarget } from './overlay-dom.js';

var preparedViewers = new WeakSet();

// Module scripts execute before DOMContentLoaded. Prepare the converter before
// its startup constructs every private Page by reading offscreen .pc heights.
export function preparePdf2htmlEx(core) {
    var document = core.document, window = core.window;
    var root = document.documentElement;
    var viewer = window.pdf2htmlEX && window.pdf2htmlEX.defaultViewer;
    if (!root || root.getAttribute('data-pdf2html-declared-page-geometry') !== 'v1'
        || !viewer || typeof viewer.find_pages !== 'function'
        || preparedViewers.has(viewer) || (viewer.pages && viewer.pages.length)) return false;
    var container = document.getElementById('page-container');
    if (!container) return false;
    var frames = Array.from(container.children).filter(function (frame) { return frame.classList.contains('pf'); });
    var numbers = new Set(), records = [];
    for (var i = 0; i < frames.length; i++) {
        var frame = frames[i];
        var size = (frame.getAttribute('data-pdf2html-page-size') || '').split(',').map(Number);
        var number = parseInt(frame.getAttribute('data-page-no'), 16);
        var content = frame.querySelector('.pc'), data = frame.querySelector('.pi'), matrix;
        try { matrix = JSON.parse(data.getAttribute('data-data')).ctm; } catch (error) { return false; }
        if (size.length !== 3 || !size.every(function (n) { return Number.isFinite(n) && n > 0 && n < 1000000; })
            || !Number.isInteger(number) || number < 1 || numbers.has(number)
            || frame.id !== 'pf' + number.toString(16) || !content
            || !Array.isArray(matrix) || matrix.length !== 6 || !matrix.every(Number.isFinite)) return false;
        var determinant = matrix[0] * matrix[3] - matrix[1] * matrix[2];
        if (!Number.isFinite(determinant) || !determinant) return false;
        numbers.add(number);
        records.push({ frame: frame, number: number, content: content, size: size, data: JSON.parse(data.getAttribute('data-data')), determinant: determinant });
    }
    if (!records.length) return false;
    var originalFind = viewer.find_pages;
    viewer.find_pages = function () {
        // Extract the converter's private Page prototype from one visible page.
        // The temporary receiver leaves the real container and viewer untouched.
        var bootstrap = Object.create(this);
        bootstrap.container = { childNodes: [records[0].frame] };
        originalFind.call(bootstrap);
        if (!bootstrap.pages || bootstrap.pages.length !== 1) return originalFind.call(this);
        var prototype = Object.getPrototypeOf(bootstrap.pages[0]);
        var map = {};
        var pages = records.map(function (record, index) {
            var page = Object.create(prototype), m = record.data.ctm, det = record.determinant;
            page.page = record.frame; page.num = record.number;
            page.loaded = true; page.shown = false; page.content_box = record.content;
            page.original_width = record.size[0]; page.original_height = record.size[1];
            page.original_scale = page.cur_scale = record.size[1] / record.size[2];
            page.page_data = record.data; page.ctm = m;
            page.ictm = [m[3]/det, -m[1]/det, -m[2]/det, m[0]/det,
                (m[2]*m[5]-m[3]*m[4])/det, (m[1]*m[4]-m[0]*m[5])/det];
            map[page.num] = index;
            return page;
        });
        this.pages = pages; this.page_map = map;
    };
    viewer.render = function () {};
    viewer.schedule_render = function () {};
    if (viewer.render_timer) window.clearTimeout(viewer.render_timer);
    viewer.render_timer = null;
    preparedViewers.add(viewer);
    return true;
}


export function createPdf2htmlEx(core) {
    var document = core.document;
    var window = core.window;
    var documentModel = core.documentModel;
    var zoom = core.zoom;
    var CSSStyleRule = window.CSSStyleRule;

    function viewer() {
        return window.pdf2htmlEX && window.pdf2htmlEX.defaultViewer || null;
    }

    // ------------------------------------------------------------------------
    // Make pdf2htmlEX's spacer spans non-atomic for native Cmd-F.
    //
    // pdf2htmlEX wraps every inter-word and intra-word spacer in
    // `<span class="_ _N">` (` ` content for word gaps, empty for kerning).
    // Its base `._` class is `display: inline-block`, which Chromium's
    // FindBuffer treats as an *atomic-inline boundary*: a U+FFFC is injected
    // into the find buffer at every such span, breaking any multi-word query
    // like "a collection of" even when those words sit on one line. Single
    // words inside one find run still match (why "collection" works in
    // isolation), but anything spanning a spacer is invisible to native find.
    //
    // Fix, applied atomically before first paint:
    //
    //  1. Rewrite every `._<N> { width: Xpx }` rule (≈ 660 of them per book)
    //     to `._<N> { padding-left: Xpx }`. Padding works on inline boxes;
    //     width does not.
    //  2. Inject one override sheet that promotes `._` from `inline-block` to
    //     `inline` (no atomic boundary). Only spacers carrying a rewritten
    //     width class get `font-size: 0`, so their inner space does not add to
    //     the new padding. Some PDFs use a plain `<span class="_"> </span>`
    //     with no width class for word gaps; those must keep their inherited
    //     font size or the visible space disappears.
    //
    // Runs synchronously at the top of init() (overlay.js is a module script,
    // so all pdf2htmlEX <style> blocks have already parsed). Both steps live
    // in one synchronous block so the browser only relayouts once; no visual
    // flash between the rewrite and the override.
    //
    // Defense in depth: if this function never runs (overlay.js missing /
    // broken), pdf2htmlEX's defaults stand — visual layout is correct, and
    // we only lose multi-word find. The override is *only* injected if the
    // rewrite actually succeeded, so we never end up with `_ { display:
    // inline }` against unmodified `width: Xpx` rules (which would collapse
    // every word-gap visually).
    // ------------------------------------------------------------------------
    function rewriteSpacerWidthsToPadding() {
        var sheets = document.styleSheets;
        var rewrote = 0;
        var rewrittenSelectors = [];
        for (var s = 0; s < sheets.length; s++) {
            var rules;
            try { rules = sheets[s].cssRules; } catch (e) { continue; }
            if (!rules) continue;
            for (var i = 0; i < rules.length; i++) {
                var r = rules[i];
                if (!(r instanceof CSSStyleRule)) continue;
                var sel = r.selectorText;
                if (!sel || !/^\._[0-9a-z]+$/.test(sel)) continue;
                var w = r.style.width;
                if (!w) continue;
                r.style.removeProperty('width');
                r.style.setProperty('padding-left', w);
                rewrote++;
                rewrittenSelectors.push('._' + sel);
            }
        }
        if (!rewrote) return;
        var override = document.createElement('style');
        override.id = 'pdf2html-find-boundary-fix';
        override.textContent = '._{display:inline !important;}' +
            rewrittenSelectors.join(',') + '{font-size:0 !important;}';
        document.head.appendChild(override);
    }

    // pdf2htmlEX paints each page as a raster behind the text layer. A missed
    // selection drag must not turn into Chrome's image-drag ghost.
    function disablePageRasterDragging() {
        var rasters = document.querySelectorAll('#page-container .pc > img.bi');
        for (var i = 0; i < rasters.length; i++) {
            rasters[i].draggable = false;
            rasters[i].setAttribute('draggable', 'false');
        }
    }

    // Geometry light documents deliberately retain pdf2htmlEX spacer spans,
    // so they need the same find fix as the canonical representation.
    function adaptDocument() {
        var mode = documentModel.textMode();
        if (mode !== 'page' && mode !== 'line') rewriteSpacerWidthsToPadding();
        disablePageRasterDragging();
    }

    // ------------------------------------------------------------------------
    // Runtime. pdf2htmlEX boots on its own DOMContentLoaded listener, so wait
    // briefly for its viewer instance.
    // ------------------------------------------------------------------------
    function adaptRuntime() {
        function attempt() {
            var v = viewer();
            if (!v) return false;
            killPdf2htmlExRenderLoop(v);
            adaptGeometry(v);
            routeRescaleToZoom(v);
            return true;
        }
        keepTextFieldKeysLocal();
        if (attempt()) return;
        var n = 0;
        var iv = setInterval(function () {
            if (attempt() || ++n > 100) clearInterval(iv);
        }, 20);
    }

    // Neutralize pdf2htmlEX's own render loop (ADR 0002). It is a
    // setTimeout-driven loop that touches .pc inline styles on scroll, which
    // causes paint flashing; `content-visibility: auto` does that job now.
    // schedule_render goes too, so scrolling no longer arms dead timers.
    function killPdf2htmlExRenderLoop(v) {
        try {
            if (v.render_timer) clearTimeout(v.render_timer);
            v.render_timer = null;
            v.render = function () {};
            v.schedule_render = function () {};
        } catch (e) {}
    }

    // pdf2htmlEX's navigation assumes page-local CSS px equal scroller px:
    // it mixes a page's offsetTop with the container's scrollTop. Our zoom
    // sits on the pages (ADR 0012), so a zoomed page's offsets are in
    // page-local units while scrollTop is in screen px. Rebuild the few
    // geometry entry points on the document model:
    //   - view_position: scroller position relative to a page, page-local
    //     units (link_handler/navigate_to_dest, view hashes)
    //   - scroll_to: convert the page-local delta back to screen px
    //   - cur_page_idx: derived on read instead of tracked per scroll
    function adaptGeometry(v) {
        if (v.__pdf2htmlGeometryAdapted || !v.pages || !v.pages.length) return;
        v.__pdf2htmlGeometryAdapted = true;
        var root = documentModel.container();

        // Page objects share a constructor; patch the prototype once.
        Object.getPrototypeOf(v.pages[0]).view_position = function () {
            var z = zoom.current();
            var extent = documentModel.pageExtent(this.page);
            return [
                (root.scrollLeft - extent.left) / z - this.page.clientLeft,
                (root.scrollTop - extent.top) / z - this.page.clientTop,
            ];
        };
        v.scroll_to = function (idx, pos) {
            if (idx < 0 || idx >= this.pages.length) return;
            var z = zoom.current();
            var cur = this.pages[idx].view_position();
            pos = pos || [0, 0];
            root.scrollLeft += (pos[0] - cur[0]) * z;
            root.scrollTop += (pos[1] - cur[1]) * z;
        };
        v.update_page_idx = function () {};
        Object.defineProperty(v, 'cur_page_idx', {
            configurable: true,
            get: function () { return (documentModel.mostVisiblePage() || 1) - 1; },
            set: function () {},
        });
    }

    // pdf2htmlEX has its own zoom (`rescale`, a CSS transform on each .pc),
    // bound to Ctrl/Cmd +/-/0 and Ctrl-wheel. Two zoom systems would fight:
    // auto-fit would not see it and it would not persist. Route its relative
    // steps and its reset into the overlay zoom and keep its own scale at 1.
    // Absolute scales only come from link destinations, which must not change
    // the reader's zoom.
    function routeRescaleToZoom(v) {
        if (v.__pdf2htmlRescaleRouted) return;
        v.__pdf2htmlRescaleRouted = true;
        v.rescale = function (factor, relative) {
            if (relative) zoom.scaleBy(factor);
            else if (factor === 0) zoom.set('auto');
        };
    }

    // pdf2htmlEX's key handler listens on window (bubble phase) and acts on
    // PageUp/PageDown/Home/End and Ctrl/Cmd +/-/0 wherever focus is,
    // including the overlay's text fields, where it scrolls the document and
    // swallows the caret movement. Keys typed into a text field stop at the
    // document so they stay with the field. Vimium and the overlay's own
    // handlers listen in the capture phase and are unaffected.
    function keepTextFieldKeysLocal() {
        document.addEventListener('keydown', function (e) {
            if (isInputTarget(e.target)) e.stopPropagation();
        });
    }

    // Navigate to an outline or link destination exactly as a click would,
    // including pdf2htmlEX's history entry. False when the link has no
    // destination or the runtime is missing, so callers can fall back.
    function followDestination(link) {
        var v = viewer();
        if (!v || !link || !link.getAttribute('data-dest-detail')) return false;
        v.link_handler({ target: link, currentTarget: link, preventDefault: function () {} });
        return true;
    }

    return { adaptDocument: adaptDocument, adaptRuntime: adaptRuntime, followDestination: followDestination };
}
