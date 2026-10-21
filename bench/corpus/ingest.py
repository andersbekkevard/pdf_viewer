#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pypdfium2==5.14.0"]
# ///
"""Ingest downloaded PDFs into the content-addressed corpus and its manifest.

Reads every incoming/<source>/_files.tsv (filename, url, license[, labels])
under the corpus directory. Only files with a row are ingested: downloaders
append a row after a file is complete. Each file is hashed (sha256), copied
to files/<sha[0:2]>/<sha>.pdf (an APFS clone, so no extra space), and gets one
row in manifest.jsonl. A file seen under several names or sources is stored
once; its provenance entries merge into the row's `sources` list.

PDF facts (pages, version, fonts, features) come from PDFium and pdffonts, in
a separate `python -I` process per file with a time limit, because corpus
files are untrusted and some are built to crash parsers. A file PDFium cannot
open still gets a row, with `error` set.

Idempotent and incremental: hashes are remembered by (path, size, mtime) in
ingest-state.json, and facts are only computed for rows that lack them (or
when FACTS_VERSION changes, or with --refresh).

Usage:
    uv run bench/corpus/ingest.py [--corpus DIR] [--jobs 6] [--source NAME ...]
                                  [--refresh] [--limit N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

FACTS_VERSION = 2
FACTS_TIMEOUT = 120          # seconds per file for the PDFium + pdffonts worker
SAMPLE_PAGES = 12            # pages inspected for text/object features
MAX_OBJECTS_PER_PAGE = 40000 # bound on page-object walks (pathological pages)
HERE = pathlib.Path(__file__).resolve()


def corpus_dir(arg: str | None) -> pathlib.Path:
    raw = arg or os.environ.get("PDFV_CORPUS_DIR") or "~/.local/share/pdf_viewer/corpus"
    return pathlib.Path(raw).expanduser()


# --------------------------------------------------------------------------
# Facts worker: runs as `python -I ingest.py --facts <pdf>`, prints one JSON.
# --------------------------------------------------------------------------

CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿ｦ-ﾟ]")
RTL_RE = re.compile(r"[֐-׿؀-ۿ܀-ݏݐ-ݿࢠ-ࣿיִ-﷿ﹰ-﻿]")


def sample_indices(n: int, k: int) -> list[int]:
    if n <= k:
        return list(range(n))
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def pdffonts_classes(pdf: str) -> dict | None:
    try:
        out = subprocess.run(["pdffonts", pdf], capture_output=True, text=True,
                             timeout=60, errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    lines = out.stdout.splitlines()
    dash = next((i for i, l in enumerate(lines) if l.startswith("----")), None)
    if dash is None:
        return None
    # Column widths from the dashes row: name, type, encoding, emb, sub, uni, object ID.
    widths = [len(c) for c in lines[dash].split(" ")]
    starts, pos = [], 0
    for w in widths:
        starts.append(pos)
        pos += w + 1
    counts = {"type3": 0, "type1": 0, "truetype": 0, "cid": 0, "other": 0, "nonembedded": 0, "total": 0}
    for line in lines[dash + 1:]:
        if len(starts) < 4 or not line.strip():
            continue
        ftype = line[starts[1]:starts[2]].strip()
        emb = line[starts[3]:starts[3] + widths[3]].strip()
        counts["total"] += 1
        if ftype.startswith("CID"):
            counts["cid"] += 1
        elif ftype.startswith("Type 3"):
            counts["type3"] += 1
        elif ftype.startswith("Type 1"):
            counts["type1"] += 1
        elif ftype.startswith("TrueType"):
            counts["truetype"] += 1
        else:
            counts["other"] += 1
        if emb == "no":
            counts["nonembedded"] += 1
    return counts


def pdfinfo_facts(pdf: str) -> dict:
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True,
                             timeout=60, errors="replace")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"pdfinfo_error": str(exc)[:200]}
    info = {}
    for line in out.stdout.splitlines():
        key, _, value = line.partition(":")
        info[key.strip()] = value.strip()
    facts = {}
    if info.get("Pages", "").isdigit():
        facts["pages"] = int(info["Pages"])
    if info.get("PDF version"):
        facts["pdf_version"] = info["PDF version"]
    for src, dst in (("Producer", "producer"), ("Creator", "creator")):
        if info.get(src):
            facts[dst] = info[src]
    if info.get("Encrypted"):
        facts["encrypted"] = not info["Encrypted"].startswith("no")
    if out.returncode != 0:
        facts["pdfinfo_error"] = (out.stderr or "").strip()[:300]
    return facts


def extract_facts(pdf: str) -> dict:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    facts: dict = {"facts_version": FACTS_VERSION}
    facts["fonts"] = pdffonts_classes(pdf)
    try:
        doc = pdfium.PdfDocument(pdf)
    except Exception as exc:  # PdfiumError: password, format, file
        facts.update(pdfinfo_facts(pdf))
        facts["error"] = f"pdfium-open: {exc}"[:300]
        return facts
    n = len(doc)
    facts["pages"] = n
    v = doc.get_version()
    facts["pdf_version"] = f"{v // 10}.{v % 10}" if v else None
    meta = doc.get_metadata_dict(skip_empty=True)
    facts["producer"] = meta.get("Producer")
    facts["creator"] = meta.get("Creator")
    facts["encrypted"] = raw.FPDF_GetSecurityHandlerRevision(doc.raw) >= 0
    form_type = raw.FPDF_GetFormType(doc.raw)

    sizes: dict[tuple, int] = {}
    rotated = False
    bad_pages = 0
    for i in range(n):
        try:
            w, h = doc.get_page_size(i)
        except Exception:
            bad_pages += 1
            continue
        key = (round(w, 1), round(h, 1))
        sizes[key] = sizes.get(key, 0) + 1
    page_sizes = sorted(({"w": w, "h": h, "count": c} for (w, h), c in sizes.items()),
                        key=lambda d: -d["count"])
    facts["page_sizes"] = page_sizes[:20]
    if bad_pages:
        facts["unreadable_pages"] = bad_pages
    distinct = []
    for d in page_sizes:
        if not any(abs(d["w"] - e["w"]) <= 2 and abs(d["h"] - e["h"]) <= 2 for e in distinct):
            distinct.append(d)

    feats = {k: False for k in ("scanned", "invisible_text", "rotated", "mixed_sizes", "forms",
                                "annotations", "ocg_layers", "transparency", "jbig2", "cjk", "rtl")}
    feats["mixed_sizes"] = len(distinct) > 1
    # An empty /AcroForm dictionary is common (iText, Word); count forms only
    # for XFA or when a sampled page carries widget annotations (below).
    feats["forms"] = form_type in (raw.FORMTYPE_XFA_FULL, raw.FORMTYPE_XFA_FOREGROUND)
    stats = {"sampled_pages": 0, "chars": 0, "cjk_chars": 0, "rtl_chars": 0, "links": 0,
             "annots": {}, "scan_like_pages": 0, "invisible_text_objs": 0, "text_objs": 0,
             "image_objs": 0, "path_objs": 0, "objects_truncated": False, "form_type": form_type}
    textless_pages = 0
    for i in sample_indices(n, SAMPLE_PAGES):
        try:
            page = doc[i]
        except Exception:
            continue
        stats["sampled_pages"] += 1
        if page.get_rotation():
            rotated = True
        pw, ph = page.get_size()
        area = max(pw * ph, 1.0)
        if raw.FPDFPage_HasTransparency(page.raw):
            feats["transparency"] = True
        # Text.
        try:
            tp = page.get_textpage()
            text = tp.get_text_range()
            tp.close()
        except Exception:
            text = ""
        visible = len(re.sub(r"\s+", "", text))
        stats["chars"] += visible
        stats["cjk_chars"] += len(CJK_RE.findall(text))
        stats["rtl_chars"] += len(RTL_RE.findall(text))
        if visible < 20:
            textless_pages += 1
        # Page objects.
        visible_text_objs = 0
        big_image = False
        count = 0
        for obj in page.get_objects(max_depth=4):
            count += 1
            if count > MAX_OBJECTS_PER_PAGE:
                stats["objects_truncated"] = True
                break
            t = obj.type
            if t == raw.FPDF_PAGEOBJ_TEXT:
                stats["text_objs"] += 1
                if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == raw.FPDF_TEXTRENDERMODE_INVISIBLE:
                    stats["invisible_text_objs"] += 1
                else:
                    visible_text_objs += 1
            elif t == raw.FPDF_PAGEOBJ_IMAGE:
                stats["image_objs"] += 1
                try:
                    l, b, r, tt = obj.get_bounds()
                    if (r - l) * (tt - b) >= 0.6 * area:
                        big_image = True
                    for k in range(raw.FPDFImageObj_GetImageFilterCount(obj.raw)):
                        size = raw.FPDFImageObj_GetImageFilter(obj.raw, k, None, 0)
                        buf = (raw.c_char * size)()
                        raw.FPDFImageObj_GetImageFilter(obj.raw, k, buf, size)
                        if b"JBIG2" in bytes(buf):
                            feats["jbig2"] = True
                except Exception:
                    pass
            elif t == raw.FPDF_PAGEOBJ_PATH:
                stats["path_objs"] += 1
            if not feats["ocg_layers"]:
                for m in range(raw.FPDFPageObj_CountMarks(obj.raw)):
                    mark = raw.FPDFPageObj_GetMark(obj.raw, m)
                    blen = raw.c_ulong(0)
                    raw.FPDFPageObjMark_GetName(mark, None, 0, blen)
                    if blen.value:
                        nb = (raw.c_ushort * (blen.value // 2 + 1))()
                        raw.FPDFPageObjMark_GetName(mark, nb, blen.value, blen)
                        name = bytes(nb)[:blen.value].decode("utf-16-le", "replace").rstrip("\x00")
                        if name == "OC":
                            feats["ocg_layers"] = True
                            break
        if big_image and visible_text_objs < 5:
            stats["scan_like_pages"] += 1
        # Annotations.
        for a in range(raw.FPDFPage_GetAnnotCount(page.raw)):
            annot = raw.FPDFPage_GetAnnot(page.raw, a)
            sub = raw.FPDFAnnot_GetSubtype(annot)
            raw.FPDFPage_CloseAnnot(annot)
            if sub == raw.FPDF_ANNOT_LINK:
                stats["links"] += 1
                continue
            stats["annots"][str(sub)] = stats["annots"].get(str(sub), 0) + 1
            if sub == raw.FPDF_ANNOT_WIDGET:
                feats["forms"] = True
            elif sub != raw.FPDF_ANNOT_POPUP:
                feats["annotations"] = True
        page.close()
    if not rotated and n <= 3000:
        for i in range(n):
            try:
                page = doc[i]
            except Exception:
                continue
            r = page.get_rotation()
            page.close()
            if r:
                rotated = True
                break
    feats["rotated"] = rotated
    sp = max(stats["sampled_pages"], 1)
    feats["scanned"] = stats["scan_like_pages"] * 2 > sp or (
        textless_pages == stats["sampled_pages"] and stats["image_objs"] >= stats["sampled_pages"] > 0)
    feats["invisible_text"] = stats["invisible_text_objs"] > 0
    feats["cjk"] = stats["cjk_chars"] >= 20 or stats["cjk_chars"] > 0.1 * max(stats["chars"], 1)
    feats["rtl"] = stats["rtl_chars"] >= 20 or stats["rtl_chars"] > 0.1 * max(stats["chars"], 1)
    stats["chars_per_page"] = round(stats["chars"] / sp, 1)
    facts["features"] = feats
    facts["feature_stats"] = stats
    doc.close()
    return facts


def facts_worker(pdf: str) -> None:
    try:
        facts = extract_facts(pdf)
    except Exception as exc:
        facts = {"facts_version": FACTS_VERSION, "error": f"facts: {type(exc).__name__}: {exc}"[:300]}
    sys.stdout.write(json.dumps(facts) + "\n")


def run_facts(pdf: pathlib.Path) -> dict:
    """Facts in an isolated `python -I` process with a time limit."""
    t0 = time.monotonic()
    try:
        out = subprocess.run([sys.executable, "-I", str(HERE), "--facts", str(pdf)],
                             capture_output=True, text=True, timeout=FACTS_TIMEOUT,
                             stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        facts = pdfinfo_facts(str(pdf))
        facts.update({"facts_version": FACTS_VERSION, "error": f"facts-timeout after {FACTS_TIMEOUT}s"})
        return facts
    line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    try:
        facts = json.loads(line)
    except json.JSONDecodeError:
        facts = pdfinfo_facts(str(pdf))
        facts.update({"facts_version": FACTS_VERSION,
                      "error": f"facts-crash: exit {out.returncode}: {out.stderr.strip()[-200:]}"})
    facts["facts_seconds"] = round(time.monotonic() - t0, 2)
    return facts


# --------------------------------------------------------------------------
# Ingest driver.
# --------------------------------------------------------------------------

def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_listing(source_dir: pathlib.Path) -> list[dict]:
    tsv = source_dir / "_files.tsv"
    rows = []
    try:
        text = tsv.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    # The last line may still be being written; ignore a line without newline.
    lines = text.split("\n")
    if not text.endswith("\n"):
        lines = lines[:-1]
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 3 or cols[0] == "filename":
            continue
        name = cols[0].strip()
        if "/" in name or name.startswith("."):
            continue  # stay inside the source directory
        labels = [l.strip() for l in cols[3].split(",")] if len(cols) > 3 else []
        rows.append({"filename": name, "url": cols[1].strip(), "license": cols[2].strip(),
                     "labels": [l for l in labels if l]})
    return rows


def labels_for(source: str, entry: dict) -> list[str]:
    labels = list(entry["labels"])
    stem = entry["filename"]
    if "__" in stem:
        prefix = stem.split("__", 1)[0]
        if prefix and len(prefix) <= 60:
            labels.append(prefix)
    return labels


def load_jsonl(path: pathlib.Path) -> dict[str, dict]:
    rows = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["sha256"]] = row
    return rows


def write_atomic(path: pathlib.Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_manifest(path: pathlib.Path, rows: dict[str, dict]) -> None:
    write_atomic(path, "".join(json.dumps(r, sort_keys=False) + "\n" for r in rows.values()))


def store_copy(src: pathlib.Path, dst: pathlib.Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp.{os.getpid()}")
    # cp -c makes an APFS clone (no extra space); plain copy as a fallback.
    if subprocess.run(["cp", "-c", str(src), str(tmp)], capture_output=True).returncode != 0:
        subprocess.run(["cp", str(src), str(tmp)], check=True)
    os.chmod(tmp, 0o444)
    os.replace(tmp, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", help=argparse.SUPPRESS)
    ap.add_argument("--corpus", help="corpus dir (default $PDFV_CORPUS_DIR or ~/.local/share/pdf_viewer/corpus)")
    ap.add_argument("--jobs", type=int, default=6, help="parallel facts workers (default 6)")
    ap.add_argument("--source", action="append", help="only these incoming/<source> dirs")
    ap.add_argument("--refresh", action="store_true", help="recompute facts for every row")
    ap.add_argument("--limit", type=int, help="ingest at most N new files (testing)")
    args = ap.parse_args()
    if args.facts:
        facts_worker(args.facts)
        return 0

    root = corpus_dir(args.corpus)
    incoming = root / "incoming"
    manifest_path = root / "manifest.jsonl"
    state_path = root / "ingest-state.json"
    lock = root / ".ingest.lock"
    root.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError:
        print(f"ingest: another ingest holds {lock} (remove it if no ingest is running)", file=sys.stderr)
        return 1
    try:
        rows = load_jsonl(manifest_path)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        new_files = 0
        listed = 0
        missing = 0
        sources = sorted(p for p in incoming.iterdir() if p.is_dir()) if incoming.exists() else []
        if args.source:
            sources = [p for p in sources if p.name in set(args.source)]
        t0 = time.monotonic()
        for sdir in sources:
            for entry in read_listing(sdir):
                if args.limit is not None and new_files >= args.limit:
                    break
                path = sdir / entry["filename"]
                try:
                    st = path.stat()
                except OSError:
                    missing += 1
                    continue
                listed += 1
                key = f"{sdir.name}/{entry['filename']}"
                cached = state.get(key)
                if cached and cached["size"] == st.st_size and cached["mtime_ns"] == st.st_mtime_ns:
                    sha = cached["sha"]
                else:
                    sha = sha256_file(path)
                    state[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha": sha}
                store_copy(path, root / "files" / sha[:2] / f"{sha}.pdf")
                row = rows.get(sha)
                if row is None:
                    row = rows[sha] = {"sha256": sha, "bytes": st.st_size, "sources": [], "labels": []}
                    new_files += 1
                prov = {"source": sdir.name, "url": entry["url"], "license": entry["license"],
                        "filename": entry["filename"]}
                if prov not in row["sources"]:
                    row["sources"].append(prov)
                for label in labels_for(sdir.name, entry):
                    if label not in row["labels"]:
                        row["labels"].append(label)
        write_atomic(state_path, json.dumps(state))
        write_manifest(manifest_path, rows)
        todo = [r for r in rows.values()
                if args.refresh or r.get("facts_version") != FACTS_VERSION]
        print(f"ingest: {listed} listed files ({missing} listed but absent), {new_files} new, "
              f"{len(rows)} unique PDFs; facts to compute: {len(todo)} "
              f"(hashing took {time.monotonic() - t0:.1f}s)", flush=True)
        done = 0
        fact_keys = ("pages", "pdf_version", "producer", "creator", "encrypted", "page_sizes", "fonts",
                     "features", "feature_stats", "error", "facts_version", "facts_seconds", "pdfinfo_error",
                     "unreadable_pages")
        with cf.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 8))) as pool:
            futures = {pool.submit(run_facts, root / "files" / r["sha256"][:2] / f"{r['sha256']}.pdf"): r
                       for r in todo}
            for fut in cf.as_completed(futures):
                row = futures[fut]
                facts = fut.result()
                for k in fact_keys:
                    row.pop(k, None)
                for k in fact_keys:
                    if k in facts:
                        row[k] = facts[k]
                row.setdefault("tier", None)
                done += 1
                if done % 100 == 0:
                    write_manifest(manifest_path, rows)
                    print(f"ingest: facts {done}/{len(todo)}", flush=True)
        write_manifest(manifest_path, rows)
        errors = sum(1 for r in rows.values() if r.get("error"))
        print(f"ingest: done; {len(rows)} rows, {errors} with errors, {time.monotonic() - t0:.0f}s")
    finally:
        lock.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
