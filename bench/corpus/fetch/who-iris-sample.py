#!/usr/bin/env python3
"""Sample PDFs from WHO IRIS (DSpace 7 REST API) by language.

usage: [SEED=n] [LABEL_PREFIX=who2] python3 -I who-iris-sample.py <lang>:<count> ...   e.g. ar:4 zh:4 ru:4
SEED unset or 0: newest items (phase 1). SEED>0: random result pages across the whole language set.
Downloads go through fetch-one.sh into incoming/who-iris-multilingual/.
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://iris.who.int/server/api"
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus)"}
LIC = "WHO IRIS item; most CC BY-NC-SA 3.0 IGO (see item record)"

def get(url):
    time.sleep(1)
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))

def main(args):
    import random
    rng = random.Random(int(os.environ.get("SEED", "0")))
    for arg in args:
        lang, count = arg.split(":"); count = int(count)
        base = {"query": f"dc.language.iso:{lang}", "dsoType": "ITEM", "size": 20, "sort": "dc.date.accessioned,DESC"}
        total = get(f"{API}/discover/search/objects?{urllib.parse.urlencode(base)}")["_embedded"]["searchResult"]["page"]["totalPages"]
        # SEED=0 keeps the phase-1 behaviour (newest items); otherwise draw random result pages
        pages = list(range(total)) if os.environ.get("SEED", "0") == "0" else rng.sample(range(total), min(total, count))
        got = 0
        for pnum in pages:
            if got >= count: break
            objs = get(f"{API}/discover/search/objects?{urllib.parse.urlencode({**base, 'page': pnum})}")["_embedded"]["searchResult"]["_embedded"]["objects"]
            for o in rng.sample(objs, min(3, len(objs))):
                if got >= count: break
                item = o["_embedded"]["indexableObject"]
                try:
                    bundles = get(item["_links"]["bundles"]["href"])["_embedded"]["bundles"]
                except Exception:
                    continue
                for b in bundles:
                    if b["name"] != "ORIGINAL": continue
                    bs = get(b["_links"]["bitstreams"]["href"])["_embedded"]["bitstreams"]
                    pdfs = [x for x in bs if x["name"].lower().endswith(".pdf") and x["sizeBytes"] < 40e6]
                    # prefer the file in the requested language (name ends in -ara/-chi/-rus etc.)
                    pdfs.sort(key=lambda x: 0 if re.search(r"[-_](ara|ar|chi|zh|rus|ru|fre|fr|spa|es)\.pdf$", x["name"].lower()) else 1)
                    if not pdfs: continue
                    x = pdfs[0]
                    prefix = os.environ.get("LABEL_PREFIX", "who")
                    name = f"{prefix}-{lang}__{item['handle'].replace('/', '-')}__{x['name']}".replace(" ", "_")
                    r = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "who-iris-multilingual",
                                        x["_links"]["content"]["href"], name, f"{LIC}; handle {item['handle']}", "40"])
                    got += r.returncode == 0
                    break

if __name__ == "__main__":
    main(sys.argv[1:])
