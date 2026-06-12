#!/bin/bash

# ============================================================================
# pdf_viewer — one-shot provenance backfill.
#
# The cache is permanently mixed-provenance: ~153 Docker-era entries (amd64
# pdf2htmlEX 0.18.8.rc2 / poppler 0.89.0) plus newer native-arm64 entries,
# indistinguishable without forensics. This stamps a "provenance" object into
# every cache entry's meta.json that lacks one, using a documented date-based
# heuristic:
#
#   Everything cached BEFORE 2026-06-12 was Docker (converter=docker-amd64).
#
# Exceptions, treated as native-arm64 (the 2026-06-12 native migration):
#   - hash aa899dbceecd0cfb (known native entry)
#   - any entry whose mappings.tsv timestamp is 2026-06-12
#
# Only meta.json is written (created if absent, merged if present — pdfinfo
# fields are preserved). HTML and all other cache files are never touched.
# Idempotent: entries that already carry a "provenance" object are skipped.
#
# Usage: backfill-provenance.sh [--dry-run]
# ============================================================================

set -u

REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
CACHE_DIR="$HOME/.cache/pdf_viewer"
MAP_FILE="$CACHE_DIR/mappings.tsv"
WRITER="$REPO_DIR/scripts/write-provenance.py"

# Docker-era toolchain versions (amd64 image). poppler 0.89.0 is the version
# baked into the retired pdf2htmlEX Docker image (see ADR 0011); pdf2htmlEX
# itself was 0.18.8.rc2 in both eras.
DOCKER_PDF2HTMLEX="0.18.8.rc2"
DOCKER_POPPLER="0.89.0"
NATIVE_PDF2HTMLEX="0.18.8.rc2"
NATIVE_POPPLER="24.06.1"

# Hard-coded native exceptions (beyond the mappings.tsv date check).
NATIVE_HASHES=("aa899dbceecd0cfb")

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

[[ -d "$CACHE_DIR" ]] || { echo "no cache dir: $CACHE_DIR" >&2; exit 1; }

# Build the set of "converted today (2026-06-12)" hashes from mappings.tsv.
TODAY_HASHES=""
if [[ -f "$MAP_FILE" ]]; then
    TODAY_HASHES=$(awk -F'\t' '$1 ~ /^2026-06-12/ {print $3}' "$MAP_FILE")
fi

is_native() {
    local h="$1"
    local n
    for n in "${NATIVE_HASHES[@]}"; do
        [[ "$h" == "$n" ]] && return 0
    done
    # mappings.tsv timestamp == today
    if [[ -n "$TODAY_HASHES" ]]; then
        while IFS= read -r th; do
            [[ "$h" == "$th" ]] && return 0
        done <<< "$TODAY_HASHES"
    fi
    return 1
}

marked_docker=0
marked_native=0
skipped=0

for d in "$CACHE_DIR"/*/; do
    h=$(basename "$d")
    [[ "$h" =~ ^[0-9a-f]{16}$ ]] || continue   # skip _assets, etc.
    meta="$d/meta.json"

    # Idempotent: skip entries that already have provenance.
    if [[ -f "$meta" ]] && python3 -c "import json,sys; sys.exit(0 if 'provenance' in json.load(open(sys.argv[1])) else 1)" "$meta" 2>/dev/null; then
        skipped=$((skipped + 1))
        continue
    fi

    if is_native "$h"; then
        converter="native-arm64"
        p2h="$NATIVE_PDF2HTMLEX"
        pop="$NATIVE_POPPLER"
        marked_native=$((marked_native + 1))
    else
        converter="docker-amd64"
        p2h="$DOCKER_PDF2HTMLEX"
        pop="$DOCKER_POPPLER"
        marked_docker=$((marked_docker + 1))
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        echo "would mark $h -> $converter"
        continue
    fi

    python3 "$WRITER" "$meta" \
        --converter "$converter" \
        --pdf2htmlex "$p2h" \
        --poppler "$pop" \
        --extra backfilled=true \
        || echo "provenance backfill FAILED: $h" >&2
done

echo "backfill done: $marked_docker docker-amd64, $marked_native native-arm64, $skipped already-had-provenance (skipped)"
