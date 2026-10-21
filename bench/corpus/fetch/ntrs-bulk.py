#!/usr/bin/env python3
"""Sample NASA NTRS reports by era and topic.

usage: python3 -I ntrs-bulk.py <plan.tsv> <max_mb> <seed>
plan.tsv rows: label<TAB>query<TAB>from YYYY-MM-DD<TAB>to YYYY-MM-DD<TAB>count
Only distribution PUBLIC records with an application/pdf download are taken.
"""
import json, os, random, subprocess, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus)"}
plan, max_mb, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
rng = random.Random(seed)
for line in open(plan):
    if not line.strip() or line.startswith("#"): continue
    label, q, lo, hi, n = line.rstrip("\n").split("\t"); n = int(n)
    url = "https://ntrs.nasa.gov/api/citations/search?" + urllib.parse.urlencode(
        {"q": q, "published.gte": lo, "published.lte": hi, "page.size": 100})
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
    except Exception as e:
        print("api fail", label, e, file=sys.stderr); continue
    time.sleep(1)
    res = [r for r in d["results"] if r.get("distribution") == "PUBLIC"]
    rng.shuffle(res); got = 0
    for r in res:
        if got >= n: break
        pdfs = [x["links"]["pdf"] for x in r.get("downloads", []) if x.get("mimetype") == "application/pdf" and x.get("links", {}).get("pdf")]
        if not pdfs: continue
        p = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "gov-nasa-ntrs", "https://ntrs.nasa.gov" + pdfs[0], f"{label}__{r['id']}.pdf",
                            "NASA technical report, US government work (NTRS distribution PUBLIC)", max_mb], env={**os.environ, "FETCH_SLEEP": "1"})
        got += p.returncode == 0
