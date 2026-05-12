import json
import unittest
from collections import Counter
from pathlib import Path

from offline_map import load_offline_map_context


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_CASE = ROOT / "tests" / "fixtures" / "field_cases" / "scout_260512_golden.json"


class FieldGoldenCaseTests(unittest.TestCase):
    def test_260512_manifest_documents_field_segments(self):
        manifest = json.loads(GOLDEN_CASE.read_text())

        self.assertEqual(manifest["case_id"], "scout_260512_field_golden")
        self.assertEqual(len(manifest["segments"]), 2)
        self.assertEqual(
            [segment["id"] for segment in manifest["segments"]],
            ["watch_260512_085237", "watch_260512_093931"],
        )
        self.assertAlmostEqual(manifest["gap_between_segments"]["duration_s"], 1125.0, places=1)
        self.assertAlmostEqual(manifest["gap_between_segments"]["endpoint_distance_m"], 546.1, places=1)

    def test_260512_overpass_map_context_meets_golden_thresholds(self):
        manifest = json.loads(GOLDEN_CASE.read_text())
        acceptance = manifest["acceptance"]
        context = load_offline_map_context(ROOT / manifest["map_context"])

        self.assertEqual(context.source_metadata.source, "openstreetmap_overpass")
        self.assertGreaterEqual(len(context.corridors), acceptance["min_overpass_corridors"])

        levels = Counter(corridor.route_level for corridor in context.corridors)
        self.assertGreaterEqual(levels["footway"], acceptance["min_footway_corridors"])
        self.assertGreaterEqual(levels["path"], acceptance["min_path_corridors"])
        self.assertGreaterEqual(levels["steps"], acceptance["min_steps_corridors"])

    def test_260512_route_network_coverage_metrics_stay_within_bounds(self):
        manifest = json.loads(GOLDEN_CASE.read_text())
        acceptance = manifest["acceptance"]

        for segment in manifest["segments"]:
            with self.subTest(segment=segment["id"]):
                self.assertGreaterEqual(
                    segment["map_inside_corridor_with_hacc_pct"],
                    acceptance["min_map_inside_with_hacc_pct"],
                )
                self.assertLessEqual(
                    segment["nearest_corridor_distance_p95_m"],
                    acceptance["max_nearest_corridor_distance_p95_m"],
                )

    def test_260512_second_segment_preserves_weak_gps_profile(self):
        manifest = json.loads(GOLDEN_CASE.read_text())
        second = manifest["segments"][1]

        self.assertGreater(second["horizontal_accuracy_p90_m"], 20.0)
        self.assertGreater(second["horizontal_accuracy_max_m"], 50.0)
        self.assertLess(second["gps_polyline_acc_lte_5m_m"], second["gps_polyline_acc_lte_20m_m"])


if __name__ == "__main__":
    unittest.main()
