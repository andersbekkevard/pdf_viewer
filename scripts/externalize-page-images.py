#!/usr/bin/env python3
"""Build a light pdf2htmlEX HTML variant with lazy page rasters.

The canonical pdf2htmlEX output embeds every full-page raster as a base64
data URI. This script keeps the canonical HTML untouched, writes each inline
page raster to a sibling directory, and writes a derived HTML file whose
page-raster <img> tags carry data-pdf2html-src instead of eager src. By
default it also collapses pdf2htmlEX's glyph-heavy text layer to one real text
node per page, preserving native find/copy while avoiding millions of DOM
nodes.

Usage:
    externalize-page-images.py <input.html> <output.light.html> \
        --image-dir <entry/page-images> --url-prefix /<hash>/page-images/
"""
from __future__ import annotations

import argparse
import base64
import html
import pathlib
import re
import shutil
import sys


IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
CLASS_RE = re.compile(r"\bclass=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
SRC_RE = re.compile(r"\s+src=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
DATA_URI_RE = re.compile(
    r"^data:image/(png|jpe?g);base64,(.*)$",
    re.IGNORECASE | re.DOTALL,
)
OLD_ATTR_RE = re.compile(
    r"\s+data-pdf2html-(?:src|raster|page)=(['\"]).*?\1",
    re.IGNORECASE | re.DOTALL,
)
BODY_TAG_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
TEXT_DIV_RE = re.compile(
    r"(<div\b[^>]*\bclass=(['\"])(?=[^'\"]*\bt\b)[^'\"]*\2[^>]*>)"
    r"(.*?)"
    r"(</div>)",
    re.IGNORECASE | re.DOTALL,
)
CLASS_ATTR_RE = re.compile(r"\bclass=(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)


def is_page_raster(tag: str) -> bool:
    match = CLASS_RE.search(tag)
    if not match:
        return False
    classes = re.split(r"\s+", match.group(2).strip())
    return "bi" in classes


def add_attrs(tag: str, attrs: str) -> str:
    tag = OLD_ATTR_RE.sub("", tag)
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + attrs + " />"
    return tag[:-1].rstrip() + attrs + ">"


def class_tokens(tag: str) -> list[str]:
    match = CLASS_ATTR_RE.search(tag)
    if not match:
        return []
    return re.split(r"\s+", match.group(2).strip())


def add_class(tag: str, class_name: str) -> str:
    tokens = class_tokens(tag)
    if class_name in tokens:
        return tag
    match = CLASS_ATTR_RE.search(tag)
    if match:
        quote = match.group(1)
        classes = (match.group(2).strip() + " " + class_name).strip()
        return tag[: match.start(2)] + html.escape(classes, quote=True) + tag[match.end(2) :]
    insert_at = -2 if tag.endswith("/>") else -1
    return tag[:insert_at].rstrip() + f' class="{class_name}"' + tag[insert_at:]


def mark_light_body(text: str) -> str:
    return BODY_TAG_RE.sub(lambda match: add_class(match.group(0), "pdf2html-light"), text, count=1)


def mark_flattened_html(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\sdata-pdf2html-text-flattened=", tag, re.IGNORECASE):
            return tag
        insert_at = -2 if tag.endswith("/>") else -1
        return tag[:insert_at].rstrip() + ' data-pdf2html-text-flattened="line"' + tag[insert_at:]

    return HTML_TAG_RE.sub(replace, text, count=1)


def mark_page_text_html(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\sdata-pdf2html-text-flattened=", tag, re.IGNORECASE):
            return tag
        insert_at = -2 if tag.endswith("/>") else -1
        return tag[:insert_at].rstrip() + ' data-pdf2html-text-flattened="page"' + tag[insert_at:]

    return HTML_TAG_RE.sub(replace, text, count=1)


def plain_text_from_markup(inner: str) -> str:
    return html.unescape(TAG_RE.sub("", inner))


def flatten_text_spans_to_lines(text: str) -> tuple[str, int]:
    flattened = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal flattened
        start, inner, end = match.group(1), match.group(3), match.group(4)

        flattened += 1
        content = plain_text_from_markup(inner)
        return start + html.escape(content, quote=False) + end

    return TEXT_DIV_RE.sub(replace, text), flattened


def collapse_text_spans_to_pages(text: str) -> tuple[str, int, int]:
    page_starts = [
        match.start()
        for match in re.finditer(
            r'<div\s+id=(["\'])pf[0-9a-f]+\1\s+class=(["\'])(?=[^"\']*\bpf\b)',
            text,
            re.IGNORECASE,
        )
    ]
    if not page_starts:
        return text, 0, 0

    page_starts.append(len(text))
    out_parts: list[str] = []
    pos = 0
    flattened = 0
    pages = 0

    for start, end in zip(page_starts, page_starts[1:]):
        out_parts.append(text[pos:start])
        chunk = text[start:end]
        lines: list[str] = []

        def remove_text_run(match: re.Match[str]) -> str:
            nonlocal flattened
            content = plain_text_from_markup(match.group(3))
            if content.strip():
                lines.append(content)
            flattened += 1
            return ""

        chunk = TEXT_DIV_RE.sub(remove_text_run, chunk)
        page_text = "\n".join(lines)
        page_text_div = (
            '<div class="pdf2html-page-text">'
            + html.escape(page_text, quote=False)
            + "</div>"
        )
        marker = '</div><div class="pi"'
        insert_at = chunk.rfind(marker)
        if insert_at >= 0:
            chunk = chunk[:insert_at] + page_text_div + chunk[insert_at:]
        else:
            chunk += page_text_div
        out_parts.append(chunk)
        pos = end
        pages += 1

    out_parts.append(text[pos:])
    return "".join(out_parts), flattened, pages


def image_extension(mime_ext: str) -> str:
    return "jpg" if mime_ext.lower() in {"jpg", "jpeg"} else "png"


def externalize(
    input_html: pathlib.Path,
    output_html: pathlib.Path,
    image_dir: pathlib.Path,
    url_prefix: str,
    eager: int,
    clean: bool,
    text_layer: str,
) -> tuple[int, int, int, int, int]:
    text = input_html.read_text(encoding="utf-8", errors="ignore")

    if clean and image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    if not url_prefix.endswith("/"):
        url_prefix += "/"

    page_index = 0
    inline_count = 0
    external_count = 0
    out_parts: list[str] = []
    pos = 0

    for match in IMG_TAG_RE.finditer(text):
        tag = match.group(0)
        if not is_page_raster(tag):
            continue

        src_match = SRC_RE.search(tag)
        if not src_match:
            continue

        src_value = src_match.group(2)
        data_match = DATA_URI_RE.match(src_value)

        page_index += 1
        asset_url = src_value

        if data_match:
            ext = image_extension(data_match.group(1))
            filename = f"{page_index:04d}.{ext}"
            asset_path = image_dir / filename
            payload = re.sub(r"\s+", "", data_match.group(2))
            try:
                asset_path.write_bytes(base64.b64decode(payload, validate=True))
            except Exception as exc:
                raise RuntimeError(
                    f"failed to decode page raster {page_index} in {input_html}: {exc}"
                ) from exc
            asset_url = url_prefix + filename
            inline_count += 1
        else:
            external_count += 1

        escaped_url = html.escape(asset_url, quote=True)
        tag_without_src = SRC_RE.sub("", tag, count=1)
        attrs = (
            f' data-pdf2html-src="{escaped_url}"'
            f' data-pdf2html-raster="external"'
            f' data-pdf2html-page="{page_index}"'
        )
        if page_index <= eager:
            attrs = f' src="{escaped_url}"' + attrs
        replacement = add_attrs(tag_without_src, attrs)

        out_parts.append(text[pos:match.start()])
        out_parts.append(replacement)
        pos = match.end()

    out_parts.append(text[pos:])
    output_text = mark_light_body("".join(out_parts))
    page_text_count = 0
    if text_layer == "page":
        output_text, flattened_count, page_text_count = collapse_text_spans_to_pages(output_text)
        output_text = mark_page_text_html(output_text)
    elif text_layer == "line":
        output_text, flattened_count = flatten_text_spans_to_lines(output_text)
        output_text = mark_flattened_html(output_text)
    else:
        flattened_count = 0
    output_html.write_text(output_text, encoding="utf-8")
    return page_index, inline_count, external_count, flattened_count, page_text_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_html", type=pathlib.Path)
    parser.add_argument("output_html", type=pathlib.Path)
    parser.add_argument("--image-dir", type=pathlib.Path, required=True)
    parser.add_argument("--url-prefix", required=True)
    parser.add_argument("--eager", type=int, default=2)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--text-layer",
        choices=("page", "line", "original"),
        default="page",
        help=(
            "light HTML text strategy: one searchable text node per page "
            "(page), one flattened node per visual line (line), or original "
            "pdf2htmlEX span DOM (original)"
        ),
    )
    parser.add_argument(
        "--preserve-text-spans",
        action="store_true",
        help="deprecated alias for --text-layer=original",
    )
    args = parser.parse_args()

    if args.eager < 0:
        parser.error("--eager must be >= 0")
    if not args.input_html.is_file():
        parser.error(f"input HTML not found: {args.input_html}")

    text_layer = "original" if args.preserve_text_spans else args.text_layer

    try:
        pages, inline_count, external_count, flattened_count, page_text_count = externalize(
            args.input_html,
            args.output_html,
            args.image_dir,
            args.url_prefix,
            args.eager,
            args.clean,
            text_layer,
        )
    except Exception as exc:
        print(f"externalize-page-images: {exc}", file=sys.stderr)
        return 1

    print(
        "externalize-page-images: "
        f"{pages} page rasters, {inline_count} extracted, "
        f"{external_count} already external, "
        f"{flattened_count} text runs flattened, "
        f"{page_text_count} page text nodes -> {args.output_html}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
