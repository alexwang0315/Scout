import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from incident_store import IncidentStore
from replay_runner import replay_route
from route_matching import RoutePoint, load_gpx_route
from safety_api import SafetyApiSnapshot, create_safety_app, snapshot_from_replay_result
from safety_models import SafetyEventType, SafetyState
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


class SafetyApiTests(unittest.TestCase):
    def test_ack_state_incident_and_capsule_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = replay_route(MISSION_PATH, OFF_ROUTE_PATH, incident_store_path=tmpdir)
            incident_id = result.incident_packages[0].incident_id
            app = create_safety_app(
                snapshot=snapshot_from_replay_result(result),
                incident_store=IncidentStore(tmpdir),
            )
            client = TestClient(app)

            ack = client.post(
                "/safety/ack",
                json={
                    "requester_id": "responder-01",
                    "reason": "nearby pull check",
                    "last_known_route_id": "normal_climb",
                },
            )
            self.assertEqual(ack.status_code, 200)
            ack_payload = ack.json()
            self.assertEqual(ack_payload["safety_state"]["level"], "L2_CONCERN")
            self.assertEqual(ack_payload["latest_incident_id"], incident_id)
            self.assertTrue(ack_payload["package_available"])
            self.assertIsNotNone(ack_payload["last_known_position"])

            state = client.get("/safety/state")
            self.assertEqual(state.status_code, 200)
            self.assertEqual(state.json()["latest_incident_id"], incident_id)
            self.assertEqual(
                state.json()["safety_state"]["active_events"][0]["event_type"],
                "route_deviation",
            )

            incident = client.get(f"/safety/incidents/{incident_id}")
            self.assertEqual(incident.status_code, 200)
            self.assertEqual(incident.json()["ai_summary_input"]["event"]["event_type"], "route_deviation")

            checkins = client.get("/safety/checkins")
            self.assertEqual(checkins.status_code, 200)
            self.assertGreaterEqual(len(checkins.json()["checkins"]), 1)
            capsule_id = checkins.json()["segment_capsules"][0]["capsule_id"]

            capsule = client.get(f"/safety/capsules/{capsule_id}")
            self.assertEqual(capsule.status_code, 200)
            self.assertEqual(capsule.json()["capsule_id"], capsule_id)

    def test_missing_incident_and_capsule_return_404(self):
        result = replay_route(MISSION_PATH, OFF_ROUTE_PATH)
        client = TestClient(create_safety_app(snapshot=snapshot_from_replay_result(result)))

        self.assertEqual(client.get("/safety/incidents/missing").status_code, 404)
        self.assertEqual(client.get("/safety/capsules/missing").status_code, 404)

    def test_live_observation_ingest_accepts_sensorlog_payload(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
            )
        )

        response = client.post(
            "/safety/observations",
            json={
                "payload": _sensorlog_record_from_point(point),
                "device": "apple_watch",
                "received_at": 1.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["observations_accepted"], 1)
        self.assertEqual(payload["safety_level"], "L0_NORMAL")
        self.assertEqual(payload["snapshot"]["observations_processed"], 1)
        self.assertEqual(payload["latest_capabilities"]["wifi_rssi"]["status"], "unavailable_by_platform")
        self.assertEqual(payload["recording_profiles"], ["low"])

    def test_live_observation_ingest_accepts_raw_batch_body(self):
        route = load_gpx_route(ROUTE_PATH)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
            )
        )

        response = client.post(
            "/safety/observations",
            json={"imu_data": [_sensorlog_record_from_point(point) for point in route.points[:2]]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["observations_accepted"], 2)
        self.assertEqual(payload["snapshot"]["observations_processed"], 2)
        self.assertEqual(payload["safety_events"], [])

    def test_live_observation_ingest_rejects_invalid_payload(self):
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
            )
        )

        response = client.post("/safety/observations", json={"payload": "not-sensorlog"})

        self.assertEqual(response.status_code, 422)

    def test_live_observation_ingest_triggers_l2_and_dynamic_state(self):
        route = load_gpx_route(OFF_ROUTE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            session = SafetyRuntimeSession(MISSION_PATH, incident_store_path=tmpdir)
            client = TestClient(
                create_safety_app(
                    SafetyApiSnapshot(safety_state=SafetyState()),
                    incident_store=IncidentStore(tmpdir),
                    runtime_session=session,
                )
            )

            response = client.post(
                "/safety/observations",
                json={
                    "payload": {
                        "imu_data": [_sensorlog_record_from_point(point) for point in route.points]
                    },
                    "device": "apple_watch",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["safety_level"], "L2_CONCERN")
            self.assertIn(
                SafetyEventType.ROUTE_DEVIATION,
                [event["event_type"] for event in payload["safety_events"]],
            )
            self.assertEqual(len(payload["incident_ids"]), 1)
            self.assertEqual(len(payload["stored_incident_paths"]), 1)

            state = client.get("/safety/state")
            self.assertEqual(state.status_code, 200)
            self.assertEqual(state.json()["safety_state"]["level"], "L2_CONCERN")
            self.assertEqual(state.json()["latest_incident_id"], payload["incident_ids"][0])


def _sensorlog_record_from_point(point: RoutePoint) -> dict:
    return {
        "loggingTime": point.timestamp,
        "locationLatitude": str(point.lat),
        "locationLongitude": str(point.lon),
        "locationAltitude": str(point.elevation_m) if point.elevation_m is not None else None,
        "locationHorizontalAccuracy": (
            str(point.gps_horizontal_accuracy_m) if point.gps_horizontal_accuracy_m is not None else "8.0"
        ),
        "pedometerDistance": point.pedometer_distance_m,
        "pedometerNumberOfSteps": point.pedometer_steps,
        "accelerometerAccelerationX": "0.1",
    }


if __name__ == "__main__":
    unittest.main()
