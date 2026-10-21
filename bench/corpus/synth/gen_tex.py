"""Generators that run TeX (pdflatex, latex + dvips + Ghostscript) on sources written here."""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

from gen_raw import WORDS
from registry import generator

TEXBIN = "/Library/TeX/texbin"
ENV = dict(os.environ, PATH=f"{TEXBIN}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
           SOURCE_DATE_EPOCH="1760000000", FORCE_SOURCE_DATE="1")


def run(cmd: list[str], cwd: Path) -> None:
    r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, errors="replace", timeout=1800)
    if r.returncode != 0:
        tail = (r.stdout + r.stderr)[-1500:]
        raise RuntimeError(f"{cmd[0]} failed:\n{tail}")


ARTICLE = r"""
\documentclass{article}
%(preamble)s
\usepackage{amsmath}
\begin{document}
\title{Synthetic test article: %(title)s}
\author{pdf\_viewer bench}
\date{20 October 2026}
\maketitle
\section{Ligatures and accents}
The efficient officer shuffled affluent fluffy waffles; difficult offices find fiscal flaws.
Words with ligatures: fi, fl, ff, ffi, ffl --- ``quotes'', en--dash, em---dash.
Norwegian letters: bl\aa b\ae r, \o l, \AA se, \O ystein, \AE rlig; German: \"Ubung, Stra\ss e; French: \'el\`eve, gar\c{c}on.
\section{Mathematics}
Inline math $e^{i\pi}+1=0$ and $\sum_{k=1}^{n} k = \frac{n(n+1)}{2}$ sit in running text.
\begin{equation}
  \int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}, \qquad
  \begin{pmatrix} a & b \\ c & d \end{pmatrix}^{-1} = \frac{1}{ad-bc}\begin{pmatrix} d & -b \\ -c & a \end{pmatrix}.
\end{equation}
\begin{align}
  f(x) &= \sum_{n=0}^{\infty} \frac{f^{(n)}(0)}{n!} x^n, &
  \nabla \cdot \mathbf{E} &= \frac{\rho}{\varepsilon_0}.
\end{align}
\section{Body text}
%(body)s
\begin{table}[h]\centering
\begin{tabular}{lrr}\hline Item & Count & Share \\ \hline alpha & 12 & 0.25 \\ bravo & 36 & 0.75 \\ \hline\end{tabular}
\caption{A small table.}\end{table}
Footnotes too.\footnote{This is a footnote with a ligature: efficient.}
\end{document}
"""


def body(rng: random.Random, paragraphs: int, words: int = 110) -> str:
    out = []
    for _ in range(paragraphs):
        ws = [rng.choice(WORDS) for _ in range(words)]
        ws[0] = ws[0].capitalize()
        out.append(" ".join(ws) + ".")
    return "\n\n".join(out)


def article(tmp: Path, name: str, preamble: str, title: str) -> Path:
    src = ARTICLE % {"preamble": preamble, "title": title, "body": body(random.Random(11), 12)}
    (tmp / f"{name}.tex").write_text(src)
    return tmp / f"{name}.tex"


@generator("tex", ["dvips-type3-300dpi", "dvips-type3-600dpi", "dvips-type1", "pdflatex-t1-bitmap",
                   "pdflatex-no-tounicode", "pdflatex-glyphtounicode"])
def tex(tmp: Path) -> dict:
    """TeX output: dvips bitmap (Type 3) fonts at 300/600 dpi, dvips Type 1, pdflatex with/without ToUnicode."""
    out = {}
    article(tmp, "dvi", "", "latex, dvips, ps2pdf")
    run(["latex", "-interaction=nonstopmode", "-halt-on-error", "dvi.tex"], tmp)
    for dpi in (300, 600):
        # An empty font map forces dvips to use Metafont-generated PK bitmaps for every font;
        # Ghostscript then turns them into Type 3 fonts, as in 1990s arXiv PostScript.
        run(["dvips", "-q", "-u", "/dev/null", "-D", str(dpi), "-o", f"bm{dpi}.ps", "dvi.dvi"], tmp)
        run(["ps2pdf", "-dAutoRotatePages=/None", f"bm{dpi}.ps", f"bm{dpi}.pdf"], tmp)
        out[f"dvips-type3-{dpi}dpi"] = tmp / f"bm{dpi}.pdf"
    run(["dvips", "-q", "-Ppdf", "-o", "type1.ps", "dvi.dvi"], tmp)
    run(["ps2pdf", "-dAutoRotatePages=/None", "type1.ps", "type1.pdf"], tmp)
    out["dvips-type1"] = tmp / "type1.pdf"

    # T1 encoding without cm-super installed: pdftex embeds PK bitmaps as Type 3 fonts.
    # On a TeX installation that has cm-super this produces Type 1 fonts instead.
    article(tmp, "t1", r"\usepackage[T1]{fontenc}", "pdflatex with T1 fontenc (bitmap EC fonts if no cm-super)")
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t1.tex"], tmp)
    out["pdflatex-t1-bitmap"] = tmp / "t1.pdf"
    article(tmp, "nouni", r"\pdfgentounicode=0", "pdflatex, OT1, no ToUnicode")
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "nouni.tex"], tmp)
    out["pdflatex-no-tounicode"] = tmp / "nouni.pdf"
    article(tmp, "uni", r"\input glyphtounicode \pdfgentounicode=1", "pdflatex, OT1, glyphtounicode")
    run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "uni.tex"], tmp)
    out["pdflatex-glyphtounicode"] = tmp / "uni.pdf"
    return out


BOOK_HEAD = r"""
\documentclass[11pt]{book}
\usepackage{amsmath}
\usepackage[hidelinks,bookmarksnumbered]{hyperref}
\title{A Two-Thousand-Page Synthetic Book}
\author{pdf\_viewer bench}
\date{2026}
\begin{document}
\frontmatter
\maketitle
\tableofcontents
\chapter{Preface}
This book exists to test page count, outline depth, page labels and memory.
Front matter is numbered in roman numerals, so page labels differ from page indices.
\mainmatter
"""


@generator("book", ["2000-pages"])
def book(tmp: Path) -> dict:
    """A ~2,000-page pdflatex book: chapters, sections, outline, roman front matter labels, math, footnotes."""
    rng = random.Random(2000)
    parts = [BOOK_HEAD]
    para = 0
    for ch in range(1, 41):
        parts.append(f"\\chapter{{Chapter {ch}: {' '.join(rng.choice(WORDS) for _ in range(3))}}}\n")
        for sec in range(1, 7):
            parts.append(f"\\section{{Section {ch}.{sec}}}\n")
            for sub in range(1, 3):
                parts.append(f"\\subsection{{Part {ch}.{sec}.{sub}}}\n")
                for _ in range(17):
                    para += 1
                    parts.append(body(rng, 1, rng.randint(90, 160)) + "\n\n")
                    if para % 7 == 0:
                        parts.append(f"\\begin{{equation}} x_{{{para}}} = \\sum_{{k=1}}^{{{para % 50 + 2}}} "
                                     f"\\frac{{k^2}}{{{para % 9 + 1}+k}} \\end{{equation}}\n")
                    if para % 11 == 0:
                        parts.append(f"A footnote marker here.\\footnote{{Footnote number {para} with efficient ligatures.}}\n\n")
    parts.append("\\end{document}\n")
    (tmp / "book.tex").write_text("".join(parts))
    for _ in range(2):  # second run fills the table of contents
        run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "book.tex"], tmp)
    return {"2000-pages": tmp / "book.pdf"}
