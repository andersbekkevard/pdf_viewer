#!/usr/bin/env python3
"""Extract selected members of a remote ZIP with HTTP range requests.

usage:
  python3 -I zip-range-extract.py list <zip_url>                 # print name<TAB>size<TAB>csize
  python3 -I zip-range-extract.py get <zip_url> <source> <license> <name>...
Members are written to incoming/<source>/<prefix><name> (prefix from env ZIP_PREFIX)
and a row "<file>\t<zip_url>#<name>\t<license>" is appended to _files.tsv after each
file is complete. Only stored (0) and deflate (8) members are supported. Handles ZIP64.
"""
import os, struct, sys, time, zlib, urllib.request

UA = "pdfv-corpus/0.1 (personal PDF viewer test corpus; anders.bekkevard@gmail.com)"
CORPUS = os.environ.get("PDFV_CORPUS_DIR", os.path.expanduser("~/.local/share/pdf_viewer/corpus"))

def rng(url, start, end):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()

def size_of(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])

def central_dir(url):
    total = size_of(url)
    tail = rng(url, max(0, total - 65536 - 22), total - 1)
    i = tail.rfind(b"PK\x05\x06")
    (_, _, _, _, n, cd_size, cd_off, _) = struct.unpack("<IHHHHIIH", tail[i:i + 22])
    if cd_off == 0xFFFFFFFF or n == 0xFFFF:
        j = tail.rfind(b"PK\x06\x06")
        n, cd_size, cd_off = struct.unpack("<QQQ", tail[j + 32:j + 56])
    cd = rng(url, cd_off, cd_off + cd_size - 1)
    entries, p = {}, 0
    while p < len(cd) and cd[p:p + 4] == b"PK\x01\x02":
        (method, crc, csize, usize, nlen, xlen, clen) = struct.unpack("<H4xIIIHHH", cd[p + 10:p + 34])
        off = struct.unpack("<I", cd[p + 42:p + 46])[0]
        name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        extra = cd[p + 46 + nlen:p + 46 + nlen + xlen]
        q = 0
        while q + 4 <= len(extra):
            hid, hlen = struct.unpack("<HH", extra[q:q + 4])
            if hid == 1:
                vals, k = extra[q + 4:q + 4 + hlen], 0
                if usize == 0xFFFFFFFF: usize = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
                if csize == 0xFFFFFFFF: csize = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
                if off == 0xFFFFFFFF: off = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
            q += 4 + hlen
        entries[name] = (method, crc, csize, usize, off)
        p += 46 + nlen + xlen + clen
    return entries

def get(url, source, lic, names):
    ents = central_dir(url)
    out = os.path.join(CORPUS, "incoming", source)
    os.makedirs(os.path.join(out, ".part"), exist_ok=True)
    prefix = os.environ.get("ZIP_PREFIX", "")
    for name in names:
        if name not in ents:
            print("missing", name, file=sys.stderr); continue
        method, crc, csize, usize, off = ents[name]
        fname = prefix + os.path.basename(name)
        dest = os.path.join(out, fname)
        if os.path.exists(dest):
            continue
        hdr = rng(url, off, off + 29)
        nlen, xlen = struct.unpack("<HH", hdr[26:30])
        start = off + 30 + nlen + xlen
        data = rng(url, start, start + csize - 1) if csize else b""
        if method == 8:
            data = zlib.decompress(data, -15)
        elif method != 0:
            print("unsupported method", method, name, file=sys.stderr); continue
        if zlib.crc32(data) & 0xFFFFFFFF != crc:
            print("crc mismatch", name, file=sys.stderr); continue
        if b"%PDF-" not in data[:1024]:
            print("not pdf", name, file=sys.stderr); continue
        part = os.path.join(out, ".part", fname)
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, dest)
        with open(os.path.join(out, "_files.tsv"), "a") as f:
            f.write(f"{fname}\t{url}#{name}\t{lic}\n")
        print(f"ok {len(data) // 1024} KB {fname}")
        time.sleep(0.5)

if __name__ == "__main__":
    if sys.argv[1] == "list":
        for n, (m, c, cs, us, o) in central_dir(sys.argv[2]).items():
            print(f"{n}\t{us}\t{cs}")
    else:
        get(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
