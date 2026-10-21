#!/usr/bin/env bash
# Download one URL into $CORPUS/incoming/<source>/<filename>, verify it is a PDF,
# then append "filename<TAB>url<TAB>license" to that source's _files.tsv.
# The row is appended only after the file is completely written and renamed.
#
# usage: fetch-one.sh <source> <url> <filename> <license> [max_mb]
# env:   PDFV_CORPUS_DIR (default ~/.local/share/pdf_viewer/corpus)
#        FETCH_SLEEP seconds to sleep after the request (default 1)
#        MIN_FREE_GB stop when free space on the volume is below this (default 55)
set -euo pipefail
src=$1 url=$2 name=$3 lic=$4 max_mb=${5:-400}
corpus=${PDFV_CORPUS_DIR:-$HOME/.local/share/pdf_viewer/corpus}
dir=$corpus/incoming/$src
mkdir -p "$dir/.part"
ua="pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"

free_gb=$(df -g "$corpus" | awk 'NR==2{print $4}')
if (( free_gb < ${MIN_FREE_GB:-55} )); then
  echo "STOP: only ${free_gb} GB free" >&2; exit 3
fi
if [[ -e "$dir/$name" ]]; then echo "skip (exists): $name"; exit 0; fi

part=$dir/.part/$name
rc=0
curl -sS -L --fail --retry 2 --retry-delay 5 --max-time 900 \
  --max-filesize $((max_mb * 1024 * 1024)) -A "$ua" -o "$part" "$url" || rc=$?
sleep "${FETCH_SLEEP:-1}"
if (( rc != 0 )); then rm -f "$part"; echo "FAIL curl=$rc $url" >&2; exit 2; fi
if ! head -c 1024 "$part" | LC_ALL=C grep -aq '%PDF-'; then
  echo "FAIL not-pdf ($(head -c 60 "$part" | tr -c '[:print:]' ' ')) $url" >&2
  rm -f "$part"; exit 4
fi
mv "$part" "$dir/$name"
printf '%s\t%s\t%s\n' "$name" "$url" "$lic" >> "$dir/_files.tsv"
echo "ok $(du -k "$dir/$name" | cut -f1) KB $name"
