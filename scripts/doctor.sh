#!/bin/bash

# ============================================================================
# pdf_viewer — doctor.sh
#
# One-command, READ-ONLY diagnosis of the full pdf_viewer chain. Walks every
# link the day-to-day workflow depends on and prints one PASS / FAIL / WARN
# line per check, each with a one-line fix hint. Exits non-zero iff a
# *required* check fails; WARN-only checks (optional features) never fail.
#
# The chain (parent epic: pdfv-6el):
#   browser extension → daemon (:7435) → cache + _assets symlink →
#   native pdf2htmlEX binary + Homebrew dylibs + poppler data.
#
# WHY: most historical debugging sessions (stale overlay assets, daemon down,
# missing toolchain, broken symlink) reduce to checking one link in this
# chain. That knowledge lived in heads and docs; this puts it in a tool.
#
# This script NEVER mutates state: no Docker, no network beyond localhost
# probes against the already-running daemon, no file writes. Safe to run
# anytime.
#
# Usage:
#   scripts/doctor.sh
#
# Env:
#   PDF_VIEWER_PORT   daemon port to probe (default: 7435). Override is for
#                     testability — pointing at a dead port exercises the
#                     daemon-down failure path without stopping the real one.
#
# Exit status:
#   0   all required checks PASS (WARN allowed)
#   1   one or more required checks FAILed
# ============================================================================

set -uo pipefail

PORT="${PDF_VIEWER_PORT:-7435}"
LAUNCHD_LABEL="com.anders.pdf_viewer"

CACHE_DIR="$HOME/.cache/pdf_viewer"
ASSET_LINK="$CACHE_DIR/_assets"
MAPPINGS="$CACHE_DIR/mappings.tsv"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ASSETS="$REPO_DIR/assets"

NATIVE_BIN="$HOME/.local/opt/pdf2htmlEX/bin/pdf2htmlEX"
POPPLER_DATA_DIR="/opt/homebrew/share/poppler"

# --- output helpers ----------------------------------------------------------

# ANSI only when stdout is a TTY (keeps log/pipe output clean).
if [ -t 1 ]; then
    C_PASS=$'\033[32m'; C_FAIL=$'\033[31m'; C_WARN=$'\033[33m'
    C_INFO=$'\033[36m'; C_OFF=$'\033[0m'
else
    C_PASS=''; C_FAIL=''; C_WARN=''; C_INFO=''; C_OFF=''
fi

FAILED=0

pass() { printf '%sPASS%s %s\n'  "$C_PASS" "$C_OFF" "$1"; }
warn() { printf '%sWARN%s %s\n   ↳ %s\n' "$C_WARN" "$C_OFF" "$1" "$2"; }
info() { printf '%sINFO%s %s\n'  "$C_INFO" "$C_OFF" "$1"; }
fail() {
    printf '%sFAIL%s %s\n   ↳ %s\n' "$C_FAIL" "$C_OFF" "$1" "$2"
    FAILED=1
}

# ============================================================================
# 1. Daemon: /healthz on :PORT
# ============================================================================

health="$(curl -fsS -m 3 "http://127.0.0.1:${PORT}/healthz" 2>/dev/null || true)"
case "$health" in
    *'"status":"ok"'*)
        entries="$(printf '%s' "$health" | sed -n 's/.*"entries":\([0-9]*\).*/\1/p')"
        pass "daemon /healthz on :${PORT} (entries=${entries:-?})"
        ;;
    *)
        fail "daemon /healthz on :${PORT} not responding" \
             "start it: uv run --directory $REPO_DIR/daemon main.py  (or launchctl kickstart -k gui/\$UID/${LAUNCHD_LABEL})"
        ;;
esac

# ============================================================================
# 2. launchd job loaded
# ============================================================================

if launchctl print "gui/$(id -u)/${LAUNCHD_LABEL}" >/dev/null 2>&1 \
   || launchctl list 2>/dev/null | grep -q "${LAUNCHD_LABEL}"; then
    pass "launchd job ${LAUNCHD_LABEL} loaded"
else
    fail "launchd job ${LAUNCHD_LABEL} not loaded" \
         "load it: launchctl bootstrap gui/\$UID $REPO_DIR/launchd/${LAUNCHD_LABEL}.plist"
fi

# ============================================================================
# 3. _assets symlink resolves into the repo's assets/
# ============================================================================

if [ ! -L "$ASSET_LINK" ]; then
    fail "_assets is not a symlink ($ASSET_LINK)" \
         "ln -s $REPO_ASSETS $ASSET_LINK"
else
    resolved="$( (cd "$ASSET_LINK" && pwd -P) 2>/dev/null || true)"
    repo_real="$( (cd "$REPO_ASSETS" && pwd -P) 2>/dev/null || true)"
    if [ -n "$resolved" ] && [ "$resolved" = "$repo_real" ]; then
        pass "_assets symlink → $resolved"
    else
        fail "_assets symlink does not resolve into repo assets (→ ${resolved:-<broken>})" \
             "rm $ASSET_LINK && ln -s $REPO_ASSETS $ASSET_LINK"
    fi
fi

# ============================================================================
# 4. Native pdf2htmlEX binary exists + --version sane (report poppler)
# ============================================================================

if [ ! -x "$NATIVE_BIN" ]; then
    fail "native pdf2htmlEX binary missing: $NATIVE_BIN" \
         "build + install it: scripts/install-native-pdf2htmlex.sh"
else
    ver_out="$("$NATIVE_BIN" --version 2>&1 || true)"
    ver_line="$(printf '%s\n' "$ver_out" | head -1)"
    case "$ver_line" in
        *"pdf2htmlEX version"*)
            poppler_ver="$(printf '%s\n' "$ver_out" | sed -n 's/.*poppler[[:space:]]*\([0-9.]*\).*/\1/p' | head -1)"
            pass "native pdf2htmlEX binary: ${ver_line} (poppler ${poppler_ver:-unknown})"
            ;;
        *)
            fail "pdf2htmlEX --version unexpected: ${ver_line:-<empty>}" \
                 "reinstall: scripts/install-native-pdf2htmlex.sh"
            ;;
    esac
fi

# ============================================================================
# 5. Every /opt/homebrew dylib in otool -L of the binary resolves
# ============================================================================

if [ ! -x "$NATIVE_BIN" ]; then
    warn "dylib check skipped (binary missing)" "see binary check above"
elif ! command -v otool >/dev/null 2>&1; then
    warn "otool not found; cannot check linked dylibs" "install Xcode command line tools: xcode-select --install"
else
    missing_dylibs=""
    while IFS= read -r lib; do
        case "$lib" in
            /opt/homebrew/*)
                [ -e "$lib" ] || missing_dylibs="${missing_dylibs}${lib}\n"
                ;;
        esac
    done < <(otool -L "$NATIVE_BIN" 2>/dev/null | awk 'NR>1 {print $1}')
    if [ -z "$missing_dylibs" ]; then
        pass "all /opt/homebrew dylibs linked by the binary resolve"
    else
        fail "linked Homebrew dylib(s) missing:\n$(printf '%b' "$missing_dylibs" | sed 's/^/        /')" \
             "brew install the owning formula(e) (e.g. cairo glib freetype poppler)"
    fi
fi

# ============================================================================
# 6. poppler data dir (WARN only — needed for CJK/CID PDFs)
# ============================================================================

if [ -d "$POPPLER_DATA_DIR" ]; then
    pass "poppler data dir present: $POPPLER_DATA_DIR"
else
    warn "poppler data dir missing: $POPPLER_DATA_DIR" \
         "brew install poppler — CJK/CID-encoded PDFs may render wrong without it"
fi

# ============================================================================
# 7. pdftocairo / pdfinfo on PATH (WARN only — optional thumbs/meta)
# ============================================================================

for tool in pdftocairo pdfinfo; do
    if command -v "$tool" >/dev/null 2>&1; then
        pass "$tool on PATH ($(command -v "$tool"))"
    else
        warn "$tool not on PATH" \
             "brew install poppler — optional thumbnail/metadata extraction will be skipped"
    fi
done

# ============================================================================
# 8. mappings.tsv exists + writable
# ============================================================================

if [ ! -f "$MAPPINGS" ]; then
    fail "mappings.tsv missing: $MAPPINGS" \
         "convert any PDF to seed it, or check CACHE_DIR=$CACHE_DIR exists"
elif [ ! -w "$MAPPINGS" ]; then
    fail "mappings.tsv not writable: $MAPPINGS" \
         "chmod u+w $MAPPINGS"
else
    pass "mappings.tsv exists + writable ($(wc -l < "$MAPPINGS" | tr -d ' ') rows)"
fi

# ============================================================================
# 9. Cache dir writable
# ============================================================================

if [ -d "$CACHE_DIR" ] && [ -w "$CACHE_DIR" ]; then
    pass "cache dir writable: $CACHE_DIR"
else
    fail "cache dir missing or not writable: $CACHE_DIR" \
         "mkdir -p $CACHE_DIR && chmod u+w $CACHE_DIR"
fi

# ============================================================================
# 10. /_assets/overlay.js returns 200 through the daemon
# ============================================================================

code="$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://127.0.0.1:${PORT}/_assets/overlay.js" 2>/dev/null || true)"
if [ "$code" = "200" ]; then
    pass "/_assets/overlay.js → 200 through the daemon"
else
    fail "/_assets/overlay.js → ${code:-no-response} through the daemon" \
         "daemon down or _assets symlink broken — see checks above"
fi

# ============================================================================
# 11. Extension — manual verification instruction (no cheap automated probe)
# ============================================================================

info "Extension (Comet MV3): no read-only automated probe exists. Verify manually —"
info "  open any *.pdf URL in Comet; it should redirect to localhost:${PORT} and render the overlay."
info "  If it stays on the native viewer, check extension/ is loaded + its declarativeNetRequest rules are enabled."

# ============================================================================

echo
if [ "$FAILED" -ne 0 ]; then
    printf '%sdoctor: FAIL%s — one or more required checks failed (see ↳ hints above)\n' "$C_FAIL" "$C_OFF"
    exit 1
fi
printf '%sdoctor: OK%s — all required checks passed\n' "$C_PASS" "$C_OFF"
exit 0
