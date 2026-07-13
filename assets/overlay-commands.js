// Palette, finder, cheatsheet, and command routing.
export function createCommandSurface(core) {
    var document = core.document;
    var window = core.window;
    var localStorage = core.storage;
    var navigation = core.navigation;
    var textInteraction = core.textInteraction;
    var library = core.library;
    var finger = core.finger;
    var isInputTarget = core.isInputTarget;
    var openSettings = core.openSettings;
    var isSearchCaseSensitive = core.isSearchCaseSensitive;
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
                        + kRow([['⌘','.'], ['⌘','B']], 'Toggle sidebar')
                        + kRow([['Ctrl','J'], ['Ctrl','K'], ['↓'], ['↑']], 'Sidebar: move Outline / Pages selector')
                        + kRow([['←','h'], ['→','l']], 'Sidebar: Outline / Pages tab (when open)')
                        + kRow([['A']], 'Toggle render-all pages')
                        + kRow([['e'], ['q'], ['E']], 'Next / prev page; active text selection extends pagewise instead')
                        + kRow([['c'], ['C']], 'Next / prev chapter; active browser selection + c selects full chapter')
                        + kRow([['⌘','⇧','.']], 'Toggle page counter')
                        + '<h3>Modes</h3>'
                        + kRow([[':']], 'Command palette (Tab / ^J / ^K to cycle)')
                        + kRow([['⌘','K']], 'Quick-open another cached doc')
                        + kRow([['⌘',',']], 'Open settings')
                        + kRow([['Ctrl','f']], 'Finger visible tokens; hint copies token')
                        + kRow([['/'], ['s']], 'Find in visible pages (Enter to jump, n/N to cycle)')
                        + kRow([[':','f']], 'Finger visible tokens; hint copies token')
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
                        + cRow(':rename <name>', ':rn', 'Rename this PDF (Tab fills current name)')
                        + cRow(':path', '—', 'Copy this PDF\'s source path / URL to clipboard')
                        + cRow(':disable', ':native', 'Open native PDF and disable viewer for this file')
                        + cRow(':pin', '—', 'Toggle pin-to-center')
                        + cRow(':scrolloff N', ':so', 'Scrolloff band at N% (e.g. :so 25)')
                        + cRow(':buffer N', ':buf', 'Render ±N pages around viewport')
                        + cRow(':all', '—', 'Toggle render-all pages')
                        + cRow(':yank <kind>', ':y', 'Copy ref / page / chapter / document')
                        + cRow(':finger', ':f', 'Hint visible URL / DOI / ISBN / ID tokens')
                        + cRow(':counter', ':num', 'Toggle page counter')
                        + cRow(':zoom N | auto', '—', 'Set page-container zoom (auto = fit-to-width)')
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

        var COMMANDS = [
            { name: 'page',    aliases: ['p'],    desc: 'goto page N',
              requiresArg: true,
              argCompleter: null,
              handler: function (a) { if (a) navigation.gotoPage(parseInt(a, 10)); } },
            { name: 'chapter', aliases: [],       desc: 'goto chapter by name',
              argCompleter: function (tail) {
                  var lt = String(tail || '').toLowerCase().trim();
                  var chaps = navigation.chapters();
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
              handler: function (a) { navigation.gotoChapter(a); } },
            { name: 'mark',    aliases: [],       desc: 'bookmark current page as <letter>',
              argCompleter: function (tail) {
                  var marks = navigation.marks();
                  var lt = navigation.markLetter(tail) || '';
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
              handler: function (a) { navigation.setMark(a); } },
            { name: 'jump',    aliases: [],       desc: 'jump to mark <letter>',
              argCompleter: function (tail) {
                  var marks = navigation.marks();
                  var lt = navigation.markLetter(tail);
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
              handler: function (a) { navigation.gotoMark(a); } },
            { name: 'clear',   aliases: [],       desc: 'delete mark <letter>',
              argCompleter: function (tail) {
                  var marks = navigation.marks();
                  var lt = navigation.markLetter(tail);
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
              handler: function (a) { navigation.clearMark(a); } },
            { name: 'pin',     aliases: [],
              desc: function () {
                  return 'turn pin-to-center ' + (localStorage.getItem('pdf2html-pinned') !== '0' ? 'OFF' : 'ON');
              },
              argCompleter: null,
              handler: function () { toggleCheckboxAndFire('pdf2html-pinned-input'); } },
            { name: 'scrolloff', aliases: ['so'], desc: 'scrolloff N% (0-50)',
              argCompleter: function (tail) { return prefixFilter(['0', '10', '25', '33', '50'], tail); },
              handler: function (a) { if (a !== undefined) setInputValueAndFire('pdf2html-scrolloff-input', parseInt(a, 10)); } },
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
              handler: function (a) { textInteraction.dispatchYank(a); } },
            { name: 'finger',  aliases: ['f'],    desc: 'hint visible URL/DOI/ISBN/ID tokens',
              argCompleter: null,
              handler: function () { finger.openFingerMode(); } },
            { name: 'counter', aliases: ['num'],
              desc: function () {
                  return (document.body.classList.contains('pageno-hidden') ? 'show' : 'hide') + ' page counter';
              },
              argCompleter: null,
              handler: function () { if (window.__pdf2htmlTogglePageno) window.__pdf2htmlTogglePageno(); } },
            { name: 'case',    aliases: [],
              desc: function () {
                  return 'turn case-sensitive search ' + (isSearchCaseSensitive() ? 'OFF' : 'ON');
              },
              argCompleter: null,
              handler: function () {
                  if (window.__pdf2htmlSetSearchCase) window.__pdf2htmlSetSearchCase(!isSearchCaseSensitive());
              } },
            // `next`/`prev` are ordered AFTER `counter` so that `:n<Enter>` —
            // which prefix-matches both `counter` (via alias `num`) and `next` —
            // auto-selects `next` (state.idx = last match in COMMANDS order).
            // Same logic puts `prev` after `pin` so `:p<Enter>` lands on prev.
            { name: 'next',    aliases: [],       desc: 'next chapter',
              argCompleter: null,
              handler: function () { navigation.gotoChapterBy(1); } },
            { name: 'prev',    aliases: [],       desc: 'prev chapter (or chapter start)',
              argCompleter: null,
              handler: function () { navigation.gotoChapterBy(-1); } },
            { name: 'zoom',    aliases: [],       desc: 'set zoom N (or auto)',
              argCompleter: function (tail) { return prefixFilter(['auto', '1.0', '1.2', '1.4', '1.6', '1.8', '2.0', '2.5'], tail); },
              handler: function (a) {
                  if (a === undefined || !window.__pdf2htmlSetZoom) return;
                  window.__pdf2htmlSetZoom(a === 'auto' ? 'auto' : parseFloat(a));
              } },
            { name: 'open',    aliases: ['o'],    desc: 'open another cached doc',
              argCompleter: function (tail) {
                  var matched = library.complete(tail);
                  return matched.map(function (e) {
                      return {
                          value: 'open ' + e.name,
                          display: e.name,
                          alias: library.recencyLabel(e),
                          rawDisplay: true,
                      };
                  });
              },
              handler: function (a) { library.open(a); } },
            { name: 'help',    aliases: ['h'],    desc: 'show cheatsheet',
              argCompleter: null,
              handler: function () { toggleCheatsheet(); } },
            { name: 'set',     aliases: [],       desc: 'open settings',
              argCompleter: null,
              handler: function () { openSettings(); } },
            { name: 'path',    aliases: [],
              desc: function () {
                  var ref = library.currentSourceRef();
                  return ref ? library.truncateMiddle(ref, 60) : 'copy source path / URL';
              },
              argCompleter: null,
              handler: function () {
                  var ref = library.currentSourceRef();
                  if (ref) textInteraction.writeClip(ref);
              } },
            { name: 'disable', aliases: ['native'], desc: 'open native PDF and disable viewer for this file',
              argCompleter: null,
              handler: function () { library.disableCurrent(); } },
            { name: 'rename',  aliases: ['rn'],
              desc: function () {
                  var current = library.currentName();
                  return current ? 'rename "' + current + '"' : 'rename this PDF';
              },
              argCompleter: function (tail) {
                  var current = library.currentName();
                  if (!current) return [];
                  // Only seed the current name when the arg is empty —
                  // `:rename<Tab>` autofills, then user edits freely. Showing
                  // the suggestion while user types the new name would create
                  // cycling weirdness on the single-row wildmenu.
                  if (String(tail || '').length > 0) return [];
                  return [{
                      value: 'rename ' + current,
                      display: current,
                      alias: '(current)',
                      desc: 'Tab to fill · edit · Enter to rename',
                      rawDisplay: true,
                  }];
              },
              handler: function (a) { library.renameCurrent(a); } },
            // Destructive, but recoverable (just re-convert). The `confirm` arg is
            // mandatory so `:d<Enter>` expands to `delete ` instead of nuking the
            // cache entry on a stray keystroke.
            { name: 'delete',  aliases: [],       desc: 'wipe this PDF from cache + go to source',
              argCompleter: function (tail) {
                  var lt = String(tail || '').toLowerCase().trim();
                  var opts = [{ value: 'delete confirm', display: 'confirm', desc: 'wipe cache entry, redirect to original' }];
                  if (!lt) return opts;
                  return opts.filter(function (o) { return o.display.indexOf(lt) === 0; });
              },
              handler: function (a) {
                  if ((a || '').toLowerCase().trim() === 'confirm') library.deleteCurrent();
              } },
        ];

        function findCommand(name) {
            if (name == null) return null;
            var n = String(name).toLowerCase();
            for (var i = 0; i < COMMANDS.length; i++) {
                if (COMMANDS[i].name === n || COMMANDS[i].aliases.indexOf(n) !== -1) return COMMANDS[i];
            }
            return null;
        }

        function commandTakesArg(cmd) {
            return !!(cmd && (cmd.argCompleter || cmd.requiresArg));
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
                    var commandNeedle = v.toLowerCase();
                    state.matches = COMMANDS
                        .filter(function (c) {
                            if (c.name.indexOf(commandNeedle) === 0) return true;
                            return c.aliases.some(function (a) { return a.indexOf(commandNeedle) === 0; });
                        })
                        .map(function (c) {
                            return {
                                value: c.name,
                                display: c.name,
                                alias: c.aliases[0] || '',
                                desc: typeof c.desc === 'function' ? c.desc() : c.desc,
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
                        acceptMatchOrRun(m);
                    });
                    completeRow.appendChild(row);
                });
                var active = completeRow.querySelector('.pdf2html-palette-match-active');
                if (active && active.scrollIntoView) {
                    active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                }
            }

            function expandCommandMatch(match) {
                if (!match || input.value.indexOf(' ') !== -1) return false;
                var cmd = findCommand(match.value);
                if (!commandTakesArg(cmd)) return false;
                input.value = cmd.name + ' ';
                computeMatches();
                // If the arg completer offers exactly one suggestion, fill it
                // directly so e.g. `:re<Tab>` lands at `:rename <current>` in
                // one keystroke instead of two. Multi-suggestion completers
                // (chapter, open, mark) still expand to `:cmd ` and let the
                // user cycle — they have nothing single to commit to.
                if (state.matches.length === 1 && state.matches[0].value) {
                    input.value = state.matches[0].value;
                }
                renderMatches();
                return true;
            }

            function acceptMatchOrRun(match) {
                if (expandCommandMatch(match)) return;
                input.value = match && match.value != null ? match.value : input.value;
                runCommand(input.value);
                wrap.remove();
            }

            function cycleMatch(delta) {
                if (state.matches.length === 0) return;
                // Tab on an unambiguous command completion (single match, no
                // space yet) expands straight into arg mode — skips the "Tab
                // then Space" two-step once there's only one command it could
                // be. Multi-match cycling still uses Space/Enter to commit.
                if (state.matches.length === 1 && input.value.indexOf(' ') === -1) {
                    if (expandCommandMatch(state.matches[0])) return;
                }
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
                    var match = state.idx >= 0 ? state.matches[state.idx] : null;
                    acceptMatchOrRun(match);
                } else if (ev.key === 'Tab') {
                    ev.preventDefault(); cycleMatch(ev.shiftKey ? -1 : 1);
                } else if (ev.ctrlKey && !ev.metaKey && !ev.altKey
                           && (ev.key === 'j' || ev.key === 'J')) {
                    ev.preventDefault(); cycleMatch(1);
                } else if (ev.ctrlKey && !ev.metaKey && !ev.altKey
                           && (ev.key === 'k' || ev.key === 'K')) {
                    ev.preventDefault(); cycleMatch(-1);
                } else if (ev.key === 'ArrowDown'
                           && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
                    ev.preventDefault(); cycleMatch(1);
                } else if (ev.key === 'ArrowUp'
                           && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
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
            if (/^\d+$/.test(trimmed)) { navigation.gotoPage(parseInt(trimmed, 10)); return; }
            var firstSpace = trimmed.indexOf(' ');
            var head = firstSpace === -1 ? trimmed : trimmed.slice(0, firstSpace);
            var tail = firstSpace === -1 ? '' : trimmed.slice(firstSpace + 1).trim();
            var cmd = findCommand(head);
            if (cmd) cmd.handler(tail || undefined);
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

        function registerPaletteHandler() {
            document.addEventListener('keydown', function (e) {
                if (e.key !== ':') return;
                if (isInputTarget(e.target)) return;
                e.preventDefault(); e.stopPropagation();
                openPalette();
            }, true);
        }

        function registerFingerShortcutHandler() {
            window.addEventListener('keydown', function (e) {
                if (!e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return;
                if (String(e.key || '').toLowerCase() !== 'f') return;
                if (isInputTarget(e.target)) return;
                if (fingerShortcutBlockedByOverlay()) return;
                e.preventDefault();
                e.stopImmediatePropagation();
                finger.openFingerMode();
            }, true);
        }

        function fingerShortcutBlockedByOverlay() {
            return !!(document.getElementById('pdf2html-palette')
                || document.getElementById('pdf2html-finder')
                || document.getElementById('pdf2html-settings')
                || document.getElementById('pdf2html-cheatsheet'));
        }

        // ------------------------------------------------------------------------
        // Cmd-K Finder — centered, pretty quick-jump dropdown. Groups candidates
        // from the current document's outline, the cached library, and the
        // palette COMMANDS into one searchable list. Sibling to openPalette()
        // (:) rather than replacing it: : stays vim ex-bar; ⌘K opens this.
        // ------------------------------------------------------------------------

        function closeFinder() {
            var ex = document.getElementById('pdf2html-finder');
            if (ex) ex.remove();
        }

        // SVG atoms — trimmed to just what the row icons need.
        function finderSvg(kind) {
            var attrs = 'width="12" height="12" viewBox="0 0 24 24" fill="none" '
                      + 'stroke="currentColor" stroke-width="1.75" '
                      + 'stroke-linecap="round" stroke-linejoin="round"';
            if (kind === 'doc') {
                return '<svg ' + attrs + '>'
                    + '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
                    + '<path d="M14 3v6h6"/></svg>';
            }
            if (kind === 'book') {
                return '<svg ' + attrs + '>'
                    + '<rect x="3" y="5" width="4" height="14"/>'
                    + '<rect x="9" y="3" width="4" height="16"/>'
                    + '<path d="M15 7l3.5-1 3 11-3.5 1z"/></svg>';
            }
            if (kind === 'cmd') {
                return '<svg ' + attrs + '>'
                    + '<path d="M5 8l4 4-4 4M12 16h7"/></svg>';
            }
            return '';
        }

        // Try to split a chapter label into a leading section number and title.
        // "3.2 Self-organization" → { num: "3.2", title: "Self-organization" }
        // If there's no number, returns { num: "", title: label }.
        function finderParseChapter(label) {
            var m = String(label || '').match(/^\s*([0-9]+(?:\.[0-9]+)*|[A-Z])\s+(.*)$/);
            if (m) return { num: m[1], title: m[2].trim() };
            return { num: '', title: String(label || '').trim() };
        }

        // Derive a human title from a path/URL when the daemon didn't supply
        // a name. Strips the extension so "/Users/x/Foo-Bar.pdf" → "Foo-Bar".
        // URL-decodes percent-encoded segments so %20 doesn't leak into the UI.
        function finderDeriveTitle(ref) {
            var s = String(ref || '').trim();
            if (!s) return '';
            // Drop query string + trailing slashes.
            s = s.replace(/[?#].*$/, '').replace(/\/+$/, '');
            var tail = s.split('/').pop() || s;
            try { tail = decodeURIComponent(tail); } catch (_) {}
            return tail.replace(/\.(pdf|html?|xml)$/i, '');
        }

        // Middle-ellipsis truncation: "/a/really/long/path/to/file.pdf" →
        // "/a/really/…/path/to/file.pdf". Preserves the trailing filename — the
        // most identifying part of a path — and drops the middle directories.
        // Guards against absurd `max` values so we never build a negative slice.
        function finderMiddleEllipsis(s, max) {
            var str = String(s || '');
            var m = Math.max(4, max | 0);
            if (str.length <= m) return str;
            var keep = m - 1; // room for the ellipsis
            var head = Math.max(1, Math.ceil(keep * 0.35));
            var tail = Math.max(1, keep - head);
            return str.slice(0, head) + '…' + str.slice(str.length - tail);
        }

        // Build the full flat-with-groups candidate list once per open. Each
        // candidate is { group, icon, label, meta, searchText, run }.
        function buildFinderCandidates() {
            var out = [];

            // --- Outline (this document) ---
            var chaps = navigation.chapters();
            for (var i = 0; i < chaps.length; i++) {
                var c = chaps[i];
                var parts = finderParseChapter(c.label);
                var num = parts.num;
                var title = parts.title;
                var metaBits = [];
                if (num) metaBits.push('§ ' + num);
                metaBits.push('p. ' + c.page);
                out.push({
                    scope: 'outline',
                    group: 'Outline · this document',
                    icon: num ? { kind: 'text', text: num } : { kind: 'text', text: '§' },
                    label: title,
                    meta: metaBits.join('  ·  '),
                    searchText: (num + ' ' + title + ' ' + c.label).toLowerCase(),
                    run: (function (page) { return function () { navigation.gotoPage(page); }; })(c.page),
                });
            }

            // --- Other documents (library) ---
            var libraryEntries = library.all();
            if (libraryEntries.length) {
                for (var j = 0; j < libraryEntries.length; j++) {
                    var e = libraryEntries[j];
                    if (library.isCurrent(e)) continue;
                    var libLabel = String(e.name || '').trim();
                    if (!libLabel) libLabel = finderDeriveTitle(e.source_ref) || '(untitled)';
                    var bits = [];
                    if (e.source_ref) bits.push(finderMiddleEllipsis(e.source_ref, 44));
                    if (e.pages) bits.push(e.pages + ' pp');
                    var rec = library.recencyLabel(e);
                    if (rec) bits.push(rec);
                    out.push({
                        scope: 'files',
                        group: 'Other documents',
                        icon: { kind: 'svg', svg: finderSvg('book') },
                        label: libLabel,
                        meta: bits.join('  ·  '),
                        searchText: library.searchText(e),
                        run: (function (href) { return function () { if (href) location.href = href; }; })(e.href),
                    });
                }
            }

            // --- Commands ---
            for (var k = 0; k < COMMANDS.length; k++) {
                var cmd = COMMANDS[k];
                var desc = typeof cmd.desc === 'function' ? cmd.desc() : (cmd.desc || '');
                var alias = cmd.aliases && cmd.aliases[0] ? cmd.aliases[0] : '';
                out.push({
                    scope: 'commands',
                    group: 'Commands',
                    icon: { kind: 'svg', svg: finderSvg('cmd') },
                    label: ':' + cmd.name + (alias ? '  ' : ''),
                    labelAlias: alias ? ':' + alias : '',
                    meta: desc,
                    searchText: (cmd.name + ' ' + (cmd.aliases || []).join(' ') + ' ' + desc).toLowerCase(),
                    // Commands that take args shouldn't fire bare — expand into the
                    // ex-bar palette so the user can supply an argument. Zero-arg
                    // commands run straight through.
                    run: (function (c) {
                        return function () {
                            if (commandTakesArg(c)) {
                                openPalette();
                                var inp = document.getElementById('pdf2html-palette-input');
                                if (inp) {
                                    inp.value = c.name + ' ';
                                    inp.dispatchEvent(new Event('input'));
                                    inp.selectionStart = inp.selectionEnd = inp.value.length;
                                }
                            } else {
                                c.handler();
                            }
                        };
                    })(cmd),
                });
            }

            return out;
        }

        // Case-insensitive substring filter; also builds match highlight ranges
        // over the label so we can show which chars hit.
        function finderFilter(candidates, query) {
            var q = String(query || '').trim().toLowerCase();
            if (!q) return candidates.map(function (c) { return { cand: c, hit: null }; });
            var out = [];
            for (var i = 0; i < candidates.length; i++) {
                var c = candidates[i];
                if (c.searchText.indexOf(q) === -1) continue;
                var labelLc = String(c.label || '').toLowerCase();
                var idx = labelLc.indexOf(q);
                out.push({ cand: c, hit: idx >= 0 ? { start: idx, end: idx + q.length } : null });
            }
            return out;
        }

        function escapeFinderHtml(s) {
            return String(s || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function renderFinderLabel(cand, hit) {
            var label = String(cand.label || '');
            var html;
            if (hit) {
                html = escapeFinderHtml(label.slice(0, hit.start))
                     + '<span class="match">' + escapeFinderHtml(label.slice(hit.start, hit.end)) + '</span>'
                     + escapeFinderHtml(label.slice(hit.end));
            } else {
                html = escapeFinderHtml(label);
            }
            if (cand.labelAlias) {
                html += '<span class="dim">' + escapeFinderHtml(cand.labelAlias) + '</span>';
            }
            return html;
        }

        function renderFinderIcon(icon) {
            if (!icon) return '';
            if (icon.kind === 'text') {
                return '<span class="icon icon-text">' + escapeFinderHtml(icon.text) + '</span>';
            }
            return '<span class="icon">' + (icon.svg || '') + '</span>';
        }

        function openFinder() {
            // Toggle: re-press ⌘K closes.
            var existing = document.getElementById('pdf2html-finder');
            if (existing) { existing.remove(); return; }

            // Kick off library fetch if we don't have it yet — first ⌘K on a
            // fresh tab would otherwise render an empty "Other documents" group.
            library.load();

            // Scope cycle: Tab advances, Shift+Tab reverses. 'all' includes the
            // command palette too; the narrower scopes drop it so the user can
            // focus on navigation without noise.
            var SCOPES = [
                { id: 'all',      label: 'All',           placeholder: 'Jump to anything — section, document, command…  ·  tab to cycle' },
                { id: 'outline',  label: 'This document', placeholder: 'Search this document…' },
                { id: 'files',    label: 'Files',         placeholder: 'Search files…' },
            ];
            var scopeIdx = 0;

            var bg = document.createElement('div');
            bg.id = 'pdf2html-finder';
            bg.innerHTML =
                '<div class="pdf2html-finder" role="dialog" aria-label="Quick finder">'
              +   '<div class="pdf2html-finder-input-row">'
              +     '<button type="button" class="pdf2html-finder-scope" id="pdf2html-finder-scope" '
              +       'title="Cycle scope (Tab / Shift+Tab)" hidden>'
              +       '<span class="scope-label"></span>'
              +     '</button>'
              +     '<input type="text" class="pdf2html-finder-input" id="pdf2html-finder-input" '
              +       'autocomplete="off" spellcheck="false" autocapitalize="off" '
              +       'placeholder="Jump to anything — section, document, command…  ·  tab to cycle">'
              +     '<button type="button" class="pdf2html-finder-close" aria-label="Close">'
              +       '<span class="pdf2html-kbd sm">Esc</span>'
              +     '</button>'
              +   '</div>'
              +   '<div class="pdf2html-finder-list" id="pdf2html-finder-list"></div>'
              +   '<div class="pdf2html-finder-foot">'
              +     '<div class="foot-group">'
              +       '<span class="foot-item"><span class="pdf2html-kbd">↑</span><span class="pdf2html-kbd">↓</span><span class="tip">navigate</span></span>'
              +       '<span class="foot-item"><span class="pdf2html-kbd">Tab</span><span class="tip">scope</span></span>'
              +       '<span class="foot-item"><span class="pdf2html-kbd">↵</span><span class="tip">go</span></span>'
              +       '<span class="foot-item"><span class="pdf2html-kbd">Esc</span><span class="tip">close</span></span>'
              +     '</div>'
              +     '<div class="foot-group"><span class="foot-item tip" id="pdf2html-finder-count">—</span></div>'
              +   '</div>'
              + '</div>';

            document.body.appendChild(bg);

            var listEl = bg.querySelector('#pdf2html-finder-list');
            var inputEl = bg.querySelector('#pdf2html-finder-input');
            var countEl = bg.querySelector('#pdf2html-finder-count');
            var closeBtn = bg.querySelector('.pdf2html-finder-close');
            var scopeBtn = bg.querySelector('#pdf2html-finder-scope');
            var scopeLabelEl = scopeBtn.querySelector('.scope-label');

            function currentScope() { return SCOPES[scopeIdx].id; }
            function cycleScope(delta) {
                scopeIdx = (scopeIdx + delta + SCOPES.length) % SCOPES.length;
                var scope = SCOPES[scopeIdx];
                var isDefault = scopeIdx === 0;
                // All mode: hide the pill entirely, fold the cue into the input
                // placeholder. Narrower scopes: materialize the pill.
                scopeBtn.hidden = isDefault;
                scopeLabelEl.textContent = isDefault ? '' : scope.label;
                scopeBtn.classList.toggle('accent', !isDefault);
                inputEl.placeholder = scope.placeholder;
                render();
            }
            scopeBtn.addEventListener('click', function () { cycleScope(1); inputEl.focus(); });

            // Click outside (on the backdrop, not the modal) closes.
            bg.addEventListener('mousedown', function (ev) {
                if (ev.target === bg) { ev.preventDefault(); closeFinder(); }
            });
            closeBtn.addEventListener('click', function () { closeFinder(); });

            var allCandidates = buildFinderCandidates();
            var state = { visible: [], idx: 0 };

            // Expose the active element-lookup fn to scroll-into-view after render.
            function scrollActiveIntoView() {
                var active = listEl.querySelector('.pdf2html-finder-row.active');
                if (active && active.scrollIntoView) {
                    active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                }
            }

            function render() {
                // Bail if the modal was ripped out from under us (poll callback,
                // async library fetch, etc. — the listEl would be orphaned).
                if (!bg.isConnected) return;
                var q = inputEl.value;
                // Cap bareNum to an int that can't roll into Infinity/NaN — the
                // gotoPage() lookup silently fails for missing pages, but we
                // still want a sane upper bound on the synthetic "Go to" row.
                var bareNumMatch = /^\s*(\d{1,7})\s*$/.exec(q);
                var bareNum = bareNumMatch ? parseInt(bareNumMatch[1], 10) : 0;

                var scope = currentScope();
                var scoped = scope === 'all'
                    ? allCandidates
                    : allCandidates.filter(function (c) { return c.scope === scope; });
                var filtered = finderFilter(scoped, q);

                // Prepend a synthetic "Go to page N" entry when the user types a
                // bare number — mirrors the : palette's `:42` shortcut.
                // Only in scopes that include in-document navigation.
                if (bareNum > 0 && (scope === 'all' || scope === 'outline')) {
                    filtered.unshift({
                        cand: {
                            group: 'Go to',
                            icon: { kind: 'svg', svg: finderSvg('doc') },
                            label: 'Page ' + bareNum,
                            meta: 'jump',
                            run: (function (n) { return function () { navigation.gotoPage(n); }; })(bareNum),
                        },
                        hit: null,
                    });
                }

                state.visible = filtered;
                if (state.idx >= filtered.length) state.idx = 0;
                if (state.idx < 0) state.idx = 0;

                listEl.innerHTML = '';
                if (!filtered.length) {
                    var empty = document.createElement('div');
                    empty.className = 'pdf2html-finder-empty';
                    empty.textContent = q ? 'No matches for "' + q + '"' : 'Nothing here yet.';
                    listEl.appendChild(empty);
                    countEl.textContent = '0 results';
                    return;
                }

                var lastGroup = null;
                // Group counts for the group-label tail count chip.
                var counts = {};
                for (var gi = 0; gi < filtered.length; gi++) {
                    var g = filtered[gi].cand.group;
                    counts[g] = (counts[g] || 0) + 1;
                }

                for (var i = 0; i < filtered.length; i++) {
                    var entry = filtered[i];
                    var cand = entry.cand;
                    if (cand.group !== lastGroup) {
                        lastGroup = cand.group;
                        var gLabel = document.createElement('div');
                        gLabel.className = 'pdf2html-finder-group';
                        gLabel.innerHTML =
                            escapeFinderHtml(cand.group)
                          + '<span class="count">' + counts[cand.group] + '</span>';
                        listEl.appendChild(gLabel);
                    }
                    var row = document.createElement('div');
                    row.className = 'pdf2html-finder-row' + (i === state.idx ? ' active' : '');
                    row.dataset.idx = String(i);
                    row.innerHTML =
                        renderFinderIcon(cand.icon)
                      + '<span class="label">' + renderFinderLabel(cand, entry.hit) + '</span>'
                      + '<span class="meta">' + escapeFinderHtml(cand.meta || '') + '</span>';
                    row.addEventListener('mousemove', (function (idx) {
                        return function () {
                            if (state.idx !== idx) {
                                state.idx = idx;
                                // Light-touch re-render: just toggle the `active`
                                // class instead of redrawing the whole list on
                                // every mouse pixel.
                                var rows = listEl.querySelectorAll('.pdf2html-finder-row');
                                for (var r = 0; r < rows.length; r++) {
                                    rows[r].classList.toggle('active', Number(rows[r].dataset.idx) === idx);
                                }
                            }
                        };
                    })(i));
                    row.addEventListener('mousedown', (function (runFn) {
                        return function (ev) {
                            ev.preventDefault();
                            closeFinder();
                            if (typeof runFn === 'function') {
                                setTimeout(function () {
                                    try { runFn(); }
                                    catch (err) { console.warn('[finder] run failed:', err); }
                                }, 0);
                            }
                        };
                    })(cand.run));
                    listEl.appendChild(row);
                }

                countEl.textContent = filtered.length + (filtered.length === 1 ? ' result' : ' results');
                scrollActiveIntoView();
            }

            function move(delta) {
                if (!state.visible.length) return;
                state.idx = (state.idx + delta + state.visible.length) % state.visible.length;
                var rows = listEl.querySelectorAll('.pdf2html-finder-row');
                for (var r = 0; r < rows.length; r++) {
                    rows[r].classList.toggle('active', Number(rows[r].dataset.idx) === state.idx);
                }
                scrollActiveIntoView();
            }

            inputEl.addEventListener('input', render);
            inputEl.addEventListener('keydown', function (ev) {
                if (ev.key === 'Escape') {
                    ev.stopPropagation(); ev.preventDefault();
                    closeFinder();
                } else if (ev.key === 'Tab') {
                    ev.preventDefault();
                    state.idx = 0;
                    cycleScope(ev.shiftKey ? -1 : 1);
                } else if (ev.key === 'Enter') {
                    ev.preventDefault();
                    var pick = state.visible[state.idx];
                    if (pick && pick.cand && typeof pick.cand.run === 'function') {
                        closeFinder();
                        setTimeout(function () {
                            try { pick.cand.run(); }
                            catch (err) { console.warn('[finder] run failed:', err); }
                        }, 0);
                    }
                } else if (ev.key === 'ArrowDown' || (ev.ctrlKey && !ev.metaKey && !ev.altKey && (ev.key === 'j' || ev.key === 'J'))) {
                    ev.preventDefault(); move(1);
                } else if (ev.key === 'ArrowUp' || (ev.ctrlKey && !ev.metaKey && !ev.altKey && (ev.key === 'k' || ev.key === 'K'))) {
                    ev.preventDefault(); move(-1);
                }
            });

            // Library might not have loaded yet; re-render once it lands so the
            // "Other documents" group fills in. Bail early if the user closed the
            // finder while we were waiting — no point mutating an orphaned DOM.
            if (!library.all().length) {
                var retries = 0;
                var poll = setInterval(function () {
                    if (!bg.isConnected) { clearInterval(poll); return; }
                    if (library.all().length || retries++ > 20) {
                        clearInterval(poll);
                        if (!bg.isConnected) return;
                        allCandidates = buildFinderCandidates();
                        render();
                    }
                }, 150);
            }

            inputEl.focus();
            render();
        }

        // ⌘K — open the finder dropdown. Bypasses isInputTarget so it works
        // from any focus state (Raycast-style quick-open expectation).
        function registerQuickOpenHandler() {
            document.addEventListener('keydown', function (e) {
                if (!e.metaKey || e.ctrlKey || e.altKey) return;
                if (e.key !== 'k' && e.key !== 'K') return;
                e.preventDefault(); e.stopPropagation();
                // If the : palette happens to be open, close it first — ⌘K is a
                // distinct UI.
                var existing = document.getElementById('pdf2html-palette');
                if (existing) existing.remove();
                openFinder();
            }, true);
        }


        // ⌘, — open settings, intercepting the browser's own preferences shortcut.
        // Capture-phase preventDefault is what keeps Comet from opening its
        // settings page; Chromium only reserves ⌘T/W/Q/N hard, so ⌘, is ours to
        // take. Bypasses isInputTarget like ⌘K — chord shortcuts should work from
        // any focus state. openSettings() toggles, so pressing again closes.
        function registerSettingsHandler() {
            document.addEventListener('keydown', function (e) {
                if (!e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
                if (e.key !== ',' && e.code !== 'Comma') return;
                e.preventDefault(); e.stopPropagation();
                openSettings();
            }, true);
        }

        // ------------------------------------------------------------------------
        // Count-prefix motion handler — the overlay's only count-prefix binding.
        //   e / q / E : +1 / -1 / -1 page (10e = +10 pages, 10q = -10 pages)
        //   c / C : ±1 chapter (10c = +10 chapters, 10C = -10 chapters)
        // Bare keys = ±1. Digits buffer until a motion fires, 1.5 s elapses, or
        // any other key cancels. Requires Vimium passthrough for `e q E c C 0-9`
        // on localhost:7435, else Vimium swallows the digits or letters. When the
        // page receives the key and a browser Selection is active, e/q/E extend
        // the focus end pagewise instead of jumping the viewport, and bare `c`
        // promotes that selection to the full chapter containing its focus page.
        // ------------------------------------------------------------------------
    function closeSurface() {
        var finder = document.getElementById('pdf2html-finder');
        if (finder) { finder.remove(); return true; }
        var palette = document.getElementById('pdf2html-palette');
        if (palette) { palette.remove(); return true; }
        var help = document.getElementById('pdf2html-cheatsheet');
        if (help) { help.remove(); return true; }
        return false;
    }
    function closeFinderOrPalette() {
        var finder = document.getElementById('pdf2html-finder');
        if (finder) { finder.remove(); return true; }
        var palette = document.getElementById('pdf2html-palette');
        if (palette) { palette.remove(); return true; }
        return false;
    }
    function closeHelp() {
        var help = document.getElementById('pdf2html-cheatsheet');
        if (help) { help.remove(); return true; }
        return false;
    }
    return {
        init: function () { registerQuestionHandler(); registerPaletteHandler(); registerFingerShortcutHandler(); registerQuickOpenHandler(); registerSettingsHandler(); },
        closeSurface: closeSurface,
        closeFinderOrPalette: closeFinderOrPalette,
        closeHelp: closeHelp,
        toggleCheatsheet: toggleCheatsheet,
        openPalette: openPalette,
        openFinder: openFinder,
        commands: function () { return COMMANDS.slice(); },
    };
}
