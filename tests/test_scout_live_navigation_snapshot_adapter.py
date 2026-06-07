from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from application_router import (
    build_default_application_router,
    observations_from_sensorlogger_message,
)
from assistant_api import create_assistant_app
from assistant_context import assistant_source_refs_from_context
from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from assistant_skill_router import (
    PRETRIP_TOOL_PLANNER_SKILL_ID,
    augment_pretrip_sources_with_local_evidence_search,
)
from ingress_evidence import IngressTransport
from pretrip_assistant_context import build_pretrip_assistant_context
from scout_ai_tool_planner import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_live_navigation_snapshot_adapter import (
    live_navigation_snapshot_from_sensor_records,
)
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_live_navigation_snapshot_adapter_merges_mqtt_like_records() -> None:
    snapshot = live_navigation_snapshot_from_sensor_records(
        [
            {
                "topic": "scout/sensors/gnss",
                "payload": {
                    "timestamp": "2026-06-07T08:00:00Z",
                    "lat": 24.051,
                    "lon": 121.22,
                    "altitude_m": 1280.5,
                    "hdop": 0.8,
                    "accuracy_m": 4.2,
                    "quality": "valid",
                    "satellites": 8,
                    "cno": [31, 42, 38],
                    "course": 44,
                    "speed_mps": 0.7,
                    "raw_nmea": "$GPRMC,redacted*00",
                },
            },
            {
                "topic": "scout/sensors/pdr",
                "payload": {
                    "timestamp": "2026-06-07T08:00:01Z",
                    "heading": 45,
                    "uncertainty_m": 6.5,
                    "source": "wearable_route_constrained",
                    "confidence": 0.82,
                    "last_anchor_at": "2026-06-07T07:59:55Z",
                    "raw_payload": {"access_token": "not-for-context"},
                },
            },
            {
                "topic": "scout/route/match",
                "payload": {
                    "nearest_route_distance_m": 12.4,
                    "route_progress_m": 14550.0,
                    "nearest_cp_id": "cp.042",
                },
            },
        ]
    )

    assert snapshot == {
        "observed_at": "2026-06-07T08:00:01Z",
        "lat": 24.051,
        "lon": 121.22,
        "elevation_m": 1280.5,
        "source": "scout/sensors/gnss",
        "hdop": 0.8,
        "horizontal_accuracy_m": 4.2,
        "fix_quality": "valid",
        "satellite_count": 8,
        "max_cno_dbhz": 42.0,
        "heading_deg": 45,
        "course_deg": 44,
        "speed_mps": 0.7,
        "nearest_route_distance_m": 12.4,
        "route_progress_m": 14550.0,
        "nearest_cp_id": "cp.042",
        "ins_dr_source": "wearable_route_constrained",
        "confidence": 0.82,
        "uncertainty_m": 6.5,
        "last_anchor_at": "2026-06-07T07:59:55Z",
    }
    assert "raw_nmea" not in snapshot
    assert "raw_payload" not in snapshot
    assert "access_token" not in str(snapshot)


def test_live_navigation_snapshot_adapter_supports_sensorlogger_payloads() -> None:
    snapshot = live_navigation_snapshot_from_sensor_records(
        [
            {
                "topic": "scout/test/alex/sensorlogger",
                "source_adapter": "sensorlogger",
                "payload": {
                    "messageId": 7,
                    "sessionId": "session-1",
                    "deviceId": "watch-1",
                    "payload": [
                        {
                            "name": "location",
                            "time": 1780555780000000000,
                            "values": {
                                "latitude": 24.12,
                                "longitude": 121.31,
                                "horizontalAccuracy": 5.0,
                                "locationCourse": 30.0,
                            },
                        },
                        {
                            "name": "pedometer",
                            "time": 1780555781000000000,
                            "values": {
                                "pedometerDistance": 112.0,
                                "heading": 31.0,
                                "confidence": 0.7,
                            },
                        },
                    ],
                },
            }
        ]
    )

    assert snapshot["observed_at"] == "2026-06-04T06:49:41Z"
    assert snapshot["lat"] == 24.12
    assert snapshot["lon"] == 121.31
    assert snapshot["horizontal_accuracy_m"] == 5.0
    assert snapshot["course_deg"] == 30.0
    assert snapshot["heading_deg"] == 31.0
    assert snapshot["confidence"] == 0.7
    assert snapshot["source"] == "sensorlogger"
    assert snapshot["ins_dr_source"] == "pedometer"


def test_adapter_snapshot_feeds_assistant_query_live_navigation_hydration() -> None:
    class FailingProvider:
        def answer(self, query: ScoutAssistantQuery, *, sources=None):
            raise RuntimeError("provider unavailable")

    snapshot = live_navigation_snapshot_from_sensor_records(
        [
            {
                "topic": "scout/sensors/gnss",
                "payload": {
                    "timestamp": "2026-06-07T08:00:00Z",
                    "lat": 24.051,
                    "lon": 121.22,
                    "altitude_m": 1280.5,
                    "hdop": 0.8,
                    "accuracy_m": 4.2,
                    "quality": "valid",
                    "satellites": 8,
                    "max_cno": 42,
                    "course": 44,
                    "speed_mps": 0.7,
                    "raw_nmea": "$GPRMC,redacted*00",
                },
            },
            {
                "topic": "scout/sensors/pdr",
                "payload": {
                    "timestamp": "2026-06-07T08:00:01Z",
                    "heading": 45,
                    "uncertainty_m": 6.5,
                    "source": "wearable_route_constrained",
                    "confidence": 0.82,
                    "last_anchor_at": "2026-06-07T07:59:55Z",
                },
            },
            {
                "topic": "scout/route/match",
                "payload": {
                    "nearest_route_distance_m": 12.4,
                    "route_progress_m": 14550.0,
                    "nearest_cp_id": "cp.042",
                },
            },
        ]
    )
    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_pretrip_router_context_resolver(PROJECT_ROOT),
        )
    )

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "哪些風險目前只是候選，不能觸發 Ln？",
            "project_id": "chilai_nanhua_day1",
            "live_navigation_snapshot": snapshot,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "registry planner fallback" in payload["answer"]
    source_ids = {source["source_id"] for source in payload["sources"]}
    assert "assistant_context.live_navigation_snapshot" in source_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in source_ids
    query_source = _source_by_id(payload, "assistant_context.live_navigation_snapshot")
    assert query_source["evidence_type"] == "live_navigation_snapshot"
    assert "raw_nmea" not in query_source["context_summary"]["live_navigation_snapshot"]
    live_summary = _source_by_id(payload, LIVE_NAVIGATION_STATE_TOOL_ID)["context_summary"]
    latest = live_summary["latest"]
    assert live_summary["hydration"]["status"] == "hydrated"
    assert latest["answerability"] == "snapshot_evidence_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["lat"] == 24.051
    assert latest["provided_fields"]["ins_dr_source"] == "wearable_route_constrained"
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert latest["boundary"]["outbound_send_performed"] is False
    assert f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}" in payload["limitations"]
    assert payload["boundary"]["phase1_mutation_allowed"] is False
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False


def test_sensorlogger_router_evidence_feeds_assistant_live_navigation_snapshot(
    tmp_path: Path,
) -> None:
    class FailingProvider:
        def answer(self, query: ScoutAssistantQuery, *, sources=None):
            raise RuntimeError("provider unavailable")

    router = build_default_application_router(record_dir=tmp_path, route_path=ROUTE_PATH)
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    first_message = {
        "messageId": 11,
        "sessionId": "session-1",
        "deviceId": "watch-1",
        "payload": [
            {
                "name": "location",
                "time": 1780555780000000000,
                "values": {
                    "latitude": anchor.lat,
                    "longitude": anchor.lon,
                    "locationAltitude": 1280.5,
                    "horizontalAccuracy": 4.2,
                    "locationCourse": 44,
                    "speed": 0.7,
                    "hdop": 0.8,
                    "fix_quality": "valid",
                    "satellites": 8,
                    "max_cno": 42,
                    "raw_nmea": "$GPRMC,redacted*00",
                },
            },
            {
                "name": "pedometer",
                "time": 1780555780000000000,
                "values": {"pedometerDistance": 100.0},
            },
        ],
    }
    second_message = {
        "messageId": 12,
        "sessionId": "session-1",
        "deviceId": "watch-1",
        "payload": [
            {
                "name": "pedometer",
                "time": 1780555790000000000,
                "values": {
                    "pedometerDistance": 112.0,
                    "heading": 45,
                    "confidence": 0.82,
                    "uncertainty_m": 6.5,
                    "last_anchor_at": "2026-06-04T06:49:40Z",
                },
            }
        ],
    }

    _dispatch_sensorlogger_message(router, first_message, ingress_id="ingress-11")
    _dispatch_sensorlogger_message(router, second_message, ingress_id="ingress-12")
    output_records = [output.model_dump(mode="json") for output in router.filter_outputs]
    latest_navigation_output = [
        record
        for record in output_records
        if record["output_kind"] == "navigation_estimate"
    ][-1]

    snapshot = live_navigation_snapshot_from_sensor_records(
        [
            {
                "topic": "scout/test/alex/sensorlogger",
                "source_adapter": "sensorlogger",
                "payload": first_message,
            },
            {
                "topic": "scout/test/alex/sensorlogger",
                "source_adapter": "sensorlogger",
                "payload": second_message,
            },
            *output_records,
            {
                "source": "route_match_fixture",
                "route_match": {
                    "nearest_route_distance_m": 12.4,
                    "nearest_cp_id": "cp.042",
                },
            },
        ]
    )

    assert snapshot["lat"] == anchor.lat
    assert snapshot["lon"] == anchor.lon
    assert snapshot["route_progress_m"] == latest_navigation_output["output_summary"]["progress_m"]
    assert snapshot["ins_dr_source"] == "dead_reckoning"
    assert snapshot["nearest_route_distance_m"] == 12.4
    assert snapshot["nearest_cp_id"] == "cp.042"
    assert "raw_nmea" not in snapshot

    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_pretrip_router_context_resolver(PROJECT_ROOT),
        )
    )
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "我現在是不是離主路太近但站在危險邊緣？",
            "project_id": "chilai_nanhua_day1",
            "live_navigation_snapshot": snapshot,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    live_summary = _source_by_id(payload, LIVE_NAVIGATION_STATE_TOOL_ID)["context_summary"]
    latest = live_summary["latest"]
    assert live_summary["hydration"]["status"] == "hydrated"
    assert latest["answerability"] == "snapshot_evidence_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["route_progress_m"] == snapshot["route_progress_m"]
    assert latest["provided_fields"]["ins_dr_source"] == "dead_reckoning"
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert latest["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False


def _pretrip_router_context_resolver(project_root: Path):
    def resolve(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        context = build_pretrip_assistant_context(
            query.project_id or query.context_ref or project_root.name,
            selected_source_id=query.selected_artifact_id,
        )
        sources = assistant_source_refs_from_context(context, query=query)
        return augment_pretrip_sources_with_local_evidence_search(
            query,
            sources=sources,
            project_root=project_root,
            limit=5,
        )

    return resolve


def _dispatch_sensorlogger_message(router, message: dict[str, object], ingress_id: str):
    records = []
    for observation in observations_from_sensorlogger_message(
        message,
        ingress_transport=IngressTransport.WAN_MQTT,
        source_adapter="sensorlogger",
        received_at="2026-06-05T00:00:00Z",
        payload_sha256="a" * 64,
        ingress_id=ingress_id,
    ):
        records.extend(router.dispatch(observation))
    return records


def _source_by_id(payload: dict[str, object], source_id: str) -> dict[str, object]:
    for source in payload["sources"]:
        if source["source_id"] == source_id:
            return source
    raise AssertionError(f"missing source {source_id}")
