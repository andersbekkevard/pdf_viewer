"""Expand PDFium's hand-written .in test templates into PDFs.

    python3 -I bench/corpus/synth/pdfium_templates.py <pdfium checkout> [--out DIR]

PDFium keeps many test cases in testing/resources/**/*.in: PDF text with
{{header}}, {{object N G}}, {{xref}}, {{trailer}}, {{trailersize}},
{{startxref}}, {{startxrefobj N G}}, {{streamlen}} and {{include file}}
placeholders. PDFium fills them with testing/tools/fixup_pdf_template.py; this is
an independent reimplementation of the same rules, so nothing from the
downloaded repository is executed. Includes may only resolve to files inside the
resources directory.

Output: $PDFV_CORPUS_DIR/incoming/pdfium-templates/<path with / as __>.pdf, with
a _files.tsv row appended after each file is complete. The url column is
generated:pdfium-template-fixup:<googlesource URL of the .in file at that commit>.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
from pathlib import Path

HEADER = b"%PDF-1.7\n%\xa0\xf2\xa4\xf4"
OBJ = re.compile(rb"{{object\s+(\d+)\s+(\d+)}}")
SXOBJ = re.compile(rb"{{startxrefobj\s+(\d+)\s+(\d+)}}")
INCLUDE = re.compile(rb"\s*{{include\s+(.+)}}")


def inline(path: Path, root: Path, out: io.BytesIO, seen: set[Path]) -> None:
    path = path.resolve()
    if path in seen or root not in path.parents:
        return
    seen.add(path)
    ends_nl = False
    with open(path, "rb") as f:
        for line in f:
            m = INCLUDE.match(line)
            if m:
                inline(path.parent / m.group(1).decode().strip(), root, out, seen)
                continue
            if path.suffix in (".in", ".js", ".fragment", ".xml"):
                if line.endswith(b"\r\n"):
                    line = line[:-2] + b"\n"
                    ends_nl = True
                else:
                    ends_nl = line.endswith(b"\n")
            out.write(line)
    if not ends_nl:
        out.write(b"\n")
    seen.discard(path)


def expand(lines: list[bytes]) -> bytes:
    # Pass 1: stream lengths for each {{streamlen}}.
    lens, state = [], 0
    for line in lines:
        if b"{{streamlen}}" in line:
            state = 1
            lens.append(0)
            continue
        if state == 1 and line.rstrip() == b"stream":
            state = 2
            continue
        if state == 2:
            if line.rstrip() == b"endstream":
                state = 0
                lens[-1] -= 1
            else:
                lens[-1] += len(line)
    # Pass 2: substitute, tracking offsets.
    out = bytearray()
    objs: dict[int, tuple[int, int]] = {}
    xref_at = 0
    for line in lines:
        off = len(out)
        line = line.replace(b"{{header}}", HEADER)
        if b"{{streamlen}}" in line:
            line = line.replace(b"{{streamlen}}", b"/Length %d" % lens.pop(0))
        if b"{{xref}}" in line:
            xref_at = off
            mx = max(objs) if objs else 0
            rows = [b"xref\n0 %d\n" % (mx + 1)]
            for i in range(mx + 1):
                rows.append(b"%010d %05d n \n" % objs[i] if i in objs else b"0000000000 65535 f \n")
            line = b"".join(rows)
        size = (max(objs) if objs else 0) + 1
        line = line.replace(b"{{trailer}}", b"trailer <<\n  /Root 1 0 R\n  /Size %d\n>>" % size)
        line = line.replace(b"{{trailersize}}", b"/Size %d" % size)
        line = line.replace(b"{{startxref}}", b"startxref\n%d" % xref_at)
        m = OBJ.match(line)
        if m:
            objs[int(m.group(1))] = (off, int(m.group(2)))
            line = OBJ.sub(rb"\g<1> \g<2> obj", line)
        m = SXOBJ.match(line)
        if m:
            line = SXOBJ.sub(b"startxref\n%d" % objs[int(m.group(1))][0], line)
        out += line
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("checkout", type=Path, help="PDFium checkout containing testing/resources")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    root = (a.checkout / "testing" / "resources").resolve()
    commit = subprocess.run(["git", "-C", str(a.checkout), "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip() or "main"
    corpus = Path(os.environ.get("PDFV_CORPUS_DIR", Path.home() / ".local/share/pdf_viewer/corpus"))
    out = a.out or corpus / "incoming" / "pdfium-templates"
    out.mkdir(parents=True, exist_ok=True)
    tsv = out / "_files.tsv"
    listed = {l.split("\t", 1)[0] for l in tsv.read_text().splitlines()} if tsv.exists() else set()
    ok = bad = 0
    for src in sorted(root.rglob("*.in")):
        rel = src.relative_to(root).as_posix()
        name = rel[:-3].replace("/", "__") + ".pdf"
        if name in listed:
            continue
        try:
            buf = io.BytesIO()
            inline(src, root, buf, set())
            data = expand(buf.getvalue().splitlines(keepends=True))
        except Exception as e:  # malformed template: skip, report
            print(f"skip {rel}: {type(e).__name__}: {e}", file=sys.stderr)
            bad += 1
            continue
        part = out / (name + ".part")
        part.write_bytes(data)
        os.replace(part, out / name)
        url = f"generated:pdfium-template-fixup:https://pdfium.googlesource.com/pdfium/+/{commit}/testing/resources/{rel}"
        with open(tsv, "a") as f:
            f.write(f"{name}\t{url}\tBSD-3-Clause (PDFium repo test template)\n")
        listed.add(name)
        ok += 1
    print(f"pdfium-templates: wrote {ok}, skipped {bad}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
