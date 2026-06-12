# Brewfile — runtime dependencies for the pdf_viewer toolchain.
#
# Declarative answer to "what does a fresh Mac need to run this?".
# Verify with:  brew bundle check --no-upgrade --file=Brewfile
# (--no-upgrade: presence is the contract, not freshness — an outdated
# formula still satisfies the runtime deps.)
#
# This list is RUNTIME only. The native pdf2htmlEX binary itself is built
# out-of-tree (~/dev/external/pdf2htmlEX_v2, installed by
# scripts/install-native-pdf2htmlex.sh) — its build-only deps (cmake,
# pkg-config, autoconf, …) live in that external build recipe, not here.
#
# The nine formulas below back the /opt/homebrew dylibs that the installed
# pdf2htmlEX binary links against; confirm with:
#   otool -L ~/.local/opt/pdf2htmlEX/bin/pdf2htmlEX

# --- pdf2htmlEX linked dylibs (otool -L of the binary) ---
brew "cairo"        # libcairo            — pdf2htmlEX rendering backend
brew "glib"         # libgio/gobject/glib — pdf2htmlEX (GLib core)
brew "gettext"      # libintl             — pdf2htmlEX (i18n, via glib)
brew "freetype"     # libfreetype         — pdf2htmlEX font rasterization
brew "libpng"       # libpng16            — pdf2htmlEX raster output
brew "jpeg-turbo"   # libjpeg             — pdf2htmlEX JPEG image handling
brew "libxml2"      # libxml2             — pdf2htmlEX
brew "openjpeg"     # libopenjp2          — pdf2htmlEX JPEG2000 decode
brew "fontconfig"   # libfontconfig       — pdf2htmlEX font discovery

# --- poppler CLI tools + data ---
brew "poppler"      # pdftocairo (scripts/extract-pdf-thumbs.sh) +
                    # pdfinfo (scripts/extract-pdf-meta.sh) + share/poppler data

# --- Python runner (NOT a brew formula here) ---
# uv is required by every Python path in the repo (daemon/, scripts/*.py via
# `uv run`; see CLAUDE.md "Python: always uv") but is intentionally NOT
# listed as a formula: this machine installs uv via the astral standalone
# installer (~/.local/bin/uv, updated by `uv self update`), and a brew copy
# would just shadow-drift behind it. On a fresh Mac install either way:
#   curl -LsSf https://astral.sh/uv/install.sh | sh    # or: brew install uv
