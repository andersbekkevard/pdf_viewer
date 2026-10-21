"""Generators that print HTML written here to PDF with headless Google Chrome (Skia PDF backend)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from registry import generator

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

STYLE = """<style>
@page { size: A4; margin: 18mm; }
body { font: 14pt/1.6 serif; }
h1 { font: bold 18pt sans-serif; }
.box { border: 1px solid #999; padding: 6pt; margin: 8pt 0; }
</style>"""

PAGES = {
    "cjk": ("ja", """<h1>CJK text, embedded fonts (Chrome print)</h1>
<p lang="ja">これは日本語のテスト文書です。ひらがな、カタカナ、漢字が混在しています。全角英数字ＡＢＣ１２３も含みます。</p>
<p lang="zh-Hans">这是一个简体中文测试文档，用于检查文本选择、复制和搜索。中文没有单词之间的空格。</p>
<p lang="zh-Hant">這是一個繁體中文測試文件，用於檢查文字選取與搜尋功能。</p>
<p lang="ko">이것은 한국어 테스트 문서입니다. 한글은 단어 사이에 공백이 있습니다.</p>
<p lang="ja">ルビ：<ruby>漢字<rt>かんじ</rt></ruby>と<ruby>東京<rt>とうきょう</rt></ruby>。</p>""" + "".join(
        f"<p lang='ja'>段落{i}：検索のための目印テキスト「マーカー{i}」を含む文章です。</p>" for i in range(1, 40))),
    "vertical-cjk": ("ja", """<h1>縦書き (writing-mode: vertical-rl)</h1>
<div style="writing-mode: vertical-rl; height: 220mm; font-size: 16pt;">
<p>これは縦書きの日本語の文章です。列は右から左へ進みます。</p>
<p>数字の縦中横：<span style="text-combine-upright: all">25</span>日、英字 PDF viewer はそのまま回転します。</p>
<p>句読点、括弧「かぎかっこ」と長音記号ー の位置も確認します。</p>""" + "".join(
        f"<p>第{i}段落の縦書きテキストです。検索語「たてがき{i}」。</p>" for i in range(1, 25)) + "</div>"),
    "rtl": ("ar", """<h1 dir="ltr">Right-to-left and bidirectional text</h1>
<p lang="ar" dir="rtl">هذا مستند اختبار باللغة العربية للتحقق من عرض النص من اليمين إلى اليسار واختيار النص ونسخه.</p>
<p lang="he" dir="rtl">זהו מסמך בדיקה בעברית לבדיקת כיוון הטקסט מימין לשמאל, בחירה והעתקה.</p>
<p lang="fa" dir="rtl">این یک سند آزمایشی به زبان فارسی است که شامل اعداد ۱۲۳۴ نیز می‌شود.</p>
<p lang="ur" dir="rtl" style="font-family: 'Noto Nastaliq Urdu'">یہ اردو زبان میں ایک آزمائشی دستاویز ہے۔</p>
<p dir="rtl" lang="ar">نص مختلط: الطلب رقم 4521 بتاريخ 2026-10-20 بقيمة 1,250.75 USD من شركة ACME Inc.</p>
<p dir="ltr">Mixed LTR paragraph with Hebrew שלום עולם and Arabic مرحبا بالعالم and the number 42 inside.</p>
<table dir="rtl" border="1" style="border-collapse: collapse"><tr><th>الاسم</th><th>الكمية</th></tr>
<tr><td>تفاح</td><td>12</td></tr><tr><td>برتقال</td><td>7</td></tr></table>""" + "".join(
        f"<p lang='ar' dir='rtl'>الفقرة رقم {i}: هذه فقرة إضافية تحتوي على كلمة البحث علامة{i}.</p>" for i in range(1, 30))),
    "complex-scripts": ("hi", """<h1>Complex scripts, combining marks and emoji</h1>
<p lang="hi">यह एक परीक्षण दस्तावेज़ है। संयुक्ताक्षर क्ष त्र ज्ञ श्र की जाँच करें।</p>
<p lang="bn">এটি একটি পরীক্ষামূলক নথি।</p>
<p lang="ta">இது ஒரு சோதனை ஆவணம்.</p>
<p lang="th">นี่คือเอกสารทดสอบภาษาไทยซึ่งไม่มีช่องว่างระหว่างคำ</p>
<p lang="el">Αυτό είναι ένα δοκιμαστικό έγγραφο. Ελληνικά με τόνους: άέήίόύώ.</p>
<p lang="ru">Это тестовый документ на русском языке.</p>
<p>Combining marks: e&#x301; a&#x308; n&#x303; vs precomposed é ä ñ. Zero-width joiner: a&#x200D;b; soft hy&shy;phen.</p>
<p>Emoji (colour bitmap font): 😀 👍🏽 👨‍👩‍👧 🇳🇴 ❤️ ✅</p>
<p>Math alphanumerics: 𝐀𝐁𝐂 𝑥𝑦𝑧 ℝ ℕ ∑ ∫ √2</p>"""),
}


@generator("browser", list(PAGES), system_fonts=True)
def browser(tmp: Path) -> dict:
    """Chrome print-to-PDF: CJK, vertical CJK, Arabic/Hebrew/Persian bidi, Indic/Thai/emoji (embedded subsets)."""
    if not Path(CHROME).exists():
        raise RuntimeError("Google Chrome not found")
    out = {}
    for name, (lang, html) in PAGES.items():
        page = tmp / f"{name}.html"
        page.write_text(f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
                        f"<title>{name}</title>{STYLE}</head><body>{html}</body></html>", encoding="utf-8")
        pdf = tmp / f"{name}.pdf"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                        "--disable-extensions", f"--user-data-dir={tmp / 'profile'}", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", page.as_uri()],
                       capture_output=True, timeout=120, check=False)
        if not pdf.exists() or pdf.stat().st_size == 0:
            raise RuntimeError(f"Chrome did not produce {pdf.name}")
        out[name] = pdf
    return out
