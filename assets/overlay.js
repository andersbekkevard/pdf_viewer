// ============================================================================
// pdf_viewer overlay — runtime layer on top of pdf2htmlEX's output.
//
// Served as /_assets/overlay.js, loaded via <script type="module"> injected
// into each converted HTML. Module scripts defer by default, so everything
// still runs after HTML parse (DOMContentLoaded), same timing as the old
// deferred classic script.
//
// This is the composition root. It owns viewer chrome and pdf2htmlEX runtime
// adaptation, then wires the library, navigation, text interaction, command,
// and finger modules through explicit capability objects at init().
// ============================================================================

import { createFinger } from './overlay-finger.js';
import { createDocumentModel } from './overlay-document.js';
import { createLibrary } from './overlay-library.js';
import { createNavigation } from './overlay-navigation.js';
import { createTextInteraction } from './overlay-text.js';
import { createCommandSurface } from './overlay-commands.js';

(function () {
    'use strict';

    // Feature modules are built in init(). Until then finger uses no-op shims
    // so early references from injected-page startup remain safe.
    var finger = {
        openFingerMode: function () {},
        closeFingerMode: function () {},
        isActive: function () { return false; },
    };
    var library = null;
    var documentModel = null;
    var navigation = null;
    var textInteraction = null;
    var commandSurface = null;

    document.addEventListener('DOMContentLoaded', init);

    function init() {
        documentModel = createDocumentModel({ document: document, window: window,
            requestAnimationFrame: requestAnimationFrame });
        library = createLibrary({ document: document, location: location, history: history,
            fetch: fetch.bind(window), entryHash: entryHash });
        navigation = createNavigation({ document: document, storage: localStorage, entryHash: entryHash });
        navigation.init();
        textInteraction = createTextInteraction({ document: document, window: window,
            storage: localStorage, navigator: navigator, performance: performance,
            requestAnimationFrame: requestAnimationFrame, Range: Range, NodeFilter: NodeFilter,
            Highlight: window.Highlight, CSS: window.CSS, el: el, isInputTarget: isInputTarget,
            isSearchCaseSensitive: isSearchCaseSensitive, navigation: navigation,
            documentModel: documentModel,
            isFingerActive: function () { return finger.isActive(); } });
        // Build feature modules before the shell mounts event coordinators.
        finger = createFinger({
            closeSearch: textInteraction.closeSearch,
            visiblePageFrames: textInteraction.visiblePageFrames,
            writeClip: textInteraction.writeClip,
        });
        commandSurface = createCommandSurface({ document: document, window: window,
            storage: localStorage, navigation: navigation, textInteraction: textInteraction,
            library: library, finger: finger, isInputTarget: isInputTarget,
            openSettings: openSettings, isSearchCaseSensitive: isSearchCaseSensitive });
        // Geometry light documents deliberately retain pdf2htmlEX spacer
        // spans. Convert their atomic inline widths to padding just as the
        // canonical representation does, so native find can cross words.
        if (documentModel.textMode() !== 'page' && documentModel.textMode() !== 'line') {
            rewriteSpacerWidthsToPadding();
        }
        killPdf2htmlExRenderLoop();
        disablePageRasterDragging();
        documentModel.mountRasterLifecycle();
        mountSidebarToggleButton();
        registerEscapeHandler();
        commandSurface.init();
        registerPagenoToggleHandler();
        registerPageJumpHandler();
        registerSidebarKeyHandler();
        registerDocumentTabGuard();
        registerFocusRouting();
        textInteraction.init();
        mountOutlineActiveTracker();
        mountPageCounter();
        mountResumePosition();
        mountZoom();
        mountSidebarBackdrop();
        mountSidebarChrome();
        mountOutlineScrollSelection();
        mountSidebarHeader();
        mountSidebarLayout();
        mountThumbnails();
        applyAppearanceSettings();
        library.load();
    }

    // ------------------------------------------------------------------------
    // Tiny DOM helper — used across sidebar chrome + settings modal for
    // readable declarative construction. Not a framework, just sugar.
    // ------------------------------------------------------------------------
    function el(tag, attrs, children) {
        var n = document.createElement(tag);
        attrs = attrs || {};
        for (var k in attrs) {
            if (!Object.prototype.hasOwnProperty.call(attrs, k)) continue;
            var v = attrs[k];
            if (v == null || v === false) continue;
            if (k === 'class') n.className = v;
            else if (k === 'html') n.innerHTML = v;
            else if (k.indexOf('on') === 0 && typeof v === 'function') {
                n.addEventListener(k.slice(2).toLowerCase(), v);
            } else if (k === 'dataset' && typeof v === 'object') {
                for (var dk in v) n.dataset[dk] = v[dk];
            } else {
                n.setAttribute(k, v);
            }
        }
        children = children || [];
        if (!Array.isArray(children)) children = [children];
        children.forEach(function (c) {
            if (c == null || c === false) return;
            n.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
        });
        return n;
    }

    function svgIcon(path, size) {
        size = size || 14;
        return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" '
            + 'fill="none" stroke="currentColor" stroke-width="1.75" '
            + 'stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
    }

    // Resolve the cache-entry hash. Prefer the inject-time <meta> tag —
    // location.pathname lies when the page is served via /view?path=…
    // (daemon FileResponse keeps the URL on /view rather than redirecting
    // to /<hash>/<stem>.html). Fall back to pathname for older entries
    // that predate the meta injection.
    function entryHash() {
        var meta = document.querySelector('meta[name="pdf2html-hash"]');
        if (meta && meta.content) return meta.content;
        var m = location.pathname.match(/^\/([a-f0-9]{6,32})\//);
        return m ? m[1] : null;
    }
    var ICONS = {
        sidebar:  '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
        outline:  '<path d="M4 6h16M4 12h16M4 18h10"/>',
        grid:     '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
        settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
        help:     '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    };


    // ------------------------------------------------------------------------
    // Sidebar backdrop host. Kept in DOM as inert plumbing so older cache
    // entries and CSS selectors still have a stable target, but the sidebar
    // is no longer modal-overlay chrome — the main PDF stays clickable.
    // ------------------------------------------------------------------------
    function mountSidebarBackdrop() {
        var bd = document.createElement('div');
        bd.id = 'pdf2html-sidebar-backdrop';
        bd.setAttribute('aria-hidden', 'true');
        document.body.appendChild(bd);
    }


    // ------------------------------------------------------------------------
    // Sidebar chrome — wrap #sidebar's pre-existing #outline in a tabs +
    // body + footer structure matching the design. pdf2htmlEX provides
    // #outline; we don't touch its contents, just wrap and add siblings.
    //
    //   #sidebar
    //     #pdf2html-sidebar-head       (added later by mountSidebarHeader)
    //     #pdf2html-sidebar-tabs       (Outline / Pages tab buttons)
    //     #pdf2html-sidebar-body
    //       #outline                   (pdf2htmlEX, moved in)
    //       #pdf2html-thumbs           (mountThumbnails populates)
    //     #pdf2html-sidebar-footer     (Settings + Help icon buttons)
    // ------------------------------------------------------------------------
    function mountSidebarChrome() {
        var sidebar = document.getElementById('sidebar');
        if (!sidebar) return;
        var outline = document.getElementById('outline');

        var tabs = el('div', { id: 'pdf2html-sidebar-tabs' }, [
            el('button', {
                class: 'pdf2html-sidebar-tab',
                dataset: { tab: 'outline' },
                html: svgIcon(ICONS.outline, 13) + '<span>Outline</span>',
                onClick: function () { setSidebarTab('outline'); },
            }),
            el('button', {
                class: 'pdf2html-sidebar-tab',
                dataset: { tab: 'thumbs' },
                html: svgIcon(ICONS.grid, 13) + '<span>Pages</span>',
                onClick: function () { setSidebarTab('thumbs'); },
            }),
        ]);

        // tabindex=-1 makes the body a valid activeElement target, so Vimium's
        // j/k scroll scopes to the sidebar (nearest scrollable ancestor of
        // activeElement) rather than the main page. See registerFocusRouting.
        var body = el('div', { id: 'pdf2html-sidebar-body', tabindex: '-1' });
        if (outline && outline.parentElement === sidebar) body.appendChild(outline);
        var thumbs = el('div', { id: 'pdf2html-thumbs' });
        body.appendChild(thumbs);

        var footer = el('div', { id: 'pdf2html-sidebar-footer' }, [
            el('button', {
                class: 'pdf2html-sidebar-footer-btn',
                title: 'Settings (:set)',
                onClick: openSettings,
                html: svgIcon(ICONS.settings, 14)
                    + '<span class="label">Settings</span>'
                    + '<span class="shortcut">:set</span>',
            }),
            el('button', {
                class: 'pdf2html-sidebar-footer-btn icon-only',
                title: 'Keyboard shortcuts (?)',
                onClick: function () { commandSurface.toggleCheatsheet(); },
                html: svgIcon(ICONS.help, 14),
            }),
        ]);

        sidebar.appendChild(tabs);
        sidebar.appendChild(body);
        sidebar.appendChild(footer);

        var saved = localStorage.getItem('pdf2html-sidebar-tab');
        setSidebarTab(saved === 'thumbs' ? 'thumbs' : 'outline');
    }

    function setSidebarTab(name) {
        if (name !== 'outline' && name !== 'thumbs') name = 'outline';
        document.body.setAttribute('data-sidebar-tab', name);
        localStorage.setItem('pdf2html-sidebar-tab', name);
        var tabs = document.querySelectorAll('#pdf2html-sidebar-tabs .pdf2html-sidebar-tab');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.toggle('active', tabs[i].dataset.tab === name);
        }
        // Re-activate the sidebar body so Vimium j/k scrolls the newly-visible
        // tab. Only when sidebar is shown, so palette-driven tab changes
        // (e.g. a future `:tab thumbs`) while closed don't hijack j/k.
        var body = document.getElementById('pdf2html-sidebar-body');
        if (body && document.body.classList.contains('sidebar-shown')) {
            try { body.focus({ preventScroll: true }); } catch (e) {}
            try { body.dispatchEvent(new Event('DOMActivate', { bubbles: true, cancelable: true })); } catch (e) {}
            try { body.dispatchEvent(new MouseEvent('click',   { bubbles: true, cancelable: true })); } catch (e) {}
        }
    }

    // ------------------------------------------------------------------------
    // Outline selection — a second, temporary target for keyboard navigation in
    // the sidebar. It stays visually hidden while it matches the current active
    // chapter; Ctrl-j/k or arrows move it, and Enter activates it.
    // ------------------------------------------------------------------------
    function mountOutlineScrollSelection() {
        var body = document.getElementById('pdf2html-sidebar-body');
        var outline = document.getElementById('outline');
        if (!body || !outline) return;

        var links = Array.prototype.slice.call(outline.querySelectorAll('a[href^="#pf"]'));
        if (!links.length) return;

        var selected = null;
        var raf = null;
        var programmaticScrollsToIgnore = 0;

        function outlineVisible() {
            return document.body.classList.contains('sidebar-shown')
                && document.body.getAttribute('data-sidebar-tab') === 'outline';
        }

        function sameTarget(a, b) {
            if (!a || !b) return false;
            return a === b || a.getAttribute('href') === b.getAttribute('href');
        }

        function syncSelectedMarker() {
            var active = activeLink();
            for (var i = 0; i < links.length; i++) {
                links[i].classList.toggle('pdf2html-selected', links[i] === selected && !sameTarget(links[i], active));
            }
        }

        function setSelected(link) {
            if (link === selected) {
                syncSelectedMarker();
                return;
            }
            selected = link || null;
            syncSelectedMarker();
        }

        function activeLink() {
            return outline.querySelector('a.pdf2html-active[href^="#pf"]');
        }

        function selectedLink() {
            return selected || nearestAnchorLink() || activeLink() || links[0] || null;
        }

        function pageFromLink(link) {
            var m = link && (link.getAttribute('href') || '').match(/#pf([0-9a-f]+)/i);
            return m ? parseInt(m[1], 16) : null;
        }

        function setActiveLink(link) {
            for (var i = 0; i < links.length; i++) {
                links[i].classList.toggle('pdf2html-active', links[i] === link);
            }
            syncSelectedMarker();
        }

        function replaceHash(link) {
            var href = link && link.getAttribute('href');
            if (!href || href.charAt(0) !== '#') return;
            try {
                history.replaceState(null, '', location.pathname + location.search + href);
            } catch (e) {}
        }

        function commitSelected() {
            var link = selected;
            if (!link) return;
            var page = pageFromLink(link);
            var pf = textInteraction.pageElement(page);
            var pc = document.getElementById('page-container');
            if (!pf || !pc) return;

            setActiveLink(link);
            setSelected(null);
            pc.scrollTop = Math.max(0, pf.offsetTop);
            replaceHash(link);
        }

        function scrollLinkToAnchor(link) {
            if (!link) return;
            var bodyRect = body.getBoundingClientRect();
            var linkRect = link.getBoundingClientRect();
            var anchorY = bodyRect.top + bodyRect.height * 0.35;
            var linkY = linkRect.top + linkRect.height / 2;
            var delta = linkY - anchorY;
            if (Math.abs(delta) > 0.5) programmaticScrollsToIgnore += 1;
            body.scrollTop += delta;
        }

        function moveSelected(dir) {
            var from = selectedLink();
            if (!from) return;
            var idx = links.indexOf(from);
            if (idx < 0) idx = 0;
            idx = Math.max(0, Math.min(links.length - 1, idx + dir));
            var next = links[idx];
            setSelected(next);
            scrollLinkToAnchor(next);
        }

        function nearestAnchorLink() {
            var bodyRect = body.getBoundingClientRect();
            var anchorY = bodyRect.top + bodyRect.height * 0.35;
            var best = null;
            var bestDist = Infinity;

            for (var i = 0; i < links.length; i++) {
                var r = links[i].getBoundingClientRect();
                if (r.bottom < bodyRect.top || r.top > bodyRect.bottom) continue;
                var mid = r.top + r.height / 2;
                var dist = Math.abs(mid - anchorY);
                if (dist < bestDist) {
                    best = links[i];
                    bestDist = dist;
                }
            }
            return best;
        }

        function updateFromScroll() {
            raf = null;
            if (!outlineVisible()) return;
            if (programmaticScrollsToIgnore > 0) {
                programmaticScrollsToIgnore -= 1;
                syncSelectedMarker();
                return;
            }
            setSelected(nearestAnchorLink());
        }

        function scheduleFromScroll() {
            if (raf) return;
            raf = requestAnimationFrame(updateFromScroll);
        }

        function syncOnVisibilityChange() {
            if (!outlineVisible()) return;
            var active = activeLink();
            if (active) {
                setSelected(active);
                try { active.scrollIntoView({ block: 'nearest' }); } catch (e) {}
                return;
            }
            setSelected(null);
        }

        for (var i = 0; i < links.length; i++) (function (link) {
            link.addEventListener('click', function () { setSelected(link); });
        })(links[i]);

        body.addEventListener('scroll', scheduleFromScroll, { passive: true });
        new MutationObserver(syncOnVisibilityChange).observe(document.body, {
            attributes: true,
            attributeFilter: ['class', 'data-sidebar-tab'],
        });
        new MutationObserver(syncSelectedMarker).observe(outline, {
            attributes: true,
            attributeFilter: ['class'],
            subtree: true,
        });

        window.addEventListener('keydown', function (e) {
            if (e.metaKey || e.altKey) return;
            if (isInputTarget(e.target)) return;
            if (!outlineVisible()) return;
            if (document.activeElement !== body
                && document.body.getAttribute('data-scroll-focus') !== 'sidebar') return;

            var ctrlDown = e.ctrlKey && !e.shiftKey && (e.key === 'j' || e.key === 'J');
            var ctrlUp = e.ctrlKey && !e.shiftKey && (e.key === 'k' || e.key === 'K');
            var arrowDown = !e.ctrlKey && !e.shiftKey && e.key === 'ArrowDown';
            var arrowUp = !e.ctrlKey && !e.shiftKey && e.key === 'ArrowUp';
            if (ctrlDown || ctrlUp || arrowDown || arrowUp) {
                e.preventDefault();
                e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                moveSelected((ctrlDown || arrowDown) ? 1 : -1);
                return;
            }

            if (!e.ctrlKey && !e.shiftKey && e.key === 'Enter') {
                if (!selected) return;
                e.preventDefault();
                e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                commitSelected();
            }
        }, true);

        syncOnVisibilityChange();
    }

    // ------------------------------------------------------------------------
    // Sidebar layout — keep the sidebar fixed on the left, but only translate
    // the PDF pages once the sidebar has exhausted the natural left-side gutter
    // around the centered page. That mirrors native browser side panels more
    // closely than re-centering the whole document inside a narrowed viewport.
    // ------------------------------------------------------------------------
    function mountSidebarLayout() {
        var sidebar = document.getElementById('sidebar');
        var pc = document.getElementById('page-container');
        if (!sidebar || !pc) return;
        var pages = Array.prototype.slice.call(pc.querySelectorAll('.pf'));
        var widestPage = pages[0] || null;
        for (var i = 1; i < pages.length; i++) {
            if (!widestPage || pages[i].offsetWidth > widestPage.offsetWidth) widestPage = pages[i];
        }

        var raf = null;
        var settleFrames = 0;

        function apply() {
            var shift = 0;
            if (document.body.classList.contains('sidebar-shown')) {
                var maxWidth = widestPage ? widestPage.getBoundingClientRect().width : 0;
                var viewportWidth = pc.getBoundingClientRect().width;
                var naturalLeft = (viewportWidth - maxWidth) / 2;
                var sidebarRect = sidebar.getBoundingClientRect();
                var gutter = 14;
                shift = Math.max(0, Math.round(sidebarRect.right + gutter - naturalLeft));
            }
            document.documentElement.style.setProperty('--pdf2html-page-shift', shift + 'px');
            document.body.classList.toggle('pdf2html-page-shifted', shift > 0);
        }

        function step() {
            raf = null;
            apply();
            if (settleFrames > 0) {
                settleFrames -= 1;
                raf = requestAnimationFrame(step);
            }
        }

        function sched(extraFrames) {
            if (extraFrames == null) extraFrames = 4;
            settleFrames = Math.max(settleFrames, extraFrames);
            if (raf) return;
            raf = requestAnimationFrame(step);
        }

        new MutationObserver(function () { sched(6); }).observe(document.body, {
            attributes: true,
            attributeFilter: ['class'],
        });
        requestAnimationFrame(function () { sched(6); });
    }


    // ------------------------------------------------------------------------
    // Thumbnails grid — a 2-col grid of placeholder page cards. pdf2htmlEX
    // doesn't ship real thumbnails (would double the cache size); these are
    // skeleton shapes purely for spatial navigation. Click scrolls the real
    // page into view.
    //
    // Active state updates via the `pdf2html-page-change` custom event that
    // mountPageCounter dispatches on scroll.
    // ------------------------------------------------------------------------
    function mountThumbnails() {
        var host = document.getElementById('pdf2html-thumbs');
        var pc = document.getElementById('page-container');
        if (!host || !pc) return;
        var pages = pc.querySelectorAll('.pf');
        if (!pages.length) return;

        // Template real thumbnail URLs at /<hash>/thumbs/N.jpg (written by
        // scripts/extract-pdf-thumbs.sh at convert time). For cache entries
        // without thumbs yet, the <img> 404s silently and skeletons stay.
        var hash = entryHash();
        var thumbBase = hash ? '/' + hash + '/thumbs/' : null;

        for (var i = 0; i < pages.length; i++) (function (pf, idx) {
            var m = (pf.id || '').match(/pf([0-9a-f]+)/i);
            var pageNum = m ? parseInt(m[1], 16) : (idx + 1);

            var inner = el('div', { class: 'thumb-page' }, [
                el('div', {
                    class: 'thumb-skeleton',
                    html: '<div class="l1"></div><div class="l2"></div><div class="l3"></div>'
                        + '<div class="l2"></div><div class="l1"></div><div class="l3"></div>'
                        + '<div class="l2"></div>',
                }),
            ]);

            if (thumbBase) {
                // Native lazy loading: Chrome only fetches once the <img>
                // scrolls near the viewport, so we pay nothing for 797 pages
                // unless the user actually browses the Pages tab.
                var img = new Image();
                img.className = 'thumb-img';
                img.loading   = 'lazy';
                img.decoding  = 'async';
                img.alt = 'Page ' + pageNum;
                img.addEventListener('load',  function () { inner.classList.add('has-img'); });
                img.addEventListener('error', function () { /* leave skeleton */ });
                img.src = thumbBase + pageNum + '.jpg';
                inner.appendChild(img);
            }

            var card = el('button', {
                class: 'pdf2html-thumb',
                title: 'Page ' + pageNum,
                dataset: { page: String(pageNum) },
                onClick: function () { pf.scrollIntoView({ block: 'start' }); },
            }, [
                el('div', { class: 'thumb-stack' }, [
                    inner,
                    el('div', { class: 'thumb-label' }, String(pageNum)),
                ]),
            ]);
            host.appendChild(card);
        })(pages[i], i);

        function thumbsTabVisible() {
            return document.body.classList.contains('sidebar-shown')
                && document.body.getAttribute('data-sidebar-tab') === 'thumbs';
        }

        var thumbButtons = Array.prototype.slice.call(host.querySelectorAll('.pdf2html-thumb'));
        var selectedPage = null;

        function thumbPage(thumb) {
            return thumb ? parseInt(thumb.dataset.page, 10) : NaN;
        }

        function activeThumbPage() {
            var active = host.querySelector('.pdf2html-thumb.active');
            var page = thumbPage(active);
            return !isNaN(page) ? page : navigation.page();
        }

        function thumbForPage(page) {
            for (var i = 0; i < thumbButtons.length; i++) {
                if (thumbPage(thumbButtons[i]) === page) return thumbButtons[i];
            }
            return null;
        }

        function syncSelectedThumbMarker() {
            var activePage = activeThumbPage();
            for (var i = 0; i < thumbButtons.length; i++) {
                var page = thumbPage(thumbButtons[i]);
                thumbButtons[i].classList.toggle(
                    'pdf2html-selected',
                    selectedPage === page && selectedPage !== activePage
                );
            }
        }

        function setSelectedPage(page) {
            if (!page || page < 1) selectedPage = null;
            else selectedPage = Math.max(1, Math.min(pages.length, page));
            syncSelectedThumbMarker();
        }

        function selectedPageBase() {
            return selectedPage || activeThumbPage() || navigation.page() || 1;
        }

        function moveSelectedPage(delta) {
            setSelectedPage(selectedPageBase() + delta);
            var thumb = thumbForPage(selectedPage);
            if (thumb) {
                try { thumb.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' }); } catch (e) {}
            }
        }

        function replaceHashForPage(page) {
            try {
                history.replaceState(null, '', location.pathname + location.search + '#pf' + page.toString(16));
            } catch (e) {}
        }

        function commitSelectedPage() {
            if (!selectedPage) return;
            var pf = textInteraction.pageElement(selectedPage);
            if (!pf) return;
            navigation.setPage(selectedPage);
            syncThumbState(selectedPage, true);
            setSelectedPage(null);
            pc.scrollTop = Math.max(0, pf.offsetTop);
            replaceHashForPage(navigation.page());
        }

        function syncThumbState(page, center) {
            if (!page || page < 1) return;
            var active = null;
            for (var j = 0; j < thumbButtons.length; j++) {
                var on = thumbPage(thumbButtons[j]) === page;
                thumbButtons[j].classList.toggle('active', on);
                if (on) thumbButtons[j].setAttribute('aria-current', 'page');
                else thumbButtons[j].removeAttribute('aria-current');
                if (on) active = thumbButtons[j];
            }
            syncSelectedThumbMarker();
            if (active && center && thumbsTabVisible()) {
                try { active.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' }); } catch (err) {}
            }
        }

        document.addEventListener('pdf2html-page-change', function (e) {
            var page = e.detail && e.detail.page;
            syncThumbState(page, true);
        });

        new MutationObserver(function () {
            if (thumbsTabVisible()) syncThumbState(navigation.page(), true);
        }).observe(document.body, {
            attributes: true,
            attributeFilter: ['class', 'data-sidebar-tab'],
        });

        window.addEventListener('keydown', function (e) {
            if (e.metaKey || e.altKey) return;
            if (isInputTarget(e.target)) return;
            if (!thumbsTabVisible()) return;
            if (document.activeElement !== document.getElementById('pdf2html-sidebar-body')
                && document.body.getAttribute('data-scroll-focus') !== 'sidebar') return;

            var ctrlDown = e.ctrlKey && !e.shiftKey && (e.key === 'j' || e.key === 'J');
            var ctrlUp = e.ctrlKey && !e.shiftKey && (e.key === 'k' || e.key === 'K');
            var arrowDown = !e.ctrlKey && !e.shiftKey && e.key === 'ArrowDown';
            var arrowUp = !e.ctrlKey && !e.shiftKey && e.key === 'ArrowUp';
            if (ctrlDown || ctrlUp || arrowDown || arrowUp) {
                e.preventDefault();
                e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                moveSelectedPage((ctrlDown || arrowDown) ? 1 : -1);
                return;
            }

            if (!e.ctrlKey && !e.shiftKey && e.key === 'Enter') {
                if (!selectedPage) return;
                e.preventDefault();
                e.stopPropagation();
                if (e.stopImmediatePropagation) e.stopImmediatePropagation();
                commitSelectedPage();
            }
        }, true);

        syncThumbState(navigation.page(), false);
    }


    // ------------------------------------------------------------------------
    // Appearance settings — exposes window setters used by the settings
    // modal.
    //
    //  pdf2html-esc-clears  '1' | '0'  (default '1'; consulted in the
    //                                   escape handler)
    // ------------------------------------------------------------------------
    function applyAppearanceSettings() {
        window.__pdf2htmlSetEscClears = function (on) {
            localStorage.setItem('pdf2html-esc-clears', on ? '1' : '0');
        };
        window.__pdf2htmlSetSearchCase = function (on) {
            localStorage.setItem('pdf2html-search-case', on ? '1' : '0');
            var sIn = document.getElementById('pdf2html-search-input');
            if (sIn) textInteraction.refreshSearch(sIn.value);
        };
    }

    function isSearchCaseSensitive() {
        return localStorage.getItem('pdf2html-search-case') === '1';
    }


    // ------------------------------------------------------------------------
    // Settings modal — opens via `:set`, the sidebar footer button, or the
    // `⌘,` keybind. Groups: Appearance (theme/accent/zoom), Behavior
    // (counter, scrolloff, pin, case), Keyboard (leader, esc-clears).
    //
    // Controls talk to the same hidden #pdf2html-scrolloff-input /
    // -pinned-input that the palette commands fire change events on, so state
    // flows through a single persistence path.
    // ------------------------------------------------------------------------
    function openSettings() {
        var ex = document.getElementById('pdf2html-settings');
        if (ex) { ex.remove(); return; }

        var bd = el('div', {
            id: 'pdf2html-settings',
            class: 'pdf2html-modal-backdrop',
            onClick: function (e) { if (e.target === bd) bd.remove(); },
        });
        var card = el('div', { class: 'pdf2html-settings-card' });

        card.appendChild(el('div', { class: 'pdf2html-settings-head' }, [
            el('div', {}, [
                el('h2', {}, 'Settings'),
                el('div', { class: 'sub' }, ':set  ·  persisted locally'),
            ]),
            el('span', {
                class: 'close',
                html: '<span class="pdf2html-kbd sm">Esc</span> to close',
            }),
        ]));

        var body = el('div', { class: 'pdf2html-settings-body', tabindex: '-1' });

        // --- Appearance ------------------------------------------------
        // Slider shows the current effective zoom. If the stored value is
        // the 'auto' sentinel (or unset), read the resolved zoom off
        // #page-container so the slider tracks the auto-fit result.
        // Moving the slider switches mode to manual via __pdf2htmlSetZoom,
        // which writes per-doc.
        var zRaw = readZoomPref();
        var zPc = document.getElementById('page-container');
        var curZoom;
        if (zRaw === null || zRaw === 'auto') {
            curZoom = parseFloat(zPc && zPc.style.zoom) || 1.0;
        } else {
            curZoom = parseFloat(zRaw);
        }
        if (!isFinite(curZoom) || curZoom <= 0) curZoom = 1.0;

        body.appendChild(makeGroup('Appearance', [
            makeRow('Theme', 'Light PDF · dark chrome',
                makeSeg([
                    { value: 'dark',   label: 'Dark' },
                    { value: 'system', label: 'System' },
                ], 'dark', function () { /* monochromatic single theme */ })),
            makeRow('Zoom', 'Page-container scale (:zoom)',
                makeSliderWithValue(0.6, 2.5, 0.1, curZoom, function (v) {
                    if (window.__pdf2htmlSetZoom) window.__pdf2htmlSetZoom(v);
                })),
        ]));

        // --- Behavior --------------------------------------------------
        var counterVis   = localStorage.getItem('pdf2html-pageno-hidden') === '0';
        var curScrollOffPct = Math.round(
            (parseFloat(localStorage.getItem('pdf2html-scrolloff') || '0.25')) * 100);
        var pinnedOn = localStorage.getItem('pdf2html-pinned') !== '0';
        var caseOn = isSearchCaseSensitive();

        // Scrolloff slider + pin switch are cross-wired: flipping pin locks
        // the slider to 50% and disables it; flipping back restores the
        // stored scrolloff. Built inline so the two controls can see each
        // other without extra plumbing.
        var soReadout = el('span', { class: 'pdf2html-slider-readout' },
            (pinnedOn ? 50 : curScrollOffPct) + '%');
        var soInput = el('input', {
            type: 'range', class: 'pdf2html-slider-input',
            min: '0', max: '50', step: '1',
            value: String(pinnedOn ? 50 : curScrollOffPct),
        });
        if (pinnedOn) soInput.disabled = true;
        soInput.addEventListener('input', function () {
            var v = parseInt(soInput.value, 10);
            soReadout.textContent = v + '%';
            setInputValueAndFire('pdf2html-scrolloff-input', v);
        });
        var soWrap = el('div', { class: 'pdf2html-slider-wrap' });
        soWrap.appendChild(soInput);
        soWrap.appendChild(soReadout);

        var pinSwitchOnToggle = function (on) {
            setCheckboxAndFire('pdf2html-pinned-input', on);
            soInput.disabled = on;
            if (on) {
                soInput.value = '50';
                soReadout.textContent = '50%';
            } else {
                var stored = Math.round(parseFloat(localStorage.getItem('pdf2html-scrolloff') || '0.25') * 100);
                soInput.value = String(stored);
                soReadout.textContent = stored + '%';
            }
        };

        body.appendChild(makeGroup('Behavior', [
            makeRow('Page counter visible', 'Top pill; toggles with ⌘⇧. or :counter',
                makeSwitch(counterVis, function (on) {
                    var isHidden = document.body.classList.contains('pageno-hidden');
                    if ((on && isHidden) || (!on && !isHidden)) {
                        if (window.__pdf2htmlTogglePageno) window.__pdf2htmlTogglePageno();
                    }
                })),
            makeRow('Scrolloff', 'Auto-scroll when cursor enters ±N% band',
                soWrap),
            makeRow('Pin cursor to center', ':pin · locks scrolloff to 50%',
                makeSwitch(pinnedOn, pinSwitchOnToggle)),
            makeRow('Case-sensitive search', ':case · / matches exact casing',
                makeSwitch(caseOn, function (on) {
                    if (window.__pdf2htmlSetSearchCase) window.__pdf2htmlSetSearchCase(on);
                })),
        ]));

        // --- Keyboard --------------------------------------------------
        var escOn = localStorage.getItem('pdf2html-esc-clears') !== '0';

        body.appendChild(makeGroup('Keyboard', [
            makeRow('Leader key', 'Space (reserved for future mappings)',
                el('div', { class: 'pdf2html-kbd' }, 'Space')),
            makeRow('Escape clears selection', 'Esc on non-overlay clears text selection',
                makeSwitch(escOn, function (on) {
                    if (window.__pdf2htmlSetEscClears) window.__pdf2htmlSetEscClears(on);
                })),
        ]));

        card.appendChild(body);
        bd.appendChild(card);
        document.body.appendChild(bd);
    }

    function makeGroup(title, rows) {
        var g = el('div', { class: 'pdf2html-settings-group' });
        g.appendChild(el('h4', {}, title));
        rows.forEach(function (r) { g.appendChild(r); });
        return g;
    }
    function makeRow(label, hint, control) {
        return el('div', { class: 'pdf2html-settings-row' }, [
            el('div', {}, [
                el('div', { class: 'label' }, label),
                hint ? el('div', { class: 'hint' }, hint) : null,
            ].filter(Boolean)),
            control,
        ]);
    }
    function makeSeg(opts, current, onPick) {
        var s = el('div', { class: 'pdf2html-seg' });
        opts.forEach(function (o) {
            var btn = el('button', {
                class: (o.value === current) ? 'active' : '',
                onClick: function () {
                    var all = s.querySelectorAll('button');
                    for (var k = 0; k < all.length; k++) all[k].classList.remove('active');
                    btn.classList.add('active');
                    onPick(o.value);
                },
            }, o.label);
            s.appendChild(btn);
        });
        return s;
    }
    function makeSwitch(on, onToggle) {
        var sw = el('button', {
            type: 'button',
            class: 'pdf2html-switch' + (on ? ' on' : ''),
            role: 'switch',
            'aria-checked': on ? 'true' : 'false',
        });
        sw.addEventListener('click', function () {
            var v = !sw.classList.contains('on');
            sw.classList.toggle('on', v);
            sw.setAttribute('aria-checked', v ? 'true' : 'false');
            onToggle(v);
        });
        return sw;
    }
    function makeSliderWithValue(min, max, step, val, onChange) {
        var wrap = el('div', { class: 'pdf2html-slider-wrap' });
        var readout = el('span', { class: 'pdf2html-slider-readout' }, formatSlider(val));
        var inp = el('input', {
            type: 'range', class: 'pdf2html-slider-input',
            min: String(min), max: String(max), step: String(step), value: String(val),
        });
        inp.addEventListener('input', function () {
            var v = parseFloat(inp.value);
            readout.textContent = formatSlider(v);
            onChange(v);
        });
        wrap.appendChild(inp);
        wrap.appendChild(readout);
        return wrap;
    }
    function formatSlider(v) { return (Math.round(v * 10) / 10).toFixed(1) + '×'; }

    function setCheckboxAndFire(id, val) {
        var cb = document.getElementById(id);
        if (!cb) return;
        cb.checked = !!val;
        cb.dispatchEvent(new Event('change'));
    }

    function setInputValueAndFire(id, val) {
        if (isNaN(val)) return;
        var input = document.getElementById(id);
        if (!input) return;
        input.value = val;
        input.dispatchEvent(new Event('change'));
    }


    // ------------------------------------------------------------------------
    // Default zoom — pdf2htmlEX emits pages at the PDF's native CSS-pixel
    // size (1 PDF pt ≈ 1 px), which varies wildly: A4 ≈ 595px, US Letter
    // 612px, 16:9 slide deck 1920px, posters even more. A fixed multiplier
    // is wrong across that range, so default to auto-fit-to-viewport:
    // pick a zoom that makes the first page occupy ~85% of #page-container
    // width. Stored values are either the sentinel 'auto' (default) or a
    // raw numeric multiplier set via `:zoom N` / settings slider; `:zoom
    // auto` returns to fit mode.
    //
    // Persistence is per-document, mirroring mountResumePosition:
    //   pdf2html-zoom:<hash>  — this doc's setting (preferred)
    //   pdf2html-zoom         — global fallback / no-hash docs
    // ------------------------------------------------------------------------
    var ZOOM_KEY_GLOBAL = 'pdf2html-zoom';
    function zoomKey() {
        var h = entryHash();
        return h ? ZOOM_KEY_GLOBAL + ':' + h : null;
    }
    function readZoomPref() {
        var k = zoomKey();
        var v = k ? localStorage.getItem(k) : null;
        if (v !== null) return v;
        return localStorage.getItem(ZOOM_KEY_GLOBAL);
    }
    function writeZoomPref(v) {
        var k = zoomKey() || ZOOM_KEY_GLOBAL;
        localStorage.setItem(k, v);
    }

    function mountZoom() {
        var pc = document.getElementById('page-container');
        if (!pc) return;
        // Read native page width BEFORE any zoom is applied — `style.zoom`
        // mutates child getBoundingClientRect values in CSS pixels.
        var firstPf = pc.querySelector('.pf');
        var pageWidth = firstPf ? firstPf.getBoundingClientRect().width : 0;

        function autoFitZoom() {
            var vw = pc.clientWidth;
            if (!pageWidth || !vw) return 1.0;
            var z = 0.85 * vw / pageWidth;
            if (z < 0.5) z = 0.5;
            if (z > 3.0) z = 3.0;
            return z;
        }

        var raw = readZoomPref();
        var mode = (raw === null || raw === 'auto') ? 'auto' : 'manual';
        var z = (mode === 'auto') ? autoFitZoom() : parseFloat(raw);
        if (!isFinite(z) || z <= 0) { z = autoFitZoom(); mode = 'auto'; }
        pc.style.zoom = String(z);
        document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));

        window.__pdf2htmlSetZoom = function (n) {
            if (n === 'auto') {
                mode = 'auto';
                writeZoomPref('auto');
                pc.style.zoom = String(autoFitZoom());
                document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));
                return;
            }
            var num = (typeof n === 'number') ? n : parseFloat(n);
            if (!isFinite(num) || num <= 0 || num > 10) return;
            mode = 'manual';
            pc.style.zoom = String(num);
            writeZoomPref(String(num));
            document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));
        };

        // Re-fit on viewport resize when in auto mode. rAF-throttled so a
        // drag-resize doesn't trigger a storm of style.zoom writes.
        var pending = false;
        window.addEventListener('resize', function () {
            if (mode !== 'auto' || pending) return;
            pending = true;
            requestAnimationFrame(function () {
                pending = false;
                if (mode === 'auto') {
                    pc.style.zoom = String(autoFitZoom());
                    document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));
                }
            });
        });
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
    //     `inline` (no atomic boundary) and pins `font-size: 0` so the inner
    //     space character collapses to zero visual width — Chromium's find
    //     buffer is layout-text-driven and still sees the space, so multi-
    //     word queries match while the visual gap stays exactly what
    //     pdf2htmlEX intended (padding-left == original width).
    //
    // Runs synchronously at the top of init() (overlay.js is `defer`, so all
    // pdf2htmlEX <style> blocks have already parsed). Both steps live in one
    // synchronous block so the browser only relayouts once; no visual flash
    // between the rewrite and the override.
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
            }
        }
        if (!rewrote) return;
        var override = document.createElement('style');
        override.id = 'pdf2html-find-boundary-fix';
        override.textContent = '._{display:inline !important;font-size:0 !important;}';
        document.head.appendChild(override);
    }


    // ------------------------------------------------------------------------
    // Neutralize pdf2htmlEX's own render loop.
    // It's a setTimeout-driven loop that touches .pc inline styles on scroll,
    // which causes paint flashing now that we manage visibility ourselves.
    // ------------------------------------------------------------------------
    function killPdf2htmlExRenderLoop() {
        function kill(v) {
            try {
                if (v.render_timer) clearTimeout(v.render_timer);
                v.render_timer = null;
                v.render = function () {};
                return true;
            } catch (e) { return false; }
        }
        function attempt() {
            return window.pdf2htmlEX
                && window.pdf2htmlEX.defaultViewer
                && kill(window.pdf2htmlEX.defaultViewer);
        }
        if (attempt()) return;
        var n = 0;
        var iv = setInterval(function () {
            if (attempt() || ++n > 100) clearInterval(iv);
        }, 20);
    }

    function disablePageRasterDragging() {
        var rasters = document.querySelectorAll('#page-container .pc > img.bi');
        for (var i = 0; i < rasters.length; i++) {
            rasters[i].draggable = false;
            rasters[i].setAttribute('draggable', 'false');
        }
    }

    // ------------------------------------------------------------------------
    // Floating ☰ button top-left — click or ⌘. / ⌘B toggles sidebar.
    // ------------------------------------------------------------------------
    function mountSidebarToggleButton() {
        var b = document.createElement('button');
        b.id = 'pdf2html-toggle';
        b.title = 'Toggle sidebar (⌘. or ⌘B)';
        // Same SVG as the in-sidebar close button — one visual language
        // for "the sidebar affordance" whether it's open or closed.
        b.innerHTML = svgIcon(ICONS.sidebar, 16);
        b.onclick = function () { document.body.classList.toggle('sidebar-shown'); };
        document.body.appendChild(b);
    }

    function registerSidebarKeyHandler() {
        document.addEventListener('keydown', function (e) {
            if (isInputTarget(e.target)) return;
            // `!e.shiftKey` matters: ⌘⇧. is the page-counter toggle and on
            // some layouts (e.g. Norwegian) e.key still reads '.' with
            // shift held, so without this guard both handlers fire.
            if (e.metaKey && !e.shiftKey && (e.key === '.' || e.key === 'b' || e.key === 'B')) {
                e.preventDefault();
                document.body.classList.toggle('sidebar-shown');
                return;
            }
            // ←/→ (and h/l) switch tabs when the sidebar is open. Guarded on
            // sidebar-shown so arrows keep their default (scroll) behavior when
            // it's closed; h/l are guarded the same way so Vimium's own
            // bindings on those keys are untouched outside the sidebar.
            var leftKey  = e.key === 'ArrowLeft'  || e.key === 'h';
            var rightKey = e.key === 'ArrowRight' || e.key === 'l';
            if ((leftKey || rightKey)
                && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey
                && document.body.classList.contains('sidebar-shown')) {
                e.preventDefault();
                setSidebarTab(leftKey ? 'outline' : 'thumbs');
            }
        });
    }

    // Bare Tab in pdf2htmlEX content walks the browser's focus order through
    // page links/anchors and can scroll to a different page. Keep Tab local to
    // overlay chrome and inputs; on the PDF surface, it is intentionally inert.
    function registerDocumentTabGuard() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isInputTarget(e.target)) return;
            var t = e.target instanceof Element ? e.target : document.activeElement;
            if (t && t.closest && t.closest(
                '#pdf2html-palette, #pdf2html-finder, #pdf2html-settings, '
                + '#pdf2html-cheatsheet, #sidebar, #pdf2html-toggle'
            )) return;
            if (t === document.body
                || t === document.documentElement
                || (t && t.closest && t.closest('#page-container'))) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);
    }


    // ------------------------------------------------------------------------
    // Focus routing — scope Vimium's j/k to whichever overlay is open.
    //
    // Vimium tracks a separate `activatedElement` (its own notion of "what
    // j/k scrolls"), NOT document.activeElement. It updates activatedElement
    // only on DOMActivate (Chromium) or click (Firefox) — see Vimium's
    // scroller.js Scroller.init. So calling .focus() on a scroller has zero
    // effect on Vimium's scrolling behavior.
    //
    // To scope j/k to a container we must dispatch a DOMActivate (+ click,
    // for Firefox parity) on it. activate() below does all three: focus for
    // native keyboard nav (Tab/arrow-scroll), DOMActivate + click for Vimium.
    //
    // Declarative routing via MutationObserver avoids wrapping every open/
    // close call site (sidebar toggles live in 5+ places; modals close via
    // Esc, backdrop click, and toggle keys). The observer reacts to the
    // canonical state change — body.sidebar-shown toggling, modal nodes
    // added/removed — so new call sites automatically participate.
    //
    // Modals stash the previously-activated element on open and restore it
    // on close, so closing settings-opened-over-sidebar hands j/k back to
    // the sidebar. Sidebar close re-activates document.body so j/k scrolls
    // the main page.
    //
    // Safety re: synthetic click — backdrop "click outside to close" checks
    // e.target === backdrop, and the scroll containers are either descendants
    // of their backdrop (modals) or on a sibling tree (sidebar vs its
    // backdrop), so bubbling won't trigger a close.
    // ------------------------------------------------------------------------
    function registerFocusRouting() {
        var prevActivation = { settings: null, cheatsheet: null };
        var body = document.body;

        function setScrollFocus(kind) {
            body.setAttribute('data-scroll-focus', kind);
        }
        function activate(el, kind) {
            if (!el) return;
            if (kind) setScrollFocus(kind);
            try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (e2) {} }
            try { el.dispatchEvent(new Event('DOMActivate', { bubbles: true, cancelable: true })); } catch (e) {}
            try { el.dispatchEvent(new MouseEvent('click',   { bubbles: true, cancelable: true })); } catch (e) {}
        }
        function stash(kind) {
            var ae = document.activeElement;
            prevActivation[kind] = (ae && ae !== document.body) ? ae : null;
        }
        // Handing j/k back to the PDF: DOMActivate alone isn't enough (Vimium
        // needs the click too), so we dispatch both, then immediately clear
        // any selection range created by pdf2htmlEX's own click listener on
        // the text layer (the blue glow the user saw is our ::selection color
        // on a tiny range that the click materializes).
        function activateMain() {
            setScrollFocus('main');
            var el = document.getElementById('page-container') || document.body;
            try { el.dispatchEvent(new Event('DOMActivate', { bubbles: true, cancelable: true })); } catch (e) {}
            try { el.dispatchEvent(new MouseEvent('click',   { bubbles: true, cancelable: true })); } catch (e) {}
            try {
                var sel = window.getSelection();
                if (sel && sel.rangeCount > 0) sel.removeAllRanges();
            } catch (e) {}
        }
        function activateSidebar() {
            activate(document.getElementById('pdf2html-sidebar-body'), 'sidebar');
        }
        function restore(kind) {
            var target = prevActivation[kind];
            prevActivation[kind] = null;
            if (target && document.contains(target)) {
                var role = target.id === 'pdf2html-sidebar-body' ? 'sidebar'
                    : (target.id === 'page-container' ? 'main' : null);
                activate(target, role);
            }
            else activateMain();
        }

        window.__pdf2htmlFocusMain = activateMain;
        window.__pdf2htmlFocusSidebar = activateSidebar;

        var pc = document.getElementById('page-container');
        if (pc) pc.addEventListener('mousedown', function () {
            if (body.classList.contains('sidebar-shown')) activateMain();
        });
        var sidebarBody = document.getElementById('pdf2html-sidebar-body');
        if (sidebarBody) sidebarBody.addEventListener('mousedown', function () {
            if (body.classList.contains('sidebar-shown')) activateSidebar();
        });

        // Sidebar: body.sidebar-shown is the canonical "visible" signal.
        var wasShown = body.classList.contains('sidebar-shown');
        new MutationObserver(function () {
            var isShown = body.classList.contains('sidebar-shown');
            if (isShown === wasShown) return;
            wasShown = isShown;
            if (isShown) {
                activateSidebar();
            } else {
                // Hand j/k back to the PDF scroller.
                activateMain();
            }
        }).observe(body, { attributes: true, attributeFilter: ['class'] });

        // Modals: react to addition/removal of the backdrop nodes.
        new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                for (var i = 0; i < m.addedNodes.length; i++) {
                    var n = m.addedNodes[i];
                    if (!(n instanceof HTMLElement)) continue;
                    if (n.id === 'pdf2html-settings') {
                        stash('settings');
                        activate(n.querySelector('.pdf2html-settings-body'));
                    } else if (n.id === 'pdf2html-cheatsheet') {
                        stash('cheatsheet');
                        activate(n.querySelector('.pdf2html-cheatsheet-body'));
                    }
                }
                for (var j = 0; j < m.removedNodes.length; j++) {
                    var r = m.removedNodes[j];
                    if (!(r instanceof HTMLElement)) continue;
                    if (r.id === 'pdf2html-settings') restore('settings');
                    else if (r.id === 'pdf2html-cheatsheet') restore('cheatsheet');
                }
            });
        }).observe(body, { childList: true });

        setScrollFocus(body.classList.contains('sidebar-shown') ? 'sidebar' : 'main');
    }


    // ------------------------------------------------------------------------
    // Escape: priority chain — palette → cheatsheet → clear selection.
    // Capture phase, since Vimium also listens for Escape.
    // ------------------------------------------------------------------------
    function registerEscapeHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            if (commandSurface.closeFinderOrPalette()) { e.preventDefault(); e.stopPropagation(); return; }
            if (finger.isActive()) { e.preventDefault(); e.stopPropagation(); finger.closeFingerMode(); return; }
            if (isInputTarget(e.target)) return;
            var settings = document.getElementById('pdf2html-settings');
            if (settings) { settings.remove(); return; }
            if (commandSurface.closeHelp()) return;
            if (document.body.classList.contains('sidebar-shown')) {
                document.body.classList.remove('sidebar-shown');
                return;
            }
            if (localStorage.getItem('pdf2html-esc-clears') === '0') return;
            var sel = window.getSelection();
            if (sel && !sel.isCollapsed) sel.removeAllRanges();
        }, true);
    }


    // ------------------------------------------------------------------------
    // Cheatsheet overlay — ? toggles, :help invokes.
    // ------------------------------------------------------------------------
    function registerPageJumpHandler() {
        var buf = '';
        var timer = null;
        function clearBuf() {
            buf = '';
            if (timer) { clearTimeout(timer); timer = null; }
        }
        document.addEventListener('keydown', function (e) {
            if (isInputTarget(e.target)) { clearBuf(); return; }
            if (e.metaKey || e.ctrlKey || e.altKey) { clearBuf(); return; }
            if (e.key >= '0' && e.key <= '9') {
                buf = (buf + e.key).slice(-6);
                e.preventDefault(); e.stopPropagation();
                if (timer) clearTimeout(timer);
                timer = setTimeout(clearBuf, 1500);
                return;
            }
            var k = e.key;
            if (k !== 'e' && k !== 'q' && k !== 'E' && k !== 'c' && k !== 'C') {
                clearBuf();
                return;
            }
            var count = parseInt(buf, 10) || 1;
            clearBuf();
            e.preventDefault(); e.stopPropagation();
            if (k === 'e' || k === 'q' || k === 'E') {
                var delta = k === 'e' ? count : -count;
                if (!textInteraction.extendSelectionByPage(delta)) {
                    var total = document.querySelectorAll('.pf').length || 1;
                    navigation.snapToPage(Math.min(total, Math.max(1, navigation.page() + delta)));
                }
            } else {
                if (k === 'c' && textInteraction.selectCurrentChapterFromSelection()) return;
                navigation.gotoChapterBy(k === 'c' ? count : -count);
            }
        }, true);
    }


    // ------------------------------------------------------------------------
    // Cursor pin / scrolloff — CSS scroll-padding on #page-container is the
    // single source of truth. Setting --pdf2html-scrolloff as a percentage
    // defines the reserved band at top and bottom; every native scroll-into-
    // view path (caret on keyboard input, shift+arrow selection extend, click
    // to place caret, Vimium caret mode, hash navigation, outline clicks,
    // :gg/:G, search next) honors it without JS.
    //
    //   pinned=false → padding = scrollOffFraction × 100%  (0% = off, 25% =
    //                  keep caret in middle half, etc.)
    //   pinned=true  → padding = 50% both sides. The "safe" region collapses
    //                  to a single line at center, so any caret movement
    //                  recenters (Vim `scrolloff=999`).
    // ------------------------------------------------------------------------
    function mountOutlineActiveTracker() {
        var outline = document.getElementById('outline');
        var pc = document.getElementById('page-container');
        if (!outline || !pc) return;

        var links = Array.prototype.slice.call(outline.querySelectorAll('a[href^="#pf"]'));
        if (!links.length) return;

        var targets = links.map(function (a) {
            var m = (a.getAttribute('href') || '').match(/#pf([0-9a-f]+)/i);
            return m ? parseInt(m[1], 16) : NaN;
        });

        var pages = document.querySelectorAll('.pf');
        // NOTE: cached offsets. If layout changes (e.g. zoom) these go stale.
        // Acceptable for outline highlight — worst case is slightly wrong
        // highlight until next scroll reset. Not worth an IntersectionObserver here.
        var offs = Array.prototype.map.call(pages, function (p) {
            return { t: p.offsetTop, b: p.offsetTop + p.offsetHeight };
        });
        var lastActive = -1;

        function setActive(active) {
            if (active === lastActive) return;
            if (lastActive >= 0) links[lastActive].classList.remove('pdf2html-active');
            if (active >= 0) {
                links[active].classList.add('pdf2html-active');
                try { links[active].scrollIntoView({ block: 'nearest' }); } catch (e) {}
            }
            lastActive = active;
        }

        function update() {
            var st = pc.scrollTop, sb = st + pc.clientHeight, bestIdx = 0, bestO = -1;
            for (var i = 0; i < offs.length; i++) {
                var o = Math.min(offs[i].b, sb) - Math.max(offs[i].t, st);
                if (o > bestO) { bestO = o; bestIdx = i; }
            }
            var cur = bestIdx + 1, active = -1;
            for (var j = 0; j < targets.length; j++) {
                if (!isNaN(targets[j]) && targets[j] <= cur) active = j;
            }
            setActive(active);
        }

        var raf = null;
        function sched() {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; update(); });
        }
        for (var k = 0; k < links.length; k++) (function (idx) {
            links[idx].addEventListener('click', function () { setActive(idx); });
        })(k);
        pc.addEventListener('scroll', sched, { passive: true });
        update();
    }


    // ------------------------------------------------------------------------
    // Page counter — small "N / total" pill at top-center, updates on scroll.
    // Tracks the current page by live viewport overlap against the currently
    // intersecting .pf frames, so it stays correct even when the page itself
    // doesn't happen to cover the viewport's exact center point.
    // ------------------------------------------------------------------------
    function mountPageCounter() {
        var container = document.getElementById('page-container');
        if (!container) return;
        var pages = Array.prototype.slice.call(container.querySelectorAll('.pf'));
        var total = pages.length;
        if (!total) return;

        var el = document.createElement('div');
        el.id = 'pdf2html-pageno';
        // Three zones: .side.left holds a chapter reference (e.g. "Ch. 3.8"),
        // .center holds the page numerals, .side.right holds a chapter/section
        // title. When only one of the two is available, it falls back to the
        // left. The pill's translateX is live-adjusted via --pageno-shift so
        // .center always lands on the viewport's exact horizontal middle,
        // regardless of side widths.
        el.innerHTML =
            '<span class="side left" hidden>' +
                '<span class="text"></span>' +
                '<span class="sep">·</span>' +
            '</span>' +
            '<span class="center">' +
                '<span class="cur" id="pdf2html-pageno-current">1</span>' +
                '<span class="sep">/</span>' +
                '<span class="tot">' + total + '</span>' +
            '</span>' +
            '<span class="side right" hidden>' +
                '<span class="sep">·</span>' +
                '<span class="text"></span>' +
            '</span>';
        document.body.appendChild(el);

        // Default: hidden. Only show if the user has explicitly enabled it
        // via ⌘⇧. or the `:counter` palette command (which writes '0').
        if (localStorage.getItem('pdf2html-pageno-hidden') !== '0') {
            document.body.classList.add('pageno-hidden');
        }
        var cur       = document.getElementById('pdf2html-pageno-current');
        var leftEl    = el.querySelector('.side.left');
        var rightEl   = el.querySelector('.side.right');
        var leftText  = leftEl.querySelector('.text');
        var rightText = rightEl.querySelector('.text');

        function recenterCenter() {
            // Two modes:
            //   (a) both sides visible → pin .center's midpoint to viewport
            //       midpoint by shifting the pill by half the side-width
            //       imbalance. Prevents the numerals from drifting when one
            //       title is much longer than the other.
            //   (b) zero or one side visible → leave the pill centered as a
            //       whole (shift=0). A single-sided pill pinned to viewport
            //       center looks lopsided because nothing visually balances
            //       the other side.
            if (leftEl.hidden || rightEl.hidden) {
                el.style.setProperty('--pageno-shift', '0px');
                return;
            }
            var pillGap = 8;
            var L = leftEl.offsetWidth  + pillGap;
            var R = rightEl.offsetWidth + pillGap;
            el.style.setProperty('--pageno-shift', ((R - L) / 2) + 'px');
        }
        // One observer handles both content changes (chapter update) and
        // viewport resizes that trip the pill's max-width clamp.
        try { new ResizeObserver(recenterCenter).observe(el); } catch (_) {}

        function updateChapter() {
            // Split active outline label into "Ch. N" + sub-title if it fits
            // the pdf2htmlEX common pattern "1.2 Title" or "Chapter 3: Title".
            var active = document.querySelector('#outline a.pdf2html-active');
            var label = active ? (active.textContent || '').trim() : '';
            var chapPart = '', subPart = '';
            if (label) {
                var m = label.match(/^\s*((?:\d+)(?:\.\d+)*)\s+(.*)$/);
                if (m) {
                    chapPart = 'Ch. ' + m[1];
                    subPart  = m[2];
                } else {
                    subPart  = label;
                }
            }
            // Chapter reference goes left, title goes right. If only one is
            // available, put it on the left so the pill stays compact rather
            // than awkwardly listing to one side.
            var lt = '', rt = '', leftKind = 'sub', rightKind = 'sub';
            if (chapPart && subPart) {
                lt = chapPart; rt = subPart; leftKind = 'muted'; rightKind = 'muted';
            } else if (chapPart) {
                lt = chapPart; leftKind = 'chap';
            } else if (subPart) {
                lt = subPart;
            }
            leftText.className   = 'text ' + leftKind;
            leftText.textContent = lt;
            rightText.className   = 'text ' + rightKind;
            rightText.textContent = rt;
            leftEl.hidden  = !lt;
            rightEl.hidden = !rt;
            recenterCenter();
        }

        var lastPageNum = -1;
        var visible = new Set();

        function pageNumFor(pf, fallback) {
            var m = (pf && pf.id || '').match(/pf([0-9a-f]+)/i);
            return m ? parseInt(m[1], 16) : fallback;
        }

        function bestVisiblePageFrom(candidates, viewportBox) {
            var best = null;
            var bestOverlap = -1;
            for (var i = 0; i < candidates.length; i++) {
                var pf = candidates[i];
                var rect = pf.getBoundingClientRect();
                var overlap = Math.min(rect.bottom, viewportBox.bottom) - Math.max(rect.top, viewportBox.top);
                if (overlap > bestOverlap) {
                    bestOverlap = overlap;
                    best = pf;
                }
            }
            if (!best || bestOverlap <= 0) return null;
            return pageNumFor(best, 1);
        }

        function bestVisiblePage() {
            var box = container.getBoundingClientRect();
            var candidates = visible.size ? Array.from(visible) : pages;
            return bestVisiblePageFrom(candidates, box)
                || (candidates === pages ? null : bestVisiblePageFrom(pages, box));
        }

        function update() {
            // Always run — consumers like the thumbnails grid listen for
            // pdf2html-page-change regardless of whether the pageno pill
            // itself is visible. Render the numeral whenever the pill is
            // visible, even if the current page was already learned while the
            // pill was hidden.
            var n = bestVisiblePage();
            if (!n) return;
            if (!document.body.classList.contains('pageno-hidden')) {
                if (cur.textContent !== String(n)) cur.textContent = String(n);
            }
            if (n !== lastPageNum) {
                lastPageNum = n;
                updateChapter();
                document.dispatchEvent(new CustomEvent(
                    'pdf2html-page-change', { detail: { page: n } }));
            }
        }

        var observer = new IntersectionObserver(function (entries) {
            for (var i = 0; i < entries.length; i++) {
                if (entries[i].isIntersecting) visible.add(entries[i].target);
                else visible.delete(entries[i].target);
            }
            sched();
        }, {
            root: container,
            rootMargin: '-20px 0px',
            threshold: 0,
        });
        pages.forEach(function (p) { observer.observe(p); });

        var raf = null;
        function sched() {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; update(); });
        }
        container.addEventListener('scroll', function () {
            sched();
        }, { passive: true });
        document.addEventListener('pdf2html-page-counter-refresh', function () {
            sched();
            requestAnimationFrame(sched);
            setTimeout(sched, 80);
            setTimeout(sched, 250);
        });
        document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));

        window.__pdf2htmlTogglePageno = function () {
            var hide = !document.body.classList.contains('pageno-hidden');
            document.body.classList.toggle('pageno-hidden', hide);
            localStorage.setItem('pdf2html-pageno-hidden', hide ? '1' : '0');
            if (!hide) update();
        };
    }

    // ------------------------------------------------------------------------
    // Resume position — jump back to the last-visited page on reopen.
    //
    // Key: `pdf2html-position:<hash>` → JSON {page, ts}. Written on every
    // pdf2html-page-change (debounced 400ms); read once at init.
    //
    // The URL hash and the saved position must not fight each other:
    //   - A `#pfXX` deep link (outline/bookmark) wins on load, but native
    //     anchoring is unreliable here — pdf2htmlEX pages + content-visibility
    //     land at the top before late layout, so we actively scroll to the
    //     target ourselves with the same RAF retry loop as the restore path.
    //   - Once the reader scrolls away from that target the writer strips the
    //     now-stale `#pfXX`, so the next reload takes the saved-position path
    //     instead of re-anchoring to a page they already left.
    //   - An unknown hash (`#foo`) is treated as no hash: we strip it (else the
    //     browser's own anchor scroll fights our restore) and resume normally.
    // Saved page 1 is treated as "nothing to resume."
    // ------------------------------------------------------------------------
    function mountResumePosition() {
        var hash = entryHash();
        if (!hash) return;
        var key = 'pdf2html-position:' + hash;

        // Parse `#pfXX` → page number; same regex shape as elsewhere
        // (outline links, getChapters). Null for an empty or unknown hash.
        function pageFromLocationHash() {
            var m = (location.hash || '').match(/#pf([0-9a-f]+)/i);
            return m ? parseInt(m[1], 16) : null;
        }

        function stripHash() {
            try {
                history.replaceState(null, '', location.pathname + location.search);
            } catch (_) {}
        }

        // Shared RAF retry loop: wait for the page element to lay out, then
        // scroll it to the top. Used by both the deep-link and restore paths.
        function scrollToPage(target) {
            var tries = 0;
            var go = function () {
                var pel = document.getElementById('pf' + target.toString(16));
                if (pel && pel.offsetHeight > 0) {
                    pel.scrollIntoView({ block: 'start' });
                    document.dispatchEvent(new CustomEvent('pdf2html-page-counter-refresh'));
                    return;
                }
                if (tries++ < 60) requestAnimationFrame(go);
            };
            requestAnimationFrame(go);
        }

        var hashPage = pageFromLocationHash();
        if (hashPage && hashPage > 0) {
            // Honor the deep link: native anchoring doesn't hold, so drive it.
            // The subsequent debounced write records the correct page.
            scrollToPage(hashPage);
        } else {
            // No hash, or an unknown hash we ignore: restore saved position.
            // An unknown hash (`#foo`) still makes the browser run its own
            // anchor scroll after load, which overrides our restore; strip it
            // first so the only scroll is ours.
            if (location.hash) stripHash();
            var saved = null;
            try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) {}
            if (saved && saved.page > 1) scrollToPage(saved.page);
        }

        var writeTimer = null;
        var lastWritten = null;   // last page persisted to localStorage
        var pendingPage = null;   // page from the latest change, write pending

        function flush() {
            if (writeTimer) { clearTimeout(writeTimer); writeTimer = null; }
            if (pendingPage == null) return;
            var p = pendingPage;
            pendingPage = null;
            try {
                localStorage.setItem(key, JSON.stringify({ page: p, ts: Date.now() }));
            } catch (_) {}
            lastWritten = p;
            // Keep the URL hash honest: once the reader has scrolled off the
            // outline target, a stale `#pfXX` would otherwise re-anchor on the
            // next reload and skip the saved-position restore. Strip it so the
            // saved position wins.
            var hp = pageFromLocationHash();
            if (hp != null && hp !== p) stripHash();
        }

        document.addEventListener('pdf2html-page-change', function (e) {
            var p = e.detail && e.detail.page;
            if (!p || p < 1) return;
            pendingPage = p;
            if (writeTimer) clearTimeout(writeTimer);
            writeTimer = setTimeout(flush, 400);
        });

        // A reload/close inside the 400ms debounce window would lose the last
        // movement; flush synchronously on pagehide to land it.
        window.addEventListener('pagehide', function () {
            if (pendingPage != null && pendingPage !== lastWritten) flush();
        });
    }

    // ------------------------------------------------------------------------
    // Sidebar header — title + author/pages block at the top of #sidebar.
    //
    // Pulls from /<hash>/meta.json (written by scripts/extract-pdf-meta.sh).
    // Falls back to <title> if meta is missing or the fetch fails. Non-fatal:
    // the sidebar is fully usable without a header; this is chrome.
    // ------------------------------------------------------------------------
    function mountSidebarHeader() {
        var sidebar = document.getElementById('sidebar');
        if (!sidebar) return;

        var titleEl = el('div', { class: 'doc-title' }, document.title || 'Document');
        var metaEl  = el('div', { class: 'doc-meta' });
        var head = el('div', { id: 'pdf2html-sidebar-head' }, [
            el('div', { class: 'doc-text' }, [titleEl, metaEl]),
            el('button', {
                class: 'pdf2html-sidebar-close',
                title: 'Close sidebar (⌘. or ⌘B)',
                onClick: function () {
                    document.body.classList.remove('sidebar-shown');
                },
                html: svgIcon(ICONS.sidebar, 15),
            }),
        ]);
        sidebar.insertBefore(head, sidebar.firstChild);

        var hash = entryHash();
        if (!hash) return;
        var metaUrl = '/' + hash + '/meta.json';
        fetch(metaUrl, { cache: 'force-cache' }).then(function (r) {
            return r.ok ? r.json() : null;
        }).then(function (m) {
            if (!m) return;
            if (m.title) titleEl.textContent = String(m.title);
            var parts = [];
            if (m.author) parts.push(String(m.author));
            if (m.pages)  parts.push(String(m.pages) + ' pages');
            metaEl.textContent = parts.join(' · ');
        }).catch(function () { /* non-fatal */ });
    }


    function registerPagenoToggleHandler() {
        // ⌘⇧.
        document.addEventListener('keydown', function (e) {
            if (!(e.metaKey && e.shiftKey && e.code === 'Period')) return;
            if (isInputTarget(e.target)) return;
            e.preventDefault();
            if (window.__pdf2htmlTogglePageno) window.__pdf2htmlTogglePageno();
        });
    }


    // ------------------------------------------------------------------------
    // Scoped search (/) — find-in-visible-pages.
    //
    // Distinct from Vimium's / and from ⌘F: scope is the pages currently
    // intersecting the viewport at the moment of typing, and the viewport
    // never moves while typing. The reader refines the query without the
    // page jumping around; Enter is the explicit "take me there" action.
    //
    //   /        open the bar (stolen from Vimium via capture-phase handler)
    //   typing   live highlight across visible .pf frames — no scroll
    //   Enter    activate the hit closest to the cursor pin, scroll to it,
    //            then hide the bar (highlights persist — nvim hlsearch)
    //   n / N    next / prev hit (global after Enter, while highlights live)
    //   Esc      clear highlights; if bar is still open, closes that too
    //
    // Highlights use the CSS Custom Highlight API so we don't wrap nodes
    // inside pdf2htmlEX's positioned .t spans (which have utility classes
    // for letter- and word-spacing that DOM surgery would visibly break).
    // ------------------------------------------------------------------------
    // ------------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------------
    function isInputTarget(t) {
        return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
    }
})();
