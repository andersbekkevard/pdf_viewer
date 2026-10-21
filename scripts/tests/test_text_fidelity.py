"""Text-layer fidelity of real pdf2htmlEX conversions.

Two defect classes, both measured from rendered pixels by
scripts/measure-text-fidelity.cjs (see docs/verification.md):

* ghosts: a glyph drawn both into the page raster and as opaque HTML text, so
  it shows doubled a pixel or two apart. Caused by covered-text bookkeeping
  drifting out of step when a page mixes Type 3 fonts with real text.
* oversized line boxes: a font whose declared ascent/descent is far beyond the
  glyphs it draws gets a line box up to 3.7 em tall; each line's selection
  highlight then floats above its text and paints over the line before it.

The committed fixtures always run when the native binary and a cached
Playwright exist. The local corpus (test/corpus-text-fidelity.tsv) runs with
PDF_VIEWER_TEXT_CORPUS=1 and prints a pass/fail table by split and class.
PDF2HTMLEX_BIN and PDF2HTMLEX_DATA_DIR point the suite at another build.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
MEASURE = REPO / "scripts" / "measure-text-fidelity.sh"
MANIFEST = REPO / "test" / "corpus-text-fidelity.tsv"
FIXTURES = REPO / "test" / "fixtures"
PREFIX = pathlib.Path.home() / ".local" / "opt" / "pdf2htmlEX"
BIN = pathlib.Path(os.environ.get("PDF2HTMLEX_BIN", PREFIX / "bin" / "pdf2htmlEX"))
DATA_DIR = pathlib.Path(os.environ.get("PDF2HTMLEX_DATA_DIR", PREFIX / "share" / "pdf2htmlEX"))
POPPLER_DATA = pathlib.Path("/opt/homebrew/share/poppler")

# Share of opaque HTML glyphs that may coincide with raster ink. Legitimate
# overlap (a rule through a word, a Type 3 bracket touching its neighbour)
# stays well below this; a desynchronised page doubles 5-15% of its glyphs.
GHOST_RATE_MAX = 0.003
# Share of text ink a full-page selection may paint over.
OCCLUSION_MAX = 0.01
# Tallest line box (= selection highlight) in ems. Text fonts need about
# 1.0-1.2; the converter clamps ascent to 1.0 and descent to 0.35.
LINE_BOX_EM_MAX = 1.4

FIXTURE_CASES = [
    ("text-fidelity/dvips_type3.pdf", "1"),
    ("text-fidelity/latex_bigdelims.pdf", "1"),
    ("text-fidelity/reportlab_base14.pdf", "1"),
    ("basic_text.pdf", "1"),
]


def tooling_missing():
    if not BIN.exists():
        return f"native pdf2htmlEX not installed at {BIN}"
    probe = subprocess.run([str(MEASURE), "--probe"], capture_output=True, text=True)
    if probe.returncode == 2:
        return "no cached Playwright for the text-fidelity harness"
    return None


def page_range(spec):
    first, _, last = spec.partition("-")
    return int(first), int(last or first)


def measure(pdf, pages):
    """Convert `pages` of `pdf` with the native binary and measure the HTML."""
    first, last = page_range(pages)
    with tempfile.TemporaryDirectory() as out:
        convert = subprocess.run(
            [str(BIN), "--data-dir", str(DATA_DIR), "--poppler-data-dir", str(POPPLER_DATA),
             "-f", str(first), "-l", str(last), "--dest-dir", out, str(pdf), "doc.html"],
            capture_output=True, text=True, timeout=300,
        )
        if convert.returncode != 0:
            raise AssertionError(f"pdf2htmlEX failed on {pdf}: {convert.stderr[-2000:]}")
        result = subprocess.run(
            [str(MEASURE), str(pathlib.Path(out) / "doc.html")],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            raise AssertionError(f"harness failed on {pdf}: {result.stderr[-2000:]}")
        metrics = json.loads(result.stdout)
        metrics["converterLog"] = convert.stderr
        return metrics


def violations(metrics):
    totals = metrics["totals"]
    found = []
    if totals["ghostRate"] > GHOST_RATE_MAX:
        worst = max(metrics["pages"], key=lambda p: p["ghosts"])
        found.append(f"ghost glyphs {totals['ghosts']}/{totals['glyphs']} "
                     f"({totals['ghostRate']:.1%}), e.g. {worst['ghostSample']!r} on {worst['page']}")
    if totals["maxOcclusion"] > OCCLUSION_MAX:
        found.append(f"selection hides {totals['maxOcclusion']:.1%} of text ink")
    if totals["maxLineBoxEm"] > LINE_BOX_EM_MAX:
        found.append(f"line box {totals['maxLineBoxEm']:.2f} em")
    if "covered-text desync" in metrics["converterLog"]:
        found.append("converter reported a covered-text desync")
    return found


class FixtureTextFidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = tooling_missing()
        if reason:
            raise unittest.SkipTest(reason)

    def test_fixtures_paint_each_glyph_once_and_select_cleanly(self):
        for name, pages in FIXTURE_CASES:
            with self.subTest(fixture=name):
                self.assertEqual(violations(measure(FIXTURES / name, pages)), [])


def corpus_entries():
    for line in MANIFEST.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        split, klass, pages, raw = line.split("\t")
        path = pathlib.Path(os.path.expanduser(raw))
        yield split, klass, pages, path if path.is_absolute() else REPO / path


@unittest.skipUnless(os.environ.get("PDF_VIEWER_TEXT_CORPUS") == "1",
                     "set PDF_VIEWER_TEXT_CORPUS=1 to run the local corpus")
class CorpusTextFidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = tooling_missing()
        if reason:
            raise unittest.SkipTest(reason)

    def test_corpus(self):
        rows = []
        for split, klass, pages, path in corpus_entries():
            if not path.exists():
                rows.append((split, klass, "skip", "-", "-", "-", path.name))
                continue
            with self.subTest(split=split, document=path.name):
                metrics = measure(path, pages)
                totals = metrics["totals"]
                problems = violations(metrics)
                rows.append((split, klass, "FAIL" if problems else "pass",
                             f"{totals['ghostRate']:.2%}", f"{totals['maxOcclusion']:.1%}",
                             f"{totals['maxLineBoxEm']:.2f}", path.name))
                self.assertEqual(problems, [])
        width = max(len(r[-1]) for r in rows)
        print(f"\n{'split':9} {'class':11} {'result':6} {'ghosts':>7} {'occl':>6} {'box em':>6}  document",
              file=sys.stderr)
        for r in rows:
            print(f"{r[0]:9} {r[1]:11} {r[2]:6} {r[3]:>7} {r[4]:>6} {r[5]:>6}  {r[6][:width]}",
                  file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
