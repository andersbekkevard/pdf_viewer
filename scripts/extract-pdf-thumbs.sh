#!/bin/bash

# ============================================================================
# Extract per-page thumbnail JPEGs into <out_thumbs_dir>/N.jpg
#
# Usage: extract-pdf-thumbs.sh <pdf_path> <out_thumbs_dir>
#
# Uses pdftocairo at -r 24 DPI + JPEG q=70 — produces ~200px-wide thumbs
# at roughly 10-20 KB per page for typical text-heavy PDFs.
#
# Prefers local `pdftocairo` (brew install poppler) — fast, no Docker
# startup. Falls back to the pdf2htmlEX Docker image (ships poppler-utils)
# if no local pdftocairo is on PATH.
#
# pdftocairo's default naming is zero-padded based on page count
# (`t-01.jpg`, `t-001.jpg`, …). We rename to unpadded N.jpg so the overlay
# JS can template URLs without having to know the page-count digit width.
# ============================================================================

set -u

PDF="${1:-}"
OUT_DIR="${2:-}"
if [[ -z "$PDF" || -z "$OUT_DIR" ]]; then
    echo "usage: $(basename "$0") <pdf> <out_thumbs_dir>" >&2
    exit 2
fi
[[ -f "$PDF" ]] || { echo "not a file: $PDF" >&2; exit 1; }

IMAGE="pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"

mkdir -p "$OUT_DIR"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# -cropbox matches pdf2htmlEX's rendering bounds — otherwise we get the
# MediaBox (default) which includes printer marks / bleed, shifting the
# content inward vs. the main viewer and exposing edge artifacts.
if command -v pdftocairo >/dev/null 2>&1; then
    pdftocairo -jpeg -r 24 -jpegopt quality=70 -cropbox \
        "$PDF" "$TMP/t" 2>/dev/null || {
        echo "pdftocairo (local) failed on $PDF" >&2
        exit 1
    }
else
    pdf_dir=$(dirname "$PDF")
    pdf_name=$(basename "$PDF")
    docker run --rm --platform linux/amd64 \
        --entrypoint pdftocairo \
        -v "$pdf_dir":/pdf:ro \
        -v "$TMP":/out \
        "$IMAGE" \
        -jpeg -r 24 -jpegopt quality=70 -cropbox \
        "/pdf/$pdf_name" /out/t 2>/dev/null || {
        echo "pdftocairo (docker) failed on $PDF" >&2
        exit 1
    }
fi

# Rename t-01.jpg / t-001.jpg → N.jpg (unpadded — trivial JS templating).
count=0
for f in "$TMP"/t-*.jpg; do
    [[ -e "$f" ]] || continue
    base=$(basename "$f")
    num=${base#t-}
    num=${num%.jpg}
    num=$((10#$num))
    mv "$f" "$OUT_DIR/$num.jpg"
    count=$((count + 1))
done

if [[ "$count" -eq 0 ]]; then
    echo "pdftocairo produced no output for $PDF" >&2
    exit 1
fi

# Sidecar manifest — lets the overlay (or upgrade tooling) cheaply detect
# whether thumbs exist without iterating the directory.
printf '%s\n' "$count" > "$OUT_DIR/.count"
