#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pypdfium2==5.14.0", "numpy>=2", "pillow>=11"]
# ///
"""Failure probe: run corpus PDFs through PDFium and the current viewer.

For each manifest row it writes <corpus>/probe/<sha256>.json with the PDFium
facts, the conversion outcome, the visual comparison of sampled pages and a
list of failure classes. See bench/corpus/README.md ("Probe usage") for the
sampling policy, thresholds and classes.

Usage:
    uv run bench/corpus/probe/probe.py [--jobs 4] [--source NAME] [--label L]
        [--sha PREFIX ...] [--per-source N] [--limit N] [--force] [--keep-work] [--work DIR]
        [--corpus DIR] [--save-all]

Resumable: a document whose probe JSON already exists for the current
pipeline (probe code, pdf2htmlEX and overlay versions) is skipped unless
--force. Untrusted PDFs are only opened in child processes: `python -I`
workers (PDFium), pdf2htmlEX, and headless Chromium, each with a time limit.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

PROBE_VERSION = "2"
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
WORKER = HERE / "pdfium_worker.py"
CONVERT = HERE / "convert.sh"
SHOOT = HERE / "shoot.cjs"
FIDELITY = REPO / "scripts" / "measure-text-fidelity.cjs"
NATIVE_BIN = pathlib.Path.home() / ".local/opt/pdf2htmlEX/bin/pdf2htmlEX"

# Sampling policy.
FULL_MAX_PAGES = 40            # convert the whole document up to this many pages
FULL_MAX_BYTES = 40 << 20      # ... and this file size
WINDOW_PAGES = 3               # long documents: page 1 plus a 3-page window mid-document
TIMING_PAGES = 10              # PDFium render timing on up to this many pages
FIT_WIDTH_CSS = 1600           # visual comparison at fit-width 1600 CSS px ...
DPR = 2                        # ... and device pixel ratio 2
MAX_PAGE_CSS_HEIGHT = 4000     # very tall pages get a smaller zoom

# Time limits (seconds).
T_INFO, T_CONVERT, T_LIGHT, T_SHOOT, T_COMPARE, T_FIDELITY = 120, 300, 240, 240, 240, 300

# Thresholds; calibration is described in the README.
INK_DARK = 128                 # luma below this is ink
INK_RADIUS = 2                 # device px of tolerance (1 CSS px at DPR 2)
VISUAL = {"extra": 0.03, "missing": 0.03, "block_diff": 0.02}   # above: page fails (diff images saved)
VISUAL_HIGH = 0.15             # extra or missing above this: visual-diff-high; between: glyph-drift
BLUR_FAINT = 0.8               # share of missing ink with faint viewer ink nearby: raster-blur
GHOST_RATE_MAX = 0.003         # same limits as scripts/tests/test_text_fidelity.py
OCCLUSION_MAX = 0.01
LINE_BOX_EM_MAX = 1.4
SLOW_RENDER_MS = 1000          # PDFium render of one page at 3200 px wide
TEXT_LOSS_RATIO = 0.5          # HTML keeps less than half of PDFium's characters
SIZE_DELTA_PX = 4              # page box differs from PDFium's by more than this

PROGRESS_NOISE = re.compile(r"^(Preprocessing|Working): \d+/\d+$")


def corpus_dir(arg):
    raw = arg or os.environ.get("PDFV_CORPUS_DIR") or "~/.local/share/pdf_viewer/corpus"
    return pathlib.Path(raw).expanduser()


def playwright_node_path() -> str | None:
    default = pathlib.Path.home() / ".npm/_npx/705bc6b22212b352/node_modules"
    if (default / "playwright").is_dir():
        return str(default)
    for base in (pathlib.Path.home() / ".npm/_npx", pathlib.Path.home() / "Library/Caches"):
        for p in base.glob("*/node_modules/playwright"):
            return str(p.parent)
    return None


def run(cmd, timeout, env=None, cwd=None):
    """Run a child in its own process group; kill the group on timeout."""
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            env=env, cwd=cwd, start_new_session=True, text=True, errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        timed_out = True
    return {"rc": proc.returncode, "out": out, "err": err, "timeout": timed_out,
            "seconds": round(time.monotonic() - t0, 2)}


def last_json(text: str):
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def pipeline_versions() -> dict:
    v = {"probe": PROBE_VERSION}
    r = run([str(NATIVE_BIN), "--version"], 30)
    v["pdf2htmlex"] = (r["out"] + r["err"]).strip().splitlines()[0] if (r["out"] + r["err"]).strip() else None
    r = run(["uv", "run", str(REPO / "scripts/inject-overlay.py"), "--print-version"], 120)
    v["overlay"] = r["out"].strip() or None
    return v


def plan_sampling(n: int | None, nbytes: int) -> dict:
    """Which pages to convert and which to compare."""
    if not n:
        return {"mode": "full-unknown-pages", "units": [[1, None]], "sample_pages": [1]}
    if n <= FULL_MAX_PAGES and nbytes <= FULL_MAX_BYTES:
        return {"mode": "full", "units": [[1, n]], "sample_pages": sorted({1, (n + 1) // 2, n})}
    m = max(2, n // 2)
    last = min(n, m + WINDOW_PAGES - 1)
    return {"mode": "windows", "units": [[1, 1], [m, last]], "sample_pages": sorted({1, m, last})}


def timing_pages(n: int, samples: list[int]) -> list[int]:
    if n <= TIMING_PAGES:
        return list(range(1, n + 1))
    spread = {1 + round(i * (n - 1) / (TIMING_PAGES - 1)) for i in range(TIMING_PAGES)}
    return sorted(spread | set(samples))


def summarize_log(text: str) -> dict:
    """Converter warnings by kind; covered-text desync counted separately."""
    kinds: dict[str, int] = {}
    desync = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or PROGRESS_NOISE.match(line) or line.startswith("["):
            continue
        if "covered-text desync" in line:
            desync += 1
            continue
        key = re.sub(r"0x[0-9a-fA-F]+|\d+(\.\d+)?", "#", line)[:160]
        kinds[key] = kinds.get(key, 0) + 1
    top = sorted(kinds.items(), key=lambda kv: -kv[1])[:12]
    return {"desync": desync, "warning_lines": sum(kinds.values()), "warnings": dict(top)}


class Prober:
    def __init__(self, root: pathlib.Path, work: pathlib.Path, versions: dict, args):
        self.root, self.work, self.versions, self.args = root, work, versions, args
        self.out_dir = root / "probe"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.node_path = playwright_node_path()
        self.python = sys.executable

    def worker(self, mode, pdf, spec, wdir, timeout):
        spec_path = wdir / f"{mode}-spec.json"
        spec_path.write_text(json.dumps(spec))
        r = run([self.python, "-I", str(WORKER), mode, str(pdf), str(spec_path)], timeout)
        res = last_json(r["out"]) if not r["timeout"] else None
        if res is None:
            res = {"worker_error": "timeout" if r["timeout"] else f"exit {r['rc']}: {r['err'].strip()[-300:]}"}
        res["seconds"] = r["seconds"]
        return res

    def probe(self, row: dict) -> dict:
        sha = row["sha256"]
        pdf_src = self.root / "files" / sha[:2] / f"{sha}.pdf"
        wdir = self.work / sha[:16]
        shutil.rmtree(wdir, ignore_errors=True)
        wdir.mkdir(parents=True)
        t0 = time.monotonic()
        result = {"sha256": sha, "pipeline": self.versions, "doc": doc_facts(row),
                  "started_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            self._probe(row, pdf_src, wdir, result)
        except Exception as exc:  # probe bug: record it rather than lose the run
            result["probe_error"] = f"{type(exc).__name__}: {exc}"[:500]
        result["seconds"] = round(time.monotonic() - t0, 1)
        classify(result)
        tmp = self.out_dir / f".{sha}.json.tmp"
        tmp.write_text(json.dumps(result, indent=1))
        os.replace(tmp, self.out_dir / f"{sha}.json")
        if not self.args.keep_work:
            shutil.rmtree(wdir, ignore_errors=True)
        return result

    def _probe(self, row, pdf_src, wdir, result):
        # The converter names its output after the input file: link a neutral name.
        pdf = wdir / "doc.pdf"
        os.symlink(pdf_src, pdf)

        n = row.get("pages")
        plan = plan_sampling(n, row.get("bytes", 0))
        samples = plan["sample_pages"]
        info = self.worker("info", pdf, {"sample_pages": samples,
                                         "timing_pages": timing_pages(n, samples) if n else [1]},
                           wdir, T_INFO)
        result["pdfium"] = info
        sizes = info.get("page_sizes") or []
        if sizes and len(sizes) != n:
            n = len(sizes)
            plan = plan_sampling(n, row.get("bytes", 0))
            samples = plan["sample_pages"]
        result["policy"] = plan

        cache = wdir / "cache"
        env = dict(os.environ, PDF_VIEWER_CACHE_DIR=str(cache))
        log = cache / "log"
        units = []
        result["convert"] = units
        artifacts = self.root / "probe" / "artifacts" / row["sha256"]
        shutil.rmtree(artifacts, ignore_errors=True)
        visual_jobs = []
        for index, (first, last) in enumerate(plan["units"]):
            hash_ = row["sha256"][:15] + format(index, "x")
            out_dir = cache / hash_
            unit = {"first": first, "last": last}
            units.append(unit)
            start = log.stat().st_size if log.exists() else 0
            cmd = ["bash", str(CONVERT), "convert", str(pdf), str(out_dir)]
            if last is not None and plan["mode"] != "full":
                cmd += [str(first), str(last)]
            r = run(cmd, T_CONVERT, env=env)
            unit.update(rc=r["rc"], seconds=r["seconds"], timeout=r["timeout"])
            if r["err"].strip():
                unit["stderr"] = r["err"].strip()[-500:]
            unit.update(summarize_log(read_from(log, start)))
            canonical = out_dir / "doc.html"
            if r["rc"] != 0 or r["timeout"] or not canonical.exists():
                unit["html"] = False
                continue
            unit["html_bytes"] = canonical.stat().st_size
            unit["html_pages"] = count_pages(canonical)
            if last is not None:
                unit["expected_pages"] = last - first + 1
            start = log.stat().st_size
            r = run(["bash", str(CONVERT), "light", str(out_dir), "doc.html", hash_, "doc"], T_LIGHT, env=env)
            light = out_dir / "doc.light.html"
            unit["light"] = {"rc": r["rc"], "seconds": r["seconds"], "timeout": r["timeout"],
                             "ok": r["rc"] == 0 and not r["timeout"] and light.exists()}
            tail = [l for l in read_from(log, start).splitlines() if "fail" in l.lower() or "error" in l.lower()]
            if tail:
                unit["light"]["log"] = tail[-5:]
            if light.exists():
                unit["light"]["bytes"] = light.stat().st_size
            unit_samples = [p for p in samples if first <= p <= (last or p)]
            if not unit_samples:
                continue
            if self.node_path and not self.args.no_fidelity:
                positions = [str(p - first + 1) for p in unit_samples]
                r = run(["node", str(FIDELITY), str(canonical), "--pages", ",".join(positions)], T_FIDELITY,
                        env=dict(os.environ, NODE_PATH=self.node_path))
                fid = last_json(r["out"]) if r["rc"] == 0 else None
                unit["fidelity"] = ({"totals": fid["totals"],
                                     "pages": [{k: p[k] for k in ("page", "glyphs", "ghosts", "ghostSample",
                                                                 "occlusion", "lineBoxEm")} for p in fid["pages"]]}
                                    if fid else {"error": ("timeout" if r["timeout"] else r["err"].strip()[-300:]),
                                                 "seconds": r["seconds"]})
            if not unit["light"]["ok"] or not self.node_path or not sizes:
                continue
            # Viewer screenshots of the sampled pages at fit-width, DPR 2.
            dims = [sizes[p - 1] for p in unit_samples if p - 1 < len(sizes) and min(sizes[p - 1]) > 1]
            if not dims:
                continue
            max_w = max(d[0] for d in dims)
            max_h = max(d[1] for d in dims)
            zoom = min(FIT_WIDTH_CSS / max_w, MAX_PAGE_CSS_HEIGHT / max_h, 10.0)
            zoom = max(zoom, 0.25)
            vw = int(max_w * zoom) + 100
            # Page margins are zoomed with the page (zoom sits on .pf), so leave room for them.
            vh = int(max_h * zoom + 60 * zoom) + 100
            shots = wdir / f"shots-{index}"
            r = run(["node", str(SHOOT), str(cache), f"/{hash_}/doc.light.html", str(shots),
                     "--zoom", f"{zoom:.6f}", "--pages", ",".join(map(str, unit_samples)),
                     "--viewport", f"{vw}x{vh}", "--dpr", str(DPR)], T_SHOOT,
                    env=dict(os.environ, NODE_PATH=self.node_path))
            shot = last_json(r["out"]) or {"fatal": "timeout" if r["timeout"] else r["err"].strip()[-300:]}
            shot["seconds"] = r["seconds"]
            unit["viewer"] = {k: shot.get(k) for k in ("fatal", "pageCount", "representation", "zoom", "loadMs",
                                                      "totalMs", "consoleErrors", "failedRequests",
                                                      "abortedRequests", "zoomNotApplied", "seconds")
                              if shot.get(k) is not None}
            unit["viewer"]["pages"] = [{k: v for k, v in p.items() if k != "file"} for p in shot.get("pages", [])]
            for p in shot.get("pages", []):
                if p.get("clipped"):
                    unit["viewer"].setdefault("clipped_pages", []).append(p["page"])
                    continue
                if p.get("file"):
                    visual_jobs.append({"page": p["page"], "shot": p["file"], "scale": zoom * DPR,
                                        "artifacts": str(artifacts), "html_chars": p.get("htmlChars")})
        if visual_jobs and not info.get("open_error") and "worker_error" not in info:
            cmp = self.worker("compare", pdf, {"jobs": visual_jobs, "thresholds": VISUAL, "dark": INK_DARK,
                                               "radius": INK_RADIUS, "save_all": self.args.save_all},
                              wdir, T_COMPARE)
            per_page = (info.get("text") or {}).get("per_sample_page") or {}
            for page in cmp.get("pages", []):
                job = next(j for j in visual_jobs if j["page"] == page["page"])
                page["html_chars"] = job["html_chars"]
                page["pdfium_chars"] = per_page.get(str(page["page"]))
            result["visual"] = cmp


def read_from(path: pathlib.Path, offset: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


PF_RE = re.compile(rb'<div[^>]*\bid="pf[0-9a-f]+"')


def count_pages(html: pathlib.Path) -> int:
    import mmap
    with open(html, "rb") as f:
        if os.fstat(f.fileno()).st_size == 0:
            return 0
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            return sum(1 for _ in PF_RE.finditer(m))


def doc_facts(row: dict) -> dict:
    """Manifest facts that the class rules use."""
    return {"nonembedded_fonts": (row.get("fonts") or {}).get("nonembedded", 0)}


def classify(r: dict) -> None:
    classes: list[str] = []
    notes: list[str] = []
    info = r.get("pdfium") or {}
    if r.get("probe_error"):
        classes.append("probe-error")
    if info.get("open_error") or info.get("worker_error") or info.get("errors"):
        classes.append("pdfium-error")
    renders = info.get("renders") or []
    slow = [x for x in renders if x.get("ms", 0) > SLOW_RENDER_MS]
    if slow:
        classes.append("pdfium-slow-page")
        notes.append(f"slowest render {max(x['ms'] for x in slow):.0f} ms on p{max(slow, key=lambda x: x['ms'])['page']}")
    text = info.get("text") or {}
    if text.get("pages") and text.get("chars", 0) == 0:
        classes.append("no-text")
    units = r.get("convert") or []
    for u in units:
        if u.get("timeout"):
            classes.append("convert-timeout")
        elif any("is not allowed" in w for w in u.get("warnings", {})):
            classes.append("convert-refused")   # pdf2htmlEX honours the copy restriction of encrypted PDFs
        elif u.get("rc") not in (0, None) or u.get("html") is False:
            classes.append("convert-crash")
        if u.get("desync"):
            classes.append("covered-text-desync")
        if u.get("expected_pages") is not None and u.get("html_pages") is not None \
                and u["html_pages"] != u["expected_pages"]:
            classes.append("page-count-mismatch")
        light = u.get("light")
        if light is not None and not light.get("ok"):
            classes.append("light-build-failed")
        fid = (u.get("fidelity") or {}).get("totals")
        if fid:
            if fid.get("ghostRate", 0) > GHOST_RATE_MAX:
                classes.append("ghost-glyphs")
            if fid.get("maxOcclusion", 0) > OCCLUSION_MAX:
                classes.append("selection-occlusion")
            if fid.get("maxLineBoxEm", 0) > LINE_BOX_EM_MAX:
                classes.append("tall-line-box")
        viewer = u.get("viewer")
        if viewer is not None:
            bad = viewer.get("fatal") or any(not p.get("found") or p.get("error")
                                             or p.get("rasterState") in ("timeout", "error")
                                             for p in viewer.get("pages", []))
            if bad:
                classes.append("viewer-load-failed")
            # Pages that could not be captured (for example a zero-width page)
            # are still checked against PDFium's size from their layout box.
            sizes = info.get("page_sizes") or []
            try:
                zoom = float(viewer.get("zoom") or 0)
            except ValueError:
                zoom = 0
            for p in viewer.get("pages", []):
                rect, n = p.get("rect"), p.get("page")
                if p.get("error") and rect and zoom and n and n <= len(sizes) and min(sizes[n - 1]) > 1:
                    if (abs(rect["width"] - sizes[n - 1][0] * zoom) > 2
                            or abs(rect["height"] - sizes[n - 1][1] * zoom) > 2):
                        classes.append("page-size-mismatch")
            if viewer.get("clipped_pages"):
                classes.append("probe-error")   # page did not fit the viewport; not compared
    if units and units[0].get("expected_pages") is None and info.get("pages") and units[0].get("html_pages") \
            and units[0]["html_pages"] != info["pages"]:
        classes.append("page-count-mismatch")
    worst = None
    for p in (r.get("visual") or {}).get("pages", []):
        if p.get("error"):
            classes.append("probe-error")
            continue
        blur = (p["missing"] > VISUAL["missing"] and p.get("missing_faint", 0) >= BLUR_FAINT
                and p["extra"] <= VISUAL["extra"])
        if blur:
            classes.append("raster-blur")
        elif max(p["extra"], p["missing"]) > VISUAL_HIGH or p["block_diff"] > VISUAL["block_diff"]:
            classes.append("visual-diff-high")
        elif max(p["extra"], p["missing"]) > max(VISUAL["extra"], VISUAL["missing"]):
            # With non-embedded fonts, Chromium and PDFium substitute different
            # local fonts: a different typeface, often shifted by its ascent.
            classes.append("font-substitution" if (r.get("doc") or {}).get("nonembedded_fonts")
                           else "glyph-drift")
        if p["ink_ref"] >= 2000 and p["ink_html"] < 0.05 * p["ink_ref"]:
            classes.append("blank-page")
        if max(abs(d) for d in p["size_delta"]) > SIZE_DELTA_PX:
            classes.append("page-size-mismatch")
        pc, hc = p.get("pdfium_chars"), p.get("html_chars")
        if pc is not None and hc is not None and pc >= 50 and hc < TEXT_LOSS_RATIO * pc:
            classes.append("text-loss")
        score = max(p["extra"], p["missing"])
        if worst is None or score > worst[0]:
            worst = (score, p)
    r["classes"] = sorted(set(classes))
    pages = info.get("pages") or "?"
    conv = "; ".join(
        f"p{u['first']}-{u['last'] if u['last'] is not None else 'end'} "
        + ("timeout" if u.get("timeout") else f"rc {u.get('rc')}") + f" {u.get('seconds', 0):.1f}s"
        + (f" light {'ok' if u['light'].get('ok') else 'FAILED'}" if u.get("light") else "")
        for u in units)
    parts = [f"{pages} pages", (r.get("policy") or {}).get("mode", "?"), conv or "not converted"]
    if worst:
        p = worst[1]
        parts.append(f"worst p{p['page']} extra {p['extra']:.3f} missing {p['missing']:.3f} blocks {p['block_diff']:.3f}")
    parts += notes
    r["summary"] = ("FAIL " + ",".join(r["classes"]) if r["classes"] else "ok") + " | " + " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus")
    ap.add_argument("--work", default=os.environ.get("PDFV_PROBE_WORK"),
                    help="scratch dir for conversions (default $PDFV_PROBE_WORK or $TMPDIR/pdfv-probe-work)")
    ap.add_argument("--jobs", type=int, default=4, help="documents in parallel (default 4, max 6)")
    ap.add_argument("--source", action="append", help="only rows with this source")
    ap.add_argument("--label", action="append", help="only rows with this label")
    ap.add_argument("--sha", action="append", help="only rows whose sha256 starts with this")
    ap.add_argument("--limit", type=int, help="probe at most N documents")
    ap.add_argument("--per-source", type=int, help="at most N documents per source (by sha256 order)")
    ap.add_argument("--per-label", type=int, help="at most N documents per (source, first label)")
    ap.add_argument("--max-pages", type=int, help="skip documents with more pages")
    ap.add_argument("--force", action="store_true", help="re-probe documents that already have a result")
    ap.add_argument("--keep-work", action="store_true", help="keep scratch conversions")
    ap.add_argument("--save-all", action="store_true", help="save diff images for every page, not only failing ones")
    ap.add_argument("--reclassify", action="store_true", help="recompute classes of stored results only")
    ap.add_argument("--no-fidelity", action="store_true", help="skip the ghost/occlusion harness")
    args = ap.parse_args()

    root = corpus_dir(args.corpus)
    work = pathlib.Path(args.work or pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "pdfv-probe-work").expanduser()
    if str(work.resolve()).startswith(str((pathlib.Path.home() / ".cache/pdf_viewer").resolve())):
        print("probe: --work must not be inside ~/.cache/pdf_viewer", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in (root / "manifest.jsonl").read_text().splitlines() if l.strip()]
    if args.source:
        rows = [r for r in rows if any(s["source"] in args.source for s in r["sources"])]
    if args.label:
        rows = [r for r in rows if set(args.label) & set(r.get("labels", []))]
    if args.sha:
        rows = [r for r in rows if any(r["sha256"].startswith(s) for s in args.sha)]
    if args.max_pages:
        rows = [r for r in rows if (r.get("pages") or 0) <= args.max_pages]
    if args.reclassify:
        # Re-apply classify() to stored results (after a threshold change); nothing is re-run.
        n = 0
        for r in rows:
            path = root / "probe" / f"{r['sha256']}.json"
            if path.exists():
                res = json.loads(path.read_text())
                res["doc"] = doc_facts(r)
                classify(res)
                tmp = path.with_name(f".{path.name}.tmp")
                tmp.write_text(json.dumps(res, indent=1))
                os.replace(tmp, path)
                n += 1
        print(f"probe: reclassified {n} results")
        return 0
    versions = pipeline_versions()
    todo = []
    for r in rows:
        out = root / "probe" / f"{r['sha256']}.json"
        if out.exists() and not args.force:
            try:
                if json.loads(out.read_text()).get("pipeline") == versions:
                    continue
            except (json.JSONDecodeError, OSError):
                pass
        todo.append(r)
    if args.per_source or args.per_label:
        # Deterministic stratified pick: the first N rows by sha256 per primary
        # source (or per (source, first label) with --per-label).
        picked, seen = [], {}
        cap = args.per_label or args.per_source
        for r in sorted(todo, key=lambda r: r["sha256"]):
            src = r["sources"][0]["source"]
            if args.per_label:
                src = (src, (r.get("labels") or [""])[0])
            if seen.get(src, 0) < cap:
                seen[src] = seen.get(src, 0) + 1
                picked.append(r)
        todo = picked
    if args.limit is not None:
        todo = todo[:args.limit]
    prober = Prober(root, work, versions, args)
    if not prober.node_path:
        print("probe: no cached Playwright found; viewer screenshots are skipped", file=sys.stderr)
    print(f"probe: {len(todo)} to probe ({len(rows) - len(todo)} already done for {versions})", flush=True)
    t0 = time.monotonic()
    done = 0
    lock = threading.Lock()
    with cf.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 6))) as pool:
        futures = {pool.submit(prober.probe, r): r for r in todo}
        for fut in cf.as_completed(futures):
            row = futures[fut]
            try:
                res = fut.result()
                line = res["summary"]
            except Exception as exc:
                line = f"probe crashed: {exc}"
            with lock:
                done += 1
                name = row["sources"][0]["source"] + "/" + row["sources"][0]["filename"]
                print(f"[{done}/{len(todo)}] {row['sha256'][:12]} {name[:60]}: {line}", flush=True)
    elapsed = time.monotonic() - t0
    if todo:
        print(f"probe: {len(todo)} documents in {elapsed:.0f}s ({len(todo) / elapsed * 60:.1f} per minute)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
