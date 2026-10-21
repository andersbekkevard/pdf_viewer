#!/bin/bash

# ============================================================================
# pdf_viewer — upgrade-cache.sh
#
# Walks ~/.cache/pdf_viewer/ and upgrades cached entries after overlay or
# engine changes. Modes are picked explicitly:
#
#   --mode=inject
#       Re-run the title/favicon/overlay-tag injector (inject-overlay.py) on
#       every cached <hash>/<stem>.html. Strips prior id="pdf2html-*" tags
#       (idempotent) and writes fresh ones at the current overlay content hash
#       (?v=<hash>, derived by the injector from assets/overlay.{js,css}).
#       Cheap — no Docker, seconds for the whole cache.
#
#   --mode=reconvert
#       Re-run pdf2htmlEX from the original source for every cache entry:
#         - https:// entries: source is the already-cached <hash>/_source/*.pdf
#           (no re-download — signed URLs often can't be refetched anyway).
#         - file:// entries: source is the original path from mappings.tsv,
#           if it still exists. Missing sources are logged and skipped.
#       Slow; requires the native pdf2htmlEX binary. Use after an engine/flag
#       change that materially affects pdf2htmlEX output.
#
#   --mode=meta
#       Run pdfinfo on every cache entry's source PDF and write <hash>/meta.json.
#       Uses local `pdfinfo` (brew install poppler). Idempotent — existing
#       meta.json files are overwritten so bumps to the schema propagate
#       cleanly.
#
#   --mode=thumbs
#       Run pdftocairo on every cache entry's source PDF and write per-page
#       thumbnail JPEGs into <hash>/thumbs/. Skips entries that already have
#       a thumbs/ directory (idempotent-ish); rm -rf it first to force rebuild.
#
#   --mode=light
#       Build the derived <stem>.light.html variant and
#       page-images/ directory from canonical HTML.
#       This never mutates mappings.tsv.
#
# None of the modes mutate mappings.tsv — cache layout is preserved verbatim.
# ============================================================================

set -u

# shellcheck source=lib/pipeline.sh
source "$(cd "$(dirname "$0")" && pwd)/lib/pipeline.sh"

say() { printf '%s\n' "$*"; log "$*"; }
die() { printf 'error: %s\n' "$*" >&2; log "FAIL: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") --mode=<inject|reconvert|meta|thumbs|light>

  --mode=inject      Re-inject title/favicon/overlay tags into every cached
                     <hash>/*.html. No Docker required.
  --mode=reconvert   Re-run pdf2htmlEX on every cache entry from its source
                     PDF. Requires the native pdf2htmlEX binary.
  --mode=meta        Run pdfinfo on every cache entry's source PDF and
                     write <hash>/meta.json. Idempotent.
  --mode=thumbs      Run pdftocairo on every cache entry's source PDF and
                     write thumbnail JPEGs into <hash>/thumbs/. Skips
                     entries that already have thumbs/.
  --mode=light       Build <stem>.light.html files without mutating
                     mappings.tsv. Disabled by PDF_VIEWER_ENABLE_LIGHT=0.
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
    inject|reconvert|meta|thumbs|light) ;;
    *) usage >&2; die "--mode is required (inject|reconvert|meta|thumbs|light)" ;;
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
        stem="${stem%.light}"
        if inject_overlay "$html" "$stem"; then
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

    native_ready || die "native pdf2htmlEX not installed — run scripts/install-native-pdf2htmlex.sh"

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

        pdf_path=$(entry_source_pdf "$source_ref" "$out_dir")
        if [[ -z "$pdf_path" ]]; then
            log "reconvert [$idx/$total] skip (source PDF missing): $source_ref"
            skipped=$((skipped + 1))
            continue
        fi
        pdf_name=$(basename "$pdf_path")
        out_name="${pdf_name%.*}.html"
        say "reconvert [$idx/$total]: $source_ref"

        # Purge prior pdf2htmlEX outputs but preserve _source/ (for https) so
        # a failed reconvert doesn't lose the downloaded bytes.
        find "$out_dir" -maxdepth 1 -mindepth 1 ! -name '_source' \
            -exec rm -rf {} + 2>>"$LOG_FILE"

        if ! native_convert "$pdf_path" "$out_dir"; then
            log "reconvert [$idx/$total] pdf2htmlEX FAILED: $source_ref"
            failed=$((failed + 1))
        elif ! build_entry "$out_dir" "$out_name" "$hash" "${pdf_name%.*}"; then
            log "reconvert [$idx/$total] inject FAILED: $out_dir/$out_name"
            failed=$((failed + 1))
        else
            # The dir was wiped above, so rebuild the extras too.
            write_provenance "$out_dir" || log "reconvert [$idx/$total] provenance write FAILED: $out_dir"
            ensure_meta "$pdf_path" "$out_dir" || log "reconvert [$idx/$total] meta FAILED: $out_dir"
            ensure_thumbs "$pdf_path" "$out_dir" || log "reconvert [$idx/$total] thumbs FAILED: $out_dir"
            ok=$((ok + 1))
        fi
    done < "$MAP_FILE"

    say "upgrade-cache reconvert: $ok ok, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi

# ----------------------------------------------------------------------------
# Mode: light
# ----------------------------------------------------------------------------
if [[ "$MODE" == "light" ]]; then
    if [[ "$LIGHT_VARIANTS_ENABLED" != "1" ]]; then
        die "--mode=light is disabled by PDF_VIEWER_ENABLE_LIGHT=0"
    fi
    [[ -f "$MAP_FILE" ]] || die "mappings.tsv not found — nothing to externalize"

    ok=0
    skipped=0
    failed=0
    total=$(wc -l < "$MAP_FILE" | tr -d ' ')
    say "light: $total cache entries queued"

    idx=0
    while IFS=$'\t' read -r ts source_ref hash html_path; do
        idx=$((idx + 1))
        [[ -n "${hash:-}" ]] || { skipped=$((skipped + 1)); continue; }

        out_dir="$CACHE_DIR/$hash"
        if [[ ! -d "$out_dir" ]]; then
            log "light [$idx/$total] skip (no dir): $hash"
            skipped=$((skipped + 1))
            continue
        fi

        html="$html_path"
        if [[ -z "$html" || ! -f "$html" || "$html" == *.light.html ]]; then
            html=$(find "$out_dir" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' | sort | head -1)
        fi
        if [[ -z "$html" || ! -f "$html" ]]; then
            log "light [$idx/$total] skip (no canonical html): $hash"
            skipped=$((skipped + 1))
            continue
        fi

        stem=$(basename "$html" .html)
        say "light [$idx/$total]: $hash"

        if build_light "$out_dir" "$(basename "$html")" "$hash" "$stem" force; then
            ok=$((ok + 1))
        else
            log "light [$idx/$total] FAILED: $html"
            failed=$((failed + 1))
        fi
    done < "$MAP_FILE"

    say "upgrade-cache light: $ok ok, $skipped skipped, $failed failed"
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

        pdf_path=$(entry_source_pdf "$source_ref" "$out_dir")
        if [[ -z "$pdf_path" ]]; then
            log "meta [$idx/$total] skip (source PDF missing): $source_ref"
            skipped=$((skipped + 1))
            continue
        fi

        if ensure_meta "$pdf_path" "$out_dir" force; then
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

# ----------------------------------------------------------------------------
# Mode: thumbs
# ----------------------------------------------------------------------------
if [[ "$MODE" == "thumbs" ]]; then
    [[ -f "$MAP_FILE" ]] || die "mappings.tsv not found — nothing to thumb"

    ok=0
    skipped=0
    failed=0
    total=$(wc -l < "$MAP_FILE" | tr -d ' ')
    say "thumbs: $total cache entries queued"

    idx=0
    while IFS=$'\t' read -r ts source_ref hash html_path; do
        idx=$((idx + 1))
        [[ -n "${hash:-}" ]] || { skipped=$((skipped + 1)); continue; }

        out_dir="$CACHE_DIR/$hash"
        if [[ ! -d "$out_dir" ]]; then
            log "thumbs [$idx/$total] skip (no dir): $hash"
            skipped=$((skipped + 1))
            continue
        fi
        if [[ -d "$out_dir/thumbs" ]]; then
            log "thumbs [$idx/$total] skip (already present): $hash"
            skipped=$((skipped + 1))
            continue
        fi

        pdf_path=$(entry_source_pdf "$source_ref" "$out_dir")
        if [[ -z "$pdf_path" ]]; then
            log "thumbs [$idx/$total] skip (source PDF missing): $source_ref"
            skipped=$((skipped + 1))
            continue
        fi

        # ensure_thumbs removes partial output on failure, so the next run
        # retries rather than honoring the "already present" skip.
        if ensure_thumbs "$pdf_path" "$out_dir"; then
            ok=$((ok + 1))
            log "thumbs [$idx/$total] ok: $hash"
        else
            failed=$((failed + 1))
            log "thumbs [$idx/$total] FAILED: $pdf_path"
        fi
    done < "$MAP_FILE"

    say "upgrade-cache thumbs: $ok ok, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi
