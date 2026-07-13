#!/usr/bin/env python3
"""Verify that a conservative light HTML file preserves its canonical structure.

This is deliberately an oracle independent of ``externalize-page-images.py``:
it tokenizes the two rendered HTML files, extracts each positioned ``.t``
subtree as exact bytes, and only masks the documented light-v1 representation
metadata and page-raster externalization while comparing the remaining bytes.

Usage:
    verify-light-structure.py <canonical.html> <conservative.light.html>
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Iterator


NAME_RE = re.compile(br"</?\s*([A-Za-z][A-Za-z0-9:_-]*)")
PAGE_ID_RE = re.compile(r"pf[0-9a-f]+\Z", re.IGNORECASE)
ROOT_METADATA = {"data-pdf2html-representation", "data-pdf2html-text-mode"}
PAGE_METADATA = {"data-pdf2html-page", "data-pdf2html-text-mode"}
RASTER_METADATA = {"src", "data-pdf2html-src", "data-pdf2html-raster", "data-pdf2html-page"}


class VerificationError(RuntimeError):
    """A comparison failure suitable for a concise CLI report."""


@dataclass(frozen=True)
class Tag:
    start: int
    end: int
    raw: bytes
    name: str | None
    closing: bool


@dataclass(frozen=True)
class PageFrame:
    identifier: str
    start: int
    end: int


@dataclass(frozen=True)
class Raster:
    attrs: tuple[tuple[str, str | None], ...]
    source: str | None
    external_source: str | None
    externalized: str | None
    page: str | None


def next_tag(data: bytes, start: int, limit: int | None = None) -> Tag | None:
    """Return the next HTML-ish tag without decoding or rewriting document bytes."""
    end_limit = len(data) if limit is None else limit
    begin = data.find(b"<", start, end_limit)
    if begin < 0:
        return None

    if data.startswith(b"<!--", begin):
        end = data.find(b"-->", begin + 4, end_limit)
        end = end_limit if end < 0 else end + 3
    elif data.startswith(b"<![CDATA[", begin):
        end = data.find(b"]]>", begin + 9, end_limit)
        end = end_limit if end < 0 else end + 3
    else:
        quote: int | None = None
        cursor = begin + 1
        while cursor < end_limit:
            character = data[cursor]
            if quote is not None:
                if character == quote:
                    quote = None
            elif character in (ord("'"), ord('"')):
                quote = character
            elif character == ord(">"):
                cursor += 1
                break
            cursor += 1
        end = cursor

    raw = data[begin:end]
    match = NAME_RE.match(raw)
    name = match.group(1).decode("ascii").lower() if match else None
    closing = bool(raw.startswith(b"</"))
    return Tag(begin, end, raw, name, closing)


def tags(data: bytes, start: int = 0, limit: int | None = None) -> Iterator[Tag]:
    cursor = start
    while (tag := next_tag(data, cursor, limit)) is not None:
        yield tag
        cursor = tag.end


@functools.lru_cache(maxsize=8192)
def attrs_from_raw(raw: bytes) -> tuple[tuple[str, str | None], ...]:
    """Read start-tag attributes without normalizing their byte values.

    This narrow scanner is intentionally sufficient for pdf2htmlEX's emitted
    markup, and avoids an HTMLParser pass for every one of AlgDat's millions
    of tags. It is an oracle parser, not converter logic.
    """
    if raw.startswith(b"</") or raw.startswith((b"<!", b"<?")):
        return ()
    cursor = 1
    length = len(raw)
    while cursor < length and raw[cursor] not in b" \t\r\n\f/>":
        cursor += 1

    parsed: list[tuple[str, str | None]] = []
    while cursor < length:
        while cursor < length and raw[cursor] in b" \t\r\n\f/":
            cursor += 1
        if cursor >= length or raw[cursor] == ord(">"):
            break
        name_start = cursor
        while cursor < length and raw[cursor] not in b" \t\r\n\f=>/":
            cursor += 1
        name = raw[name_start:cursor].decode("latin-1").lower()
        if not name:
            cursor += 1
            continue
        while cursor < length and raw[cursor] in b" \t\r\n\f":
            cursor += 1
        value: str | None = None
        if cursor < length and raw[cursor] == ord("="):
            cursor += 1
            while cursor < length and raw[cursor] in b" \t\r\n\f":
                cursor += 1
            if cursor < length and raw[cursor] in (ord("'"), ord('"')):
                quote = raw[cursor]
                cursor += 1
                value_start = cursor
                while cursor < length and raw[cursor] != quote:
                    cursor += 1
                value = raw[value_start:cursor].decode("latin-1")
                if cursor < length:
                    cursor += 1
            else:
                value_start = cursor
                while cursor < length and raw[cursor] not in b" \t\r\n\f>/":
                    cursor += 1
                value = raw[value_start:cursor].decode("latin-1")
        parsed.append((name, value))
    return tuple(parsed)


def attrs(tag: Tag) -> tuple[tuple[str, str | None], ...]:
    return () if tag.closing or tag.name is None else attrs_from_raw(tag.raw)


def attr_value(tag: Tag, name: str) -> str | None:
    target = name.lower()
    for attr_name, value in attrs(tag):
        if attr_name == target:
            return value
    return None


def class_tokens(tag: Tag) -> tuple[str, ...]:
    value = attr_value(tag, "class")
    return tuple(value.split()) if value else ()


def is_page_frame(tag: Tag) -> bool:
    identifier = attr_value(tag, "id")
    return bool(
        tag.name == "div"
        and not tag.closing
        and identifier
        and PAGE_ID_RE.fullmatch(identifier)
        and "pf" in class_tokens(tag)
    )


def matching_div_end(data: bytes, opening: Tag, limit: int | None = None) -> int:
    depth = 1
    for tag in tags(data, opening.end, limit):
        if tag.name != "div":
            continue
        if tag.closing:
            depth -= 1
            if depth == 0:
                return tag.end
        elif not tag.raw.rstrip().endswith(b"/>"):
            depth += 1
    raise VerificationError(f"unclosed page frame {attr_value(opening, 'id')!r}")


def page_frames(data: bytes) -> list[PageFrame]:
    pages: list[PageFrame] = []
    cursor = 0
    while (tag := next_tag(data, cursor)) is not None:
        cursor = tag.end
        if not is_page_frame(tag):
            continue
        end = matching_div_end(data, tag)
        pages.append(PageFrame(attr_value(tag, "id") or "", tag.start, end))
        cursor = end
    return pages


def text_subtrees(data: bytes, page: PageFrame) -> list[bytes]:
    """Extract complete ``.t`` div byte slices, with no transform dependency."""
    subtrees: list[bytes] = []
    cursor = page.start
    while (tag := next_tag(data, cursor, page.end)) is not None:
        if tag.start >= page.end:
            break
        cursor = tag.end
        if tag.name != "div" or tag.closing or "t" not in class_tokens(tag):
            continue
        end = matching_div_end(data, tag, page.end)
        subtrees.append(data[tag.start:end])
        cursor = end
    return subtrees


def hash_slices(slices: list[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    for value in slices:
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest(), sum(len(value) for value in slices)


def filtered_attrs(
    tag: Tag,
    excluded: set[str],
    *,
    remove_class: str | None = None,
) -> tuple[tuple[str, str | None], ...]:
    filtered: list[tuple[str, str | None]] = []
    for name, value in attrs(tag):
        if name in excluded:
            continue
        if name == "class" and remove_class and value is not None:
            remaining = tuple(token for token in value.split() if token != remove_class)
            if not remaining:
                continue
            filtered.append((name, " ".join(remaining)))
            continue
        filtered.append((name, value))
    return tuple(filtered)


def tagged_fingerprint(label: bytes, attributes: tuple[tuple[str, str | None], ...]) -> bytes:
    return b"<" + label + b":" + repr(attributes).encode("utf-8") + b">"


def is_page_raster(tag: Tag) -> bool:
    return tag.name == "img" and not tag.closing and "bi" in class_tokens(tag)


def raster_from_tag(tag: Tag) -> Raster:
    return Raster(
        attrs=filtered_attrs(tag, RASTER_METADATA),
        source=attr_value(tag, "src"),
        external_source=attr_value(tag, "data-pdf2html-src"),
        externalized=attr_value(tag, "data-pdf2html-raster"),
        page=attr_value(tag, "data-pdf2html-page"),
    )


def normalized_page(data: bytes, page: PageFrame) -> tuple[bytes, list[Raster], Tag]:
    parts: list[bytes] = []
    rasters: list[Raster] = []
    cursor = page.start
    page_tag: Tag | None = None
    for tag in tags(data, page.start, page.end):
        if tag.start >= page.end:
            break
        parts.append(data[cursor:tag.start])
        cursor = tag.end
        if is_page_frame(tag):
            page_tag = tag
            parts.append(tagged_fingerprint(b"PAGE", filtered_attrs(tag, PAGE_METADATA)))
        elif is_page_raster(tag):
            rasters.append(raster_from_tag(tag))
            parts.append(tagged_fingerprint(b"RASTER", rasters[-1].attrs))
        else:
            parts.append(tag.raw)
    parts.append(data[cursor:page.end])
    if page_tag is None:
        raise VerificationError(f"page {page.identifier} has no opening frame tag")
    return b"".join(parts), rasters, page_tag


def normalized_document_outside_pages(data: bytes, pages: list[PageFrame]) -> bytes:
    """Mask page bodies and the two documented document-level metadata changes."""
    parts: list[bytes] = []
    cursor = 0
    for index, page in enumerate(pages, start=1):
        parts.append(normalized_free_fragment(data[cursor:page.start]))
        parts.append(f"<PAGE-{index}>".encode("ascii"))
        cursor = page.end
    parts.append(normalized_free_fragment(data[cursor:]))
    return b"".join(parts)


def normalized_free_fragment(fragment: bytes) -> bytes:
    parts: list[bytes] = []
    cursor = 0
    for tag in tags(fragment):
        parts.append(fragment[cursor:tag.start])
        cursor = tag.end
        if tag.name == "html" and not tag.closing:
            parts.append(tagged_fingerprint(b"HTML", filtered_attrs(tag, ROOT_METADATA)))
        elif tag.name == "body" and not tag.closing:
            parts.append(
                tagged_fingerprint(
                    b"BODY", filtered_attrs(tag, set(), remove_class="pdf2html-light")
                )
            )
        else:
            parts.append(tag.raw)
    parts.append(fragment[cursor:])
    return b"".join(parts)


def document_metadata(data: bytes) -> tuple[Tag | None, Tag | None]:
    html_tag: Tag | None = None
    body_tag: Tag | None = None
    for tag in tags(data):
        if tag.closing:
            continue
        if tag.name == "html" and html_tag is None:
            html_tag = tag
        elif tag.name == "body" and body_tag is None:
            body_tag = tag
        if html_tag and body_tag:
            break
    return html_tag, body_tag


def validate_light_metadata(light: bytes) -> None:
    html_tag, body_tag = document_metadata(light)
    if html_tag is None:
        raise VerificationError("light HTML has no <html> root")
    if attr_value(html_tag, "data-pdf2html-representation") != "light-v1":
        raise VerificationError("light HTML is missing data-pdf2html-representation=light-v1")
    if attr_value(html_tag, "data-pdf2html-text-mode") != "original":
        raise VerificationError("light HTML is not conservative (expected data-pdf2html-text-mode=original)")
    if body_tag is None or "pdf2html-light" not in class_tokens(body_tag):
        raise VerificationError("light HTML body is missing the pdf2html-light representation class")


def validate_rasters(
    canonical: list[Raster], light: list[Raster], page_index: int
) -> None:
    if len(canonical) != len(light):
        raise VerificationError(
            f"raster count mismatch at page {page_index}: canonical={len(canonical)} light={len(light)}"
        )
    for raster_index, (source, derived) in enumerate(zip(canonical, light), start=1):
        if source.attrs != derived.attrs:
            raise VerificationError(
                f"raster structure mismatch at page {page_index}, raster {raster_index}"
            )
        if not source.source or not source.source.lower().startswith("data:image/"):
            raise VerificationError(
                f"canonical raster {raster_index} on page {page_index} is not an inline data URL"
            )
        if (
            not derived.external_source
            or derived.external_source.lower().startswith("data:")
            or derived.externalized != "external"
            or derived.page != str(page_index)
        ):
            raise VerificationError(
                f"light raster {raster_index} on page {page_index} is not correctly externalized"
            )
        if derived.source is not None and derived.source != derived.external_source:
            raise VerificationError(
                f"light raster {raster_index} on page {page_index} has an unexpected src"
            )


def verify(canonical: bytes, light: bytes) -> dict[str, int | str]:
    validate_light_metadata(light)
    canonical_pages = page_frames(canonical)
    light_pages = page_frames(light)
    if len(canonical_pages) != len(light_pages):
        raise VerificationError(
            f"page-frame count mismatch: canonical={len(canonical_pages)} light={len(light_pages)}"
        )
    if not canonical_pages:
        raise VerificationError("canonical HTML has no pdf2htmlEX page frames")
    for index, (source, derived) in enumerate(zip(canonical_pages, light_pages), start=1):
        if source.identifier != derived.identifier:
            raise VerificationError(
                f"page-frame order mismatch at page {index}: "
                f"canonical={source.identifier} light={derived.identifier}"
            )

    if normalized_document_outside_pages(canonical, canonical_pages) != normalized_document_outside_pages(
        light, light_pages
    ):
        raise VerificationError("document structure mismatch outside page frames")

    canonical_slices: list[bytes] = []
    light_slices: list[bytes] = []
    raster_count = 0
    for index, (source, derived) in enumerate(zip(canonical_pages, light_pages), start=1):
        source_text = text_subtrees(canonical, source)
        derived_text = text_subtrees(light, derived)
        source_hash, source_bytes = hash_slices(source_text)
        derived_hash, derived_bytes = hash_slices(derived_text)
        if source_text != derived_text:
            raise VerificationError(
                f"text subtree mismatch at page {index}: "
                f"canonical_sha256={source_hash} light_sha256={derived_hash} "
                f"canonical_bytes={source_bytes} light_bytes={derived_bytes}"
            )

        source_page, source_rasters, source_tag = normalized_page(canonical, source)
        derived_page, derived_rasters, derived_tag = normalized_page(light, derived)
        if filtered_attrs(source_tag, PAGE_METADATA) != filtered_attrs(derived_tag, PAGE_METADATA):
            raise VerificationError(f"page-frame structure mismatch at page {index}")
        light_page_number = attr_value(derived_tag, "data-pdf2html-page")
        if light_page_number is not None and light_page_number != str(index):
            raise VerificationError(f"light page {index} has incorrect page representation metadata")
        light_page_mode = attr_value(derived_tag, "data-pdf2html-text-mode")
        if light_page_mode is not None and light_page_mode != "original":
            raise VerificationError(f"light page {index} is not marked conservative/original")
        validate_rasters(source_rasters, derived_rasters, index)
        if source_page != derived_page:
            raise VerificationError(f"structure mismatch at page {index}")

        canonical_slices.extend(source_text)
        light_slices.extend(derived_text)
        raster_count += len(source_rasters)

    canonical_text_hash, text_bytes = hash_slices(canonical_slices)
    light_text_hash, _ = hash_slices(light_slices)
    return {
        "pages": len(canonical_pages),
        "rasters": raster_count,
        "text_runs": len(canonical_slices),
        "text_bytes": text_bytes,
        "text_sha256": canonical_text_hash,
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        "light_sha256": hashlib.sha256(light).hexdigest(),
        "light_text_sha256": light_text_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("canonical", type=pathlib.Path)
    parser.add_argument("light", type=pathlib.Path)
    args = parser.parse_args()
    for path in (args.canonical, args.light):
        if not path.is_file():
            parser.error(f"HTML file not found: {path}")

    try:
        report = verify(args.canonical.read_bytes(), args.light.read_bytes())
    except VerificationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "PASS "
        f"pages={report['pages']} rasters={report['rasters']} "
        f"text_runs={report['text_runs']} text_bytes={report['text_bytes']} "
        f"text_sha256={report['text_sha256']} "
        f"canonical_sha256={report['canonical_sha256']} "
        f"light_sha256={report['light_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
