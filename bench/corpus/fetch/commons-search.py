#!/usr/bin/env python3
"""Fetch PDFs from Wikimedia Commons search, optionally verifying the script.

usage: python3 -I commons-search.py <source> <plan.tsv> <max_mb> <seed>
plan.tsv rows: label<TAB>search terms<TAB>count<TAB>script (or -)
script is one of: arab hebr cjk hira hang deva beng taml thai tibt ethi mymr geor armn khmr -.
Search: filemime:application/pdf filesize:<max_mb MB> <terms> in the File namespace.
After download, if the first 3 pages have extractable text (pdftotext), at least 20% of
its letters must be in the script's Unicode ranges or the file is discarded. Files with
no text (scans) are kept and labelled script-unverified. Rows get a 4th labels column.
"""
import json, os, random, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
CORPUS = os.environ.get("PDFV_CORPUS_DIR", os.path.expanduser("~/.local/share/pdf_viewer/corpus"))
UA = {"User-Agent": "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"}
RANGES = {"arab": [(0x600, 0x6FF), (0x750, 0x77F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)], "hebr": [(0x590, 0x5FF), (0xFB1D, 0xFB4F)],
          "cjk": [(0x3040, 0x30FF), (0x3400, 0x9FFF), (0xF900, 0xFAFF)], "hira": [(0x3040, 0x30FF), (0x3400, 0x9FFF)],
          "hang": [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)], "deva": [(0x900, 0x97F)], "beng": [(0x980, 0x9FF)],
          "taml": [(0xB80, 0xBFF)], "thai": [(0xE00, 0xE7F)], "tibt": [(0xF00, 0xFFF)], "ethi": [(0x1200, 0x139F)],
          "mymr": [(0x1000, 0x109F)], "geor": [(0x10A0, 0x10FF)], "armn": [(0x530, 0x58F)], "khmr": [(0x1780, 0x17FF)]}

def api(**p):
    p["format"] = "json"; time.sleep(1)
    return json.load(urllib.request.urlopen(urllib.request.Request(
        "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p), headers=UA), timeout=60))

def script_share(path, script):
    try:
        t = subprocess.run(["pdftotext", "-l", "3", path, "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except Exception:
        return None
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 50: return None
    hit = sum(1 for c in letters if any(a <= ord(c) <= b for a, b in RANGES[script]))
    return hit / len(letters)

def main(source, plan, max_mb, seed):
    rng = random.Random(seed)
    out = os.path.join(CORPUS, "incoming", source); part = os.path.join(out, ".part")
    os.makedirs(part, exist_ok=True)
    for line in open(plan):
        if not line.strip() or line.startswith("#"): continue
        label, terms, count, script = line.rstrip("\n").split("\t"); count = int(count)
        try:
            d = api(action="query", list="search", srnamespace=6, srlimit=50,
                    srsearch=f"filemime:application/pdf filesize:<{int(max_mb * 1000)} {terms}")
        except Exception as e:
            print("search fail", label, e, file=sys.stderr); continue
        titles = [x["title"] for x in d["query"]["search"]]; rng.shuffle(titles)
        if not titles: print("no hits", label, file=sys.stderr); continue
        pages = []
        for i in range(0, min(len(titles), 50), 10):  # small batches: long non-ASCII title lists give HTTP 414
            try:
                pages += list(api(action="query", prop="imageinfo", iiprop="url|size|extmetadata",
                                  titles="|".join(titles[i:i + 10]))["query"]["pages"].values())
            except Exception as e:
                print("imageinfo fail", label, e, file=sys.stderr)
        got = 0
        for pg in pages:
            if got >= count: break
            ii = pg.get("imageinfo", [{}])[0]; u = ii.get("url")
            if not u: continue
            name = f"{label}__{pg['pageid']}.pdf"; dest = os.path.join(out, name)
            if os.path.exists(dest): continue
            tmp = os.path.join(part, name)
            r = subprocess.run(["curl", "-sS", "-L", "--fail", "--max-time", "600", "-A", UA["User-Agent"], "-o", tmp, u])
            time.sleep(1)
            if r.returncode or not open(tmp, "rb").read(1024).count(b"%PDF-"):
                if os.path.exists(tmp): os.remove(tmp)
                continue
            labels = []
            if script != "-":
                s = script_share(tmp, script)
                if s is None: labels.append(f"script-{script}-unverified")
                elif s < 0.2: os.remove(tmp); print("wrong script", round(s, 2), pg["title"], file=sys.stderr); continue
                else: labels.append(f"script-{script}")
            lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "?")
            title = pg["title"].replace("\t", " ")
            shutil.move(tmp, dest)
            with open(os.path.join(out, "_files.tsv"), "a") as f:
                f.write(f"{name}\t{u}\t{lic} (Wikimedia Commons: {title})\t{','.join(labels)}\n")
            print("ok", os.path.getsize(dest) // 1024, "KB", name, labels)
            got += 1

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
