#!/usr/bin/env python3
"""Copy PDFs from a staging checkout into incoming/<source>/ and append _files.tsv rows.

usage:
  find <checkout>/<dir> -iname '*.pdf' | sed 's|^<checkout>/||' | \
    python3 -I stage-copy.py --source NAME --root <checkout> [--strip PREFIX/] \
        --url 'https://.../<commit>/{path}' --license TEXT

stdin holds one path per line, relative to --root. The file name in incoming/ is
the path with --strip removed, '/' replaced by '__' and ' ' by '_'. {path} in --url
is the URL-quoted full relative path. Each file is copied to a .part name and
renamed; only then is its row appended. Files already listed are skipped.
"""
import argparse, os, shutil, sys, urllib.parse
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--source", required=True)
ap.add_argument("--root", required=True)
ap.add_argument("--strip", default="")
ap.add_argument("--url", required=True)
ap.add_argument("--license", required=True)
a = ap.parse_args()

corpus = Path(os.environ.get("PDFV_CORPUS_DIR", Path.home() / ".local/share/pdf_viewer/corpus"))
dest = corpus / "incoming" / a.source
dest.mkdir(parents=True, exist_ok=True)
tsv = dest / "_files.tsv"
seen = {l.split("\t", 1)[0] for l in tsv.read_text().splitlines() if l} if tsv.exists() else set()
n = 0
with open(tsv, "a") as out:
    for rel in sys.stdin.read().splitlines():
        rel = rel.strip()
        if not rel:
            continue
        short = rel[len(a.strip):] if a.strip and rel.startswith(a.strip) else rel
        name = short.replace("/", "__").replace(" ", "_")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        if name in seen:
            continue
        src = Path(a.root) / rel
        if not src.is_file():
            print("missing", rel, file=sys.stderr)
            continue
        part = dest / (name + ".part")
        shutil.copyfile(src, part)
        os.replace(part, dest / name)
        out.write(f"{name}\t{a.url.format(path=urllib.parse.quote(rel))}\t{a.license}\n")
        out.flush()
        seen.add(name)
        n += 1
print(f"{a.source}: copied {n}", file=sys.stderr)
