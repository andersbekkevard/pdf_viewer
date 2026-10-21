#!/usr/bin/env bash
# Rebuild the text-fidelity fixtures from source. The PDFs are committed, so
# this is needed only when a source changes. Requires TeX Live (latex, dvips,
# pdflatex), Ghostscript's ps2pdf and uv.
#
#   dvips_type3.pdf      Times text with Computer Modern math as Type 3 bitmap
#                        fonts (dvips -Ppk), the font mix of pre-2000 TeX PDFs.
#   latex_bigdelims.pdf  pdflatex with embedded Type 1 CM, including the cmex
#                        extension font whose delimiters hang 3 em below the
#                        baseline.
#   reportlab_base14.pdf non-embedded base-14 fonts the viewer must substitute.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp dvips_type3.tex latex_bigdelims.tex "$work/"
(cd "$work" \
    && latex -interaction=batchmode dvips_type3.tex >/dev/null \
    && dvips -q -Ppk -D 600 dvips_type3.dvi -o dvips_type3.ps \
    && ps2pdf dvips_type3.ps dvips_type3.pdf \
    && pdflatex -interaction=batchmode latex_bigdelims.tex >/dev/null)
cp "$work/dvips_type3.pdf" "$work/latex_bigdelims.pdf" .
uv run --with reportlab python reportlab_base14.py
