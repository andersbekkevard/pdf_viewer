"""Generators built with ReportLab (base-14 fonts, AcroForm, non-embedded CJK CID fonts, stripped ToUnicode)."""

from __future__ import annotations

import io
from pathlib import Path

from rawpdf import Doc, label_page, pdf_string, text
from registry import generator

PANGRAM = "The quick brown fox jumps over the lazy dog 0123456789"
LATIN1 = "Blåbærsyltetøy, Ærlig Øystein, Åse; Straße, Übung; élève, garçon; ¿Qué? ¡Sí! £ € © ® ° ± µ ¶ §"


def canvas(buf, title: str, size=(612, 792)):
    from reportlab.pdfgen.canvas import Canvas
    c = Canvas(buf, pagesize=size, invariant=1)
    c.setTitle(title)
    c.setProducer("pdf_viewer bench/corpus/synth (ReportLab)")
    return c


@generator("base14", ["standard-14", "nonembedded-truetype"])
def base14(tmp: Path) -> dict:
    """Non-embedded base-14 fonts incl. Symbol and ZapfDingbats; non-embedded TrueType names (Arial, Calibri)."""
    out = {}
    buf = io.BytesIO()
    c = canvas(buf, "Base-14 fonts, not embedded")
    y = 740
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, y, "The 14 standard fonts, none embedded")
    y -= 30
    for f in ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique", "Times-Roman", "Times-Bold",
              "Times-Italic", "Times-BoldItalic", "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"):
        c.setFont("Helvetica", 8)
        c.drawString(40, y + 12, f)
        c.setFont(f, 13)
        c.drawString(40, y, PANGRAM)
        c.drawString(40, y - 16, LATIN1)
        y -= 48
    c.setFont("Helvetica", 8)
    c.drawString(40, y + 12, "Symbol")
    c.setFont("Symbol", 14)
    c.drawString(40, y, "αβγδεζηθικλμνξοπρστυφχψω ΑΒΓΔ ∀∃∈∉∑∏∫≈≠≤≥∞")
    y -= 30
    c.setFont("Helvetica", 8)
    c.drawString(40, y + 12, "ZapfDingbats")
    c.setFont("ZapfDingbats", 14)
    c.drawString(40, y, "✁✂✃✄✆✇✈✉✌✍✎✏✐✑✒✓✔✕✖✗✘✙✚✛✜✝✞✟")
    c.showPage()
    c.save()
    out["standard-14"] = buf.getvalue()

    d = Doc("Non-embedded TrueType fonts")
    widths = " ".join(["556"] * 224)
    fonts = {}
    for key, name, flags in (("A1", "Arial", 32), ("A2", "Arial,Bold", 32), ("A3", "Calibri", 32),
                             ("A4", "Garamond", 34), ("A5", "Wingdings-Regular", 4), ("A6", "MadeUpFontName", 32)):
        desc = d.add(f"<< /Type /FontDescriptor /FontName /{name} /Flags {flags} /FontBBox [-665 -325 2000 1006] "
                     f"/ItalicAngle 0 /Ascent 905 /Descent -212 /CapHeight 716 /StemV 80 >>")
        fonts[key] = d.add(f"<< /Type /Font /Subtype /TrueType /BaseFont /{name} /FirstChar 32 /LastChar 255 "
                           f"/Widths [{widths}] /Encoding /WinAnsiEncoding /FontDescriptor {desc} 0 R >>")
    c2 = bytearray(label_page("TrueType fonts referenced by name, not embedded", [
        "The viewer must substitute. Widths are all 556, so the substitute is stretched or squeezed."]))
    y = 640
    for key, f in fonts.items():
        c2 += text(40, y + 14, f"font {key}", 8, "F1") + text(40, y, PANGRAM, 14, key) + text(40, y - 18, LATIN1, 11, key)
        y -= 70
    d.page(bytes(c2), fonts=" ".join(f"/{k} {v} 0 R" for k, v in fonts.items()))
    out["nonembedded-truetype"] = d.finish()
    return out


@generator("forms", ["reportlab-acroform"])
def forms(tmp: Path) -> dict:
    """AcroForm made by ReportLab, with appearance streams: text, checkbox, radio, choice, list."""
    buf = io.BytesIO()
    c = canvas(buf, "ReportLab AcroForm")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(40, 740, "Form fields with appearance streams")
    c.setFont("Helvetica", 12)
    f = c.acroForm
    rows = [("Name", lambda y: f.textfield(name="name", value="Anders Test", x=200, y=y, width=300, height=20)),
            ("Email", lambda y: f.textfield(name="email", value="", x=200, y=y, width=300, height=20, borderColor=None)),
            ("Subscribe", lambda y: f.checkbox(name="subscribe", checked=True, x=200, y=y, size=18)),
            ("Unchecked", lambda y: f.checkbox(name="other", checked=False, x=200, y=y, size=18)),
            ("Size S", lambda y: f.radio(name="size", value="S", selected=False, x=200, y=y, size=18)),
            ("Size M", lambda y: f.radio(name="size", value="M", selected=True, x=200, y=y, size=18)),
            ("City", lambda y: f.choice(name="city", value="Boston", options=["Oslo", "Boston", "Trondheim"], x=200, y=y, width=200, height=20)),
            ("Fruits", lambda y: f.listbox(name="fruits", value="pear", options=["apple", "pear", "plum"], x=200, y=y - 40, width=200, height=60))]
    y = 690
    for label, make in rows:
        c.drawString(40, y + 5, label)
        make(y)
        y -= 50
    c.showPage()
    c.save()
    return {"reportlab-acroform": buf.getvalue()}


CJK = {
    "HeiseiMin-W3": "これは日本語のテスト文書です。横書きと縦書きを確認します。",
    "HeiseiKakuGo-W5": "フォントが埋め込まれていない日本語のゴシック体。",
    "STSong-Light": "这是一个简体中文测试文档，用于检查字体替换和文本提取。",
    "MSung-Light": "這是一個繁體中文測試文件，用於檢查字型替換。",
    "HYSMyeongJo-Medium": "이것은 한국어 테스트 문서입니다. 글꼴 대체를 확인합니다.",
    "HYGothic-Medium": "임베드되지 않은 한국어 고딕 글꼴입니다.",
}


@generator("cjk", ["nonembedded-cid", "nonembedded-vertical"])
def cjk(tmp: Path) -> dict:
    """Non-embedded CJK CID fonts (Adobe-Japan1/GB1/CNS1/Korea1) horizontal and vertical (UniJIS-UCS2-V)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    out = {}
    buf = io.BytesIO()
    c = canvas(buf, "Non-embedded CJK fonts")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 740, "Non-embedded CID fonts: the viewer needs CJK fallback fonts")
    y = 690
    for name, s in CJK.items():
        pdfmetrics.registerFont(UnicodeCIDFont(name))
        c.setFont("Helvetica", 9)
        c.drawString(40, y + 18, name)
        c.setFont(name, 16)
        c.drawString(40, y, s)
        y -= 60
    c.showPage()
    c.save()
    out["nonembedded-cid"] = buf.getvalue()

    buf = io.BytesIO()
    c = canvas(buf, "Vertical CJK, non-embedded")
    vfont = UnicodeCIDFont("HeiseiMin-W3", isVertical=True)
    pdfmetrics.registerFont(vfont)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 750, "Vertical writing (UniJIS-UCS2-V), columns right to left")
    c.setFont(vfont.fontName, 18)
    for i, line in enumerate(("縦書きの日本語の文章です。", "右から左へ列が進みます。", "句読点の位置にも注意。")):
        c.drawString(540 - i * 40, 700, line)
    c.showPage()
    c.save()
    out["nonembedded-vertical"] = buf.getvalue()
    return out


@generator("tounicode-stripped", ["latin-truetype", "cjk-truetype"], system_fonts=True)
def tounicode_stripped(tmp: Path) -> dict:
    """Embedded TrueType subsets with custom encodings whose ToUnicode maps were removed: copy yields garbage."""
    import pikepdf
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    out = {}
    jobs = {
        "latin-truetype": ("/System/Library/Fonts/Supplemental/Arial.ttf", 0,
                           ["Embedded Arial subset, ToUnicode removed.", PANGRAM, LATIN1,
                            "Search for 'quick' fails if the viewer relies on ToUnicode."]),
        "cjk-truetype": ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 0,
                         ["Embedded Arial Unicode subset (CJK glyphs), ToUnicode removed.", "这是一个简体中文测试文档。",
                          "これは日本語のテストです。", "Mixed Latin text 12345."]),
    }
    for variant, (path, idx, lines) in jobs.items():
        if not Path(path).exists():
            continue
        fname = f"T{variant[:3]}"
        pdfmetrics.registerFont(TTFont(fname, path, subfontIndex=idx))
        buf = io.BytesIO()
        c = canvas(buf, f"ToUnicode stripped: {variant}")
        y = 720
        for line in lines:
            c.setFont(fname, 16)
            c.drawString(40, y, line)
            y -= 36
        c.showPage()
        c.save()
        with pikepdf.open(io.BytesIO(buf.getvalue())) as pdf:
            for page in pdf.pages:
                for _, font in page.Resources.Font.items():
                    if "/ToUnicode" in font:
                        del font["/ToUnicode"]
            o = io.BytesIO()
            pdf.save(o, deterministic_id=True)
            out[variant] = o.getvalue()
    return out
