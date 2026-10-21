#!/usr/bin/env python3
"""Failure rates of probed corpus documents, by source, label, feature and more.

Reads <corpus>/manifest.jsonl and <corpus>/probe/*.json (stdlib only, no PDF
is opened). A document counts once in every group it belongs to: under each
of its sources and labels, and under every detected feature.

`viewer fail` is the share of documents with at least one viewer class (all
classes except the PDFium-side and document-property ones listed in
NOT_VIEWER). Class columns give the share of documents with that class.

Usage:
    python3 bench/corpus/probe/summary.py [--corpus DIR] [--json OUT.json]
        [--by source,label,feature,fonts,pages,producer] [--min-n 3]
        [--examples N]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import sys

NOT_VIEWER = {"no-text", "pdfium-error", "pdfium-slow-page", "probe-error"}
ABBREV = {
    "convert-crash": "crash", "convert-refused": "refused", "convert-timeout": "ctime", "light-build-failed": "light",
    "covered-text-desync": "desync", "page-count-mismatch": "pgcnt", "page-size-mismatch": "pgsize",
    "viewer-load-failed": "load", "visual-diff-high": "vhigh", "glyph-drift": "drift", "font-substitution": "fsubst",
    "raster-blur": "blur", "blank-page": "blank", "ghost-glyphs": "ghost",
    "selection-occlusion": "occl", "tall-line-box": "tall", "text-loss": "txtloss",
    "no-text": "notext", "pdfium-error": "pdfium", "pdfium-slow-page": "pslow", "probe-error": "probe",
}


def corpus_dir(arg):
    raw = arg or os.environ.get("PDFV_CORPUS_DIR") or "~/.local/share/pdf_viewer/corpus"
    return pathlib.Path(raw).expanduser()


def page_bucket(n):
    if not n:
        return "unknown"
    for limit, name in ((1, "1"), (10, "2-10"), (40, "11-40"), (200, "41-200"), (1000, "201-1000")):
        if n <= limit:
            return name
    return ">1000"


def producer_family(row):
    p = (row.get("producer") or row.get("creator") or "").strip()
    if not p:
        return "(none)"
    p = re.sub(r"[®™©]", "", p)
    word = re.split(r"[\s/;,(]+", p)[0].lower()
    return word[:24] or "(none)"


def groups_for(row, dims):
    out = []
    if "source" in dims:
        out += [("source", s) for s in sorted({s["source"] for s in row["sources"]})]
    if "label" in dims:
        out += [("label", l) for l in row.get("labels", [])]
    if "feature" in dims:
        feats = [k for k, v in (row.get("features") or {}).items() if v]
        out += [("feature", f) for f in feats] or [("feature", "(none)")]
    if "fonts" in dims:
        fonts = row.get("fonts") or {}
        out += [("fonts", k) for k in ("type3", "type1", "truetype", "cid", "nonembedded") if fonts.get(k)]
        if fonts and not fonts.get("total"):
            out.append(("fonts", "(no fonts)"))
    if "pages" in dims:
        out.append(("pages", page_bucket(row.get("pages"))))
    if "producer" in dims:
        out.append(("producer", producer_family(row)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus")
    ap.add_argument("--json", help="also write the full aggregation as JSON here")
    ap.add_argument("--by", default="source,label,feature,fonts,pages,producer")
    ap.add_argument("--min-n", type=int, default=3, help="hide groups with fewer documents in the table")
    ap.add_argument("--examples", type=int, default=3, help="example sha256s per class in the JSON")
    args = ap.parse_args()
    root = corpus_dir(args.corpus)
    dims = args.by.split(",")
    rows = {}
    for line in (root / "manifest.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["sha256"]] = r
    results = {}
    for path in (root / "probe").glob("*.json"):
        try:
            res = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if res.get("sha256") in rows:
            results[res["sha256"]] = res

    all_classes = collections.Counter()
    for res in results.values():
        all_classes.update(res.get("classes", []))
    classes = [c for c, _ in all_classes.most_common()]

    agg: dict = collections.defaultdict(lambda: {"n": 0, "viewer_fail": 0, "classes": collections.Counter()})
    examples = collections.defaultdict(list)
    for sha, res in results.items():
        row = rows[sha]
        cls = set(res.get("classes", []))
        viewer_fail = bool(cls - NOT_VIEWER)
        keys = [("all", "all")] + groups_for(row, dims)
        for key in keys:
            g = agg[key]
            g["n"] += 1
            g["viewer_fail"] += viewer_fail
            g["classes"].update(cls)
        for c in cls:
            if len(examples[c]) < args.examples:
                name = row["sources"][0]["source"] + "/" + row["sources"][0]["filename"]
                examples[c].append({"sha256": sha, "name": name, "summary": res.get("summary")})

    print(f"{len(results)} probed of {len(rows)} manifest rows; "
          f"pipeline {next(iter(results.values()))['pipeline'] if results else '-'}")
    print("Columns: n documents, viewer fail % (any viewer class), then % of documents per class.")
    print("Legend: " + ", ".join(f"{ABBREV.get(c, c)}={c}" for c in classes))
    header = ["group", "n", "fail%"] + [ABBREV.get(c, c) for c in classes]
    for dim in ["all"] + dims:
        items = sorted(((k, v) for k, v in agg.items() if k[0] == dim and (v["n"] >= args.min_n or dim == "all")),
                       key=lambda kv: (-kv[1]["n"], kv[0][1]))
        if not items:
            continue
        print(f"\n== by {dim}")
        table = [header]
        for (d, name), g in items:
            table.append([name[:34], str(g["n"]), f"{100 * g['viewer_fail'] / g['n']:.0f}"]
                         + [(f"{100 * g['classes'][c] / g['n']:.0f}" if g["classes"][c] else ".") for c in classes])
        widths = [max(len(r[i]) for r in table) for i in range(len(header))]
        for r in table:
            print("  ".join(r[i].ljust(widths[i]) if i == 0 else r[i].rjust(widths[i]) for i in range(len(r))))

    if args.json:
        out = {
            "probed": len(results), "manifest_rows": len(rows), "classes": dict(all_classes),
            "groups": [{"dim": d, "group": name, "n": g["n"], "viewer_fail": g["viewer_fail"],
                        "viewer_fail_rate": round(g["viewer_fail"] / g["n"], 4),
                        "classes": dict(g["classes"]),
                        "class_rates": {c: round(k / g["n"], 4) for c, k in g["classes"].items()}}
                       for (d, name), g in sorted(agg.items())],
            "examples": examples,
        }
        pathlib.Path(args.json).write_text(json.dumps(out, indent=1))
        print(f"\nJSON: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
