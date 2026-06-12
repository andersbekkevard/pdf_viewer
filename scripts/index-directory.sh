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
# Requires the native pdf2htmlEX binary (install-native-pdf2htmlex.sh).
# Fails fast otherwise.
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
# Native arm64 pdf2htmlEX (replaces the old amd64 Docker image). --data-dir
# is passed explicitly on every invocation; the binary's baked default is
# fragile.
NATIVE_BIN="$HOME/.local/opt/pdf2htmlEX/bin/pdf2htmlEX"
NATIVE_DATA_DIR="$HOME/.local/opt/pdf2htmlEX/share/pdf2htmlEX"
# Baked poppler-data default is a version-pinned Cellar path that breaks on
# brew upgrade; pass the stable symlink explicitly (needed for CJK/CID PDFs).
NATIVE_POPPLER_DATA="/opt/homebrew/share/poppler"
INJECTOR="$REPO_DIR/scripts/inject-overlay.py"
EXTERNALIZER="$REPO_DIR/scripts/externalize-page-images.py"
LIGHT_VARIANTS_ENABLED="${PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT:-0}"

mkdir -p "$CACHE_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }
say() { printf '%s\n' "$*"; log "$*"; }
die() { printf 'error: %s\n' "$*" >&2; log "FAIL: $*"; exit 1; }

# Asset symlink (same guarantee pdf2html-convert.sh makes)
if [[ ! -L "$ASSET_LINK" ]]; then
    rm -rf "$ASSET_LINK" 2>/dev/null
    ln -s "$ASSET_SRC" "$ASSET_LINK" || die "could not link assets dir"
fi

# Overlay asset version is a content hash derived by the injector. Capture it
# once for the provenance writer (the injector itself derives it per call).
OVERLAY_HASH="$(uv run "$INJECTOR" --print-version)"

FD=$(command -v fd || command -v fdfind || true)
[[ -n "$FD" ]] || die "fd not found — install via 'brew install fd'"

if [[ ! -x "$NATIVE_BIN" ]]; then
    notify "native pdf2htmlEX not installed"
    die "native pdf2htmlEX not installed — run scripts/install-native-pdf2htmlex.sh"
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

    # Content hash = stable across moves/renames
    hash=$(shasum -a 256 "$pdf" | awk '{print $1}' | head -c 16)
    out_dir="$CACHE_DIR/$hash"
    mkdir -p "$out_dir"

    # Cache hit if *any* html exists in this hash dir — two PDFs that share
    # content (e.g. the same textbook under different filenames) collide on
    # hash and point at the same converted bundle.
    did_convert=0
    existing_html=$(find "$out_dir" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' | sort | head -1)
    if [[ -n "$existing_html" ]]; then
        out_name=$(basename "$existing_html")
        log "[${n}/${total}] skip cached: $pdf -> $out_name"
        skipped=$((skipped + 1))
    else
        out_name="${pdf_name%.*}.html"
        say "[${n}/${total}] convert: $pdf"
        if ! "$NATIVE_BIN" --data-dir "$NATIVE_DATA_DIR" \
                --poppler-data-dir "$NATIVE_POPPLER_DATA" --dest-dir "$out_dir" \
                "$pdf" >>"$LOG_FILE" 2>&1; then
            log "[${n}/${total}] pdf2htmlEX FAILED: $pdf"
            failed=$((failed + 1))
            continue
        fi
        if ! uv run "$INJECTOR" "$out_dir/$out_name" "${pdf_name%.*}" \
                >>"$LOG_FILE" 2>&1; then
            log "[${n}/${total}] inject FAILED: $pdf"
            failed=$((failed + 1))
            continue
        fi
        if [[ "$LIGHT_VARIANTS_ENABLED" == "1" ]]; then
            light_out_name="${out_name%.html}.light.html"
            if uv run "$EXTERNALIZER" \
                    "$out_dir/$out_name" "$out_dir/$light_out_name" \
                    --image-dir "$out_dir/page-images" \
                    --url-prefix "/$hash/page-images/" \
                    --eager 2 \
                    --clean >>"$LOG_FILE" 2>&1; then
                uv run "$INJECTOR" "$out_dir/$light_out_name" "${pdf_name%.*}" \
                    >>"$LOG_FILE" 2>&1 \
                    || log "[${n}/${total}] light inject failed: $pdf"
            else
                log "[${n}/${total}] light variant failed: $pdf"
                rm -f "$out_dir/$light_out_name"
            fi
        else
            log "[${n}/${total}] light variant skipped pending search/selection/resolution fixes: $pdf"
        fi
        converted=$((converted + 1))
        did_convert=1
    fi

    # Conversion provenance — pipeline-owned, only on a real conversion.
    # Merges into meta.json (preserving pdfinfo fields); versions parsed from
    # the binary so reconversions after a toolchain upgrade stay accurate.
    if [[ "$did_convert" == "1" ]]; then
        python3 "$REPO_DIR/scripts/write-provenance.py" "$out_dir/meta.json" \
            --converter native-arm64 --bin "$NATIVE_BIN" \
            --overlay-version "$OVERLAY_HASH" \
            >>"$LOG_FILE" 2>&1 \
            || log "[${n}/${total}] provenance write failed for $pdf"
    fi

    # Metadata — non-fatal if it fails. Written whether this was a fresh
    # convert or a cache hit (covers entries converted before meta.json
    # was plumbed in). Gate on pdfinfo keys, not file existence — a
    # provenance-only meta.json may have just been created above.
    if ! python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if any(k in d for k in ('pages','title','author','file_size')) else 1)" "$out_dir/meta.json" 2>/dev/null; then
        "$REPO_DIR/scripts/extract-pdf-meta.sh" "$pdf" "$out_dir/meta.json" \
            >>"$LOG_FILE" 2>&1 \
            || log "[${n}/${total}] meta extraction failed for $pdf"
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
