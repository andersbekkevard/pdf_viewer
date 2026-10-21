"""Production shell contracts for paint-safe light generation."""
from __future__ import annotations

import pathlib
import os
import subprocess
import unittest


ROOT = pathlib.Path(__file__).parents[2]
# The shared pipeline owns the light-generation contract; every producer
# script must go through it rather than calling the toolchain itself.
PIPELINE = ROOT / "scripts" / "lib" / "pipeline.sh"
PRODUCERS = (
    ROOT / "scripts" / "pdf2html-convert.sh",
    ROOT / "scripts" / "index-directory-parallel.sh",
    ROOT / "scripts" / "upgrade-cache.sh",
)
SCRIPTS = (PIPELINE,) + PRODUCERS + (ROOT / "scripts" / "index-directory.sh",)


class LightShellContractTests(unittest.TestCase):
    def test_light_generation_defaults_on_with_new_flag_over_legacy_compatibility_flag(self) -> None:
        expected = 'LIGHT_VARIANTS_ENABLED="${PDF_VIEWER_ENABLE_LIGHT:-${PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT:-1}}"'
        self.assertIn(expected, PIPELINE.read_text(encoding="utf-8"))

    def test_producers_build_entries_through_the_shared_pipeline(self) -> None:
        for script in PRODUCERS:
            source = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertIn('/lib/pipeline.sh"', source)
                self.assertNotIn('"$EXTERNALIZER"', source)
                self.assertNotIn('"$NATIVE_BIN" --data-dir', source)
                self.assertNotIn("LIGHT_VARIANTS_ENABLED=", source)

    def test_serial_indexer_is_the_parallel_indexer_with_one_worker(self) -> None:
        source = (ROOT / "scripts" / "index-directory.sh").read_text(encoding="utf-8")
        self.assertIn('index-directory-parallel.sh" "${1:-}" 1', source)

    def test_new_flag_can_disable_default_and_overrides_legacy_flag(self) -> None:
        assignment = 'LIGHT_VARIANTS_ENABLED="${PDF_VIEWER_ENABLE_LIGHT:-${PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT:-1}}"'
        cases = (
            ({}, "1"),
            ({"PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT": "0"}, "0"),
            ({"PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT": "1"}, "1"),
            ({"PDF_VIEWER_ENABLE_LIGHT": "0", "PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT": "1"}, "0"),
            ({"PDF_VIEWER_ENABLE_LIGHT": "1", "PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT": "0"}, "1"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                environment = os.environ.copy()
                environment.pop("PDF_VIEWER_ENABLE_LIGHT", None)
                environment.pop("PDF_VIEWER_ENABLE_EXPERIMENTAL_LIGHT", None)
                environment.update(overrides)
                completed = subprocess.run(
                    ["bash", "-c", assignment + '; printf "%s" "$LIGHT_VARIANTS_ENABLED"'],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                self.assertEqual(expected, completed.stdout)

    def test_every_production_externalizer_call_selects_paint_safe_text(self) -> None:
        for script in (PIPELINE,):
            lines = script.read_text(encoding="utf-8").splitlines()
            call_lines = [index for index, line in enumerate(lines) if 'uv run "$EXTERNALIZER"' in line]
            self.assertTrue(call_lines, f"{script.name} has no externalizer call")
            for index in call_lines:
                with self.subTest(script=script.name, call=index):
                    call = "\n".join(lines[index : index + 9])
                    self.assertIn("--text-layer=paint-safe", call)

    def test_shell_messages_do_not_describe_light_as_experimental(self) -> None:
        for script in SCRIPTS:
            source = script.read_text(encoding="utf-8").lower()
            with self.subTest(script=script.name):
                self.assertNotIn("experimental light", source)
                self.assertNotIn("skip-experimental", source)


if __name__ == "__main__":
    unittest.main()
