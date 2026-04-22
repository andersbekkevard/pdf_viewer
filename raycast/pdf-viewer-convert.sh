#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title PDF viewer: convert
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 📑
# @raycast.description Convert active Comet PDF tab to localhost HTML (pdf_viewer pipeline, served overlay)

# Thin entrypoint — all real logic lives in pdf_viewer/scripts/ so it can be
# edited/tested outside of Raycast's conventions.
#
# Silent mode only shows a HUD at script COMPLETION. A cache-miss conversion
# can take 1-2 minutes, so if we just exec'd into the real script the user
# would see nothing for that entire wait. Instead we fork the real work into
# the background and exit immediately — Raycast renders the wrapper's
# stdout as a HUD toast the instant that happens. The real script is
# on its own from there (macOS notifications cover mid-run progress).

# Preflight: Docker must be running for a cache-miss conversion. Done
# synchronously in the wrapper so the failure surfaces via Raycast's HUD
# (the only reliable visual channel — macOS `osascript display notification`
# requires Script Editor to have notification permission, which many setups
# don't). The socket check is instant and matches how Docker Desktop itself
# signals its state: the socket is created on start, removed on stop.
# The underlying script re-runs `docker info` for defense-in-depth.
if [[ ! -S /var/run/docker.sock ]]; then
    echo "⚠️ Docker not running — start Docker.app"
    exit 1
fi

nohup /Users/andersbekkevard/dev/misc/pdf_viewer/scripts/pdf2html-convert.sh "$@" \
    >>"$HOME/.cache/pdf_viewer/log" 2>&1 &
disown
echo "starting conversion…"
