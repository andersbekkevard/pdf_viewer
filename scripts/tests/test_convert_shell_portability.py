"""Portability contracts for the conversion pipeline's failure paths.

scripts/pdf2html-convert.sh runs under macOS system bash 3.2 (#!/bin/bash),
so bash 4+ expansions such as ${var@Q} are fatal at runtime: the magic-byte
failure banner died with "bad substitution", fail() never ran, and the script
fell through into a bogus convert attempt with empty names.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest


ROOT = pathlib.Path(__file__).parents[2]
CONVERT = ROOT / "scripts" / "pdf2html-convert.sh"
PIPELINE = ROOT / "scripts" / "lib" / "pipeline.sh"

# Bash 4+ parameter-transformation operators; none are valid on bash 3.2.
BASH4_OPS = ("@Q", "@E", "@P", "@A", "@a", "@K", "@k")


def run_system_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )


def extract_function(source: str, name: str) -> str:
    lines = source.splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(name + "() {")
    )
    end = next(
        index for index in range(start + 1, len(lines)) if lines[index] == "}"
    )
    return "\n".join(lines[start : end + 1])


class ConvertPortabilityTests(unittest.TestCase):
    def test_no_bash4_transform_operators(self) -> None:
        for script in (CONVERT, PIPELINE):
            # Comment lines document the ban by name; only live code can break.
            code = "\n".join(
                line
                for line in script.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for op in BASH4_OPS:
                with self.subTest(script=script.name, op=op):
                    for match in re.finditer(r"\$\{[^}]*" + re.escape(op) + r"\}", code):
                        self.fail(f"bash4-only expansion {match.group(0)!r} in {script.name}")

    def test_no_mapfile_or_assoc_arrays(self) -> None:
        for script in (CONVERT, PIPELINE):
            source = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                self.assertNotIn("mapfile", source)
                self.assertNotIn("declare -A", source)

    def test_pipeline_parses_on_system_bash(self) -> None:
        for script in (CONVERT, PIPELINE):
            with self.subTest(script=script.name):
                subprocess.run(["/bin/bash", "-n", str(script)], check=True)

    def test_magic_failure_path_uses_sanitized_magic(self) -> None:
        source = CONVERT.read_text(encoding="utf-8")
        self.assertIn("MAGIC_SAFE=", source)
        self.assertIn("magic: $MAGIC_SAFE", source)

    def test_osasafe_escapes_quotes_and_backslashes_on_system_bash(self) -> None:
        source = CONVERT.read_text(encoding="utf-8")
        osasafe = extract_function(source, "osasafe")
        completed = run_system_bash(
            osasafe + '\nosasafe \'say "hi" \\ bye\''
        )
        self.assertEqual(r'say \"hi\" \\ bye', completed.stdout)

    def test_magic_sanitize_pipeline_on_system_bash(self) -> None:
        completed = run_system_bash(
            'MAGIC=\'<!DO\'; MAGIC_SAFE=$(printf \'%s\' "$MAGIC" | tr -cd \'[:print:]\' | cut -c1-20); printf \'%s\' "$MAGIC_SAFE"'
        )
        self.assertEqual("<!DO", completed.stdout)

    def test_progress_filter_keeps_warnings_and_failure_signal(self) -> None:
        filter_cmd = "tr '\\r' '\\n' | grep -vE '^(Preprocessing|Working): [0-9]+/[0-9]+$'"
        # Success case: progress ticks dropped, warnings kept, status 0.
        ok = run_system_bash(
            "printf 'Preprocessing: 1/83\\rWorking: 2/83\\rToUnicode CMap dropped\\n'"
            f" | {filter_cmd} >/dev/null; printf '%s' \"${{PIPESTATUS[0]}}\""
        )
        # The printf builtin succeeds, so PIPESTATUS[0] is 0; check filtering
        # via a second run that captures stdout instead.
        filtered = run_system_bash(
            "printf 'Preprocessing: 1/83\\rWorking: 2/83\\rToUnicode CMap dropped\\n'"
            f" | {filter_cmd}"
        )
        self.assertEqual("ToUnicode CMap dropped\n", filtered.stdout)
        self.assertEqual("0", ok.stdout)
        # Failure case: a failing producer still reports nonzero.
        failed = run_system_bash(
            f"(printf 'Working: 1/2\\r'; exit 3) | {filter_cmd}; printf '%s' \"${{PIPESTATUS[0]}}\""
        )
        self.assertEqual("3", failed.stdout)


if __name__ == "__main__":
    unittest.main()
