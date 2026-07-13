// Text selection, extraction, search, and selection-follow scrolling.
export function createTextInteraction(core) {
    var document = core.document;
    var window = core.window;
    var localStorage = core.storage;
    var navigator = core.navigator;
    var performance = core.performance;
    var requestAnimationFrame = core.requestAnimationFrame;
    var Range = core.Range;
    var NodeFilter = core.NodeFilter;
    var Highlight = core.Highlight;
    var CSS = core.CSS;
    var el = core.el;
    var isInputTarget = core.isInputTarget;
    var isSearchCaseSensitive = core.isSearchCaseSensitive;
    var navigation = core.navigation;
    var documentModel = core.documentModel;
    var isFingerActive = core.isFingerActive;
        function pageElement(pageNum) {
            return documentModel.page(pageNum);
        }

        function pageNumberFromElement(pf) {
            return documentModel.pageNumber(pf);
        }

        function pageElementFromNode(node) {
            return documentModel.pageFromNode(node);
        }

        function pageNumberFromNode(node) {
            return documentModel.pageNumberFromNode(node);
        }

        function pageTextBoundaryPosition(pageNum, towardsStart) {
            return documentModel.pageTextBoundaryPosition(pageNum, towardsStart);
        }

        function selectionPageSpan(sel) {
            if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
            var anchorPage = pageNumberFromNode(sel.anchorNode);
            var focusPage = pageNumberFromNode(sel.focusNode);
            if (!anchorPage || !focusPage) return null;
            return {
                start: Math.min(anchorPage, focusPage),
                end: Math.max(anchorPage, focusPage),
                anchor: anchorPage,
                focus: focusPage,
            };
        }

        function extendSelectionByPage(delta) {
            var sel = window.getSelection();
            var span = selectionPageSpan(sel);
            if (!span || !sel || typeof sel.extend !== 'function') return false;
            var total = totalPages();
            if (!total) return false;
            var targetPage = Math.max(1, Math.min(total, span.focus + delta));
            if (targetPage === span.focus) return true;
            var pos = pageTextBoundaryPosition(targetPage, delta > 0);
            if (!pos) return false;
            document.body.classList.remove('pdf2html-search-entered');
            try {
                sel.extend(pos.node, pos.offset);
                return true;
            } catch (e) {
                return false;
            }
        }

        function chapterRangeForPage(pageNum) {
            if (!pageNum || pageNum < 1) return null;
            var chaps = navigation.sortedChapters();
            if (!chaps.length) return null;
            var idx = -1;
            for (var i = 0; i < chaps.length; i++) {
                if (chaps[i].page <= pageNum) idx = i; else break;
            }
            if (idx === -1) idx = 0;
            var startPage = chaps[idx].page;
            var endPage = totalPages() + 1;
            for (var j = idx + 1; j < chaps.length; j++) {
                if (chaps[j].page > startPage) { endPage = chaps[j].page; break; }
            }
            return {
                start: startPage,
                end: endPage,
                label: chaps[idx].label,
            };
        }

        function selectCurrentChapterFromSelection() {
            var sel = window.getSelection();
            var span = selectionPageSpan(sel);
            if (!span || !sel) return false;
            var chapter = chapterRangeForPage(span.focus);
            if (!chapter) return false;
            var startPos = pageTextBoundaryPosition(chapter.start, true);
            var endPos = pageTextBoundaryPosition(chapter.end - 1, false);
            if (!startPos || !endPos) return false;
            document.body.classList.remove('pdf2html-search-entered');
            try {
                // Chapter-promotion is a selection reshape. Let the browser's own
                // selection scroll behavior carry the viewport, and only suppress
                // our cursor-pin fallback so we don't add a second competing
                // smooth-scroll on top.
                searchSuppressPinUntil = performance.now() + 500;
                var range = document.createRange();
                range.setStart(startPos.node, startPos.offset);
                range.setEnd(endPos.node, endPos.offset);
                sel.removeAllRanges();
                sel.addRange(range);
                return true;
            } catch (e) {
                return false;
            }
        }

        // Like gotoPage, but bypasses #page-container's scroll-padding so the
        // target page's top aligns flush with the viewport top. An 8 px lead-in
        // keeps a sliver of inter-page gap visible (no prev-page content, but a
        // clear "this is the top of a page" cue). Used by e/E page stepping.
        function yankCurrentLocation() {
            var link = document.querySelector('#outline a.pdf2html-active');
            var chapter = link ? link.textContent.trim() : '';
            var pc = document.getElementById('page-container');
            if (!pc) return;
            var pages = documentModel.pages();
            var st = pc.scrollTop, sb = st + pc.clientHeight, bestIdx = 0, bestO = -1;
            for (var i = 0; i < pages.length; i++) {
                var t = pages[i].offsetTop, b = t + pages[i].offsetHeight;
                var o = Math.min(b, sb) - Math.max(t, st);
                if (o > bestO) { bestO = o; bestIdx = i; }
            }
            var text = (chapter ? chapter + ' · ' : '') + 'p. ' + (bestIdx + 1);
            writeClip(text);
        }

        // Text extraction — yanks actual content for notes / quoting workflow.
        // pdf2htmlEX lays out each visual line as a `.t` div inside `.pc`; joining
        // them with '\n' preserves the per-line structure that plain textContent
        // on `.pc` would collapse. Hidden pages (display:none outside render
        // window) still have their DOM — textContent traverses regardless.
        function pageText(pageNum) {
            return documentModel.pageText(pageNum);
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
            return documentModel.totalPages();
        }

        // Active chapter → [startPage, endPage). End is the next outline entry
        // with strictly greater page (so subsections within the same page don't
        // terminate the range early), or document end.
        function activeChapterRange() {
            return chapterRangeForPage(navigation.page());
        }

        function writeClip(text) {
            if (!text) return Promise.resolve(false);
            var value = String(text);
            if (navigator.clipboard && navigator.clipboard.writeText) {
                try {
                    return navigator.clipboard.writeText(value).then(function () {
                        return true;
                    }, function () {
                        return fallbackWriteClip(value);
                    });
                } catch (e) {
                    return Promise.resolve(fallbackWriteClip(value));
                }
            }
            return Promise.resolve(fallbackWriteClip(value));
        }

        function fallbackWriteClip(text) {
            var ta = document.createElement('textarea');
            var active = document.activeElement;
            var selection = window.getSelection ? window.getSelection() : null;
            var ranges = [];
            try {
                if (selection) {
                    for (var i = 0; i < selection.rangeCount; i++) {
                        ranges.push(selection.getRangeAt(i).cloneRange());
                    }
                }
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                ta.style.top = '0';
                document.body.appendChild(ta);
                ta.select();
                ta.setSelectionRange(0, ta.value.length);
                return !!document.execCommand && document.execCommand('copy');
            } catch (e) {
                return false;
            } finally {
                if (ta.parentElement) ta.remove();
                if (selection) {
                    try {
                        selection.removeAllRanges();
                        ranges.forEach(function (r) { selection.addRange(r); });
                    } catch (e) {}
                }
                if (active && active.focus) {
                    try { active.focus({ preventScroll: true }); } catch (e) {}
                }
            }
        }

        function yankPage() {
            writeClip(pageText(navigation.page()));
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

        // ------------------------------------------------------------------------
        // Finger mode — tmux-fingers-style token picker for the visible viewport.
        //
        // V1 deliberately stays local: it scans only visible rendered page frames
        // and only structured tokens. Hints use keys that already pass through
        // Vimium on localhost (e/s/q/c/h/l/n), so the mode works without extending
        // Vimium's exclusion list. The pdf2htmlEX text DOM remains untouched:
        // targets are painted through CSS Custom Highlights, while hint labels live
        // in a fixed overlay layer backed by original browser Ranges for copy.
        // ------------------------------------------------------------------------
        // (Finger-mode implementation lives in ./overlay-finger.js — created via
        // createFinger(core) in init(). openFingerMode/closeFingerMode/isActive
        // come back on the `finger` object below.)

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

        // The CSS path covers everything the browser scrolls natively (mouse drag,
        // keyboard shift+arrow, click-to-place, scrollIntoView calls). Vimium's
        // caret/visual mode moves the selection via Selection.modify() — a
        // programmatic API that Chrome does NOT auto-scroll for. This handler
        // fills that gap: read the focus range's *visual* rect (which correctly
        // reflects pdf2htmlEX's transformed text; Element.scrollIntoView uses
        // layout rects and lands in the wrong place here), compute the delta
        // against the same band the CSS enforces, and smooth-scroll.
        //
        // Suppressed during a mouse drag so Chrome's native drag-past-edge
        // auto-scroll (the mouse behavior that already "feels right") is left
        // alone.
        function mountCursorPin() {
            applyScrollOffStyle();
            var raf = null;
            var dragging = false;
            var lastScrollTs = 0;
            // Smooth scroll animates ~300ms. A second scroll inside that window
            // cancels the in-flight animation and restarts — so held `j` in
            // Vimium, which fires selection updates every ~30ms, never lets the
            // animation finish and the caret outruns the viewport (worst at
            // page boundaries where delta includes the inter-page margin).
            // Fall back to instant for rapid-fire; keep smooth for isolated
            // moves where the animation has time to complete.
            var RAPID_WINDOW_MS = 180;

            function beginPointerSelection() {
                dragging = true;
                document.body.classList.add('pdf2html-pointer-selecting');
            }
            function endPointerSelection() {
                dragging = false;
                document.body.classList.remove('pdf2html-pointer-selecting');
            }
            document.addEventListener('mousedown', beginPointerSelection);
            document.addEventListener('mouseup', endPointerSelection);
            window.addEventListener('blur', endPointerSelection);

            document.addEventListener('selectionchange', function () {
                if (dragging || raf) return;
                if (performance.now() < searchSuppressPinUntil) return;
                raf = requestAnimationFrame(function () {
                    raf = null;
                    var sel = document.getSelection();
                    if (!sel || sel.rangeCount === 0 || !sel.focusNode) return;
                    var pc = document.getElementById('page-container');
                    if (!pc) return;
                    var r = document.createRange();
                    try { r.setStart(sel.focusNode, sel.focusOffset); r.collapse(true); }
                    catch (e) { return; }
                    var rect = r.getBoundingClientRect();
                    // Collapsed ranges sometimes return (0,0,0,0) at DOM edges —
                    // no reliable caret position, bail.
                    if (rect.top === 0 && rect.bottom === 0 && rect.left === 0) return;

                    var h = pc.clientHeight;
                    var y = rect.top - pc.getBoundingClientRect().top;
                    var frac = pinned ? 0.5 : scrollOffFraction;
                    var margin = h * frac;
                    var delta = 0;
                    if (pinned)              delta = y - h * 0.5;
                    else if (y < margin)     delta = y - margin;
                    else if (y > h - margin) delta = y - (h - margin);
                    if (Math.abs(delta) >= 1) {
                        var now = performance.now();
                        var behavior = (now - lastScrollTs < RAPID_WINDOW_MS) ? 'auto' : 'smooth';
                        pc.scrollBy({ top: delta, behavior: behavior });
                        lastScrollTs = now;
                    }
                });
            });

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
        // Render window — now CSS-only via `content-visibility: auto` on `.pf`
        // (see overlay.css). The browser handles paint-skipping for offscreen
        // pages; the entire DOM stays in the layout tree so native Cmd-F can
        // index it. This mount is left as the install point for the hidden
        // settings inputs (scrolloff, pin) that the palette and settings modal
        // dispatch `change` events on.
        //
        // Historically this also toggled `.pdf2html-force` per page to gate
        // `.pc { display: none }`; that whole mechanism was deleted with
        // ADR 0009 because it broke native browser find.
        // ------------------------------------------------------------------------
        function mountRenderWindow() {
            var host = document.createElement('div');
            host.id = 'pdf2html-hidden-controls';
            host.setAttribute('aria-hidden', 'true');
            host.innerHTML =
                '<input type="number" id="pdf2html-scrolloff-input" min="0" max="50" step="1">' +
                '<input type="checkbox" id="pdf2html-pinned-input">';
            document.body.appendChild(host);

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
        var searchState = { hits: [], activeIdx: -1, entered: false };
        // When Enter promotes a hit to a browser Selection, the cursor-pin handler
        // (mountCursorPin) would see the resulting selectionchange and issue its
        // own competing scroll. Suppress it until our own smooth-scroll settles.
        var searchSuppressPinUntil = 0;

        // Single capture-phase handler owns every key that matters to search.
        // Listen on WINDOW at capture so we fire before any document- or
        // input-level listener (Vimium and friends hook those and can otherwise
        // swallow Enter / Esc before we see them).
        function mountSearch() {
            window.addEventListener('keydown', function (e) {
                // Finger mode owns its alphabet while active. Search is also a
                // window-capture listener registered earlier, so it must yield
                // explicitly for overlapping keys like `s`.
                if (isFingerActive()) return;

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

                // --- Bar closed, no persistent hits: `/` or `s` opens search --
                if (!searchState.entered) {
                    var opener = e.key === '/' || (e.key === 's' && !e.metaKey && !e.ctrlKey && !e.altKey);
                    if (!opener) return;
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
                // `/` or `s` reopens for a fresh query — drops the existing state.
                if (e.key === '/' || (e.key === 's' && !e.metaKey && !e.ctrlKey && !e.altKey)) {
                    e.preventDefault();
                    e.stopImmediatePropagation();
                    closeSearch();
                    openSearch();
                    return;
                }
                // Any other key: fall through. We keep nvim-style hlsearch —
                // highlights + n/N persist until explicit Esc. The
                // ::selection-hiding body class is dropped separately by the
                // selectionchange listener below, the moment the Selection
                // diverges from the active hit (Vimium V extending, mouse
                // drag, anything).
            }, true);

            // ::selection is transparent while body.pdf2html-search-entered is
            // set so the orange active-hit paint shows through. As soon as the
            // Selection is modified by anything that isn't our own n/N (Vimium
            // V extending via Selection.modify, click, mouse drag, …), flip
            // ::selection back to the default blue so the user can actually see
            // what's being selected. Range identity, not event source, is the
            // cleanest signal.
            document.addEventListener('selectionchange', function () {
                if (!document.body.classList.contains('pdf2html-search-entered')) return;
                var sel = window.getSelection();
                if (!sel || !sel.rangeCount) {
                    document.body.classList.remove('pdf2html-search-entered');
                    return;
                }
                var activeR = searchState.hits[searchState.activeIdx];
                if (!activeR) {
                    document.body.classList.remove('pdf2html-search-entered');
                    return;
                }
                var selR = sel.getRangeAt(0);
                try {
                    if (selR.compareBoundaryPoints(Range.START_TO_START, activeR) !== 0
                     || selR.compareBoundaryPoints(Range.END_TO_END, activeR) !== 0) {
                        document.body.classList.remove('pdf2html-search-entered');
                    }
                } catch (e) {
                    // Detached / cross-document range — drop the class to be safe.
                    document.body.classList.remove('pdf2html-search-entered');
                }
            });
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
            // Selection was already promoted on Enter by focusActiveHit, so Vimium
            // V / ⌘C already work. Esc just tears down the visual affordances and
            // leaves whatever Selection is current alone. Drop the body class so
            // the ::selection color reverts from orange back to the default blue.
            var ex = document.getElementById('pdf2html-search');
            if (ex) ex.remove();
            clearSearchHighlights();
            document.body.classList.remove('pdf2html-search-entered');
            searchState = { hits: [], activeIdx: -1, entered: false };
        }

        function clearSearchHighlights() {
            try {
                if (window.CSS && CSS.highlights) {
                    CSS.highlights.delete('pdf2html-search-hit');
                    CSS.highlights.delete('pdf2html-search-active');
                }
            } catch (e) { /* Highlight API unsupported — nothing to clear */ }
        }

        // Scope rule: only pages currently intersecting the viewport. Under
        // content-visibility: auto, off-viewport pages still have their text in the
        // DOM (so native Cmd-F sees them), but the `/` overlay deliberately scopes
        // to what the user is actually looking at — the rect check is the contract.
        function visiblePageFrames() {
            return documentModel.visiblePages();
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

            var cs = isSearchCaseSensitive();
            var needle = cs ? q : q.toLowerCase();
            var pages = visiblePageFrames();
            var inactive = new Highlight();

            // Per-line flat-text search. pdf2htmlEX splits words across kerning
            // spans (`sho<span class="_ _7"></span>ws`) and wraps every inter-word
            // space in a spacer span — so a line's text is spread across many
            // sibling text nodes. A naive per-text-node `indexOf` would miss any
            // query that crosses a span (multi-word, or even one word like
            // "shows" cut by a kerning gap). We flatten each `.t` into one string
            // with an offset map back to (textNode, localOffset), search the flat
            // string, and rebuild Ranges that may span several text nodes per hit.
            // Scope is still per `.t` (visual line) — Cmd-F's built-in find has
            // the same line-scoped contract, and crossing line breaks would match
            // nothing the user can see.
            pages.forEach(function (pf) {
                var pc = documentModel.pageContent(pf);
                if (!pc) return;
                var lines = pc.querySelectorAll('.t');
                for (var li = 0; li < lines.length; li++) {
                    collectHitsInLine(lines[li], needle, cs, inactive);
                }
            });

            if (searchState.hits.length) {
                CSS.highlights.set('pdf2html-search-hit', inactive);
            }
        }

        // Flatten one `.t` into a single string + (node, start, end) map and
        // push a Range for each occurrence of `needle`. Splits the matched
        // [start, end) across the contributing text nodes — the resulting Range
        // is multi-node when a hit crosses a kerning/spacer span, single-node
        // when it doesn't.
        function collectHitsInLine(line, needle, cs, highlight) {
            var walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
            var flat = '';
            var map = [];
            var node;
            while ((node = walker.nextNode())) {
                var t = node.nodeValue || '';
                if (!t.length) continue;
                map.push({ node: node, start: flat.length, end: flat.length + t.length });
                flat += t;
            }
            if (!flat) return;
            var hay = cs ? flat : flat.toLowerCase();
            var cursor = 0, idx;
            while ((idx = hay.indexOf(needle, cursor)) !== -1) {
                var r = rangeFromFlatOffsets(map, idx, idx + needle.length);
                if (r) {
                    searchState.hits.push(r);
                    highlight.add(r);
                }
                cursor = idx + needle.length;
            }
        }

        // Translate [flatStart, flatEnd) back into a DOM Range over the original
        // text nodes. Linear over `map`; fine for one line.
        function rangeFromFlatOffsets(map, flatStart, flatEnd) {
            var startEntry = null, endEntry = null;
            for (var i = 0; i < map.length; i++) {
                var m = map[i];
                if (!startEntry && flatStart >= m.start && flatStart < m.end) startEntry = m;
                if (flatEnd > m.start && flatEnd <= m.end) { endEntry = m; break; }
            }
            if (!startEntry || !endEntry) return null;
            var r = document.createRange();
            try {
                r.setStart(startEntry.node, flatStart - startEntry.start);
                r.setEnd(endEntry.node, flatEnd - endEntry.start);
                return r;
            } catch (e) {
                return null;
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
            // active.priority > 0 keeps the orange paint on top of the browser's
            // built-in ::selection paint that we set below (custom-highlight
            // priority can outrank ::selection in Chromium).
            try {
                if (window.CSS && CSS.highlights) {
                    var inactive = new Highlight();
                    for (var i = 0; i < searchState.hits.length; i++) {
                        if (i !== searchState.activeIdx) inactive.add(searchState.hits[i]);
                    }
                    var active = new Highlight();
                    active.add(range);
                    active.priority = 10;
                    CSS.highlights.set('pdf2html-search-hit', inactive);
                    CSS.highlights.set('pdf2html-search-active', active);
                }
            } catch (e) { /* no highlight API → skip re-paint */ }

            var pc = document.getElementById('page-container');
            if (pc) {
                var delta = scrollDeltaForRect(pc, range.getBoundingClientRect());
                if (Math.abs(delta) >= 1) pc.scrollBy({ top: delta, behavior: 'smooth' });
            }

            // Promote the active range to a real browser Selection so Vimium's V
            // and ⌘C work immediately after Enter — no Esc-to-promote detour.
            // Suppress the cursor-pin selectionchange reaction briefly so its
            // scroll doesn't fight our own smooth-scroll above. The body class
            // recolors ::selection to orange so the native selection paint
            // doesn't cover our custom active highlight (Chromium paints
            // built-in pseudos on top of custom highlights regardless of
            // Highlight.priority).
            searchSuppressPinUntil = performance.now() + 500;
            try {
                var sel = window.getSelection();
                if (sel) {
                    sel.removeAllRanges();
                    sel.addRange(range);
                }
                document.body.classList.add('pdf2html-search-entered');
            } catch (e) { /* detached / cross-origin range — ignore */ }

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

        function refreshSearch(raw) {
            updateSearchHits(raw);
            updateSearchCount();
        }


    return {
        init: function () { mountRenderWindow(); mountCursorPin(); mountSearch(); },
        closeSearch: closeSearch,
        refreshSearch: refreshSearch,
        visiblePageFrames: visiblePageFrames,
        writeClip: writeClip,
        dispatchYank: dispatchYank,
        extendSelectionByPage: extendSelectionByPage,
        selectCurrentChapterFromSelection: selectCurrentChapterFromSelection,
        pageElement: pageElement,
        pageNumberFromNode: pageNumberFromNode,
        selectionPageSpan: selectionPageSpan,
        pageTextBoundaryPosition: pageTextBoundaryPosition,
        suppressPin: function () { return searchSuppressPinUntil; },
    };
}
