#!/usr/bin/env python3
"""Sample PDFs from the SafeDocs CC-MAIN-2021-31-UNSAFE corpora-pdf zips on digitalcorpora.org.

usage:
  python3 -I safedocs-sample.py issue-trackers --quota pdfium=379,poppler=359,... [--max-mb 25] [--dry-run]
  python3 -I safedocs-sample.py unsafe --quota common-crawl-cmin=350,evalThree=250,... [--max-mb 20] [--dry-run]

The corpus is 1,060 zips (~1 TB). Members are read with HTTP range requests
through bench/corpus/fetch/zip-range-extract.py (loaded as a module, not changed);
no zip is downloaded whole. Central directories are cached as
$PDFV_CORPUS_DIR/staging/safedocs-lists/<zip>.lst (name<TAB>size<TAB>csize).

Candidate pool: issue-trackers reads zips x986-x999 (path
corpora-pdf/issue-trackers/<tracker>/...). unsafe reads every 25th zip in key order
plus x966-x999 and groups by the set directory (corpora-pdf/<set>/...). --zips REGEX
adds more zips to the pool (phase 3 added the 75 corpora-pdf-x0NN-NN zips, which hold
common-crawl-cmin); a larger pool changes which files a quota selects, so files
taken earlier stay and new ones are added up to the quota.

Selection is deterministic: within each group, members up to --max-mb are sorted
by sha256 of the member path and the first N (the quota) are taken. Quotas are
totals, so raising a quota extends the earlier sample. Files already present are
skipped. Members without %PDF in the first 4 KB are skipped. --jobs N reads N members
at a time (phase 2 used 4).

Output: incoming/safedocs-issue-trackers/<tracker>__<name> or
incoming/safedocs-unsafe/<set>__<name>[.pdf]; url column <zip url>#<member>.
"""
import argparse, collections, threading, hashlib, importlib.util, os, re, struct, sys, time, urllib.parse, urllib.request, zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("zre", HERE / "zip-range-extract.py")
zre = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zre)

BASE = "https://digitalcorpora.s3.amazonaws.com/"
PREFIX = "corpora/files/CC-MAIN-2021-31-UNSAFE/corpora-pdf/"
CORPUS = Path(os.environ.get("PDFV_CORPUS_DIR", Path.home() / ".local/share/pdf_viewer/corpus"))
LISTS = CORPUS / "staging" / "safedocs-lists"
LIC = {
    "issue-trackers": "SafeDocs CC-MAIN-2021-31-UNSAFE issue-trackers (digitalcorpora.org); copyright stays with each attachment's owner (research/testing use)",
    "unsafe": "SafeDocs CC-MAIN-2021-31-UNSAFE (digitalcorpora.org; DARPA SafeDocs, JPL/Kudu Dynamics); fuzzed/malformed derivatives of public PDFs (research/testing use)",
}
SOURCE = {"issue-trackers": "safedocs-issue-trackers", "unsafe": "safedocs-unsafe"}


def all_zips() -> list[str]:
    cache = LISTS / "_keys.txt"
    if cache.exists():
        return cache.read_text().split()
    keys, tok = [], None
    while True:
        u = f"{BASE}?list-type=2&prefix={PREFIX}" + (f"&continuation-token={urllib.parse.quote(tok)}" if tok else "")
        d = urllib.request.urlopen(u, timeout=60).read().decode()
        keys += [k for k in re.findall(r"<Key>([^<]+)</Key>", d) if k.endswith(".zip")]
        m = re.search(r"<NextContinuationToken>([^<]+)<", d)
        if not m:
            break
        tok = m.group(1)
    names = [Path(k).stem for k in sorted(keys)]
    LISTS.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(names) + "\n")
    return names


def pool(kind: str, extra: str | None = None) -> list[str]:
    names = all_zips()
    tail = [n for n in names if re.fullmatch(r"corpora-pdf-x9(6[6-9]|[7-9]\d)", n)]
    if kind == "issue-trackers":
        base = {n for n in tail if n >= "corpora-pdf-x986"}
    else:
        base = set(names[::25]) | set(tail)
    if extra:
        base |= {n for n in names if re.fullmatch(extra, n)}
    return sorted(base)


def listing(z: str) -> list[tuple[str, int]]:
    f = LISTS / f"{z}.lst"
    if not f.exists():
        ents = zre.central_dir(f"{BASE}{PREFIX}{z}.zip")
        f.write_text("".join(f"{n}\t{e[3]}\t{e[2]}\n" for n, e in ents.items()))
        time.sleep(0.3)
    return [(l.split("\t")[0], int(l.split("\t")[1])) for l in f.read_text().splitlines() if l]


def fetch(url: str, ents: dict, name: str) -> bytes:
    method, crc, csize, usize, off = ents[name]
    hdr = zre.rng(url, off, off + 29)
    nlen, xlen = struct.unpack("<HH", hdr[26:30])
    start = off + 30 + nlen + xlen
    raw = zre.rng(url, start, start + csize - 1) if csize else b""
    if method == 8:
        raw = zlib.decompress(raw, -15)
    elif method != 0:
        raise ValueError(f"method {method}")
    if zlib.crc32(raw) & 0xFFFFFFFF != crc:
        raise ValueError("crc mismatch")
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["issue-trackers", "unsafe"])
    ap.add_argument("--quota", required=True, help="group=N,... (totals per tracker or set)")
    ap.add_argument("--max-mb", type=float, default=25)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--zips", help="regex of extra zip names to add to the pool, e.g. 'corpora-pdf-x0\\d\\d-\\d\\d'")
    ap.add_argument("--jobs", type=int, default=1, help="parallel range requests (keep low; 4 was used)")
    a = ap.parse_args()
    quota = {k: int(v) for k, v in (x.split("=") for x in a.quota.split(","))}
    LISTS.mkdir(parents=True, exist_ok=True)
    groups = collections.defaultdict(list)
    for z in pool(a.kind, a.zips):
        for name, size in listing(z):
            p = name.split("/")
            if a.kind == "issue-trackers":
                if len(p) != 4 or p[1] != "issue-trackers" or not name.lower().endswith(".pdf"):
                    continue
                g = p[2]
            else:
                if len(p) < 3 or p[1] == "issue-trackers" or name.endswith("/"):
                    continue
                g = p[1]
            if g in quota and 0 < size <= a.max_mb * (1 << 20):
                groups[g].append((hashlib.sha256(name.encode()).hexdigest(), z, name, size))
    out = CORPUS / "incoming" / SOURCE[a.kind]
    out.mkdir(parents=True, exist_ok=True)
    tsv = out / "_files.tsv"
    seen = {l.split("\t")[0] for l in tsv.read_text().splitlines()} if tsv.exists() else set()
    todo = collections.defaultdict(list)
    for g, q in quota.items():
        pick = sorted(groups[g])[:q]
        new = []
        for _, z, name, size in pick:
            base = Path(name).name
            fname = f"{g}__{base}" + ("" if base.lower().endswith(".pdf") else ".pdf")
            if fname not in seen:
                new.append((fname, name, size))
                todo[z].append((fname, name))
        print(f"{g:18} pool={len(groups[g]):6} quota={q:5} new={len(new):5} {sum(s for *_, s in new) / 1e6:8.1f} MB")
    if a.dry_run:
        return 0
    lock = threading.Lock()
    counts = collections.Counter()

    def one(url: str, ents: dict, fname: str, name: str) -> None:
        try:
            data = fetch(url, ents, name)
        except Exception as e:
            with lock:
                print("fail", name, e, flush=True)
                counts["bad"] += 1
            return
        if b"%PDF" not in data[:4096]:
            with lock:
                print("not-pdf", name, flush=True)
                counts["bad"] += 1
            return
        part = out / (fname + ".part")
        part.write_bytes(data)
        os.replace(part, out / fname)
        with lock:
            with open(tsv, "a") as f:
                f.write(f"{fname}\t{url}#{name}\t{LIC[a.kind]}\n")
            seen.add(fname)
            counts["ok"] += 1
            print("ok", len(data) // 1024, "KB", fname, flush=True)
        time.sleep(0.3)

    with ThreadPoolExecutor(max_workers=a.jobs) as pool_:
        for z, items in sorted(todo.items()):
            url = f"{BASE}{PREFIX}{z}.zip"
            ents = zre.central_dir(url)
            list(pool_.map(lambda it: one(url, ents, *it), items))
    ok, bad = counts["ok"], counts["bad"]
    print(f"done ok={ok} skipped={bad}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
