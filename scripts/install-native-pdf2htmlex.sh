#!/bin/bash

# ============================================================================
# pdf_viewer — install-native-pdf2htmlex.sh
#
# Installs a locally-built native macOS arm64 pdf2htmlEX (0.18.8.rc2,
# poppler 24.06.1, fontforge 20230101) from the v2 build tree into a
# stable, relocation-safe prefix at ~/.local/opt/pdf2htmlEX/.
#
# WHY: the built binary bakes its default data-dir into the build tree
# (native/build/install/share/pdf2htmlEX). That path is fragile — deleting
# or moving the build tree breaks the binary. This installer copies the
# binary + share data into a stable prefix and the daemon/scripts then
# always pass --data-dir explicitly, so the baked-in default is irrelevant.
#
# This script COPIES ONLY. It never rebuilds, never touches Docker, and
# never hits the network. If the build artifacts are missing, it points
# you at native/build.sh and exits.
#
# Runtime deps: the binary links several Homebrew dylibs (cairo, glib,
# freetype, …) via /opt/homebrew/opt/* symlinks, plus poppler's runtime
# data dir (/opt/homebrew/share/poppler). Those are runtime requirements,
# not bundled. The installer WARNS (does not fail) if any linked dylib or
# the poppler data dir is missing.
#
# Usage:
#   scripts/install-native-pdf2htmlex.sh
#
# Env:
#   PDF2HTMLEX_BUILD_TREE   override the build tree root
#                           (default: ~/dev/external/pdf2htmlEX_v2)
#
# Working invocation pattern (what callers should use after install):
#   ~/.local/opt/pdf2htmlEX/bin/pdf2htmlEX \
#     --data-dir ~/.local/opt/pdf2htmlEX/share/pdf2htmlEX \
#     --poppler-data-dir /opt/homebrew/share/poppler \
#     --dest-dir <out> <input.pdf>
#
#   --data-dir is REQUIRED from any cwd (the baked default points into the
#   build tree). --poppler-data-dir is belt-and-suspenders: the binary's
#   baked poppler default is a version-pinned Homebrew Cellar path that
#   breaks on poppler upgrades; the /opt/homebrew/share/poppler symlink is
#   stable and is needed for CJK / CID-encoded PDFs.
# ============================================================================

set -euo pipefail

BUILD_TREE="${PDF2HTMLEX_BUILD_TREE:-$HOME/dev/external/pdf2htmlEX_v2}"
INSTALL_TREE="$BUILD_TREE/native/build/install"
NATIVE_BIN_FALLBACK="$BUILD_TREE/native/pdf2htmlEX"
BUILD_SCRIPT="$BUILD_TREE/native/build.sh"

DEST="$HOME/.local/opt/pdf2htmlEX"
DEST_BIN="$DEST/bin/pdf2htmlEX"
DEST_SHARE="$DEST/share/pdf2htmlEX"

POPPLER_DATA_DIR="/opt/homebrew/share/poppler"
TEST_PDF="$BUILD_TREE/pdf2htmlEX/test/browser_tests/basic_text.pdf"

say()  { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. Locate build artifacts -----------------------------------------------

[ -d "$BUILD_TREE" ] || die "build tree not found: $BUILD_TREE
  Set PDF2HTMLEX_BUILD_TREE or build it first: $BUILD_SCRIPT"

# Prefer the cmake install-tree binary; fall back to native/pdf2htmlEX.
if [ -x "$INSTALL_TREE/bin/pdf2htmlEX" ]; then
    SRC_BIN="$INSTALL_TREE/bin/pdf2htmlEX"
elif [ -x "$NATIVE_BIN_FALLBACK" ]; then
    SRC_BIN="$NATIVE_BIN_FALLBACK"
else
    die "no built pdf2htmlEX binary found.
  Looked for:
    $INSTALL_TREE/bin/pdf2htmlEX
    $NATIVE_BIN_FALLBACK
  Build it first: $BUILD_SCRIPT"
fi

SRC_SHARE="$INSTALL_TREE/share/pdf2htmlEX"
[ -d "$SRC_SHARE" ] || die "share data not found: $SRC_SHARE
  Build it first: $BUILD_SCRIPT"
[ -f "$SRC_SHARE/manifest" ] || die "share data looks incomplete (no manifest): $SRC_SHARE"

say "Build tree:    $BUILD_TREE"
say "Source binary: $SRC_BIN"
say "Source share:  $SRC_SHARE"

# --- 2. Copy into the stable prefix ------------------------------------------

mkdir -p "$DEST/bin" "$DEST/share"

# Idempotent: overwrite binary and replace share tree wholesale.
cp -f "$SRC_BIN" "$DEST_BIN"
chmod +x "$DEST_BIN"

rm -rf "$DEST_SHARE"
cp -R "$SRC_SHARE" "$DEST_SHARE"

say "Installed binary: $DEST_BIN"
say "Installed share:  $DEST_SHARE"

# --- 3. Runtime dylib + poppler-data check (warn only) -----------------------

missing=0
if command -v otool >/dev/null 2>&1; then
    while IFS= read -r lib; do
        # Only check absolute Homebrew dylib paths; skip /usr/lib + frameworks.
        case "$lib" in
            /opt/homebrew/*)
                if [ ! -e "$lib" ]; then
                    warn "linked dylib missing: $lib (brew install the owning formula)"
                    missing=1
                fi
                ;;
        esac
    done < <(otool -L "$DEST_BIN" 2>/dev/null | awk 'NR>1 {print $1}')
else
    warn "otool not found; skipping dylib dependency check"
fi

if [ ! -d "$POPPLER_DATA_DIR" ]; then
    warn "poppler data dir missing: $POPPLER_DATA_DIR (brew install poppler) — CJK/CID PDFs may fail"
    missing=1
fi
[ "$missing" -eq 0 ] && say "Runtime deps: all linked Homebrew dylibs + poppler data present."

# --- 4. Self-test: --version + tiny conversion -------------------------------

ver="$("$DEST_BIN" --version 2>&1 | head -1 || true)"
case "$ver" in
    *"pdf2htmlEX version"*) say "Version check: $ver" ;;
    *) die "version check failed: $ver" ;;
esac

if [ -f "$TEST_PDF" ]; then
    tmp_out="$(mktemp -d "${TMPDIR:-/tmp}/p2h-install-selftest.XXXXXX")"
    trap 'rm -rf "$tmp_out"' EXIT
    if "$DEST_BIN" \
        --data-dir "$DEST_SHARE" \
        --poppler-data-dir "$POPPLER_DATA_DIR" \
        --dest-dir "$tmp_out" \
        "$TEST_PDF" >/dev/null 2>&1; then
        out_html="$tmp_out/basic_text.html"
        if [ -s "$out_html" ] && grep -q 'class="pf' "$out_html"; then
            bytes="$(wc -c < "$out_html" | tr -d ' ')"
            say "Self-test conversion: OK (basic_text.html, ${bytes} bytes, class=\"pf\" present)"
        else
            die "self-test produced no valid HTML (missing output or no class=\"pf\")"
        fi
    else
        die "self-test conversion failed (non-zero exit)"
    fi
else
    warn "test PDF not found, skipping conversion self-test: $TEST_PDF"
fi

say ""
say "OK — pdf2htmlEX installed at $DEST"
say "Invoke with explicit data dirs from any cwd:"
say "  $DEST_BIN \\"
say "    --data-dir $DEST_SHARE \\"
say "    --poppler-data-dir $POPPLER_DATA_DIR \\"
say "    --dest-dir <out> <input.pdf>"
