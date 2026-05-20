import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from incident_store import IncidentStore
from route_matching import load_gpx_route
from safety_models import IncidentPackage, SafetyEvent, SafetyEventType, SafetyLevel
from scout_pi_runtime import create_pi_runtime_app


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


class ScoutPiRuntimeTests(unittest.TestCase):
    def test_health_runtime_and_provider_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_pi_runtime_app(
                {
                    "SCOUT_DATA_ROOT": tmpdir,
                    "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                    "SCOUT_SAFETY_INCIDENT_STORE": str(Path(tmpdir) / "incidents"),
                }
            )
            client = TestClient(app)

            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "ok")
            self.assertEqual(health.json()["runtime_profile"], "pi-field")
            self.assertEqual(health.json()["data_root"], tmpdir)
            self.assertEqual(
                health.json()["storage"]["required_directories"],
                ["missions", "incidents", "capsules", "raw_ring", "logs", "providers", "tmp"],
            )
            self.assertEqual(health.json()["storage"]["missing_directories"], [])
            self.assertEqual(health.json()["optional_features"]["event_bus"], "none")
            self.assertFalse(health.json()["optional_features"]["live_hardware_enabled"])
            self.assertFalse(health.json()["optional_features"]["ai_inference_enabled"])
            self.assertFalse(health.json()["optional_features"]["local_model_enabled"])

            runtime = client.get("/runtime/status")
            self.assertEqual(runtime.status_code, 200)
            self.assertTrue(runtime.json()["safety_runtime_enabled"])
            self.assertEqual(runtime.json()["observations_processed"], 0)
            self.assertEqual(runtime.json()["data_root"], tmpdir)
            self.assertEqual(runtime.json()["event_bus"], "none")

            providers = client.get("/providers/status")
            self.assertEqual(providers.status_code, 200)
            self.assertFalse(providers.json()["live_hardware_enabled"])
            self.assertEqual(providers.json()["provider_contract"], "fixture_or_degraded_step1")
            self.assertEqual(providers.json()["providers"][0]["provider_id"], "gnss.position")
            self.assertTrue(all(item["control_allowed"] is False for item in providers.json()["providers"]))

    def test_safety_observation_ingest_updates_runtime_status(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_pi_runtime_app(
                {
                    "SCOUT_DATA_ROOT": tmpdir,
                    "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                    "SCOUT_SAFETY_INCIDENT_STORE": str(Path(tmpdir) / "incidents"),
                }
            )
            client = TestClient(app)

            response = client.post(
                "/safety/observations",
                json={
                    "payload": _sensorlog_record_from_point(point),
                    "device": "apple_watch",
                    "received_at": 1.0,
                },
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["observations_accepted"], 1)
            self.assertEqual(response.json()["safety_level"], "L0_NORMAL")

            runtime = client.get("/runtime/status")
            self.assertEqual(runtime.json()["observations_processed"], 1)

    def test_data_root_layout_and_incident_store_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            incident_store_path = data_root / "incidents"
            env = {
                "SCOUT_DATA_ROOT": str(data_root),
                "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                "SCOUT_SAFETY_INCIDENT_STORE": str(incident_store_path),
            }

            first_app = create_pi_runtime_app(env)
            first_client = TestClient(first_app)
            self.assertEqual(first_client.get("/health").status_code, 200)

            for child in ("missions", "incidents", "capsules", "raw_ring", "logs", "providers", "tmp"):
                self.assertTrue((data_root / child).is_dir())

            package = _incident_package()
            IncidentStore(incident_store_path).save(package)

            restarted_app = create_pi_runtime_app(env)
            restarted_client = TestClient(restarted_app)
            incident = restarted_client.get(f"/safety/incidents/{package.incident_id}")

            self.assertEqual(incident.status_code, 200)
            self.assertEqual(incident.json()["incident_id"], package.incident_id)
            self.assertEqual(restarted_client.get("/runtime/status").json()["stored_incidents"], 1)

    def test_step1_blocks_live_hardware_ai_and_event_bus_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_pi_runtime_app(
                {
                    "SCOUT_DATA_ROOT": tmpdir,
                    "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                    "SCOUT_ENABLE_LIVE_HARDWARE": "1",
                    "SCOUT_ENABLE_AI_INFERENCE": "1",
                    "SCOUT_ENABLE_LOCAL_MODEL": "1",
                    "SCOUT_EVENT_BUS": "mqtt",
                }
            )
            client = TestClient(app)

            health = client.get("/health")

            self.assertEqual(health.status_code, 503)
            self.assertEqual(health.json()["status"], "degraded")
            self.assertEqual(
                health.json()["step1_blockers"],
                [
                    "live_hardware_must_stay_disabled_for_step1",
                    "ai_inference_must_stay_disabled_for_step1",
                    "local_model_must_stay_disabled_for_step1",
                    "event_bus_must_stay_none_for_step1",
                ],
            )


def _sensorlog_record_from_point(point):
    return {
        "loggingTime": point.timestamp,
        "locationLatitude(WGS84)": point.lat,
        "locationLongitude(WGS84)": point.lon,
        "locationAltitude(m)": point.elevation_m,
        "locationSpeed(m/s)": 0.8,
        "locationCourse(°)": 90.0,
        "locationHorizontalAccuracy(m)": 5.0,
        "accelerometerAccelerationX(G)": 0.01,
        "accelerometerAccelerationY(G)": 0.02,
        "accelerometerAccelerationZ(G)": 0.98,
        "motionYaw(rad)": 0.0,
        "motionPitch(rad)": 0.0,
        "motionRoll(rad)": 0.0,
        "batteryLevel(%)": 90.0,
    }


def _incident_package():
    return IncidentPackage(
        incident_id="incident_pi_restart_smoke_12",
        trigger_level=SafetyLevel.CONCERN,
        triggered_at=12.0,
        trigger_event=SafetyEvent(
            event_type=SafetyEventType.ROUTE_DEVIATION,
            level=SafetyLevel.CONCERN,
            timestamp=12.0,
            reason="Persisted package restart smoke.",
            confidence=0.82,
        ),
        raw_window_start=-168.0,
        raw_window_end=192.0,
        raw_samples=[{"timestamp": 12.0, "raw": {"sample": "trigger"}}],
        ai_summary_input={"event": {"event_type": "route_deviation"}},
    )
