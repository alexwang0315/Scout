from __future__ import annotations

import inspect
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime_stream_status_surface
from runtime_input_admission import RuntimeInputAdmissionState
from runtime_stream_controls import RuntimeStreamControlStore
from runtime_stream_status_surface import (
    READ_ONLY_STATUS_ROUTE,
    build_runtime_stream_status_surface,
    create_runtime_stream_status_router,
)
from runtime_stream_telemetry import RuntimeStreamTelemetryStore


def test_status_surface_combines_policy_telemetry_control_and_provider_policy() -> None:
    telemetry_store = RuntimeStreamTelemetryStore()
    control_store = RuntimeStreamControlStore()
    admission_state = RuntimeInputAdmissionState()
    admission_state.seen_dedupe_keys.append("runtime-stream-test-key")

    snapshot = build_runtime_stream_status_surface(
        telemetry_store=telemetry_store,
        control_store=control_store,
        admission_state=admission_state,
    )
    payload = snapshot.model_dump(mode="json")

    assert payload["artifact_kind"] == "runtime_stream_status_surface"
    assert payload["status"] == "read_only_status_ready"
    assert payload["policy"]["artifact_kind"] == "runtime_stream_policy_manifest"
    assert payload["policy"]["boundary"]["creates_live_endpoint"] is False
    assert payload["telemetry"]["artifact_kind"] == "runtime_stream_telemetry_snapshot"
    assert payload["telemetry"]["admission_state"]["seen_dedupe_key_count"] == 1
    assert payload["control"]["artifact_kind"] == "runtime_stream_control_snapshot"
    assert payload["control"]["status"] == "observing"
    assert payload["remote_provider_policy"]["status"] == "policy_ready_not_connected"
    assert payload["remote_provider_policy"]["boundary"]["sends_network_request"] is False
    assert payload["boundary"]["transport_routes_mounted"] is False
    assert payload["boundary"]["observation_ingest_allowed"] is False
    assert payload["boundary"]["stream_control_mutation_allowed"] is False
    assert payload["boundary"]["live_provider_send_allowed"] is False
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["raw_payloads_embedded"] is False
    assert payload["boundary"]["route_inventory"] == [READ_ONLY_STATUS_ROUTE]


def test_status_surface_router_exposes_only_get_read_only_status_route() -> None:
    app = FastAPI()
    app.include_router(create_runtime_stream_status_router())
    client = TestClient(app)

    route_methods = {
        route.path: sorted(route.methods or [])
        for route in app.routes
        if route.path.startswith("/runtime/streams")
    }

    assert route_methods == {"/runtime/streams/status-read-only": ["GET"]}
    response = client.get("/runtime/streams/status-read-only")
    blocked_post = client.post("/runtime/streams/status-read-only", json={})

    assert response.status_code == 200
    assert response.json()["boundary"]["read_only_surface"] is True
    assert blocked_post.status_code == 405


def test_status_surface_can_report_separately_mounted_live_transport_routes() -> None:
    snapshot = build_runtime_stream_status_surface(
        transport_routes_mounted=True,
        live_provider_send_allowed=True,
    )
    payload = snapshot.model_dump(mode="json")

    assert payload["boundary"]["read_only_surface"] is True
    assert payload["boundary"]["transport_routes_mounted"] is True
    assert payload["boundary"]["observation_ingest_allowed"] is True
    assert payload["boundary"]["stream_control_mutation_allowed"] is True
    assert payload["boundary"]["live_provider_send_allowed"] is True
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert "POST /runtime/streams/http-push/observations" in payload["boundary"]["route_inventory"]
    assert "live transport routes are mounted separately" in payload["notes"][0]


def test_status_surface_does_not_embed_raw_payloads_or_import_live_transport_api() -> None:
    snapshot = build_runtime_stream_status_surface().model_dump(mode="json")
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    source = inspect.getsource(runtime_stream_status_surface)

    assert "locationLatitude" not in serialized
    assert "accelerometerAccelerationX" not in serialized
    assert '"payload":' not in serialized
    assert "runtime_stream_transport_api" not in source
    assert "create_runtime_stream_transport_router" not in source
    assert "from safety_api" not in source
    assert "import safety_api" not in source
    assert "incident_store" not in source
    assert "ObservedFact" not in source
    assert "requests.post" not in source
    assert "requests.get" not in source
    assert "httpx." not in source
    assert "urllib" not in source
