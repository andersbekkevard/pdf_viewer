"""Generators that write PDF objects by hand (see rawpdf.py)."""

from __future__ import annotations

import io
import math
import random
import struct
from pathlib import Path

from rawpdf import Doc, b, label_page, pdf_string, rect, text
from registry import generator

WORDS = ("the of and to in is that for it as was with be by on not he this are or his from at "
         "which but have an they you were her she there been one all we their has would when "
         "if will two more no out so said what up its about into than them can only other new "
         "some could time these may then do first any my now such like our over man me even "
         "most made after also did many before must through back years where much your way "
         "well down should because each just those people how too little state good very make "
         "world still own see men work long get here between both life being under never day "
         "same another know while last might us great old year off come since against go came "
         "right used take three viewer page render glyph font layer stream object matrix").split()


def prose(rng: random.Random, n: int) -> list[str]:
    return [rng.choice(WORDS) for _ in range(n)]


def circle(cx: float, cy: float, r: float) -> bytes:
    k = 0.5523 * r
    return (b"%g %g m %g %g %g %g %g %g c %g %g %g %g %g %g c "
            b"%g %g %g %g %g %g c %g %g %g %g %g %g c h\n" % (
                cx + r, cy,
                cx + r, cy + k, cx + k, cy + r, cx, cy + r,
                cx - k, cy + r, cx - r, cy + k, cx - r, cy,
                cx - r, cy - k, cx - k, cy - r, cx, cy - r,
                cx + k, cy - r, cx + r, cy - k, cx + r, cy))


def up_arrow(w: float, h: float) -> bytes:
    cx, s = w / 2, min(w, h) / 612
    return (b"0 0 1 RG 0 0 1 rg %g w %g %g m %g %g l S %g %g m %g %g l %g %g l f\n" % (
        6 * s, cx, h * 0.3, cx, h * 0.6, cx, h * 0.66, cx - 30 * s, h * 0.58, cx + 30 * s, h * 0.58)
        + b"0 g " + text(cx - 70 * s, h * 0.68, "TOP OF CONTENT", 16 * s, "F4"))


# --------------------------------------------------------------------------- rotation

@generator("rotate", ["mixed", "all-90", "text-angles"])
def rotate(tmp: Path) -> dict:
    """/Rotate 0/90/180/270/-90/450/45, inherited /Rotate, landscape boxes, rotated text."""
    out = {}
    d = Doc("Rotated pages, mixed")
    for r in (0, 90, 180, 270, -90, 450):
        d.page(label_page(f"/Rotate {r}", ["The arrow points to the top of the content.",
                                            f"A viewer should show this page turned by {r % 360} degrees clockwise."])
               + up_arrow(612, 792), extra=f"/Rotate {r}")
    d.page(label_page("Landscape MediaBox, /Rotate 90", ["MediaBox 792 x 612 plus /Rotate 90 is portrait on screen."],
                      792, 612) + up_arrow(792, 612), 792, 612, extra="/Rotate 90")
    d.page(label_page("/Rotate 45 (invalid)", ["Not a multiple of 90. PDF 1.7 says multiple of 90; readers differ."])
           + up_arrow(612, 792), extra="/Rotate 45")
    inter = d.reserve()
    inh = [d.page(label_page(f"Inherited /Rotate 90 ({i})", ["This page has no /Rotate key.",
                                                             "Its parent Pages node has /Rotate 90."])
                  + up_arrow(612, 792), parent=inter) for i in (1, 2)]
    d.set(inter, f"<< /Type /Pages /Parent {d.pages} 0 R /Kids [{inh[0]} 0 R {inh[1]} 0 R] /Count 2 /Rotate 90 >>")
    d.page(label_page("Back to /Rotate 0", ["Last page, upright."]) + up_arrow(612, 792))
    kids = d.kids[:4] + [inter] + d.kids[4:]
    out["mixed"] = d.finish(kids=kids, count=len(d.kids) + 2)

    d = Doc("Every page /Rotate 90")
    for i in range(1, 6):
        d.page(label_page(f"Page {i} of 5, /Rotate 90",
                          ["A landscape scan stored as portrait pages with /Rotate 90."]) + up_arrow(612, 792),
               extra="/Rotate 90")
    out["all-90"] = d.finish()

    d = Doc("Text at many angles and transforms")
    c = bytearray(label_page("Text matrices", ["Each sample says how it is drawn. Selection boxes should follow the glyphs."]))
    for i, ang in enumerate((0, 30, 45, 90, 135, 180, 270, -15)):
        a = math.radians(ang)
        x, y = 150 + (i % 4) * 120, 520 - (i // 4) * 200
        c += b"BT /F1 14 Tf %.4f %.4f %.4f %.4f %g %g Tm " % (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), x, y)
        c += pdf_string(f"angle {ang}") + b" Tj ET\n"
    c += b"BT /F2 14 Tf -1 0 0 1 300 200 Tm (mirrored horizontally) Tj ET\n"
    c += b"BT /F2 14 Tf 1 0 0.5 1 330 200 Tm (sheared 0.5) Tj ET\n"
    c += b"q BT /F1 12 Tf 50 Tz 1 0 0 1 40 150 Tm (Tz 50 horizontal scaling) Tj 200 Tz 0 -20 Td (Tz 200 scaling) Tj ET Q\n"
    c += b"q BT /F1 12 Tf 8 Tc 1 0 0 1 40 100 Tm (Tc 8 character spacing) Tj ET Q\n"
    c += b"q BT /F1 12 Tf 25 Tw 1 0 0 1 40 80 Tm (Tw 25 word spacing between words) Tj ET Q\n"
    c += b"BT /F1 12 Tf 1 0 0 1 40 60 Tm (base) Tj 6 Ts (super) Tj -4 Ts (sub) Tj 0 Ts ( back) Tj ET\n"
    c += b"BT /F3 12 Tf 1 0 0 1 560 400 Tm"
    for ch in "VERTICAL":
        c += b" (" + ch.encode() + b") Tj 0 -14 Td"
    c += b" ET\n"
    d.page(bytes(c))
    out["text-angles"] = d.finish()
    return out


# --------------------------------------------------------------------------- page sizes

def grid_page(w: float, h: float, step: float, unit_label: str) -> bytes:
    c = bytearray(b"0.8 G 2 w ")
    x = 0.0
    while x <= w:
        c += b"%g 0 m %g %g l S " % (x, x, h)
        x += step
    y = 0.0
    while y <= h:
        c += b"0 %g m %g %g l S " % (y, w, y)
        y += step
    c += b"0 g\n"
    for i in range(int(w // step) + 1):
        for j in range(int(h // step) + 1):
            c += text(i * step + 10, j * step + 10, f"({i * 10},{j * 10}) {unit_label}", 48)
            c += text(i * step + 10, j * step + 70, f"small 6pt text in cell {i},{j}", 6)
    return bytes(c)


@generator("pagesize", ["mixed", "huge-200in", "userunit-2000in", "tiny-10pt", "strip-200x1in"])
def pagesize(tmp: Path) -> dict:
    """Mixed page sizes, offset/cropped boxes, a 200 in page, UserUnit, tiny and extreme-aspect pages."""
    out = {}
    d = Doc("Mixed page sizes")
    sizes = [("A4", 595.28, 841.89), ("US Letter", 612, 792), ("A3 landscape", 1190.55, 841.89),
             ("A5", 419.53, 595.28), ("Business card", 252, 144), ("Receipt 3.15 x 40 in", 227, 2880),
             ("Square 10 in", 720, 720), ("A0", 2383.94, 3370.39)]
    for name, w, h in sizes:
        d.page(label_page(name, [f"{w:g} x {h:g} pt"], w, h), w, h)
    d.page(label_page("MediaBox [100 100 712 892]", ["The origin is not at 0,0."], 612, 792)
           .replace(b"0.6 G", b"1 0 0 1 100 100 cm 0.6 G", 1), box="100 100 712 892")
    c = label_page("CropBox [72 72 540 720]", ["Text in the outer inch is outside the CropBox and must not show."])
    c += text(14, 40, "OUTSIDE CROPBOX - SHOULD BE HIDDEN", 14, "F4")
    d.page(c, extra="/CropBox [72 72 540 720] /TrimBox [90 90 522 702] /BleedBox [80 80 532 712]")
    d.page(label_page("/UserUnit 2", ["MediaBox 612 x 792 with UserUnit 2: 17 x 22 in."]), extra="/UserUnit 2")
    out["mixed"] = d.finish()

    d = Doc("200 in square page")
    d.page(grid_page(14400, 14400, 720, "in"), 14400, 14400)
    out["huge-200in"] = d.finish()

    d = Doc("UserUnit 10 page: 2000 in square", "1.6")
    d.page(grid_page(14400, 14400, 720, "x10 in"), 14400, 14400, extra="/UserUnit 10")
    out["userunit-2000in"] = d.finish()

    d = Doc("Tiny page")
    d.page(b"0 g " + text(1, 4, "Hi", 4) + b"0.5 w 0.5 0.5 9 9 re S", 10, 10)
    d.page(label_page("Normal page after a tiny one", []))
    out["tiny-10pt"] = d.finish()

    d = Doc("200 x 1 in strip")
    c = bytearray()
    for i in range(0, 200, 5):
        c += text(i * 72 + 4, 30, f"{i} in", 20)
    d.page(bytes(c) + b"1 w 0 36 m 14400 36 l S", 14400, 72)
    out["strip-200x1in"] = d.finish()
    return out


# --------------------------------------------------------------------------- transparency

BLEND = ["Normal", "Multiply", "Screen", "Overlay", "Darken", "Lighten", "ColorDodge", "ColorBurn",
         "HardLight", "SoftLight", "Difference", "Exclusion", "Hue", "Saturation", "Color", "Luminosity"]


@generator("transparency", ["blend-modes", "groups-softmask"])
def transparency(tmp: Path) -> dict:
    """All 16 blend modes; isolated/knockout groups; constant alpha; luminosity soft mask; image SMask."""
    out = {}
    d = Doc("Blend modes")
    gs = " ".join(f"/BM{i} << /BM /{m} >>" for i, m in enumerate(BLEND))
    c = bytearray(label_page("16 blend modes", ["Orange square with each /BM over rainbow stripes."]))
    for i in range(12):
        hue = i / 12
        r, g, bl = (abs(math.sin(math.pi * (hue + k / 3))) for k in range(3))
        c += b"%.3f %.3f %.3f rg %g 60 %g 600 re f\n" % (r, g, bl, 40 + i * 44, 44)
    for i, m in enumerate(BLEND):
        x, y = 60 + (i % 4) * 130, 560 - (i // 4) * 130
        c += b"q /BM%d gs 1 0.55 0.1 rg %g %g 100 100 re f Q\n" % (i, x, y)
        c += b"q 1 1 1 rg %g %g 100 14 re f Q " % (x, y - 16) + text(x + 2, y - 13, m, 10)
    c += b"q /BM1 gs " + text(60, 40, "Text drawn with /BM /Multiply over the stripes", 22, "F4") + b"Q\n"
    d.page(bytes(c), res=f"/ExtGState << {gs} >>")
    out["blend-modes"] = d.finish()

    d = Doc("Transparency groups and soft masks")
    two = circle(60, 60, 45) + b"f " + circle(110, 60, 45) + b"f"
    forms = {}
    for name, iso, ko in (("ni_nk", "false", "false"), ("i_nk", "true", "false"),
                          ("ni_k", "false", "true"), ("i_k", "true", "true")):
        forms[name] = d.stream(b"/A gs 0 0.4 1 rg " + two,
                               f"/Type /XObject /Subtype /Form /BBox [0 0 170 120] "
                               f"/Resources << /ExtGState << /A << /ca 0.5 /BM /Multiply >> >> >> "
                               f"/Group << /S /Transparency /CS /DeviceRGB /I {iso} /K {ko} >>")
    grad_fn = d.add("<< /FunctionType 2 /Domain [0 1] /C0 [1] /C1 [0] /N 1 >>")
    mask_group = d.stream(b"/Sh0 sh", "/Type /XObject /Subtype /Form /BBox [0 0 612 792] "
                          f"/Group << /S /Transparency /CS /DeviceGray >> "
                          f"/Resources << /Shading << /Sh0 << /ShadingType 2 /ColorSpace /DeviceGray "
                          f"/Coords [60 0 550 0] /Function {grad_fn} 0 R /Extend [true true] >> >> >>")
    W = H = 64
    rgb = bytes(v for y in range(H) for x in range(W) for v in (x * 4, y * 4, 200))
    alpha = bytes(max(0, 255 - int(math.hypot(x - 32, y - 32) * 8)) for y in range(H) for x in range(W))
    smask = d.stream(alpha, f"/Type /XObject /Subtype /Image /Width {W} /Height {H} /ColorSpace /DeviceGray /BitsPerComponent 8")
    img = d.stream(rgb, f"/Type /XObject /Subtype /Image /Width {W} /Height {H} /ColorSpace /DeviceRGB "
                        f"/BitsPerComponent 8 /SMask {smask} 0 R")
    c = bytearray(label_page("Groups, alpha, soft masks", [
        "Row 1: form groups non-isolated/isolated x non-knockout/knockout over a stripe.",
        "Row 2: constant alpha fill, stroke and text. Row 3: luminosity soft mask and image SMask."]))
    c += b"1 0.8 0 rg 30 520 560 40 re f\n"
    for i, name in enumerate(forms):
        c += b"q 1 0 0 1 %g 470 cm /%s Do Q " % (30 + i * 140, name.encode()) + text(30 + i * 140, 455, name, 9)
    c += b"q /CA5 gs 0 0.6 0 RG 12 w 40 300 200 100 re S Q q /ca5 gs 1 0 0 rg 120 330 200 100 re f Q\n"
    c += b"q /ca3 gs " + text(340, 360, "30% opaque text", 28, "F4") + b"Q\n"
    c += b"q /SM gs 0 0 0.8 rg 40 120 300 120 re f " + text(50, 170, "Text under a luminosity mask", 18, "F4") + b"Q\n"
    c += b"q 1 0 0 rg 380 120 180 120 re f Q q 160 0 0 160 390 100 cm /Img Do Q\n"
    xo = " ".join(f"/{k} {v} 0 R" for k, v in forms.items()) + f" /Img {img} 0 R"
    d.page(bytes(c), res=f"/XObject << {xo} >> /ExtGState << /CA5 << /CA 0.5 >> /ca5 << /ca 0.5 >> "
                         f"/ca3 << /ca 0.3 >> /SM << /SMask << /Type /Mask /S /Luminosity /G {mask_group} 0 R >> >> >>",
           extra="/Group << /S /Transparency /CS /DeviceRGB /I true >>")
    out["groups-softmask"] = d.finish()
    return out


# --------------------------------------------------------------------------- shadings

def q16(v: float, lo: float, hi: float) -> int:
    return max(0, min(65535, round((v - lo) / (hi - lo) * 65535)))


@generator("shading", ["types-1-7", "patterns"])
def shading(tmp: Path) -> dict:
    """Shading types 1-7 with sh; shading and tiling patterns filling shapes and text."""
    out = {}
    d = Doc("Shading types 1-7")
    dec = "/Decode [0 612 0 792 0 1 0 1 0 1]"
    calc = d.stream(b"{ 2 copy mul }", "/FunctionType 4 /Domain [0 1 0 1] /Range [0 1 0 1 0 1]", compress=False)
    f_rg = d.add("<< /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0 1 0] /N 1 >>")
    f_gb = d.add("<< /FunctionType 2 /Domain [0 1] /C0 [0 1 0] /C1 [0 0 1] /N 1 >>")
    stitch = d.add(f"<< /FunctionType 3 /Domain [0 1] /Functions [{f_rg} 0 R {f_gb} 0 R] /Bounds [0.5] /Encode [0 1 0 1] >>")
    cells = [(40, 520), (230, 520), (420, 520), (40, 300), (230, 300), (420, 300), (40, 80), (230, 80)]
    sh = {}
    x, y = cells[0]
    sh[1] = d.add(f"<< /ShadingType 1 /ColorSpace /DeviceRGB /Domain [0 1 0 1] /Matrix [150 0 0 150 {x} {y}] /Function {calc} 0 R >>")
    x, y = cells[1]
    sh[2] = d.add(f"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [{x + 20} 0 {x + 130} 0] /Function {stitch} 0 R /Extend [true true] >>")
    x, y = cells[2]
    sh[3] = d.add(f"<< /ShadingType 3 /ColorSpace /DeviceRGB /Coords [{x + 50} {y + 50} 5 {x + 90} {y + 90} 70] /Function {f_rg} 0 R /Extend [false true] >>")
    x, y = cells[3]
    tri = bytearray()
    for flag, (vx, vy), col in ((0, (x, y), (255, 0, 0)), (0, (x + 150, y), (0, 255, 0)), (0, (x + 75, y + 150), (0, 0, 255)),
                                (1, (x + 150, y + 150), (255, 255, 0))):
        tri += struct.pack(">BHH3B", flag, q16(vx, 0, 612), q16(vy, 0, 792), *col)
    sh[4] = d.stream(bytes(tri), f"/ShadingType 4 /ColorSpace /DeviceRGB /BitsPerCoordinate 16 /BitsPerComponent 8 /BitsPerFlag 8 {dec}")
    x, y = cells[4]
    lat = bytearray()
    for j in range(3):
        for i in range(3):
            lat += struct.pack(">HH3B", q16(x + i * 75 + (10 if i == j else 0), 0, 612), q16(y + j * 75, 0, 792),
                               i * 120, j * 120, 255 - i * 60)
    sh[5] = d.stream(bytes(lat), f"/ShadingType 5 /ColorSpace /DeviceRGB /BitsPerCoordinate 16 /BitsPerComponent 8 /VerticesPerRow 3 {dec}")

    def patch(x: float, y: float, tensor: bool) -> bytes:
        s = 150
        pts = [(0, 0), (0, 50), (0, 100), (0, 150), (50, 170), (100, 130), (150, 150), (150, 100), (150, 50), (150, 0), (100, -20), (50, 20)]
        if tensor:
            pts += [(50, 50), (50, 100), (100, 100), (100, 50)]
        data = struct.pack(">B", 0)
        for px, py in pts:
            data += struct.pack(">HH", q16(x + px * s / 150, 0, 612), q16(y + py * s / 150, 0, 792))
        for col in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)):
            data += struct.pack(">3B", *col)
        return data
    x, y = cells[5]
    sh[6] = d.stream(patch(x, y, False), f"/ShadingType 6 /ColorSpace /DeviceRGB /BitsPerCoordinate 16 /BitsPerComponent 8 /BitsPerFlag 8 {dec}")
    x, y = cells[6]
    sh[7] = d.stream(patch(x, y, True), f"/ShadingType 7 /ColorSpace /DeviceRGB /BitsPerCoordinate 16 /BitsPerComponent 8 /BitsPerFlag 8 {dec}")
    c = bytearray(label_page("Shading types 1-7", ["Each cell is clipped and painted with the sh operator."]))
    for t in range(1, 8):
        x, y = cells[t - 1]
        c += b"q %g %g 170 190 re W n /Sh%d sh Q " % (x - 10, y - 20, t) + text(x, y - 34, f"ShadingType {t}", 10)
    d.page(bytes(c), res="/Shading << " + " ".join(f"/Sh{t} {n} 0 R" for t, n in sh.items()) + " >>")
    out["types-1-7"] = d.finish()

    d = Doc("Patterns")
    f_rg = d.add("<< /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0 0 1] /N 1 >>")
    p_sh = d.add(f"<< /Type /Pattern /PatternType 2 /Shading << /ShadingType 2 /ColorSpace /DeviceRGB "
                 f"/Coords [40 0 570 0] /Function {f_rg} 0 R /Extend [true true] >> >>")
    tile = b"1 0 0 rg 0 0 10 10 re f 0 0 1 rg 10 10 10 10 re f"
    p_tile = d.stream(tile, "/Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 20 20] "
                            "/XStep 20 /YStep 20 /Resources << >>")
    p_unc = d.stream(b"0 0 m 12 12 l 12 0 m 0 12 l S", "/Type /Pattern /PatternType 1 /PaintType 2 /TilingType 2 "
                                                        "/BBox [0 0 12 12] /XStep 12 /YStep 12 /Resources << >>")
    c = bytearray(label_page("Pattern fills", ["Text filled with an axial shading pattern, a tiling pattern,",
                                               "an uncolored tiling pattern, and text stroked with a pattern."]))
    c += b"/Pattern cs /PSh scn " + text(40, 600, "Shading-filled text", 54, "F4")
    c += b"/PTile scn " + text(40, 500, "Tiling-filled text", 54, "F4") + b"40 300 250 150 re f\n"
    c += b"/CS0 cs 0 0.6 0 /PUnc scn 320 300 250 150 re f " + text(40, 400, "Uncolored tiling", 54, "F4")
    c += b"/Pattern CS /PSh SCN 2 w " + text(40, 200, "Stroked (Tr 1)", 60, "F4", "1 Tr")
    c += b"/Pattern cs /PTile scn " + text(40, 100, "Fill+clip (Tr 6)", 40, "F4", "6 Tr") + b"0 0 612 200 re f\n"
    d.page(bytes(c), res=f"/Pattern << /PSh {p_sh} 0 R /PTile {p_tile} 0 R /PUnc {p_unc} 0 R >> "
                         f"/ColorSpace << /CS0 [/Pattern /DeviceRGB] >>")
    out["patterns"] = d.finish()
    return out


# --------------------------------------------------------------------------- optional content

@generator("ocg", ["layers"])
def ocg(tmp: Path) -> dict:
    """Optional content: default-off layer with text, print-only layer, OCMD, form XObject with /OC."""
    d = Doc("Optional content groups", "1.5")
    on = d.add("<< /Type /OCG /Name (Visible layer) >>")
    off = d.add("<< /Type /OCG /Name (Hidden by default) >>")
    prn = d.add("<< /Type /OCG /Name (Print only) /Usage << /Print << /PrintState /ON >> /View << /ViewState /OFF >> >> >>")
    md = d.add(f"<< /Type /OCMD /OCGs [{off} 0 R] /P /AllOff >>")
    form = d.stream(b"0.8 0 0 rg 0 0 200 60 re f 1 g " + text(10, 25, "Form XObject in hidden layer", 12, "F4"),
                    f"/Type /XObject /Subtype /Form /BBox [0 0 200 60] /OC {off} 0 R "
                    f"/Resources << /Font << /F4 {d.fonts['F4']} 0 R >> >>")
    c = bytearray(label_page("Optional content", ["Blue text is in an ON layer. Red text is in a layer that is OFF by",
                                                  "default and must not render or be found by search.",
                                                  "Green text is print-only (View OFF)."]))
    c += b"/OC /L1 BDC 0 0 1 rg " + text(40, 560, "VISIBLE LAYER TEXT", 24, "F4") + b"EMC\n"
    c += b"/OC /L2 BDC 1 0 0 rg " + text(40, 500, "HIDDEN LAYER TEXT hiddenlayerword", 24, "F4") + b"EMC\n"
    c += b"/OC /L3 BDC 0 0.6 0 rg " + text(40, 440, "PRINT ONLY TEXT printonlyword", 24, "F4") + b"EMC\n"
    c += b"/OC /M1 BDC 0.5 0 0.5 rg " + text(40, 380, "OCMD: shown because hidden layer is off", 18, "F4") + b"EMC\n"
    c += b"q 1 0 0 1 40 280 cm /Fx Do Q\n"
    d.page(bytes(c), res=f"/Properties << /L1 {on} 0 R /L2 {off} 0 R /L3 {prn} 0 R /M1 {md} 0 R >> /XObject << /Fx {form} 0 R >>")
    ocp = (f"/OCProperties << /OCGs [{on} 0 R {off} 0 R {prn} 0 R] /D << /Name (Default) /ON [{on} 0 R] "
           f"/OFF [{off} 0 R] /Order [{on} 0 R {off} 0 R {prn} 0 R] /RBGroups [] "
           f"/AS [<< /Event /View /OCGs [{prn} 0 R] /Category [/View] >> << /Event /Print /OCGs [{prn} 0 R] /Category [/Print] >>] >> >>")
    return {"layers": d.finish(ocp + " /PageMode /UseOC")}


# --------------------------------------------------------------------------- invisible text

def scan_image(rng: random.Random, lines: list[list[str]], dpi: int = 200) -> tuple[bytes, list, int, int]:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    W, H = int(8.5 * dpi), int(11 * dpi)
    img = Image.new("L", (W, H), 245)
    dr = ImageDraw.Draw(img)
    font = None
    for cand in ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            font = ImageFont.truetype(cand, int(11 / 72 * dpi))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default(int(11 / 72 * dpi))
    boxes = []  # (word, x_pt, y_pt baseline, w_pt, size_pt)
    y = dpi
    for words in lines:
        x = dpi
        for w in words:
            wl = dr.textlength(w, font=font)
            dr.text((x, y), w, fill=20, font=font)
            boxes.append((w, x * 72 / dpi, 792 - (y + 0.8 * 11 / 72 * dpi) * 72 / dpi, wl * 72 / dpi, 11))
            x += wl + dr.textlength(" ", font=font)
        y += int(15 / 72 * dpi)
    img = img.rotate(0.6, resample=Image.BICUBIC, fillcolor=245)
    noise = Image.effect_noise((W, H), 18)
    img = Image.blend(img, noise, 0.08).filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return buf.getvalue(), boxes, W, H


@generator("invisible-text", ["ocr-scan", "hiding-tricks"])
def invisible_text(tmp: Path) -> dict:
    """OCR-style scan (JPEG + render mode 3 text) and other ways text is present but not visible."""
    out = {}
    rng = random.Random(7)
    d = Doc("Simulated OCR scan")
    for pno in range(3):
        lines = []
        for _ in range(38):
            n, line = 0, []
            while n < 70:
                w = rng.choice(WORDS)
                line.append(w)
                n += len(w) + 1
            lines.append(line)
        jpg, boxes, W, H = scan_image(rng, lines)
        im = d.stream(jpg, f"/Type /XObject /Subtype /Image /Width {W} /Height {H} /ColorSpace /DeviceGray "
                           f"/BitsPerComponent 8 /Filter /DCTDecode", compress=False)
        c = bytearray(b"q 612 0 0 792 0 0 cm /Im0 Do Q\nBT 3 Tr\n")
        for w, x, y, wpt, size in boxes:
            natural = 0.5 * size * len(w)  # rough Helvetica width
            c += b"/F1 %g Tf %g Tz 1 0 0 1 %.2f %.2f Tm " % (size, round(100 * wpt / natural, 1), x, y) + pdf_string(w + " ") + b" Tj\n"
        c += b"ET\n"
        d.page(bytes(c), res=f"/XObject << /Im0 {im} 0 R >>")
    out["ocr-scan"] = d.finish()

    d = Doc("Hidden text tricks")
    img = d.stream(bytes([200, 60, 60] * 4), "/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8")
    c = bytearray(label_page("Text that is present but should not be seen", [
        "Each row: a visible label, then the hidden sample to its right."]))
    rows = [
        ("Tr 3 (invisible)", text(260, 0, "invisibleword mode three", 14, "F1", "3 Tr")),
        ("Tr 7 (clip only)", b"q " + text(260, 0, "clipword mode seven", 14, "F4", "7 Tr") + b"0 0.5 0 rg 250 -10 300 30 re f Q\n"),
        ("white on white", b"1 g " + text(260, 0, "whiteonwhite text", 14) + b"0 g\n"),
        ("under opaque rect", text(260, 0, "coveredbyrect text", 14) + b"0.3 g 255 -5 200 22 re f 0 g\n"),
        ("under opaque image", text(260, 0, "coveredbyimage text", 14) + b"q 200 0 0 22 255 -5 cm /Im Do Q\n"),
        ("font size 0.01", b"BT /F1 0.01 Tf 1 0 0 1 260 0 Tm (tinyfontword) Tj ET\n"),
        ("clipped away", b"q 0 0 1 1 re W n " + text(260, 0, "clippedawayword", 14) + b"Q\n"),
        ("fill alpha 0", b"q /A0 gs " + text(260, 0, "alphazeroword", 14) + b"Q\n"),
        ("drawn twice (fake bold)", text(260, 0, "doubleword fakebold", 14) + text(260.4, 0, "doubleword fakebold", 14)),
        ("outside MediaBox", text(-400, 0, "offpageword", 14)),
    ]
    y = 640
    for label, body in rows:
        c += text(40, y, label, 12, "F4") + b"q 1 0 0 1 0 %g cm " % y + body + b" Q\n"
        y -= 50
    d.page(bytes(c), res=f"/XObject << /Im {img} 0 R >> /ExtGState << /A0 << /ca 0 /CA 0 >> >>")
    out["hiding-tricks"] = d.finish()
    return out


# --------------------------------------------------------------------------- annotations

@generator("annotations", ["all-types", "rotated-page"])
def annotations(tmp: Path) -> dict:
    """Most annotation subtypes, with and without appearance streams, hidden/print flags, rotated page."""
    out = {}
    d = Doc("Annotations")
    target = d.reserve()
    annots = []
    hl_ap = d.stream(b"/M gs 1 1 0 rg 0 0 120 16 re f", "/Type /XObject /Subtype /Form /BBox [0 0 120 16] "
                                                         "/Resources << /ExtGState << /M << /BM /Multiply >> >> >>")
    hidden_ap = d.stream(b"1 0 0 rg 0 0 200 30 re f 1 g " + text(5, 10, "HIDDEN ANNOT", 14, "F4"),
                         f"/Type /XObject /Subtype /Form /BBox [0 0 200 30] /Resources << /Font << /F4 {d.fonts['F4']} 0 R >> >>")
    ef = d.stream(b"Attached file contents.\n", "/Type /EmbeddedFile /Subtype /text#2Fplain")

    def A(s: str) -> int:
        n = d.add(s)
        annots.append(n)
        return n
    A("<< /Type /Annot /Subtype /Link /Rect [40 690 250 706] /Border [0 0 1] /C [0 0 1] "
      "/A << /S /URI /URI (https://example.com/pdf-viewer-test) >> >>")
    A(f"<< /Type /Annot /Subtype /Link /Rect [300 690 520 706] /Border [0 0 1] /Dest [{target} 0 R /XYZ 0 792 0] >>")
    A("<< /Type /Annot /Subtype /Link /Rect [40 660 250 676] /Border [0 0 1] /Dest (named-target) >>")
    note = A("<< /Type /Annot /Subtype /Text /Rect [300 650 320 670] /Contents (A sticky note comment) /Name /Comment "
             "/T (Tester) /C [1 1 0] /Open false >>")
    A(f"<< /Type /Annot /Subtype /Popup /Rect [330 560 520 650] /Parent {note} 0 R /Open false >>")
    A("<< /Type /Annot /Subtype /FreeText /Rect [40 580 280 630] /Contents (FreeText without appearance stream) "
      "/DA (/Helv 12 Tf 0 0 1 rg) /Q 0 >>")
    A("<< /Type /Annot /Subtype /Line /Rect [40 520 280 570] /L [45 525 275 565] /LE [/None /OpenArrow] /C [1 0 0] /BS << /W 2 >> >>")
    A("<< /Type /Annot /Subtype /Square /Rect [300 500 400 560] /C [0 0.5 0] /IC [0.8 1 0.8] /BS << /W 3 >> >>")
    A("<< /Type /Annot /Subtype /Circle /Rect [420 500 520 560] /C [0.5 0 0.5] /BS << /W 2 /S /D /D [4 2] >> >>")
    A("<< /Type /Annot /Subtype /Polygon /Rect [40 420 200 500] /Vertices [50 430 120 490 190 430] /C [0 0 1] >>")
    A("<< /Type /Annot /Subtype /PolyLine /Rect [220 420 380 500] /Vertices [230 430 260 490 300 430 340 490 370 430] /C [1 0.5 0] >>")
    A("<< /Type /Annot /Subtype /Ink /Rect [400 420 560 500] /InkList [[410 430 430 480 450 440 480 490 520 430 550 470]] /C [0 0 0] /BS << /W 2 >> >>")
    marked = [("Highlight", f"/AP << /N {hl_ap} 0 R >>"), ("Underline", ""), ("Squiggly", ""), ("StrikeOut", "")]
    c = bytearray(label_page("Annotations", ["Links, markup, shapes, note, stamp, attachment, hidden/print-only flags."]))
    c += text(40, 694, "URI link to example.com", 12) + text(300, 694, "GoTo link to page 2", 12) + text(40, 664, "Named destination", 12)
    y = 380
    for sub, ap in marked:
        c += text(40, y, f"{sub} markup over this text", 12)
        A(f"<< /Type /Annot /Subtype /{sub} /Rect [38 {y - 3} 240 {y + 13}] /QuadPoints [38 {y + 13} 240 {y + 13} 38 {y - 3} 240 {y - 3}] "
          f"/C [1 0.9 0] {ap} >>")
        y -= 24
    A("<< /Type /Annot /Subtype /Stamp /Rect [300 300 520 380] /Name /Approved /C [1 0 0] >>")
    A(f"<< /Type /Annot /Subtype /FileAttachment /Rect [300 260 320 280] /Name /Paperclip /Contents (note.txt) "
      f"/FS << /Type /Filespec /F (note.txt) /UF (note.txt) /EF << /F {ef} 0 R >> >> >>")
    A(f"<< /Type /Annot /Subtype /Square /Rect [40 180 240 210] /F 2 /AP << /N {hidden_ap} 0 R >> /C [1 0 0] >>")
    A(f"<< /Type /Annot /Subtype /Square /Rect [300 180 500 210] /F 32 /AP << /N {hidden_ap} 0 R >> /C [1 0 0] >>")
    A(f"<< /Type /Annot /Subtype /Square /Rect [40 130 240 160] /F 4 /AP << /N {hl_ap} 0 R >> /C [0 0 1] >>")
    c += text(40, 215, "Hidden flag (F 2): nothing should show below", 10) + text(300, 215, "NoView flag (F 32): nothing below", 10)
    c += text(40, 165, "Print flag (F 4): visible, printable", 10)
    p1 = d.page(bytes(c), extra="/Annots [" + " ".join(f"{a} 0 R" for a in annots) + "]")
    d.kids.append(target)
    c2 = label_page("Page 2: link target", ["The GoTo and named-destination links land here."])
    cs = d.stream(c2)
    d.set(target, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] "
                  f"/Resources << /Font << {d.font_res()} >> >> /Contents {cs} 0 R >>")
    acro = f"/AcroForm << /Fields [] /DR << /Font << /Helv {d.fonts['F1']} 0 R >> >> /DA (/Helv 0 Tf 0 g) >>"
    names = f"/Names << /Dests << /Names [(named-target) [{target} 0 R /Fit]] >> >>"
    out["all-types"] = d.finish(acro + " " + names)

    d = Doc("Annotations on a rotated page")
    a1 = d.add("<< /Type /Annot /Subtype /Text /Rect [100 600 120 620] /F 20 /Contents (NoRotate note) /Open true >>")
    a2 = d.add("<< /Type /Annot /Subtype /FreeText /Rect [100 400 400 450] /Contents (FreeText on a /Rotate 90 page) /DA (/Helv 14 Tf 1 0 0 rg) >>")
    a3 = d.add("<< /Type /Annot /Subtype /Link /Rect [100 300 300 320] /Border [0 0 2] /A << /S /URI /URI (https://example.org/) >> >>")
    c = label_page("/Rotate 90 with annotations", ["Link box must stay over its text after rotation."]) + text(100, 304, "rotated link text", 14) + up_arrow(612, 792)
    d.page(c, extra=f"/Rotate 90 /Annots [{a1} 0 R {a2} 0 R {a3} 0 R]")
    out["rotated-page"] = d.finish(f"/AcroForm << /Fields [] /DR << /Font << /Helv {d.fonts['F1']} 0 R >> >> /DA (/Helv 0 Tf 0 g) >>")
    return out


# --------------------------------------------------------------------------- forms without appearances

@generator("forms-raw", ["need-appearances"])
def forms_raw(tmp: Path) -> dict:
    """AcroForm with /NeedAppearances true and no /AP: text, comb, password, checkbox, radio, choice, signature."""
    d = Doc("AcroForm without appearance streams")
    page = d.reserve()
    fields, widgets = [], []

    def W(s: str, top: bool = True) -> int:
        n = d.add(s.replace("PAGE", f"{page} 0 R"))
        widgets.append(n)
        if top:
            fields.append(n)
        return n
    da = "/DA (/Helv 12 Tf 0 g) /MK << /BC [0 0 0] /BG [0.9 0.95 1] >>"
    W(f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V (prefilled value) /Rect [200 680 500 700] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (notes) /Ff 4096 /V (line one\\rline two\\rline three) /Rect [200 600 500 670] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (comb) /Ff {(1 << 24) | (1 << 23)} /MaxLen 8 /V (12345678) /Rect [200 560 440 585] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (password) /Ff 8192 /V (secret) /Rect [200 520 400 540] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) /V /Yes /AS /Yes /Rect [200 480 216 496] /P PAGE "
      f"/MK << /CA (4) /BC [0 0 0] >> /DA (/ZaDb 0 Tf 0 g) >>")
    radio = d.reserve()
    kids = []
    for i, opt in enumerate(("red", "green", "blue")):
        k = d.add(f"<< /Type /Annot /Subtype /Widget /Parent {radio} 0 R /Rect [{200 + i * 60} 440 {216 + i * 60} 456] "
                  f"/P {page} 0 R /AS /{'green' if opt == 'green' else 'Off'} /MK << /CA (l) /BC [0 0 0] >> /DA (/ZaDb 0 Tf 0 g) >>")
        kids.append(k)
        widgets.append(k)
    d.set(radio, f"<< /FT /Btn /T (colour) /Ff {1 << 15 | 1 << 14} /V /green /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>")
    fields.append(radio)
    W(f"<< /Type /Annot /Subtype /Widget /FT /Ch /T (combo) /Ff {1 << 17} /Opt [(Oslo) (Boston) (Trondheim)] /V (Boston) /Rect [200 400 400 420] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Ch /T (list) /Opt [(alpha) (bravo) (charlie) (delta)] /V (charlie) /I [2] /Rect [200 320 400 390] /P PAGE {da} >>")
    W(f"<< /Type /Annot /Subtype /Widget /FT /Btn /T (button) /Ff {1 << 16} /Rect [200 270 320 300] /P PAGE "
      f"/MK << /CA (Push me) /BG [0.8 0.8 0.8] /BC [0 0 0] >> /DA (/Helv 12 Tf 0 g) >>")
    W("<< /Type /Annot /Subtype /Widget /FT /Sig /T (signature) /Rect [200 200 450 250] /P PAGE /MK << /BC [1 0 0] >> >>")
    addr = d.reserve()
    s1 = d.add(f"<< /Type /Annot /Subtype /Widget /Parent {addr} 0 R /T (street) /V (1 Main St) /Rect [200 150 400 170] /P {page} 0 R {da} >>")
    s2 = d.add(f"<< /Type /Annot /Subtype /Widget /Parent {addr} 0 R /T (city) /V (Cambridge) /Rect [200 120 400 140] /P {page} 0 R {da} >>")
    widgets += [s1, s2]
    d.set(addr, f"<< /FT /Tx /T (address) /Kids [{s1} 0 R {s2} 0 R] >>")
    fields.append(addr)
    c = bytearray(label_page("Form fields, no appearance streams", ["/NeedAppearances true: the viewer must draw every field."]))
    for y, lab in ((685, "Text"), (640, "Multiline"), (567, "Comb (8)"), (525, "Password"), (483, "Checkbox (on)"),
                   (443, "Radio (green)"), (405, "Combo box"), (360, "List box"), (280, "Push button"), (220, "Signature"),
                   (155, "address.street"), (125, "address.city")):
        c += text(40, y, lab, 12)
    cs = d.stream(bytes(c))
    zadb = d.add("<< /Type /Font /Subtype /Type1 /BaseFont /ZapfDingbats >>")
    d.set(page, f"<< /Type /Page /Parent {d.pages} 0 R /MediaBox [0 0 612 792] /Resources << /Font << {d.font_res()} >> >> "
                f"/Contents {cs} 0 R /Annots [{' '.join(f'{w} 0 R' for w in widgets)}] >>")
    d.kids.append(page)
    acro = (f"/AcroForm << /Fields [{' '.join(f'{f} 0 R' for f in fields)}] /NeedAppearances true "
            f"/DR << /Font << /Helv {d.fonts['F1']} 0 R /ZaDb {zadb} 0 R >> >> /DA (/Helv 0 Tf 0 g) >>")
    return {"need-appearances": d.finish(acro)}


# --------------------------------------------------------------------------- text mapping

def cmap(ranges: list[tuple[int, int, int]]) -> bytes:
    body = "\n".join(f"<{lo:02X}> <{hi:02X}> <{dst:04X}>" for lo, hi, dst in ranges)
    return (b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            + b"%d beginbfrange\n" % len(ranges) + body.encode() + b"\nendbfrange\nendcmap\n"
            b"CMapName currentdict /CMap defineresource pop\nend\nend\n")


@generator("text-mapping", ["wrong-tounicode", "actualtext-ligatures", "reading-order"])
def text_mapping(tmp: Path) -> dict:
    """ToUnicode that lies (shifted, PUA), ActualText and ligature glyphs, drawing order != reading order."""
    out = {}
    d = Doc("Wrong ToUnicode maps")
    shift = d.stream(cmap([(0x41, 0x59, 0x42), (0x61, 0x79, 0x62), (0x20, 0x20, 0x20)]))
    pua = d.stream(cmap([(0x20, 0x7E, 0xE020)]))
    f7 = d.add(f"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding /ToUnicode {shift} 0 R >>")
    f8 = d.add(f"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman /Encoding /WinAnsiEncoding /ToUnicode {pua} 0 R >>")
    c = bytearray(label_page("ToUnicode disagrees with the glyphs", [
        "Line 1 copies as letters shifted by one (Uif rvjdl...). Line 2 copies as Private Use Area code points.",
        "Search for 'quick' should still match what is shown only if the viewer ignores ToUnicode."]))
    c += text(40, 600, "The quick brown fox jumps over the lazy dog", 18, "F7")
    c += text(40, 560, "Pack my box with five dozen liquor jugs", 18, "F8")
    d.page(bytes(c), fonts=f"/F7 {f7} 0 R /F8 {f8} 0 R")
    out["wrong-tounicode"] = d.finish()

    d = Doc("ActualText and ligatures")
    lig = d.add("<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman "
                "/Encoding << /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [1 /fi /fl /ff /ffi] >> >>")
    c = bytearray(label_page("Ligatures and ActualText", [
        "Line 1: fi/fl glyphs by name, no ActualText. Line 2: same with /ActualText.",
        "Line 3: hyphenated word with ActualText of the whole word. Line 4: soft hyphen."]))
    c += b"BT /FL 20 Tf 40 600 Td (e\001cient \002u\003y o\004ce) Tj ET\n"
    c += (b"BT /FL 20 Tf 40 560 Td /Span << /ActualText (efficient) >> BDC (e\001cient) Tj EMC ( ) Tj "
          b"/Span << /ActualText <FEFF0066006C007500660066007900> >> BDC (\002u\003y) Tj EMC ET\n")
    c += (b"BT /F2 20 Tf 40 520 Td /Span << /ActualText (internationalisation) >> BDC (internation-) Tj "
          b"0 -24 Td (alisation) Tj EMC ET\n")
    c += b"BT /F2 20 Tf 40 440 Td (soft\255hyphen and a\240non-breaking space) Tj ET\n"
    d.page(bytes(c), fonts=f"/FL {lig} 0 R")
    out["actualtext-ligatures"] = d.finish()

    d = Doc("Drawing order differs from reading order")
    rng = random.Random(3)
    c = bytearray(label_page("Reading order", [
        "Two columns; the right column is drawn first. Line under: words drawn right to left.",
        "Bottom: words separated only by TJ kerning, and text placed one glyph at a time."]))
    cols = []
    for col in range(2):
        lines = [" ".join(prose(rng, 7)) for _ in range(14)]
        cols.append(lines)
    for col in (1, 0):
        x = 40 if col == 0 else 320
        for i, line in enumerate(cols[col]):
            c += text(x, 620 - i * 16, f"{'L' if col == 0 else 'R'}{i + 1:02d} {line}", 10)
    words = "these words are drawn from right to left".split()
    x = 40.0
    pos = []
    for w in words:
        pos.append((x, w))
        x += 6.2 * len(w) + 6
    for x, w in reversed(pos):
        c += text(x, 360, w, 12)
    c += b"BT /F2 14 Tf 40 320 Td [(words) -333 (separated) -333 (by) -333 (kerning) -333 (only) -250 (no) -333 (space) -333 (glyphs)] TJ ET\n"
    c += b"BT /F1 14 Tf 40 290 Td"
    for ch in "glyph by glyph positioning":
        c += b" (" + ch.encode() + b") Tj 8.1 0 Td"
    c += b" ET\n"
    d.page(bytes(c))
    out["reading-order"] = d.finish()
    return out


# --------------------------------------------------------------------------- Type 3 fonts

GLYPHS_5x7 = {
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    " ": ["00000"] * 7,
}


@generator("type3", ["vector-no-tounicode", "bitmap-glyphs"])
def type3(tmp: Path) -> dict:
    """Type 3 fonts: vector glyphs with private names and no ToUnicode; 1-bit image-mask glyphs like dvips."""
    out = {}
    d = Doc("Type 3 vector font")
    procs = {
        "g1": b"700 0 0 0 600 700 d1 0 0 m 300 700 l 600 0 l f",
        "g2": b"700 0 0 0 600 700 d1 0 0 600 700 re f",
        "g3": b"700 0 0 0 600 700 d1 " + circle(300, 350, 300) + b"f",
        "g4": b"700 0 0 0 600 700 d1 0 0 m 600 700 l 600 0 m 0 700 l 80 w S",
        "g5": b"700 0 d0 1 0 0 rg 0 0 600 700 re f",
        "sp": b"350 0 0 0 0 0 d1",
    }
    cp = {k: d.stream(v) for k, v in procs.items()}
    f = d.add("<< /Type /Font /Subtype /Type3 /FontBBox [0 0 700 700] /FontMatrix [0.001 0 0 0.001 0 0] "
              f"/CharProcs << {' '.join(f'/{k} {v} 0 R' for k, v in cp.items())} >> "
              "/Encoding << /Type /Encoding /Differences [1 /g1 /g2 /g3 /g4 /g5 32 /sp] >> "
              "/FirstChar 1 /LastChar 32 /Widths [700 700 700 700 700 " + "0 " * 26 + "350] /Resources << >> >>")
    c = bytearray(label_page("Type 3 font, private glyph names, no ToUnicode", [
        "Shapes are glyphs with codes 1-5 named /g1../g5. Copy gives control characters or nothing.",
        "Glyph 5 uses d0 and sets its own red colour."]))
    c += b"BT /T3 36 Tf 40 560 Td (\001\002\003\004\005 \001\001\002\002 \003\004\005) Tj ET\n"
    c += b"BT /T3 12 Tf 40 500 Td (\001\002\003\004\005 \001\002\003\004\005 \001\002\003\004\005) Tj ET\n"
    d.page(bytes(c), fonts=f"/T3 {f} 0 R")
    out["vector-no-tounicode"] = d.finish()

    d = Doc("Type 3 bitmap font")
    cp = {}
    for ch, rows in GLYPHS_5x7.items():
        data = bytes(int(r.ljust(8, "0"), 2) for r in reversed(rows))
        if ch == " ":
            cp[f"a{ord(ch)}"] = d.stream(b"6 0 0 0 0 0 d1")
        else:
            cp[f"a{ord(ch)}"] = d.stream(b"6 0 0 0 5 7 d1 q 5 0 0 7 0 0 cm BI /W 5 /H 7 /IM true /BPC 1 /D [1 0] ID\n"
                                         + bytes(reversed(data)) + b"\nEI Q", compress=False)
    codes = sorted(ord(ch) for ch in GLYPHS_5x7)
    diffs = " ".join(f"{c_} /a{c_}" for c_ in codes)
    widths = " ".join("6" if chr(i) in GLYPHS_5x7 else "0" for i in range(codes[0], codes[-1] + 1))
    f = d.add("<< /Type /Font /Subtype /Type3 /FontBBox [0 0 6 7] /FontMatrix [0.1666 0 0 0.1666 0 0] "
              f"/CharProcs << {' '.join(f'/{k} {v} 0 R' for k, v in cp.items())} >> "
              f"/Encoding << /Type /Encoding /Differences [{diffs}] >> /FirstChar {codes[0]} /LastChar {codes[-1]} "
              f"/Widths [{widths}] /Resources << >> >>")
    c = bytearray(label_page("Type 3 bitmap glyphs (dvips-like)", [
        "Glyphs are 5x7 one-bit image masks named /a72 etc., no ToUnicode.",
        "The code is ASCII, so copy may still work by luck; rendering is blocky by design."]))
    for i, size in enumerate((8, 12, 24, 48, 96)):
        c += b"BT /T3 %d Tf 40 %g Td (HELLO WORLD PDF) Tj ET\n" % (size, 620 - i * 110 + (96 - size) / 2)
    d.page(bytes(c), fonts=f"/T3 {f} 0 R")
    out["bitmap-glyphs"] = d.finish()
    return out


# --------------------------------------------------------------------------- page count and page tree

@generator("pagetree", ["10000-pages-flat", "10000-pages-balanced", "1000-deep-chain"])
def pagetree(tmp: Path) -> dict:
    """10,000 tiny pages (flat and balanced trees) and a 1,000-level degenerate page tree."""
    out = {}

    def tiny(i: int, n: int) -> bytes:
        return text(40, 740, f"Page {i} of {n}", 18) + text(40, 700, f"marker-{i:05d}", 10) + b"40 690 m 300 690 l S"

    d = Doc("10,000 pages, flat tree")
    for i in range(1, 10001):
        d.page(tiny(i, 10000))
    out["10000-pages-flat"] = d.finish()

    d = Doc("10,000 pages, balanced tree")
    leaves = []
    for i in range(1, 10001):
        leaves.append(d.page(tiny(i, 10000), parent=-1))
    level = leaves
    counts = {p: 1 for p in leaves}
    while len(level) > 10:
        nxt = []
        for j in range(0, len(level), 10):
            group = level[j:j + 10]
            n = d.reserve()
            counts[n] = sum(counts[g] for g in group)
            d.set(n, f"<< /Type /Pages /Parent PARENT /Kids [{' '.join(f'{g} 0 R' for g in group)}] /Count {counts[n]} >>")
            for g in group:
                d.objs[g] = d.objs[g].replace(b"/Parent -1 0 R", b"/Parent %d 0 R" % n).replace(b"/Parent PARENT", b"/Parent %d 0 R" % n)
            nxt.append(n)
        level = nxt
    for g in level:
        d.objs[g] = d.objs[g].replace(b"/Parent PARENT", b"/Parent %d 0 R" % d.pages)
    out["10000-pages-balanced"] = d.finish(kids=level, count=10000)

    d = Doc("1,000-level page tree chain")
    prev = d.pages
    nodes = []
    for i in range(1, 1001):
        n = d.reserve()
        p = d.page(tiny(i, 1000), parent=n)
        nodes.append((n, p, prev))
        prev = n
    for depth, (n, p, parent) in enumerate(nodes):
        child = f" {nodes[depth + 1][0]} 0 R" if depth + 1 < len(nodes) else ""
        d.set(n, f"<< /Type /Pages /Parent {parent} 0 R /Kids [{p} 0 R{child}] /Count {1000 - depth} >>")
    out["1000-deep-chain"] = d.finish(kids=[nodes[0][0]], count=1000)
    return out
