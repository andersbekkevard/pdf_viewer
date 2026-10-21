#!/usr/bin/env python3
"""Select CC-MAIN-2021-31 members from the Tika metadata table.

usage: python3 -I cc-tika-select.py <tika-20230714.csv.gz> <seed> > candidates.tsv
Writes file_name<TAB>class rows for these classes (reservoir-sampled, seeded):
  xfa       has_xfa = true                                   (60)
  acroform  pdf_has_acroform_fields = true, no XFA           (60)
  annotcand pdf_incremental_updates >= 1, no form fields, in 60 seeded zips (1500; checked later for markup annotations)
  rtl       tika_eval_lang in ara, heb, fas, urd               (60)
The metadata table is
https://digitalcorpora.s3.amazonaws.com/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/metadata/tika-20230714.csv.gz
"""
import csv, gzip, random, sys
path, seed = sys.argv[1], int(sys.argv[2])
rng = random.Random(seed)
annot_zips = set(rng.sample(range(7933), 60))  # annotation candidates only from 60 zips, to bound central-directory fetches
want = {"xfa": 60, "acroform": 60, "annotcand": 1500, "rtl": 60}
res = {k: [] for k in want}; seen = {k: 0 for k in want}; done = set()
csv.field_size_limit(10**8)
with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        fn = r.get("file_name", "")
        if not fn.endswith(".pdf") or fn in done: continue
        done.add(fn)
        t = lambda k: (r.get(k) or "").lower() in ("true", "t", "1", "yes")
        try: inc = int(r.get("pdf_incremental_updates") or 0)
        except ValueError: inc = 0
        if t("has_xfa"): k = "xfa"
        elif t("pdf_has_acroform_fields"): k = "acroform"
        elif (r.get("tika_eval_lang") or "") in ("ara", "heb", "fas", "urd"): k = "rtl"
        elif inc >= 1 and fn[:4].isdigit() and int(fn[:4]) in annot_zips: k = "annotcand"
        else: continue
        seen[k] += 1
        if len(res[k]) < want[k]: res[k].append(fn)
        else:
            j = rng.randrange(seen[k])
            if j < want[k]: res[k][j] = fn
for k, v in res.items():
    print(f"# {k}: {seen[k]} matching, {len(v)} sampled", file=sys.stderr)
    for fn in v: print(f"{fn}\t{k}")
