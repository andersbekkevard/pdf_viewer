#!/usr/bin/env bash
# Fetch CTAN package documentation PDFs.
# usage: ctan-fetch.sh <pkg>[:<regex for the doc file name>] ...
# Reads https://ctan.org/pkg/<pkg>, takes the first mirrors.ctan.org .pdf link whose
# file name matches the regex (default: any), and fetches it into incoming/ctan-docs/.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
for spec in "$@"; do
  pkg=${spec%%:*}; rx=.; [[ $spec == *:* ]] && rx=${spec#*:}
  url=$(curl -s -A "Mozilla/5.0" "https://ctan.org/pkg/$pkg" | grep -oE 'https://mirrors\.ctan\.org/[^"]+\.pdf' | awk '!s[$0]++' | grep -E "/[^/]*$rx[^/]*\.pdf$" | head -1)
  sleep 1
  [[ -z $url ]] && { echo "no pdf for $pkg" >&2; continue; }
  FETCH_SLEEP=2 "$here/fetch-one.sh" ctan-docs "$url" "$pkg--$(basename "$url")" "CTAN package documentation for $pkg; LPPL or other free license per package" 60 || true
done
