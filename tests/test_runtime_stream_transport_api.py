import unittest
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from route_matching import RoutePoint, load_gpx_route
from runtime_observation_envelope import build_signed_runtime_observation_envelope
from runtime_stream_controls import RuntimeStreamControlStore
from runtime_stream_telemetry import RuntimeStreamTelemetryStore
from runtime_stream_transport_api import create_runtime_stream_transport_router
from safety_api import SafetyObservationAdmissionConfig
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


class RuntimeStreamTransportApiTests(unittest.TestCase):
    def test_http_push_transport_ingests_signed_observation(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = _client(session=session, admission_config=admission_config)
        envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=1,
            transport="http_push",
        )

        response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
                "received_at": 1.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["transport_surface"], "http_push")
        self.assertEqual(body["observations_accepted"], 1)
        self.assertEqual(body["admission"]["status"], "admitted_not_forwarded")
        self.assertEqual(body["admission"]["transport"], "http_push")
        self.assertEqual(session.snapshot().observations_processed, 1)

    def test_websocket_transport_ingests_signed_observation(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = _client(session=session, admission_config=admission_config)
        envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=1,
            transport="websocket",
        )

        with client.websocket_connect("/runtime/streams/websocket/observations") as websocket:
            websocket.send_json(
                {
                    "envelope": envelope.model_dump(mode="json"),
                    "payload": payload,
                    "device": "apple_watch",
                    "source": "runtime_websocket_sensorlog",
                    "received_at": 1.0,
                }
            )
            body = websocket.receive_json()

        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["transport_surface"], "websocket")
        self.assertEqual(body["observations_accepted"], 1)
        self.assertEqual(body["admission"]["status"], "admitted_not_forwarded")
        self.assertEqual(body["admission"]["transport"], "websocket")
        self.assertEqual(session.snapshot().observations_processed, 1)

    def test_transport_endpoint_mismatch_is_rejected_before_runtime(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        client = _client(session=session, admission_config=admission_config)
        envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=1,
            transport="websocket",
        )

        response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"]["reason"],
            "transport_endpoint_mismatch",
        )
        self.assertEqual(session.snapshot().observations_processed, 0)

    def test_transport_status_reports_http_acceptance_and_rejection_without_raw_payload(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        telemetry_store = RuntimeStreamTelemetryStore()
        client = _client(
            session=session,
            admission_config=admission_config,
            telemetry_store=telemetry_store,
        )
        accepted_envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=1,
            transport="http_push",
        )
        mismatch_envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=2,
            transport="websocket",
        )

        accepted = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": accepted_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        rejected = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": mismatch_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        status = client.get("/runtime/streams/status")

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(status.status_code, 200)
        body = status.json()
        http_status = body["transport_surfaces"]["http_push"]
        self.assertEqual(body["status"], "observing")
        self.assertEqual(body["totals"]["accepted_count"], 1)
        self.assertEqual(body["totals"]["rejected_count"], 1)
        self.assertEqual(http_status["accepted_count"], 1)
        self.assertEqual(http_status["rejected_count"], 1)
        self.assertEqual(http_status["last_admission_status"], "admitted_not_forwarded")
        self.assertEqual(http_status["last_rejection_reason"], "transport_endpoint_mismatch")
        self.assertEqual(body["admission_state"]["seen_dedupe_key_count"], 1)
        self.assertEqual(body["admission_state"]["backpressure_queue_depth"], 0)
        self.assertEqual(body["boundary"]["raw_payload_embedded"], False)
        self.assertEqual(body["boundary"]["incident_bridge_enabled"], False)
        serialized = json.dumps(body, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn("accelerometerAccelerationX", serialized)
        self.assertNotIn('"raw_payload":', serialized)

    def test_transport_status_reports_websocket_connection_lifecycle(self):
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        telemetry_store = RuntimeStreamTelemetryStore()
        client = _client(
            session=session,
            admission_config=admission_config,
            telemetry_store=telemetry_store,
        )

        initial = client.get("/runtime/streams/status").json()
        with client.websocket_connect("/runtime/streams/websocket/observations"):
            connected = telemetry_store.snapshot(
                admission_state=admission_config.state
            ).model_dump(mode="json")
        closed = client.get("/runtime/streams/status").json()

        self.assertEqual(initial["transport_surfaces"]["websocket"]["connection_status"], "idle")
        self.assertEqual(
            connected["transport_surfaces"]["websocket"]["connection_status"],
            "connected",
        )
        self.assertEqual(connected["totals"]["active_websocket_connections"], 1)
        self.assertEqual(
            closed["transport_surfaces"]["websocket"]["connection_status"],
            "closed",
        )
        self.assertEqual(closed["totals"]["active_websocket_connections"], 0)

    def test_operator_controls_pause_resume_end_and_drain_stream_locally(self):
        point = load_gpx_route(ROUTE_PATH).points[0]
        payload = _sensorlog_record_from_point(point)
        secret_key = "runtime-stream-secret"
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(MISSION_PATH)
        control_store = RuntimeStreamControlStore()
        client = _client(
            session=session,
            admission_config=admission_config,
            control_store=control_store,
        )

        pause = client.post(
            "/runtime/streams/control/pause",
            json={"operator_id": "admin.local", "reason": "manual pause"},
        )
        paused_envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=1,
            transport="http_push",
        )
        paused_observation = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": paused_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        resume = client.post(
            "/runtime/streams/control/resume",
            json={"operator_id": "admin.local", "reason": "resume stream"},
        )
        accepted_envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=2,
            transport="http_push",
        )
        accepted = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": accepted_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        admission_config.state.disconnected_queue_keys.append("queued-a")
        admission_config.state.backpressure_queue_keys.append("backpressure-a")
        drain = client.post(
            "/runtime/streams/control/drain-queue",
            json={"operator_id": "admin.local", "reason": "clear stale queue"},
        )
        end = client.post(
            "/runtime/streams/control/end",
            json={"operator_id": "admin.local", "reason": "trip complete"},
        )
        after_end_envelope = _signed_envelope(
            payload,
            secret_key=secret_key,
            sequence_no=3,
            transport="http_push",
        )
        after_end = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": after_end_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        status = client.get("/runtime/streams/status").json()

        self.assertEqual(pause.status_code, 200)
        self.assertEqual(pause.json()["snapshot_after"]["status"], "paused")
        self.assertEqual(paused_observation.status_code, 409)
        self.assertEqual(paused_observation.json()["detail"]["reason"], "runtime_stream_paused")
        self.assertEqual(resume.status_code, 200)
        self.assertEqual(resume.json()["snapshot_after"]["status"], "observing")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(session.snapshot().observations_processed, 1)
        self.assertEqual(drain.status_code, 200)
        self.assertEqual(drain.json()["queue_depth_before"], 2)
        self.assertEqual(drain.json()["queue_depth_after"], 0)
        self.assertEqual(admission_config.state.disconnected_queue_keys, [])
        self.assertEqual(admission_config.state.backpressure_queue_keys, [])
        self.assertEqual(end.status_code, 200)
        self.assertEqual(after_end.status_code, 409)
        self.assertEqual(after_end.json()["detail"]["reason"], "runtime_stream_ended")
        self.assertEqual(status["control"]["status"], "ended")
        self.assertEqual(status["boundary"]["incident_bridge_enabled"], False)
        self.assertEqual(status["control"]["boundary"]["phase2_writeback_count"], 0)


def _client(
    *,
    session: SafetyRuntimeSession,
    admission_config: SafetyObservationAdmissionConfig,
    telemetry_store: RuntimeStreamTelemetryStore | None = None,
    control_store: RuntimeStreamControlStore | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_runtime_stream_transport_router(
            runtime_session=session,
            observation_admission_config=admission_config,
            telemetry_store=telemetry_store,
            control_store=control_store,
        )
    )
    return TestClient(app)


def _signed_envelope(
    payload: dict,
    *,
    secret_key: str,
    sequence_no: int,
    transport: str,
):
    return build_signed_runtime_observation_envelope(
        payload,
        secret_key=secret_key,
        envelope_id=f"runtime_stream_transport.api.{sequence_no:04d}",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        transport=transport,
        device_id="watch.transport.001",
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
