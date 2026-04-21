#!/usr/bin/env python3
"""Inject title, favicon, and overlay <link>/<script> tags into a pdf2htmlEX
output HTML in place.

Usage: inject-overlay.py <html_path> <title_stem> <overlay_version>

Idempotent: strips any prior id="pdf2html-overlay-*" / id="pdf2html-favicon"
tags (and old inline <style>/<script> pairs from the legacy hardcoded script)
before injecting the current versions. Safe to re-run — that's the whole
point of upgrade-cache.sh --mode=inject.
"""
import sys
import re
import pathlib
import html as _html
import urllib.parse as _up


def inject(html: str, stem: str, version: str) -> str:
    stem_escaped = _html.escape(stem)

    # --- Title -------------------------------------------------------------
    if re.search(r'<title>.*?</title>', html, flags=re.DOTALL):
        html = re.sub(r'<title>.*?</title>', f'<title>{stem_escaped}</title>',
                      html, count=1, flags=re.DOTALL)
    else:
        html = html.replace('</head>', f'<title>{stem_escaped}</title></head>', 1)

    # --- Favicon -----------------------------------------------------------
    html = re.sub(
        r'<link[^>]*\brel\s*=\s*["\']?(?:shortcut\s+)?icon["\'][^>]*>\s*',
        '', html, flags=re.IGNORECASE)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<text y=".9em" font-size="90">📑</text></svg>')
    favicon = (f'<link id="pdf2html-favicon" rel="icon" '
               f'href="data:image/svg+xml;utf8,{_up.quote(svg)}">')
    if 'id="pdf2html-favicon"' in html:
        html = re.sub(r'<link id="pdf2html-favicon"[^>]*>\s*', '', html)
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

    overlay_tags = (
        f'<link id="pdf2html-overlay-css" rel="stylesheet" '
        f'href="/_assets/overlay.css?v={version}">'
        f'<script id="pdf2html-overlay-js" '
        f'src="/_assets/overlay.js?v={version}" defer></script>'
    )
    html = html.replace('</head>', overlay_tags + '</head>', 1)
    return html


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: inject-overlay.py <html_path> <title_stem> <version>",
              file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    stem, version = sys.argv[2], sys.argv[3]
    try:
        html = path.read_text(encoding='utf-8', errors='ignore')
    except FileNotFoundError:
        print(f"not found: {path}", file=sys.stderr)
        return 1
    path.write_text(inject(html, stem, version), encoding='utf-8')
    return 0


if __name__ == "__main__":
    sys.exit(main())
