import tempfile
import unittest
import json
from pathlib import Path

from fastapi.testclient import TestClient

from incident_store import IncidentStore
from route_matching import load_gpx_route
from safety_models import IncidentPackage, SafetyEvent, SafetyEventType, SafetyLevel
from scout_pi_runtime import create_pi_runtime_app
from live_runtime_enablement import HardwareProviderControlPolicy


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
            self.assertFalse(
                health.json()["optional_features"]["runtime_stream_status_enabled"]
            )
            self.assertEqual(client.get("/runtime/streams/status-read-only").status_code, 404)

            runtime = client.get("/runtime/status")
            self.assertEqual(runtime.status_code, 200)
            self.assertTrue(runtime.json()["safety_runtime_enabled"])
            self.assertEqual(runtime.json()["observations_processed"], 0)
            self.assertEqual(runtime.json()["data_root"], tmpdir)
            self.assertEqual(runtime.json()["event_bus"], "none")
            self.assertFalse(runtime.json()["runtime_stream_status_enabled"])

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

    def test_runtime_stream_status_surface_is_opt_in_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_pi_runtime_app(
                {
                    "SCOUT_DATA_ROOT": tmpdir,
                    "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                    "SCOUT_SAFETY_INCIDENT_STORE": str(Path(tmpdir) / "incidents"),
                    "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                }
            )
            client = TestClient(app)

            route_methods = {
                route.path: sorted(route.methods or [])
                for route in app.routes
                if route.path.startswith("/runtime/streams")
            }
            response = client.get("/runtime/streams/status-read-only")
            blocked_post = client.post("/runtime/streams/status-read-only", json={})

            self.assertEqual(
                route_methods,
                {"/runtime/streams/status-read-only": ["GET"]},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["artifact_kind"], "runtime_stream_status_surface")
            self.assertTrue(payload["boundary"]["read_only_surface"])
            self.assertFalse(payload["boundary"]["transport_routes_mounted"])
            self.assertFalse(payload["boundary"]["observation_ingest_allowed"])
            self.assertFalse(payload["boundary"]["stream_control_mutation_allowed"])
            self.assertFalse(payload["boundary"]["live_provider_send_allowed"])
            self.assertFalse(payload["boundary"]["safety_mutation_allowed"])
            self.assertEqual(blocked_post.status_code, 405)
            self.assertTrue(
                client.get("/health").json()["optional_features"][
                    "runtime_stream_status_enabled"
                ]
            )
            self.assertTrue(
                client.get("/runtime/status").json()["runtime_stream_status_enabled"]
            )

    def test_live_runtime_profile_mounts_stream_assistant_and_authorized_provider_control(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            assistant_config = data_root / "assistant-models.json"
            assistant_config.write_text(
                json.dumps(
                    {
                        "active_profile": "cloud",
                        "cloud_model": {
                            "profile": "cloud",
                            "model_name": "gpt-4.1-mini",
                            "base_url": "https://api.openai.com/v1",
                            "token_env_var": "SCOUT_CLOUD_MODEL_TOKEN",
                        },
                        "local_model": {
                            "profile": "local",
                            "model_name": "qwen2.5:0.5b",
                            "base_url": "http://scout-ollama:11434/v1",
                        },
                        "connect_on_startup": False,
                        "fallback_to_local_on_error": True,
                        "local_fallback_fixed_schema": True,
                    }
                ),
                encoding="utf-8",
            )
            hardware_policy = data_root / "hardware-control-policy.json"
            hardware_policy.write_text(
                HardwareProviderControlPolicy(
                    policy_id="hardware_control_policy.pi5_live.v0",
                    allowed_provider_refs=["provider.gnss.live.v0"],
                    allowed_actions=["read_provider_status", "set_device_mode"],
                ).to_json(),
                encoding="utf-8",
            )
            env = {
                "SCOUT_DATA_ROOT": str(data_root),
                "SCOUT_RUNTIME_PROFILE": "pi-field-live",
                "SCOUT_ENABLE_LIVE_RUNTIME": "1",
                "SCOUT_ENABLE_LIVE_HARDWARE": "1",
                "SCOUT_ENABLE_AI_INFERENCE": "1",
                "SCOUT_ENABLE_LOCAL_MODEL": "1",
                "SCOUT_REMOTE_PROVIDER_LIVE_SEND_ENABLED": "1",
                "SCOUT_RUNTIME_STREAM_STATUS_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "runtime-stream-secret",
                "SCOUT_SAFETY_MISSION_GRAPH": str(MISSION_PATH),
                "SCOUT_SAFETY_INCIDENT_STORE": str(data_root / "incidents"),
                "SCOUT_AI_ASSISTANT_ENABLED": "1",
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(assistant_config),
                "SCOUT_CLOUD_MODEL_TOKEN": "cloud-token",
                "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                "SCOUT_REMOTE_WEBHOOK_TOKEN": "provider-token",
                "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac-secret",
                "SCOUT_REMOTE_PRIMARY_TARGET_REF": "primary-target",
                "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup-target",
                "SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH": str(hardware_policy),
                "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN": "hardware-control-token",
            }
            app = create_pi_runtime_app(env)
            client = TestClient(app)

            health = client.get("/health")
            stream_post = client.post("/runtime/streams/http-push/observations", json={})
            stream_status = client.get("/runtime/streams/status-read-only")
            assistant_status = client.get("/assistant/status")
            providers = client.get("/providers/status")
            unauthorized_control_status = client.get("/providers/control/status")
            control_status = client.get(
                "/providers/control/status",
                headers={"Authorization": "Bearer hardware-control-token"},
            )
            stream_control_status = client.get("/runtime/streams/control/status")
            unauthorized_stream_pause = client.post(
                "/runtime/streams/control/pause",
                json={"operator_id": "operator.admin.local", "reason": "smoke"},
            )
            authorized_stream_pause = client.post(
                "/runtime/streams/control/pause",
                headers={"Authorization": "Bearer hardware-control-token"},
                json={"operator_id": "operator.admin.local", "reason": "smoke"},
            )
            authorized_stream_resume = client.post(
                "/runtime/streams/control/resume",
                headers={"Authorization": "Bearer hardware-control-token"},
                json={"operator_id": "operator.admin.local", "reason": "resume"},
            )
            unauthorized_control = client.post(
                "/providers/control/provider.gnss.live.v0/actions/read_provider_status",
                json={"operator_id": "operator.admin.local", "reason": "smoke"},
            )
            authorized_control = client.post(
                "/providers/control/provider.gnss.live.v0/actions/read_provider_status",
                headers={"Authorization": "Bearer hardware-control-token"},
                json={"operator_id": "operator.admin.local", "reason": "smoke"},
            )

            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["runtime_profile"], "pi-field-live")
            self.assertEqual(health.json()["live_enablement"]["status"], "live_enablement_ready")
            self.assertTrue(health.json()["optional_features"]["live_runtime_enabled"])
            self.assertTrue(health.json()["optional_features"]["runtime_stream_transport_enabled"])
            self.assertTrue(health.json()["optional_features"]["remote_provider_live_send_enabled"])
            self.assertTrue(health.json()["optional_features"]["local_model_enabled"])
            self.assertTrue(health.json()["optional_features"]["hardware_provider_control_enabled"])
            self.assertEqual(stream_post.status_code, 422)
            self.assertTrue(stream_status.json()["boundary"]["transport_routes_mounted"])
            self.assertTrue(stream_status.json()["boundary"]["observation_ingest_allowed"])
            self.assertTrue(stream_status.json()["boundary"]["stream_control_mutation_allowed"])
            self.assertTrue(stream_status.json()["boundary"]["live_provider_send_allowed"])
            self.assertFalse(stream_status.json()["boundary"]["safety_mutation_allowed"])
            self.assertEqual(assistant_status.status_code, 200)
            self.assertEqual(assistant_status.json()["provider"], "pydantic_ai")
            self.assertTrue(assistant_status.json()["config_loaded"])
            self.assertEqual(providers.json()["provider_contract"], "live_control_policy")
            self.assertTrue(providers.json()["providers"][0]["control_allowed"])
            self.assertEqual(control_status.status_code, 200)
            self.assertEqual(control_status.json()["policy_id"], "hardware_control_policy.pi5_live.v0")
            self.assertEqual(stream_control_status.status_code, 200)
            self.assertTrue(stream_control_status.json()["operator_authorization_required"])
            self.assertFalse(stream_control_status.json()["token_value_exposed"])
            self.assertEqual(unauthorized_stream_pause.status_code, 401)
            self.assertEqual(authorized_stream_pause.status_code, 200)
            self.assertEqual(
                authorized_stream_pause.json()["snapshot_after"]["status"],
                "paused",
            )
            self.assertEqual(authorized_stream_resume.status_code, 200)
            self.assertEqual(
                authorized_stream_resume.json()["snapshot_after"]["status"],
                "observing",
            )
            self.assertEqual(unauthorized_control_status.status_code, 401)
            self.assertEqual(
                unauthorized_control_status.json()["detail"]["reason"],
                "hardware_control_auth_required",
            )
            self.assertEqual(unauthorized_control.status_code, 401)
            self.assertEqual(authorized_control.status_code, 200)
            body = authorized_control.json()
            self.assertEqual(body["status"], "control_command_recorded")
            self.assertTrue(body["provider_control_authorized"])
            self.assertFalse(body["hardware_driver_invoked"])
            self.assertFalse(body["safety_mutation_allowed"])
            self.assertFalse(body["outbound_send_allowed"])


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
