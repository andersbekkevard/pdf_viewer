#!/bin/bash

# ============================================================================
# pdf_viewer — parallel bulk directory indexer.
#
# Usage: index-directory-parallel.sh <folder> [jobs]
#   jobs: number of concurrent conversions (default 2). Each worker invokes
#         the native pdf2htmlEX binary directly.
#
# Same contract as scripts/index-directory.sh (idempotent, content-hash cache),
# but runs conversions concurrently via xargs -P.
#
# Concurrency model:
#   - Each PDF is processed independently by a worker.
#   - Atomic claim via `mkdir "$out_dir/.converting"` prevents two workers from
#     racing on the same content hash (rare: only when the same PDF content
#     appears twice under different filenames).
#   - Mapping-file rewrites are serialized via an mkdir-based mutex.
#   - Stale `.converting` dirs from killed runs are purged at startup.
#
# Job-count default: the old Docker default was 4 because each conversion ran
# single-threaded inside its container, so saturating cores meant many
# containers. The native arm64 binary parallelizes internally (~6 threads per
# conversion), so the old 4 would oversubscribe badly. Default 2 keeps total
# in-flight threads (~2×6) near a typical Apple Silicon core count while still
# overlapping I/O-bound phases (hashing, injection, meta) across workers.
#
# Requires the native pdf2htmlEX binary (install-native-pdf2htmlex.sh).
# Fails fast otherwise.
# ============================================================================

set -u

# Defined early so validation failures below can surface via macOS
# notification. Raycast silent mode doesn't display stderr, and without
# this the script dies invisibly when given a bad path.
notify() { osascript -e "display notification \"$1\" with title \"pdf_viewer\"" >/dev/null 2>&1; }

DIR_ARG="${1:-}"
JOBS="${2:-2}"

if [[ -z "$DIR_ARG" ]]; then
    notify "No folder argument given"
    echo "usage: $(basename "$0") <folder> [jobs]" >&2
    exit 2
fi
if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || [[ "$JOBS" -lt 1 ]]; then
    notify "Invalid jobs value: $JOBS"
    echo "jobs must be a positive integer (got '$JOBS')" >&2
    exit 2
fi

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
MAP_LOCK="$CACHE_DIR/.maplock"
ASSET_LINK="$CACHE_DIR/_assets"
# Native arm64 pdf2htmlEX (replaces the old amd64 Docker image). --data-dir
# is passed explicitly on every invocation; the binary's baked default is
# fragile.
NATIVE_BIN="$HOME/.local/opt/pdf2htmlEX/bin/pdf2htmlEX"
NATIVE_DATA_DIR="$HOME/.local/opt/pdf2htmlEX/share/pdf2htmlEX"
# Baked poppler-data default is a version-pinned Cellar path that breaks on
# brew upgrade; pass the stable symlink explicitly (needed for CJK/CID PDFs).
NATIVE_POPPLER_DATA="/opt/homebrew/share/poppler"
OVERLAY_VERSION=25
INJECTOR="$REPO_DIR/scripts/inject-overlay.py"
EXTERNALIZER="$REPO_DIR/scripts/externalize-page-images.py"
LIGHT_VARIANTS_ENABLED="${PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT:-0}"

export REPO_DIR CACHE_DIR LOG_FILE MAP_FILE MAP_LOCK ASSET_LINK NATIVE_BIN NATIVE_DATA_DIR NATIVE_POPPLER_DATA OVERLAY_VERSION INJECTOR EXTERNALIZER LIGHT_VARIANTS_ENABLED

mkdir -p "$CACHE_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }
say() { printf '%s\n' "$*"; log "$*"; }
die() { printf 'error: %s\n' "$*" >&2; log "FAIL: $*"; exit 1; }

export -f log

if [[ ! -L "$ASSET_LINK" ]]; then
    rm -rf "$ASSET_LINK" 2>/dev/null
    ln -s "$ASSET_SRC" "$ASSET_LINK" || die "could not link assets dir"
fi

FD=$(command -v fd || command -v fdfind || true)
[[ -n "$FD" ]] || die "fd not found — install via 'brew install fd'"

if [[ ! -x "$NATIVE_BIN" ]]; then
    notify "native pdf2htmlEX not installed"
    die "native pdf2htmlEX not installed — run scripts/install-native-pdf2htmlex.sh"
fi

# Purge stale .converting claim dirs left behind by killed runs (>30 min old).
find "$CACHE_DIR" -maxdepth 2 -type d -name .converting -mmin +30 -exec rmdir {} + 2>/dev/null
rmdir "$MAP_LOCK" 2>/dev/null  # clear stale map lock too

# ---------------------------------------------------------------------------
# Worker — converts a single PDF. Invoked by xargs -P.
# ---------------------------------------------------------------------------
worker() {
    local pdf="$1"
    local pdf_name hash out_dir existing_html out_name rc

    [[ -f "$pdf" ]] || { log "[miss] $pdf"; return 0; }

    pdf_name=$(basename "$pdf")
    hash=$(shasum -a 256 "$pdf" | awk '{print $1}' | head -c 16)
    out_dir="$CACHE_DIR/$hash"
    mkdir -p "$out_dir"

    existing_html=$(find "$out_dir" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' | sort | head -1)

    if [[ -z "$existing_html" ]]; then
        # Attempt atomic claim on this hash. If another worker already owns
        # it, wait for them to finish and then treat as cache hit.
        if mkdir "$out_dir/.converting" 2>/dev/null; then
            out_name="${pdf_name%.*}.html"
            log "[convert] $pdf"

            if "$NATIVE_BIN" --data-dir "$NATIVE_DATA_DIR" \
                    --poppler-data-dir "$NATIVE_POPPLER_DATA" --dest-dir "$out_dir" \
                    "$pdf" >>"$LOG_FILE" 2>&1; then
                if uv run "$INJECTOR" "$out_dir/$out_name" "${pdf_name%.*}" \
                        "$OVERLAY_VERSION" >>"$LOG_FILE" 2>&1; then
                    if [[ "$LIGHT_VARIANTS_ENABLED" == "1" ]]; then
                        local light_out_name="${out_name%.html}.light.html"
                        if uv run "$EXTERNALIZER" \
                                "$out_dir/$out_name" "$out_dir/$light_out_name" \
                                --image-dir "$out_dir/page-images" \
                                --url-prefix "/$hash/page-images/" \
                                --eager 2 \
                                --clean >>"$LOG_FILE" 2>&1; then
                            uv run "$INJECTOR" "$out_dir/$light_out_name" "${pdf_name%.*}" \
                                "$OVERLAY_VERSION" >>"$LOG_FILE" 2>&1 \
                                || log "[fail-light-inject] $pdf"
                        else
                            log "[fail-light] $pdf"
                            rm -f "$out_dir/$light_out_name"
                        fi
                    else
                        log "[skip-light-disabled] $pdf"
                    fi
                    rc=0
                else
                    log "[fail-inject] $pdf"
                    rc=1
                fi
            else
                log "[fail-pdf2htmlex] $pdf"
                rc=1
            fi

            rmdir "$out_dir/.converting" 2>/dev/null
            [[ $rc -ne 0 ]] && return 1
        else
            # Another worker owns the conversion — wait up to 15 min for it.
            local waited=0
            while [[ -d "$out_dir/.converting" ]] && [[ $waited -lt 4500 ]]; do
                sleep 0.2
                waited=$((waited + 1))
            done
            existing_html=$(find "$out_dir" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' | sort | head -1)
            if [[ -z "$existing_html" ]]; then
                log "[fail-peer] $pdf (peer worker did not complete)"
                return 1
            fi
            log "[skip-peer] $pdf"
        fi
    else
        log "[skip-cached] $pdf"
    fi

    # Metadata — non-fatal.
    if [[ ! -f "$out_dir/meta.json" ]]; then
        "$REPO_DIR/scripts/extract-pdf-meta.sh" "$pdf" "$out_dir/meta.json" \
            >>"$LOG_FILE" 2>&1 || log "[fail-meta] $pdf"
    fi

    # Upsert mapping under mutex. Busy-wait on mkdir — critical section is <50ms.
    local waited=0
    while ! mkdir "$MAP_LOCK" 2>/dev/null; do
        sleep 0.02
        waited=$((waited + 1))
        [[ $waited -gt 15000 ]] && { log "[fail-lock] $pdf"; return 1; }
    done
    {
        local final_html
        final_html=$(find "$out_dir" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' | sort | head -1)
        if [[ -n "$final_html" ]]; then
            if [[ -f "$MAP_FILE" ]]; then
                awk -F'\t' -v h="$hash" '$3 != h' "$MAP_FILE"
            fi
            printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$pdf" "$hash" "$final_html"
        elif [[ -f "$MAP_FILE" ]]; then
            cat "$MAP_FILE"
        fi
    } > "$MAP_FILE.tmp.$$" && mv "$MAP_FILE.tmp.$$" "$MAP_FILE"
    rmdir "$MAP_LOCK" 2>/dev/null

    return 0
}
export -f worker

# ---------------------------------------------------------------------------
# Discover + dispatch.
# ---------------------------------------------------------------------------
total=$("$FD" -t f -e pdf -e PDF . "$DIR" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$total" -eq 0 ]]; then
    say "index: no PDFs under $DIR"
    exit 0
fi

say "index: $total PDFs under $DIR (jobs=$JOBS)"
notify "Indexing $total PDFs with $JOBS workers…"

start_ts=$(date +%s)

"$FD" -t f -e pdf -e PDF . "$DIR" -0 2>/dev/null \
    | xargs -0 -P "$JOBS" -n 1 -I{} bash -c 'worker "$@"' _ {}
rc=$?

elapsed=$(( $(date +%s) - start_ts ))

# Post-hoc summary by scanning the log tail. Counts match serial script's
# {converted, skipped, failed} semantics.
summary_converted=$(grep -c "^\[.*\] \[convert\] " "$LOG_FILE" 2>/dev/null || echo 0)
summary_skipped=$(grep -c "^\[.*\] \[skip-" "$LOG_FILE" 2>/dev/null || echo 0)
summary_failed=$(grep -c "^\[.*\] \[fail-" "$LOG_FILE" 2>/dev/null || echo 0)

summary="index done in $DIR: ${elapsed}s, xargs rc=$rc (see log for per-PDF detail)"
say "$summary"
notify "$summary"
exit $rc
