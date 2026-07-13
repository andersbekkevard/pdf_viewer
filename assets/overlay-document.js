// Document structure, text shape, and light-raster lifecycle.
//
// pdf2htmlEX's page IDs are hexadecimal (`#pf1`, `#pfa`, …), while feature
// code deals in one-based page numbers. Keep that DOM translation — plus the
// canonical/light representation differences — in one place.
export function createDocumentModel(core) {
    var document = core.document;
    var window = core.window;
    var requestAnimationFrame = core.requestAnimationFrame;

    function html() { return document.documentElement; }
    function container() { return document.getElementById('page-container'); }
    function pages() {
        var root = container();
        return root ? Array.prototype.slice.call(root.querySelectorAll('.pf')) : [];
    }
    function totalPages() { return pages().length; }
    function page(pageNum) {
        if (!pageNum || pageNum < 1) return null;
        return document.getElementById('pf' + pageNum.toString(16));
    }
    function pageNumber(pf) {
        if (!pf || !pf.id) return null;
        var match = pf.id.match(/^pf([0-9a-f]+)$/i);
        return match ? parseInt(match[1], 16) : null;
    }
    function pageFromNode(node) {
        if (!node) return null;
        var element = node.nodeType === 1 ? node : node.parentElement;
        return element && element.closest ? element.closest('.pf') : null;
    }
    function pageNumberFromNode(node) { return pageNumber(pageFromNode(node)); }
    function pageContent(pageOrNumber) {
        var pf = typeof pageOrNumber === 'number' ? page(pageOrNumber) : pageOrNumber;
        return pf ? pf.querySelector('.pc') : null;
    }
    function pageText(pageNum) {
        var pc = pageContent(pageNum);
        if (!pc) return '';
        var lines = pc.querySelectorAll('.t');
        if (!lines.length) return (pc.textContent || '').trim();
        var out = [];
        for (var i = 0; i < lines.length; i++) {
            var text = (lines[i].textContent || '').trim();
            if (text) out.push(text);
        }
        return out.join('\n');
    }
    function pageTextBoundaryPosition(pageNum, towardsStart) {
        var pc = pageContent(pageNum);
        if (!pc) return null;
        var walker = document.createTreeWalker(pc, window.NodeFilter.SHOW_TEXT);
        var node, pick = null;
        while ((node = walker.nextNode())) {
            if (!node.nodeValue || node.nodeValue.length === 0) continue;
            pick = node;
            if (towardsStart) break;
        }
        if (!pick) return null;
        return { node: pick, offset: towardsStart ? 0 : pick.nodeValue.length };
    }
    function visiblePages() {
        var root = container();
        if (!root) return [];
        var rootRect = root.getBoundingClientRect();
        return pages().filter(function (pf) {
            var rect = pf.getBoundingClientRect();
            return rect.bottom >= rootRect.top && rect.top <= rootRect.bottom;
        });
    }

    // The explicit marker is the forward contract. Existing generated cache
    // entries still use body/attribute markers, so retain those as fallbacks.
    function representation() {
        if (html() && html().getAttribute('data-pdf2html-representation') === 'light-v1') return 'light-v1';
        if (document.body && document.body.classList.contains('pdf2html-light')) return 'light-legacy';
        return document.querySelector('img.bi[data-pdf2html-src]') ? 'light-legacy' : 'canonical';
    }
    function isLight() { return representation().indexOf('light') === 0; }
    function textMode() {
        var root = html();
        if (!root) return 'canonical';
        return root.getAttribute('data-pdf2html-text-mode')
            || root.getAttribute('data-pdf2html-text-flattened')
            || 'canonical';
    }
    function isTextFlattened() { return textMode() !== 'canonical'; }

    // Only light documents externalize their raster sources. Page state lives
    // on the frame so other features can observe lifecycle without inspecting
    // individual image attributes: unloaded -> loading -> ready | error.
    function mountRasterLifecycle() {
        var rasters = document.querySelectorAll('#page-container .pc > img.bi[data-pdf2html-src]');
        if (!rasters.length) return;
        var root = container();
        var allPages = pages();
        var preloadPx = 3500;
        var raf = null;

        function setState(pf, state) { pf.dataset.pdf2htmlRasterState = state; }
        function sourceFor(img) { return img.getAttribute('data-pdf2html-src'); }
        function pageRasters(pf) { return pf.querySelectorAll('img.bi[data-pdf2html-src]'); }
        function isReady(img) { return img.complete && img.naturalWidth > 0; }
        function bind(img, pf) {
            if (img.__pdf2htmlRasterLifecycleBound) return;
            img.__pdf2htmlRasterLifecycleBound = true;
            img.addEventListener('load', function () {
                if (img.getAttribute('src') === sourceFor(img)) setState(pf, 'ready');
            });
            img.addEventListener('error', function () {
                if (img.getAttribute('src') === sourceFor(img)) setState(pf, 'error');
            });
        }
        function loadPage(pf) {
            var imgs = pageRasters(pf);
            var ready = true;
            var failed = false;
            for (var i = 0; i < imgs.length; i++) {
                var img = imgs[i];
                var src = sourceFor(img);
                if (!src) continue;
                bind(img, pf);
                var hasCurrentSource = img.getAttribute('src') === src;
                if (!hasCurrentSource) img.setAttribute('src', src);
                if (!isReady(img)) {
                    ready = false;
                    // A complete image with no natural width is a cached
                    // failure. Keep the observable error state until this
                    // page is unloaded and later retried.
                    if (hasCurrentSource && img.complete) failed = true;
                }
            }
            setState(pf, failed ? 'error' : ready ? 'ready' : 'loading');
        }
        function unloadPage(pf) {
            var imgs = pageRasters(pf);
            for (var i = 0; i < imgs.length; i++) imgs[i].removeAttribute('src');
            setState(pf, 'unloaded');
        }
        function sync() {
            raf = null;
            var rootRect = root ? root.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
            var top = rootRect.top - preloadPx;
            var bottom = rootRect.bottom + preloadPx;
            for (var i = 0; i < allPages.length; i++) {
                var rect = allPages[i].getBoundingClientRect();
                if (rect.bottom >= top && rect.top <= bottom) loadPage(allPages[i]);
                else unloadPage(allPages[i]);
            }
        }
        function scheduleSync() {
            if (raf) return;
            raf = requestAnimationFrame(sync);
        }

        if (root) root.addEventListener('scroll', scheduleSync, { passive: true });
        window.addEventListener('resize', scheduleSync);
        document.addEventListener('pdf2html-page-counter-refresh', scheduleSync);
        scheduleSync();
    }

    return {
        container: container,
        pages: pages,
        totalPages: totalPages,
        page: page,
        pageNumber: pageNumber,
        pageFromNode: pageFromNode,
        pageNumberFromNode: pageNumberFromNode,
        pageContent: pageContent,
        pageText: pageText,
        pageTextBoundaryPosition: pageTextBoundaryPosition,
        visiblePages: visiblePages,
        representation: representation,
        isLight: isLight,
        textMode: textMode,
        isTextFlattened: isTextFlattened,
        mountRasterLifecycle: mountRasterLifecycle,
    };
}
