#!/usr/bin/env python3
"""Sample arXiv PDFs across eras and categories through export.arxiv.org.

usage: python3 -I arxiv-sample.py <plan.tsv>
plan.tsv rows: label<TAB>search_query<TAB>from YYYYMMDD<TAB>to YYYYMMDD<TAB>count
One request every 3 seconds (API and PDF alike). Downloads go through fetch-one.sh
into incoming/arxiv/ named <label>__<id>.pdf. Also writes _arxiv-ids.tsv there
(id, label, title, primary category) for provenance.
"""
import os, subprocess, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.environ.get("PDFV_CORPUS_DIR", os.path.expanduser("~/.local/share/pdf_viewer/corpus"))
OUT = os.path.join(CORPUS, "incoming", "arxiv")
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
UA = "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"
LICENSE = "arXiv non-exclusive distribution licence or author CC licence (per paper)"

def api(q, frm, to, n):
    query = f"({q}) AND submittedDate:[{frm}0000 TO {to}2359]"
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": query, "start": 0, "max_results": n * 3, "sortBy": "submittedDate", "sortOrder": "ascending"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=60).read()
    time.sleep(3)
    root = ET.fromstring(data)
    out = []
    for e in root.findall("a:entry", NS):
        aid = e.find("a:id", NS).text.rsplit("/abs/", 1)[1]
        aid = aid.rsplit("v", 1)[0] if aid[-1].isdigit() and "v" in aid.split("/")[-1] else aid
        title = " ".join(e.find("a:title", NS).text.split())
        prim = e.find("x:primary_category", NS).get("term")
        out.append((aid, title, prim))
    return out

def main(plan):
    os.makedirs(OUT, exist_ok=True)
    for line in open(plan):
        if not line.strip() or line.startswith("#"):
            continue
        label, q, frm, to, n = line.rstrip("\n").split("\t")
        n = int(n)
        try:
            entries = api(q, frm, to, n)
        except Exception as ex:
            print("API FAIL", label, ex, file=sys.stderr); continue
        # spread picks over the result list instead of the first n
        step = max(1, len(entries) // max(n, 1))
        picks = entries[::step][:n]
        for aid, title, prim in picks:
            name = f"{label}__{aid.replace('/', '_')}.pdf"
            url = f"https://export.arxiv.org/pdf/{aid}"
            r = subprocess.run([os.path.join(HERE, "fetch-one.sh"), "arxiv", url, name, LICENSE, "100"],
                               env={**os.environ, "FETCH_SLEEP": "3"})
            if r.returncode == 0:
                with open(os.path.join(OUT, "_arxiv-ids.tsv"), "a") as f:
                    f.write(f"{aid}\t{label}\t{prim}\t{title}\n")

if __name__ == "__main__":
    main(sys.argv[1])
