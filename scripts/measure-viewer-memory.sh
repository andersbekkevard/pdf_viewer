#!/usr/bin/env bash
# Run the same-journey renderer physical-footprint benchmark without adding deps.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HARNESS="$REPO_DIR/scripts/measure-viewer-memory.cjs"

if ! curl -fsS http://127.0.0.1:7435/healthz >/dev/null; then
    echo "measure-viewer-memory.sh: daemon unreachable on :7435 (it must already be running)" >&2
    exit 2
fi

PW_NODE_PATH="$HOME/.npm/_npx/705bc6b22212b352/node_modules"
if ! NODE_PATH="$PW_NODE_PATH" node -e "require.resolve('playwright')" >/dev/null 2>&1; then
    FOUND=$(find "$HOME/.npm/_npx" "$HOME/Library/Caches" -maxdepth 6 \
        -type d -name playwright -path '*/node_modules/playwright' 2>/dev/null | head -1)
    if [[ -z "$FOUND" ]]; then
        echo "measure-viewer-memory.sh: no local Playwright found; do not install it for this check" >&2
        exit 2
    fi
    PW_NODE_PATH="$(dirname "$FOUND")"
fi

exec env NODE_PATH="$PW_NODE_PATH" node "$HARNESS" "$@"
