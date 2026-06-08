import tempfile
import unittest
from pathlib import Path

from ins_dr_navigation import route_heading_deg
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
        self.assertEqual(update.observation.raw["position_estimate"]["source"], "gnss")
        self.assertEqual(update.observation.raw["position_estimate"]["primary_truth_source"], "raw_gnss")
        self.assertEqual(update.observation.raw["map_evidence"]["corridor"]["inside"], True)
        self.assertEqual(update.observation.raw["capabilities"]["wifi_rssi"]["status"], "unavailable_by_platform")

    def test_dr_only_sensorlog_observation_continues_after_gnss_anchor(self):
        route = load_gpx_route(ROUTE_PATH)
        anchor = route.points[100]
        session = SafetyRuntimeSession(MISSION_PATH)
        anchor_update = session.observe(
            sensorlog_record_to_observation(
                {
                    "loggingTime": "2026-05-11T08:52:12.450+08:00",
                    "locationLatitude": str(anchor.lat),
                    "locationLongitude": str(anchor.lon),
                    "locationHorizontalAccuracy": "6.0",
                    "pedometerDistance": "100.0",
                }
            )
        )
        dr_only = sensorlog_record_to_observation(
            {
                "loggingTime": "2026-05-11T08:52:22.450+08:00",
                "pedometerDistance": "128.0",
            }
        )

        update = session.observe(dr_only)

        self.assertIsNotNone(anchor_update.route_progress_sample)
        self.assertIsNotNone(update.route_progress_sample)
        self.assertIsNone(update.observation.lat)
        self.assertIsNone(update.observation.lon)
        self.assertEqual(update.observation.raw["position_estimate"]["source"], "dead_reckoning")
        self.assertEqual(update.observation.raw["position_estimate"]["primary_truth_source"], "raw_gnss+dead_reckoning")
        self.assertEqual(update.observation.raw["position_estimate"]["pdr_delta_m"], 28.0)
        assert update.route_progress_sample is not None
        assert anchor_update.route_progress_sample is not None
        self.assertGreater(update.route_progress_sample.progress_m, anchor_update.route_progress_sample.progress_m)
        self.assertTrue(update.observation.raw["map_evidence"]["corridor"]["inside"])

    def test_dr_only_odometry_observation_continues_after_gnss_anchor(self):
        route = load_gpx_route(ROUTE_PATH)
        anchor = route.points[100]
        heading = route_heading_deg(route, anchor.progress_m)
        session = SafetyRuntimeSession(MISSION_PATH)
        anchor_update = session.observe(
            Observation(
                timestamp=10.0,
                source="pi_gnss_nmea_smoke",
                lat=anchor.lat,
                lon=anchor.lon,
                gps_horizontal_accuracy_m=6.0,
                raw={"sentence_type": "GPGGA"},
            )
        )
        dr_only = Observation(
            timestamp=11.0,
            source="wheel_odometry",
            raw={
                "odometry": {
                    "distance_delta_m": 3.0,
                    "heading_deg": heading,
                }
            },
        )

        update = session.observe(dr_only)

        self.assertIsNotNone(anchor_update.route_progress_sample)
        self.assertIsNotNone(update.route_progress_sample)
        self.assertIsNone(update.observation.lat)
        self.assertIsNone(update.observation.lon)
        position_estimate = update.observation.raw["position_estimate"]
        self.assertEqual(position_estimate["source"], "dead_reckoning")
        self.assertEqual(position_estimate["primary_truth_source"], "raw_gnss+dead_reckoning")
        self.assertEqual(position_estimate["pdr_delta_m"], 3.0)
        assert update.route_progress_sample is not None
        assert anchor_update.route_progress_sample is not None
        self.assertGreater(update.route_progress_sample.progress_m, anchor_update.route_progress_sample.progress_m)

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
                    for post_index, post_point in enumerate(route.points[index + 1 : index + 6], start=index + 1):
                        session.observe(_observation_from_route_point(post_index, post_point))
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
            self.assertGreater(snapshot.incident_packages[0].raw_samples[-1]["timestamp"], triggered.incident_packages[0].triggered_at)
            self.assertEqual(
                snapshot.incident_packages[0].ai_summary_input["raw_window"]["latest_sample_timestamp"],
                snapshot.incident_packages[0].raw_samples[-1]["timestamp"],
            )


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
