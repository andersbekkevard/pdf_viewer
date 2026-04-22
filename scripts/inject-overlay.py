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
