#!/usr/bin/env python3
"""Parse `pdfinfo` output into a normalized meta.json.

Reads pdfinfo plaintext from <argv[1]> (or stdin) and writes JSON to stdout.
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
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    json.dump(parse(text), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
