#!/usr/bin/env python3
"""Extract per-page plain text from a pdf2htmlEX HTML file.

Usage: extract-find-text.py <html_path> <out_text_json>

The output feeds the overlay's native-browser-find shadow layer. Parsing the
converted HTML, rather than the source PDF, keeps this cheap to backfill from
cache and makes the text match pdf2htmlEX's selectable layer.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from html.parser import HTMLParser


class Pdf2HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[dict[str, object]] = []
        self._page: dict[str, object] | None = None
        self._page_depth = 0
        self._text_depth = 0
        self._line_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        classes = set((attrs.get("class") or "").split())

        if self._text_depth:
            self._text_depth += 1
            if tag == "div" and self._page is not None:
                self._page_depth += 1
            return

        if tag != "div":
            return

        if self._page is None:
            if "pf" not in classes:
                return
            page = self._page_number(attrs)
            if page is None:
                return
            self._page = {"page": page, "lines": []}
            self._page_depth = 1
            return

        self._page_depth += 1
        if "t" in classes:
            self._text_depth = 1
            self._line_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._text_depth:
            self._text_depth -= 1
            if self._text_depth == 0:
                self._finish_line()
            if tag == "div":
                self._close_page_div()
            return

        if tag == "div" and self._page is not None:
            self._close_page_div()

    def handle_data(self, data: str) -> None:
        if self._text_depth:
            self._line_parts.append(data)

    def _page_number(self, attrs: dict[str, str | None]) -> int | None:
        # pdf2htmlEX page IDs are hex and authoritative. `data-page-no` looks
        # decimal in some docs but is hex in others (`data-page-no="140"` for
        # #pf140, i.e. page 320), so using it first corrupts page mappings.
        raw_id = attrs.get("id") or ""
        match = re.fullmatch(r"pf([0-9a-fA-F]+)", raw_id)
        if match:
            return int(match.group(1), 16)

        raw = attrs.get("data-page-no")
        if raw and raw.isdigit():
            return int(raw)
        return None

    def _finish_line(self) -> None:
        if self._page is None:
            return
        line = "".join(self._line_parts).strip()
        self._line_parts = []
        if line:
            lines = self._page["lines"]
            assert isinstance(lines, list)
            lines.append(line)

    def _close_page_div(self) -> None:
        if self._page is None:
            return
        self._page_depth -= 1
        if self._page_depth > 0:
            return

        lines = self._page["lines"]
        assert isinstance(lines, list)
        self.pages.append({
            "page": self._page["page"],
            "text": "\n".join(str(line) for line in lines),
        })
        self._page = None
        self._page_depth = 0


def extract(html_path: pathlib.Path) -> dict[str, object]:
    parser = Pdf2HtmlTextParser()
    with html_path.open("r", encoding="utf-8", errors="ignore") as f:
        for chunk in iter(lambda: f.read(1 << 20), ""):
            if not chunk:
                break
            parser.feed(chunk)
    parser.close()
    parser.pages.sort(key=lambda p: int(p["page"]))
    return {
        "version": 1,
        "source": "pdf2htmlEX-html",
        "pages": parser.pages,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: extract-find-text.py <html_path> <out_text_json>", file=sys.stderr)
        return 2

    html_path = pathlib.Path(sys.argv[1])
    out_path = pathlib.Path(sys.argv[2])
    if not html_path.is_file():
        print(f"not found: {html_path}", file=sys.stderr)
        return 1

    payload = extract(html_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    tmp_path.replace(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
