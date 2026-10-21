#!/usr/bin/env python3
"""Fetch CC-MAIN-2021-31 members selected by cc-tika-select.py into incoming/forms-annotations/.

usage: uv run --no-project --with pypdfium2 python -I cc-forms-annots.py <candidates.tsv> <scratch_dir> <max_annot_files> <max_mb>
xfa, acroform and rtl rows are kept as they are (rtl goes to incoming/commoncrawl-cc-main-2021-31
with prefix rtl__). annotcand rows are downloaded to scratch_dir, opened with PDFium, and kept
only if some page (first 80) has a markup annotation (Text, FreeText, Line, Square, Circle,
Polygon, PolyLine, Highlight, Underline, Squiggly, StrikeOut, Stamp, Caret, Ink, FileAttachment);
the others are deleted. Rows carry a labels column (cc-xfa, cc-acroform, annot-<subtypes>).
"""
import importlib.util, os, shutil, sys, zlib
import pypdfium2 as pdfium
import pypdfium2.raw as raw
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("zre", os.path.join(HERE, "zip-range-extract.py"))
zre = importlib.util.module_from_spec(spec); spec.loader.exec_module(zre)
CORPUS = os.environ.get("PDFV_CORPUS_DIR", os.path.expanduser("~/.local/share/pdf_viewer/corpus"))
BASE = "https://digitalcorpora.s3.amazonaws.com/corpora/files/CC-MAIN-2021-31-PDF-UNTRUNCATED/zipfiles"
LIC = "Common Crawl terms of use; copyright stays with each document's owner (research/testing use)"
MARKUP = {raw.FPDF_ANNOT_TEXT: "text", raw.FPDF_ANNOT_FREETEXT: "freetext", raw.FPDF_ANNOT_LINE: "line", raw.FPDF_ANNOT_SQUARE: "square",
          raw.FPDF_ANNOT_CIRCLE: "circle", raw.FPDF_ANNOT_POLYGON: "polygon", raw.FPDF_ANNOT_POLYLINE: "polyline",
          raw.FPDF_ANNOT_HIGHLIGHT: "highlight", raw.FPDF_ANNOT_UNDERLINE: "underline", raw.FPDF_ANNOT_SQUIGGLY: "squiggly",
          raw.FPDF_ANNOT_STRIKEOUT: "strikeout", raw.FPDF_ANNOT_STAMP: "stamp", raw.FPDF_ANNOT_CARET: "caret",
          raw.FPDF_ANNOT_INK: "ink", raw.FPDF_ANNOT_FILEATTACHMENT: "fileattachment"}

def markup(path):
    found = set()
    try:
        doc = pdfium.PdfDocument(path)
    except Exception:
        return found
    for i in range(min(len(doc), 80)):
        page = doc[i]
        for j in range(raw.FPDFPage_GetAnnotCount(page)):
            a = raw.FPDFPage_GetAnnot(page, j)
            st = raw.FPDFAnnot_GetSubtype(a)
            if st in MARKUP: found.add(MARKUP[st])
            raw.FPDFPage_CloseAnnot(a)
    doc.close()
    return found

def zip_url(fn):
    z = int(fn[:4]); lo = z // 1000 * 1000
    return f"{BASE}/{lo:04d}-{lo + 999:04d}/{z:04d}.zip"

def emit(source, data, fname, url, labels):
    out = os.path.join(CORPUS, "incoming", source); os.makedirs(os.path.join(out, ".part"), exist_ok=True)
    dest = os.path.join(out, fname)
    if os.path.exists(dest): return
    part = os.path.join(out, ".part", fname)
    with open(part, "wb") as f: f.write(data)
    os.replace(part, dest)
    with open(os.path.join(out, "_files.tsv"), "a") as f:
        f.write(f"{fname}\t{url}\t{LIC}\t{labels}\n")
    print("ok", len(data) // 1024, "KB", source, fname, labels, flush=True)

def main(cands, scratch, max_annot, max_mb):
    rows = [l.rstrip("\n").split("\t") for l in open(cands) if l.strip() and not l.startswith("#")]
    by_zip = {}
    for fn, k in rows: by_zip.setdefault(zip_url(fn), []).append((fn, k))
    kept_annot = 0
    os.makedirs(scratch, exist_ok=True)
    for url, items in sorted(by_zip.items()):
        try: ents = zre.central_dir(url)
        except Exception as e: print("cd fail", url, e, file=sys.stderr); continue
        for fn, k in items:
            if k == "annotcand" and kept_annot >= max_annot: continue
            if fn not in ents: continue
            method, crc, csize, usize, off = ents[fn]
            if usize > max_mb * 1e6: continue
            hdr = zre.rng(url, off, off + 29)
            import struct
            nlen, xlen = struct.unpack("<HH", hdr[26:30]); start = off + 30 + nlen + xlen
            data = zre.rng(url, start, start + csize - 1)
            if method == 8: data = zlib.decompress(data, -15)
            if zlib.crc32(data) & 0xFFFFFFFF != crc or b"%PDF-" not in data[:1024]: continue
            src = f"{url}#{fn}"
            if k in ("xfa", "acroform"):
                emit("forms-annotations", data, f"cc-{k}__{fn}", src, f"cc-{k},forms")
            elif k == "rtl":
                emit("commoncrawl-cc-main-2021-31", data, f"rtl__{fn}", src, "rtl")
            else:
                tmp = os.path.join(scratch, fn)
                with open(tmp, "wb") as f: f.write(data)
                m = markup(tmp); os.remove(tmp)
                if m:
                    emit("forms-annotations", data, f"cc-annot__{fn}", src, "annotations," + ",".join("annot-" + x for x in sorted(m)))
                    kept_annot += 1
    print("annotated kept", kept_annot, file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]))
