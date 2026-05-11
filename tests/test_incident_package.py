import unittest

from incident_package import IncidentPackageBuilder
from safety_models import Observation, SafetyEvent, SafetyEventType, SafetyLevel


class IncidentPackageBuilderTests(unittest.TestCase):
    def test_builds_l2_package_from_last_five_minutes_of_raw_samples(self):
        builder = IncidentPackageBuilder(raw_window_seconds=300)
        for timestamp in [0.0, 60.0, 120.0, 240.0, 301.0, 360.0]:
            builder.observe(
                Observation(
                    timestamp=timestamp,
                    source="test",
                    lat=25.0,
                    lon=121.0,
                    raw={"sample": timestamp},
                )
            )
        event = SafetyEvent(
            event_type=SafetyEventType.MISSED_CHECKPOINT,
            level=SafetyLevel.CONCERN,
            timestamp=360.0,
            reason="Missed expected checkpoint.",
            confidence=0.8,
        )

        package = builder.build_for_event(event)

        self.assertIsNotNone(package)
        self.assertEqual(package.raw_window_start, 60.0)
        self.assertEqual(package.raw_window_end, 660.0)
        self.assertEqual([sample["timestamp"] for sample in package.raw_samples], [60.0, 120.0, 240.0, 301.0, 360.0])
        self.assertEqual(package.trigger_event, event)

    def test_l1_event_does_not_build_incident_package(self):
        builder = IncidentPackageBuilder()
        event = SafetyEvent(
            event_type=SafetyEventType.WEAK_GPS,
            level=SafetyLevel.WATCH,
            timestamp=1.0,
            reason="Weak GPS.",
            confidence=0.7,
        )

        package = builder.build_for_event(event)

        self.assertIsNone(package)

    def test_event_can_override_raw_window_seconds(self):
        builder = IncidentPackageBuilder(raw_window_seconds=300)
        for timestamp in [0.0, 120.0, 180.0, 240.0, 300.0]:
            builder.observe(Observation(timestamp=timestamp, source="test", raw={"sample": timestamp}))
        event = SafetyEvent(
            event_type=SafetyEventType.ROUTE_DEVIATION,
            level=SafetyLevel.CONCERN,
            timestamp=300.0,
            reason="Outside approved corridor.",
            confidence=0.85,
        )

        package = builder.build_for_event(event, raw_window_seconds=180)

        self.assertIsNotNone(package)
        self.assertEqual(package.raw_window_start, 120.0)
        self.assertEqual(package.raw_window_end, 480.0)
        self.assertEqual([sample["timestamp"] for sample in package.raw_samples], [120.0, 180.0, 240.0, 300.0])

    def test_ai_summary_input_extracts_trigger_sample_evidence(self):
        builder = IncidentPackageBuilder(raw_window_seconds=300)
        builder.observe(
            Observation(
                timestamp=10.0,
                source="test",
                lat=25.1,
                lon=121.1,
                gps_horizontal_accuracy_m=8.0,
                raw={
                    "route_index": 42,
                    "timestamp": "2026-05-11T00:00:10Z",
                    "position_estimate": {"source": "gps", "progress_m": 120.0},
                    "recording_policy": {
                        "segment_id": "seg_02",
                        "control_zone_id": "zone_forest",
                        "control_zone_type": "forest",
                        "recording_policy_id": "policy_medium",
                        "profile": "raw_lock",
                        "safety_level": "L2_CONCERN",
                    },
                    "map_evidence": {
                        "corridor": {"inside": False, "corridor_id": "corridor_main"},
                        "hazards": [{"hazard_id": "hazard_slope", "hazard_type": "steep_slope"}],
                    },
                    "go_no_go": {"decision": {"decision": "turn_back"}},
                },
            )
        )
        event = SafetyEvent(
            event_type=SafetyEventType.ROUTE_DEVIATION,
            level=SafetyLevel.CONCERN,
            timestamp=10.0,
            reason="Outside approved corridor.",
            confidence=0.85,
            details={"evidence_source": "offline_map_corridor"},
        )

        package = builder.build_for_event(event)

        self.assertIsNotNone(package)
        summary = package.ai_summary_input
        self.assertEqual(summary["event"]["event_type"], "route_deviation")
        self.assertEqual(summary["mission_context"]["segment_id"], "seg_02")
        self.assertEqual(summary["mission_context"]["recording_profile"], "raw_lock")
        self.assertEqual(summary["route_evidence"]["position_estimate"]["source"], "gps")
        self.assertEqual(summary["map_evidence"]["hazard_ids"], ["hazard_slope"])
        self.assertEqual(summary["go_no_go"]["decision"]["decision"], "turn_back")
        self.assertEqual(summary["raw_window"]["sample_count"], 1)


if __name__ == "__main__":
    unittest.main()
