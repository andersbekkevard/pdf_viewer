# shellcheck shell=bash
# ============================================================================
# pdf_viewer conversion pipeline — sourced, never executed.
#
# One definition of the cache layout, the toolchain paths and the steps that
# turn a source PDF into a cache entry. Sourced by pdf2html-convert.sh (one
# browser tab), index-directory-parallel.sh (bulk) and upgrade-cache.sh
# (rebuilds), so a change to how entries are built happens once.
#
# Runs under macOS system bash 3.2, so no bash 4 features (the portability
# tests in scripts/tests/ enforce this).
# Every step logs to $LOG_FILE and returns a status; the caller decides what
# is fatal and how to tell the user (Raycast notification, stdout, summary).
# ============================================================================

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$PIPELINE_DIR/../.." && pwd)"
ASSET_SRC="$REPO_DIR/assets"
# PDF_VIEWER_CACHE_DIR points a run at a scratch cache (tests); the daemon
# always serves ~/.cache/pdf_viewer.
CACHE_DIR="${PDF_VIEWER_CACHE_DIR:-$HOME/.cache/pdf_viewer}"
LOG_FILE="$CACHE_DIR/log"
MAP_FILE="$CACHE_DIR/mappings.tsv"
MAP_LOCK="$CACHE_DIR/.maplock"
ASSET_LINK="$CACHE_DIR/_assets"
# Native arm64 pdf2htmlEX (ADR 0011), installed by
# scripts/install-native-pdf2htmlex.sh. --data-dir is passed explicitly on
# every invocation; the binary's baked default lookup is fragile.
NATIVE_BIN="$HOME/.local/opt/pdf2htmlEX/bin/pdf2htmlEX"
NATIVE_DATA_DIR="$HOME/.local/opt/pdf2htmlEX/share/pdf2htmlEX"
# The baked poppler-data default is a version-pinned Cellar path that breaks
# on brew upgrade; pass the stable symlink explicitly (needed for CJK/CID).
NATIVE_POPPLER_DATA="/opt/homebrew/share/poppler"
INJECTOR="$REPO_DIR/scripts/inject-overlay.py"
EXTERNALIZER="$REPO_DIR/scripts/externalize-page-images.py"
RUNTIME_PREPARER="$REPO_DIR/scripts/prepare-light-runtime.py"
# Light HTML (ADR 0010) is on by default; PDF_VIEWER_ENABLE_LIGHT=0 keeps only
# the canonical artifact. The legacy flag name remains compatible.
LIGHT_VARIANTS_ENABLED="${PDF_VIEWER_ENABLE_LIGHT:-${PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT:-1}}"

mkdir -p "$CACHE_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

# The daemon serves /_assets/* through this symlink into the repo.
ensure_asset_link() {
    [[ -L "$ASSET_LINK" ]] && return 0
    rm -rf "$ASSET_LINK" 2>/dev/null
    ln -s "$ASSET_SRC" "$ASSET_LINK"
}

native_ready() { [[ -x "$NATIVE_BIN" ]]; }

# First 16 hex chars of the file's SHA-256: the cache key for local PDFs.
content_hash() { shasum -a 256 "$1" | awk '{print $1}' | head -c 16; }

# The canonical (non-light) HTML in an entry, or nothing.
canonical_html() {
    find "$1" -maxdepth 1 -type f -name '*.html' ! -name '*.light.html' 2>/dev/null | sort | head -1
}

# The source PDF for a mappings.tsv row: the cached download for URLs, the
# original path for local files. Prints nothing when it is gone.
entry_source_pdf() {
    local source_ref="$1" out_dir="$2"
    if [[ "$source_ref" =~ ^https?:// ]]; then
        ls "$out_dir/_source"/*.pdf 2>/dev/null | head -1
    elif [[ -f "$source_ref" ]]; then
        printf '%s\n' "$source_ref"
    fi
}

# native_convert <pdf> <out_dir> — run pdf2htmlEX into out_dir. pdf2htmlEX
# redraws its Preprocessing/Working progress with carriage returns, which
# lands in the log as one unreadable line; normalize to newlines and drop the
# ticks while real warnings (ToUnicode, Fontconfig, locale) still reach the
# log. PIPESTATUS keeps the binary's status, not the filter's.
native_convert() {
    "$NATIVE_BIN" --data-dir "$NATIVE_DATA_DIR" \
        --poppler-data-dir "$NATIVE_POPPLER_DATA" --dest-dir "$2" \
        "$1" 2>&1 \
        | tr '\r' '\n' | grep -vE '^(Preprocessing|Working): [0-9]+/[0-9]+$' \
        >>"$LOG_FILE" 2>&1
    return "${PIPESTATUS[0]}"
}

# inject_overlay <html> <title> — title, favicon and overlay tags. Idempotent.
inject_overlay() {
    uv run "$INJECTOR" "$1" "$2" >>"$LOG_FILE" 2>&1
}

# build_light <out_dir> <canonical_name> <hash> <title> [force] — derive the
# light HTML and page images when missing, older than the canonical HTML, or
# forced, then inject it. A failed build removes the partial light file so the
# daemon serves canonical. Returns non-zero only on failure.
build_light() {
    local out_dir="$1" out_name="$2" hash="$3" title="$4" force="${5:-}"
    local light_name="${out_name%.html}.light.html"
    if [[ "$LIGHT_VARIANTS_ENABLED" != "1" ]]; then
        log "light variant disabled by PDF_VIEWER_ENABLE_LIGHT=0: $out_dir/$out_name"
        return 0
    fi
    if [[ -n "$force" || ! -f "$out_dir/$light_name" || "$out_dir/$out_name" -nt "$out_dir/$light_name" ]]; then
        log "light variant start: $out_dir/$light_name"
        if ! uv run "$EXTERNALIZER" \
                "$out_dir/$out_name" "$out_dir/$light_name" \
                --image-dir "$out_dir/page-images" \
                --url-prefix "/$hash/page-images/" \
                --eager 2 \
                --text-layer=paint-safe \
                --clean >>"$LOG_FILE" 2>&1; then
            log "light variant failed for $out_name; canonical stays"
            rm -f "$out_dir/$light_name"
            return 1
        fi
        if ! uv run "$RUNTIME_PREPARER" "$out_dir/$light_name" \
                --font-dir "$out_dir/page-fonts" \
                --font-url-prefix "/$hash/page-fonts/" >>"$LOG_FILE" 2>&1; then
            log "light runtime preparation failed for $out_name; canonical stays"
            rm -f "$out_dir/$light_name"
            return 1
        fi
    fi
    inject_overlay "$out_dir/$light_name" "$title" || { log "light inject failed: $out_dir/$light_name"; return 1; }
}

# build_entry <out_dir> <canonical_name> <hash> <title> — the HTML artifacts
# for a converted entry: inject the canonical file (fatal on failure), then
# the light variant (non-fatal: canonical still serves).
build_entry() {
    inject_overlay "$1/$2" "$4" || { log "inject failed: $1/$2"; return 1; }
    build_light "$1" "$2" "$3" "$4" || true
}

# write_provenance <out_dir> — converter and overlay versions into meta.json.
# Only after a real conversion; a cache hit keeps its original provenance.
write_provenance() {
    [[ -n "${PIPELINE_OVERLAY_VERSION:-}" ]] \
        || PIPELINE_OVERLAY_VERSION="$(uv run "$INJECTOR" --print-version)"
    python3 "$REPO_DIR/scripts/write-provenance.py" "$1/meta.json" \
        --converter native-arm64 --bin "$NATIVE_BIN" \
        --overlay-version "$PIPELINE_OVERLAY_VERSION" \
        >>"$LOG_FILE" 2>&1
}

# meta.json can exist with provenance only; pdfinfo keys mean it is complete.
has_pdfinfo_meta() {
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if any(k in d for k in ('pages','title','author','file_size')) else 1)" \
        "$1/meta.json" 2>/dev/null
}

# ensure_meta <pdf> <out_dir> [force] — pdfinfo fields into meta.json.
ensure_meta() {
    [[ -z "${3:-}" ]] && has_pdfinfo_meta "$2" && return 0
    "$REPO_DIR/scripts/extract-pdf-meta.sh" "$1" "$2/meta.json" >>"$LOG_FILE" 2>&1
}

# ensure_thumbs <pdf> <out_dir> — per-page thumbnails for the Pages tab. A
# failed run removes its partial output so the next run retries instead of
# treating the directory as done.
ensure_thumbs() {
    [[ -d "$2/thumbs" ]] && return 0
    if ! "$REPO_DIR/scripts/extract-pdf-thumbs.sh" "$1" "$2/thumbs" >>"$LOG_FILE" 2>&1; then
        rm -rf "$2/thumbs"
        return 1
    fi
}

# upsert_mapping <source_ref> <hash> <canonical_html> — replace the row for
# <hash> in mappings.tsv. Serialized by an mkdir lock so concurrent workers
# and conversions never lose each other's rows; the critical section is a
# few milliseconds, and a lock older than a minute is from a killed run.
upsert_mapping() {
    local source_ref="$1" hash="$2" html="$3" waited=0
    while ! mkdir "$MAP_LOCK" 2>/dev/null; do
        if [[ -n "$(find "$MAP_LOCK" -maxdepth 0 -mmin +1 2>/dev/null)" ]]; then
            rmdir "$MAP_LOCK" 2>/dev/null
            continue
        fi
        sleep 0.02
        waited=$((waited + 1))
        [[ $waited -gt 3000 ]] && { log "mapping lock timeout: $hash"; return 1; }
    done
    {
        [[ -f "$MAP_FILE" ]] && awk -F'\t' -v h="$hash" '$3 != h' "$MAP_FILE"
        printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$source_ref" "$hash" "$html"
    } > "$MAP_FILE.tmp.$$" && mv "$MAP_FILE.tmp.$$" "$MAP_FILE"
    local rc=$?
    rmdir "$MAP_LOCK" 2>/dev/null
    return $rc
}
