#!/usr/bin/env bash
# Fetch OpenStax book PDFs by exact title.
# usage: openstax-fetch.sh "<title>"...
# Looks each title up in the OpenStax CMS API and fetches high_resolution_pdf_url.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
api='https://openstax.org/apps/cms/api/v2/pages/?type=books.Book&fields=title,high_resolution_pdf_url,license_name&limit=250'
json=$(curl -s -A "Mozilla/5.0" "$api")
for t in "$@"; do
  line=$(python3 -I -c 'import json,sys; t=sys.argv[1]; d=json.loads(sys.stdin.read())
for b in d["items"]:
    if b["title"]==t: print(b["high_resolution_pdf_url"]+"\t"+str(b.get("license_name")))' "$t" <<<"$json")
  [[ -z $line ]] && { echo "no book: $t" >&2; continue; }
  url=${line%%$'\t'*}; lic=${line#*$'\t'}
  name=$(echo "$t" | tr ' ' '_' | tr -cd 'A-Za-z0-9_.-').pdf
  FETCH_SLEEP=2 "$here/fetch-one.sh" openstax "$url" "$name" "$lic (OpenStax)" 520 || true
done
