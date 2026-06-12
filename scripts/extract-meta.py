#!/usr/bin/env python3
"""Parse `pdfinfo` output into a normalized meta.json.

Reads pdfinfo plaintext from <argv[1]> (or stdin). With no output path it
writes JSON to stdout. With an output path as <argv[2]> it *merges* the
parsed pdfinfo fields into any existing meta.json at that path, preserving
keys this script doesn't own — notably the pipeline-written "provenance"
object (see scripts/write-provenance.py). This merge is what keeps
extract-pdf-meta.sh from clobbering provenance on a re-run.

Missing fields are omitted rather than emitted as null — keeps the JSON
scannable and the schema forgiving.

Emitted keys (any of):
    title       Document /Title
    author      Document /Author
    subject     Document /Subject
    keywords    Document /Keywords
    producer    /Producer (the PDF library that wrote the file)
    creator     /Creator (the authoring app, e.g. "Adobe InDesign")
    pages       int, page count
    year        int, extracted from CreationDate if parseable
    created     raw CreationDate string
    file_size   int, bytes
"""
import sys
import re
import json
import os

# pdfinfo-owned keys. On a merge these are refreshed from the new parse (so
# schema/value changes propagate); a key absent from the new parse is dropped
# from the merged output. Any key NOT in this set — e.g. "provenance" — is
# left untouched.
PDFINFO_KEYS = (
    "title", "author", "subject", "keywords", "producer", "creator",
    "pages", "year", "created", "file_size",
)


def parse(text: str) -> dict:
    raw: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        raw[key.strip()] = value.strip()

    meta: dict = {}
    for src, dst in [
        ("Title", "title"),
        ("Author", "author"),
        ("Subject", "subject"),
        ("Keywords", "keywords"),
        ("Producer", "producer"),
        ("Creator", "creator"),
    ]:
        v = raw.get(src, "").strip()
        if v:
            meta[dst] = v

    if raw.get("Pages"):
        try:
            meta["pages"] = int(raw["Pages"])
        except ValueError:
            pass

    cd = raw.get("CreationDate", "")
    if cd:
        meta["created"] = cd
        m = re.search(r"\b(19|20)\d{2}\b", cd)
        if m:
            meta["year"] = int(m.group())

    fs = raw.get("File size", "")
    if fs:
        m = re.match(r"(\d+)\s*bytes", fs)
        if m:
            meta["file_size"] = int(m.group(1))

    return meta


def main() -> int:
    # argv[1] = pdfinfo plaintext (or stdin if absent/"-").
    # argv[2] = optional output meta.json to merge into (preserves "provenance"
    #           and any other non-pdfinfo key); without it, write to stdout.
    in_path = sys.argv[1] if len(sys.argv) > 1 else None
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    if in_path and in_path != "-":
        with open(in_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    parsed = parse(text)

    if not out_path:
        json.dump(parsed, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    # Merge into existing meta.json: refresh pdfinfo-owned keys, preserve the
    # rest (provenance et al.).
    meta: dict = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                meta = loaded
        except (OSError, ValueError):
            meta = {}

    for key in PDFINFO_KEYS:
        meta.pop(key, None)
    # Reinsert refreshed pdfinfo fields in their canonical order, ahead of any
    # preserved trailing keys like "provenance".
    refreshed = {k: parsed[k] for k in PDFINFO_KEYS if k in parsed}
    preserved = {k: v for k, v in meta.items() if k not in PDFINFO_KEYS}
    merged = {**refreshed, **preserved}

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
