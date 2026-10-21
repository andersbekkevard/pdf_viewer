#!/usr/bin/env bash
# Fetch IRS forms, instructions and publications by file stem.
# usage: irs-forms.sh <label> <stem>...       current:  https://www.irs.gov/pub/irs-pdf/<stem>.pdf
#        irs-forms.sh <label> prior:<stem>--<year>...   prior: https://www.irs.gov/pub/irs-prior/<stem>--<year>.pdf
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
label=$1; shift
for s in "$@"; do
  if [[ $s == prior:* ]]; then s=${s#prior:}; url="https://www.irs.gov/pub/irs-prior/$s.pdf"; else url="https://www.irs.gov/pub/irs-pdf/$s.pdf"; fi
  FETCH_SLEEP=1 "$here/fetch-one.sh" gov-irs "$url" "${label}__$s.pdf" "US federal government work, public domain" 60 || true
done
