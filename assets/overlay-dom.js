// Small stateless DOM helpers shared by the overlay modules.

// Declarative element construction: el('div', {class, html, onClick, dataset,
// ...attrs}, children). Not a framework, just sugar.
export function el(tag, attrs, children) {
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

export var ICONS = {
    sidebar:  '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
    outline:  '<path d="M4 6h16M4 12h16M4 18h10"/>',
    grid:     '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    help:     '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
};

export function svgIcon(path, size) {
    size = size || 14;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" '
        + 'fill="none" stroke="currentColor" stroke-width="1.75" '
        + 'stroke-linecap="round" stroke-linejoin="round">' + path + '</svg>';
}

// Remove an overlay that held keyboard focus. When a focused input leaves the
// DOM, Chromium relocates the selection to the last text before it — the end
// of the document — leaving a stray caret that Vimium's `v` would start
// from. A collapsed selection after removal is that stray caret; a real
// (non-collapsed) selection, such as a promoted search hit, is kept.
export function removeOverlay(node) {
    if (!node) return false;
    node.remove();
    var sel = window.getSelection();
    if (sel && sel.rangeCount && sel.isCollapsed) sel.removeAllRanges();
    return true;
}

// Keys typed into a text field belong to that field, not to viewer bindings.
export function isInputTarget(t) {
    return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT'
        || t.isContentEditable === true);
}

export function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// "/a/really/long/path/to/file.pdf" → "/a/rea…/path/to/file.pdf": keeps the
// trailing filename, the most identifying part, and drops the middle.
export function middleEllipsis(s, max) {
    var str = String(s || '');
    var m = Math.max(4, max | 0);
    if (str.length <= m) return str;
    var keep = m - 1;
    var head = Math.max(1, Math.ceil(keep * 0.35));
    return str.slice(0, head) + '…' + str.slice(str.length - Math.max(1, keep - head));
}
