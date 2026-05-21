import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from route_matching import RoutePoint, load_gpx_route
from runtime_observation_envelope import build_signed_runtime_observation_envelope
from safety_api import (
    SafetyApiSnapshot,
    SafetyObservationAdmissionConfig,
    create_safety_app,
)
from safety_models import SafetyState
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


class SafetyObservationAdmissionApiTests(unittest.TestCase):
    def test_signed_runtime_observation_is_admitted_before_safety_runtime(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "api-admission-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
                observation_admission_config=admission_config,
            )
        )
        envelope = _signed_envelope(payload, secret_key=secret_key, sequence_no=1)

        response = client.post(
            "/safety/observations",
            json={
                "envelope": envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_signed_sensorlog",
                "received_at": 1.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["observations_accepted"], 1)
        self.assertEqual(body["snapshot"]["observations_processed"], 1)
        self.assertEqual(body["ingest_surface"], "safety_api_direct")
        self.assertEqual(body["admission_transport"], "http_push")
        self.assertEqual(body["admission"]["status"], "admitted_not_forwarded")
        self.assertEqual(body["admission"]["source_id"], "runtime_source.apple_watch.v0")
        self.assertEqual(body["admission"]["device_id"], "watch.api.001")
        self.assertEqual(body["admission"]["sequence_no"], 1)
        self.assertEqual(body["admission"]["queue_depth"], 0)
        self.assertNotIn("payload", body["admission"])
        self.assertNotIn("raw_payload", body["admission"])
        self.assertEqual(admission_config.state.seen_dedupe_keys, [envelope.dedupe_key])

    def test_signed_runtime_observation_rejects_tampered_payload_before_runtime(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "api-admission-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
                observation_admission_config=admission_config,
            )
        )
        envelope = _signed_envelope(payload, secret_key=secret_key, sequence_no=1)
        tampered_payload = dict(payload)
        tampered_payload["locationLatitude"] = "25.0"

        response = client.post(
            "/safety/observations",
            json={
                "envelope": envelope.model_dump(mode="json"),
                "payload": tampered_payload,
                "device": "apple_watch",
                "source": "runtime_signed_sensorlog",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["admission_status"], "rejected_signature")
        self.assertEqual(session.snapshot().observations_processed, 0)

    def test_signed_runtime_observation_rejects_duplicate_before_runtime(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "api-admission-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
                observation_admission_config=admission_config,
            )
        )
        envelope = _signed_envelope(payload, secret_key=secret_key, sequence_no=1)
        request_body = {
            "envelope": envelope.model_dump(mode="json"),
            "payload": payload,
            "device": "apple_watch",
            "source": "runtime_signed_sensorlog",
            "received_at": 1.0,
        }

        first = client.post("/safety/observations", json=request_body)
        duplicate = client.post("/safety/observations", json=request_body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.json()["detail"]["admission_status"],
            "rejected_duplicate",
        )
        self.assertEqual(session.snapshot().observations_processed, 1)


def _signed_envelope(payload: dict, *, secret_key: str, sequence_no: int):
    return build_signed_runtime_observation_envelope(
        payload,
        secret_key=secret_key,
        envelope_id=f"runtime_observation_envelope.api.{sequence_no:04d}",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport="http_push",
        device_id="watch.api.001",
        sequence_no=sequence_no,
        observed_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
        received_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
    )


def _sensorlog_record_from_point(point: RoutePoint) -> dict:
    return {
        "loggingTime": point.timestamp,
        "locationLatitude": str(point.lat),
        "locationLongitude": str(point.lon),
        "locationAltitude": str(point.elevation_m) if point.elevation_m is not None else None,
        "locationHorizontalAccuracy": (
            str(point.gps_horizontal_accuracy_m)
            if point.gps_horizontal_accuracy_m is not None
            else "8.0"
        ),
        "pedometerDistance": point.pedometer_distance_m,
        "pedometerNumberOfSteps": point.pedometer_steps,
        "accelerometerAccelerationX": "0.1",
    }


if __name__ == "__main__":
    unittest.main()
