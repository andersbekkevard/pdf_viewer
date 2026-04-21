#!/bin/bash

# ============================================================================
# pdf_viewer — upgrade-cache.sh
#
# Walks ~/.cache/pdf_viewer/ and upgrades cached entries after overlay or
# engine changes. Two modes, picked explicitly:
#
#   --mode=inject
#       Re-run the title/favicon/overlay-tag injector (inject-overlay.py) on
#       every cached <hash>/<stem>.html. Strips prior id="pdf2html-*" tags
#       (idempotent) and writes fresh ones at the current OVERLAY_VERSION.
#       Cheap — no Docker, seconds for the whole cache.
#
#   --mode=reconvert
#       Re-run pdf2htmlEX from the original source for every cache entry:
#         - https:// entries: source is the already-cached <hash>/_source/*.pdf
#           (no re-download — signed URLs often can't be refetched anyway).
#         - file:// entries: source is the original path from mappings.tsv,
#           if it still exists. Missing sources are logged and skipped.
#       Slow and requires Docker. Use after an engine/flag change that
#       materially affects pdf2htmlEX output.
#
#   --mode=meta
#       Run pdfinfo on every cache entry's source PDF and write <hash>/meta.json.
#       Uses local `pdfinfo` (brew install poppler) if present, falls back to
#       the pdf2htmlEX Docker image. Idempotent — existing meta.json files are
#       overwritten so bumps to the schema propagate cleanly.
#
# None of the modes mutate mappings.tsv — cache layout is preserved verbatim.
# ============================================================================

set -u

PORT=7435
REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
CACHE_DIR="$HOME/.cache/pdf_viewer"
LOG_FILE="$CACHE_DIR/log"
MAP_FILE="$CACHE_DIR/mappings.tsv"
IMAGE="pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"
OVERLAY_VERSION=1
INJECTOR="$REPO_DIR/scripts/inject-overlay.py"

mkdir -p "$CACHE_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }
say() { printf '%s\n' "$*"; log "$*"; }
die() { printf 'error: %s\n' "$*" >&2; log "FAIL: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") --mode=<inject|reconvert|meta>

  --mode=inject      Re-inject title/favicon/overlay tags into every cached
                     <hash>/*.html. No Docker required.
  --mode=reconvert   Re-run pdf2htmlEX on every cache entry from its source
                     PDF. Requires Docker.
  --mode=meta        Run pdfinfo on every cache entry's source PDF and
                     write <hash>/meta.json. Idempotent.
EOF
}

MODE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode=*)   MODE="${1#--mode=}"; shift ;;
        --mode)     MODE="${2:-}"; shift 2 ;;
        -h|--help)  usage; exit 0 ;;
        *)          usage >&2; die "unknown arg: $1" ;;
    esac
done

case "$MODE" in
    inject|reconvert|meta) ;;
    *) usage >&2; die "--mode is required (inject|reconvert|meta)" ;;
esac

# ----------------------------------------------------------------------------
# Mode: inject
# ----------------------------------------------------------------------------
if [[ "$MODE" == "inject" ]]; then
    updated=0
    skipped=0
    failed=0

    shopt -s nullglob
    for html in "$CACHE_DIR"/*/*.html; do
        # Skip the _assets symlink subtree (shouldn't have *.html but be safe)
        case "$html" in "$CACHE_DIR"/_assets/*) continue ;; esac

        stem=$(basename "$html" .html)
        if python3 "$INJECTOR" "$html" "$stem" "$OVERLAY_VERSION" \
                >>"$LOG_FILE" 2>&1; then
            updated=$((updated + 1))
        else
            log "inject failed: $html"
            failed=$((failed + 1))
        fi
    done
    shopt -u nullglob

    say "upgrade-cache inject: $updated updated, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi

# ----------------------------------------------------------------------------
# Mode: reconvert
# ----------------------------------------------------------------------------
if [[ "$MODE" == "reconvert" ]]; then
    [[ -f "$MAP_FILE" ]] || die "mappings.tsv not found — nothing to reconvert"

    if ! docker info >/dev/null 2>&1; then
        die "Docker daemon not running — start Docker.app"
    fi

    ok=0
    skipped=0
    failed=0

    # Collect entries first so we can report a total before diving in
    total=$(wc -l < "$MAP_FILE" | tr -d ' ')
    say "reconvert: $total cache entries queued"

    idx=0
    while IFS=$'\t' read -r ts source_ref hash html_path; do
        idx=$((idx + 1))
        [[ -n "${hash:-}" ]] || { skipped=$((skipped + 1)); continue; }

        out_dir="$CACHE_DIR/$hash"
        if [[ ! -d "$out_dir" ]]; then
            log "reconvert [$idx/$total] skip (no dir): $hash"
            skipped=$((skipped + 1))
            continue
        fi

        # Resolve mount source + PDF name by source scheme
        if [[ "$source_ref" =~ ^https?:// ]]; then
            pdf_dir="$out_dir/_source"
            existing_pdf=$(ls "$pdf_dir"/*.pdf 2>/dev/null | head -1)
            if [[ -z "$existing_pdf" ]]; then
                log "reconvert [$idx/$total] skip (no cached source PDF): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
            pdf_name=$(basename "$existing_pdf")
        else
            if [[ ! -f "$source_ref" ]]; then
                log "reconvert [$idx/$total] skip (source missing): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
            pdf_dir=$(dirname "$source_ref")
            pdf_name=$(basename "$source_ref")
        fi

        out_name="${pdf_name%.*}.html"
        say "reconvert [$idx/$total]: $source_ref"

        # Purge prior pdf2htmlEX outputs but preserve _source/ (for https) so
        # a failed reconvert doesn't lose the downloaded bytes.
        find "$out_dir" -maxdepth 1 -mindepth 1 ! -name '_source' \
            -exec rm -rf {} + 2>>"$LOG_FILE"

        if docker run --rm --platform linux/amd64 \
                -e LC_ALL=C.UTF-8 -e LANG=C.UTF-8 \
                -v "$pdf_dir":/pdf:ro \
                -v "$out_dir":/out \
                -w /pdf \
                "$IMAGE" \
                --dest-dir /out \
                "$pdf_name" \
                > >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE") \
                2> >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE"); then

            if python3 "$INJECTOR" "$out_dir/$out_name" "${pdf_name%.*}" \
                    "$OVERLAY_VERSION" >>"$LOG_FILE" 2>&1; then
                ok=$((ok + 1))
            else
                log "reconvert [$idx/$total] inject FAILED: $out_dir/$out_name"
                failed=$((failed + 1))
            fi
        else
            log "reconvert [$idx/$total] pdf2htmlEX FAILED: $source_ref"
            failed=$((failed + 1))
        fi
    done < "$MAP_FILE"

    say "upgrade-cache reconvert: $ok ok, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi

# ----------------------------------------------------------------------------
# Mode: meta
# ----------------------------------------------------------------------------
if [[ "$MODE" == "meta" ]]; then
    [[ -f "$MAP_FILE" ]] || die "mappings.tsv not found — nothing to reindex"

    ok=0
    skipped=0
    failed=0
    total=$(wc -l < "$MAP_FILE" | tr -d ' ')
    say "meta: $total cache entries queued"

    idx=0
    while IFS=$'\t' read -r ts source_ref hash html_path; do
        idx=$((idx + 1))
        [[ -n "${hash:-}" ]] || { skipped=$((skipped + 1)); continue; }

        out_dir="$CACHE_DIR/$hash"
        if [[ ! -d "$out_dir" ]]; then
            log "meta [$idx/$total] skip (no dir): $hash"
            skipped=$((skipped + 1))
            continue
        fi

        # Resolve source PDF by scheme.
        if [[ "$source_ref" =~ ^https?:// ]]; then
            pdf_path=$(ls "$out_dir/_source"/*.pdf 2>/dev/null | head -1)
            if [[ -z "$pdf_path" ]]; then
                log "meta [$idx/$total] skip (no cached source PDF): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
        else
            if [[ ! -f "$source_ref" ]]; then
                log "meta [$idx/$total] skip (source missing): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
            pdf_path="$source_ref"
        fi

        if "$REPO_DIR/scripts/extract-pdf-meta.sh" "$pdf_path" "$out_dir/meta.json" \
                >>"$LOG_FILE" 2>&1; then
            ok=$((ok + 1))
            log "meta [$idx/$total] ok: $hash"
        else
            failed=$((failed + 1))
            log "meta [$idx/$total] FAILED: $pdf_path"
        fi
    done < "$MAP_FILE"

    say "upgrade-cache meta: $ok ok, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi
