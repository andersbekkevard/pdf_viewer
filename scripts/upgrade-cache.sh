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
#       Build the derived <stem>.light.html variant and page-images/ directory
#       from the canonical <stem>.html, including collapsed page-level text.
#       This never mutates mappings.tsv.
#
# None of the modes mutate mappings.tsv — cache layout is preserved verbatim.
# ============================================================================

set -u

PORT=7435
REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
CACHE_DIR="$HOME/.cache/pdf_viewer"
LOG_FILE="$CACHE_DIR/log"
MAP_FILE="$CACHE_DIR/mappings.tsv"
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
  --mode=light       EXPERIMENTAL/DISABLED by default while quality bugs are
                     open. Requires PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT=1.
                     Builds optional <stem>.light.html files without mutating
                     mappings.tsv.
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
        if uv run "$INJECTOR" "$html" "$stem" \
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

    [[ -x "$NATIVE_BIN" ]] || \
        die "native pdf2htmlEX not installed — run scripts/install-native-pdf2htmlex.sh"

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

        if "$NATIVE_BIN" --data-dir "$NATIVE_DATA_DIR" \
                --poppler-data-dir "$NATIVE_POPPLER_DATA" --dest-dir "$out_dir" \
                "$pdf_dir/$pdf_name" >>"$LOG_FILE" 2>&1; then

            if uv run "$INJECTOR" "$out_dir/$out_name" "${pdf_name%.*}" \
                    >>"$LOG_FILE" 2>&1; then
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
                            || log "reconvert [$idx/$total] light inject FAILED: $out_dir/$light_out_name"
                    else
                        log "reconvert [$idx/$total] light FAILED: $source_ref"
                        rm -f "$out_dir/$light_out_name"
                    fi
                else
                    log "reconvert [$idx/$total] light skipped pending search/selection/resolution fixes"
                fi
                # Conversion provenance — pipeline-owned. The dir was wiped
                # above, so this creates a fresh provenance-only meta.json;
                # --mode=meta (or the next live convert) will merge pdfinfo
                # fields in alongside it. Versions parsed from the binary so
                # this stays accurate across toolchain upgrades.
                OVERLAY_HASH="$(uv run "$INJECTOR" --print-version)"
                python3 "$REPO_DIR/scripts/write-provenance.py" "$out_dir/meta.json" \
                    --converter native-arm64 --bin "$NATIVE_BIN" \
                    --overlay-version "$OVERLAY_HASH" \
                    >>"$LOG_FILE" 2>&1 \
                    || log "reconvert [$idx/$total] provenance write FAILED: $out_dir"
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
# Mode: light
# ----------------------------------------------------------------------------
if [[ "$MODE" == "light" ]]; then
    if [[ "$LIGHT_VARIANTS_ENABLED" != "1" ]]; then
        die "--mode=light is disabled while light HTML quality bugs are open; set PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT=1 to override for targeted testing"
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
        light_html="$out_dir/${stem}.light.html"
        say "light [$idx/$total]: $hash"

        if uv run "$EXTERNALIZER" \
                "$html" "$light_html" \
                --image-dir "$out_dir/page-images" \
                --url-prefix "/$hash/page-images/" \
                --eager 2 \
                --clean >>"$LOG_FILE" 2>&1; then
            if uv run "$INJECTOR" "$light_html" "$stem" \
                    >>"$LOG_FILE" 2>&1; then
                ok=$((ok + 1))
            else
                log "light [$idx/$total] inject FAILED: $light_html"
                failed=$((failed + 1))
            fi
        else
            log "light [$idx/$total] FAILED: $html"
            rm -f "$light_html"
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

        # Resolve source PDF by scheme (same rules as meta mode).
        if [[ "$source_ref" =~ ^https?:// ]]; then
            pdf_path=$(ls "$out_dir/_source"/*.pdf 2>/dev/null | head -1)
            if [[ -z "$pdf_path" ]]; then
                log "thumbs [$idx/$total] skip (no cached source PDF): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
        else
            if [[ ! -f "$source_ref" ]]; then
                log "thumbs [$idx/$total] skip (source missing): $source_ref"
                skipped=$((skipped + 1))
                continue
            fi
            pdf_path="$source_ref"
        fi

        if "$REPO_DIR/scripts/extract-pdf-thumbs.sh" "$pdf_path" "$out_dir/thumbs" \
                >>"$LOG_FILE" 2>&1; then
            ok=$((ok + 1))
            log "thumbs [$idx/$total] ok: $hash"
        else
            failed=$((failed + 1))
            log "thumbs [$idx/$total] FAILED: $pdf_path"
            # Clean up partial output so the next run retries rather than
            # honoring the "already present" skip.
            rm -rf "$out_dir/thumbs"
        fi
    done < "$MAP_FILE"

    say "upgrade-cache thumbs: $ok ok, $skipped skipped, $failed failed"
    exit $(( failed > 0 ? 1 : 0 ))
fi
