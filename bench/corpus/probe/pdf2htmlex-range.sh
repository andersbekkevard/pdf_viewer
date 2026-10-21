#!/usr/bin/env bash
# Stand-in for the pipeline's NATIVE_BIN that converts only pages
# $PROBE_FIRST..$PROBE_LAST of the document (see convert.sh).
exec "$PROBE_REAL_BIN" -f "$PROBE_FIRST" -l "$PROBE_LAST" "$@"
