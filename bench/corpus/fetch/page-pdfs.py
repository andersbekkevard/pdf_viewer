#!/usr/bin/env python3
"""Fetch a sample of the PDFs linked from one HTML page.

usage: python3 -I page-pdfs.py <source> <label> <page_url> <count> <license> [regex]
Links ending in .pdf (case-insensitive, query allowed) are resolved against the page,
deduplicated, filtered by the optional regex, spread-sampled, and fetched through
fetch-one.sh into incoming/<source>/ as <label>__<basename>.
"""
import os, re, subprocess, sys, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
src, label, page, count, lic = sys.argv[1:6]
rx = re.compile(sys.argv[6]) if len(sys.argv) > 6 else None
req = urllib.request.Request(page, headers={"User-Agent": "Mozilla/5.0 (pdfv-corpus/0.1)"})
html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
links = []
for h in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.I):
    u = urllib.parse.urljoin(page, h.strip())
    if re.search(r"\.pdf($|[?#])", u, re.I) and (not rx or rx.search(u)) and u not in links:
        links.append(u)
print(f"# {len(links)} pdf links on {page}", file=sys.stderr)
count = int(count)
step = max(1, len(links) // max(count, 1))
for u in links[::step][:count]:
    base = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(u).path))
    base = re.sub(r"[^\w.\-]+", "_", base)
    subprocess.run([os.path.join(HERE, "fetch-one.sh"), src, u, f"{label}__{base}", lic, "60"],
                   env={**os.environ, "FETCH_SLEEP": "2"})
