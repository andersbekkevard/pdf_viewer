#!/usr/bin/env bash
# Sample PDFs linked from one MIT OpenCourseWare course page.
# usage: ocw-sample.sh <label> <page_url> <count> [filter_regex]
# The page's /resources/ links are spread-sampled; each resource page's .pdf is fetched.
set -euo pipefail
label=$1 page=$2 count=$3 filt=${4:-.}
here=$(cd "$(dirname "$0")" && pwd)
ua="pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"
course=$(sed -E 's#(https://ocw.mit.edu/courses/[^/]+)/.*#\1#' <<<"$page")
res=()
while IFS= read -r l; do res+=("$l"); done < <(curl -s -A "$ua" "$page" | grep -oE 'href="/courses/[^"]+/resources/[^"]+/"' | sed -E 's/href="([^"]+)"/\1/' | grep -E "$filt" | awk '!s[$0]++')
n=${#res[@]}; (( n == 0 )) && { echo "no resources on $page" >&2; exit 1; }
step=$(( n / count )); (( step < 1 )) && step=1
for ((i = 0, k = 0; i < n && k < count; i += step, k++)); do
  sleep 1
  pdf=$(curl -s -A "$ua" "https://ocw.mit.edu${res[$i]}" | grep -oE 'href="[^"]+\.pdf"' | head -1 | sed -E 's/href="([^"]+)"/\1/')
  [[ -z $pdf ]] && { echo "no pdf in ${res[$i]}" >&2; continue; }
  [[ $pdf == /* ]] && pdf="https://ocw.mit.edu$pdf"
  name="${label}__$(basename "$pdf" | sed -E 's/^[0-9a-f]{32}_//')"
  "$here/fetch-one.sh" mit-ocw "$pdf" "$name" "CC BY-NC-SA 4.0 (MIT OpenCourseWare)" 150 || true
done
