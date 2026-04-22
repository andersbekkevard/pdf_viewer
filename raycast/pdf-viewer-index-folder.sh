#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title PDF viewer: index folder
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 📑
# @raycast.description Bulk-convert every *.pdf under a folder into the pdf_viewer cache. Idempotent (already-cached docs are skipped). Requires Docker running.
# @raycast.argument1 { "type": "text", "placeholder": "Folder path (absolute or ~/...)" }

# Thin entrypoint — real logic lives in pdf_viewer/scripts/.
#
# Silent mode shows a HUD at completion only; for a folder with N PDFs this
# could be tens of minutes. Fork the real script into the background and
# exit immediately so Raycast shows a HUD the instant it's triggered; the
# real work continues on its own and fires macOS notifications for progress.
#
# ~/.local/bin + homebrew paths are exported here because Raycast doesn't
# inherit them from the user's interactive shell — `fd` lives there.

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Preflight: Docker must be running. Done synchronously in the wrapper so
# the failure surfaces via Raycast's HUD (osascript notifications need Script
# Editor notification permission, which many setups don't grant). Socket is
# created by Docker Desktop on start, removed on stop — instant check. The
# underlying script re-runs `docker info` for defense-in-depth.
if [[ ! -S /var/run/docker.sock ]]; then
    echo "⚠️ Docker not running — start Docker.app"
    exit 1
fi

nohup /Users/andersbekkevard/dev/misc/pdf_viewer/scripts/index-directory.sh "$1" \
    >>"$HOME/.cache/pdf_viewer/log" 2>&1 &
disown
echo "indexing folder…"
