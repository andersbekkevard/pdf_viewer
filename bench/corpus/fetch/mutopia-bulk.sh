#!/usr/bin/env bash
# Sample Mutopia Project A4 scores across composers.
# usage: mutopia-bulk.sh <n_composers> <per_composer> <seed>
# Composers come from https://www.mutopiaproject.org/browse.html, shuffled with the seed;
# page-pdfs.py fetches <per_composer> -a4.pdf files from each composer's first table page.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
n=$1 per=$2 seed=$3
curl -s -A "Mozilla/5.0" https://www.mutopiaproject.org/browse.html | grep -oE 'Composer=[A-Za-z]+' | sort -u | sed 's/Composer=//' |
  python3 -I -c "import random,sys; r=random.Random($seed); c=sys.stdin.read().split(); r.shuffle(c); print('\n'.join(c[:$n]))" |
while read -r c; do
  python3 -I "$here/page-pdfs.py" sheet-music "mutopia2-$c" "https://www.mutopiaproject.org/cgibin/make-table.cgi?Composer=$c" "$per" \
    "Mutopia Project: public domain or CC BY / CC BY-SA (per piece)" '-a4\.pdf$'
done
