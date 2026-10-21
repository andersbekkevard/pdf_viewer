#!/usr/bin/env python3
"""Targeted MIT OpenCourseWare PDFs through the MIT Learn content-file search API.

usage: python3 -I ocw-learn.py <plan.tsv> <seed>
plan.tsv rows: label<TAB>q (or -)<TAB>content_feature_type (or -)<TAB>count
Searches https://api.learn.mit.edu/api/v1/content_file_search/?platform=ocw at random
offsets, keeps results with content_type pdf, opens each OCW resource page and fetches
its first .pdf link into incoming/mit-ocw/ as ocw3-<label>__<basename>.
"""
import json, os, random, re, subprocess, sys, time, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"}
API = "https://api.learn.mit.edu/api/v1/content_file_search/"

def get(url, js=True):
    time.sleep(1)
    b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    return json.loads(b) if js else b.decode("utf-8", "replace")

def main(plan, seed):
    rng = random.Random(seed); seen = set()
    for line in open(plan):
        if not line.strip() or line.startswith("#"): continue
        label, q, ft, n = line.rstrip("\n").split("\t"); n = int(n)
        params = {"platform": "ocw", "limit": 50}
        if q != "-": params["q"] = q
        if ft != "-": params["content_feature_type"] = ft
        try: total = min(get(API + "?" + urllib.parse.urlencode({**params, "limit": 1}))["count"], 5000)
        except Exception as e: print("api fail", label, e, file=sys.stderr); continue
        got, tries = 0, 0
        while got < n and tries < 8:
            tries += 1
            off = rng.randrange(0, max(1, total - 50))
            try: res = get(API + "?" + urllib.parse.urlencode({**params, "offset": off}))["results"]
            except Exception: continue
            res = [r for r in res if r.get("content_type") == "pdf" and r.get("url", "").startswith("https://ocw.mit.edu/") and r["url"] not in seen]
            rng.shuffle(res)
            for r in res[: max(1, n // 4)]:
                if got >= n: break
                seen.add(r["url"])
                try: page = get(r["url"], js=False)
                except Exception: continue
                m = re.search(r'href="([^"]+\.pdf)"', page)
                if not m: continue
                u = m.group(1); u = "https://ocw.mit.edu" + u if u.startswith("/") else u
                base = re.sub(r"^[0-9a-f]{32}_", "", os.path.basename(u))
                p = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "mit-ocw", u, f"ocw3-{label}__{base}",
                                    f"CC BY-NC-SA 4.0 (MIT OpenCourseWare); course {r.get('resource_readable_id')}", "80"],
                                   env={**os.environ, "FETCH_SLEEP": "1"})
                got += p.returncode == 0

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
