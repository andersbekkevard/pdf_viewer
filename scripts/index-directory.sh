#!/bin/bash

# ============================================================================
# pdf_viewer — bulk directory indexer.
#
# Usage: index-directory.sh <folder>
#
# Recursively finds every *.pdf under <folder> (via fd), converts each one
# into the cache, skips entries whose content hash is already present.
# Idempotent — second run on the same folder is a no-op.
#
# Invoked via Raycast wrapper at
#   raycast/pdf-viewer-index-folder.sh
# which also takes the folder path as a Raycast argument.
#
# Requires Docker running (see ADR 0004). Fails fast otherwise.
# ============================================================================

set -u

# Defined early so validation failures below can surface via macOS
# notification. Raycast silent mode doesn't display stderr, and without
# this the script dies invisibly when given a bad path.
notify() {
    osascript -e "display notification \"$1\" with title \"pdf_viewer\"" >/dev/null 2>&1
}

DIR_ARG="${1:-}"
if [[ -z "$DIR_ARG" ]]; then
    notify "No folder argument given"
    echo "usage: $(basename "$0") <folder>" >&2
    exit 2
fi

# Expand leading ~ — Raycast passes the literal string, no shell expansion
DIR="${DIR_ARG/#\~/$HOME}"
if [[ ! -d "$DIR" ]]; then
    notify "Folder not found: $DIR_ARG"
    echo "not a directory: $DIR" >&2
    exit 1
fi

REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
ASSET_SRC="$REPO_DIR/assets"
CACHE_DIR="$HOME/.cache/pdf_viewer"
LOG_FILE="$CACHE_DIR/log"
MAP_FILE="$CACHE_DIR/mappings.tsv"
ASSET_LINK="$CACHE_DIR/_assets"
IMAGE="pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"
OVERLAY_VERSION=23
INJECTOR="$REPO_DIR/scripts/inject-overlay.py"
TEXT_EXTRACTOR="$REPO_DIR/scripts/extract-find-text.py"

mkdir -p "$CACHE_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }
say() { printf '%s\n' "$*"; log "$*"; }
die() { printf 'error: %s\n' "$*" >&2; log "FAIL: $*"; exit 1; }

# Asset symlink (same guarantee pdf2html-convert.sh makes)
if [[ ! -L "$ASSET_LINK" ]]; then
    rm -rf "$ASSET_LINK" 2>/dev/null
    ln -s "$ASSET_SRC" "$ASSET_LINK" || die "could not link assets dir"
fi

FD=$(command -v fd || command -v fdfind || true)
[[ -n "$FD" ]] || die "fd not found — install via 'brew install fd'"

if ! docker info >/dev/null 2>&1; then
    notify "Docker daemon not running"
    die "Docker daemon not running — start Docker.app"
fi

# Discover PDFs. macOS ships bash 3.2 (no mapfile), so read-into-array by hand.
PDFS=()
while IFS= read -r line; do
    PDFS+=("$line")
done < <("$FD" -t f -e pdf -e PDF . "$DIR" 2>/dev/null)
total=${#PDFS[@]}
if [[ $total -eq 0 ]]; then
    say "index: no PDFs under $DIR"
    exit 0
fi

say "index: $total PDFs under $DIR"
notify "Indexing $total PDFs…"

converted=0
skipped=0
failed=0

for idx in "${!PDFS[@]}"; do
    pdf="${PDFS[$idx]}"
    n=$((idx + 1))
    pdf_name=$(basename "$pdf")
    pdf_dir=$(dirname "$pdf")

    # Content hash = stable across moves/renames
    hash=$(shasum -a 256 "$pdf" | awk '{print $1}' | head -c 16)
    out_dir="$CACHE_DIR/$hash"
    mkdir -p "$out_dir"

    # Cache hit if *any* html exists in this hash dir — two PDFs that share
    # content (e.g. the same textbook under different filenames) collide on
    # hash and point at the same converted bundle.
    existing_html=$(ls "$out_dir"/*.html 2>/dev/null | head -1)
    if [[ -n "$existing_html" ]]; then
        out_name=$(basename "$existing_html")
        log "[${n}/${total}] skip cached: $pdf -> $out_name"
        skipped=$((skipped + 1))
    else
        out_name="${pdf_name%.*}.html"
        say "[${n}/${total}] convert: $pdf"
        if ! docker run --rm --platform linux/amd64 \
                -e LC_ALL=C.UTF-8 -e LANG=C.UTF-8 \
                -v "$pdf_dir":/pdf:ro \
                -v "$out_dir":/out \
                -w /pdf \
                "$IMAGE" \
                --dest-dir /out \
                "$pdf_name" \
                > >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE") \
                2> >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE"); then
            log "[${n}/${total}] pdf2htmlEX FAILED: $pdf"
            failed=$((failed + 1))
            continue
        fi
        if ! python3 "$INJECTOR" "$out_dir/$out_name" "${pdf_name%.*}" \
                "$OVERLAY_VERSION" >>"$LOG_FILE" 2>&1; then
            log "[${n}/${total}] inject FAILED: $pdf"
            failed=$((failed + 1))
            continue
        fi
        converted=$((converted + 1))
    fi

    # Metadata — non-fatal if it fails. Written whether this was a fresh
    # convert or a cache hit (covers entries converted before meta.json
    # was plumbed in).
    if [[ ! -f "$out_dir/meta.json" ]]; then
        "$REPO_DIR/scripts/extract-pdf-meta.sh" "$pdf" "$out_dir/meta.json" \
            >>"$LOG_FILE" 2>&1 \
            || log "[${n}/${total}] meta extraction failed for $pdf"
    fi

    # Native Cmd-F support — generated from cached HTML, so cache hits created
    # before this feature can be backfilled without reconversion.
    if [[ ! -f "$out_dir/text.json" ]]; then
        final_html=$(ls "$out_dir"/*.html 2>/dev/null | head -1)
        if [[ -n "$final_html" ]]; then
            python3 "$TEXT_EXTRACTOR" "$final_html" "$out_dir/text.json" \
                >>"$LOG_FILE" 2>&1 \
                || log "[${n}/${total}] find-text extraction failed for $pdf"
        fi
    fi

    # Upsert mapping (dedup on hash). Happens for cache hits too so that a
    # PDF moved to a new path refreshes its source_ref row.
    {
        if [[ -f "$MAP_FILE" ]]; then
            awk -F'\t' -v h="$hash" '$3 != h' "$MAP_FILE"
        fi
        printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$pdf" "$hash" "$out_dir/$out_name"
    } > "$MAP_FILE.tmp" && mv "$MAP_FILE.tmp" "$MAP_FILE"
done

summary="index done in $DIR: $converted converted, $skipped skipped, $failed failed"
say "$summary"
notify "$summary"
exit $(( failed > 0 ? 1 : 0 ))
