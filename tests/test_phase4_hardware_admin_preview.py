from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from phase4_admin_runtime import create_phase4_admin_runtime_app
from phase4_hardware_admin_preview import prepare_phase4_hardware_admin_preview
from scout_ai_tool_planner import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_live_navigation_snapshot_evidence import LIVE_NAVIGATION_EVIDENCE_SOURCE_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _write_live_navigation_evidence(evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sensorlogger_payload = {
        "messageId": 101,
        "sessionId": "session-1",
        "deviceId": "watch-1",
        "payload": [
            {
                "name": "location",
                "time": 1780555780000000000,
                "values": {
                    "latitude": 24.051,
                    "longitude": 121.22,
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
            }
        ],
    }
    raw_record = {
        "parse_status": "accepted",
        "source_adapter": "sensorlogger_mqtt",
        "ingress_transport": "mqtt",
        "received_at": 1780555780.5,
        "raw_payload_text": json.dumps(sensorlogger_payload, ensure_ascii=False),
    }
    filter_record = {
        "route_target": "navigation.ins_dr",
        "output_kind": "navigation_estimate",
        "output_summary": {
            "route_progress_m": 14550.0,
            "confidence": 0.82,
            "uncertainty_m": 6.5,
            "ins_dr_source": "wearable_route_constrained",
            "last_anchor_at": "2026-06-04T06:49:40Z",
        },
    }
    (evidence_dir / "sensorlogger_mqtt_raw.jsonl").write_text(
        json.dumps(raw_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "sensorlogger_mqtt_filter_outputs.jsonl").write_text(
        json.dumps(filter_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _source_by_id(payload: dict[str, object], source_id: str) -> dict[str, object]:
    for source in payload["sources"]:
        if source["source_id"] == source_id:
            return source
    raise AssertionError(f"missing source {source_id}")


def test_phase4_admin_runtime_serves_pretrip_and_mock_assistant_on_lan_profile() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_DATA_ROOT": "/data/scout",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": "/data/scout/admin/pretrip-workspaces",
            "SCOUT_SAFETY_INCIDENT_STORE": "/data/scout/incidents",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_WEATHER_API_ENABLED": "false",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["status"] == "ok"
    assert health_payload["runtime_profile"] == "pi-phase4-admin-preview"
    assert health_payload["boundaries"]["phase1_field_runtime_started"] is False
    assert health_payload["boundaries"]["safety_api_mutation_allowed"] is False
    assert health_payload["boundaries"]["local_pretrip_workspace_write_allowed"] is True
    assert health_payload["boundaries"]["debug_api_enabled"] is False
    assert health_payload["auth"]["required"] is False
    assert health_payload["auth"]["token_value_exposed"] is False
    assert health_payload["ingress_observers"]["enabled"] is True
    assert health_payload["ingress_observers"]["boundary"]["safety_api_called"] is False
    assert (
        health_payload["ingress_observers"]["boundary"]["credential_value_exposed"]
        is False
    )
    registry = health_payload["assistant_context_registry"]
    assert registry["read_only"] is True
    assert registry["runtime_safety_truth"] is False
    assert registry["pretrip_workspace_root_configured"] is True
    assert registry["live_navigation_evidence_configured"] is False
    assert registry["context_path_values_exposed"] is False
    assert registry["credential_values_exposed"] is False
    assert health_payload["routes"]["hardware_readiness"] == "/admin/hardware-readiness"
    assert health_payload["routes"]["hardware_readiness_context"] == "/admin/hardware-readiness/context"

    pretrip = client.get("/admin/pretrip")
    assert pretrip.status_code == 200
    assert 'id="map"' in pretrip.text
    assert "/admin/pretrip/projects/${PROJECT_ID}" in pretrip.text

    hardware_context = client.get("/admin/hardware-readiness/context")
    assert hardware_context.status_code == 200
    assert hardware_context.json()["surface"] == "hardware_readiness"
    assert hardware_context.json()["boundary"]["provider_control_allowed"] is False

    status = client.get("/assistant/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["provider"] == "mock"
    assert status_payload["token_values_exposed"] is False
    assert status_payload["assistant_context_registry"] == registry


def test_phase4_admin_runtime_loads_scout_env_before_snapshot(monkeypatch) -> None:
    calls: list[Path] = []

    def fake_load_scout_env_files(*, repo_root: Path) -> object:
        calls.append(repo_root)
        os.environ["OPENROUTER_API_KEY"] = "sk-loaded-from-persistent"
        return object()

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "phase4_admin_runtime.load_scout_env_files",
        fake_load_scout_env_files,
    )

    app = create_phase4_admin_runtime_app()

    assert app.title == "Scout Phase 4 Admin LAN Preview"
    assert calls == [ROOT]


def test_phase4_admin_runtime_explicit_environ_skips_process_env_loader(
    monkeypatch,
) -> None:
    def fail_load_scout_env_files(*, repo_root: Path) -> object:
        raise AssertionError(f"unexpected env load for {repo_root}")

    monkeypatch.setattr(
        "phase4_admin_runtime.load_scout_env_files",
        fail_load_scout_env_files,
    )

    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )

    assert app.title == "Scout Phase 4 Admin LAN Preview"


def test_phase4_admin_runtime_status_reports_live_evidence_config_without_path_values(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "private-live-evidence"
    evidence_dir.mkdir()
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects"
            ),
            "SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR": str(evidence_dir),
        }
    )
    client = TestClient(app)

    health_payload = client.get("/health").json()
    preview_payload = client.get("/phase4/admin-preview/status").json()
    assistant_payload = client.get("/assistant/status").json()

    for payload in (health_payload, preview_payload, assistant_payload):
        registry = payload["assistant_context_registry"]
        assert registry["pretrip_workspace_root_configured"] is True
        assert registry["live_navigation_evidence_configured"] is True
        assert registry["live_navigation_evidence_adapter"] == "sensorlogger_mqtt_jsonl"
        assert registry["context_path_values_exposed"] is False
        assert registry["credential_values_exposed"] is False
        assert registry["live_safety_api_calls_allowed"] is False
        assert registry["phase1_safety_mutation_allowed"] is False
        assert registry["outbound_send_allowed"] is False
        assert registry["hardware_control_allowed"] is False
        dumped_registry = json.dumps(registry, ensure_ascii=False)
        assert str(evidence_dir) not in dumped_registry
        assert "private-live-evidence" not in dumped_registry


def test_phase4_admin_runtime_assistant_failure_returns_read_only_safe_response(
    monkeypatch,
) -> None:
    class FailingProvider:
        def answer(self, query, *, sources=None):
            raise TimeoutError("provider timed out")

    monkeypatch.setattr(
        "phase4_admin_runtime.create_assistant_provider_from_env",
        lambda _env: FailingProvider(),
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={"surface": "pretrip", "question": "hi"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_only"] is True
    assert payload["model_interpretation"] is True
    assert payload["surface"] == "pretrip"
    assert "Assistant provider failed safely" in payload["answer"]
    assert payload["boundary"]["pretrip_review_mutation_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["observability"]["safe_failure"] is True
    assert payload["observability"]["latency_class"] == "timeout_or_error"


def test_phase4_admin_runtime_pretrip_assistant_exposes_checkpoint_counts() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "有多少個cp",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("Scout AI read-only deterministic skill result")
    assert "124 個 CP" in payload["answer"]
    assert any(
        limitation == "resolved_by=assistant_skill.pretrip.cp_count.v0"
        for limitation in payload["limitations"]
    )
    assert payload["sources"][0]["source_id"] == "assistant_skill.pretrip.cp_count.v0"
    context_source = next(
        source
        for source in payload["sources"]
        if source["source_id"] == "assistant_context.pretrip"
    )
    summary = context_source["context_summary"]["summary"]
    assert summary["cp_count"] == 124
    assert summary["checkpoint_candidate_count"] == 124
    assert summary["cp_count_meaning"] == (
        "checkpoint_candidate_count from the pre-trip checkpoint candidates"
    )


def test_phase4_admin_runtime_pretrip_assistant_exposes_mcp_cp_links() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "黑水塘在第幾cp附近？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("Scout AI read-only deterministic skill result")
    assert "黑水塘 在 CP 002 附近" in payload["answer"]
    assert any(
        limitation == "resolved_by=assistant_skill.pretrip.place_to_cp.v0"
        for limitation in payload["limitations"]
    )
    context_source = next(
        source
        for source in payload["sources"]
        if source["source_id"] == "assistant_context.pretrip"
    )
    summary = context_source["context_summary"]["summary"]
    links = summary["major_critical_point_cp_links"]
    heishuitang = next(link for link in links if link["label"] == "黑水塘")
    assert heishuitang["mcp_id"] == "mcp.heishuitang.002"
    assert heishuitang["nearest_cp_candidate_id"] == "cp.002"
    assert heishuitang["nearest_cp_label"] == "CP 002"
    assert heishuitang["nearest_cp_distance_m"] == 0.0
    assert heishuitang["candidate_only"] is True
    assert heishuitang["runtime_safety_truth"] is False
    assert "mcp.heishuitang.002" in {
        source["source_id"] for source in payload["sources"]
    }


def test_phase4_admin_runtime_pretrip_general_question_adds_local_evidence_search() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects"
            ),
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "大崩塌有什麼風險？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    search_source = _source_by_id(
        payload,
        "assistant_skill.pretrip.local_evidence_search.v0",
    )
    assert search_source["evidence_type"] == "assistant_local_evidence_search_results"
    summary = search_source["context_summary"]
    assert summary["result_count"] >= 1
    assert summary["runtime_safety_truth"] is False
    assert any("大崩塌" in result["snippet"] for result in summary["results"])
    assert any(
        source["source_id"] == "assistant_context.pretrip"
        for source in payload["sources"]
    )


def test_phase4_admin_runtime_pretrip_general_question_searches_mcp_evidence() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects"
            ),
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "黑水塘有什麼資料？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    search_source = _source_by_id(
        payload,
        "assistant_skill.pretrip.local_evidence_search.v0",
    )
    results = search_source["context_summary"]["results"]
    assert any(
        result["evidence_type"] == "pretrip_major_critical_point_candidate"
        and result["metadata"]["mcp_id"] == "mcp.heishuitang.002"
        for result in results
    )
    assert any(
        result["evidence_type"] == "pretrip_mcp_cp_support_reconciliation"
        and result["metadata"]["nearest_cp_candidate_id"] == "cp.002"
        for result in results
    )


def test_phase4_admin_runtime_pretrip_assistant_hydrates_live_navigation_evidence(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "sensorlogger-evidence"
    _write_live_navigation_evidence(evidence_dir)
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects"
            ),
            "SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR": str(evidence_dir),
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "我現在是不是離主路太近但站在危險邊緣？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    source_ids = {source["source_id"] for source in payload["sources"]}
    assert LIVE_NAVIGATION_EVIDENCE_SOURCE_ID in source_ids
    assert LIVE_NAVIGATION_STATE_TOOL_ID in source_ids
    evidence_source = _source_by_id(payload, LIVE_NAVIGATION_EVIDENCE_SOURCE_ID)
    evidence_summary = evidence_source["context_summary"]
    assert evidence_summary["read_only"] is True
    assert evidence_summary["runtime_safety_truth"] is False
    assert "raw_payload_text" not in json.dumps(evidence_summary, ensure_ascii=False)
    assert "raw_nmea" not in json.dumps(evidence_summary, ensure_ascii=False)
    live_summary = _source_by_id(payload, LIVE_NAVIGATION_STATE_TOOL_ID)["context_summary"]
    latest = live_summary["latest"]
    assert live_summary["hydration"]["status"] == "hydrated"
    assert live_summary["hydration"]["source_id"] == LIVE_NAVIGATION_EVIDENCE_SOURCE_ID
    assert latest["provided_fields"]["lat"] == 24.051
    assert latest["provided_fields"]["lon"] == 121.22
    assert latest["provided_fields"]["ins_dr_source"] == "wearable_route_constrained"
    assert latest["answerability"] == "snapshot_missing_required_fields"
    assert "nearest_route_distance_m" in latest["missing_fields"]
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert latest["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["safety_mutation_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["hardware_control_allowed"] is False


def test_phase4_admin_runtime_pretrip_general_question_uses_tool_plan_fallback(
    monkeypatch,
) -> None:
    class FailingProvider:
        def answer(self, query, *, sources=None):
            raise TimeoutError("provider should fall back to local evidence search")

    monkeypatch.setattr(
        "phase4_admin_runtime.create_assistant_provider_from_env",
        lambda _env: FailingProvider(),
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects"
            ),
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "大崩塌有什麼風險？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["observability"]["safe_failure"] is True
    assert "Scout AI model answer unavailable" in payload["answer"]
    assert "最高候選風險點" in payload["evidence_backed_answer"]
    assert "score=" in payload["evidence_backed_answer"]
    assert any(
        limitation == f"resolved_by={RISK_SCORE_TOOL_ID}"
        for limitation in payload["limitations"]
    )
    source_ids = {source["source_id"] for source in payload["sources"]}
    assert RISK_SCORE_TOOL_ID in source_ids
    assert "assistant_skill.pretrip.local_evidence_search.v0" in source_ids


def test_phase4_admin_runtime_pretrip_place_to_cp_skill_bypasses_failed_provider(
    monkeypatch,
) -> None:
    class FailingProvider:
        def answer(self, query, *, sources=None):
            raise TimeoutError("provider should not be called for deterministic skill")

    monkeypatch.setattr(
        "phase4_admin_runtime.create_assistant_provider_from_env",
        lambda _env: FailingProvider(),
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "黑水塘在第幾cp附近？",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["observability"]["safe_failure"] is False
    assert payload["answer"].startswith("Scout AI read-only deterministic skill result")
    assert "黑水塘 在 CP 002 附近" in payload["answer"]
    assert payload["sources"][0]["source_id"] == (
        "assistant_skill.pretrip.place_to_cp.v0"
    )


def test_phase4_admin_runtime_pretrip_cp_count_skill_bypasses_failed_provider(
    monkeypatch,
) -> None:
    class FailingProvider:
        def answer(self, query, *, sources=None):
            raise TimeoutError("provider should not be called for deterministic skill")

    monkeypatch.setattr(
        "phase4_admin_runtime.create_assistant_provider_from_env",
        lambda _env: FailingProvider(),
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "有多少個cp",
            "context_ref": "chilai_nanhua_day1",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["observability"]["safe_failure"] is False
    assert payload["answer"].startswith("Scout AI read-only deterministic skill result")
    assert "124 個 CP" in payload["answer"]
    assert payload["sources"][0]["source_id"] == "assistant_skill.pretrip.cp_count.v0"


def test_phase4_admin_runtime_mounts_debug_projection_when_explicitly_enabled() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_ADMIN_BASIC_USERNAME": "scout-admin",
            "SCOUT_ADMIN_ACCESS_TOKEN": "test-token",
            "SCOUT_DEBUG_API_ENABLED": "true",
            "SCOUT_DEBUG_LOG_PATH": "/tmp/scout-phase4-admin-debug-test.jsonl",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["routes"]["debug_admin"] == "/admin/debug"
    assert health.json()["routes"]["debug_events"] == "/debug/events"
    assert health.json()["boundaries"]["debug_api_enabled"] is True
    assert health.json()["boundaries"]["debug_projection_clear_allowed"] is True
    assert health.json()["boundaries"]["debug_projection_clear_mutates_runtime"] is False

    unauthenticated = client.get("/admin/debug")
    assert unauthenticated.status_code == 401

    debug_page = client.get(
        "/admin/debug",
        headers={"Authorization": "Bearer test-token"},
    )
    assert debug_page.status_code == 200
    assert "Scout Phase 3.5 Runtime Debug" in debug_page.text

    debug_state = client.get(
        "/debug/state",
        headers={"Authorization": "Bearer test-token"},
    )
    assert debug_state.status_code == 200
    assert debug_state.json()["debug_boundary"]["read_only"] is True


def test_phase4_admin_runtime_mounts_mobile_wearable_ingress_status(
    tmp_path: Path,
) -> None:
    status_path = tmp_path / "sensorlogger_mqtt_status.json"
    status_path.write_text(
        json.dumps(
            {
                "artifact_kind": "scout_sensorlogger_mqtt_observer_status",
                "source_tool": "scout_sensorlogger_mqtt_observer",
                "message_count": 1,
                "invalid_message_count": 0,
                "sensor_names": ["accelerometer"],
                "sessions": [],
                "mqtt": {
                    "host": "mqtt.example.test",
                    "port": 8884,
                    "topic": "scout/test/alex/sensorlogger",
                    "transport": "websockets",
                    "use_tls": True,
                    "username_configured": True,
                    "password_configured": True,
                },
                "mqtt_state": {
                    "connected": True,
                    "subscribed": True,
                    "ever_connected": True,
                    "ever_subscribed": True,
                },
                "ingress": {
                    "record_count": 0,
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "unrecognized_count": 0,
                    "ingress_transports": [],
                    "source_adapters": [],
                    "records": [],
                    "boundary": {
                        "runtime_admission_performed": False,
                        "phase1_l0_l4_state_mutated": False,
                        "safety_api_called": False,
                        "phase2_brain_writeback": False,
                    },
                },
                "evidence": {
                    "evidence_dir": str(tmp_path),
                    "raw_jsonl_path": str(tmp_path / "sensorlogger_mqtt_raw.jsonl"),
                    "ingress_index_jsonl_path": str(
                        tmp_path / "sensorlogger_mqtt_ingress_index.jsonl"
                    ),
                    "status_path": str(status_path),
                },
                "boundary": {
                    "evidence_only": True,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "phase2_brain_writeback": False,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_ADMIN_ACCESS_TOKEN": "test-token",
            "SCOUT_DEBUG_API_ENABLED": "true",
            "SCOUT_MOBILE_WEARABLE_INGRESS_STATUS_PATH": str(status_path),
        }
    )
    client = TestClient(app)

    health = client.get("/health", headers={"Authorization": "Bearer test-token"})
    assert health.status_code == 200
    assert health.json()["routes"]["debug_mobile_wearable_ingress"] == (
        "/debug/mobile-wearable/ingress"
    )

    unauthenticated = client.get("/debug/mobile-wearable/ingress")
    assert unauthenticated.status_code == 401

    response = client.get(
        "/debug/mobile-wearable/ingress",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["status_path"] == str(status_path)
    assert payload["message_count"] == 1
    assert payload["mqtt"]["credential_configured"] is True
    assert payload["boundary"]["safety_api_called"] is False
    assert "password_configured" not in json.dumps(payload, sort_keys=True)


def test_phase4_admin_runtime_can_point_hardware_readiness_at_live_probe_fixture(tmp_path: Path) -> None:
    fixture_path = tmp_path / "hardware-live-probe.json"
    fixture_path.write_text(
        json.dumps(
            {
                "interface_inventory": [
                    {
                        "interface_ref": "storage.ssd.data_root",
                        "interface_type": "ssd",
                        "status": "available",
                        "signal_activity": "mounted_root_observed",
                        "last_seen_at": "2026-05-22T14:39:24+08:00",
                        "disk_model": "KINGSTON SNV3S1000G",
                        "source_id": "storage.ssd.data_root",
                        "source_path": "tmp-live-probe",
                        "evidence_type": "hardware_interface_inventory",
                    }
                ],
                "provider_health": [],
                "sample_replay_timeline": [],
                "runtime_debug_events": [],
                "mock_transport_queue": [],
            }
        ),
        encoding="utf-8",
    )
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_HARDWARE_READINESS_FIXTURE_PATH": str(fixture_path),
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    response = client.get("/admin/hardware-readiness/context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_path"] == str(fixture_path)
    assert payload["summary"]["interface_count"] == 1
    assert payload["interface_inventory"][0]["details"]["disk_model"] == "KINGSTON SNV3S1000G"


def test_phase4_admin_runtime_can_require_basic_or_bearer_auth() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_ADMIN_BASIC_USERNAME": "scout-admin",
            "SCOUT_ADMIN_ACCESS_TOKEN": "test-token",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["auth"]["required"] is True
    assert health.json()["auth"]["token_configured"] is True
    assert health.json()["auth"]["token_value_exposed"] is False
    assert "test-token" not in json.dumps(health.json())

    unauthenticated = client.get("/admin/pretrip")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"].startswith("Basic ")

    bearer = client.get(
        "/admin/pretrip",
        headers={"Authorization": "Bearer test-token"},
    )
    assert bearer.status_code == 200

    basic = client.get(
        "/assistant/status",
        auth=("scout-admin", "test-token"),
    )
    assert basic.status_code == 200
    assert basic.json()["provider"] == "mock"


def test_phase4_admin_runtime_fails_closed_when_auth_required_without_token() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["auth"]["misconfigured"] is True

    blocked = client.get("/admin/pretrip")
    assert blocked.status_code == 503
    assert blocked.json()["auth"]["misconfigured"] is True


def test_phase4_hardware_admin_preview_plan_uses_lan_url_and_separate_port() -> None:
    plan = prepare_phase4_hardware_admin_preview(
        hardware_host="scout.local",
        host_port=9110,
    )

    assert plan["artifact_kind"] == "phase4_hardware_admin_preview_plan"
    assert plan["status"] == "ready_to_deploy"
    assert plan["compose_file"] == "docker-compose.pi.admin.yml"
    assert plan["urls"]["pretrip_admin"] == "http://scout.local:9110/admin/pretrip"
    assert plan["urls"]["debug_admin"] == "http://scout.local:9110/admin/debug"
    assert plan["urls"]["debug_events"] == "http://scout.local:9110/debug/events"
    assert plan["urls"]["pretrip_admin_local_tiles"].endswith(
        "/admin/pretrip?tileSource=local"
    )
    assert plan["runtime_port_policy"]["existing_runtime_host_port"] == 9099
    assert plan["runtime_port_policy"]["admin_preview_host_port"] == 9110
    assert plan["runtime_port_policy"]["shares_existing_runtime_port"] is False
    assert plan["boundaries"]["does_not_replace_pi_runtime_service"] is True
    assert plan["boundaries"]["admin_auth_required"] is True
    assert plan["boundaries"]["admin_token_value_embedded"] is False
    assert plan["boundaries"]["phase1_runtime_mutation_allowed"] is False
    assert plan["boundaries"]["phase2_writeback_allowed"] is False
    assert plan["boundaries"]["debug_api_enabled"] is True
    assert plan["boundaries"]["debug_projection_clear_mutates_runtime"] is False
    assert plan["boundaries"]["debug_projection_log_path"] == "/data/scout/admin/debug/runtime-debug-events.jsonl"
    assert plan["tile_cache"]["capacity_limit_bytes"] == 10 * 1024 * 1024 * 1024
    assert plan["network_expectations"]["open_meteo_live_weather_enabled"] is False


def test_phase4_hardware_admin_preview_cli_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "phase4_hardware_admin_preview.py"),
            "--hardware-host",
            "scout.local",
            "--host-port",
            "9110",
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["urls"]["health"] == "http://scout.local:9110/health"
    assert payload["environment"]["SCOUT_SAFETY_ENABLED"] == "false"
    assert payload["environment"]["SCOUT_AI_ASSISTANT_PROVIDER"] == "pydantic_ai"
    assert payload["environment"]["SCOUT_AI_ASSISTANT_CONFIG_PATH"] == "/data/scout/config/assistant-models.json"
    assert payload["environment"]["SCOUT_ADMIN_AUTH_REQUIRED"] == "true"
    assert payload["environment"]["SCOUT_DEBUG_API_ENABLED"] == "true"
    assert payload["environment"]["SCOUT_DEBUG_LOG_PATH"] == "/data/scout/admin/debug/runtime-debug-events.jsonl"
    assert "phase4-admin-token" in payload["operator_commands"]["create_token"]


def test_phase4_admin_dockerfile_runs_admin_app_not_field_runtime() -> None:
    source = read("Dockerfile.pi.admin")

    assert "ARG TARGETPLATFORM=linux/arm64" in source
    assert "FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm" in source
    assert "SCOUT_RUNTIME_PROFILE=pi-phase4-admin-preview" in source
    assert "SCOUT_SAFETY_ENABLED=false" in source
    assert "SCOUT_PRETRIP_WORKSPACE_ROOT=/data/scout/admin/pretrip-workspaces" in source
    assert "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT=/data/scout/osm-tiles" in source
    assert "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT=/data/scout/raster-tiles" in source
    assert "SCOUT_ADMIN_AUTH_REQUIRED=true" in source
    assert "SCOUT_ADMIN_ACCESS_TOKEN_FILE=/data/scout/admin/secrets/phase4-admin-token" in source
    assert "phase46_live_replay_debug_projector.py" in source
    assert "debug_api.py" in source
    assert "hardware_readiness_api.py" in source
    assert "hardware_readiness_admin_view.py" in source
    assert "hardware_readiness_assistant_context.py" in source
    assert "scout_hardware_readiness_live_probe.py" in source
    assert "runtime_debug_log.py" in source
    assert "runtime_debug_models.py" in source
    assert "docs/admin/phase-3-5-runtime-debug.html" in source
    assert "docs/admin/phase-3-6-hardware-readiness.html" in source
    assert "phase4_admin_runtime.py" in source
    assert "docs/admin/phase4-pretrip-planning.html" in source
    assert "pretrip_overpass_ingest.py" in source
    assert "pretrip_gis_perception.py" in source
    assert "pretrip_route_comparison.py" in source
    assert "tests/fixtures/hardware/readiness_context.json" in source
    assert "tests/fixtures/pretrip/projects/chilai_nanhua_day1/" in source
    assert "scout_agent_builtin_tools.py" in source
    assert "scout_cli.py" in source
    assert "scout_agent_cli.py" in source
    assert "scout_agent_runtime.py" in source
    assert "assistant_weather_preparation.py" in source
    assert "dashboard_connected_preparation.py" in source
    assert "tools/pi_wio_e5_lorawan_uplink_trial_plan.py" in source
    assert "tools/pi_wio_e5_lorawan_rf_trial.py" in source
    assert "tools/pi_wio_e5_chirpstack_join_audit.py" in source
    assert "tools/pi_wio_e5_chirpstack_as9232_profile_provision.py" in source
    assert "tools/pi_wio_e5_chirpstack_key_sync.py" in source
    assert 'CMD ["python", "-m", "uvicorn", "phase4_admin_runtime:app"' in source
    assert "scout_pi_runtime:app" not in source
    assert "COPY *.py" not in source


def test_phase4_admin_compose_keeps_runtime_9099_free_for_existing_service() -> None:
    source = read("docker-compose.pi.admin.yml")

    assert "scout-phase4-admin:" in source
    assert "dockerfile: Dockerfile.pi.admin" in source
    assert "image: scout-fusion/pi-phase4-admin:preview" in source
    assert 'SCOUT_SAFETY_ENABLED: "false"' in source
    assert "SCOUT_PRETRIP_WORKSPACE_ROOT: /data/scout/admin/pretrip-workspaces" in source
    assert "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT: /data/scout/osm-tiles" in source
    assert "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT: /data/scout/raster-tiles" in source
    assert 'SCOUT_ADMIN_AUTH_REQUIRED: "${SCOUT_ADMIN_AUTH_REQUIRED:-true}"' in source
    assert "SCOUT_ADMIN_ACCESS_TOKEN_FILE: /data/scout/admin/secrets/phase4-admin-token" in source
    assert "env_file:" in source
    assert "- /data/scout/secrets/live-runtime.env" in source
    assert "SCOUT_AI_ASSISTANT_PROVIDER: pydantic_ai" in source
    assert "SCOUT_AI_ASSISTANT_CONFIG_PATH: /data/scout/config/assistant-models.json" in source
    assert "host.docker.internal:host-gateway" in source
    assert 'SCOUT_DEBUG_API_ENABLED: "${SCOUT_DEBUG_API_ENABLED:-true}"' in source
    assert "SCOUT_DEBUG_LOG_PATH:" in source
    assert "/data/scout/admin/debug/runtime-debug-events.jsonl" in source
    assert '- "9110:9099"' in source
    assert '- "9099:9099"' not in source
    assert "depends_on:" not in source
    assert "SCOUT_CLOUD_MODEL_TOKEN:" not in source


def test_phase4_admin_docker_context_whitelists_only_metadata_and_admin_assets() -> None:
    dockerignore = read(".dockerignore")

    assert "!Dockerfile.pi.admin" in dockerignore
    assert "!requirements.pi.admin.txt" in dockerignore
    assert "!phase4_admin_runtime.py" in dockerignore
    assert "!phase46_live_replay_debug_projector.py" in dockerignore
    assert "!debug_api.py" in dockerignore
    assert "!hardware_readiness_api.py" in dockerignore
    assert "!hardware_readiness_admin_view.py" in dockerignore
    assert "!hardware_readiness_assistant_context.py" in dockerignore
    assert "!pretrip_candidate_generation.py" in dockerignore
    assert "!pretrip_geojson_import.py" in dockerignore
    assert "!pretrip_gpx_corpus.py" in dockerignore
    assert "!pretrip_import.py" in dockerignore
    assert "!pretrip_layer_preparation.py" in dockerignore
    assert "!pretrip_overpass_ingest.py" in dockerignore
    assert "!pretrip_gis_perception.py" in dockerignore
    assert "!pretrip_route_comparison.py" in dockerignore
    assert "!pretrip_source_ingest.py" in dockerignore
    assert "!pretrip_workspace_edit.py" in dockerignore
    assert "!runtime_debug_log.py" in dockerignore
    assert "!scout_agent_builtin_tools.py" in dockerignore
    assert "!scout_cli.py" in dockerignore
    assert "!scout_agent_cli.py" in dockerignore
    assert "!scout_agent_runtime.py" in dockerignore
    assert "!assistant_weather_preparation.py" in dockerignore
    assert "!dashboard_connected_preparation.py" in dockerignore
    assert "!scout_hardware_readiness_live_probe.py" in dockerignore
    assert "!scout_sx1303_gateway_observer.py" in dockerignore
    assert "!tools/pi_sx1303_gateway_smoke.py" in dockerignore
    assert "!tools/pi_sx1303_gateway_rx_smoke.py" in dockerignore
    assert "!tools/pi_sx1303_gateway_uplink_mqtt_tail.py" in dockerignore
    assert "!tools/pi_wio_e5_lorawan_uplink_trial_plan.py" in dockerignore
    assert "!tools/pi_wio_e5_lorawan_rf_trial.py" in dockerignore
    assert "!tools/pi_wio_e5_chirpstack_join_audit.py" in dockerignore
    assert "!tools/pi_wio_e5_chirpstack_as9232_profile_provision.py" in dockerignore
    assert "!tools/pi_wio_e5_chirpstack_key_sync.py" in dockerignore
    assert "!admin_api.py" in dockerignore
    assert "!docs/admin/phase-3-5-runtime-debug.html" in dockerignore
    assert "!docs/admin/phase-3-6-hardware-readiness.html" in dockerignore
    assert "!docs/admin/phase4-pretrip-planning.html" in dockerignore
    assert "!tests/fixtures/hardware/readiness_context.json" in dockerignore
    assert "!tests/fixtures/pretrip/projects/chilai_nanhua_day1/**" in dockerignore
    assert "!*.py" not in dockerignore
    assert "!catographydata/" not in dockerignore
    assert "!PdrSample/" not in dockerignore


def test_hardware_plan_documents_phase4_admin_lan_preview_boundary() -> None:
    source = read("docs/specs/hardware-port-plan.md")

    assert "## Phase 4 Admin LAN Preview Profile" in source
    assert "`scout-phase4-admin`" in source
    assert "`http://scout.local:9110/admin/pretrip`" in source
    assert "`phase4_hardware_demo_smoke.py`" in source
    assert "`phase4_hardware_tile_workspace_smoke.py`" in source
    assert "`SCOUT_ADMIN_AUTH_REQUIRED=true`" in source
    assert "`/data/scout/admin/secrets/phase4-admin-token`" in source
    assert "admin token values are never embedded" in source
    assert "runs read-only HTTP GET checks" in source
    assert "is plan-only" in source
    assert "does not call" in source
    assert "`scout.local`" in source
    assert "no Phase 1 field runtime is started by this profile" in source
    assert "不是現場安全 runtime" in source
