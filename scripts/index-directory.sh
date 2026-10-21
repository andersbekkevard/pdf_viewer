#!/bin/bash

# ============================================================================
# pdf_viewer — bulk directory indexer, one conversion at a time.
#
# Usage: index-directory.sh <folder>
#
# The serial entry point used by raycast/pdf-viewer-index-folder.sh. It is
# index-directory-parallel.sh with a single worker; see that script for the
# contract (content-hash cache, idempotent, metadata and thumbnails).
# ============================================================================

exec "$(cd "$(dirname "$0")" && pwd)/index-directory-parallel.sh" "${1:-}" 1
