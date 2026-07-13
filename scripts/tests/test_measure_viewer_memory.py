"""Contracts for the renderer-footprint report seam.

The benchmark's browser work is intentionally live-only.  This test covers the
stable public Node-module seam used to turn independently measured renderer
samples into a machine-readable comparison and capacity recommendation.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest


HARNESS = pathlib.Path(__file__).parents[1] / "measure-viewer-memory.cjs"


def summarize(samples: dict[str, list[int]]) -> dict[str, object]:
    program = """
const { summarizeSamples } = require(process.argv[1]);
const result = summarizeSamples(JSON.parse(process.argv[2]));
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", program, str(HARNESS), json.dumps(samples)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class MeasureViewerMemoryTests(unittest.TestCase):
    def test_median_ratios_and_threshold_recommendation_come_from_samples(self) -> None:
        result = summarize(
            {
                "canonical": [9 * 1024**3, 10 * 1024**3, 11 * 1024**3],
                "original_light": [4 * 1024**3, 5 * 1024**3, 6 * 1024**3],
                "geometry_light": [3 * 1024**3, 4 * 1024**3, 5 * 1024**3],
            }
        )

        self.assertEqual(10 * 1024**3, result["medians_bytes"]["canonical"])
        self.assertEqual(5 * 1024**3, result["medians_bytes"]["original_light"])
        self.assertEqual(4 * 1024**3, result["medians_bytes"]["geometry_light"])
        self.assertEqual(0.5, result["ratios_to_canonical"]["original_light"])
        self.assertEqual(0.4, result["ratios_to_canonical"]["geometry_light"])
        self.assertEqual("fits", result["thresholds"]["original_light"]["5_gib"])
        self.assertEqual("fits", result["thresholds"]["geometry_light"]["5_gib"])
        self.assertEqual("exceeds", result["thresholds"]["canonical"]["8_gib"])
        self.assertEqual("geometry_light", result["recommendation"]["representation"])

    def test_recommendation_reports_when_no_representation_fits_five_gib(self) -> None:
        result = summarize(
            {
                "canonical": [9 * 1024**3],
                "original_light": [7 * 1024**3],
                "geometry_light": [6 * 1024**3],
            }
        )

        self.assertEqual("does_not_fit", result["thresholds"]["geometry_light"]["5_gib"])
        self.assertEqual("geometry_light", result["recommendation"]["representation"])
        self.assertIn("No representation fits", result["recommendation"]["summary"])


if __name__ == "__main__":
    unittest.main()
