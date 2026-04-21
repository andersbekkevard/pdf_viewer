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
        registerPagenoToggleHandler();
        registerRenderAllHandler();
        registerSidebarKeyHandler();
        mountCursorPin();
        mountRenderWindow();
        mountOutlineActiveTracker();
        mountPageCounter();
        mountZoom();
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
        var z = raw !== null ? parseFloat(raw) : 1.6;
        if (!isFinite(z) || z <= 0) z = 1.6;
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
        b.textContent = '☰';
        b.title = 'Toggle sidebar (⌘. or s)';
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
            }
        });
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
            var cs = document.getElementById('pdf2html-cheatsheet');
            if (cs) { cs.remove(); return; }
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

    function cheatsheetHTML() {
        return '<div id="pdf2html-cheatsheet-panel">'
            + '<h3>OUR SHORTCUTS</h3><table>'
            + '<tr><td>s or ⌘.</td><td>Toggle sidebar</td></tr>'
            + '<tr><td>A</td><td>Toggle render-all pages</td></tr>'
            + '<tr><td>⌘⇧.</td><td>Toggle page counter</td></tr>'
            + '<tr><td>:</td><td>Open command palette</td></tr>'
            + '<tr><td>?</td><td>Toggle this help</td></tr>'
            + '<tr><td>Esc</td><td>Close overlay / clear selection</td></tr>'
            + '</table>'
            + '<h3>COMMAND PALETTE (:)</h3><table>'
            + '<tr><td>:42</td><td>Goto page 42</td></tr>'
            + '<tr><td>:pin 30</td><td>Set cursor pin to 30%</td></tr>'
            + '<tr><td>:buffer 20</td><td>Set render buffer to ±20 pages</td></tr>'
            + '<tr><td>:all</td><td>Toggle render-all</td></tr>'
            + '<tr><td>:yank</td><td>Copy "Chapter · p. N" to clipboard</td></tr>'
            + '<tr><td>:counter</td><td>Toggle page counter</td></tr>'
            + '<tr><td>:zoom 1.8</td><td>Set page-container zoom</td></tr>'
            + '<tr><td>:help</td><td>Show this help</td></tr>'
            + '</table>'
            + '<h3>USEFUL VIMIUM</h3><table>'
            + '<tr><td>v</td><td>Visual mode (extend selection with j/k/w/b)</td></tr>'
            + '<tr><td>/  n  N</td><td>Find (only scans rendered pages)</td></tr>'
            + '<tr><td>m{a-z}  &#x27;{a-z}</td><td>Set / jump to bookmark</td></tr>'
            + '<tr><td>gg  G</td><td>Top / bottom of document</td></tr>'
            + '<tr><td>zi  zo  z0</td><td>Zoom in / out / reset</td></tr>'
            + '</table>'
            + '<h3>SIDEBAR CONTROLS</h3><table>'
            + '<tr><td>Render all</td><td>Force every page visible (inflates find)</td></tr>'
            + '<tr><td>Render ±N</td><td>Pages kept in DOM around viewport</td></tr>'
            + '<tr><td>Cursor pin N%</td><td>Where selection focus anchors during scroll</td></tr>'
            + '</table></div>';
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
    // Command palette — : opens a vim-like ex-bar at the bottom.
    // ------------------------------------------------------------------------
    function openPalette() {
        var ex = document.getElementById('pdf2html-palette');
        if (ex) { ex.remove(); return; }
        var wrap = document.createElement('div');
        wrap.id = 'pdf2html-palette';
        wrap.innerHTML =
            '<span id="pdf2html-palette-prompt">:</span>' +
            '<input type="text" id="pdf2html-palette-input" autocomplete="off" spellcheck="false" autocapitalize="off">';
        document.body.appendChild(wrap);
        var input = document.getElementById('pdf2html-palette-input');
        input.focus();
        input.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') {
                ev.stopPropagation(); ev.preventDefault(); wrap.remove();
            } else if (ev.key === 'Enter') {
                ev.preventDefault(); runCommand(input.value); wrap.remove();
            }
        });
    }

    function runCommand(raw) {
        var parts = raw.trim().split(/\s+/);
        if (!parts[0]) return;
        // Bare number: `:42` = goto page 42
        if (/^\d+$/.test(parts[0])) { gotoPage(parseInt(parts[0], 10)); return; }
        var c = parts[0].toLowerCase(), arg = parts[1];
        if ((c === 'p' || c === 'page') && arg)                         gotoPage(parseInt(arg, 10));
        else if (c === 'pin' && arg !== undefined)                       setInputValueAndFire('pdf2html-pin-input', parseInt(arg, 10));
        else if ((c === 'buffer' || c === 'buf') && arg !== undefined)   setInputValueAndFire('pdf2html-buffer-input', parseInt(arg, 10));
        else if (c === 'all')                                            toggleCheckboxAndFire('pdf2html-all-input');
        else if (c === 'yank' || c === 'y')                              yankCurrentLocation();
        else if (c === 'counter' || c === 'num')                         window.__pdf2htmlTogglePageno && window.__pdf2htmlTogglePageno();
        else if (c === 'zoom' && arg !== undefined)                      window.__pdf2htmlSetZoom && window.__pdf2htmlSetZoom(parseFloat(arg));
        else if (c === 'help' || c === 'h')                              toggleCheatsheet();
    }

    function gotoPage(n) {
        if (!n || n < 1) return;
        var el = document.getElementById('pf' + n.toString(16));
        if (el) el.scrollIntoView({ block: 'start' });
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

    function registerPaletteHandler() {
        document.addEventListener('keydown', function (e) {
            if (e.key !== ':') return;
            if (isInputTarget(e.target)) return;
            e.preventDefault(); e.stopPropagation();
            openPalette();
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
    // Cursor pin — keep selection focus at a fixed fraction of the viewport.
    // Each selection change scrolls #page-container by the exact delta so the
    // cursor stays put and the page flows past (Vim's scrolloff=999 feel).
    // ------------------------------------------------------------------------
    var pinFraction = clampPin(parseFloat(localStorage.getItem('pdf2html-pin') || '0.5'));

    function clampPin(f) {
        if (isNaN(f) || f < 0 || f > 1) return 0.5;
        return f;
    }

    function mountCursorPin() {
        var raf = null;
        document.addEventListener('selectionchange', function () {
            if (raf) return;
            raf = requestAnimationFrame(function () {
                raf = null;
                var sel = document.getSelection();
                if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !sel.focusNode) return;
                var pc = document.getElementById('page-container');
                if (!pc) return;
                var r = document.createRange();
                try { r.setStart(sel.focusNode, sel.focusOffset); r.collapse(true); }
                catch (e) { return; }
                var rect = r.getBoundingClientRect();
                var pcRect = pc.getBoundingClientRect();
                var cursorY = rect.top - pcRect.top;
                var desired = pc.clientHeight * pinFraction;
                var delta = cursorY - desired;
                if (Math.abs(delta) >= 1) pc.scrollTop += delta;
            });
        });
        window.__pdf2htmlSetPin = function (f) { pinFraction = f; };
    }


    // ------------------------------------------------------------------------
    // Rolling render window — uses IntersectionObserver, so it's zoom-robust
    // (browser manages root geometry itself, no cached page offsets to go stale).
    //
    // Also owns the sidebar config panel (Render all / buffer / pin %).
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

    function mountConfigPanel(initialBuffer, initialRenderAll, onBuffer, onAll) {
        var sidebar = document.getElementById('sidebar');
        if (!sidebar) return;
        var panel = document.createElement('div');
        panel.id = 'pdf2html-cfg';
        panel.innerHTML =
            '<label><input type="checkbox" id="pdf2html-all-input"> Render all pages</label>' +
            '<label>Render ±<input type="number" id="pdf2html-buffer-input" min="0" max="2000"> pages around viewport</label>' +
            '<label>Cursor pin <input type="number" id="pdf2html-pin-input" min="0" max="100" step="5">% from top</label>';
        sidebar.insertBefore(panel, sidebar.firstChild);

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

        var pinInput = document.getElementById('pdf2html-pin-input');
        pinInput.value = Math.round(pinFraction * 100);
        pinInput.addEventListener('change', function () {
            var p = parseInt(pinInput.value, 10);
            if (isNaN(p)) p = 50;
            p = Math.max(0, Math.min(100, p));
            pinFraction = p / 100;
            localStorage.setItem('pdf2html-pin', String(pinFraction));
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
        el.innerHTML = '<span id="pdf2html-pageno-current">1</span> / ' + total;
        document.body.appendChild(el);

        // Default: hidden. Only show if the user has explicitly enabled it
        // via ⌘⇧. or the `:counter` palette command (which writes '0').
        if (localStorage.getItem('pdf2html-pageno-hidden') !== '0') {
            document.body.classList.add('pageno-hidden');
        }
        var cur = document.getElementById('pdf2html-pageno-current');

        function update() {
            if (document.body.classList.contains('pageno-hidden')) return;
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
                        if (cur.textContent !== String(n)) cur.textContent = String(n);
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
    // Helpers
    // ------------------------------------------------------------------------
    function isInputTarget(t) {
        return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
    }
})();
