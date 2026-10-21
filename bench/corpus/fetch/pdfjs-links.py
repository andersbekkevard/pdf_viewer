#!/usr/bin/env python3
"""Fetch documents that the pdf.js test suite links to (test/pdfs/*.link) into incoming/pdfjs-linked/.

usage: python3 -I pdfjs-links.py [--step N] [--max-mb 80]

Needs the sparse pdf.js checkout and test_manifest.json from adversarial-suites.sh
(in $PDFV_CORPUS_DIR/staging). Links are taken in name order; --step 3 takes every
third (phase 1), --step 1 takes all. Downloads run one at a time with a pause.
A file is kept if it has %PDF in its first KB; its md5 is compared with the
manifest and a mismatch is logged but kept. Results go to staging/pdfjs-linked.log.
"""
import argparse, hashlib, json, os, subprocess, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=int, default=1)
ap.add_argument("--max-mb", type=int, default=80)
a = ap.parse_args()
corpus = Path(os.environ.get("PDFV_CORPUS_DIR", Path.home() / ".local/share/pdf_viewer/corpus"))
staging = corpus / "staging"
dest = corpus / "incoming" / "pdfjs-linked"
dest.mkdir(parents=True, exist_ok=True)
tsv = dest / "_files.tsv"
log = open(staging / "pdfjs-linked.log", "a")
md5s = {Path(e["file"]).name: e["md5"] for e in json.load(open(staging / "pdfjs_test_manifest.json"))
        if e.get("link") and e.get("md5")}
seen = {l.split("\t")[0] for l in tsv.read_text().splitlines()} if tsv.exists() else set()
LIC = "unknown per file (third-party document linked from the mozilla/pdf.js test suite)"
for i, lf in enumerate(sorted((staging / "pdfjs/test/pdfs").glob("*.link"))):
    if i % a.step:
        continue
    name = lf.name[:-5]
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    if name in seen:
        continue
    url = lf.read_text().strip().splitlines()[0].strip()
    part = dest / (name + ".part")
    r = subprocess.run(["curl", "-sSL", "--fail", "--max-time", "300", "--max-filesize", str(a.max_mb << 20),
                        "-A", "pdf-viewer-test-corpus/1.0 (personal research)", "-o", str(part), url],
                       capture_output=True, text=True)
    status = "ok"
    if r.returncode != 0 or not part.exists():
        status = f"curl-{r.returncode} {r.stderr.strip()[:120]}"
    else:
        data = part.read_bytes()
        want = md5s.get(lf.name[:-5])
        if b"%PDF" not in data[:1024]:
            status = "not-pdf"
        elif want and hashlib.md5(data).hexdigest() != want:
            status = "md5-mismatch(kept)"
    if status.startswith(("curl", "not-pdf")):
        part.unlink(missing_ok=True)
    else:
        os.replace(part, dest / name)
        with open(tsv, "a") as out:
            out.write(f"{name}\t{url}\t{LIC}\n")
    print(f"{name}\t{status}\t{url}", file=log, flush=True)
    time.sleep(1.5)
print("done", file=log, flush=True)
