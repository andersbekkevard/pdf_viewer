#!/usr/bin/env python3
"""Assign corpus tiers from probe results and write them to manifest.jsonl.

`tier` holds the smallest tier a document belongs to; tiers nest, so a `t0`
document is also in T1 and T2. Every probed row is at least `t2`; rows not
yet probed get `null`.

- T0: one small document per failure class and per detected feature (plus
  font classes), chosen greedily so one document can cover several, and one
  passing document per owner document type as a control.
- T1, when the owner's own documents (source `own-local`) are probed: T0,
  then from those documents up to two per (course:, kind:) label pair (a
  failing one first, then a passing one), every own document of 200+ pages,
  and up to 12 own documents without a course label, failing ones first; then
  a small top-up per document type from the public sources, and two documents
  per class (own documents preferred).
- T1 otherwise: T0 plus a stratified sample weighted toward the owner's document types
  (slides, papers, problem sets, lecture notes, long textbooks), then other
  real-world documents and adversarial test-suite files. Within each type the
  pick first covers every failure class present, then alternates failing and
  passing documents across labels and sources. Every class gets at least two
  T1 documents when the corpus has two. Expensive documents (probe time over
  90 s) are only taken to cover a class.
- T2: every other probed document.

Stdlib only; no PDF is opened. It takes the ingest lock, so it never writes
the manifest at the same time as ingest.py.

Usage: python3 bench/corpus/probe/tiers.py [--corpus DIR] [--dry-run] [--t1-target 140]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import sys
import time

NOT_FAILURE = {"no-text", "probe-error"}  # no-text is a document property; probe-error is ours
TEST_SUITES = {"pdfium", "pdfium-templates", "pdfjs", "pdfjs-linked", "poppler-test", "qpdf",
               "verapdf-corpus", "safedocs-issue-trackers", "safedocs-unsafe", "synth"}
QUOTAS = {"slides": 20, "paper": 20, "problem-set": 15, "notes": 8, "textbook": 12,
          "real-world": 15, "adversarial": 10}
# With the owner's own documents (source OWN_SOURCE) probed, T1 is built from
# them first and the public quotas shrink to a top-up.
OWN_SOURCE = "own-local"
OWN_PER_COURSE_KIND = 2        # documents per (course:, kind:) label pair
OWN_LONG_PAGES = 200           # own documents this long are all taken (textbooks)
OWN_OTHER_QUOTA = 12           # own documents without a course label (e.g. viewer cache)
TOPUP_QUOTAS = {"slides": 5, "paper": 6, "problem-set": 4, "notes": 3, "textbook": 3,
                "real-world": 6, "adversarial": 6}
EXPENSIVE_SECONDS = 90


def corpus_dir(arg):
    raw = arg or os.environ.get("PDFV_CORPUS_DIR") or "~/.local/share/pdf_viewer/corpus"
    return pathlib.Path(raw).expanduser()


def doc_type(row: dict) -> str:
    labels = " ".join(row.get("labels", [])).lower()
    sources = {s["source"] for s in row["sources"]}
    pages = row.get("pages") or 0
    sizes = row.get("page_sizes") or []
    if re.search(r"slides|beamer|ppt", labels):
        return "slides"
    if re.search(r"pset|exam|assign|\blab|homework|quiz|problem", labels):
        return "problem-set"
    if re.search(r"notes|readings|handwritten", labels):
        return "notes"
    if "arxiv" in sources or "arxiv-" in labels:
        return "paper"
    if pages >= 200 and (sources & {"openstax", "internet-archive", "ctan-docs"} or "book" in labels):
        return "textbook"
    if sources <= TEST_SUITES:
        return "adversarial"
    if sizes and sizes[0]["w"] > 1.2 * sizes[0]["h"] and pages >= 8:
        return "slides"
    if pages >= 300:
        return "textbook"
    return "real-world"


def stable(sha: str, salt: str = "") -> str:
    return hashlib.sha256((salt + sha).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus")
    ap.add_argument("--dry-run", action="store_true", help="print the selection, do not write")
    args = ap.parse_args()
    root = corpus_dir(args.corpus)
    manifest = root / "manifest.jsonl"
    lock = root / ".ingest.lock"
    for _ in range(600):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(1)
    else:
        print("tiers: ingest lock held for 10 minutes; giving up", file=sys.stderr)
        return 1
    try:
        rows = [json.loads(l) for l in manifest.read_text().splitlines() if l.strip()]
        by_sha = {r["sha256"]: r for r in rows}
        probes = {}
        probed: set = set()
        for path in (root / "probe").glob("*.json"):
            try:
                res = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if res.get("sha256") in by_sha:
                probed.add(res["sha256"])
                if "probe-error" not in res.get("classes", []):
                    probes[res["sha256"]] = res

        def classes(sha):
            return set(probes[sha].get("classes", []))

        def traits(sha):
            row = by_sha[sha]
            t = {f"feature:{k}" for k, v in (row.get("features") or {}).items() if v}
            fonts = row.get("fonts") or {}
            t |= {f"fonts:{k}" for k in ("type3", "cid", "nonembedded", "truetype", "type1") if fonts.get(k)}
            if row.get("encrypted"):
                t.add("feature:encrypted")
            return t

        def cost(sha):
            row = by_sha[sha]
            return (probes[sha].get("seconds", 999), row.get("pages") or 0, row.get("bytes", 0))

        types = {sha: doc_type(by_sha[sha]) for sha in probes}

        # T0: greedy cover of every class and trait, smallest documents first.
        needs = collections.Counter()
        for sha in probes:
            needs.update(c for c in classes(sha) if c not in NOT_FAILURE)
            needs.update(traits(sha))
        t0: list[str] = []
        covered: set = set()
        small = sorted((s for s in probes if (by_sha[s].get("pages") or 0) <= 20), key=cost)
        small += sorted((s for s in probes if (by_sha[s].get("pages") or 0) > 20), key=cost)
        for need, _ in sorted(needs.items(), key=lambda kv: kv[1]):  # rarest first
            if need in covered:
                continue
            for sha in small:
                have = (classes(sha) - NOT_FAILURE) | traits(sha)
                if need in have:
                    t0.append(sha)
                    covered |= have
                    break
        for kind in ("slides", "paper", "problem-set", "notes", "textbook"):
            ok = sorted((s for s in probes if types[s] == kind and not (classes(s) - NOT_FAILURE)), key=cost)
            if ok and ok[0] not in t0:
                t0.append(ok[0])

        # T1: T0, then the owner's own documents when present, then quotas per
        # document type from the public sources.
        t1 = list(t0)
        chosen = set(t1)
        own = [s for s in probes if any(x["source"] == OWN_SOURCE for x in by_sha[s]["sources"])]

        def label_value(sha, prefix):
            return next((l[len(prefix):] for l in by_sha[sha].get("labels", []) if l.startswith(prefix)), None)

        if own:
            cells = collections.defaultdict(list)
            for s in own:
                course, kind = label_value(s, "course:"), label_value(s, "kind:")
                if (by_sha[s].get("pages") or 0) >= OWN_LONG_PAGES:
                    cells[("long", None)].append(s)
                elif course:
                    cells[(course, kind)].append(s)
                else:
                    cells[("other", kind)].append(s)
            for key, members in sorted(cells.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
                failing = sorted((s for s in members if classes(s) - NOT_FAILURE), key=cost)
                passing = sorted((s for s in members if not classes(s) - NOT_FAILURE), key=cost)
                if key[0] == "long":
                    take = members
                elif key[0] == "other":
                    take = []  # filled below, spread over kinds
                else:
                    take = (failing[:1] + passing[:1] + failing[1:])[:OWN_PER_COURSE_KIND]
                for s in take:
                    if s not in chosen:
                        t1.append(s)
                        chosen.add(s)
            others = [s for key, m in sorted(cells.items(), key=lambda kv: str(kv[0])) if key[0] == "other" for s in m]
            others.sort(key=lambda s: (s in chosen, not (classes(s) - NOT_FAILURE), stable(s, "own")))
            for s in others[:OWN_OTHER_QUOTA]:
                if s not in chosen:
                    t1.append(s)
                    chosen.add(s)
        quotas = TOPUP_QUOTAS if own else QUOTAS
        for kind, quota in quotas.items():
            pool = [s for s in probes if types[s] == kind and s not in chosen and s not in own]
            picked = []
            # 1. one document per failure class present in this type.
            present = collections.Counter(c for s in pool for c in classes(s) - NOT_FAILURE)
            for cls, _ in sorted(present.items(), key=lambda kv: kv[1]):
                if len(picked) >= quota:
                    break
                if any(cls in classes(s) for s in picked):
                    continue
                cands = sorted((s for s in pool if cls in classes(s) and s not in picked), key=cost)
                if cands:
                    picked.append(cands[0])
            # 2. fill: alternate failing and passing, round-robin over labels/sources.
            def group(s):
                row = by_sha[s]
                return (row.get("labels") or [row["sources"][0]["source"]])[0]
            fail = sorted((s for s in pool if s not in picked and classes(s) - NOT_FAILURE
                           and probes[s].get("seconds", 0) <= EXPENSIVE_SECONDS), key=lambda s: stable(s, kind))
            ok = sorted((s for s in pool if s not in picked and not (classes(s) - NOT_FAILURE)
                         and probes[s].get("seconds", 0) <= EXPENSIVE_SECONDS), key=lambda s: stable(s, kind))
            used_groups = collections.Counter(group(s) for s in picked)
            for lst in (fail, ok):
                lst.sort(key=lambda s: used_groups[group(s)])
            turn = 0
            while len(picked) < quota and (fail or ok):
                lst = (fail if turn % 3 != 2 else ok) or fail or ok   # two failing to one passing
                # take the candidate from the least used label/source group
                lst.sort(key=lambda s: used_groups[group(s)])
                s = lst.pop(0)
                picked.append(s)
                used_groups[group(s)] += 1
                turn += 1
            t1 += picked
            chosen |= set(picked)
        # 3. at least two T1 documents per class.
        all_classes = collections.Counter(c for s in probes for c in classes(s) - NOT_FAILURE)
        own_set = set(own)
        for cls in all_classes:
            have = [s for s in t1 if cls in classes(s)]
            cands = sorted((s for s in probes if cls in classes(s) and s not in chosen),
                           key=lambda s: (s not in own_set, cost(s)))
            while len(have) < 2 and cands:
                s = cands.pop(0)
                t1.append(s)
                chosen.add(s)
                have.append(s)

        # T2 is every probed row; rows not yet probed get null so a later run
        # can probe them and re-run this script.
        tier = {sha: ("t2" if sha in probed else None) for sha in by_sha}
        for s in t1:
            tier[s] = "t1"
        for s in t0:
            tier[s] = "t0"

        def report(name, members):
            kinds = collections.Counter(types[s] for s in members)
            cls = collections.Counter(c for s in members for c in classes(s))
            secs = sum(probes[s].get("seconds", 0) for s in members)
            print(f"{name}: {len(members)} documents, probe time {secs / 60:.1f} min single-worker")
            print("  types:   " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()))
            print("  classes: " + ", ".join(f"{k} {v}" for k, v in cls.most_common()))
        if own:
            own_t1 = [s for s in t1 if s in own_set]
            print(f"own documents: {len(own)} probed, {len(own_t1)} in T1")
        report("T0", t0)
        report("T1 (includes T0)", t1)
        print(f"T2: {len(probed)} probed documents; {len(by_sha) - len(probed)} unprobed rows get tier null")
        missing = [c for c in all_classes if not any(c in classes(s) for s in t0)]
        if missing:
            print("T0 lacks classes: " + ", ".join(missing))
        if args.dry_run:
            return 0
        for r in rows:
            r["tier"] = tier[r["sha256"]]
        tmp = manifest.with_name(f".{manifest.name}.tmp.{os.getpid()}")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.replace(tmp, manifest)
        print(f"tiers: wrote {manifest}")
    finally:
        lock.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
