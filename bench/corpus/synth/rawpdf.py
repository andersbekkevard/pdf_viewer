"""A small hand-rolled PDF writer.

The synthetic generators need byte-level control (inherited page attributes,
broken xref tables, incremental updates, unusual fonts), so they write PDF
objects directly instead of going through a library that would normalise them.
"""

from __future__ import annotations

import hashlib
import zlib


def b(x: str | bytes) -> bytes:
    return x if isinstance(x, bytes) else x.encode("latin-1")


def pdf_string(s: str, encoding: str = "cp1252") -> bytes:
    """A literal string, escaped, in a single-byte encoding."""
    raw = s.encode(encoding)
    out = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"(" + out + b")"


def text(x: float, y: float, s: str, size: float = 12, font: str = "F1",
         extra: str = "") -> bytes:
    """One BT/ET block placing a single string."""
    return (b"BT /%s %g Tf %s %g %g Td " % (b(font), size, b(extra), x, y)
            + pdf_string(s) + b" Tj ET\n")


def rect(x: float, y: float, w: float, h: float, op: str = "S") -> bytes:
    return b"%g %g %g %g re %s\n" % (x, y, w, h, b(op))


STD14 = {
    "F1": "Helvetica", "F2": "Times-Roman", "F3": "Courier",
    "F4": "Helvetica-Bold", "F5": "Times-Italic", "F6": "Courier-Bold",
}


class Raw:
    """Numbered objects serialised with a classic xref table."""

    def __init__(self, version: str = "1.7"):
        self.version = version
        self.objs: dict[int, bytes] = {}
        self.n = 0

    def reserve(self) -> int:
        self.n += 1
        return self.n

    def add(self, body: str | bytes) -> int:
        n = self.reserve()
        self.objs[n] = b(body)
        return n

    def set(self, n: int, body: str | bytes) -> None:
        self.objs[n] = b(body)

    def stream_body(self, data: bytes, extra: str = "", compress: bool = True) -> bytes:
        if compress:
            data = zlib.compress(data, 9)
            extra = extra + " /Filter /FlateDecode"
        return (b"<< /Length %d %s >>\nstream\n" % (len(data), b(extra))) + data + b"\nendstream"

    def stream(self, data: bytes, extra: str = "", compress: bool = True,
               n: int | None = None) -> int:
        body = self.stream_body(data, extra, compress)
        if n is None:
            return self.add(body)
        self.set(n, body)
        return n

    def serialise(self, root: int, info: int | None = None,
                  trailer_extra: str = "") -> tuple[bytes, dict[int, int], int]:
        """Return (bytes, offsets, xref_offset)."""
        out = bytearray(b"%PDF-" + b(self.version) + b"\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for num in sorted(self.objs):
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + self.objs[num] + b"\nendobj\n"
        size = max(self.objs) + 1
        xref_at = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % size
        for num in range(1, size):
            if num in offsets:
                out += b"%010d 00000 n \n" % offsets[num]
            else:
                out += b"0000000000 65535 f \n"
        fid = hashlib.md5(bytes(out)).hexdigest().encode()
        out += b"trailer\n<< /Size %d /Root %d 0 R " % (size, root)
        if info:
            out += b"/Info %d 0 R " % info
        out += b"/ID [<%s> <%s>] %s >>\n" % (fid, fid, b(trailer_extra))
        out += b"startxref\n%d\n%%%%EOF\n" % xref_at
        return bytes(out), offsets, xref_at


class Doc(Raw):
    """A document with a flat page tree, base-14 fonts and an Info dict."""

    def __init__(self, title: str, version: str = "1.7"):
        super().__init__(version)
        self.catalog = self.reserve()
        self.pages = self.reserve()
        self.kids: list[int] = []
        self.fonts = {k: self.add(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{v} /Encoding /WinAnsiEncoding >>")
            for k, v in STD14.items()}
        self.info = self.add(
            b"<< /Title " + pdf_string(title)
            + b" /Producer (pdf_viewer bench/corpus/synth) /CreationDate (D:20261020000000Z) >>")

    def font_res(self) -> str:
        return " ".join(f"/{k} {v} 0 R" for k, v in self.fonts.items())

    def page(self, content: bytes, w: float = 612, h: float = 792, res: str = "",
             extra: str = "", parent: int | None = None, compress: bool = True,
             box: str | None = None, fonts: str = "") -> int:
        c = self.stream(content, compress=compress)
        box = box or f"0 0 {w:g} {h:g}"
        num = self.add(
            f"<< /Type /Page /Parent {parent or self.pages} 0 R /MediaBox [{box}] "
            f"/Resources << /Font << {fonts} {self.font_res()} >> {res} >> /Contents {c} 0 R {extra} >>")
        if parent is None:
            self.kids.append(num)
        return num

    def finish(self, catalog_extra: str = "", pages_extra: str = "",
               kids: list[int] | None = None, count: int | None = None) -> bytes:
        kids = self.kids if kids is None else kids
        count = len(self.kids) if count is None else count
        self.set(self.pages, f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                             f"/Count {count} {pages_extra} >>")
        self.set(self.catalog, f"<< /Type /Catalog /Pages {self.pages} 0 R {catalog_extra} >>")
        return self.serialise(self.catalog, self.info)[0]


def label_page(title: str, lines: list[str], w: float = 612, h: float = 792) -> bytes:
    """A frame, a title and a few explanatory lines, scaled to the page."""
    s = max(min(w, h) / 612, 0.02)
    out = bytearray(b"0.6 G %g w " % (2 * s) + rect(10 * s, 10 * s, w - 20 * s, h - 20 * s))
    out += b"0 g " + text(36 * s, h - 60 * s, title, 20 * s, "F4")
    for i, line in enumerate(lines):
        out += text(36 * s, h - (90 + 16 * i) * s, line, 11 * s)
    return bytes(out)
