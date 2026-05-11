import tempfile
import unittest
from pathlib import Path

from observation_adapter import sensorlog_record_to_observation
from route_matching import RoutePoint, load_gpx_route
from safety_models import Observation, SafetyEventType
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"
CONTEXT_DIR = ROOT / "tests" / "fixtures" / "mission_context"


class SafetyRuntimeSessionTests(unittest.TestCase):
    def test_missing_gps_observation_records_policy_without_route_event(self):
        session = SafetyRuntimeSession(MISSION_PATH)
        observation = Observation(
            timestamp=1.0,
            source="live_sensorlog",
            raw={"capabilities": {"gps": {"status": "unavailable"}}},
        )

        update = session.observe(observation)

        self.assertIsNone(update.route_progress_sample)
        self.assertEqual(update.safety_events, [])
        self.assertEqual(update.recording_decision.profile, "low")
        self.assertEqual(update.observation.raw["recording_policy"]["profile"], "low")
        self.assertEqual(session.snapshot().observations_processed, 1)

    def test_sensorlog_observation_flows_through_route_context(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        observation = sensorlog_record_to_observation(
            {
                "loggingTime": "2026-05-11T08:52:12.450+08:00",
                "locationLatitude": str(point.lat),
                "locationLongitude": str(point.lon),
                "locationAltitude": str(point.elevation_m),
                "locationHorizontalAccuracy": "14.0",
                "heartRateBPM": "111",
                "accelerometerAccelerationX": "0.1",
            }
        )
        session = SafetyRuntimeSession(MISSION_PATH)

        update = session.observe(observation)

        self.assertIsNotNone(update.route_progress_sample)
        self.assertEqual(update.safety_state.level, "L0_NORMAL")
        self.assertEqual(update.safety_events, [])
        self.assertEqual(update.observation.raw["position_estimate"]["source"], "gps")
        self.assertEqual(update.observation.raw["map_evidence"]["corridor"]["inside"], True)
        self.assertEqual(update.observation.raw["capabilities"]["wifi_rssi"]["status"], "unavailable_by_platform")

    def test_provider_context_flows_into_live_go_no_go(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        observation = _observation_from_route_point(0, point)
        session = SafetyRuntimeSession(
            MISSION_PATH,
            mission_context_path=CONTEXT_DIR / "low_battery_near_sunset.json",
        )

        update = session.observe(observation)

        self.assertEqual(update.safety_state.level, "L2_CONCERN")
        self.assertEqual(update.safety_events[0].event_type, SafetyEventType.RESOURCE_CONSTRAINT)
        self.assertEqual(update.observation.raw["provider_context"]["resource_state"]["device_battery"], 0.14)
        self.assertEqual(update.observation.raw["provider_context"]["route_context"]["current_segment_id"], "seg_05")

    def test_off_route_stream_triggers_l2_and_persists_incident(self):
        route = load_gpx_route(OFF_ROUTE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            session = SafetyRuntimeSession(MISSION_PATH, incident_store_path=tmpdir)
            triggered = None

            for index, point in enumerate(route.points):
                update = session.observe(_observation_from_route_point(index, point))
                if any(event.event_type == SafetyEventType.ROUTE_DEVIATION for event in update.safety_events):
                    triggered = update
                    break

            self.assertIsNotNone(triggered)
            assert triggered is not None
            self.assertEqual(triggered.safety_state.level, "L2_CONCERN")
            self.assertEqual(len(triggered.incident_packages), 1)
            self.assertEqual(len(triggered.stored_incident_paths), 1)
            self.assertTrue(triggered.stored_incident_paths[0].exists())
            self.assertEqual(
                triggered.incident_packages[0].ai_summary_input["event"]["event_type"],
                "route_deviation",
            )
            snapshot = session.snapshot()
            self.assertEqual(snapshot.safety_state.level, "L2_CONCERN")
            self.assertEqual(len(snapshot.incident_packages), 1)


def _observation_from_route_point(index: int, point: RoutePoint) -> Observation:
    return Observation(
        timestamp=float(index),
        source="live_test",
        lat=point.lat,
        lon=point.lon,
        elevation_m=point.elevation_m,
        gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
        raw={
            "sensorlog": {
                "loggingTime": point.timestamp,
                "pedometerDistance": point.pedometer_distance_m,
                "pedometerNumberOfSteps": point.pedometer_steps,
            }
        },
    )


if __name__ == "__main__":
    unittest.main()
