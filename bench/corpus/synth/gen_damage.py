"""Encryption, file-structure variants, byte-level damage and incremental updates."""

from __future__ import annotations

import io
import re
import struct
import zlib
from pathlib import Path

from rawpdf import Doc, b, label_page, text
from registry import generator


def base_doc(title: str, pages: int = 3, compress: bool = False) -> Doc:
    d = Doc(title)
    for i in range(1, pages + 1):
        d.page(label_page(f"{title}: page {i} of {pages}", [
            "Body text so the page has something to extract.",
            f"Search marker: basemarker{i}"]), compress=compress)
    return d


# --------------------------------------------------------------------------- encryption

@generator("encrypt", ["owner-only-rc4-40", "owner-only-rc4-128", "owner-only-aes128", "owner-only-aes256",
                       "user-password-aes256", "user-password-rc4-128"])
def encrypt(tmp: Path) -> dict:
    """Encrypted files: owner password only (opens without prompt, restricted) and user password 'test'."""
    import pikepdf
    src = base_doc("Encrypted document").finish()
    no_copy = pikepdf.Permissions(extract=False, modify_other=False, print_highres=False)
    specs = {
        "owner-only-rc4-40": dict(owner="owner", user="", R=2, aes=False, allow=no_copy, metadata=False),
        "owner-only-rc4-128": dict(owner="owner", user="", R=3, aes=False, allow=no_copy, metadata=False),
        "owner-only-aes128": dict(owner="owner", user="", R=4, aes=True, allow=no_copy),
        "owner-only-aes256": dict(owner="owner", user="", R=6, allow=no_copy),
        "user-password-aes256": dict(owner="owner", user="test", R=6),
        "user-password-rc4-128": dict(owner="owner", user="test", R=3, aes=False, metadata=False),
    }
    out = {}
    for name, kw in specs.items():
        with pikepdf.open(io.BytesIO(src)) as pdf:
            buf = io.BytesIO()
            pdf.save(buf, encryption=pikepdf.Encryption(**kw))
            out[name] = buf.getvalue()
    return out


# --------------------------------------------------------------------------- structure (valid)

@generator("structure", ["object-streams", "linearized", "pdf-2.0", "version-1.0-header-1.7-catalog"])
def structure(tmp: Path) -> dict:
    """Valid structural variants: xref and object streams, linearized, PDF 2.0, catalog /Version override."""
    import pikepdf
    out = {}
    src = base_doc("Structure variants", 20, compress=True).finish()
    for name, kw in (("object-streams", dict(object_stream_mode=pikepdf.ObjectStreamMode.generate)),
                     ("linearized", dict(linearize=True)),
                     ("pdf-2.0", dict(force_version="2.0", object_stream_mode=pikepdf.ObjectStreamMode.generate))):
        with pikepdf.open(io.BytesIO(src)) as pdf:
            buf = io.BytesIO()
            pdf.save(buf, deterministic_id=True, **kw)
            out[name] = buf.getvalue()
    d = base_doc("Header 1.0, catalog Version 1.7", 2)
    d.version = "1.0"
    out["version-1.0-header-1.7-catalog"] = d.finish("/Version /1.7")
    return out


# --------------------------------------------------------------------------- damage

@generator("damaged", ["truncated-50pct", "truncated-90pct", "truncated-no-eof", "startxref-wrong",
                       "xref-offsets-shifted", "no-xref", "garbage-before-header", "no-header",
                       "trailing-garbage", "wrong-stream-lengths", "missing-objects", "page-count-wrong",
                       "cyclic-page-tree", "corrupt-flate", "objstm-truncated", "header-version-9.9",
                       "empty-file", "html-not-pdf"])
def damaged(tmp: Path) -> dict:
    """Broken files a viewer must reject cleanly or repair: truncation, bad xref, bad streams, cycles."""
    import pikepdf
    good = base_doc("Damaged document", 6).finish()
    out = {}
    out["truncated-50pct"] = good[: len(good) // 2]
    out["truncated-90pct"] = good[: len(good) * 9 // 10]
    out["truncated-no-eof"] = good[:-30]
    m = re.search(rb"startxref\n(\d+)", good)
    out["startxref-wrong"] = good[: m.start(1)] + b"%d" % (int(m.group(1)) - 123) + good[m.end(1):]

    def shift(mo: re.Match) -> bytes:
        return b"%010d 00000 n " % (int(mo.group(1)) + 7)
    out["xref-offsets-shifted"] = re.sub(rb"(\d{10}) 00000 n ", shift, good)
    out["no-xref"] = good[: good.rindex(b"xref\n0 ")] + b"%%EOF\n"
    out["garbage-before-header"] = (b"Content-Type: application/pdf\r\n\r\n" + bytes(range(256)) * 4) + good
    out["no-header"] = good[good.index(b"\n", good.index(b"\n") + 1) + 1:]
    out["trailing-garbage"] = good + b"\n" + b"garbage after EOF " * 200 + b"\n"
    out["wrong-stream-lengths"] = re.sub(rb"/Length (\d+)", lambda mo: b"/Length %d" % (int(mo.group(1)) * 2 + 5), good)

    d = base_doc("Missing objects", 3)
    pg = d.kids[1]
    d.objs[pg] = re.sub(rb"/Contents \d+ 0 R", b"/Contents 9999 0 R", d.objs[pg])
    d.objs[pg] = d.objs[pg].replace(b"/F1 ", b"/F1 9998 0 R /Fx ", 1)
    out["missing-objects"] = d.finish()

    out["page-count-wrong"] = base_doc("Count says 50", 3).finish(count=50)

    d = base_doc("Cyclic page tree", 3)
    inner = d.reserve()
    d.set(inner, f"<< /Type /Pages /Parent {d.pages} 0 R /Kids [{d.pages} 0 R {d.kids[2]} 0 R] /Count 2 >>")
    out["cyclic-page-tree"] = d.finish(kids=d.kids[:2] + [inner], count=4)

    d = base_doc("Corrupt flate stream", 3, compress=True)
    data = d.finish()
    first = data.index(b"stream\n", data.index(b"/FlateDecode")) + 7
    cor = bytearray(data)
    for k in range(first + 20, first + 40):
        cor[k] ^= 0x5A
    out["corrupt-flate"] = bytes(cor)

    with pikepdf.open(io.BytesIO(base_doc("Object streams, truncated", 30, compress=True).finish())) as pdf:
        buf = io.BytesIO()
        pdf.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate, deterministic_id=True)
        objstm = buf.getvalue()
    out["objstm-truncated"] = objstm[: int(len(objstm) * 0.7)]
    out["header-version-9.9"] = good.replace(b"%PDF-1.7", b"%PDF-9.9", 1)
    out["empty-file"] = b""
    out["html-not-pdf"] = (b"<!doctype html><html><head><title>Sign in</title></head>"
                           b"<body><p>This is an HTML login page served with a .pdf name.</p></body></html>\n")
    return out


# --------------------------------------------------------------------------- incremental updates

def append_table(data: bytes, objs: dict[int, bytes], size: int, root: int, prev: int, info: int | None,
                 free: dict[int, int] | None = None) -> bytes:
    out = bytearray(data)
    offs = {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n"
    entries = {n: b"%010d 00000 n \n" % o for n, o in offs.items()}
    for n, gen in (free or {}).items():
        entries[n] = b"0000000000 %05d f \n" % gen
    out += b"0 1\n0000000000 65535 f \n"
    for n in sorted(entries):
        out += b"%d 1\n" % n + entries[n]
    out += b"trailer\n<< /Size %d /Root %d 0 R /Prev %d " % (size, root, prev)
    if info:
        out += b"/Info %d 0 R " % info
    out += b">>\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


def append_xref_stream(data: bytes, objs: dict[int, bytes], size: int, root: int, prev: int, info: int | None) -> bytes:
    out = bytearray(data)
    offs = {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    xs = size
    offs[xs] = len(out)
    rows = b"".join(struct.pack(">BIH", 1, offs[n], 0) for n in sorted(offs))
    index = " ".join(f"{n} 1" for n in sorted(offs))
    body = zlib.compress(rows)
    out += (b"%d 0 obj\n<< /Type /XRef /Size %d /Root %d 0 R /Prev %d /W [1 4 2] /Index [%s] "
            b"/Filter /FlateDecode /Length %d %s>>\nstream\n" % (
                xs, size + 1, root, prev, index.encode(), len(body), b"/Info %d 0 R " % info if info else b""))
    out += body + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % offs[xs]
    return bytes(out)


def rev1() -> tuple[Doc, bytes, int]:
    d = Doc("Incremental updates")
    d.page(label_page("Revision 1, page 1", ["This text is from the ORIGINAL revision: originalrevisiontext."]), compress=False)
    d.page(label_page("Revision 1, page 2", ["Page 2 exists in revision 1."]), compress=False)
    data, offs, xref_at = d.serialise_pages()
    return d, data, xref_at


def _serialise_pages(self: Doc):
    self.set(self.pages, f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in self.kids)}] /Count {len(self.kids)} >>")
    self.set(self.catalog, f"<< /Type /Catalog /Pages {self.pages} 0 R >>")
    return self.serialise(self.catalog, self.info)


Doc.serialise_pages = _serialise_pages


def content_of(d: Doc, page: int) -> int:
    return int(re.search(rb"/Contents (\d+) 0 R", d.objs[page]).group(1))


@generator("incremental", ["three-revisions", "deleted-page", "broken-prev"])
def incremental(tmp: Path) -> dict:
    """Appended updates: replaced content, added annotation, page added via xref stream, page deleted, bad /Prev."""
    out = {}
    d, data, x1 = rev1()
    p1, p2 = d.kids
    size = max(d.objs) + 1
    annot = size
    c1 = content_of(d, p1)
    upd = {
        c1: d.stream_body(label_page("Revision 2, page 1", ["This text REPLACED revision 1: revisiontwotext."]), compress=False),
        annot: b"<< /Type /Annot /Subtype /Text /Rect [500 700 520 720] /Contents (Added in revision 2) /Open true >>",
        p1: d.objs[p1][:-2] + b" /Annots [%d 0 R] >>" % annot,
    }
    size2 = annot + 1
    data2 = append_table(data, upd, size2, d.catalog, x1, d.info)
    x2 = int(re.findall(rb"startxref\n(\d+)", data2)[-1])
    c3, p3 = size2, size2 + 1
    font_res = d.font_res()
    upd3 = {
        c3: d.stream_body(label_page("Revision 3, page 3", ["This page was added by an update with an xref stream."]), compress=False),
        p3: b(f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Resources << /Font << {font_res} >> >> /Contents {c3} 0 R >>"),
        d.pages: b(f"<< /Type /Pages /Kids [{p1} 0 R {p2} 0 R {p3} 0 R] /Count 3 >>"),
    }
    out["three-revisions"] = append_xref_stream(data2, upd3, p3 + 1, d.catalog, x2, d.info)
    data3 = out["three-revisions"]
    bad = data3[: data3.rindex(b"/Prev %d" % x2)] + b"/Prev %d" % (x2 + 5) + data3[data3.rindex(b"/Prev %d" % x2) + len(b"/Prev %d" % x2):]
    out["broken-prev"] = bad

    d, data, x1 = rev1()
    p1, p2 = d.kids
    upd = {d.pages: b(f"<< /Type /Pages /Kids [{p1} 0 R] /Count 1 >>")}
    out["deleted-page"] = append_table(data, upd, max(d.objs) + 1, d.catalog, x1, d.info, free={p2: 1})
    return out
