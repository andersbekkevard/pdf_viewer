"""Public CLI contracts for the conservative light structure verifier."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "verify-light-structure.py"


def canonical_document(second_text: str = "Second") -> str:
    return f'''<!doctype html>
<html><body><div id="page-container">
<div id="pf1" class="pf w0 h0"><div class="pc"><img class="bi x0" src="data:image/png;base64,QUFB"></div><div class="t x1">First</div></div>
<div id="pf2" class="pf w0 h0"><div class="pc"><img class="bi x0" src="data:image/png;base64,QkJC"></div><div class="t x2">{second_text}</div></div>
</div></body></html>'''


def conservative_light_document(second_text: str = "Second", *, page_metadata: bool = True) -> str:
    first_page_metadata = (
        ' data-pdf2html-page="1" data-pdf2html-text-mode="original"'
        if page_metadata
        else ""
    )
    second_page_metadata = (
        ' data-pdf2html-page="2" data-pdf2html-text-mode="original"'
        if page_metadata
        else ""
    )
    return f'''<!doctype html>
<html data-pdf2html-representation="light-v1" data-pdf2html-text-mode="original"><body class="pdf2html-light"><div id="page-container">
<div id="pf1" class="pf w0 h0"{first_page_metadata}><div class="pc"><img class="bi x0" src="/entry/page-images/0001.png" data-pdf2html-src="/entry/page-images/0001.png" data-pdf2html-raster="external" data-pdf2html-page="1"></div><div class="t x1">First</div></div>
<div id="pf2" class="pf w0 h0"{second_page_metadata}><div class="pc"><img class="bi x0" data-pdf2html-src="/entry/page-images/0002.png" data-pdf2html-raster="external" data-pdf2html-page="2"></div><div class="t x2">{second_text}</div></div>
</div></body></html>'''


class VerifyLightStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.canonical = self.root / "source.html"
        self.light = self.root / "source.light.html"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_verifier(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.canonical), str(self.light)],
            capture_output=True,
            text=True,
        )

    def test_accepts_only_externalized_rasters_and_representation_metadata(self) -> None:
        self.canonical.write_text(canonical_document(), encoding="utf-8")
        self.light.write_text(conservative_light_document(), encoding="utf-8")

        result = self.run_verifier()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("PASS", result.stdout)
        self.assertIn("pages=2", result.stdout)
        self.assertIn("text_runs=2", result.stdout)
        self.assertIn("text_sha256=", result.stdout)

    def test_reports_the_first_page_whose_text_subtree_changes(self) -> None:
        self.canonical.write_text(canonical_document(), encoding="utf-8")
        self.light.write_text(conservative_light_document("Changed"), encoding="utf-8")

        result = self.run_verifier()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("text subtree mismatch at page 2", result.stderr)
        self.assertIn("canonical_sha256=", result.stderr)
        self.assertIn("light_sha256=", result.stderr)

    def test_accepts_converter_style_conservative_pages_without_optional_page_metadata(self) -> None:
        self.canonical.write_text(canonical_document(), encoding="utf-8")
        self.light.write_text(conservative_light_document(page_metadata=False), encoding="utf-8")

        result = self.run_verifier()

        self.assertEqual(0, result.returncode, result.stderr)

    def test_rejects_non_raster_structure_changes(self) -> None:
        self.canonical.write_text(canonical_document(), encoding="utf-8")
        self.light.write_text(
            conservative_light_document().replace('class="pc"', 'class="pc changed"', 1),
            encoding="utf-8",
        )

        result = self.run_verifier()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("structure mismatch at page 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
