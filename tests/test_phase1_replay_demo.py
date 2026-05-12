import argparse
import tempfile
import unittest
from pathlib import Path

from phase1_replay_demo import main, run_phase1_replay_demo


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"


class Phase1ReplayDemoTests(unittest.TestCase):
    def test_normal_route_summary_stays_l0(self):
        summary = run_phase1_replay_demo(
            argparse.Namespace(
                mission=MISSION_PATH,
                route=ROUTE_PATH,
                map_context=None,
                risk_rules=None,
                mission_context=None,
                route_progress_config=None,
                incident_store=None,
            )
        )

        self.assertEqual(summary["observations_processed"], 3812)
        self.assertEqual(summary["safety_level"], "L0_NORMAL")
        self.assertEqual(summary["safety_events"], [])
        self.assertEqual(summary["incident_ids"], [])
        self.assertEqual(summary["progressed_checkpoints"], [f"cp_{index:02d}" for index in range(1, 11)])
        self.assertIn("low", summary["recording_profiles"])

    def test_off_route_summary_reports_l2_and_stores_incident(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = run_phase1_replay_demo(
                argparse.Namespace(
                    mission=MISSION_PATH,
                    route=OFF_ROUTE_PATH,
                    map_context=None,
                    risk_rules=None,
                    mission_context=None,
                    route_progress_config=None,
                    incident_store=Path(tmpdir),
                )
            )

            self.assertEqual(summary["safety_level"], "L2_CONCERN")
            self.assertEqual(summary["safety_events"], ["route_deviation"])
            self.assertEqual(len(summary["incident_ids"]), 1)
            self.assertEqual(len(summary["stored_incident_paths"]), 1)
            self.assertTrue(Path(summary["stored_incident_paths"][0]).exists())
            self.assertEqual(summary["latest_incident_summary"]["event"]["event_type"], "route_deviation")

    def test_main_returns_success(self):
        code = main(["--mission", str(MISSION_PATH), "--route", str(ROUTE_PATH)])

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
