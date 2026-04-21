#!/bin/bash

# ============================================================================
# pdf_viewer — phase-1 conversion logic.
#
# Invoked by the thin Raycast entrypoint at
#   raycast_scripts/other/pdf-viewer-convert.sh
# (raycast only indexes files under raycast_scripts/, so that's where the
# Raycast-header entrypoint must live).
#
# This script carries the real behavior. It's functionally equivalent to the
# old hardcoded pdf2html-convert.sh in raycast_scripts/other/, but:
#   - Uses port 7435 + cache ~/.cache/pdf_viewer/ so it runs side-by-side
#     with the old one for A/B comparison
#   - Injects <link>/<script> tags pointing to /_assets/overlay.{css,js}
#     instead of inline CSS/JS
#   - Those assets are symlinked from pdf_viewer/assets/, so editing them
#     is a file-save away from affecting every converted HTML
# ============================================================================

PORT=7435
REPO_DIR="/Users/andersbekkevard/dev/misc/pdf_viewer"
ASSET_SRC="$REPO_DIR/assets"
CACHE_DIR="$HOME/.cache/pdf_viewer"
LOG_FILE="$CACHE_DIR/log"
MAP_FILE="$CACHE_DIR/mappings.tsv"
ASSET_LINK="$CACHE_DIR/_assets"
IMAGE="pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"
OVERLAY_VERSION=1  # bump to bust browser cache of /_assets/overlay.*

mkdir -p "$CACHE_DIR"
# Silence stdio so Raycast doesn't raise notifications from subprocess output
exec >>"$LOG_FILE" 2>&1

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

notify() {
    osascript -e "display notification \"$1\" with title \"pdf_viewer\"" >/dev/null 2>&1
}

fail() {
    log "FAIL: $1"
    osascript -e 'do shell script "afplay /System/Library/Sounds/Basso.aiff &"' >/dev/null 2>&1
    notify "$1"
    exit 1
}

# Symlink assets into cache dir so http.server serves them at /_assets/*
if [[ ! -L "$ASSET_LINK" ]]; then
    rm -rf "$ASSET_LINK" 2>/dev/null
    ln -s "$ASSET_SRC" "$ASSET_LINK" || fail "Could not link assets dir"
fi

# Get active tab URL from Comet
TAB_URL=$(osascript -e 'tell application "Comet" to return URL of active tab of front window' 2>/dev/null)

# -----------------------------------------------------------------------------
# Scheme dispatch. file:// and http(s):// both end up with:
#   HASH, OUT_DIR, PDF_NAME, OUT_NAME, PDF_DIR (mount source), SOURCE_REF (log)
# -----------------------------------------------------------------------------
if [[ "$TAB_URL" =~ ^file://.*\.[pP][dD][fF]$ ]]; then
    ENCODED_PATH="${TAB_URL#file://}"
    LOCAL_PATH=$(python3 -c "import sys, urllib.parse as u; print(u.unquote(sys.argv[1]))" "$ENCODED_PATH")
    [[ -f "$LOCAL_PATH" ]] || fail "PDF not found on disk"

    # Stable per-file cache key (content hash, survives moves/renames)
    HASH=$(shasum -a 256 "$LOCAL_PATH" | awk '{print $1}' | head -c 16)
    PDF_NAME=$(basename "$LOCAL_PATH")
    OUT_NAME="${PDF_NAME%.*}.html"
    OUT_DIR="$CACHE_DIR/$HASH"
    PDF_DIR=$(dirname "$LOCAL_PATH")
    SOURCE_REF="$LOCAL_PATH"
    mkdir -p "$OUT_DIR"

elif [[ "$TAB_URL" =~ ^https?:// ]]; then
    # host+path hash (query stripped, so signed URLs cache across sessions)
    HASH=$(python3 -c "import sys,hashlib,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(hashlib.sha256((p.netloc+p.path).encode()).hexdigest()[:16])" "$TAB_URL")
    OUT_DIR="$CACHE_DIR/$HASH"
    PDF_DIR="$OUT_DIR/_source"
    SOURCE_REF="$TAB_URL"
    mkdir -p "$OUT_DIR"

    # Resolve PDF_NAME/OUT_NAME. Three cases:
    #   1. fully cached (OUT_DIR has *.html)      → read name from html
    #   2. _source has leftover *.pdf from a prior crashed convert → reuse
    #   3. cold miss                               → download + parse filename
    EXISTING_HTML=$(ls "$OUT_DIR"/*.html 2>/dev/null | head -1)
    EXISTING_PDF=$(ls "$OUT_DIR/_source"/*.pdf 2>/dev/null | head -1)

    if [[ -n "$EXISTING_HTML" ]]; then
        OUT_NAME=$(basename "$EXISTING_HTML")
        PDF_NAME="${OUT_NAME%.html}.pdf"
    elif [[ -n "$EXISTING_PDF" ]]; then
        PDF_NAME=$(basename "$EXISTING_PDF")
        OUT_NAME="${PDF_NAME%.*}.html"
    else
        mkdir -p "$PDF_DIR"
        notify "Downloading…"
        log "download start: $TAB_URL"
        if ! curl -fsSL --max-time 300 \
                -D "$PDF_DIR/headers.txt" \
                -o "$PDF_DIR/document.pdf" \
                "$TAB_URL"; then
            rm -rf "$OUT_DIR"
            fail "Download failed"
        fi

        # Magic-byte sanity check (catches login pages from expired signed URLs)
        MAGIC=$(head -c 4 "$PDF_DIR/document.pdf" 2>/dev/null)
        if [[ "$MAGIC" != "%PDF" ]]; then
            log "magic-byte check failed; first 200 bytes of $PDF_DIR/document.pdf:"
            head -c 200 "$PDF_DIR/document.pdf" | od -c >>"$LOG_FILE" 2>&1
            rm -rf "$OUT_DIR"
            fail "Downloaded file is not a PDF (magic: ${MAGIC@Q})"
        fi
        log "download ok: $(du -h "$PDF_DIR/document.pdf" | cut -f1)"

        # Filename: Content-Disposition → URL path → fallback
        PDF_NAME=$(python3 - "$PDF_DIR/headers.txt" "$TAB_URL" <<'PY'
import sys, re, email.message, urllib.parse as u
headers_path, url = sys.argv[1], sys.argv[2]
name = None
try:
    hdrs = open(headers_path, 'r', encoding='utf-8', errors='replace').read()
    # curl -D captures all hops; keep the last Content-Disposition seen
    matches = re.findall(r'(?im)^content-disposition:\s*(.+?)\s*$', hdrs)
    if matches:
        msg = email.message.Message()
        msg['content-disposition'] = matches[-1]
        name = msg.get_filename()
except Exception:
    pass
if not name:
    path = u.urlparse(url).path
    name = path.rsplit('/', 1)[-1] or ''
name = u.unquote(name or '').strip().replace('/', '_').replace('\\', '_').replace('\x00', '')
if not name.lower().endswith('.pdf'):
    name = (name + '.pdf') if name else 'document.pdf'
if name in ('.pdf', '.', '..'):
    name = 'document.pdf'
print(name)
PY
        )
        [[ -n "$PDF_NAME" ]] || PDF_NAME="document.pdf"
        OUT_NAME="${PDF_NAME%.*}.html"
        mv "$PDF_DIR/document.pdf" "$PDF_DIR/$PDF_NAME"
        log "resolved filename: $PDF_NAME"
    fi

else
    fail "Active tab is not a file:// or http(s):// PDF"
fi

# -----------------------------------------------------------------------------
# Convert if not cached. Docker only consulted here, on actual cache miss.
# -----------------------------------------------------------------------------
if [[ ! -f "$OUT_DIR/$OUT_NAME" ]]; then
    if ! docker info >/dev/null 2>&1; then
        fail "Docker daemon not running — start Docker.app"
    fi
    notify "Converting $PDF_NAME…"
    log "convert start: $SOURCE_REF -> $OUT_DIR/$OUT_NAME"
    docker run --rm --platform linux/amd64 \
        -e LC_ALL=C.UTF-8 -e LANG=C.UTF-8 \
        -v "$PDF_DIR":/pdf:ro \
        -v "$OUT_DIR":/out \
        -w /pdf \
        "$IMAGE" \
        --dest-dir /out \
        "$PDF_NAME" \
        > >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE") \
        2> >(grep -v 'perl: warning\|Setting locale failed' >>"$LOG_FILE") \
        || fail "pdf2htmlEX conversion failed (see $LOG_FILE)"
    log "convert done: $OUT_NAME"
fi

# Inject title, favicon, and overlay <link>/<script> tags (idempotent)
python3 - "$OUT_DIR/$OUT_NAME" "${PDF_NAME%.*}" "$OVERLAY_VERSION" <<'PY'
import sys, re, pathlib, html as _html, urllib.parse as _up
p = pathlib.Path(sys.argv[1])
stem = _html.escape(sys.argv[2])
version = sys.argv[3]
html = p.read_text(encoding='utf-8', errors='ignore')

# --- Title -----------------------------------------------------------------
if re.search(r'<title>.*?</title>', html, flags=re.DOTALL):
    html = re.sub(r'<title>.*?</title>', f'<title>{stem}</title>', html,
                  count=1, flags=re.DOTALL)
else:
    html = html.replace('</head>', f'<title>{stem}</title></head>', 1)

# --- Favicon ---------------------------------------------------------------
html = re.sub(r'<link[^>]*\brel\s*=\s*["\']?(?:shortcut\s+)?icon["\'][^>]*>\s*',
              '', html, flags=re.IGNORECASE)
_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">📑</text></svg>'
_favicon = f'<link id="pdf2html-favicon" rel="icon" href="data:image/svg+xml;utf8,{_up.quote(_svg)}">'
if 'id="pdf2html-favicon"' in html:
    html = re.sub(r'<link id="pdf2html-favicon"[^>]*>\s*', '', html)
html = html.replace('</head>', _favicon + '</head>', 1)

# --- Overlay link + script tags --------------------------------------------
# Strip any prior inline/style injection (from the old hardcoded script) or
# prior tag injection (for upgrades).
html = re.sub(r'<style id="pdf2html-overlay-css">.*?</style>\s*',   '', html, flags=re.DOTALL)
html = re.sub(r'<script id="pdf2html-overlay-js">.*?</script>\s*',  '', html, flags=re.DOTALL)
html = re.sub(r'<link id="pdf2html-overlay-css"[^>]*>\s*',          '', html)
html = re.sub(r'<script id="pdf2html-overlay-js"[^>]*></script>\s*', '', html)

overlay_tags = (
    f'<link id="pdf2html-overlay-css" rel="stylesheet" href="/_assets/overlay.css?v={version}">'
    f'<script id="pdf2html-overlay-js" src="/_assets/overlay.js?v={version}" defer></script>'
)
html = html.replace('</head>', overlay_tags + '</head>', 1)

p.write_text(html, encoding='utf-8')
PY

# Ensure static server is up
if ! curl -sf "http://localhost:${PORT}/" >/dev/null 2>&1; then
    log "starting http.server on :$PORT rooted at $CACHE_DIR"
    (cd "$CACHE_DIR" && nohup python3 -m http.server "$PORT" >>"$LOG_FILE" 2>&1 &)
    for i in $(seq 1 25); do
        sleep 0.2
        curl -sf "http://localhost:${PORT}/" >/dev/null 2>&1 && break
    done
fi

ENCODED_NAME=$(python3 -c "import sys, urllib.parse as u; print(u.quote(sys.argv[1]))" "$OUT_NAME")
URL="http://localhost:${PORT}/${HASH}/${ENCODED_NAME}"

# Upsert pdf→html mapping (dedupe on HASH — works for both file and url)
{
    if [[ -f "$MAP_FILE" ]]; then
        awk -F'\t' -v h="$HASH" '$3 != h' "$MAP_FILE"
    fi
    printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$SOURCE_REF" "$HASH" "$OUT_DIR/$OUT_NAME"
} > "$MAP_FILE.tmp" && mv "$MAP_FILE.tmp" "$MAP_FILE"

# Navigate current tab in-place so back-button returns to the source PDF
osascript -e "
tell application \"Comet\"
    set URL of active tab of front window to \"${URL}\"
end tell
" >/dev/null 2>&1
