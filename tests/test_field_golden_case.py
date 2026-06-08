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
        self.assertEqual(manifest["generated_by"], "generate_field_golden_case.py")
        self.assertEqual(
            manifest["bbox"],
            {"south": 25.0585, "west": 121.6505, "north": 25.073, "east": 121.6705},
        )

    def test_260512_overpass_map_context_meets_golden_thresholds(self):
        manifest = json.loads(GOLDEN_CASE.read_text())
        acceptance = manifest["acceptance"]
        context = load_offline_map_context(ROOT / manifest["map_context"])

        self.assertEqual(context.source_metadata.source, "openstreetmap_overpass")
        self.assertGreaterEqual(len(context.corridors), acceptance["min_overpass_corridors"])
        self.assertEqual(manifest["map_context_summary"]["corridors"], len(context.corridors))

        levels = Counter(corridor.route_level for corridor in context.corridors)
        self.assertGreaterEqual(levels["footway"], acceptance["min_footway_corridors"])
        self.assertGreaterEqual(levels["path"], acceptance["min_path_corridors"])
        self.assertGreaterEqual(levels["steps"], acceptance["min_steps_corridors"])
        self.assertEqual(manifest["map_context_summary"]["route_level_counts"]["footway"], levels["footway"])

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
                self.assertGreaterEqual(
                    len(segment["representative_samples"]),
                    acceptance["min_representative_samples_per_segment"],
                )
                self.assertEqual(
                    segment["map_coverage"]["nearest_corridor_distance_p95_m"],
                    segment["nearest_corridor_distance_p95_m"],
                )

    def test_260512_expanded_sensor_metrics_are_preserved(self):
        manifest = json.loads(GOLDEN_CASE.read_text())

        for segment in manifest["segments"]:
            with self.subTest(segment=segment["id"]):
                self.assertEqual(segment["sensor_availability"]["gps_records"], segment["valid_location_records"])
                self.assertEqual(segment["sensor_availability"]["imu_records"], segment["records"])
                self.assertGreater(segment["horizontal_accuracy_distribution_m"]["p95"], 0)
                self.assertGreater(segment["elevation_profile_m"]["max"], segment["elevation_profile_m"]["min"])
                self.assertGreater(segment["speed_profile_mps"]["max"], 0)
                self.assertIn("walking", segment["activity_counts"])

    def test_260512_second_segment_preserves_weak_gps_profile(self):
        manifest = json.loads(GOLDEN_CASE.read_text())
        second = manifest["segments"][1]

        self.assertGreater(second["horizontal_accuracy_p90_m"], 20.0)
        self.assertGreater(second["horizontal_accuracy_max_m"], 50.0)
        self.assertGreater(second["horizontal_accuracy_distribution_m"]["gt_50_count"], 0)
        self.assertLess(second["gps_polyline_acc_lte_5m_m"], second["gps_polyline_acc_lte_20m_m"])


if __name__ == "__main__":
    unittest.main()
