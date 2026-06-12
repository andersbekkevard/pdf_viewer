#!/bin/bash

# ============================================================================
# pdf_viewer — install-native-pdf2htmlex.sh
#
# Installs a native macOS arm64 pdf2htmlEX (0.18.8.rc2, poppler 24.06.1,
# fontforge 20230101) into a stable, relocation-safe prefix at
# ~/.local/opt/pdf2htmlEX/. Two source paths, tried in order:
#
#   1. LOCAL BUILD TREE (preferred when present): the v2 build tree at
#      ~/dev/external/pdf2htmlEX_v2. Its binary links Homebrew dylibs via
#      absolute /opt/homebrew/opt/* paths — no bundled lib/ needed.
#   2. HOMEBREW TAP (fallback on a machine without the build tree):
#      `brew install andersbekkevard/tools/pdf2htmlex` ships a RELOCATABLE
#      bundle — the binary plus every Homebrew dylib it needs, with
#      @executable_path/../lib install names. The brew keg lays this out
#      under libexec/{bin,lib,share}. This installer copies bin + lib +
#      share out of that keg so the binary keeps finding its bundled libs.
#
# WHY: the local-build binary bakes its default data-dir into the build
# tree (native/build/install/share/pdf2htmlEX). That path is fragile —
# deleting or moving the build tree breaks the binary. This installer
# copies the binary + share data into a stable prefix and the
# daemon/scripts always pass --data-dir explicitly, so the baked-in
# default is irrelevant.
#
# This script COPIES ONLY. It never rebuilds, never touches Docker, and
# never hits the network. If neither source is present it points you at
# native/build.sh (or the tap) and exits.
#
# Runtime deps differ by source:
#   - From the build tree: the binary links several Homebrew dylibs
#     (cairo, glib, freetype, …) via /opt/homebrew/opt/* and needs the
#     poppler data dir (/opt/homebrew/share/poppler). The installer WARNS
#     (does not fail) if a linked dylib or the poppler data dir is missing.
#   - From the brew tap: dylibs are BUNDLED into the prefix's lib/ via
#     @executable_path/../lib, so no /opt/homebrew/* dylibs are required;
#     only the poppler data dir matters (CJK/CID PDFs).
#
# The destination layout contract (bin/pdf2htmlEX + share/pdf2htmlEX) is
# unchanged; the brew path additionally populates lib/ (additive, ignored
# by the build-tree binary which uses absolute paths).
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

BREW_FORMULA="andersbekkevard/tools/pdf2htmlex"

DEST="$HOME/.local/opt/pdf2htmlEX"
DEST_BIN="$DEST/bin/pdf2htmlEX"
DEST_LIB="$DEST/lib"
DEST_SHARE="$DEST/share/pdf2htmlEX"

POPPLER_DATA_DIR="/opt/homebrew/share/poppler"
TEST_PDF="$BUILD_TREE/pdf2htmlEX/test/browser_tests/basic_text.pdf"

say()  { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- 1. Locate source artifacts ----------------------------------------------
#
# SRC_LIB is set only for the brew bundle (relocatable, dylibs in lib/);
# the build-tree binary leaves it empty (absolute /opt/homebrew links).
SRC_BIN=""
SRC_SHARE=""
SRC_LIB=""
SRC_DESC=""

if [ -d "$BUILD_TREE" ]; then
    # Prefer the cmake install-tree binary; fall back to native/pdf2htmlEX.
    if [ -x "$INSTALL_TREE/bin/pdf2htmlEX" ]; then
        SRC_BIN="$INSTALL_TREE/bin/pdf2htmlEX"
    elif [ -x "$NATIVE_BIN_FALLBACK" ]; then
        SRC_BIN="$NATIVE_BIN_FALLBACK"
    fi
    if [ -n "$SRC_BIN" ] && [ -f "$INSTALL_TREE/share/pdf2htmlEX/manifest" ]; then
        SRC_SHARE="$INSTALL_TREE/share/pdf2htmlEX"
        SRC_DESC="local build tree ($BUILD_TREE)"
    else
        SRC_BIN=""
    fi
fi

# Fallback: the brew tap keg. Layout is libexec/{bin,lib,share}.
if [ -z "$SRC_BIN" ] && command -v brew >/dev/null 2>&1; then
    BREW_PREFIX="$(brew --prefix "$BREW_FORMULA" 2>/dev/null || true)"
    if [ -n "$BREW_PREFIX" ] && [ -x "$BREW_PREFIX/libexec/bin/pdf2htmlEX" ]; then
        SRC_BIN="$BREW_PREFIX/libexec/bin/pdf2htmlEX"
        SRC_SHARE="$BREW_PREFIX/libexec/share/pdf2htmlEX"
        SRC_LIB="$BREW_PREFIX/libexec/lib"
        SRC_DESC="brew keg ($BREW_PREFIX)"
    fi
fi

if [ -z "$SRC_BIN" ]; then
    die "no pdf2htmlEX source found. Tried:
    local build tree: $INSTALL_TREE/bin/pdf2htmlEX
                      $NATIVE_BIN_FALLBACK
    brew keg:         \$(brew --prefix $BREW_FORMULA)/libexec/bin/pdf2htmlEX
  Build it (native/build.sh) or install the tap:
    brew tap andersbekkevard/tools && brew install $BREW_FORMULA"
fi

[ -d "$SRC_SHARE" ] || die "share data not found: $SRC_SHARE"
[ -f "$SRC_SHARE/manifest" ] || die "share data looks incomplete (no manifest): $SRC_SHARE"

say "Source:        $SRC_DESC"
say "Source binary: $SRC_BIN"
say "Source share:  $SRC_SHARE"
[ -n "$SRC_LIB" ] && say "Source lib:    $SRC_LIB (bundled relocatable dylibs)"

# --- 2. Copy into the stable prefix ------------------------------------------

mkdir -p "$DEST/bin" "$DEST/share"

# Bundled libs first (brew source only): the binary's @executable_path/../lib
# install names require lib/ to sit beside bin/ in DEST.
if [ -n "$SRC_LIB" ] && [ -d "$SRC_LIB" ]; then
    rm -rf "$DEST_LIB"
    cp -R "$SRC_LIB" "$DEST_LIB"
    say "Installed lib:    $DEST_LIB"
else
    # Build-tree binary uses absolute paths; drop any stale bundled lib/ so
    # the prefix matches the active source exactly.
    rm -rf "$DEST_LIB"
fi

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
