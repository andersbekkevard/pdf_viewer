"""PDFium side of the probe, run as `python -I pdfium_worker.py <mode> ...`.

Corpus PDFs are untrusted, so the probe never opens them in its own process:
each call is a separate isolated interpreter with a time limit set by the
caller, and a crash only costs that call.

Modes (each prints one JSON object on stdout):

  info <pdf> <spec.json>
      Open time, page count and sizes, render time of the timing pages at
      device scale (fit-width 1600 CSS px at DPR 2 = 3200 device px wide),
      text extraction time and character count, characters per sampled page.

  compare <pdf> <spec.json>
      For each job {page, shot, scale, artifacts}: render the page at `scale`
      (device px per PDF point), compare with the viewer screenshot by extra
      and missing ink (see ink_compare), and save diff images for pages over
      the thresholds in spec["thresholds"] (one sheet per page: viewer,
    PDFium and diff side by side at quarter resolution). Diff colours: red = extra
    ink (in the viewer only), blue = missing ink (in PDFium only), orange
    tint = 16x16 blocks whose colour differs.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
import time

FIT_WIDTH_DEVICE_PX = 3200   # 1600 CSS px at DPR 2
TEXT_ALL_PAGES_MAX = 600     # extract text from every page up to this count
TEXT_TIME_BUDGET = 20.0      # seconds; stop extracting after this
MIN_FREE_BYTES = 56 * 2**30  # below this free space (56 GiB, as df -h shows), diff sheets are not saved


def open_doc(path):
    import pypdfium2 as pdfium
    t0 = time.perf_counter()
    doc = pdfium.PdfDocument(path)
    try:
        doc.init_forms()
    except Exception:
        pass
    return doc, (time.perf_counter() - t0) * 1000


def mode_info(pdf: str, spec: dict) -> dict:
    out: dict = {"errors": []}
    try:
        doc, open_ms = open_doc(pdf)
    except Exception as exc:
        return {"open_error": str(exc)[:300]}
    n = len(doc)
    t0 = time.perf_counter()
    sizes = []
    for i in range(n):
        try:
            page = doc[i]
            w, h = page.get_size()
            page.close()
        except Exception as exc:
            out["errors"].append(f"page {i + 1} size: {exc}"[:200])
            w, h = 0.0, 0.0
        sizes.append([round(w, 2), round(h, 2)])
    out["open_ms"] = round(open_ms, 1)
    out["sizes_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["pages"] = n
    out["page_sizes"] = sizes

    renders = []
    for p in spec.get("timing_pages", []):
        if not 1 <= p <= n:
            continue
        entry = {"page": p}
        try:
            page = doc[p - 1]
            w, h = page.get_size()
            scale = FIT_WIDTH_DEVICE_PX / max(w, 1e-3)
            t1 = time.perf_counter()
            bitmap = page.render(scale=scale, may_draw_forms=True)
            entry["ms"] = round((time.perf_counter() - t1) * 1000, 1)
            entry["px"] = [bitmap.width, bitmap.height]
            bitmap.close()
            page.close()
        except Exception as exc:
            entry["error"] = str(exc)[:200]
            out["errors"].append(f"page {p} render: {exc}"[:200])
        renders.append(entry)
    out["renders"] = renders

    wanted = set(spec.get("sample_pages", []))
    extract = range(1, n + 1) if n <= TEXT_ALL_PAGES_MAX else sorted(wanted | set(spec.get("timing_pages", [])))
    chars = 0
    done = 0
    per_page = {}
    t2 = time.perf_counter()
    for p in extract:
        if not 1 <= p <= n:
            continue
        if time.perf_counter() - t2 > TEXT_TIME_BUDGET:
            out["text_truncated"] = True
            break
        try:
            page = doc[p - 1]
            tp = page.get_textpage()
            text = tp.get_text_range()
            tp.close()
            page.close()
        except Exception as exc:
            out["errors"].append(f"page {p} text: {exc}"[:200])
            continue
        c = len(re.sub(r"\s+", "", text))
        chars += c
        done += 1
        if p in wanted:
            per_page[str(p)] = c
    for p in wanted:  # sampled pages outside the extracted range (should not happen)
        per_page.setdefault(str(p), None)
    out["text"] = {"ms": round((time.perf_counter() - t2) * 1000, 1), "pages": done, "chars": chars,
                   "per_sample_page": per_page}
    doc.close()
    return out


# --------------------------------------------------------------------------
# Visual comparison
# --------------------------------------------------------------------------

def dilate(mask, r):
    """Square dilation of a boolean mask by r pixels (separable, no wraparound)."""
    import numpy as np
    if r <= 0:
        return mask.copy()
    out = mask.copy()
    for s in range(1, r + 1):
        out[s:, :] |= mask[:-s, :]
        out[:-s, :] |= mask[s:, :]
    tmp = out.copy()
    for s in range(1, r + 1):
        out[:, s:] |= tmp[:, :-s]
        out[:, :-s] |= tmp[:, s:]
    return out


def erode(mask, r):
    return ~dilate(~mask, r)


def ink_compare(shot_rgb, ref_rgb, dark: int, radius: int):
    """Extra and missing ink between a viewer screenshot and a PDFium render.

    Glyph rasterization differs between Chromium and PDFium at every edge, so
    a pixel diff is useless. Instead: a pixel is ink when its luma is below
    `dark`. Extra ink is screenshot ink with no reference ink within `radius`
    device px; missing ink is reference ink with no screenshot ink within
    `radius`. A 3x3 opening (erode then dilate) then drops one-pixel slivers,
    so what remains is structure: a stroke, glyph or rule that is in one image
    and not the other. A block metric adds colour: the share of 16x16 device px
    blocks whose mean colour differs by more than 48 levels in some channel.
    """
    import numpy as np
    h = min(shot_rgb.shape[0], ref_rgb.shape[0])
    w = min(shot_rgb.shape[1], ref_rgb.shape[1])
    a = shot_rgb[:h, :w].astype(np.int32)
    b = ref_rgb[:h, :w].astype(np.int32)
    luma = lambda x: (x[..., 0] * 299 + x[..., 1] * 587 + x[..., 2] * 114) // 1000
    la, lb = luma(a), luma(b)
    da, db = la < dark, lb < dark
    near_a, near_b = dilate(da, radius), dilate(db, radius)
    extra = da & ~near_b
    missing = db & ~near_a
    extra_o = dilate(erode(extra, 1), 1) & extra
    missing_o = dilate(erode(missing, 1), 1) & missing
    # Missing ink with faint viewer ink nearby (luma < 200 within radius) is
    # a lighter, blurred copy of the stroke, not absent content.
    faint_a = dilate(la < 200, radius)
    missing_faint = int((missing_o & faint_a).sum())
    area = h * w
    ink_a, ink_b = int(da.sum()), int(db.sum())
    floor = max(area * 0.002, 1.0)
    bs = 16
    hb, wb = h // bs, w // bs
    if hb and wb:
        ma = a[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs, 3).mean(axis=(1, 3))
        mb = b[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs, 3).mean(axis=(1, 3))
        blocks = np.abs(ma - mb).max(axis=2) > 48
        block = float(blocks.mean())
    else:
        blocks = np.zeros((0, 0), dtype=bool)
        block = 0.0
    metrics = {
        "size": [w, h],
        "size_delta": [int(shot_rgb.shape[1] - ref_rgb.shape[1]), int(shot_rgb.shape[0] - ref_rgb.shape[0])],
        "ink_html": ink_a,
        "ink_ref": ink_b,
        "extra_px": int(extra_o.sum()),
        "missing_px": int(missing_o.sum()),
        "extra": round(int(extra_o.sum()) / max(ink_b, floor), 5),
        "missing": round(int(missing_o.sum()) / max(ink_b, floor), 5),
        "block_diff": round(block, 5),
        "missing_faint": round(missing_faint / max(int(missing_o.sum()), 1), 4),
    }
    return metrics, extra_o, missing_o, blocks


def save_artifacts(prefix: pathlib.Path, shot_img, ref_img, extra, missing, blocks):
    import numpy as np
    from PIL import Image
    h, w = extra.shape
    ref = np.asarray(ref_img.convert("L"))[:h, :w].astype(np.float32)
    base = 255 - (255 - ref) * 0.35
    rgb = np.stack([base, base, base], axis=-1).astype(np.uint8)
    # Colour blocks that differ: orange tint (under the ink marks).
    if blocks.size:
        bmask = np.kron(blocks, np.ones((16, 16), dtype=bool))
        full = np.zeros((h, w), dtype=bool)
        full[:bmask.shape[0], :bmask.shape[1]] = bmask
        rgb[full] = (rgb[full] * 0.5 + np.array([255, 170, 0]) * 0.5).astype(np.uint8)
    # Thicken marks so they stay visible after the 4x downscale.
    rgb[dilate(extra, 2)] = (220, 0, 0)
    rgb[dilate(missing, 2)] = (0, 70, 230)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # One sheet per page to bound disk use: viewer | PDFium | diff, each at a
    # quarter of device resolution (800 px wide for a fit-width page).
    q = lambda im: im.resize((max(1, im.width // 4), max(1, im.height // 4)), Image.LANCZOS)
    panels = [q(shot_img.convert("RGB")), q(ref_img.convert("RGB")), q(Image.fromarray(rgb))]
    gap = 6
    sheet = Image.new("RGB", (sum(p.width for p in panels) + 2 * gap, max(p.height for p in panels)), (128, 128, 128))
    x = 0
    for panel in panels:
        sheet.paste(panel, (x, 0))
        x += panel.width + gap
    sheet.save(f"{prefix}-sheet.jpg", quality=80, optimize=True)


def mode_compare(pdf: str, spec: dict) -> dict:
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 400_000_000
    th = spec["thresholds"]
    try:
        doc, _ = open_doc(pdf)
    except Exception as exc:
        return {"open_error": str(exc)[:300]}
    results = []
    for job in spec["jobs"]:
        entry = {"page": job["page"]}
        try:
            shot_img = Image.open(job["shot"]).convert("RGB")
            page = doc[job["page"] - 1]
            t0 = time.perf_counter()
            bitmap = page.render(scale=job["scale"], may_draw_forms=True)
            entry["render_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            ref_img = bitmap.to_pil().convert("RGB")
            bitmap.close()
            page.close()
            metrics, extra, missing, blocks = ink_compare(np.asarray(shot_img), np.asarray(ref_img),
                                                  spec.get("dark", 128), spec.get("radius", 2))
            entry.update(metrics)
            failing = (metrics["extra"] > th["extra"] or metrics["missing"] > th["missing"]
                       or metrics["block_diff"] > th["block_diff"])
            low_disk = shutil.disk_usage(pathlib.Path.home()).free < MIN_FREE_BYTES
            if (failing or spec.get("save_all")) and low_disk:
                entry["artifacts_skipped"] = "low disk"
            elif failing or spec.get("save_all"):
                prefix = pathlib.Path(job["artifacts"]) / f"p{job['page']}"
                save_artifacts(prefix, shot_img, ref_img, extra, missing, blocks)
                entry["artifacts"] = f"{prefix}-sheet.jpg"
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        results.append(entry)
    doc.close()
    return {"pages": results}


def main() -> int:
    mode, pdf, spec_path = sys.argv[1], sys.argv[2], sys.argv[3]
    spec = json.loads(pathlib.Path(spec_path).read_text())
    if mode == "info":
        result = mode_info(pdf, spec)
    elif mode == "compare":
        result = mode_compare(pdf, spec)
    else:
        raise SystemExit(f"unknown mode {mode}")
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
