from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from assistant_api import create_assistant_app
from assistant_context import (
    assistant_source_refs_from_context,
    create_assistant_context_resolver,
)
from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from assistant_skill_router import augment_pretrip_sources_with_local_evidence_search
from pretrip_assistant_context import build_pretrip_assistant_context
from route_matching import load_gpx_route
from scout_ai_tool_planner import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_live_navigation_snapshot_evidence import (
    LIVE_NAVIGATION_EVIDENCE_SOURCE_ID,
    augment_sources_with_live_navigation_snapshot_evidence,
    build_live_navigation_snapshot_source_from_evidence_dir,
)
from scout_sensorlogger_mqtt_observer import (
    SensorLoggerMqttObserver,
    SensorLoggerMqttObserverConfig,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_live_navigation_snapshot_source_loads_sensorlogger_evidence_dir(
    tmp_path: Path,
) -> None:
    observer = _write_sensorlogger_navigation_evidence(tmp_path)

    source = build_live_navigation_snapshot_source_from_evidence_dir(observer.config.evidence_dir)

    assert source is not None
    assert source.source_id == LIVE_NAVIGATION_EVIDENCE_SOURCE_ID
    assert source.evidence_type == "live_navigation_snapshot"
    summary = source.context_summary
    assert summary is not None
    snapshot = summary["live_navigation_snapshot"]
    assert snapshot["lat"] == _route_anchor().lat
    assert snapshot["lon"] == _route_anchor().lon
    assert snapshot["horizontal_accuracy_m"] == 4.2
    assert snapshot["fix_quality"] == "valid"
    assert snapshot["satellite_count"] == 8
    assert snapshot["max_cno_dbhz"] == 42
    assert snapshot["heading_deg"] == 45
    assert snapshot["course_deg"] == 44
    assert snapshot["speed_mps"] == 0.7
    assert snapshot["route_progress_m"] > 0
    assert snapshot["ins_dr_source"] == "dead_reckoning"
    assert "nearest_route_distance_m" in summary["missing_fields"]
    assert "nearest_cp_id" in summary["missing_fields"]
    assert summary["raw_payloads_embedded"] is False
    assert summary["boundary"]["safety_api_called"] is False
    assert "raw_nmea" not in json.dumps(summary, ensure_ascii=False)
    assert "raw_payload_text" not in json.dumps(summary, ensure_ascii=False)


def test_live_navigation_evidence_source_hydrates_assistant_query(
    tmp_path: Path,
) -> None:
    class FailingProvider:
        def answer(self, query: ScoutAssistantQuery, *, sources=None):
            raise RuntimeError("provider unavailable")

    observer = _write_sensorlogger_navigation_evidence(tmp_path)
    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_pretrip_evidence_context_resolver(
                PROJECT_ROOT,
                evidence_dir=observer.config.evidence_dir,
            ),
        )
    )

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "我現在是不是離主路太近但站在危險邊緣？",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    source_ids = {source["source_id"] for source in payload["sources"]}
    assert LIVE_NAVIGATION_EVIDENCE_SOURCE_ID in source_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in source_ids
    live_summary = _source_by_id(payload, LIVE_NAVIGATION_STATE_TOOL_ID)["context_summary"]
    latest = live_summary["latest"]
    assert live_summary["hydration"]["status"] == "hydrated"
    assert live_summary["hydration"]["source_id"] == LIVE_NAVIGATION_EVIDENCE_SOURCE_ID
    assert latest["answerability"] == "snapshot_missing_required_fields"
    assert "nearest_route_distance_m" in latest["missing_fields"]
    assert "nearest_cp_id" in latest["missing_fields"]
    assert latest["provided_fields"]["ins_dr_source"] == "dead_reckoning"
    assert latest["provided_fields"]["lat"] == _route_anchor().lat
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert latest["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False


def test_live_navigation_evidence_project_without_local_route_reports_missing_route_path(
    tmp_path: Path,
) -> None:
    observer = _write_sensorlogger_navigation_evidence(tmp_path)

    source = build_live_navigation_snapshot_source_from_evidence_dir(
        observer.config.evidence_dir,
        project_root=PROJECT_ROOT,
    )

    assert source is not None
    summary = source.context_summary
    assert summary is not None
    source_report = summary["source_report"]
    route_resolution = _report_by_kind(
        source_report,
        "live_navigation_route_path_resolution",
    )
    assert route_resolution["status"] == "missing_route_path"
    assert route_resolution["runtime_safety_truth"] is False
    assert any(
        ref.get("artifact_id") == "artifact:gpx:chilai_nanhua_day1"
        and ref.get("kind") == "gpx"
        for ref in route_resolution["route_source_refs"]
    )
    assert any(report.get("status") == "missing_route_path" for report in source_report)
    assert "nearest_route_distance_m" in summary["missing_fields"]
    assert "nearest_cp_id" in summary["missing_fields"]


def test_live_navigation_evidence_route_match_enrichment_completes_snapshot(
    tmp_path: Path,
) -> None:
    class FailingProvider:
        def answer(self, query: ScoutAssistantQuery, *, sources=None):
            raise RuntimeError("provider unavailable")

    observer = _write_sensorlogger_navigation_evidence(tmp_path)
    route_match_project = _write_route_match_project(tmp_path / "route_match_project")
    source = build_live_navigation_snapshot_source_from_evidence_dir(
        observer.config.evidence_dir,
        project_root=route_match_project,
    )
    assert source is not None
    summary = source.context_summary
    assert summary is not None
    snapshot = summary["live_navigation_snapshot"]
    assert snapshot["nearest_route_distance_m"] <= 0.001
    assert snapshot["nearest_cp_id"] == "cp.anchor"
    assert summary["missing_fields"] == []
    assert any(
        report.get("enricher_id") == "scout.ai.live_navigation_snapshot.route_match_enrich.v0"
        and report.get("status") == "enriched"
        for report in summary["source_report"]
    )

    client = TestClient(
        create_assistant_app(
            provider=FailingProvider(),
            context_resolver=_pretrip_evidence_context_resolver(
                PROJECT_ROOT,
                evidence_dir=observer.config.evidence_dir,
                route_match_project_root=route_match_project,
            ),
        )
    )
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "我現在是不是離主路太近但站在危險邊緣？",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    live_summary = _source_by_id(payload, LIVE_NAVIGATION_STATE_TOOL_ID)["context_summary"]
    latest = live_summary["latest"]
    assert latest["answerability"] == "snapshot_evidence_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["nearest_cp_id"] == "cp.anchor"
    assert latest["provided_fields"]["nearest_route_distance_m"] <= 0.001
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert latest["boundary"]["outbound_send_performed"] is False


def test_configured_assistant_context_resolver_adds_live_navigation_evidence(
    tmp_path: Path,
) -> None:
    observer = _write_sensorlogger_navigation_evidence(tmp_path)
    resolver = create_assistant_context_resolver(
        pretrip_workspace_root=PROJECT_ROOT.parent,
        live_navigation_evidence_dir=observer.config.evidence_dir,
    )

    sources = resolver(
        ScoutAssistantQuery(
            surface="pretrip",
            question="我現在是不是離主路太近但站在危險邊緣？",
            project_id="chilai_nanhua_day1",
        )
    )

    source_ids = {source.source_id for source in sources}
    assert LIVE_NAVIGATION_EVIDENCE_SOURCE_ID in source_ids
    evidence_source = next(
        source for source in sources if source.source_id == LIVE_NAVIGATION_EVIDENCE_SOURCE_ID
    )
    summary = evidence_source.context_summary
    assert summary is not None
    assert summary["read_only"] is True
    assert summary["runtime_safety_truth"] is False
    assert summary["raw_payloads_embedded"] is False
    assert "raw_payload_text" not in json.dumps(summary, ensure_ascii=False)
    assert "raw_nmea" not in json.dumps(summary, ensure_ascii=False)
    assert any(
        report.get("status") == "missing_route_path"
        for report in summary["source_report"]
    )


def test_configured_assistant_context_resolver_without_evidence_dir_is_unchanged() -> None:
    resolver = create_assistant_context_resolver(pretrip_workspace_root=PROJECT_ROOT.parent)

    sources = resolver(
        ScoutAssistantQuery(
            surface="pretrip",
            question="我現在是不是離主路太近但站在危險邊緣？",
            project_id="chilai_nanhua_day1",
        )
    )

    assert LIVE_NAVIGATION_EVIDENCE_SOURCE_ID not in {
        source.source_id for source in sources
    }


def _write_sensorlogger_navigation_evidence(tmp_path: Path) -> SensorLoggerMqttObserver:
    observer = SensorLoggerMqttObserver(
        SensorLoggerMqttObserverConfig(
            host="mqtt.example.test",
            topic="scout/test/alex/sensorlogger",
            evidence_dir=tmp_path,
            application_route_path=ROUTE_PATH,
        )
    )
    anchor = _route_anchor()
    observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(
            {
                "messageId": 101,
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
        ),
        received_at=1780555780.5,
    )
    observer.handle_message(
        topic="scout/test/alex/sensorlogger",
        payload=json.dumps(
            {
                "messageId": 102,
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
        ),
        received_at=1780555790.5,
    )
    return observer


def _pretrip_evidence_context_resolver(
    project_root: Path,
    *,
    evidence_dir: Path,
    route_match_project_root: Path | None = None,
    route_path: Path | None = None,
):
    def resolve(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        context = build_pretrip_assistant_context(
            query.project_id or query.context_ref or project_root.name,
            selected_source_id=query.selected_artifact_id,
        )
        sources = assistant_source_refs_from_context(context, query=query)
        sources = augment_sources_with_live_navigation_snapshot_evidence(
            query,
            sources=sources,
            evidence_dir=evidence_dir,
            project_root=route_match_project_root,
            route_path=route_path,
            limit=50,
        )
        return augment_pretrip_sources_with_local_evidence_search(
            query,
            sources=sources,
            project_root=project_root,
            limit=5,
        )

    return resolve


def _write_route_match_project(project_root: Path) -> Path:
    anchor = _route_anchor()
    (project_root / "candidates").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "live_navigation_route_path": str(ROUTE_PATH),
            }
        ),
        encoding="utf-8",
    )
    (project_root / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cp.anchor",
                    "lat": anchor.lat,
                    "lon": anchor.lon,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _route_anchor():
    return load_gpx_route(ROUTE_PATH).points[100]


def _source_by_id(payload: dict[str, object], source_id: str) -> dict[str, object]:
    for source in payload["sources"]:
        if source["source_id"] == source_id:
            return source
    raise AssertionError(f"missing source {source_id}")


def _report_by_kind(reports: list[dict[str, object]], source_kind: str) -> dict[str, object]:
    for report in reports:
        if report.get("source_kind") == source_kind:
            return report
    raise AssertionError(f"missing source report {source_kind}")
