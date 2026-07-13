"""Focused contracts for the light HTML converter."""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "externalize-page-images.py"
OVERLAY_CSS = pathlib.Path(__file__).parents[2] / "assets" / "overlay.css"
SPEC = importlib.util.spec_from_file_location("externalize_page_images", SCRIPT)
assert SPEC and SPEC.loader
converter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(converter)

PNG_BYTES = b"\x89PNG\r\n\x1a\ngeometry"
PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")


def document(second_raster: str = "/already-external.png") -> str:
    return f"""<!doctype html>
<html><body><div id="page-container">
<div id="pf1" class="pf w0 h0"><div class="pc">
<img class="bi x0" src="{PNG_DATA_URI}">
<div class="c"><div class="t m0 x1 h2 y3 ff1 fs2 fc0 sc0">Start <span class="_ _1"> </span><span class="fc1 sc0">Paint</span><span class="ls4">Wide</span><span class="ff4"><span class="fc2 sc0">Font</span></span></div></div>
</div><div class="pi"></div></div>
<div class="pf h0 w0" id="pf2"><div class="pc">
<img class="bi x0" src="{second_raster}"><div class="c"><div class="t x2 y4">Second &amp; line<span class="_ _2"></span><span class="_ _3"> </span>Gap</div></div>
</div><div class="pi"></div></div>
</div></body></html>"""


class ExternalizePageImagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.input = self.root / "source.html"
        self.output = self.root / "source.light.html"
        self.images = self.root / "page-images"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_source(self, source: str | None = None) -> None:
        self.input.write_text(source or document(), encoding="utf-8")

    def convert(self, *, clean: bool = True) -> tuple[int, int, int, int, int]:
        return converter.externalize(
            self.input,
            self.output,
            self.images,
            "/entry/page-images/",
            eager=1,
            clean=clean,
            text_layer="geometry",
        )

    def test_geometry_contract_retains_lines_spacers_and_geometry(self) -> None:
        self.write_source()
        result = self.convert()
        output = self.output.read_text(encoding="utf-8")

        self.assertEqual((2, 1, 1), result[:3])
        self.assertEqual(PNG_BYTES, (self.images / "0001.png").read_bytes())
        self.assertIn('data-pdf2html-representation="light-v1"', output)
        self.assertIn('data-pdf2html-text-mode="geometry"', output)
        self.assertEqual(2, converter.page_frame_count(output))
        self.assertEqual(2, sum(1 for tag in converter.IMG_TAG_RE.findall(output)))
        self.assertIn('data-pdf2html-page="1" data-pdf2html-text-mode="geometry"', output)
        self.assertIn('data-pdf2html-page="2" data-pdf2html-text-mode="geometry"', output)
        self.assertIn('data-pdf2html-src="/entry/page-images/0001.png"', output)
        self.assertIn('data-pdf2html-src="/already-external.png"', output)
        self.assertIn('src="/entry/page-images/0001.png"', output)

        self.assertEqual(
            ["Start PaintWideFont", "Second & line Gap"],
            converter.text_lines(output),
        )
        self.assertIn('<span class="_ _1"></span>', output)
        self.assertNotIn('<span class="_ _2"></span>', output)
        self.assertIn('<span class="_ _3"> </span>', output)
        self.assertIn('<span class="ls4">Wide</span>', output)
        self.assertIn('<span class="ff4">Font</span>', output)
        self.assertNotIn('<span class="fc1 sc0">Paint</span>', output)
        self.assertNotIn('<span class="fc2 sc0">Font</span>', output)
        self.assertNotIn("pdf2html-page-text", output)

    def test_rebuild_is_idempotent_and_clean_removes_stale_assets(self) -> None:
        self.write_source()
        self.convert()
        first = self.output.read_text(encoding="utf-8")
        (self.images / "9999.png").write_bytes(b"stale")

        self.convert(clean=True)

        self.assertEqual(first, self.output.read_text(encoding="utf-8"))
        self.assertEqual(["0001.png"], sorted(path.name for path in self.images.iterdir()))
        self.assertEqual(PNG_BYTES, (self.images / "0001.png").read_bytes())

    def test_cli_defaults_to_paint_safe_text(self) -> None:
        self.write_source()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.input),
                str(self.output),
                "--image-dir",
                str(self.images),
                "--url-prefix",
                "/entry/page-images/",
                "--clean",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        output = self.output.read_text(encoding="utf-8")
        source = self.input.read_text(encoding="utf-8")

        self.assertIn("paint-safe hidden lines", completed.stdout)
        self.assertIn('data-pdf2html-representation="light-v1"', output)
        self.assertIn('data-pdf2html-text-mode="paint-safe"', output)
        self.assertEqual(
            [match.group(0) for match in converter.TEXT_DIV_RE.finditer(source)],
            [match.group(0) for match in converter.TEXT_DIV_RE.finditer(output)],
        )

    def test_cli_geometry_mode_is_explicit(self) -> None:
        self.write_source()
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.input),
                str(self.output),
                "--image-dir",
                str(self.images),
                "--url-prefix",
                "/entry/page-images/",
                "--clean",
                "--text-layer=geometry",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(
            'data-pdf2html-text-mode="geometry"', self.output.read_text(encoding="utf-8")
        )

    def test_cli_help_identifies_paint_safe_default_and_original_diagnostics(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("paint-safe, default", completed.stdout)
        self.assertIn("original diagnostics", completed.stdout)

    def test_cli_paint_safe_mode_reports_its_opt_in_line_count(self) -> None:
        self.write_source(
            document().replace(
                "<html><body>",
                "<html><head><style>.ff1{visibility:hidden}</style></head><body>",
            )
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.input),
                str(self.output),
                "--image-dir",
                str(self.images),
                "--url-prefix",
                "/entry/page-images/",
                "--clean",
                "--text-layer=paint-safe",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("paint-safe hidden lines", completed.stdout)
        self.assertIn('data-pdf2html-text-mode="paint-safe"', self.output.read_text(encoding="utf-8"))

    def test_only_geometry_mode_makes_text_transparent(self) -> None:
        css = OVERLAY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            'html[data-pdf2html-representation="light-v1"][data-pdf2html-text-mode="geometry"]\n'
            'body #page-container .t,',
            css,
        )
        self.assertNotRegex(
            css,
            r"body\.pdf2html-light\s+#page-container\s+\.t(?:\s|,|\*)",
        )

    def test_paint_safe_only_simplifies_provably_hidden_lines(self) -> None:
        source = f"""<!doctype html>
<html><head><style>
.ff1 {{ font-family: sans-serif; visibility: hidden; }}
.ff2 {{ font-family: serif; visibility: visible; }}
.ink-override {{ visibility: visible; }}
</style></head><body><div id="page-container">
<div id="pf1" class="pf"><div class="pc"><img class="bi" src="{PNG_DATA_URI}"><div class="c">
<div class="t ff1 fc0">Hidden <span class="fc1 sc0">paint</span><span class="_ _1"></span></div>
<div class="t ff2 fc0">Visible <span class="fc1 sc0">paint</span></div>
<div class="t ff1" style="visibility:visible">Inline override</div>
<div class="t ff1"><span style="visibility:visible">Descendant override</span></div>
<div class="t ff1"><span class="ink-override">Class override</span></div>
</div></div></div></div></body></html>"""
        self.write_source(source)
        converter.externalize(
            self.input,
            self.output,
            self.images,
            "/entry/page-images/",
            eager=1,
            clean=True,
            text_layer="paint-safe",
        )
        output = self.output.read_text(encoding="utf-8")

        source_lines = [match.group(0) for match in converter.TEXT_DIV_RE.finditer(source)]
        output_lines = [match.group(0) for match in converter.TEXT_DIV_RE.finditer(output)]
        self.assertEqual(5, len(output_lines))
        self.assertIn('data-pdf2html-text-mode="paint-safe"', output)
        self.assertIn('data-pdf2html-paint-safe="hidden"', output_lines[0])
        self.assertIn("pdf2html-paint-safe", output_lines[0].split(">", 1)[0])
        self.assertNotIn('<span class="fc1 sc0">paint</span>', output_lines[0])
        self.assertEqual(converter.text_lines(source), converter.text_lines(output))
        self.assertEqual(source_lines[1:], output_lines[1:])

    def test_paint_safe_css_targets_only_marked_hidden_lines(self) -> None:
        css = OVERLAY_CSS.read_text(encoding="utf-8")

        self.assertIn(
            '.t.pdf2html-paint-safe[data-pdf2html-paint-safe="hidden"]',
            css,
        )
        self.assertNotIn(
            '[data-pdf2html-text-mode="paint-safe"]\nbody #page-container .t,',
            css,
        )

    def test_paint_safe_rejects_unbalanced_eligible_line_before_publishing(self) -> None:
        self.images.mkdir()
        sentinel = self.images / "0001.png"
        sentinel.write_bytes(b"published-raster")
        self.output.write_text("published-html", encoding="utf-8")
        self.write_source(
            f"""<html><head><style>.ff1{{visibility:hidden}}</style></head><body>
<div id="pf1" class="pf"><img class="bi" src="{PNG_DATA_URI}"><div class="t ff1"><span class="fc1">broken</div></div>
</body></html>"""
        )

        with self.assertRaisesRegex(RuntimeError, "unclosed <span>"):
            converter.externalize(
                self.input,
                self.output,
                self.images,
                "/entry/page-images/",
                eager=1,
                clean=True,
                text_layer="paint-safe",
            )

        self.assertEqual(b"published-raster", sentinel.read_bytes())
        self.assertEqual("published-html", self.output.read_text(encoding="utf-8"))

    def test_rejects_missing_or_malformed_page_rasters(self) -> None:
        self.write_source(document().replace(f' src="{PNG_DATA_URI}"', "", 1))
        with self.assertRaisesRegex(RuntimeError, "has no src"):
            self.convert()

        self.write_source(document().replace(PNG_DATA_URI, "data:image/png;base64,not-base64!"))
        with self.assertRaisesRegex(RuntimeError, "failed to decode page raster 1"):
            self.convert()

    def test_validation_failure_preserves_published_light_artifacts(self) -> None:
        self.images.mkdir()
        sentinel = self.images / "0001.png"
        sentinel.write_bytes(b"published-raster")
        self.output.write_text("published-html", encoding="utf-8")
        self.write_source(document().replace(PNG_DATA_URI, "data:image/png;base64,not-base64!"))

        with self.assertRaisesRegex(RuntimeError, "failed to decode page raster 1"):
            self.convert(clean=True)

        self.assertEqual(b"published-raster", sentinel.read_bytes())
        self.assertEqual("published-html", self.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
