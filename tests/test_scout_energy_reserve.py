import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scout_energy_baseline import build_energy_reserve_baseline, internal_load_score
from scout_energy_models import load_wearable_activity_summary, load_wearable_activity_summaries


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
FIXTURES = [
    FIXTURE_ROOT / "apple_health_clean_activity.json",
    FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]


class ScoutEnergyReserveTests(unittest.TestCase):
    def test_loads_provider_neutral_activity_summary_with_provenance_and_boundary(self):
        activity = load_wearable_activity_summary(FIXTURES[0], root=ROOT)

        self.assertEqual(activity.artifact_kind, "scout_wearable_activity_summary")
        self.assertEqual(activity.source_provider, "apple_health_export")
        self.assertEqual(activity.source_path, "tests/fixtures/wearables/apple_health_clean_activity.json")
        self.assertEqual(len(activity.sha256), 64)
        self.assertEqual(activity.heart_rate.sample_count, 6)
        self.assertEqual(activity.heart_rate.zone_minutes["z3"], 25)
        self.assertEqual(activity.data_quality.heart_rate_confidence, "high")
        self.assertFalse(activity.boundary.medical_diagnosis)
        self.assertFalse(activity.boundary.phase1_runtime_safety_truth)
        self.assertFalse(activity.boundary.safety_api_calls_allowed)
        self.assertFalse(activity.privacy.raw_track_shared)
        self.assertFalse(activity.privacy.exact_timestamps_shared)

    def test_missing_hr_interval_lowers_quality_without_crashing_baseline(self):
        clean = load_wearable_activity_summary(FIXTURES[0], root=ROOT)
        missing = load_wearable_activity_summary(FIXTURES[1], root=ROOT)

        self.assertGreater(internal_load_score(clean), internal_load_score(missing))
        self.assertEqual(missing.data_quality.missing_hr_seconds, 900)
        self.assertEqual(missing.data_quality.heart_rate_confidence, "low")

    def test_builds_7_28_90_day_baseline_and_reserve_band(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        baseline = build_energy_reserve_baseline(activities, reference_date=date(2026, 5, 27))
        payload = baseline.model_dump(mode="json")

        self.assertEqual(baseline.artifact_kind, "scout_energy_reserve_baseline")
        self.assertEqual(baseline.source_provider, "mixed_wearable_activity_summaries")
        self.assertEqual(baseline.source_path, "aggregate:tests/fixtures/wearables")
        self.assertEqual(len(baseline.sha256), 64)
        self.assertEqual(baseline.acute_7_day_load.activity_count, 1)
        self.assertEqual(baseline.recent_28_day_baseline.activity_count, 2)
        self.assertEqual(baseline.stable_90_day_baseline.activity_count, 3)
        self.assertEqual(len(baseline.route_family_profiles), 1)
        route_family = baseline.route_family_profiles[0]
        self.assertEqual(route_family.route_family, "local_day_hike")
        self.assertEqual(route_family.activity_count, 3)
        self.assertGreater(route_family.route_effort_units_p50, 0)
        self.assertGreater(route_family.moving_time_per_effort_p50, 0)
        self.assertEqual(route_family.confidence, "medium")
        self.assertEqual(baseline.reserve_trend.current_band, "rest_suggested")
        self.assertGreater(baseline.reserve_trend.acute_load_ratio, 1.5)
        self.assertEqual(baseline.data_quality.missing_hr_seconds, 900)
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(payload["boundary"]["provider_values_are_scout_truth"])
        self.assertFalse(payload["privacy"]["raw_samples_embedded"])
        self.assertIn("route_family_profiles", payload)
        self.assertNotIn("/safety/", json.dumps(payload))
        self.assertNotIn("<trkpt", json.dumps(payload))

    def test_route_family_profiles_require_minimum_family_history(self):
        activity = load_wearable_activity_summary(FIXTURES[0], root=ROOT)
        baseline = build_energy_reserve_baseline([activity], reference_date=date(2026, 5, 27))

        self.assertEqual(baseline.activity_count, 1)
        self.assertEqual(baseline.route_family_profiles, [])

    def test_garmin_provider_values_remain_source_values_not_scout_truth(self):
        garmin = load_wearable_activity_summary(FIXTURES[2], root=ROOT)

        self.assertEqual(garmin.body_energy_provider_values.garmin_body_battery_end, 35)
        self.assertEqual(garmin.body_energy_provider_values.garmin_stress_avg, 62)
        self.assertTrue(garmin.body_energy_provider_values.source_value_only)
        self.assertFalse(garmin.body_energy_provider_values.scout_truth)

    def test_energy_reserve_cli_builds_fixture_backed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "energy"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_energy_reserve",
                    "build",
                    "--activity",
                    str(FIXTURES[0]),
                    "--activity",
                    str(FIXTURES[1]),
                    "--activity",
                    str(FIXTURES[2]),
                    "--output-dir",
                    str(output_dir),
                    "--reference-date",
                    "2026-05-27",
                    "--root",
                    str(ROOT),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )

            payload = json.loads(completed.stdout)
            baseline_path = Path(payload["baseline_path"])
            explanation_path = Path(payload["explanation_path"])
            capsule_path = Path(payload["companion_capsule_path"])
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            self.assertTrue(baseline_path.is_file())
            self.assertTrue(explanation_path.is_file())
            self.assertTrue(capsule_path.is_file())

        self.assertEqual(payload["artifact_kind"], "scout_energy_reserve_artifact_export")
        self.assertEqual(payload["source_provider"], "mixed_wearable_activity_summaries")
        self.assertEqual(payload["source_path"], "aggregate:tests/fixtures/wearables")
        self.assertEqual(len(payload["sha256"]), 64)
        self.assertEqual(payload["data_quality"]["missing_hr_seconds"], 900)
        self.assertFalse(payload["privacy"]["raw_samples_embedded"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertEqual(baseline["source_provider"], "mixed_wearable_activity_summaries")
        self.assertEqual(baseline["source_path"], "aggregate:tests/fixtures/wearables")
        self.assertEqual(baseline["route_family_profiles"][0]["route_family"], "local_day_hike")
        self.assertEqual(len(baseline["sha256"]), 64)
        self.assertEqual(baseline["reserve_trend"]["current_band"], "rest_suggested")
        self.assertFalse(baseline["boundary"]["medical_diagnosis"])
        self.assertFalse(baseline["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(baseline["boundary"]["safety_api_calls_allowed"])
        self.assertFalse(baseline["privacy"]["raw_samples_embedded"])
        self.assertNotIn("/safety/", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
