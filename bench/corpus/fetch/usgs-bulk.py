#!/usr/bin/env python3
"""Sample USGS GeoPDF maps from the public prd-tnm S3 bucket.

usage: python3 -I usgs-bulk.py <seed> <max_mb> <spec>...   spec = STATE:ustopo | STATE:hist/<scale>
For each spec, lists the prefix (first 1000 keys) and fetches one random *_geo.pdf.
"""
import os, random, re, subprocess, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
B = "https://prd-tnm.s3.amazonaws.com"
rng = random.Random(int(sys.argv[1])); max_mb = float(sys.argv[2])
for spec in sys.argv[3:]:
    st, kind = spec.split(":")
    prefix = f"StagedProducts/Maps/USTopo/PDF/{st}/" if kind == "ustopo" else f"StagedProducts/Maps/HistoricalTopo/PDF/{st}/{kind.split('/')[1]}/"
    xml = urllib.request.urlopen(f"{B}/?list-type=2&prefix={prefix}", timeout=60).read().decode()
    keys = [(k, int(s)) for k, s in re.findall(r"<Key>([^<]+_geo\.pdf)</Key>.*?<Size>(\d+)</Size>", xml) if int(s) < max_mb * 1e6]
    if not keys: print("none", spec, file=sys.stderr); continue
    k, _ = rng.choice(keys)
    subprocess.run([os.path.join(HERE, "fetch-one.sh"), "usgs-geopdf", f"{B}/{urllib.request.quote(k)}",
                    os.path.basename(k).replace(" ", "_"), "USGS map, US government work, public domain", str(int(max_mb))])
