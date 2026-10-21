#!/bin/bash
# Fetch the public PDF test suites into the corpus (see bench/corpus/sources/adversarial.md).
#
#   bench/corpus/fetch/adversarial-suites.sh [pdfjs|pdfium|poppler|qpdf|verapdf ...]
#
# Each repository is cloned shallow (and sparse where it helps) into
# $PDFV_CORPUS_DIR/staging/<name>; nothing from it is executed. Only PDFs are
# copied to incoming/<source>/ by stage-copy.py, with URLs pinned to the cloned
# commit. Re-running pulls nothing new into existing clones and skips files that
# are already listed. veraPDF takes all of the ISO/Isartor/TWG/Undefined
# directories and every 5th file of PDF_A-*/PDF_UA-* (VERAPDF_STEP to change).
# PDFium's .in templates are expanded by bench/corpus/synth/pdfium_templates.py.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CORPUS=${PDFV_CORPUS_DIR:-$HOME/.local/share/pdf_viewer/corpus}
STAGE=$CORPUS/staging
COPY="python3 -I $HERE/stage-copy.py"
mkdir -p "$STAGE"
cd "$STAGE"

sparse() { # dir url pattern...
  local dir=$1 url=$2; shift 2
  [ -d "$dir" ] || git clone -q --depth 1 --filter=blob:none --sparse "$url" "$dir"
  git -C "$dir" sparse-checkout set --no-cone "$@"
}

do_pdfjs() {
  sparse pdfjs https://github.com/mozilla/pdf.js.git 'test/pdfs/*'
  local c; c=$(git -C pdfjs rev-parse HEAD)
  curl -sfL -o pdfjs_test_manifest.json "https://raw.githubusercontent.com/mozilla/pdf.js/$c/test/test_manifest.json"
  (cd pdfjs && find test/pdfs -type f -iname '*.pdf' | sort) | $COPY --source pdfjs --root pdfjs --strip test/pdfs/ \
    --url "https://raw.githubusercontent.com/mozilla/pdf.js/$c/{path}" \
    --license "unknown per file (mozilla/pdf.js test suite; repo Apache-2.0; many files come from bug reports)"
  echo "pdfjs: linked documents are fetched by pdfjs-links.py"
}

do_pdfium() {
  sparse pdfium https://pdfium.googlesource.com/pdfium 'testing/resources/*'
  local c; c=$(git -C pdfium rev-parse HEAD)
  (cd pdfium && find testing/resources -type f -iname '*.pdf' | sort) | $COPY --source pdfium --root pdfium \
    --strip testing/resources/ --url "https://pdfium.googlesource.com/pdfium/+/$c/{path}" \
    --license "BSD-3-Clause (PDFium repo); some files third-party"
  python3 -I "$HERE/../synth/pdfium_templates.py" pdfium
}

do_poppler() {
  [ -d poppler ] || git clone -q --depth 1 --filter=blob:none --no-checkout https://gitlab.freedesktop.org/poppler/test.git poppler
  git -C poppler sparse-checkout set --no-cone '*.pdf' '*.PDF' /COPYING
  git -C poppler checkout -q HEAD
  local c; c=$(git -C poppler rev-parse HEAD)
  (cd poppler && find . -type f -iname '*.pdf' -not -path './.git/*' | sed 's|^\./||' | sort) | $COPY --source poppler-test \
    --root poppler --url "https://gitlab.freedesktop.org/poppler/test/-/raw/$c/{path}" \
    --license "unknown per file (poppler test repo; repo code GPL-2.0; files from bug reports)"
}

do_qpdf() {
  sparse qpdf https://github.com/qpdf/qpdf.git '*.pdf'
  local c; c=$(git -C qpdf rev-parse HEAD)
  (cd qpdf && find . -type f -iname '*.pdf' -not -path './.git/*' | sed 's|^\./||' | sort) | $COPY --source qpdf --root qpdf \
    --url "https://raw.githubusercontent.com/qpdf/qpdf/$c/{path}" --license "Apache-2.0 (qpdf repo test files)"
}

do_verapdf() {
  [ -d verapdf ] || git clone -q --depth 1 https://github.com/veraPDF/veraPDF-corpus.git verapdf
  local c step=${VERAPDF_STEP:-5}; c=$(git -C verapdf rev-parse HEAD)
  (cd verapdf && { find 'ISO 32000-1' 'ISO 32000-2' 'Isartor test files' 'TWG test files' 'Undefined' -type f -iname '*.pdf' | sort;
                   find PDF_A-* PDF_UA-* -type f -iname '*.pdf' | sort | awk -v s="$step" '(NR-1)%s==0'; }) |
    $COPY --source verapdf-corpus --root verapdf \
      --url "https://raw.githubusercontent.com/veraPDF/veraPDF-corpus/$c/{path}" --license "CC-BY-4.0 (veraPDF consortium)"
}

df -h "$HOME" | tail -1
for s in "${@:-pdfjs pdfium poppler qpdf verapdf}"; do
  for t in $s; do "do_$t"; done
done
