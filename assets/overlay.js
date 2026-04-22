// ============================================================================
// pdf_viewer overlay — runtime layer on top of pdf2htmlEX's output.
//
// Served as /_assets/overlay.js, loaded via <script src="..." defer> injected
// into each converted HTML. Everything runs on DOMContentLoaded.
// ============================================================================

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', init);

    function init() {
        killPdf2htmlExRenderLoop();
        mountSidebarToggleButton();
        registerEscapeHandler();
        registerQuestionHandler();
        registerPaletteHandler();
        registerQuickOpenHandler();
        registerPagenoToggleHandler();
        registerRenderAllHandler();
        registerSidebarKeyHandler();
        registerFocusRouting();
        registerPageTracker();
        mountCursorPin();
        mountRenderWindow();
        mountOutlineActiveTracker();
        mountPageCounter();
        mountResumePosition();
        mountZoom();
        mountSidebarBackdrop();
        mountSidebarChrome();
        mountSidebarHeader();
        mountThumbnails();
        mountSearch();
        applyAppearanceSettings();
        loadLibrary();
    }

    // Module-level page tracker. mountPageCounter dispatches pdf2html-page-change
    // on scroll; other commands (`:mark`, `:yank`) read from here instead of
    // recomputing via elementFromPoint.
    var currentPage = 1;
    function registerPageTracker() {
        document.addEventListener('pdf2html-page-change', function (e) {
            if (e.detail && e.detail.page) currentPage = e.detail.page;
        });
    }

    function currentChapterLabel() {
        var link = document.querySelector('#outline a.pdf2html-active');
        return link ? (link.textContent || '').replace(/\s+/g, ' ').trim() : '';
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
    // Sidebar backdrop — dims + blurs the PDF when the sidebar is shown.
    // Always in DOM; visibility driven by body.sidebar-shown class. Clicking
    // the backdrop closes the sidebar (Comet-style "tap outside to dismiss").
    // ------------------------------------------------------------------------
    function mountSidebarBackdrop() {
        var bd = document.createElement('div');
        bd.id = 'pdf2html-sidebar-backdrop';
        bd.addEventListener('click', function () {
            document.body.classList.remove('sidebar-shown');
        });
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
                onClick: toggleCheatsheet,
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
            }, [inner, el('div', { class: 'thumb-label' }, String(pageNum))]);
            host.appendChild(card);
        })(pages[i], i);

        document.addEventListener('pdf2html-page-change', function (e) {
            var page = e.detail && e.detail.page;
            var thumbs = host.querySelectorAll('.pdf2html-thumb');
            var active = null;
            for (var j = 0; j < thumbs.length; j++) {
                var on = parseInt(thumbs[j].dataset.page, 10) === page;
                thumbs[j].classList.toggle('active', on);
                if (on) active = thumbs[j];
            }
            // Only auto-scroll the thumb into view when the sidebar is open
            // AND the thumbs tab is active, so we don't steal scroll position
            // while the user is reading.
            if (active
                && document.body.classList.contains('sidebar-shown')
                && document.body.getAttribute('data-sidebar-tab') === 'thumbs') {
                try { active.scrollIntoView({ block: 'nearest' }); } catch (err) {}
            }
        });
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
    }


    // ------------------------------------------------------------------------
    // Settings modal — opens via `:set`, the sidebar footer button, or the
    // `⌘,` keybind. Groups: Appearance (theme/accent/zoom), Behavior
    // (render-all, counter, buffer, pin), Keyboard (leader, esc-clears,
    // smooth-scroll).
    //
    // Controls talk to the same hidden #pdf2html-all-input / -buffer-input /
    // -pin-input that the palette commands fire change events on, so state
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
        var curZoom = parseFloat(localStorage.getItem('pdf2html-zoom') || '1.4');
        if (!isFinite(curZoom) || curZoom <= 0) curZoom = 1.4;

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
        var renderAllOn  = localStorage.getItem('pdf2html-render-all') === '1';
        var counterVis   = localStorage.getItem('pdf2html-pageno-hidden') === '0';
        var curBuffer    = parseInt(localStorage.getItem('pdf2html-buffer') || '10', 10);
        if (isNaN(curBuffer)) curBuffer = 10;
        var curScrollOffPct = Math.round(
            (parseFloat(localStorage.getItem('pdf2html-scrolloff') || '0.25')) * 100);
        var pinnedOn = localStorage.getItem('pdf2html-pinned') !== '0';

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
                var stored = Math.round(scrollOffFraction * 100);
                soInput.value = String(stored);
                soReadout.textContent = stored + '%';
            }
        };

        body.appendChild(makeGroup('Behavior', [
            makeRow('Render all pages', ':all · heavy for long docs',
                makeSwitch(renderAllOn, function (on) {
                    setCheckboxAndFire('pdf2html-all-input', on);
                })),
            makeRow('Page counter visible', 'Top pill; toggles with ⌘⇧. or :counter',
                makeSwitch(counterVis, function (on) {
                    var isHidden = document.body.classList.contains('pageno-hidden');
                    if ((on && isHidden) || (!on && !isHidden)) {
                        if (window.__pdf2htmlTogglePageno) window.__pdf2htmlTogglePageno();
                    }
                })),
            makeRow('Render buffer', 'Pages kept rendered ±N around viewport',
                makeSeg([
                    { value: 5,  label: '±5'  },
                    { value: 10, label: '±10' },
                    { value: 20, label: '±20' },
                    { value: 50, label: '±50' },
                ], curBuffer, function (v) {
                    setInputValueAndFire('pdf2html-buffer-input', v);
                })),
            makeRow('Scrolloff', 'Auto-scroll when cursor enters ±N% band',
                soWrap),
            makeRow('Pin cursor to center', ':pin · locks scrolloff to 50%',
                makeSwitch(pinnedOn, pinSwitchOnToggle)),
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
        var sw = el('div', { class: 'pdf2html-switch' + (on ? ' on' : '') });
        sw.addEventListener('click', function () {
            var v = !sw.classList.contains('on');
            sw.classList.toggle('on', v);
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


    // ------------------------------------------------------------------------
    // Default zoom — pdf2htmlEX emits pages at the PDF's native size (~595px
    // wide for A4), which leaves huge margins on a modern wide viewport.
    // Apply a CSS `zoom` to #page-container on load so the default view
    // fills more of the screen, closer to Chrome's fit-to-width. Persist to
    // localStorage; tweak via `:zoom 1.8` palette command.
    // ------------------------------------------------------------------------
    function mountZoom() {
        var pc = document.getElementById('page-container');
        if (!pc) return;
        var raw = localStorage.getItem('pdf2html-zoom');
        var z = raw !== null ? parseFloat(raw) : 1.4;
        if (!isFinite(z) || z <= 0) z = 1.4;
        pc.style.zoom = String(z);

        window.__pdf2htmlSetZoom = function (n) {
            if (!isFinite(n) || n <= 0 || n > 10) return;
            pc.style.zoom = String(n);
            localStorage.setItem('pdf2html-zoom', String(n));
        };
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


    // ------------------------------------------------------------------------
    // Floating ☰ button top-left — click or `s` / ⌘. toggles sidebar.
    // ------------------------------------------------------------------------
    function mountSidebarToggleButton() {
        var b = document.createElement('button');
        b.id = 'pdf2html-toggle';
        b.title = 'Toggle sidebar (⌘. or s)';
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
            if (e.metaKey && !e.shiftKey && e.key === '.') {
                e.preventDefault();
                document.body.classList.toggle('sidebar-shown');
                return;
            }
            if (e.key === 's' && !e.metaKey && !e.ctrlKey && !e.altKey) {
                document.body.classList.toggle('sidebar-shown');
                return;
            }
            // ←/→ switch tabs when the sidebar is open. Guarded on sidebar-shown
            // so arrows keep their default (scroll) behavior when it's closed.
            if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight')
                && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey
                && document.body.classList.contains('sidebar-shown')) {
                e.preventDefault();
                setSidebarTab(e.key === 'ArrowLeft' ? 'outline' : 'thumbs');
            }
        });
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

        function activate(el) {
            if (!el) return;
            try { el.focus({ preventScroll: true }); } catch (e) { try { el.focus(); } catch (e2) {} }
            try { el.dispatchEvent(new Event('DOMActivate', { bubbles: true, cancelable: true })); } catch (e) {}
            try { el.dispatchEvent(new MouseEvent('click',   { bubbles: true, cancelable: true })); } catch (e) {}
        }
        function stash(kind) {
            var ae = document.activeElement;
            prevActivation[kind] = (ae && ae !== document.body) ? ae : null;
        }
        function mainScrollTarget() {
            // The PDF scroller — what j/k should drive when no overlay owns focus.
            return document.getElementById('page-container') || document.body;
        }
        function restore(kind) {
            var target = prevActivation[kind];
            prevActivation[kind] = null;
            if (target && document.contains(target)) activate(target);
            else activate(mainScrollTarget());
        }

        // Sidebar: body.sidebar-shown is the canonical "visible" signal.
        var wasShown = document.body.classList.contains('sidebar-shown');
        new MutationObserver(function () {
            var isShown = document.body.classList.contains('sidebar-shown');
            if (isShown === wasShown) return;
            wasShown = isShown;
            if (isShown) {
                activate(document.getElementById('pdf2html-sidebar-body'));
            } else {
                // Hand j/k back to the PDF scroller.
                activate(mainScrollTarget());
            }
        }).observe(document.body, { attributes: true, attributeFilter: ['class'] });

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
        }).observe(document.body, { childList: true });
    }


    // ------------------------------------------------------------------------
    // Escape: priority chain — palette → cheatsheet → clear selection.
    // Capture phase, since Vimium also listens for Escape.
    // ------------------------------------------------------------------------
    function registerEscapeHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            var pal = document.getElementById('pdf2html-palette');
            if (pal) { e.preventDefault(); e.stopPropagation(); pal.remove(); return; }
            if (isInputTarget(e.target)) return;
            var settings = document.getElementById('pdf2html-settings');
            if (settings) { settings.remove(); return; }
            var cs = document.getElementById('pdf2html-cheatsheet');
            if (cs) { cs.remove(); return; }
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
    function toggleCheatsheet() {
        var ex = document.getElementById('pdf2html-cheatsheet');
        if (ex) { ex.remove(); return; }
        var bg = document.createElement('div');
        bg.id = 'pdf2html-cheatsheet';
        bg.innerHTML = cheatsheetHTML();
        bg.addEventListener('click', function (ev) { if (ev.target === bg) bg.remove(); });
        document.body.appendChild(bg);
    }

    // Cheatsheet markup — grouped card, two columns:
    //   left = Viewer + Modes + Vimium + sidebar controls
    //   right = command palette reference
    // Each row uses kbd chips (.pdf2html-kbd) for keys; commands get an aligned
    // cmd/alias pair. Keep every command listed here in sync with the COMMANDS
    // table below so the palette + help stay consistent.
    function cheatsheetHTML() {
        function keysHtml(groups) {
            return groups.map(function (group, gi) {
                var chips = group.map(function (k) {
                    return '<span class="pdf2html-kbd">' + escapeHtml(k) + '</span>';
                }).join('');
                return (gi > 0 ? '<span class="sep-or">or</span>' : '') + chips;
            }).join('');
        }
        function kRow(groups, desc) {
            return '<div class="pdf2html-cheatsheet-row">'
                + '<span class="keys">' + keysHtml(groups) + '</span>'
                + '<span class="desc">' + escapeHtml(desc) + '</span>'
                + '</div>';
        }
        function cRow(cmd, alias, desc) {
            var aliasHtml = (alias && alias !== '—')
                ? '<span class="alias">' + escapeHtml(alias) + '</span>' : '';
            return '<div class="pdf2html-cheatsheet-row">'
                + '<span class="cmd">' + escapeHtml(cmd) + aliasHtml + '</span>'
                + '<span class="desc">' + escapeHtml(desc) + '</span>'
                + '</div>';
        }
        return '<div id="pdf2html-cheatsheet-panel">'
            + '<div class="pdf2html-cheatsheet-head">'
                + '<div>'
                    + '<div class="title">Keyboard reference</div>'
                    + '<div class="subtitle">Comet PDF viewer</div>'
                + '</div>'
                + '<span class="close">'
                    + '<span class="pdf2html-kbd sm">?</span> or '
                    + '<span class="pdf2html-kbd sm">Esc</span> to close'
                + '</span>'
            + '</div>'
            + '<div class="pdf2html-cheatsheet-body" tabindex="-1">'
                + '<div class="pdf2html-cheatsheet-section">'
                    + '<h3>Viewer</h3>'
                    + kRow([['s'], ['⌘','.']], 'Toggle sidebar')
                    + kRow([['←'], ['→']], 'Sidebar: Outline / Pages tab (when open)')
                    + kRow([['A']], 'Toggle render-all pages')
                    + kRow([['⌘','⇧','.']], 'Toggle page counter')
                    + '<h3>Modes</h3>'
                    + kRow([[':']], 'Command palette (Tab / ^J / ^K to cycle)')
                    + kRow([['⌘','K']], 'Quick-open another cached doc')
                    + kRow([['/']], 'Find in visible pages (Enter to jump, n/N to cycle)')
                    + kRow([['?']], 'Toggle this cheatsheet')
                    + kRow([['Esc']], 'Close overlay / clear selection')
                    + '<h3>Vimium (external)</h3>'
                    + kRow([['v']], 'Visual mode (extend with j/k/w/b)')
                    + kRow([['m','{a-z}'], ["'", '{a-z}']], 'Set / jump to bookmark')
                    + kRow([['g','g'], ['G']], 'Top / bottom of document')
                    + kRow([['z','i'], ['z','o'], ['z','0']], 'Zoom in / out / reset')
                    + '<h3>Sidebar controls</h3>'
                    + '<div class="pdf2html-cheatsheet-row"><span class="cmd">Render all</span><span class="desc">Force every page visible (inflates find)</span></div>'
                    + '<div class="pdf2html-cheatsheet-row"><span class="cmd">Render ±N</span><span class="desc">Pages kept in DOM around viewport</span></div>'
                    + '<div class="pdf2html-cheatsheet-row"><span class="cmd">Scrolloff N%</span><span class="desc">Auto-scroll band; Pin toggle locks at 50%</span></div>'
                + '</div>'
                + '<div class="pdf2html-cheatsheet-section">'
                    + '<h3>Commands · type : to begin</h3>'
                    + cRow(':42', '—', 'Goto page 42 (bare number)')
                    + cRow(':page N', ':p', 'Goto page N')
                    + cRow(':chapter <name>', '—', 'Jump to chapter by name (Tab to pick)')
                    + cRow(':next', '—', 'Next chapter')
                    + cRow(':prev', '—', 'Prev chapter (or chapter start if mid-chapter)')
                    + cRow(':mark <a-z>', '—', 'Bookmark current page (persists across reloads)')
                    + cRow(':jump <a-z>', '—', 'Jump to bookmark')
                    + cRow(':clear <a-z>', '—', 'Delete a bookmark')
                    + cRow(':open <doc>', ':o', 'Open another cached doc')
                    + cRow(':pin', '—', 'Toggle pin-to-center')
                    + cRow(':scrolloff N', ':so', 'Scrolloff band at N% (e.g. :so 25)')
                    + cRow(':buffer N', ':buf', 'Render ±N pages around viewport')
                    + cRow(':all', '—', 'Toggle render-all pages')
                    + cRow(':yank <kind>', ':y', 'Copy ref / page / chapter / document')
                    + cRow(':counter', ':num', 'Toggle page counter')
                    + cRow(':zoom N', '—', 'Set page-container zoom')
                    + cRow(':help', ':h', 'Open this cheatsheet')
                + '</div>'
            + '</div>'
            + '</div>';
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function registerQuestionHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== '?') return;
            if (isInputTarget(e.target)) return;
            e.preventDefault(); e.stopPropagation();
            toggleCheatsheet();
        }, true);
    }


    // ------------------------------------------------------------------------
    // Command palette — : opens a vim-like ex-bar at the bottom, with
    // nvim wildmenu-style autocomplete: Tab cycles matches, Shift+Tab
    // reverses, commands + arguments are both completable.
    //
    // COMMANDS is the single source of truth for both the dispatcher and
    // the completer. Extend by pushing a new entry here — one line per
    // command, one line in the cheatsheet, done.
    // ------------------------------------------------------------------------
    // Prefix filter used by numeric arg completers. Case-insensitive. Completers
    // own their filtering (empty tail = return everything) so the `chapter` completer
    // can do substring matching without the outer filter fighting it.
    function prefixFilter(list, tail) {
        var lt = String(tail || '').toLowerCase();
        return list.filter(function (a) { return String(a).toLowerCase().indexOf(lt) === 0; });
    }

    // Library — list of all cached docs for `:open`. Daemon returns the
    // full set sorted recency-first; we cache once per page load. Completers
    // are synchronous so if the fetch hasn't resolved yet the user sees an
    // empty list (retry by typing or reopening the palette a beat later).
    var libraryEntries = null;
    function loadLibrary() {
        if (libraryEntries !== null) return;
        fetch('/library', { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .catch(function () { return []; })
            .then(function (d) { libraryEntries = Array.isArray(d) ? d : []; });
    }

    // Relative age label ("3h", "2d", "12m"). Returns '' when we have no
    // visit record yet.
    function recencyLabel(entry) {
        if (!entry || !entry.last_seen) return entry && entry.count ? entry.count + 'x' : '';
        var ageSec = (Date.now() / 1000) - entry.last_seen;
        var ago;
        if (ageSec < 60) ago = 'now';
        else if (ageSec < 3600) ago = Math.round(ageSec / 60) + 'm';
        else if (ageSec < 86400) ago = Math.round(ageSec / 3600) + 'h';
        else ago = Math.round(ageSec / 86400) + 'd';
        return entry.count + 'x · ' + ago;
    }

    function openLibraryEntry(needle) {
        if (!needle || !libraryEntries || !libraryEntries.length) return;
        var n = needle.toLowerCase().trim();
        var exact = null, sub = null;
        for (var i = 0; i < libraryEntries.length; i++) {
            var name = (libraryEntries[i].name || '').toLowerCase();
            if (name === n) { exact = libraryEntries[i]; break; }
            if (!sub && name.indexOf(n) !== -1) sub = libraryEntries[i];
        }
        var pick = exact || sub;
        if (pick && pick.href) location.href = pick.href;
    }

    // Marks — persistent bookmarks keyed by hash + single letter.
    // Vimium's `m`/`'` don't survive reloads; these do. Writes only happen
    // at user intent (`:mark x`), so the storage footprint is tiny.
    function marksKey() {
        var h = entryHash();
        return h ? 'pdf2html-marks:' + h : null;
    }

    function loadMarks() {
        var k = marksKey();
        if (!k) return {};
        try { return JSON.parse(localStorage.getItem(k) || '{}') || {}; }
        catch (_) { return {}; }
    }

    function saveMarks(m) {
        var k = marksKey();
        if (!k) return;
        try { localStorage.setItem(k, JSON.stringify(m)); } catch (_) {}
    }

    // Letter parser — accept first a-z char, normalize to lowercase. Lets
    // the user type `:mark A` or `:mark apple`; only the `a` is used.
    function markLetter(s) {
        if (!s) return null;
        var m = String(s).trim().match(/^([a-zA-Z])/);
        return m ? m[1].toLowerCase() : null;
    }

    function setMark(arg) {
        var letter = markLetter(arg);
        if (!letter) return;
        var marks = loadMarks();
        marks[letter] = {
            page: currentPage,
            label: currentChapterLabel(),
            ts: Date.now(),
        };
        saveMarks(marks);
    }

    function gotoMark(arg) {
        var letter = markLetter(arg);
        if (!letter) return;
        var marks = loadMarks();
        var m = marks[letter];
        if (m && m.page) gotoPage(m.page);
    }

    function clearMark(arg) {
        var letter = markLetter(arg);
        if (!letter) return;
        var marks = loadMarks();
        if (!marks[letter]) return;
        delete marks[letter];
        saveMarks(marks);
    }

    // Chapter-relative navigation. Uses the full outline (incl. subsections)
    // as "section boundaries" — same mental model as vim's `]]` / `[[`.
    // `:prev` has two modes: if we're deeper than NEAR_THRESHOLD pages into
    // the current section, go to the section's start; otherwise go to the
    // previous section. Threshold keeps the UX forgiving when the user is
    // slightly past a heading.
    var CHAPTER_NEAR_THRESHOLD = 2;

    function sortedChapterPages() {
        var chaps = getChapters();
        chaps.sort(function (a, b) { return a.page - b.page; });
        var seen = {};
        return chaps.filter(function (c) {
            if (seen[c.page]) return false;
            seen[c.page] = true;
            return true;
        });
    }

    function gotoNextChapter() {
        var chaps = sortedChapterPages();
        for (var i = 0; i < chaps.length; i++) {
            if (chaps[i].page > currentPage) { gotoPage(chaps[i].page); return; }
        }
    }

    function gotoPrevChapter() {
        var chaps = sortedChapterPages();
        if (!chaps.length) return;
        var idx = -1;
        for (var i = 0; i < chaps.length; i++) {
            if (chaps[i].page <= currentPage) idx = i; else break;
        }
        if (idx === -1) return;
        var offset = currentPage - chaps[idx].page;
        if (offset >= CHAPTER_NEAR_THRESHOLD) gotoPage(chaps[idx].page);
        else if (idx > 0) gotoPage(chaps[idx - 1].page);
    }

    // Pull current outline entries. Re-read on each palette open so that
    // late-mounted outlines and user-navigated state both work.
    function getChapters() {
        var links = document.querySelectorAll('#outline a[href^="#pf"]');
        var out = [];
        for (var i = 0; i < links.length; i++) {
            var a = links[i];
            var m = (a.getAttribute('href') || '').match(/#pf([0-9a-f]+)/i);
            if (!m) continue;
            var label = (a.textContent || '').replace(/\s+/g, ' ').trim();
            if (!label) continue;
            out.push({ label: label, page: parseInt(m[1], 16) });
        }
        return out;
    }

    var COMMANDS = [
        { name: 'page',    aliases: ['p'],    desc: 'goto page N',
          argCompleter: null,
          handler: function (a) { if (a) gotoPage(parseInt(a, 10)); } },
        { name: 'chapter', aliases: [],       desc: 'goto chapter by name',
          argCompleter: function (tail) {
              var lt = String(tail || '').toLowerCase().trim();
              var chaps = getChapters();
              var matched = lt ? chaps.filter(function (c) {
                  return c.label.toLowerCase().indexOf(lt) !== -1;
              }) : chaps;
              return matched.map(function (c) {
                  return {
                      value: 'chapter ' + c.label,
                      display: c.label,
                      alias: 'p. ' + c.page,
                      desc: '',
                      rawDisplay: true,
                  };
              });
          },
          handler: function (a) { gotoChapter(a); } },
        { name: 'mark',    aliases: [],       desc: 'bookmark current page as <letter>',
          argCompleter: function (tail) {
              var marks = loadMarks();
              var lt = markLetter(tail) || '';
              // z → a so the most-reached letter ('a' on a home-row hand)
              // sits at the bottom of the wildmenu, closest to the caret.
              var letters = 'zyxwvutsrqponmlkjihgfedcba'.split('');
              if (lt) letters = [lt];
              return letters.map(function (L) {
                  var m = marks[L];
                  var preview = m
                      ? 'p. ' + m.page + (m.label ? ' · ' + m.label : '')
                      : '—';
                  return {
                      value: 'mark ' + L,
                      display: L + '  ·  ' + preview,
                      alias: m ? 'set' : '',
                      rawDisplay: true,
                  };
              });
          },
          handler: function (a) { setMark(a); } },
        { name: 'jump',    aliases: [],       desc: 'jump to mark <letter>',
          argCompleter: function (tail) {
              var marks = loadMarks();
              var lt = markLetter(tail);
              // Most recently set mark last (bottom = closest to caret).
              var letters = Object.keys(marks).sort(function (a, b) {
                  return (marks[a].ts || 0) - (marks[b].ts || 0);
              });
              if (lt) letters = letters.filter(function (L) { return L === lt; });
              return letters.map(function (L) {
                  var m = marks[L];
                  return {
                      value: 'jump ' + L,
                      display: L + '  ·  p. ' + m.page + (m.label ? ' · ' + m.label : ''),
                      alias: '',
                      rawDisplay: true,
                  };
              });
          },
          handler: function (a) { gotoMark(a); } },
        { name: 'clear',   aliases: [],       desc: 'delete mark <letter>',
          argCompleter: function (tail) {
              var marks = loadMarks();
              var lt = markLetter(tail);
              // Most recently set last — mirrors `:jump` ordering.
              var letters = Object.keys(marks).sort(function (a, b) {
                  return (marks[a].ts || 0) - (marks[b].ts || 0);
              });
              if (lt) letters = letters.filter(function (L) { return L === lt; });
              return letters.map(function (L) {
                  var m = marks[L];
                  return {
                      value: 'clear ' + L,
                      display: L + '  ·  p. ' + m.page + (m.label ? ' · ' + m.label : ''),
                      alias: '',
                      rawDisplay: true,
                  };
              });
          },
          handler: function (a) { clearMark(a); } },
        { name: 'pin',     aliases: [],       desc: 'toggle pin-to-center',
          argCompleter: null,
          handler: function () { toggleCheckboxAndFire('pdf2html-pinned-input'); } },
        { name: 'scrolloff', aliases: ['so'], desc: 'scrolloff N% (0-50)',
          argCompleter: function (tail) { return prefixFilter(['0', '10', '25', '33', '50'], tail); },
          handler: function (a) { if (a !== undefined) setInputValueAndFire('pdf2html-scrolloff-input', parseInt(a, 10)); } },
        { name: 'buffer',  aliases: ['buf'],  desc: 'render ±N pages',
          argCompleter: function (tail) { return prefixFilter(['5', '10', '20', '50'], tail); },
          handler: function (a) { if (a !== undefined) setInputValueAndFire('pdf2html-buffer-input', parseInt(a, 10)); } },
        { name: 'all',     aliases: [],       desc: 'toggle render-all',
          argCompleter: null,
          handler: function () { toggleCheckboxAndFire('pdf2html-all-input'); } },
        { name: 'yank',    aliases: ['y'],    desc: 'copy content (ref/page/chapter/doc)',
          argCompleter: function (tail) {
              // Order: ref → document → chapter → page. Reversed in spirit
              // with the project's "priority at the bottom" convention —
              // `page` (the narrowest, most-frequent selection) sits last,
              // so `:y<space><Enter>` yanks just the current page.
              var options = [
                  { value: 'yank ref',      display: 'ref',      desc: 'chapter · p. N (meta)' },
                  { value: 'yank document', display: 'document', desc: 'full document text' },
                  { value: 'yank chapter',  display: 'chapter',  desc: 'current chapter text' },
                  { value: 'yank page',     display: 'page',     desc: 'current page text' },
              ];
              var lt = String(tail || '').toLowerCase().trim();
              if (!lt) return options;
              return options.filter(function (o) {
                  return o.display.indexOf(lt) === 0;
              });
          },
          handler: function (a) { dispatchYank(a); } },
        { name: 'counter', aliases: ['num'],  desc: 'toggle page counter',
          argCompleter: null,
          handler: function () { if (window.__pdf2htmlTogglePageno) window.__pdf2htmlTogglePageno(); } },
        // `next`/`prev` are ordered AFTER `counter` so that `:n<Enter>` —
        // which prefix-matches both `counter` (via alias `num`) and `next` —
        // auto-selects `next` (state.idx = last match in COMMANDS order).
        // Same logic puts `prev` after `pin` so `:p<Enter>` lands on prev.
        { name: 'next',    aliases: [],       desc: 'next chapter',
          argCompleter: null,
          handler: function () { gotoNextChapter(); } },
        { name: 'prev',    aliases: [],       desc: 'prev chapter (or chapter start)',
          argCompleter: null,
          handler: function () { gotoPrevChapter(); } },
        { name: 'zoom',    aliases: [],       desc: 'set zoom N',
          argCompleter: function (tail) { return prefixFilter(['1.0', '1.2', '1.4', '1.6', '1.8', '2.0', '2.5'], tail); },
          handler: function (a) { if (a !== undefined && window.__pdf2htmlSetZoom) window.__pdf2htmlSetZoom(parseFloat(a)); } },
        { name: 'open',    aliases: ['o'],    desc: 'open another cached doc',
          argCompleter: function (tail) {
              if (!libraryEntries) return [];
              var lt = String(tail || '').toLowerCase().trim();
              var matched = lt
                  ? libraryEntries.filter(function (e) {
                        return (e.name || '').toLowerCase().indexOf(lt) !== -1;
                    })
                  : libraryEntries.slice(0, 30);
              // Daemon sorts recency-first. Reverse so the most recent doc
              // sits at the BOTTOM of the wildmenu — closest to the caret,
              // same priority-near-input convention as :mark/:jump.
              matched = matched.slice().reverse();
              return matched.map(function (e) {
                  return {
                      value: 'open ' + e.name,
                      display: e.name,
                      alias: recencyLabel(e),
                      rawDisplay: true,
                  };
              });
          },
          handler: function (a) { openLibraryEntry(a); } },
        { name: 'help',    aliases: ['h'],    desc: 'show cheatsheet',
          argCompleter: null,
          handler: function () { toggleCheatsheet(); } },
        { name: 'set',     aliases: [],       desc: 'open settings',
          argCompleter: null,
          handler: function () { openSettings(); } },
    ];

    function findCommand(name) {
        var n = name.toLowerCase();
        for (var i = 0; i < COMMANDS.length; i++) {
            if (COMMANDS[i].name === n || COMMANDS[i].aliases.indexOf(n) !== -1) return COMMANDS[i];
        }
        return null;
    }

    function openPalette() {
        var ex = document.getElementById('pdf2html-palette');
        if (ex) { ex.remove(); return; }

        var wrap = document.createElement('div');
        wrap.id = 'pdf2html-palette';

        var completeRow = document.createElement('div');
        completeRow.id = 'pdf2html-palette-complete';
        wrap.appendChild(completeRow);

        var lineRow = document.createElement('div');
        lineRow.id = 'pdf2html-palette-line';
        lineRow.innerHTML =
            '<span id="pdf2html-palette-prompt">:</span>' +
            '<input type="text" id="pdf2html-palette-input" autocomplete="off" ' +
                'spellcheck="false" autocapitalize="off" ' +
                'placeholder="command · Tab to complete · Enter to run">' +
            '<span class="pdf2html-palette-hint">' +
                '<span class="pdf2html-kbd sm">Tab</span>/' +
                '<span class="pdf2html-kbd sm">^J</span>/' +
                '<span class="pdf2html-kbd sm">^K</span> cycle · ' +
                '<span class="pdf2html-kbd sm">Esc</span> close' +
            '</span>';
        wrap.appendChild(lineRow);
        document.body.appendChild(wrap);

        var input = document.getElementById('pdf2html-palette-input');
        var state = { matches: [], idx: -1 };

        function computeMatches() {
            var v = input.value;
            // Empty input → no suggestions. Showing all commands on open
            // feels noisy for a 4h/day UI — palette opens clean, starts
            // suggesting on the first keystroke.
            if (v.length === 0) { state.matches = []; state.idx = -1; return; }
            var firstSpace = v.indexOf(' ');
            if (firstSpace === -1) {
                // Command-name completion — match canonical OR any alias.
                // The wildmenu displays name + alias + desc, so carry all three.
                state.matches = COMMANDS
                    .filter(function (c) {
                        if (c.name.indexOf(v) === 0) return true;
                        return c.aliases.some(function (a) { return a.indexOf(v) === 0; });
                    })
                    .map(function (c) {
                        return {
                            value: c.name,
                            display: c.name,
                            alias: c.aliases[0] || '',
                            desc: c.desc,
                        };
                    });
            } else {
                // Arg completion — completer owns the filter so `chapter` can
                // substring-match while numeric completers prefix-match.
                var head = v.slice(0, firstSpace);
                var tail = v.slice(firstSpace + 1);
                var cmd = findCommand(head);
                if (cmd && cmd.argCompleter) {
                    var results = cmd.argCompleter(tail) || [];
                    state.matches = results.map(function (a) {
                        if (a && typeof a === 'object') {
                            return {
                                value: a.value != null ? a.value : (head + ' ' + (a.display || '')),
                                display: a.display != null ? String(a.display) : String(a.value || ''),
                                alias: a.alias || '',
                                desc: a.desc != null ? a.desc : (cmd.desc || ''),
                                rawDisplay: !!a.rawDisplay,
                            };
                        }
                        return {
                            value: head + ' ' + a,
                            display: String(a),
                            alias: '',
                            desc: cmd.desc || '',
                        };
                    });
                } else {
                    state.matches = [];
                }
            }
            // Auto-highlight the LAST match — visually the row closest to the
            // input (wildmenu stacks above the input, so the bottom of the
            // list is right next to the caret). Enter runs the highlighted
            // match, so a prefix + Enter completes without Tab.
            state.idx = state.matches.length - 1;
        }

        function renderMatches() {
            completeRow.innerHTML = '';
            if (state.matches.length === 0) {
                completeRow.style.display = 'none';
                return;
            }
            completeRow.style.display = '';
            state.matches.forEach(function (m, i) {
                var row = document.createElement('div');
                row.className = 'pdf2html-palette-match' +
                    (i === state.idx ? ' pdf2html-palette-match-active' : '') +
                    (m.rawDisplay ? ' pdf2html-palette-match--wide' : '');

                var nameEl = document.createElement('span');
                nameEl.className = 'name';
                var label = m.display || m.value;
                nameEl.textContent = m.rawDisplay ? label : (':' + label);

                var aliasEl = document.createElement('span');
                aliasEl.className = 'alias';
                aliasEl.textContent = m.alias
                    ? (m.rawDisplay ? m.alias : ':' + m.alias)
                    : '—';

                var descEl = document.createElement('span');
                descEl.className = 'pdf2html-palette-match-desc';
                descEl.textContent = m.desc || '';

                row.appendChild(nameEl);
                row.appendChild(aliasEl);
                row.appendChild(descEl);

                // Mousedown (not click) so we fire before the input loses focus.
                row.addEventListener('mousedown', function (ev) {
                    ev.preventDefault();
                    input.value = m.value;
                    runCommand(input.value);
                    wrap.remove();
                });
                completeRow.appendChild(row);
            });
            var active = completeRow.querySelector('.pdf2html-palette-match-active');
            if (active && active.scrollIntoView) {
                active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
        }

        function cycleMatch(delta) {
            if (state.matches.length === 0) return;
            var n = state.matches.length;
            state.idx = ((state.idx + delta) % n + n) % n;
            // Fill input with the match; don't recompute (we want cycling to
            // stay in the current set of candidates).
            input.value = state.matches[state.idx].value;
            renderMatches();
        }

        input.focus();
        input.addEventListener('input', function () { computeMatches(); renderMatches(); });
        input.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') {
                ev.stopPropagation(); ev.preventDefault(); wrap.remove();
            } else if (ev.key === 'Enter') {
                ev.preventDefault();
                // If a match is highlighted (auto-selected bottom row, or
                // Tab-cycled), run *that* — so typing a prefix + Enter
                // expands to the full command. Fall back to the raw input
                // when there's no match (bare `:42`, no-completion args).
                var run = (state.idx >= 0 && state.matches[state.idx])
                    ? state.matches[state.idx].value
                    : input.value;
                runCommand(run);
                wrap.remove();
            } else if (ev.key === 'Tab') {
                ev.preventDefault(); cycleMatch(ev.shiftKey ? -1 : 1);
            } else if (ev.ctrlKey && !ev.metaKey && !ev.altKey
                       && (ev.key === 'j' || ev.key === 'J')) {
                ev.preventDefault(); cycleMatch(1);
            } else if (ev.ctrlKey && !ev.metaKey && !ev.altKey
                       && (ev.key === 'k' || ev.key === 'K')) {
                ev.preventDefault(); cycleMatch(-1);
            } else if (ev.key === ' ' && input.value.indexOf(' ') === -1
                       && state.matches.length > 0) {
                // Space = "I'm done typing the command, let me give an arg."
                // Expand the highlighted match. If multiple commands prefix-
                // match, prefer one that takes an argument (since user just
                // signaled they want to provide one) — this is what makes
                // `:c<space>` land on `chapter` instead of `counter`.
                var pick = null;
                for (var i = 0; i < state.matches.length; i++) {
                    var c = findCommand(state.matches[i].value);
                    if (c && c.argCompleter) { pick = state.matches[i]; break; }
                }
                if (!pick && state.idx >= 0) pick = state.matches[state.idx];
                if (pick) {
                    ev.preventDefault();
                    input.value = pick.value + ' ';
                    computeMatches(); renderMatches();
                }
            }
        });

        // Show all commands by default on open — nvim user already knows
        // what they want, but the discoverable surface is nice for anyone
        // wandering in.
        computeMatches();
        renderMatches();
    }

    function runCommand(raw) {
        var trimmed = raw.trim();
        if (!trimmed) return;
        // Bare number: `:42` = goto page 42
        if (/^\d+$/.test(trimmed)) { gotoPage(parseInt(trimmed, 10)); return; }
        var firstSpace = trimmed.indexOf(' ');
        var head = firstSpace === -1 ? trimmed : trimmed.slice(0, firstSpace);
        var tail = firstSpace === -1 ? '' : trimmed.slice(firstSpace + 1).trim();
        var cmd = findCommand(head);
        if (cmd) cmd.handler(tail || undefined);
    }

    function gotoPage(n) {
        if (!n || n < 1) return;
        var el = document.getElementById('pf' + n.toString(16));
        if (el) el.scrollIntoView({ block: 'start' });
    }

    // Match by exact (case-insensitive) label first, then substring. Falls back
    // silently if there's no match — palette already showed candidates, so an
    // empty submit is user saying "never mind."
    function gotoChapter(needle) {
        if (!needle) return;
        var chaps = getChapters();
        if (!chaps.length) return;
        var n = needle.toLowerCase().trim();
        var exact = null, sub = null;
        for (var i = 0; i < chaps.length; i++) {
            var lbl = chaps[i].label.toLowerCase();
            if (lbl === n) { exact = chaps[i]; break; }
            if (!sub && lbl.indexOf(n) !== -1) sub = chaps[i];
        }
        var pick = exact || sub;
        if (pick) gotoPage(pick.page);
    }

    function setInputValueAndFire(id, val) {
        if (isNaN(val)) return;
        var i = document.getElementById(id);
        if (!i) return;
        i.value = val;
        i.dispatchEvent(new Event('change'));
    }

    function toggleCheckboxAndFire(id) {
        var cb = document.getElementById(id);
        if (!cb) return;
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event('change'));
    }

    function yankCurrentLocation() {
        var link = document.querySelector('#outline a.pdf2html-active');
        var chapter = link ? link.textContent.trim() : '';
        var pc = document.getElementById('page-container');
        if (!pc) return;
        var pages = document.querySelectorAll('.pf');
        var st = pc.scrollTop, sb = st + pc.clientHeight, bestIdx = 0, bestO = -1;
        for (var i = 0; i < pages.length; i++) {
            var t = pages[i].offsetTop, b = t + pages[i].offsetHeight;
            var o = Math.min(b, sb) - Math.max(t, st);
            if (o > bestO) { bestO = o; bestIdx = i; }
        }
        var text = (chapter ? chapter + ' · ' : '') + 'p. ' + (bestIdx + 1);
        if (navigator.clipboard) navigator.clipboard.writeText(text);
    }

    // Text extraction — yanks actual content for notes / quoting workflow.
    // pdf2htmlEX lays out each visual line as a `.t` div inside `.pc`; joining
    // them with '\n' preserves the per-line structure that plain textContent
    // on `.pc` would collapse. Hidden pages (display:none outside render
    // window) still have their DOM — textContent traverses regardless.
    function pageText(pageNum) {
        var pf = document.getElementById('pf' + pageNum.toString(16));
        if (!pf) return '';
        var pc = pf.querySelector('.pc');
        if (!pc) return '';
        var lines = pc.querySelectorAll('.t');
        if (!lines.length) return (pc.textContent || '').trim();
        var out = [];
        for (var i = 0; i < lines.length; i++) {
            var t = (lines[i].textContent || '').trim();
            if (t) out.push(t);
        }
        return out.join('\n');
    }

    function pageRangeText(startPage, endPageExcl) {
        var out = [];
        for (var p = startPage; p < endPageExcl; p++) {
            var t = pageText(p);
            if (t) out.push(t);
        }
        return out.join('\n\n');
    }

    function totalPages() {
        return document.querySelectorAll('.pf').length;
    }

    // Active chapter → [startPage, endPage). End is the next outline entry
    // with strictly greater page (so subsections within the same page don't
    // terminate the range early), or document end.
    function activeChapterRange() {
        var active = document.querySelector('#outline a.pdf2html-active');
        if (!active) return null;
        var m = (active.getAttribute('href') || '').match(/#pf([0-9a-f]+)/i);
        if (!m) return null;
        var startPage = parseInt(m[1], 16);
        var chaps = sortedChapterPages();
        var endPage = totalPages() + 1;
        for (var i = 0; i < chaps.length; i++) {
            if (chaps[i].page > startPage) { endPage = chaps[i].page; break; }
        }
        return {
            start: startPage,
            end: endPage,
            label: (active.textContent || '').replace(/\s+/g, ' ').trim(),
        };
    }

    function writeClip(text) {
        if (text && navigator.clipboard) navigator.clipboard.writeText(text);
    }

    function yankPage() {
        writeClip(pageText(currentPage));
    }

    function yankChapter() {
        var r = activeChapterRange();
        if (!r) return;
        var body = pageRangeText(r.start, r.end);
        writeClip((r.label ? r.label + '\n\n' : '') + body);
    }

    function yankDocument() {
        var body = pageRangeText(1, totalPages() + 1);
        if (!body) return;
        var title = (document.title || 'Document').trim();
        writeClip(title + '\n\n' + body);
    }

    function dispatchYank(kind) {
        var k = (kind || '').toLowerCase().trim();
        if (k === 'page')                     yankPage();
        else if (k === 'chapter' || k === 'ch') yankChapter();
        else if (k === 'document' || k === 'doc') yankDocument();
        else                                  yankCurrentLocation();  // ref (default)
    }

    function registerPaletteHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== ':') return;
            if (isInputTarget(e.target)) return;
            e.preventDefault(); e.stopPropagation();
            openPalette();
        }, true);
    }

    // ⌘K — jump straight to the library picker. Bypasses isInputTarget so it
    // works from any focus state (Raycast-style quick-open expectation).
    function registerQuickOpenHandler() {
        document.addEventListener('keydown', function (e) {
            if (!e.metaKey || e.ctrlKey || e.altKey) return;
            if (e.key !== 'k' && e.key !== 'K') return;
            e.preventDefault(); e.stopPropagation();
            var existing = document.getElementById('pdf2html-palette');
            if (existing) existing.remove();
            openPalette();
            var input = document.getElementById('pdf2html-palette-input');
            if (input) {
                input.value = 'open ';
                input.dispatchEvent(new Event('input'));
                input.selectionStart = input.selectionEnd = input.value.length;
            }
        }, true);
    }


    // ------------------------------------------------------------------------
    // Render-all quick toggle (A key) — fires change on the sidebar checkbox
    // so all persistence and rendering logic happens via the normal path.
    // ------------------------------------------------------------------------
    function registerRenderAllHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'A') return;
            if (isInputTarget(e.target)) return;
            var cb = document.getElementById('pdf2html-all-input');
            if (!cb) return;
            e.preventDefault();
            cb.checked = !cb.checked;
            cb.dispatchEvent(new Event('change'));
        });
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
    var scrollOffFraction = clampScrollOff(parseFloat(localStorage.getItem('pdf2html-scrolloff') || '0.25'));
    var pinned = localStorage.getItem('pdf2html-pinned') !== '0';

    function clampScrollOff(f) {
        if (isNaN(f) || f < 0) return 0;
        if (f > 0.5) return 0.5;
        return f;
    }

    function applyScrollOffStyle() {
        var pct = (pinned ? 50 : scrollOffFraction * 100) + '%';
        var pc = document.getElementById('page-container');
        if (pc) pc.style.setProperty('--pdf2html-scrolloff', pct);
    }

    function mountCursorPin() {
        applyScrollOffStyle();
        window.__pdf2htmlSetScrollOff = function (f) {
            scrollOffFraction = clampScrollOff(f);
            applyScrollOffStyle();
        };
        window.__pdf2htmlSetPinned = function (on) {
            pinned = !!on;
            applyScrollOffStyle();
        };
    }


    // ------------------------------------------------------------------------
    // Rolling render window — uses IntersectionObserver, so it's zoom-robust
    // (browser manages root geometry itself, no cached page offsets to go stale).
    //
    // Also owns the sidebar config panel (Render all / buffer / scrolloff / pin).
    // ------------------------------------------------------------------------
    function mountRenderWindow() {
        var container = document.getElementById('page-container');
        if (!container) return;
        var pages = Array.prototype.slice.call(container.querySelectorAll('.pf'));
        if (!pages.length) return;

        var buffer = parseInt(localStorage.getItem('pdf2html-buffer') || '10', 10);
        if (isNaN(buffer) || buffer < 0) buffer = 10;
        var renderAll = localStorage.getItem('pdf2html-render-all') === '1';

        var idx = new Map();
        pages.forEach(function (p, i) { idx.set(p, i); });
        var visible = new Set();
        var raf = null;
        var allForced = false;

        function apply() {
            // Render-all: force every page once, then short-circuit — avoids
            // touching the DOM 797 times per observer callback during scroll.
            if (renderAll) {
                if (allForced) return;
                for (var i = 0; i < pages.length; i++) pages[i].classList.add('pdf2html-force');
                allForced = true;
                return;
            }
            allForced = false;

            var from, to;
            if (visible.size === 0) {
                from = 0;
                to = Math.min(pages.length - 1, buffer);
            } else {
                var first = Infinity, last = -1;
                visible.forEach(function (i) {
                    if (i < first) first = i;
                    if (i > last) last = i;
                });
                from = Math.max(0, first - buffer);
                to = Math.min(pages.length - 1, last + buffer);
            }
            for (var j = 0; j < pages.length; j++) {
                var want = j >= from && j <= to;
                if (want !== pages[j].classList.contains('pdf2html-force')) {
                    pages[j].classList.toggle('pdf2html-force', want);
                }
            }
        }

        function sched() {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; apply(); });
        }

        var observer = new IntersectionObserver(function (entries) {
            for (var i = 0; i < entries.length; i++) {
                var n = idx.get(entries[i].target);
                if (n === undefined) continue;
                if (entries[i].isIntersecting) visible.add(n);
                else visible.delete(n);
            }
            sched();
        }, {
            root: container,
            rootMargin: '-20px 0px',  // discount slivers of pages peeking at edges
            threshold: 0,
        });
        pages.forEach(function (p) { observer.observe(p); });

        mountConfigPanel(buffer, renderAll, function (newBuffer) {
            buffer = newBuffer;
            sched();
        }, function (newAll) {
            renderAll = newAll;
            sched();
        });
    }

    // The settings modal and palette commands talk to state through these
    // three hidden inputs — they persist changes and fan out to the live
    // render window / pin system via the `change` event. Keeping them as
    // DOM elements (rather than pure variables) preserves the existing
    // setInputValueAndFire / toggleCheckboxAndFire plumbing the palette
    // already uses.
    function mountConfigPanel(initialBuffer, initialRenderAll, onBuffer, onAll) {
        var host = document.createElement('div');
        host.id = 'pdf2html-hidden-controls';
        host.setAttribute('aria-hidden', 'true');
        host.innerHTML =
            '<input type="checkbox" id="pdf2html-all-input">' +
            '<input type="number" id="pdf2html-buffer-input" min="0" max="2000">' +
            '<input type="number" id="pdf2html-scrolloff-input" min="0" max="50" step="1">' +
            '<input type="checkbox" id="pdf2html-pinned-input">';
        document.body.appendChild(host);

        var bufferInput = document.getElementById('pdf2html-buffer-input');
        bufferInput.value = initialBuffer;
        bufferInput.disabled = initialRenderAll;
        bufferInput.addEventListener('change', function () {
            var n = parseInt(bufferInput.value, 10);
            if (isNaN(n) || n < 0) n = 10;
            localStorage.setItem('pdf2html-buffer', String(n));
            onBuffer(n);
        });

        var allInput = document.getElementById('pdf2html-all-input');
        allInput.checked = initialRenderAll;
        allInput.addEventListener('change', function () {
            var on = allInput.checked;
            localStorage.setItem('pdf2html-render-all', on ? '1' : '0');
            bufferInput.disabled = on;
            onAll(on);
        });

        var scrollOffInput = document.getElementById('pdf2html-scrolloff-input');
        scrollOffInput.value = Math.round(scrollOffFraction * 100);
        scrollOffInput.addEventListener('change', function () {
            var p = parseInt(scrollOffInput.value, 10);
            if (isNaN(p)) p = 25;
            p = Math.max(0, Math.min(50, p));
            scrollOffFraction = p / 100;
            localStorage.setItem('pdf2html-scrolloff', String(scrollOffFraction));
            applyScrollOffStyle();
        });

        var pinnedInput = document.getElementById('pdf2html-pinned-input');
        pinnedInput.checked = pinned;
        pinnedInput.addEventListener('change', function () {
            pinned = pinnedInput.checked;
            localStorage.setItem('pdf2html-pinned', pinned ? '1' : '0');
            applyScrollOffStyle();
        });
    }


    // ------------------------------------------------------------------------
    // Outline active tracker — highlights the outline entry whose target page
    // is the deepest one still ≤ current page. Updates on scroll.
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
            if (active === lastActive) return;
            if (lastActive >= 0) links[lastActive].classList.remove('pdf2html-active');
            if (active >= 0) {
                links[active].classList.add('pdf2html-active');
                try { links[active].scrollIntoView({ block: 'nearest' }); } catch (e) {}
            }
            lastActive = active;
        }

        var raf = null;
        function sched() {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; update(); });
        }
        pc.addEventListener('scroll', sched, { passive: true });
        update();
    }


    // ------------------------------------------------------------------------
    // Page counter — small "N / total" pill at top-center, updates on scroll.
    // Uses elementFromPoint so it's zoom-robust (no cached offsets).
    // ------------------------------------------------------------------------
    function mountPageCounter() {
        var container = document.getElementById('page-container');
        if (!container) return;
        var total = container.querySelectorAll('.pf').length;
        if (!total) return;

        var el = document.createElement('div');
        el.id = 'pdf2html-pageno';
        // Structured spans so CSS can tint each segment (design: chapter in
        // full fg, separators dim, numerals tabular). The chapter segments
        // stay hidden until we have an active outline entry.
        el.innerHTML =
            '<span class="chap" hidden></span>' +
            '<span class="sep" hidden>·</span>' +
            '<span class="sub" hidden></span>' +
            '<span class="sep chap-sep" hidden>·</span>' +
            '<span class="cur" id="pdf2html-pageno-current">1</span>' +
            '<span class="sep">/</span>' +
            '<span class="tot">' + total + '</span>';
        document.body.appendChild(el);

        // Default: hidden. Only show if the user has explicitly enabled it
        // via ⌘⇧. or the `:counter` palette command (which writes '0').
        if (localStorage.getItem('pdf2html-pageno-hidden') !== '0') {
            document.body.classList.add('pageno-hidden');
        }
        var cur     = document.getElementById('pdf2html-pageno-current');
        var chapEl  = el.querySelector('.chap');
        var subEl   = el.querySelector('.sub');
        // The two chapter-flanking separators (before the chapter subtitle,
        // and between chapter-line and the page numerals). The final "/"
        // separator between cur/tot is always visible and isn't tracked here.
        var allSeps = el.querySelectorAll('.sep');
        var chapSeps = [allSeps[0], el.querySelector('.sep.chap-sep')];

        function updateChapter() {
            // Split active outline label into "Ch. N" + sub-title if it fits
            // the pdf2htmlEX common pattern "1.2 Title" or "Chapter 3: Title".
            var active = document.querySelector('#outline a.pdf2html-active');
            var label = active ? (active.textContent || '').trim() : '';
            if (!label) {
                chapEl.hidden = subEl.hidden = true;
                chapSeps.forEach(function (s) { if (s) s.hidden = true; });
                return;
            }
            // Try "N.N.N  Title" or "N  Title" — lead numeric token is the chapter ref.
            var m = label.match(/^\s*((?:\d+)(?:\.\d+)*)\s+(.*)$/);
            var chapPart, subPart;
            if (m) {
                chapPart = 'Ch. ' + m[1];
                subPart  = m[2];
            } else {
                chapPart = '';
                subPart  = label;
            }
            if (chapPart) {
                chapEl.textContent = chapPart;
                chapEl.hidden = false;
            } else {
                chapEl.hidden = true;
            }
            subEl.textContent = subPart;
            subEl.hidden = !subPart;
            // Show "·" between chap and sub if both present; and "·" before
            // the page number iff any chapter text is visible at all.
            if (chapSeps[0]) chapSeps[0].hidden = !(chapPart && subPart);
            if (chapSeps[1]) chapSeps[1].hidden = !(chapPart || subPart);
        }

        var lastPageNum = -1;
        function update() {
            // Always run — consumers like the thumbnails grid listen for
            // pdf2html-page-change regardless of whether the pageno pill
            // itself is visible. Text-content update is still guarded
            // behind the visibility class.
            var r = container.getBoundingClientRect();
            var hit = document.elementFromPoint(
                r.left + container.clientWidth / 2,
                r.top + container.clientHeight / 2
            );
            while (hit && hit !== document.body) {
                if (hit.classList && hit.classList.contains('pf')) {
                    var m = (hit.id || '').match(/pf([0-9a-f]+)/i);
                    if (m) {
                        var n = parseInt(m[1], 16);
                        if (n !== lastPageNum) {
                            lastPageNum = n;
                            if (!document.body.classList.contains('pageno-hidden')) {
                                if (cur.textContent !== String(n)) cur.textContent = String(n);
                            }
                            updateChapter();
                            document.dispatchEvent(new CustomEvent(
                                'pdf2html-page-change', { detail: { page: n } }));
                        }
                    }
                    return;
                }
                hit = hit.parentElement;
            }
        }

        var raf = null;
        container.addEventListener('scroll', function () {
            if (raf) return;
            raf = requestAnimationFrame(function () { raf = null; update(); });
        }, { passive: true });
        setTimeout(update, 80);

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
    // pdf2html-page-change (debounced 400ms); read once at init. Skipped if
    // the URL already carries a `#pfXX` anchor (outline/bookmark deep-link
    // wins). Saved page 1 is treated as "nothing to resume."
    // ------------------------------------------------------------------------
    function mountResumePosition() {
        var hash = entryHash();
        if (!hash) return;
        var key = 'pdf2html-position:' + hash;

        if (!location.hash) {
            var saved = null;
            try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) {}
            if (saved && saved.page > 1) {
                var target = saved.page;
                var tries = 0;
                var restore = function () {
                    var pel = document.getElementById('pf' + target.toString(16));
                    if (pel && pel.offsetHeight > 0) {
                        pel.scrollIntoView({ block: 'start' });
                        return;
                    }
                    if (tries++ < 60) requestAnimationFrame(restore);
                };
                requestAnimationFrame(restore);
            }
        }

        var writeTimer = null;
        document.addEventListener('pdf2html-page-change', function (e) {
            var p = e.detail && e.detail.page;
            if (!p || p < 1) return;
            if (writeTimer) clearTimeout(writeTimer);
            writeTimer = setTimeout(function () {
                try {
                    localStorage.setItem(key, JSON.stringify({ page: p, ts: Date.now() }));
                } catch (_) {}
            }, 400);
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
                title: 'Close sidebar (s)',
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
    var searchState = { hits: [], activeIdx: -1, entered: false };

    // Single capture-phase handler owns every key that matters to search.
    // Listen on WINDOW at capture so we fire before any document- or
    // input-level listener (Vimium and friends hook those and can otherwise
    // swallow Enter / Esc before we see them).
    function mountSearch() {
        window.addEventListener('keydown', function (e) {
            var bar = document.getElementById('pdf2html-search');
            var inSearchInput = e.target && e.target.id === 'pdf2html-search-input';

            // --- Bar open ------------------------------------------------
            // Esc closes the bar regardless of where focus has drifted to;
            // other keys only respond when the caret is actually in the
            // search input so we don't eat the reader's j/k/etc.
            if (bar) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    closeSearch();
                    return;
                }
                if (!inSearchInput) return;
                if (e.key === 'Enter') {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    if (!searchState.hits.length) return;
                    searchState.entered = true;
                    searchState.activeIdx = indexOfClosestHitToViewport();
                    focusActiveHit();
                    dismissSearchBar();
                    return;
                }
                // Typing, arrows, backspace fall through to the input.
                return;
            }

            // --- Bar closed, no persistent hits: `/` opens a new search --
            if (!searchState.entered) {
                if (e.key !== '/') return;
                if (isInputTarget(e.target)) return;
                e.preventDefault();
                e.stopImmediatePropagation();
                openSearch();
                return;
            }

            // --- Bar closed, highlights persist (nvim hlsearch) ----------
            if (isInputTarget(e.target)) return;
            if (e.key === 'Escape') {
                e.preventDefault();
                e.stopImmediatePropagation();
                closeSearch();
                return;
            }
            if (e.key === 'n' || e.key === 'N') {
                e.preventDefault();
                e.stopImmediatePropagation();
                var n = searchState.hits.length;
                if (!n) return;
                var dir = e.key === 'n' ? 1 : -1;
                searchState.activeIdx = (searchState.activeIdx + dir + n) % n;
                focusActiveHit();
                return;
            }
            // `/` reopens for a fresh query — drops the existing state.
            if (e.key === '/') {
                e.preventDefault();
                e.stopImmediatePropagation();
                closeSearch();
                openSearch();
                return;
            }
        }, true);
    }

    function openSearch() {
        var ex = document.getElementById('pdf2html-search');
        // Re-pressing `/` while the bar is open toggles it closed, matching
        // how other overlay keys here behave.
        if (ex) { closeSearch(); return; }

        searchState = { hits: [], activeIdx: -1, entered: false };

        var input = el('input', {
            type: 'text',
            id: 'pdf2html-search-input',
            autocomplete: 'off',
            spellcheck: 'false',
            autocapitalize: 'off',
            placeholder: 'find in visible pages · Enter to jump · n/N next/prev',
        });
        var countEl = el('span', {
            class: 'pdf2html-search-count',
            id: 'pdf2html-search-count',
        });
        var wrap = el('div', { id: 'pdf2html-search' }, [
            el('div', { id: 'pdf2html-search-line' }, [
                el('span', { id: 'pdf2html-search-prompt' }, '/'),
                input,
                countEl,
                el('span', {
                    class: 'pdf2html-search-hint',
                    html:
                        '<span class="pdf2html-kbd sm">Enter</span> jump · ' +
                        '<span class="pdf2html-kbd sm">n</span>/' +
                        '<span class="pdf2html-kbd sm">N</span> nav · ' +
                        '<span class="pdf2html-kbd sm">Esc</span> close',
                }),
            ]),
        ]);
        document.body.appendChild(wrap);
        input.focus();

        // Live-update on typing. Enter / Esc / n / N are all handled by the
        // document capture-phase listener in mountSearch so they fire even
        // if something else (Vimium, extensions) has hooked this input.
        input.addEventListener('input', function () {
            searchState.entered = false;
            searchState.activeIdx = -1;
            updateSearchHits(input.value);
            updateSearchCount();
        });
    }

    function dismissSearchBar() {
        var ex = document.getElementById('pdf2html-search');
        if (ex) ex.remove();
    }

    function closeSearch() {
        // If a hit was activated (Enter was pressed), promote it to a real
        // browser Selection on the way out. The yellow/orange highlights go
        // away, but the word ends up "marked" — so Vimium's V, ⌘C, etc all
        // work on it as though the reader had dragged-selected it manually.
        var promote = (searchState.entered
            && searchState.activeIdx >= 0
            && searchState.hits[searchState.activeIdx]) || null;
        var ex = document.getElementById('pdf2html-search');
        if (ex) ex.remove();
        clearSearchHighlights();
        searchState = { hits: [], activeIdx: -1, entered: false };
        if (promote) {
            try {
                var sel = window.getSelection();
                if (sel) {
                    sel.removeAllRanges();
                    sel.addRange(promote);
                }
            } catch (e) { /* detached / cross-origin range — ignore */ }
        }
    }

    function clearSearchHighlights() {
        try {
            if (window.CSS && CSS.highlights) {
                CSS.highlights.delete('pdf2html-search-hit');
                CSS.highlights.delete('pdf2html-search-active');
            }
        } catch (e) { /* Highlight API unsupported — nothing to clear */ }
    }

    // Scope rule: only pages currently intersecting the viewport AND actually
    // rendered (.pdf2html-force). Collapsed .pc elements contain no selectable
    // text anyway, so skipping them is free.
    function visiblePageFrames() {
        var pc = document.getElementById('page-container');
        if (!pc) return [];
        var pcRect = pc.getBoundingClientRect();
        var out = [];
        var pages = pc.querySelectorAll('.pf');
        for (var i = 0; i < pages.length; i++) {
            var pf = pages[i];
            if (!pf.classList.contains('pdf2html-force')) continue;
            var r = pf.getBoundingClientRect();
            if (r.bottom < pcRect.top || r.top > pcRect.bottom) continue;
            out.push(pf);
        }
        return out;
    }

    function updateSearchHits(raw) {
        clearSearchHighlights();
        searchState.hits = [];

        var q = (raw || '').trim();
        if (!q) return;
        if (!window.CSS || !CSS.highlights || typeof Highlight === 'undefined') {
            // No Highlight API support → bar still works but nothing paints.
            // Acceptable degradation; Comet is Chromium so this shouldn't fire.
            return;
        }

        var qLower = q.toLowerCase();
        var pages = visiblePageFrames();
        var inactive = new Highlight();

        pages.forEach(function (pf) {
            var pc = pf.querySelector('.pc');
            if (!pc) return;
            var walker = document.createTreeWalker(pc, NodeFilter.SHOW_TEXT);
            var node;
            while ((node = walker.nextNode())) {
                var text = node.nodeValue;
                if (!text) continue;
                var lower = text.toLowerCase();
                var cursor = 0, idx;
                while ((idx = lower.indexOf(qLower, cursor)) !== -1) {
                    var r = document.createRange();
                    try {
                        r.setStart(node, idx);
                        r.setEnd(node, idx + qLower.length);
                        searchState.hits.push(r);
                        inactive.add(r);
                    } catch (e) { /* degenerate range, skip */ }
                    cursor = idx + qLower.length;
                }
            }
        });

        if (searchState.hits.length) {
            CSS.highlights.set('pdf2html-search-hit', inactive);
        }
    }

    // Minimal-scroll rule, mirroring the cursor-pin scrolloff semantics:
    //   pinned=true                → cursor must sit at center; any offset
    //                                from 0.5·h is the scroll delta.
    //   pinned=false, margin = scrollOffFraction·h
    //                              → if the match's top lies inside
    //                                [margin, h - margin] the viewport does
    //                                NOT move. Outside that band, scroll the
    //                                minimum amount to pull it just inside
    //                                the nearest edge.
    //
    // Returns the delta to add to pc.scrollTop (0 when no scroll is needed).
    function scrollDeltaForRect(pc, rect) {
        var pcRect = pc.getBoundingClientRect();
        var h = pc.clientHeight;
        var y = rect.top - pcRect.top;
        if (pinned) return y - h * 0.5;
        var margin = h * scrollOffFraction;
        if (y < margin) return y - margin;
        if (y > h - margin) return y - (h - margin);
        return 0;
    }

    // Enter's first pick: the match that needs the smallest scroll. If any
    // matches are already inside the safe band their delta is 0, so the
    // first-in-DOM such match wins — "select what's already on screen"
    // rather than "teleport to the nearest one above center".
    function indexOfClosestHitToViewport() {
        if (!searchState.hits.length) return 0;
        var pc = document.getElementById('page-container');
        if (!pc) return 0;
        var bestIdx = 0, bestDist = Infinity;
        for (var i = 0; i < searchState.hits.length; i++) {
            var d = Math.abs(scrollDeltaForRect(pc, searchState.hits[i].getBoundingClientRect()));
            if (d < bestDist) { bestDist = d; bestIdx = i; }
        }
        return bestIdx;
    }

    function focusActiveHit() {
        var range = searchState.hits[searchState.activeIdx];
        if (!range) { updateSearchCount(); return; }

        // Rebuild the two highlight groups so the active range moves between
        // them. The CSS Highlight API has no per-range style — we partition.
        try {
            if (window.CSS && CSS.highlights) {
                var inactive = new Highlight();
                for (var i = 0; i < searchState.hits.length; i++) {
                    if (i !== searchState.activeIdx) inactive.add(searchState.hits[i]);
                }
                var active = new Highlight();
                active.add(range);
                CSS.highlights.set('pdf2html-search-hit', inactive);
                CSS.highlights.set('pdf2html-search-active', active);
            }
        } catch (e) { /* no highlight API → skip re-paint */ }

        var pc = document.getElementById('page-container');
        if (pc) {
            var delta = scrollDeltaForRect(pc, range.getBoundingClientRect());
            if (Math.abs(delta) >= 1) pc.scrollBy({ top: delta, behavior: 'smooth' });
        }

        updateSearchCount();
    }

    function updateSearchCount() {
        var cEl = document.getElementById('pdf2html-search-count');
        if (!cEl) return;
        var n = searchState.hits.length;
        if (!n) { cEl.textContent = ''; return; }
        // "· / N" while still typing; "K / N" once Enter has activated a hit.
        var cur = searchState.activeIdx >= 0
            ? String(searchState.activeIdx + 1)
            : '·';
        cEl.textContent = cur + ' / ' + n;
    }


    // ------------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------------
    function isInputTarget(t) {
        return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
    }
})();
