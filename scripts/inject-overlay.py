#!/usr/bin/env python3
"""Inject title, favicon, and overlay <link>/<script> tags into a pdf2htmlEX
output HTML in place.

Usage: inject-overlay.py <html_path> <title_stem>
       inject-overlay.py --print-version

The asset version (?v=…) is derived automatically from a content hash of
assets/overlay.js + assets/overlay.css (first 10 hex chars of sha256 over the
two files' concatenated bytes), resolved relative to this script's repo
location. No manual version constant — editing either asset changes the hash,
so the ?v= self-busts; re-running with unchanged assets is a byte-identical
no-op.

A legacy third positional argument (the old explicit version) is accepted and
ignored for back-compat with any in-flight caller, but it has no effect.

Idempotent: strips any prior id="pdf2html-overlay-*" / id="pdf2html-favicon"
tags (and old inline <style>/<script> pairs from the legacy hardcoded script)
before injecting the current versions. Safe to re-run — that's the whole
point of upgrade-cache.sh --mode=inject.
"""
import sys
import re
import hashlib
import pathlib
import html as _html

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_DIR / "assets"


def _asset_files() -> list[pathlib.Path]:
    """All overlay assets that affect the rendered viewer: every overlay*.js
    module (the entry overlay.js plus any extracted overlay-<seam>.js leaves)
    plus overlay.css. Sorted by name for a deterministic, order-stable hash."""
    js = sorted(ASSETS_DIR.glob("overlay*.js"))
    css = [ASSETS_DIR / "overlay.css"]
    return js + css


def asset_version() -> str:
    """First 10 hex chars of sha256 over the concatenated bytes of every
    overlay module + overlay.css (deterministic name order). Editing any
    module — or adding/removing one — changes the hash. Stable across runs
    when assets are unchanged."""
    h = hashlib.sha256()
    for path in _asset_files():
        h.update(path.read_bytes())
    return h.hexdigest()[:10]


def inject(html: str, stem: str, version: str, entry_hash: str = "") -> str:
    stem_escaped = _html.escape(stem)

    # --- Title -------------------------------------------------------------
    if re.search(r'<title>.*?</title>', html, flags=re.DOTALL):
        html = re.sub(r'<title>.*?</title>', f'<title>{stem_escaped}</title>',
                      html, count=1, flags=re.DOTALL)
    else:
        html = html.replace('</head>', f'<title>{stem_escaped}</title></head>', 1)

    # --- Cache-entry hash meta ---------------------------------------------
    # The overlay JS needs to know its own <hash> so it can build URLs to
    # sibling assets (meta.json, thumbs/N.jpg). Path-based detection via
    # location.pathname fails when the HTML is served through /view?path=...
    # (FileResponse keeps the URL on /view), so we embed the hash explicitly.
    html = re.sub(r'<meta id="pdf2html-hash"[^>]*>\s*', '', html)
    if entry_hash:
        hash_tag = f'<meta id="pdf2html-hash" name="pdf2html-hash" content="{_html.escape(entry_hash)}">'
        html = html.replace('</head>', hash_tag + '</head>', 1)

    # --- Favicon -----------------------------------------------------------
    html = re.sub(
        r'<link[^>]*\brel\s*=\s*["\']?(?:shortcut\s+)?icon["\'][^>]*>\s*',
        '', html, flags=re.IGNORECASE)
    favicon = (f'<link id="pdf2html-favicon" rel="icon" type="image/svg+xml" '
               f'href="/_assets/favicon.svg?v={version}">')
    html = html.replace('</head>', favicon + '</head>', 1)

    # --- Overlay link + script tags ---------------------------------------
    # Strip any prior inline injection (old hardcoded script) or prior tag
    # injection (for upgrades).
    html = re.sub(r'<style id="pdf2html-overlay-css">.*?</style>\s*',
                  '', html, flags=re.DOTALL)
    html = re.sub(r'<script id="pdf2html-overlay-js">.*?</script>\s*',
                  '', html, flags=re.DOTALL)
    html = re.sub(r'<link id="pdf2html-overlay-css"[^>]*>\s*', '', html)
    html = re.sub(r'<script id="pdf2html-overlay-js"[^>]*></script>\s*', '', html)

    # overlay.js is now an ES module entry point that imports sibling
    # overlay-<seam>.js leaves via plain relative specifiers. type="module"
    # scripts defer by default (same post-parse timing as the old `defer`
    # classic script), so the render-loop kill still runs after HTML parse.
    # The ?v= busts the entry module on asset change; the imported leaves are
    # busted by the daemon's ETag + must-revalidate (no query strings on the
    # import specifiers, which would otherwise break module resolution).
    overlay_tags = (
        f'<link id="pdf2html-overlay-css" rel="stylesheet" '
        f'href="/_assets/overlay.css?v={version}">'
        f'<script id="pdf2html-overlay-js" type="module" '
        f'src="/_assets/overlay.js?v={version}"></script>'
    )
    html = html.replace('</head>', overlay_tags + '</head>', 1)
    return html


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--print-version":
        print(asset_version())
        return 0
    # Accept <html> <stem> [legacy_version]; the legacy version is ignored.
    if len(sys.argv) not in (3, 4):
        print("usage: inject-overlay.py <html_path> <title_stem>\n"
              "       inject-overlay.py --print-version",
              file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    stem = sys.argv[2]
    version = asset_version()
    # Cache layout is <cache_root>/<hash>/<stem>.html; the parent dir name
    # is the content hash. Fall back to "" if the path doesn't match — the
    # injector still works, just without the hash meta tag.
    entry_hash = path.parent.name if re.fullmatch(r"[a-f0-9]{6,64}",
                                                  path.parent.name) else ""
    try:
        html = path.read_text(encoding='utf-8', errors='ignore')
    except FileNotFoundError:
        print(f"not found: {path}", file=sys.stderr)
        return 1
    path.write_text(inject(html, stem, version, entry_hash), encoding='utf-8')
    return 0


if __name__ == "__main__":
    sys.exit(main())
