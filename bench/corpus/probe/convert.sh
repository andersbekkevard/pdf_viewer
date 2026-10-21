#!/usr/bin/env bash
# Probe conversion steps, run through the repo's own pipeline functions.
#
#   convert.sh convert <pdf> <out_dir> [<first> <last>]
#       native_convert from scripts/lib/pipeline.sh. With a page range, the
#       pipeline's NATIVE_BIN is pointed at pdf2htmlex-range.sh, which adds
#       -f/-l and execs the real binary; the pipeline itself is unchanged.
#   convert.sh light <out_dir> <canonical_name> <hash> <title>
#       inject_overlay on the canonical HTML, then build_light: the same two
#       steps as the pipeline's build_entry, called separately because
#       build_entry ignores a light-build failure and the probe records it.
#
# The caller must set PDF_VIEWER_CACHE_DIR to a scratch cache; this script
# refuses to run against the real cache. Exit status is the step's status.
set -u
PROBE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$PROBE_DIR/../../.." && pwd)"
if [[ -z "${PDF_VIEWER_CACHE_DIR:-}" || "$PDF_VIEWER_CACHE_DIR" == "$HOME/.cache/pdf_viewer"* ]]; then
    echo "convert.sh: PDF_VIEWER_CACHE_DIR must point at a scratch cache" >&2
    exit 64
fi
# shellcheck source=../../../scripts/lib/pipeline.sh
source "$REPO/scripts/lib/pipeline.sh"
ensure_asset_link || exit 65

step="$1"; shift
case "$step" in
    convert)
        pdf="$1" out_dir="$2"
        mkdir -p "$out_dir"
        if [[ $# -ge 4 ]]; then
            export PROBE_REAL_BIN="$NATIVE_BIN" PROBE_FIRST="$3" PROBE_LAST="$4"
            NATIVE_BIN="$PROBE_DIR/pdf2htmlex-range.sh"
        fi
        native_convert "$pdf" "$out_dir"
        ;;
    light)
        out_dir="$1" name="$2" hash="$3" title="$4"
        inject_overlay "$out_dir/$name" "$title" || exit 70
        build_light "$out_dir" "$name" "$hash" "$title"
        ;;
    *)
        echo "convert.sh: unknown step $step" >&2
        exit 64
        ;;
esac
