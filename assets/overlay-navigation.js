// Document position, structural navigation, and persistent marks.
export function createNavigation(core) {
    var document = core.document;
    var storage = core.storage;
    var entryHash = core.entryHash;
    var currentPage = 1;
    var chapterNearThreshold = 2;

    function init() {
        document.addEventListener('pdf2html-page-change', function (e) {
            if (e.detail && e.detail.page) currentPage = e.detail.page;
        });
    }
    function page() { return currentPage; }
    function setPage(value) { if (value) currentPage = value; }
    function chapterLabel() {
        var link = document.querySelector('#outline a.pdf2html-active');
        return link ? (link.textContent || '').replace(/\s+/g, ' ').trim() : '';
    }
    function chapters() {
        var links = document.querySelectorAll('#outline a[href^="#pf"]'), out = [];
        for (var i = 0; i < links.length; i++) {
            var a = links[i], m = (a.getAttribute('href') || '').match(/#pf([0-9a-f]+)/i);
            if (!m) continue;
            var label = (a.textContent || '').replace(/\s+/g, ' ').trim();
            if (label) out.push({ label: label, page: parseInt(m[1], 16) });
        }
        return out;
    }
    function sortedChapters() {
        var result = chapters().sort(function (a, b) { return a.page - b.page; }), seen = {};
        return result.filter(function (c) { if (seen[c.page]) return false; seen[c.page] = true; return true; });
    }
    function gotoPage(n) {
        var target = document.getElementById('pf' + n.toString(16));
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    function snapToPage(n) {
        if (!n || n < 1) return;
        var target = document.getElementById('pf' + n.toString(16));
        var container = document.getElementById('page-container');
        if (!target || !container) return;
        container.scrollTop = Math.max(0, target.offsetTop - 8);
    }
    function gotoChapter(needle) {
        if (!needle) return;
        var list = chapters(), n = needle.toLowerCase().trim(), exact = null, sub = null;
        for (var i = 0; i < list.length; i++) {
            var label = list[i].label.toLowerCase();
            if (label === n) { exact = list[i]; break; }
            if (!sub && label.indexOf(n) !== -1) sub = list[i];
        }
        var pick = exact || sub;
        if (pick) gotoPage(pick.page);
    }
    function gotoChapterBy(delta) {
        var list = sortedChapters();
        if (!list.length || !delta) return;
        var idx = -1;
        for (var i = 0; i < list.length; i++) { if (list[i].page <= currentPage) idx = i; else break; }
        var target;
        if (delta > 0) target = idx === -1 ? 0 : idx + delta;
        else if (delta === -1) {
            if (idx === -1) return;
            target = currentPage - list[idx].page >= chapterNearThreshold ? idx : idx - 1;
        } else { if (idx === -1) return; target = idx + delta; }
        target = Math.min(list.length - 1, Math.max(0, target));
        snapToPage(list[target].page);
    }
    function marksKey() { var hash = entryHash(); return hash ? 'pdf2html-marks:' + hash : null; }
    function marks() {
        var key = marksKey(); if (!key) return {};
        try { return JSON.parse(storage.getItem(key) || '{}') || {}; } catch (_) { return {}; }
    }
    function saveMarks(value) { var key = marksKey(); if (key) try { storage.setItem(key, JSON.stringify(value)); } catch (_) {} }
    function markLetter(value) {
        if (!value) return null;
        var match = String(value).trim().match(/^([a-zA-Z])/);
        return match ? match[1].toLowerCase() : null;
    }
    function setMark(value) {
        var letter = markLetter(value); if (!letter) return;
        var all = marks(); all[letter] = { page: currentPage, label: chapterLabel(), ts: Date.now() }; saveMarks(all);
    }
    function gotoMark(value) { var letter = markLetter(value), mark = letter && marks()[letter]; if (mark && mark.page) gotoPage(mark.page); }
    function clearMark(value) {
        var letter = markLetter(value); if (!letter) return;
        var all = marks(); if (!all[letter]) return; delete all[letter]; saveMarks(all);
    }
    return { init: init, page: page, setPage: setPage, chapterLabel: chapterLabel, chapters: chapters,
        sortedChapters: sortedChapters, gotoPage: gotoPage, snapToPage: snapToPage,
        gotoChapter: gotoChapter, gotoChapterBy: gotoChapterBy, marks: marks,
        markLetter: markLetter, setMark: setMark, gotoMark: gotoMark, clearMark: clearMark };
}
