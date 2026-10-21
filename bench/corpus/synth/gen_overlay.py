"""Generators for things painted over or around page text: markup annotations, transparency over
text, page boxes that disagree, and form widgets with appearance streams.

The phase-1 probe found these classes failing most often (visual-diff-high, covered-text-desync,
ghost-glyphs on annotations and forms; page-size mismatches on PDFium test files).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from rawpdf import Doc, b, label_page, pdf_string, rect, text
from gen_raw import WORDS, circle
from registry import generator


def sw(s: str, font: str = "Times-Roman", size: float = 11) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(s, font, size)


class Body:
    """A page of body text with known word positions (Times-Roman, F2)."""

    def __init__(self, rng: random.Random, title: str, lines: int = 42, size: float = 11,
                 x: float = 72, top: float = 700, lead: float = 14.5, width: float = 468):
        self.size, self.x = size, x
        self.lines: list[tuple[float, list[str]]] = []
        c = bytearray(text(x, top + 40, title, 16, "F4"))
        for i in range(lines):
            words: list[str] = []
            while sw(" ".join(words + ["word"]), size=size) < width:
                words.append(rng.choice(WORDS))
            y = top - i * lead
            self.lines.append((y, words))
            c += text(x, y, " ".join(words), size, "F2")
        self.content = bytes(c)

    def word_box(self, line: int, first: int, count: int = 1) -> tuple[float, float, float, float]:
        y, words = self.lines[line]
        pre = " ".join(words[:first]) + (" " if first else "")
        x0 = self.x + sw(pre, size=self.size)
        x1 = x0 + sw(" ".join(words[first:first + count]), size=self.size)
        return x0, y - 0.22 * self.size, x1, y + 0.78 * self.size

    def line_box(self, line: int) -> tuple[float, float, float, float]:
        return self.word_box(line, 0, len(self.lines[line][1]))


def quad(x0, y0, x1, y1) -> str:
    return f"[{x0:.2f} {y1:.2f} {x1:.2f} {y1:.2f} {x0:.2f} {y0:.2f} {x1:.2f} {y0:.2f}]"


def rstr(x0, y0, x1, y1) -> str:
    return f"[{x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f}]"


def form(d: Doc, bbox: tuple, content: bytes, res: str = "", matrix: str = "") -> int:
    return d.stream(content, f"/Type /XObject /Subtype /Form /BBox {rstr(*bbox)} "
                             f"{'/Matrix ' + matrix if matrix else ''} /Resources << {res} >>")


def attach(d: Doc, page: int, annots: list[int]) -> None:
    d.objs[page] = d.objs[page][:-2] + b" /Annots [" + " ".join(f"{a} 0 R" for a in annots).encode() + b"] >>"


META = "/T (Corpus Tester) /M (D:20261020120000Z) /CreationDate (D:20261020120000Z)"


# --------------------------------------------------------------------------- markup annotations

def markup_page(d: Doc, rng: random.Random, title: str, with_ap: bool, rotate: int = 0) -> None:
    bd = Body(rng, title)
    pg = d.page(bd.content, extra=f"/Rotate {rotate}" if rotate else "")
    gs = "/ExtGState << /M << /BM /Multiply /ca 1 >> >>"
    helv = f"/Font << /Helv {d.fonts['F1']} 0 R /HeBo {d.fonts['F4']} 0 R >>"
    annots = []

    def add(body: str, ap: int | None = None) -> int:
        n = d.add(f"<< /Type /Annot {body} {META} /F 4 " + (f"/AP << /N {ap} 0 R >> " if ap and with_ap else "") + ">>")
        annots.append(n)
        return n

    for k, (ln, w0, cnt) in enumerate([(2, 1, 3), (5, 0, 6), (9, 2, 2), (14, 4, 5), (20, 0, 4), (27, 3, 3)]):
        x0, y0, x1, y1 = bd.word_box(ln, w0, cnt)
        ap = form(d, (x0, y0, x1, y1), b"/M gs 1 0.92 0.23 rg %.2f %.2f %.2f %.2f re f" % (x0, y0, x1 - x0, y1 - y0), gs) if with_ap else None
        add(f"/Subtype /Highlight /Rect {rstr(x0, y0, x1, y1)} /QuadPoints {quad(x0, y0, x1, y1)} /C [1 0.92 0.23] "
            f"/CA 1 /Contents (highlight {k + 1})", ap)
    # a highlight across two lines (one annotation, two quads)
    a0, a1 = bd.word_box(31, 5, 4), bd.word_box(32, 0, 3)
    ap = form(d, (a1[0], a1[1], a0[2], a0[3]), b"/M gs 0.5 1 0.5 rg %.2f %.2f %.2f %.2f re f %.2f %.2f %.2f %.2f re f" % (
        a0[0], a0[1], a0[2] - a0[0], a0[3] - a0[1], a1[0], a1[1], a1[2] - a1[0], a1[3] - a1[1]), gs) if with_ap else None
    add(f"/Subtype /Highlight /Rect {rstr(a1[0], a1[1], a0[2], a0[3])} /QuadPoints [{quad(*a0)[1:-1]} {quad(*a1)[1:-1]}] /C [0.5 1 0.5]", ap)
    for sub, ln, col, yoff in (("Underline", 11, "0 0 1", 0.0), ("StrikeOut", 17, "1 0 0", 0.35), ("Squiggly", 23, "0 0.6 0", 0.0)):
        x0, y0, x1, y1 = bd.word_box(ln, 1, 4)
        yy = y0 + yoff * (y1 - y0) + 1
        if sub == "Squiggly":
            path = b"%.2f %.2f m " % (x0, yy) + b"".join(b"%.2f %.2f l " % (x, yy + (1.5 if i % 2 else -0.5))
                                                       for i, x in enumerate(frange(x0, x1, 2.5)))
        else:
            path = b"%.2f %.2f m %.2f %.2f l " % (x0, yy, x1, yy)
        ap = form(d, (x0, y0, x1, y1), b"%s RG 1 w " % col.encode() + path + b"S") if with_ap else None
        add(f"/Subtype /{sub} /Rect {rstr(x0, y0, x1, y1)} /QuadPoints {quad(x0, y0, x1, y1)} /C [{col}]", ap)
    # ink scribble in the margin and over text
    pts = [(520 + 25 * math.sin(t / 3), 300 + t * 6) for t in range(40)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    r = (min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2)
    ap = form(d, r, b"0.8 0 0.8 RG 2 w 1 J 1 j " + b"%.2f %.2f m " % pts[0] + b"".join(b"%.2f %.2f l " % p for p in pts[1:]) + b"S") if with_ap else None
    add(f"/Subtype /Ink /Rect {rstr(*r)} /InkList [[{' '.join(f'{x:.2f} {y:.2f}' for x, y in pts)}]] /C [0.8 0 0.8] /BS << /W 2 >>", ap)
    # free text box over the body text
    r = (300, 470, 520, 520)
    ft = b"1 1 0.85 rg 0 0 0 RG 1 w 300.5 470.5 219 49 re B BT /Helv 10 Tf 0 g 306 506 Td (FreeText comment drawn over body) Tj 0 -13 Td (text; its words are annotation text.) Tj ET"
    ap = form(d, r, ft, helv) if with_ap else None
    add(f"/Subtype /FreeText /Rect {rstr(*r)} /Contents (FreeText comment drawn over body text; its words are annotation text.) "
        f"/DA (/Helv 10 Tf 0 g) /DS (font: Helvetica 10pt) /C [1 1 0.85] /BS << /W 1 >>", ap)
    # stamp
    r = (360, 120, 540, 180)
    st = b"0.85 0.1 0.1 RG 0.85 0.1 0.1 rg 3 w 362 122 176 56 re S BT /HeBo 28 Tf 375 140 Td (APPROVED) Tj ET"
    ap = form(d, r, st, helv) if with_ap else None
    add(f"/Subtype /Stamp /Rect {rstr(*r)} /Name /Approved /Contents (Approved stamp)", ap)
    # sticky note with popup
    r = (40, 600, 60, 620)
    ap = form(d, r, b"1 0.9 0.3 rg 0 G 0.5 w 40.5 600.5 19 19 re B 0 G 44 615 m 56 615 l 44 610 m 56 610 l 44 605 m 52 605 l S") if with_ap else None
    note = add(f"/Subtype /Text /Rect {rstr(*r)} /Name /Comment /Open false /C [1 0.9 0.3] /Contents (Margin note on line five)", ap)
    pop = d.add(f"<< /Type /Annot /Subtype /Popup /Rect [60 520 240 620] /Parent {note} 0 R /Open false >>")
    annots.append(pop)
    d.objs[note] = d.objs[note][:-2] + b" /Popup %d 0 R >>" % pop
    # square and circle markup around words
    x0, y0, x1, y1 = bd.word_box(36, 2, 3)
    r = (x0 - 3, y0 - 3, x1 + 3, y1 + 3)
    ap = form(d, r, b"1 0 0 RG 1.5 w %.2f %.2f %.2f %.2f re S" % (r[0] + 0.75, r[1] + 0.75, r[2] - r[0] - 1.5, r[3] - r[1] - 1.5)) if with_ap else None
    add(f"/Subtype /Square /Rect {rstr(*r)} /C [1 0 0] /BS << /W 1.5 >>", ap)
    x0, y0, x1, y1 = bd.word_box(39, 1, 2)
    r = (x0 - 6, y0 - 5, x1 + 6, y1 + 5)
    cx, cy, rr = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, (r[3] - r[1]) / 2 - 1
    ap = form(d, r, b"0 0 1 RG 1 w " + ellipse(cx, cy, (r[2] - r[0]) / 2 - 1, rr) + b"S") if with_ap else None
    add(f"/Subtype /Circle /Rect {rstr(*r)} /C [0 0 1] /BS << /W 1 >>", ap)
    attach(d, pg, annots)


def frange(a: float, b_: float, step: float):
    x = a
    while x <= b_:
        yield x
        x += step


def ellipse(cx: float, cy: float, rx: float, ry: float) -> bytes:
    kx, ky = 0.5523 * rx, 0.5523 * ry
    return (b"%.2f %.2f m %.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c %.2f %.2f %.2f %.2f %.2f %.2f c h " % (
                cx + rx, cy, cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry,
                cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy, cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry,
                cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy))


@generator("markup", ["with-appearances", "without-appearances", "rotated-pages", "many-highlights",
                      "appearance-transforms"])
def markup(tmp: Path) -> dict:
    """Body text with highlight/underline/strikeout/squiggly/ink/FreeText/stamp/note/square/circle markup."""
    out = {}
    for variant, with_ap, rots in (("with-appearances", True, (0, 0, 0)), ("without-appearances", False, (0, 0, 0)),
                                   ("rotated-pages", True, (90, 180, 270))):
        d = Doc(f"Markup annotations: {variant}")
        rng = random.Random(41)
        for i, r in enumerate(rots):
            markup_page(d, rng, f"Annotated page {i + 1} ({variant}, /Rotate {r})", with_ap, r)
        out[variant] = d.finish(f"/AcroForm << /Fields [] /DR << /Font << /Helv {d.fonts['F1']} 0 R >> >> /DA (/Helv 0 Tf 0 g) >>")

    d = Doc("Many highlights")
    rng = random.Random(42)
    for p in range(10):
        bd = Body(rng, f"Every line highlighted, page {p + 1}")
        pg = d.page(bd.content)
        annots = []
        for ln in range(len(bd.lines)):
            box = bd.line_box(ln)
            col = ("1 0.92 0.23", "0.5 1 0.5", "0.6 0.8 1")[ln % 3]
            ap = form(d, box, b"/M gs %s rg %.2f %.2f %.2f %.2f re f" % (col.encode(), box[0], box[1], box[2] - box[0], box[3] - box[1]),
                      "/ExtGState << /M << /BM /Multiply >> >>")
            annots.append(d.add(f"<< /Type /Annot /Subtype /Highlight /Rect {rstr(*box)} /QuadPoints {quad(*box)} /C [{col}] "
                                f"/F 4 {META} /AP << /N {ap} 0 R >> >>"))
        attach(d, pg, annots)
    out["many-highlights"] = d.finish()

    d = Doc("Appearance streams that need transforming")
    rng = random.Random(43)
    bd = Body(rng, "Appearance BBox, Matrix and Rect disagree", lines=30)
    pg = d.page(bd.content)
    annots = []
    helv = f"/Font << /Helv {d.fonts['F1']} 0 R /HeBo {d.fonts['F4']} 0 R >>"
    x0, y0, x1, y1 = bd.word_box(3, 1, 5)
    ap = form(d, (0, 0, 100, 10), b"/M gs 1 0.9 0.2 rg 0 0 100 10 re f", "/ExtGState << /M << /BM /Multiply >> >>")
    annots.append(d.add(f"<< /Type /Annot /Subtype /Highlight /Rect {rstr(x0, y0, x1, y1)} /QuadPoints {quad(x0, y0, x1, y1)} "
                        f"/C [1 0.9 0.2] /F 4 /AP << /N {ap} 0 R >> /Contents (AP BBox 100x10 at origin, scaled into Rect) >>"))
    ang = math.radians(30)
    ca, sa = math.cos(ang), math.sin(ang)
    corners = [(0, 0), (180, 0), (0, 60), (180, 60)]
    tx = [(ca * x - sa * y, sa * x + ca * y) for x, y in corners]
    bx0, by0 = min(p[0] for p in tx), min(p[1] for p in tx)
    bx1, by1 = max(p[0] for p in tx), max(p[1] for p in tx)
    r = (330, 200, 330 + bx1 - bx0, 200 + by1 - by0)
    ap = form(d, (0, 0, 180, 60), b"0.1 0.3 0.8 RG 0.1 0.3 0.8 rg 3 w 2 2 176 56 re S BT /HeBo 26 Tf 14 20 Td (RECEIVED) Tj ET",
              helv, f"[{ca:.5f} {sa:.5f} {-sa:.5f} {ca:.5f} 0 0]")
    annots.append(d.add(f"<< /Type /Annot /Subtype /Stamp /Rect {rstr(*r)} /F 4 /AP << /N {ap} 0 R >> /Contents (Stamp with a 30 degree /Matrix) >>"))
    on = form(d, (0, 0, 20, 20), b"0 0.6 0 rg 0 0 20 20 re f")
    off = form(d, (0, 0, 20, 20), b"0.8 0 0 rg 0 0 20 20 re f")
    annots.append(d.add(f"<< /Type /Annot /Subtype /Square /Rect [60 200 80 220] /F 4 /AP << /N << /On {on} 0 R /Off {off} 0 R >> >> /AS /On "
                        f"/Contents (Appearance state On: green, Off: red) >>"))
    big = form(d, (0, 0, 400, 100), b"0.95 0.95 1 rg 0 0 1 RG 0 0 400 100 re B BT /Helv 14 Tf 0 g 10 70 Td (FreeText AP BBox is 400x100) Tj 0 -20 Td (but Rect is 200x50; it must be scaled.) Tj ET", helv)
    annots.append(d.add(f"<< /Type /Annot /Subtype /FreeText /Rect [60 100 260 150] /F 4 /DA (/Helv 14 Tf 0 g) "
                        f"/Contents (FreeText AP BBox is 400x100 but Rect is 200x50) /AP << /N {big} 0 R >> >>"))
    attach(d, pg, annots)
    out["appearance-transforms"] = d.finish(f"/AcroForm << /Fields [] /DR << {helv} >> /DA (/Helv 0 Tf 0 g) >>")
    return out


# --------------------------------------------------------------------------- transparency over text

@generator("text-overlay", ["translucent-rects", "watermark-over", "watermark-under", "softmask-text", "text-over-image"])
def text_overlay(tmp: Path) -> dict:
    """Translucent paint over and under body text: rects, watermarks, soft-masked text, text over an image."""
    out = {}
    gs = ("/ExtGState << /A35 << /ca 0.35 /CA 0.35 >> /A20 << /ca 0.25 >> /MUL << /BM /Multiply /ca 0.8 >> "
          "/SCR << /BM /Screen >> /A80 << /ca 0.8 >> >>")

    def wm(word: str) -> bytes:
        return b"q /A20 gs 0.8 0 0 rg BT /F4 80 Tf 0.7071 0.7071 -0.7071 0.7071 100 140 Tm " + pdf_string(word) + b" Tj ET Q\n"

    d = Doc("Translucent rectangles over text")
    rng = random.Random(51)
    for p in range(2):
        bd = Body(rng, f"Translucent paint over text, page {p + 1}")
        c = bytearray(bd.content)
        for i, ln in enumerate(range(1, 40, 4)):
            x0, y0, x1, y1 = bd.line_box(ln)
            mode = ("/A35", "/MUL", "/SCR")[i % 3]
            col = ("1 1 0", "0.3 0.6 1", "1 0.4 0.4")[i % 3]
            c += b"q %s gs %s rg %.2f %.2f %.2f %.2f re f Q\n" % (mode.encode(), col.encode(), x0, y0, x1 - x0, y1 - y0)
        c += b"q /A35 gs 0 0 0 rg 300 380 200 120 re f Q\n"
        c += b"q /A80 gs 1 1 1 rg 72 200 300 60 re f Q\n"
        d.page(bytes(c), res=gs)
    out["translucent-rects"] = d.finish()

    for variant, over in (("watermark-over", True), ("watermark-under", False)):
        d = Doc(f"Diagonal watermark {'over' if over else 'under'} text")
        rng = random.Random(52)
        for p in range(2):
            bd = Body(rng, f"Watermark drawn {'after' if over else 'before'} the body text, page {p + 1}")
            c = (bd.content + wm("CONFIDENTIAL")) if over else (wm("CONFIDENTIAL") + bd.content)
            d.page(c, res=gs)
        out[variant] = d.finish()

    d = Doc("Text faded by a soft mask")
    rng = random.Random(53)
    bd = Body(rng, "Body text inside a transparency group with a luminosity mask")
    fn = d.add("<< /FunctionType 2 /Domain [0 1] /C0 [1] /C1 [0.15] /N 1 >>")
    mask = form(d, (0, 0, 612, 792), b"/Sh sh", f"/Shading << /Sh << /ShadingType 2 /ColorSpace /DeviceGray /Coords [0 760 0 60] /Function {fn} 0 R /Extend [true true] >> >>")
    d.objs[mask] = d.objs[mask].replace(b"/Resources", b"/Group << /S /Transparency /CS /DeviceGray >> /Resources", 1)
    grp = d.stream(bd.content, f"/Type /XObject /Subtype /Form /BBox [0 0 612 792] /Group << /S /Transparency /I true >> "
                               f"/Resources << /Font << {d.font_res()} >> >>")
    d.page(b"q /SM gs /Body Do Q\n" + text(72, 40, "The text above fades towards the bottom; it is still selectable.", 10),
           res=f"/XObject << /Body {grp} 0 R >> /ExtGState << /SM << /SMask << /Type /Mask /S /Luminosity /G {mask} 0 R >> >> >>")
    out["softmask-text"] = d.finish()

    d = Doc("Text over a photo-like image")
    W, H = 200, 260
    rgb = bytes(v for y in range(H) for x in range(W)
                for v in (int(127 + 120 * math.sin(x / 17 + y / 31)), int(127 + 120 * math.sin(y / 13)), int(127 + 120 * math.cos(x / 23))))
    img = d.stream(rgb, f"/Type /XObject /Subtype /Image /Width {W} /Height {H} /ColorSpace /DeviceRGB /BitsPerComponent 8")
    rng = random.Random(54)
    bd = Body(rng, "Slide-style text over a full-page image", lines=20, size=16, lead=24)
    c = b"q 612 0 0 792 0 0 cm /Im Do Q q /A80 gs 1 1 1 rg 60 200 492 560 re f Q\n" + bd.content
    c += b"q /SCR gs 1 1 1 rg BT /F4 40 Tf 72 120 Td (Screen-blended title text) Tj ET Q\n"
    c += b"q /A35 gs 0 0 0 rg BT /F4 30 Tf 72 70 Td (35% black caption over image) Tj ET Q\n"
    d.page(c, res=f"/XObject << /Im {img} 0 R >> " + gs)
    out["text-over-image"] = d.finish()
    return out


# --------------------------------------------------------------------------- page boxes

def box_page(label: str, notes: list[str], mb: tuple, extra_lines: int = 0) -> bytes:
    """Content that marks the MediaBox corners and draws a 72 pt grid with coordinates."""
    x0, y0, x1, y1 = (min(mb[0], mb[2]), min(mb[1], mb[3]), max(mb[0], mb[2]), max(mb[1], mb[3]))
    c = bytearray(b"0.85 G 0.5 w ")
    gx = math.floor(x0 / 72) * 72
    while gx <= x1:
        c += b"%g %g m %g %g l S " % (gx, y0, gx, y1)
        gx += 72
    gy = math.floor(y0 / 72) * 72
    while gy <= y1:
        c += b"%g %g m %g %g l S " % (x0, gy, x1, gy)
        gy += 72
    c += b"0 g\n"
    for cx, cy, name in ((x0, y0, "MB bottom-left"), (x1, y0, "MB bottom-right"), (x0, y1, "MB top-left"), (x1, y1, "MB top-right")):
        c += b"1 0 0 rg %g %g 12 12 re f 0 g " % (cx - 6, cy - 6)
        c += text(cx + (8 if cx == x0 else -90), cy + (8 if cy == y0 else -16), f"{name} ({cx:g},{cy:g})", 8)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    c += text(mx - 150, my + 40, label, 16, "F4")
    for i, n in enumerate(notes):
        c += text(mx - 150, my + 18 - 14 * i, n, 10)
    c += b"0 0 1 RG 3 w %g %g m %g %g l S 0 0 1 rg %g %g m %g %g l %g %g l f\n" % (
        mx, my - 120, mx, my - 50, mx, my - 40, mx - 10, my - 58, mx + 10, my - 58)
    return bytes(c)


@generator("pageboxes", ["crop-rotate-grid", "crop-outside-media", "negative-and-inverted", "inherited-boxes",
                         "fractional-boxes", "all-boxes-differ"])
def pageboxes(tmp: Path) -> dict:
    """CropBox vs MediaBox vs /Rotate combinations, boxes outside/inverted/negative/inherited/fractional."""
    out = {}
    d = Doc("CropBox x Rotate grid")
    crops = {"no CropBox": None, "CropBox inset 72": (72, 72, 540, 720), "CropBox bottom-left half": (0, 0, 306, 396),
             "CropBox top-right offset": (200, 300, 612, 792)}
    for cname, cb in crops.items():
        for rot in (0, 90, 180, 270):
            vis = (cb[2] - cb[0], cb[3] - cb[1]) if cb else (612, 792)
            if rot % 180:
                vis = vis[::-1]
            notes = [f"MediaBox [0 0 612 792], {cname}, /Rotate {rot}",
                     f"Visible page should be {vis[0]:g} x {vis[1]:g} pt; arrow points up in content."]
            extra = (f"/CropBox [{' '.join(f'{v:g}' for v in cb)}] " if cb else "") + f"/Rotate {rot}"
            c = box_page(f"{cname}, /Rotate {rot}", notes, (0, 0, 612, 792))
            if cb:  # put the label inside the crop region too
                c += text(cb[0] + 10, cb[3] - 20, f"inside crop: {cname}, rot {rot}", 11, "F4")
            d.page(c, extra=extra)
    out["crop-rotate-grid"] = d.finish()

    d = Doc("CropBox partly or fully outside MediaBox")
    for name, cb, note in (("CropBox extends past MediaBox", "-100 -100 400 500", "Effective box is the intersection: [0 0 400 500]."),
                           ("CropBox entirely outside MediaBox", "700 900 900 1100", "Readers fall back to MediaBox or show nothing."),
                           ("CropBox equals MediaBox", "0 0 612 792", "No visible change."),
                           ("Zero-area CropBox", "100 100 100 300", "Degenerate box; readers differ.")):
        d.page(box_page(name, [note, f"CropBox [{cb}]"], (0, 0, 612, 792)), extra=f"/CropBox [{cb}]")
    out["crop-outside-media"] = d.finish()

    d = Doc("Negative and inverted boxes")
    d.page(box_page("MediaBox [-306 -396 306 396]", ["Origin at the page centre."], (-306, -396, 306, 396)), box="-306 -396 306 396")
    d.page(box_page("MediaBox [612 792 0 0]", ["Corners given in reverse order; must normalise."], (0, 0, 612, 792)), box="612 792 0 0")
    d.page(box_page("Inverted CropBox [540 720 72 72]", ["CropBox corners reversed."], (0, 0, 612, 792)), extra="/CropBox [540 720 72 72]")
    d.page(box_page("MediaBox [-1000 -1000 -388 -208]", ["Entirely negative coordinates."], (-1000, -1000, -388, -208)),
           box="-1000 -1000 -388 -208", extra="/Rotate 90")
    out["negative-and-inverted"] = d.finish()

    d = Doc("Boxes and Rotate inherited from the page tree")
    inter = d.reserve()
    kids = [d.page(box_page(f"Inherited page {i}", ["No MediaBox/CropBox/Rotate on the page itself.",
                                                    "Parent Pages: MediaBox A4 landscape, CropBox inset 36, Rotate 270."],
                            (0, 0, 842, 595)), parent=inter) for i in (1, 2)]
    for k in kids:  # remove page-level MediaBox so it is inherited
        d.objs[k] = d.objs[k].replace(b"/MediaBox [0 0 612 792] ", b"")
    ov = d.page(box_page("Overrides parent", ["Page sets its own MediaBox (Letter) and /Rotate 0;",
                                              "CropBox still inherited from the parent (inset 36 of A4 landscape)."],
                         (0, 0, 612, 792)), parent=inter, extra="/Rotate 0")
    d.set(inter, f"<< /Type /Pages /Parent {d.pages} 0 R /Kids [{kids[0]} 0 R {kids[1]} 0 R {ov} 0 R] /Count 3 "
                 f"/MediaBox [0 0 842 595] /CropBox [36 36 806 559] /Rotate 270 >>")
    d.page(box_page("Plain Letter page", ["Not under the intermediate node."], (0, 0, 612, 792)))
    out["inherited-boxes"] = d.finish(kids=[inter] + d.kids, count=4)

    d = Doc("Fractional boxes")
    d.page(box_page("MediaBox [0.5 0.5 595.78 842.39]", ["Fractional MediaBox origin and size."], (0.5, 0.5, 595.78, 842.39)),
           box="0.5 0.5 595.78 842.39")
    d.page(box_page("CropBox [3.3 7.7 590.01 830.1]", ["Fractional CropBox, MediaBox A4."], (0, 0, 595.28, 841.89)),
           box="0 0 595.28 841.89", extra="/CropBox [3.3 7.7 590.01 830.1]")
    d.page(box_page("UserUnit 1.5 with CropBox", ["MediaBox Letter, UserUnit 1.5, CropBox inset 50.5."], (0, 0, 612, 792)),
           extra="/UserUnit 1.5 /CropBox [50.5 50.5 561.5 741.5]")
    d.page(box_page("595.276 x 841.89 /Rotate 90 with odd CropBox", ["CropBox [10.25 20.75 585.5 820.125]."], (0, 0, 595.276, 841.89)),
           box="0 0 595.276 841.89", extra="/Rotate 90 /CropBox [10.25 20.75 585.5 820.125]")
    d.version = "1.6"
    out["fractional-boxes"] = d.finish()

    d = Doc("All page boxes differ")
    c = box_page("Media, Crop, Bleed, Trim, Art all differ", ["Viewers should show the CropBox (blue frame).",
                                                              "Bleed red, Trim green, Art orange."], (0, 0, 700, 900))
    for col, bx in (("0 0 1", (40, 40, 660, 860)), ("1 0 0", (50, 50, 650, 850)), ("0 0.6 0", (60, 60, 640, 840)), ("1 0.5 0", (90, 90, 610, 810))):
        c += b"%s RG 2 w %g %g %g %g re S\n" % (col.encode(), bx[0], bx[1], bx[2] - bx[0], bx[3] - bx[1])
    d.page(c, 700, 900, extra="/CropBox [40 40 660 860] /BleedBox [50 50 650 850] /TrimBox [60 60 640 840] /ArtBox [90 90 610 810]")
    d.page(c, 700, 900, extra="/CropBox [40 40 660 860] /BleedBox [50 50 650 850] /TrimBox [60 60 640 840] /ArtBox [90 90 610 810] /Rotate 90")
    out["all-boxes-differ"] = d.finish()
    return out


# --------------------------------------------------------------------------- forms with appearances

class Form:
    def __init__(self, d: Doc):
        self.d, self.fields, self.widgets = d, [], []
        self.zadb = d.add("<< /Type /Font /Subtype /Type1 /BaseFont /ZapfDingbats >>")
        self.res = f"/Font << /Helv {d.fonts['F1']} 0 R /TiIt {d.fonts['F5']} 0 R /ZaDb {self.zadb} 0 R >>"

    def ap(self, w: float, h: float, body: bytes, bg=(0.93, 0.95, 1.0), border=(0.3, 0.3, 0.3), matrix: str = "") -> int:
        c = b"%g %g %g rg 0 0 %g %g re f %g %g %g RG 1 w 0.5 0.5 %g %g re S " % (*bg, w, h, *border, w - 1, h - 1) + body
        return form(self.d, (0, 0, w, h), c, self.res, matrix)

    def text_ap(self, w: float, h: float, value: str, size: float = 11, q: int = 0, matrix: str = "", lines: int = 1) -> int:
        body = bytearray(b"/Tx BMC q 1 1 %g %g re W n BT /Helv %g Tf 0 g " % (w - 2, h - 2, size))
        for i, line in enumerate(value.split("\n")[:lines] if lines > 1 else [value]):
            tw = sw(line, "Helvetica", size)
            x = 2 if q == 0 else (w - tw) / 2 if q == 1 else w - tw - 2
            y = (h - size) / 2 + 0.22 * size if lines == 1 else h - (i + 1) * (size + 2)
            body += b"1 0 0 1 %.2f %.2f Tm " % (x, y) + pdf_string(line) + b" Tj "
        body += b"ET Q EMC"
        return self.ap(w, h, bytes(body), matrix=matrix)

    def widget(self, page: int, s: str, top: bool = True) -> int:
        n = self.d.add(f"<< /Type /Annot /Subtype /Widget /P {page} 0 R /F 4 {s} >>")
        self.widgets.append(n)
        if top:
            self.fields.append(n)
        return n

    def acroform(self, need: bool = False) -> str:
        return (f"/AcroForm << /Fields [{' '.join(f'{f} 0 R' for f in self.fields)}] /NeedAppearances {'true' if need else 'false'} "
                f"/DR << {self.res} >> /DA (/Helv 0 Tf 0 g) >>")


def labels(rows: list[tuple[float, str]]) -> bytes:
    return b"".join(text(40, y, lab, 11) for y, lab in rows)


@generator("forms-ap", ["acrobat-style", "rotated-widgets", "stale-appearance", "flags"])
def forms_ap(tmp: Path) -> dict:
    """AcroForm widgets with explicit appearance streams: alignments, comb, states, rotation, stale APs, flags."""
    out = {}
    d = Doc("Form widgets with appearance streams")
    f = Form(d)
    page = d.reserve()
    rows = []
    y = 700
    for q, name in ((0, "left"), (1, "centre"), (2, "right")):
        ap = f.text_ap(260, 22, f"Aligned {name}", q=q)
        f.widget(page, f"/FT /Tx /T (align_{name}) /V (Aligned {name}) /Q {q} /DA (/Helv 11 Tf 0 g) /Rect [200 {y} 460 {y + 22}] "
                       f"/MK << /BG [0.93 0.95 1] /BC [0.3 0.3 0.3] >> /AP << /N {ap} 0 R >>")
        rows.append((y + 6, f"Text, Q {q} ({name})"))
        y -= 34
    ap = f.text_ap(260, 22, "auto-sized font", size=9)
    f.widget(page, f"/FT /Tx /T (autosize) /V (auto-sized font) /DA (/Helv 0 Tf 0 g) /Rect [200 {y} 460 {y + 22}] /AP << /N {ap} 0 R >>")
    rows.append((y + 6, "Text, font size 0 (auto)"))
    y -= 34
    comb = b"/Tx BMC BT /Helv 14 Tf 0 g " + b"".join(b"1 0 0 1 %.2f 6 Tm (%s) Tj " % (i * 30 + 11, ch.encode()) for i, ch in enumerate("20261020")) + b"ET "
    comb += b"0.6 G " + b"".join(b"%g 0 m %g 24 l S " % (i * 30, i * 30) for i in range(1, 8)) + b"EMC"
    ap = f.ap(240, 24, comb)
    f.widget(page, f"/FT /Tx /T (comb) /Ff {(1 << 24) | (1 << 23)} /MaxLen 8 /V (20261020) /DA (/Helv 14 Tf 0 g) "
                   f"/Rect [200 {y} 440 {y + 24}] /AP << /N {ap} 0 R >>")
    rows.append((y + 6, "Comb field, 8 cells"))
    y -= 90
    ml = "First line of a note\nsecond line\nthird line with more words"
    ap = f.text_ap(300, 70, ml, size=11, lines=3)
    f.widget(page, f"/FT /Tx /T (multiline) /Ff 4096 /V ({ml.replace(chr(10), chr(92) + 'r')}) /DA (/Helv 11 Tf 0 g) "
                   f"/Rect [200 {y} 500 {y + 70}] /AP << /N {ap} 0 R >>")
    rows.append((y + 50, "Multiline"))
    y -= 34
    ap = f.text_ap(200, 22, "********")
    f.widget(page, f"/FT /Tx /T (password) /Ff 8192 /DA (/Helv 11 Tf 0 g) /Rect [200 {y} 400 {y + 22}] /AP << /N {ap} 0 R >>")
    rows.append((y + 6, "Password (AP shows stars, no /V)"))
    y -= 34
    on = f.ap(18, 18, b"q BT /ZaDb 14 Tf 0 g 3 4 Td (4) Tj ET Q", bg=(1, 1, 1))
    off = f.ap(18, 18, b"", bg=(1, 1, 1))
    down_on = f.ap(18, 18, b"q BT /ZaDb 14 Tf 0 g 3 4 Td (4) Tj ET Q", bg=(0.75, 0.75, 0.75))
    down_off = f.ap(18, 18, b"", bg=(0.75, 0.75, 0.75))
    for i, (st, lab) in enumerate((("Yes", "on"), ("Off", "off"))):
        f.widget(page, f"/FT /Btn /T (check_{lab}) /V /{st} /AS /{st} /Rect [{200 + i * 60} {y} {218 + i * 60} {y + 18}] "
                       f"/MK << /CA (4) /BC [0 0 0] /BG [1 1 1] >> /DA (/ZaDb 0 Tf 0 g) "
                       f"/AP << /N << /Yes {on} 0 R /Off {off} 0 R >> /D << /Yes {down_on} 0 R /Off {down_off} 0 R >> >>")
    rows.append((y + 5, "Checkboxes (on, off) with down states"))
    y -= 34
    radio = d.reserve()
    kids = []
    for i, st in enumerate(("Bokmal", "Nynorsk", "Sami")):
        ron = f.ap(18, 18, b"0 g " + circle(9, 9, 4) + b"f", bg=(1, 1, 1))
        roff = f.ap(18, 18, b"", bg=(1, 1, 1))
        k = d.add(f"<< /Type /Annot /Subtype /Widget /P {page} 0 R /F 4 /Parent {radio} 0 R /Rect [{200 + i * 80} {y} {218 + i * 80} {y + 18}] "
                  f"/AS /{'Nynorsk' if st == 'Nynorsk' else 'Off'} /MK << /CA (l) /BC [0 0 0] >> /DA (/ZaDb 0 Tf 0 g) "
                  f"/AP << /N << /{st} {ron} 0 R /Off {roff} 0 R >> >> >>")
        kids.append(k)
        f.widgets.append(k)
    d.set(radio, f"<< /FT /Btn /T (language) /Ff {(1 << 15) | (1 << 14)} /V /Nynorsk /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>")
    f.fields.append(radio)
    rows.append((y + 5, "Radio with custom state names (Nynorsk)"))
    y -= 34
    ap = f.text_ap(200, 22, "Trondheim")
    f.widget(page, f"/FT /Ch /T (combo) /Ff {1 << 17} /Opt [(Oslo) (Boston) (Trondheim)] /V (Trondheim) /DA (/Helv 11 Tf 0 g) "
                   f"/Rect [200 {y} 400 {y + 22}] /AP << /N {ap} 0 R >>")
    rows.append((y + 6, "Combo box"))
    y -= 80
    lb = b"/Tx BMC 0.6 0.75 0.9 rg 1 33 198 15 re f BT /Helv 11 Tf 0 g 1 0 0 1 4 52 Tm (alpha) Tj 1 0 0 1 4 37 Tm (bravo) Tj 1 0 0 1 4 22 Tm (charlie) Tj 1 0 0 1 4 7 Tm (delta) Tj ET EMC"
    ap = f.ap(200, 66, lb)
    f.widget(page, f"/FT /Ch /T (listbox) /Opt [(alpha) (bravo) (charlie) (delta)] /V (bravo) /I [1] /DA (/Helv 11 Tf 0 g) "
                   f"/Rect [200 {y} 400 {y + 66}] /AP << /N {ap} 0 R >>")
    rows.append((y + 50, "List box (bravo selected)"))
    y -= 40
    btn = f.ap(120, 28, b"BT /Helv 12 Tf 0 g 30 9 Td (Submit) Tj ET", bg=(0.8, 0.8, 0.8))
    f.widget(page, f"/FT /Btn /T (submit) /Ff {1 << 16} /Rect [200 {y} 320 {y + 28}] /MK << /CA (Submit) /BG [0.8 0.8 0.8] >> /AP << /N {btn} 0 R >>")
    rows.append((y + 8, "Push button"))
    y -= 60
    sig = f.ap(250, 50, b"BT /TiIt 20 Tf 0 0 0.5 rg 10 18 Td (Corpus Tester) Tj ET 0 0 0.5 RG 10 12 m 240 12 l S", bg=(1, 1, 1))
    f.widget(page, f"/FT /Sig /T (signature) /Rect [200 {y} 450 {y + 50}] /AP << /N {sig} 0 R >>")
    rows.append((y + 20, "Signature (appearance only, not signed)"))
    cs = d.stream(text(40, 750, "Form fields with appearance streams (NeedAppearances false)", 16, "F4") + labels(rows))
    d.set(page, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Resources << /Font << {d.font_res()} >> >> "
                f"/Contents {cs} 0 R /Annots [{' '.join(f'{w} 0 R' for w in f.widgets)}] >>")
    d.kids.append(page)
    out["acrobat-style"] = d.finish(f.acroform())

    d = Doc("Rotated widgets")
    f = Form(d)
    page = d.reserve()
    rot = "[0 1 -1 0 0 0]"
    for i, (val, x) in enumerate((("Rotated field A", 100), ("Rotated field B", 160), ("Rotated field C", 220))):
        ap = f.text_ap(240, 24, val, matrix=rot)
        f.widget(page, f"/FT /Tx /T (rot{i}) /V ({val}) /DA (/Helv 11 Tf 0 g) /Rect [{x} 300 {x + 24} 540] "
                       f"/MK << /R 90 /BG [0.93 0.95 1] /BC [0.3 0.3 0.3] >> /AP << /N {ap} 0 R >>")
    on = f.ap(18, 18, b"q BT /ZaDb 14 Tf 0 g 3 4 Td (4) Tj ET Q", bg=(1, 1, 1), matrix=rot)
    off = f.ap(18, 18, b"", bg=(1, 1, 1), matrix=rot)
    f.widget(page, f"/FT /Btn /T (rotcheck) /V /Yes /AS /Yes /Rect [300 300 318 318] /MK << /R 90 /CA (4) >> "
                   f"/AP << /N << /Yes {on} 0 R /Off {off} 0 R >> >>")
    cs = d.stream(text(40, 750, "Page /Rotate 90; widgets /MK /R 90 with rotated appearance matrices.", 12, "F4")
                  + text(40, 730, "On screen the field text reads left to right, like the page title.", 10))
    d.set(page, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Rotate 90 /Resources << /Font << {d.font_res()} >> >> "
                f"/Contents {cs} 0 R /Annots [{' '.join(f'{w} 0 R' for w in f.widgets)}] >>")
    d.kids.append(page)
    out["rotated-widgets"] = d.finish(f.acroform())

    d = Doc("Stale appearance streams")
    f = Form(d)
    page = d.reserve()
    rows = []
    for i, (v, apv, need) in enumerate((("NEW value in /V", "OLD value in AP", "false"), ("Second NEW value", "Second OLD value", "false"))):
        y = 650 - i * 50
        ap = f.text_ap(260, 22, apv)
        f.widget(page, f"/FT /Tx /T (stale{i}) /V ({v}) /DA (/Helv 11 Tf 0 g) /Rect [250 {y} 510 {y + 22}] /AP << /N {ap} 0 R >>")
        rows.append((y + 6, f"/V and AP disagree ({i + 1})"))
    on = f.ap(18, 18, b"q BT /ZaDb 14 Tf 0 g 3 4 Td (4) Tj ET Q", bg=(1, 1, 1))
    off = f.ap(18, 18, b"", bg=(1, 1, 1))
    f.widget(page, f"/FT /Btn /T (stalecheck) /V /Yes /AS /Off /Rect [250 500 268 518] /AP << /N << /Yes {on} 0 R /Off {off} 0 R >> >>")
    rows.append((505, "Checkbox: /V Yes but /AS Off"))
    cs = d.stream(text(40, 750, "Appearance streams that do not match field values", 16, "F4")
                  + text(40, 730, "A viewer that regenerates appearances shows the NEW values; one that trusts /AP shows OLD.", 10) + labels(rows))
    d.set(page, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Resources << /Font << {d.font_res()} >> >> "
                f"/Contents {cs} 0 R /Annots [{' '.join(f'{w} 0 R' for w in f.widgets)}] >>")
    d.kids.append(page)
    out["stale-appearance"] = d.finish(f.acroform())

    d = Doc("Widget flags")
    f = Form(d)
    page = d.reserve()
    rows = []
    for i, (flag, ff, lab) in enumerate(((2, 0, "Hidden (F 2): nothing should show"), (32, 0, "NoView (F 32): nothing should show"),
                                         (4, 1, "ReadOnly field (Ff 1), printable"), (4 | 128, 0, "Locked annotation (F 128+4)"),
                                         (0, 0, "Not printable (F 0): visible on screen"), (4, 2, "Required field (Ff 2)"))):
        y = 650 - i * 50
        ap = f.text_ap(260, 22, f"field {i}: {lab.split(':')[0]}")
        n = f.widget(page, f"/FT /Tx /T (flag{i}) /Ff {ff} /V (field {i}) /DA (/Helv 11 Tf 0 g) /Rect [300 {y} 560 {y + 22}] /AP << /N {ap} 0 R >>")
        d.objs[n] = d.objs[n].replace(b"/F 4 ", b"/F %d " % flag, 1)
        rows.append((y + 6, lab))
    cs = d.stream(text(40, 750, "Widget annotation flags", 16, "F4") + labels(rows))
    d.set(page, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Resources << /Font << {d.font_res()} >> >> "
                f"/Contents {cs} 0 R /Annots [{' '.join(f'{w} 0 R' for w in f.widgets)}] >>")
    d.kids.append(page)
    out["flags"] = d.finish(f.acroform())
    return out
