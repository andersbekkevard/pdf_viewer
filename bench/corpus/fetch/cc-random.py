#!/usr/bin/env python3
"""Uniform random sample of CC-MAIN-2021-31-PDF-UNTRUNCATED members across many zips.

usage: python3 -I cc-random.py <n_zips> <per_zip> <max_mb> <seed>
Zips are drawn at random from 0000..7932; within each zip, members up to max_mb are
drawn at random. Files land in incoming/commoncrawl-cc-main-2021-31/ as
random<NNNN>__<member>. Uses zip-range-extract.py (HTTP range requests).
"""
import os, random, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
X = os.path.join(HERE, "zip-range-extract.py")
BASE = "https://digitalcorpora.s3.amazonaws.com/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/zipfiles"
LIC = "Common Crawl terms of use; copyright stays with each document's owner (research/testing use)"
n_zips, per_zip, max_mb, seed = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
rng = random.Random(seed)
for z in rng.sample(range(0, 7933), n_zips):
    url = f"{BASE}/{z // 1000 * 1000:04d}-{z // 1000 * 1000 + 999:04d}/{z:04d}.zip"
    out = subprocess.run([sys.executable, "-I", X, "list", url], capture_output=True, text=True)
    rows = [l.split("\t") for l in out.stdout.splitlines() if l.endswith("\t") is False]
    rows = [r for r in rows if len(r) == 3 and int(r[1]) <= max_mb * 1e6]
    if not rows:
        print("no members", url, file=sys.stderr); continue
    pick = [r[0] for r in rng.sample(rows, min(per_zip, len(rows)))]
    subprocess.run([sys.executable, "-I", "-u", X, "get", url, "commoncrawl-cc-main-2021-31", LIC, *pick],
                   env={**os.environ, "ZIP_PREFIX": f"random{z:04d}__"})
