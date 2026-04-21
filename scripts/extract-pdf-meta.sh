#!/bin/bash

# ============================================================================
# Extract PDF metadata into meta.json.
#
# Usage: extract-pdf-meta.sh <pdf_path> <out_meta_json>
#
# Prefers local `pdfinfo` (from `brew install poppler`) — fast, no docker
# startup. Falls back to the pdf2htmlEX Docker image, which ships
# poppler-utils inside, if no local pdfinfo is on PATH.
# ============================================================================

set -u

PDF="${1:-}"
OUT="${2:-}"
if [[ -z "$PDF" || -z "$OUT" ]]; then
    echo "usage: $(basename "$0") <pdf> <out.json>" >&2
    exit 2
fi
[[ -f "$PDF" ]] || { echo "not a file: $PDF" >&2; exit 1; }

REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
IMAGE="pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"
PARSER="$REPO_DIR/scripts/extract-meta.py"

RAW=$(mktemp)
trap 'rm -f "$RAW"' EXIT

if command -v pdfinfo >/dev/null 2>&1; then
    pdfinfo -enc UTF-8 "$PDF" > "$RAW" 2>/dev/null || {
        echo "pdfinfo (local) failed on $PDF" >&2
        exit 1
    }
else
    pdf_dir=$(dirname "$PDF")
    pdf_name=$(basename "$PDF")
    docker run --rm --platform linux/amd64 \
        --entrypoint pdfinfo \
        -v "$pdf_dir":/pdf:ro \
        "$IMAGE" \
        -enc UTF-8 "/pdf/$pdf_name" > "$RAW" 2>/dev/null || {
        echo "pdfinfo (docker) failed on $PDF" >&2
        exit 1
    }
fi

python3 "$PARSER" "$RAW" > "$OUT"
