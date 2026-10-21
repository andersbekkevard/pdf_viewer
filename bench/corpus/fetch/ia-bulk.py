#!/usr/bin/env python3
"""Sample public-domain scanned books from the Internet Archive.

usage: python3 -I ia-bulk.py <plan.tsv> <max_mb> <seed>
plan.tsv rows: label<TAB>advancedsearch query<TAB>count
Items flagged access-restricted are skipped; only items with year <= 1928 or
possible-copyright-status NOT_IN_COPYRIGHT are taken. The first PDF whose format is
Text PDF / Image Container PDF / Grayscale PDF / Additional Text PDF and is under
max_mb is fetched into incoming/internet-archive/ as <label>__<file>.
"""
import json, os, random, subprocess, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"}
FORMATS = ["Text PDF", "Additional Text PDF", "Image Container PDF", "Grayscale PDF"]

def get(url):
    time.sleep(1)
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120))

def main(plan, max_mb, seed):
    rng = random.Random(seed)
    for line in open(plan):
        if not line.strip() or line.startswith("#"): continue
        label, q, count = line.rstrip("\n").split("\t"); count = int(count)
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
            [("q", f"({q}) AND mediatype:texts"), ("fl[]", "identifier"), ("fl[]", "year"), ("rows", "200"), ("sort[]", "downloads desc"), ("output", "json")])
        try: docs = get(url)["response"]["docs"]
        except Exception as e: print("search fail", label, e, file=sys.stderr); continue
        rng.shuffle(docs); got = 0
        for d in docs:
            if got >= count: break
            try: md = get(f"https://archive.org/metadata/{d['identifier']}")
            except Exception: continue
            m = md.get("metadata", {})
            if m.get("access-restricted-item") in ("true", True): continue
            try: year = int(str(m.get("year", d.get("year", "9999")))[:4])
            except ValueError: year = 9999
            if year > 1928 and m.get("possible-copyright-status") != "NOT_IN_COPYRIGHT": continue
            files = [f for f in md.get("files", []) if f["name"].lower().endswith(".pdf") and f.get("format") in FORMATS
                     and int(f.get("size", 0)) < max_mb * 1e6]
            files.sort(key=lambda f: FORMATS.index(f["format"]))
            if not files: continue
            f = files[0]; ident = d["identifier"]
            src = f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}"
            name = f"{label}__{os.path.basename(f['name'])}".replace(" ", "_")
            r = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "internet-archive", src, name,
                                f"Public domain (year {year}; Internet Archive item {ident}; format {f['format']})", str(int(max_mb))],
                               env={**os.environ, "FETCH_SLEEP": "2"})
            got += r.returncode == 0

if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), int(sys.argv[3]))
