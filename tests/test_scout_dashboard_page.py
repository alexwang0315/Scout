from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import admin_api
from admin_api import create_admin_app


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
DOC = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.md"
PRETRIP_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
LAYER_CONTRACT_DOC = ROOT / "docs" / "specs" / "scout-admin-map-layer-contract.md"
WEATHER_DOC = ROOT / "docs" / "specs" / "scout-weather-environment-sensing.md"
SMOKE_TOOL = ROOT / "tools" / "admin_ui_visual_smoke.js"


def test_scout_dashboard_page_serves_static_shell() -> None:
    client = TestClient(create_admin_app())

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Scout Dashboard v0.1" in response.text
    assert 'id="dashboardShell"' in response.text
    assert 'id="dashboardMap"' in response.text
    assert 'id="dashboardAgent"' in response.text
    assert 'id="dashboardEvidence"' in response.text


def test_scout_dashboard_ai_hat_trace_displays_actual_postprocess_mode() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'agentAiHatTraceValue(response, "ai_hat_postprocess_applied=")' in html
    assert "postprocess=${aiHatPostprocess}" in html


def test_scout_dashboard_body_index_fresh_project_has_no_fabricated_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "empty_store",
    )
    client = TestClient(create_admin_app())

    response = client.get(
        "/admin/dashboard/body-index?project_id=fresh_body_index_project"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "scout_dashboard_body_index.v1"
    assert payload["project_id"] == "fresh_body_index_project"
    assert payload["import_status"] == "not_imported"
    assert payload["source_index"] == []
    expected_summary = {
        "scout_pace_coefficient": "unavailable",
        "energy_reserve": "unavailable",
        "vulnerability": "unavailable",
        "experience_trust": "unavailable",
        "score_percent": 0,
        "evidence_status": "unavailable",
    }
    for key, value in expected_summary.items():
        assert payload["summary"][key] == value
    assert payload["coverage_cards"] == [
        ["Health exports", "0", "no local HealthExport sources imported"],
        ["Walking sessions", "0", "no walking workouts imported"],
        ["GPX tracks", "0", "no route traces imported"],
        ["15-min windows", "0", "no sanitized pressure windows"],
        ["Provider metrics", "0", "no source-value metric families"],
    ]
    assert payload["pressure_timeline"] == []
    assert payload["provider_metrics"] == []
    assert payload["provider_metric_summaries"] == []
    assert all(row[1] == "pending" for row in payload["health_signals"])
    assert all("--" in row[2] for row in payload["health_signals"])
    assert payload["boundary"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["raw_gpx_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False

    html = PAGE.read_text(encoding="utf-8")
    for fabricated_value in (
        'value: "3.8 km/h"',
        'value: "410 m/h"',
        'value: "-34%"',
        'scout_pace_coefficient: "0.82"',
        '["Health exports", "3", "HealthAutoExport zip files"]',
        '["2018 long walk", "16 windows", "single GPX session", 33]',
    ):
        assert fabricated_value not in html


def test_scout_dashboard_body_index_all_invalid_import_stays_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "InvalidHealthExport"
    source_dir.mkdir()
    with zipfile.ZipFile(source_dir / "invalid.zip", "w") as archive:
        archive.writestr("invalid.json", "{not valid json")
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "invalid_store",
    )
    client = TestClient(create_admin_app())

    response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "invalid_body_index_project",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["import_status"] == "not_imported"
    assert payload["source_index"] == []
    assert payload["summary"]["evidence_status"] == "unavailable"
    assert payload["summary"]["scout_pace_coefficient"] == "unavailable"
    assert payload["summary"]["score_percent"] == 0
    assert payload["import_result"]["processed_source_count"] == 0
    assert payload["import_result"]["error_count"] == 1
    assert all(row[1] == "0" for row in payload["coverage_cards"])

    read_response = client.get(
        "/admin/dashboard/body-index?project_id=invalid_body_index_project"
    )
    assert read_response.status_code == 200
    assert read_response.json()["summary"] == payload["summary"]


def test_scout_dashboard_body_index_import_dedupes_and_sanitizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "HealthExport"
    source_dir.mkdir()
    _write_body_index_health_export_zip(
        source_dir / "HealthAutoExport-body-index-a.zip",
        day="2026-06-02",
        workout_id="walk-body-index-a",
        hour=8,
    )
    _write_body_index_health_export_zip(
        source_dir / "HealthAutoExport-body-index-b.zip",
        day="2026-06-03",
        workout_id="walk-body-index-b",
        hour=9,
    )
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "store",
    )
    client = TestClient(create_admin_app())

    rejected = client.post(
        "/admin/dashboard/body-index/import",
        json={"project_id": "test_body_index", "source_dir": str(source_dir)},
    )
    assert rejected.status_code == 400

    response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "test_body_index",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["schema_version"] == "scout_dashboard_body_index.v1"
    assert payload["project_id"] == "test_body_index"
    assert payload["import_status"] == "imported"
    assert payload["summary"]["evidence_status"] == "available"
    assert payload["import_result"]["new_source_count"] == 2
    assert payload["import_result"]["duplicate_source_count"] == 0
    assert payload["import_result"]["processed_source_count"] == 2
    assert payload["import_result"]["error_count"] == 0
    coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
    assert coverage["Health exports"] == "2"
    assert coverage["Walking sessions"] == "2"
    assert coverage["GPX tracks"] == "2"
    assert int(coverage["15-min windows"]) > 0
    assert int(coverage["Provider metrics"]) >= 4
    assert "vo2_max" in payload["provider_metrics"]
    assert "walking_heart_rate_average" in payload["provider_metrics"]
    provider_metric_summaries = {
        metric["metric_name"]: metric for metric in payload["provider_metric_summaries"]
    }
    assert provider_metric_summaries["vo2_max"]["median_value"] == 37.0
    assert provider_metric_summaries["vo2_max"]["mean_value"] == 37.0
    assert provider_metric_summaries["vo2_max"]["sample_count"] == 4
    assert provider_metric_summaries["resting_heart_rate"]["median_value"] == 72.0
    health_signals = {row[0]: row for row in payload["health_signals"]}
    assert health_signals["VO2max Baseline"][2] == "median 37.0 / n=4"
    assert health_signals["Resting HR"][2] == "median 72.0 bpm / n=2"
    assert health_signals["HRV Baseline"][2].startswith("median ")
    assert health_signals["HR Pressure Windows"][2].endswith("windows")
    vo2_trend = health_signals["VO2max Baseline"][5]
    assert vo2_trend["direction"] == "mid"
    assert vo2_trend["position_percent"] == 50
    assert vo2_trend["min_label"] == "min 36.9"
    assert vo2_trend["baseline_label"] == "baseline 37.0"
    assert vo2_trend["average_label"] == "avg 37.0"
    assert vo2_trend["max_label"] == "max 37.1"
    assert "min-max range" in vo2_trend["summary"]
    pressure_trend = health_signals["HR Pressure Windows"][5]
    assert pressure_trend["min_label"] == "min 0"
    assert pressure_trend["max_label"].startswith("max ")
    assert payload["boundary"]["raw_health_payload_shared"] is False
    assert payload["boundary"]["raw_gpx_shared"] is False
    assert payload["boundary"]["exact_timestamps_shared"] is False
    assert payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert payload["boundary"]["safety_api_called"] is False
    assert payload["boundary"]["outbound_alert_sent"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "heartRateData" not in serialized
    assert "latitude" not in serialized
    assert "longitude" not in serialized
    assert "<trkpt" not in serialized
    assert "HealthAutoExport-body-index-a.zip" not in serialized
    assert "2026-06-02 08:00:00 +0800" not in serialized

    second_response = client.post(
        "/admin/dashboard/body-index/import",
        json={
            "project_id": "test_body_index",
            "source_dir": str(source_dir),
            "confirm_import": True,
        },
    )
    assert second_response.status_code == 200, second_response.text
    second_payload = second_response.json()
    assert second_payload["import_result"]["new_source_count"] == 0
    assert second_payload["import_result"]["duplicate_source_count"] == 2
    assert second_payload["import_result"]["processed_source_count"] == 2

    read_response = client.get("/admin/dashboard/body-index?project_id=test_body_index")
    assert read_response.status_code == 200
    read_payload = read_response.json()
    assert read_payload["coverage_cards"] == second_payload["coverage_cards"]
    assert read_payload["summary"]["evidence_status"] == "available"
    serialized_read = json.dumps(read_payload, ensure_ascii=False)
    for forbidden_value in (
        "heartRateData",
        "latitude",
        "longitude",
        "<trkpt",
        "HealthAutoExport-body-index-a.zip",
        "2026-06-02 08:00:00 +0800",
    ):
        assert forbidden_value not in serialized_read


def test_scout_dashboard_body_index_watch_imports_new_zip(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_id = "test_body_index_watch"
    source_dir = tmp_path / "HealthExportWatch"
    source_dir.mkdir()
    monkeypatch.setattr(
        admin_api,
        "DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT",
        tmp_path / "watch_store",
    )
    client = TestClient(create_admin_app())

    rejected = client.post(
        "/admin/dashboard/body-index/watch/start",
        json={
            "project_id": project_id,
            "source_dir": str(source_dir),
            "interval_seconds": 1,
        },
    )
    assert rejected.status_code == 400

    response = client.post(
        "/admin/dashboard/body-index/watch/start",
        json={
            "confirm_watch": True,
            "project_id": project_id,
            "source_dir": str(source_dir),
            "interval_seconds": 1,
            "operator_alias": "watch_test",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["running"] is True

    try:
        _write_body_index_health_export_zip(
            source_dir / "HealthAutoExport-watch-new.zip",
            day="2026-06-04",
            workout_id="walk-body-index-watch",
            hour=7,
        )
        deadline = time.monotonic() + 12
        payload: dict[str, object] | None = None
        status: dict[str, object] | None = None
        while time.monotonic() < deadline:
            status_response = client.get(
                f"/admin/dashboard/body-index/watch/status?project_id={project_id}"
            )
            assert status_response.status_code == 200
            status = status_response.json()
            read_response = client.get(
                f"/admin/dashboard/body-index?project_id={project_id}"
            )
            assert read_response.status_code == 200
            payload = read_response.json()
            coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
            if coverage.get("Health exports") == "1":
                break
            time.sleep(0.25)
        assert payload is not None
        assert status is not None
        coverage = {row[0]: row[1] for row in payload["coverage_cards"]}
        assert coverage["Health exports"] == "1"
        assert coverage["Walking sessions"] == "1"
        assert status["running"] is True
        assert int(status["scan_count"]) >= 1
        assert int(status["import_count"]) >= 1
        assert status["last_result"]["new_source_count"] == 1
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "heartRateData" not in serialized
        assert "HealthAutoExport-watch-new.zip" not in serialized
        assert "<trkpt" not in serialized
    finally:
        stop_response = client.post(
            "/admin/dashboard/body-index/watch/stop",
            json={"project_id": project_id},
        )
        assert stop_response.status_code == 200
        assert stop_response.json()["running"] is False


def test_scout_dashboard_serves_pace_fit_emergency_desktop_approval_ui() -> None:
    client = TestClient(create_admin_app())

    response = client.get("/admin/dashboard/emergency-approval-desktop-v0")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'data-emergency-ui-version="v0"' in response.text
    assert 'data-dashboard-emergency-mode="desktop-only"' in response.text
    assert '<section class="mobile-device"' not in response.text
    assert 'data-emergency-surface="mobile"' not in response.text
    assert 'data-map-surface="mobile"' not in response.text
    assert 'data-evidence-frame="mobile"' not in response.text
    assert 'data-emergency-surface="desktop"' in response.text
    assert '<header class="desktop-header">' not in response.text
    assert "Scout Emergency Approval Console" not in response.text
    assert "Emergency Approval Desktop UI v0" not in response.text
    assert 'data-dashboard-sent-state="sent=false"' in response.text
    assert "sent=false" in response.text
    assert "safety_api_called: false" in response.text

    legacy_response = client.get("/admin/dashboard/emergency-mobile-approval-v0")
    assert legacy_response.status_code == 200
    assert 'data-dashboard-emergency-mode="desktop-only"' in legacy_response.text
    assert 'data-emergency-surface="mobile"' not in legacy_response.text


def test_scout_dashboard_documentation_records_active_change_log() -> None:
    doc = DOC.read_text(encoding="utf-8")

    assert "# Scout Dashboard v0.1" in doc
    assert "## Active Recording Rule" in doc
    assert "Status: active." in doc
    assert "continue recording until the user explicitly says to stop" in doc
    assert "## Implementation Record" in doc
    assert "Import New Trip Tab Added" in doc
    assert "GPX Import and Map Preparation Parameters Exposed" in doc
    assert "Reference GPX Inputs Merged" in doc
    assert "Documentation Recording Rule Added" in doc
    assert "Template Project Root and Material Root Clarified" in doc
    assert "Material Root Overlap With DTM and MCP Clarified" in doc
    assert "Optional Import Parameters Marked" in doc
    assert "Workspace Root and BBox Derivation Clarified" in doc
    assert "Workspace Root and Target Name Consolidated" in doc
    assert "Optional Parameters Collapsed Into Advanced Frame" in doc
    assert "Low-value Import Panels Condensed" in doc
    assert "Country Material Pool Tab Added" in doc
    assert "Route Context Briefing Regeneration And Product Copy Cleanup" in doc
    assert "Route Context Intelligence Spec-Aligned Briefing Generation" in doc
    assert "Route Briefing Trip-Only Product Copy Guard" in doc
    assert "Future LoRaWAN Sender Dashboard Placement" in doc
    assert "scout_lorawan_sender.py" in doc
    assert "Primary dashboard integration should be `MQTT / Observer Message`." in doc
    assert "sender/action lane" in doc
    assert "command candidates, queue state, dry-run/live send" in doc
    assert "it should not own the sender workbench" in doc
    assert "`Debug Message` may show sender status" in doc
    assert "must remain status-only and must not own the send button" in doc
    assert "send_sos" in doc
    assert "trigger_l4" in doc
    assert "change_safety_level" in doc
    assert "Pace Fit Body Index Dashboard" in doc
    assert "HealthExport Body Index UX Implemented" in doc
    assert "Body Index HealthExport Import Merge Button" in doc
    assert "Body Index Baseline Trend Arrows" in doc
    assert "Body Index Directory Watch Import" in doc


def test_scout_dashboard_contains_requested_navigation_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for expected in (
        "Home",
        "Features",
        "LBS",
        "Workspace",
        "Import New Trip",
        "Trip Intake",
        "Country Material Pool",
        "Admin Surfaces",
        "Pre-trip",
        "Admin",
        "Debug",
        "Agent",
        "Map",
        "Timeline Evidence",
        "Safety / Emergency",
        "Exploring for Six Axis",
        "Pace Dashboard",
        "Body Index",
        "Emergency UI",
        "Debug Message",
        "MQTT / Observer Message",
        "Settings / Configure",
    ):
        assert expected in html

    assert 'data-route="features-lbs"' in html
    assert 'data-route="features-workspace"' in html
    assert 'data-route="features-import-new-trip"' in html
    assert 'data-route="features-country-material-pool"' in html
    assert 'data-route="surface-pretrip"' in html
    assert 'data-route="surface-admin"' in html
    assert 'data-route="surface-debug"' in html
    assert 'data-route="outdoor-pace-fit-body-index"' in html
    assert 'data-route="outdoor-pace-fit-emergency"' in html


def test_scout_dashboard_points_to_current_chilai_workspace() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PROJECT_ID = "chilai_nanhua_day1_scoutAI";' in html
    assert 'new URLSearchParams(window.location.search).get("projectId")' in html
    assert "^[A-Za-z0-9_.-]+$" in html
    assert (
        'const WORKSPACE_ROOT = "/Users/alexwang0315/workspace/'
        'chilai_nanhua_day1_scoutAI";'
    ) in html
    assert "chilai_nanhua_day1 route map" not in html
    assert "chilai_nanhua_day1_scoutAI route map" in html


def test_scout_dashboard_embeds_existing_admin_surfaces() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "renderSurfaceFrame" in html
    assert 'id="surfaceFrame"' in html
    assert 'class="surface-frame"' in html
    assert 'src: surfaceSrc("/admin/pretrip")' in html
    assert 'src: surfaceSrc("/admin")' in html
    assert 'src: surfaceSrc("/admin/debug")' in html
    assert "projectId=${encodeURIComponent(projectId())}" in html
    assert "Admin Surfaces" in html
    assert "Current Admin Surfaces" not in html
    assert "Open full page" in html


def test_scout_dashboard_data_fetches_have_timeout_fallback() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "const FETCH_TIMEOUT_MS = 20000;" in html
    assert "const ASSISTANT_QUERY_TIMEOUT_MS = 240000;" in html
    assert "const PRETRIP_PROJECT_FETCH_TIMEOUT_MS = 180000;" in html
    assert "new AbortController()" in html
    assert "const timeoutMs = Number(options.timeoutMs) || FETCH_TIMEOUT_MS;" in html
    assert "signal: controller.signal" in html
    assert "window.clearTimeout(timer)" in html
    assert "{ timeoutMs: PRETRIP_PROJECT_FETCH_TIMEOUT_MS }" in html
    assert "setRoute(routeFromHash());" in html
    assert "loadData().finally(() =>" in html
    assert "routeUsesEmbeddedFrame(state.route)" in html
    assert 'return route === "map" || route === "agent" || route.startsWith("surface-");' in html
    assert "routeUsesWideFrame(route)" in html
    assert 'return route === "agent" || route === "debug" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index" || route === "outdoor-pace-fit-emergency";' in html
    assert "routeUsesFullFrame(route)" in html
    assert 'return route === "map";' in html
    assert "/debug-projection`" not in html


def test_scout_dashboard_agent_tab_posts_to_same_origin_assistant_api() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'id="dashboardAgent"' in html
    assert 'data-agent-query-path="/assistant/query"' in html
    assert 'const ASSISTANT_STATUS_PATH = "/assistant/status";' in html
    assert 'const ASSISTANT_QUERY_PATH = "/assistant/query";' in html
    assert 'id="agentTranscript"' in html
    assert 'id="agentComposer"' in html
    assert 'id="agentQuestionInput"' in html
    assert 'id="agentAskButton"' in html
    assert 'id="agentProjectChip"' in html
    assert 'id="agentFallbackToggle"' in html
    assert 'id="agentRawEvalToggle"' in html
    assert "AI HAT+2 fallback" in html
    assert "Facts-only model eval" in html
    assert "agentUseAiHatFallback" in html
    assert "agentUseAiHatRawEval" in html
    assert "width: fit-content;" in html
    assert "max-width: min(900px, 86%);" in html
    assert "border: 0;" in html
    assert ".agent-message.user .agent-message-body" in html
    assert 'class="agent-message-body"' in html
    assert "function displayAgentAnswer(answer)" in html
    assert ".replace(/^結論[:：]\\s*/u, \"\")" in html
    assert "response?.evidence_backed_answer" in html
    assert "response?.local_model_answer" in html
    assert "AI HAT+2 原始回答（grounding 失敗，僅供品質檢查）" in html
    assert "回答（AI HAT+2 grounded repair）" in html
    assert "回答（AI HAT+2 synthesized from workspace facts）" in html
    assert "回答（AI HAT+2 staged missing-context synthesis）" in html
    assert "回答（AI HAT+2 + field-state-short-answer skill）" in html
    assert "skill using：${aiHatSkillId" in html
    assert "function agentAiHatSkillId(response)" in html
    assert "ai_hat_skill_id=" in html
    assert "回答（AI HAT+2 action + verified Scout evidence）" not in html
    assert "AI HAT+2 模型原始輸出（typed decision 不算自然語言回答）" in html
    assert "AI HAT+2 typed decision token" in html
    assert "AI HAT+2 action token" in html
    assert "if (aiHatActionToken)" in html
    assert "Verified Scout evidence：已用於上方 hybrid answer" not in html
    assert '"typed_decision_only"' in html
    assert '"typed_decision_with_verified_evidence"' in html
    assert '"typed_missing_context_action_only"' in html
    assert "function agentAiHatTypedDecision(response)" in html
    assert "function agentAiHatActionToken(response)" in html
    assert "ai_hat_typed_decision=" in html
    assert "ai_hat_action_token=" in html
    assert "模型未產生獨立回答（AI HAT+2 copied grounding reference）" in html
    assert "AI HAT+2 原始回答（未通過 grounding，不計成功）" not in html
    assert "模型未成功回答（工具摘要另列）" in html
    assert "不能算作模型答題成功" in html
    assert "function agentAiHatGenerationMode(response)" in html
    assert "function agentAnswerLooksLikeReferenceCopy(answer, reference)" in html
    assert "ai_hat_generation_mode=" in html
    assert "function agentDeterministicFallbackOnly(response)" in html
    assert "deterministic_tool_fallback_only=true" in html
    assert "segment_missing_display_geometry_count" in html
    assert "segment_missing_distance_count" in html
    assert "Scout grounding reference（工具摘要，不取代本地模型回答）" in html
    assert "Scout grounding reference" in html
    assert "quality verdict：AI HAT+2 evidence-prompted answer did not preserve required Scout evidence" in html
    assert "near-copy/subset of the deterministic Scout grounding reference" in html
    assert "typed decision 只能算分類成功" in html
    assert "action token 不能算作回答，也不會套用固定句型" in html
    assert "transparent Scout evidence lock" not in html
    assert "missing|缺|stale|過期" not in html
    assert "(?:缺少|過期|过期)" in html
    assert "AI HAT+2 raw answer（未採用：grounding failed）" not in html
    assert "useEvidenceAsAnswer" not in html
    assert (
        'displayAgentAnswer(response?.answer || "(empty assistant answer)")'
        in html
    )
    assert "response?.evidence_backed_answer || response?.answer" not in html
    assert "Pydantic AI read-only model interpretation" in html
    assert "AI HAT+2 ${observability.local_model_name}" in html
    assert "observability.provider_class" not in html
    assert "function bindAgentChatControls()" in html
    assert "function ensureAgentChat()" in html
    assert "function submitAgentQuestion()" in html
    assert "postJson(" in html
    assert "ASSISTANT_QUERY_PATH," in html
    assert "{ timeoutMs: ASSISTANT_QUERY_TIMEOUT_MS }" in html
    assert "request timed out after" in html
    assert 'surface: "pretrip"' in html
    assert "project_id: projectId()" in html
    assert 'runtime_preference: "cloud"' in html
    assert 'payload.runtime_preference = "ai_hat_plus_2_fallback";' in html
    assert "payload.ai_hat_raw_eval = Boolean(state.agentUseAiHatRawEval);" in html
    assert "AI HAT+2 本地模型回答" in html
    assert "prompt-contract=${aiHatPromptContract}" in html
    assert "answer-contract=${aiHatAnswerContract}" in html
    assert "few-shot=${aiHatFewShotSource}:${aiHatFewShotCount}" in html
    assert "few-shot-topic=${aiHatFewShotQuestion}" in html
    assert "endpoint-response=${aiHatEndpointResponse}" in html
    assert "eval-tokens=${aiHatEvalCount}" in html
    assert "selected-call=${aiHatSelectedCall}" in html
    assert "sampling=${aiHatSampling}" in html
    assert "response?.local_model_attempts" in html
    assert "model attempt ${attempt.call_index}" in html
    assert "answer-template=${aiHatAnswerTemplate}" in html
    assert "本地模型只收到 facts-only evidence brief，沒有預寫答案" in html
    assert "function agentAiHatTraceValue(response, prefix)" in html
    assert "meta: state.agentUseAiHatFallback ? [\"AI HAT+2 fallback requested\"] : []" in html
    assert "meta: [`project=${projectId()}`, \"surface=pretrip\"]" not in html
    assert "Same-origin Scout AI conversation through /assistant/query" in html
    assert "No live safety" in html
    assert "SCOUT_AI_ASSISTANT_ENABLED=1" in html
    assert "127.0.0.1:8765" not in html
    assert 'contentGrid?.classList.toggle("is-frame-wide", frameWide);' in html
    assert ".content-grid.is-frame-wide .evidence-drawer" in html
    assert "dashboardAgent.hidden = false;" in html
    assert "dashboardAgent.focus?.({ preventScroll: true });" in html


def test_scout_dashboard_workspace_tab_summarizes_project_stats() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function workspaceStats()" in html
    assert "function renderWorkspaceStatsPanels(stats)" in html
    assert 'data-workspace-stats="true"' in html
    for label in (
        "Route Statistics",
        "Project Counts",
        "Lifecycle Times",
        "Route length",
        "Route points",
        "Elevation range",
        "Reference tracks",
        "Checkpoints",
        "Segments",
        "Terrain tiles",
        "Review queue",
        "Evidence refs",
        "Imported",
        "Layers prepared",
        "Runtime exported",
        "Runtime loaded",
        "Data source",
    ):
        assert label in html

    assert "formatDistanceKm(numberValue(route.distance_m" in html
    assert 'if (value === null || value === undefined || value === "") return "--";' in html
    assert "formatDateTime(" in html
    assert "latestDebugEventTime" in html
    assert "workspaceEvidenceRefCount(project)" in html
    assert "project.import_manifest?.imported_at" in html
    assert "project.layer_preparation?.prepared_at" in html
    assert "state.pretripDataProjectId || projectId()" in html


def test_scout_dashboard_workspace_tab_exposes_structure_cache_and_operations() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderWorkspaceStructurePanels",
        "workspaceStructureRows",
        "renderWorkspaceCachePanels",
        "workspaceCacheRows",
        "renderWorkspaceOperationConsole",
        "bindWorkspaceControls",
        "formatTtl",
        "formatBoolean",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Workspace Structure",
        "Material Index",
        "Workspace Health",
        "Cached Material",
        "Cached TTL",
        "Cache Refs",
        "Workspace Operations",
        "Project root",
        "Source inbox",
        "Normalized route",
        "Import manifest",
        "Layer manifest",
        "Review queue",
        "Runtime handoff",
        "Imagery tiles",
        "Raster OCR",
        "OSM PBF",
        "OSM PBF TTL",
        "CWA TTL",
        "GEE TTL",
        "Weather cacheable",
    ):
        assert label in html

    for action in ("clone", "transfer", "pack", "restore", "delete"):
        assert f'data-workspace-action="{action}"' in html

    assert 'data-workspace-structure="true"' in html
    assert 'data-workspace-cache="true"' in html
    assert 'data-workspace-operations="true"' in html
    assert 'id="workspaceOperationStatus"' in html
    assert 'id="workspaceRedirectProjectInput"' in html
    assert 'id="workspaceSwitchProject"' in html
    assert "operator intent only" in html
    assert "No filesystem mutation is performed by this dashboard." in html
    assert "Delete requires an explicit destructive approval outside this dashboard." in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "Workspace id must use letters, numbers, underscore, dash or dot only." in html


def test_scout_dashboard_import_new_trip_tab_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderImportNewTripPage",
        "renderImportTripPreflight",
        "renderImportTripPipeline",
        "renderImportSelectField",
        "importTripProjectId",
        "importTripDefaultLayerIds",
        "setImportTripStatus",
        "bindImportTripControls",
        "splitImportReferenceGpxSources",
        "classifyImportReferenceGpxSources",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Import New Trip",
        "Import New Trip",
        "Optional Parameters",
        "GPX Import Defaults",
        "Map Preparation Defaults",
        "Defaults are used when this frame stays collapsed.",
        "Import Pipeline",
        "Validate Intake",
        "Stage Import",
        "Open Workspace",
        "operator-triggered",
        "no live safety",
        "boundary metadata",
        "derived routing",
        "GPX required",
        "32 layers",
        "candidate export",
        "no outbound",
        "GIS repro-only",
        "Target name",
        "Project root",
        "Country material pool",
        "Material Pool",
        "material pool",
    ):
        assert label in html

    for marker in (
        'data-import-new-trip="true"',
        'data-import-trip-parameters="true"',
        'data-map-preparation-parameters="true"',
        'data-import-trip-preflight="true"',
        'data-import-trip-pipeline="true"',
        'class="import-context-panel"',
        'class="import-guard-strip"',
        'id="importTripIdInput"',
        'id="importGoldenRouteGpxPath"',
        'id="importWorkspaceRoot"',
        'id="importTargetNameInput"',
        'id="importTripStatus"',
        'data-import-trip-action="validate"',
        'data-import-trip-action="stage"',
        'data-import-trip-action="open"',
        'class="panel optional-parameters-frame"',
    ):
        assert marker in html

    for field_id in (
        "importReferenceGpxSources",
        "importWorkspaceRoot",
        "importTargetNameInput",
        "importTemplateProjectRoot",
        "importMaterialRoot",
        "importDtmDirs",
        "importMcpNamedPointEvidence",
        "importProfile",
        "importStage",
        "importCheckpointSpacingM",
        "importMaxReferenceDisplayPoints",
        "importMaxReasonableGpxSpeedKmh",
        "importMaxPreviousGpxSpeedRatio",
        "importOverwriteWorkspace",
        "prepareLayersList",
        "prepareBBox",
        "prepareRouteEvidenceBundle",
        "prepareRouteCorridorM",
        "prepareReferenceTrackCorridorM",
        "prepareLayersProfile",
        "prepareLayersNetworkMode",
        "prepareAllowNetworkFetch",
        "prepareAiMode",
        "prepareAiOutputPolicy",
        "prepareImageryMinZoom",
        "prepareImageryMaxZoom",
        "prepareSeedImageryCache",
        "prepareImageryProviderAllowsOfflinePrefetch",
        "prepareImagerySeedMaxTiles",
        "prepareImageryCacheFallbackProjectIds",
        "prepareOsmPbfPath",
        "prepareOsmPbfSourceUrl",
        "prepareOsmPbfCacheTtlDays",
        "prepareOsmiumBin",
        "preparePreparedAt",
    ):
        assert field_id in html

    for parameter_label in (
        "Golden route GPX path",
        "Reference GPX directory or paths",
        "Checkpoint spacing (m)",
        "Max reference display points",
        "Max reasonable GPX speed (km/h)",
        "Max previous speed ratio",
        "Layer ids",
        "Route evidence bundle",
        "Route corridor (m)",
        "Reference track corridor (m)",
        "Network mode",
        "AI mode",
        "Imagery min zoom",
        "Imagery max zoom",
        "OSM PBF cache TTL days",
    ):
        assert parameter_label in html

    assert "(optional)" not in html
    assert "Golden route GPX path (optional)" not in html
    assert "Target workspace (optional)" not in html
    assert "Project root (optional)" not in html
    assert "Import Boundary" not in html
    assert "Workspace Routing" not in html
    assert "Preflight Checklist" not in html
    assert "Layer Preparation Target" not in html
    assert "Runtime Handoff Guard" not in html
    assert "Evidence Drawer" not in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true">' in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true" open>' not in html
    assert 'id="importTripWorkspaceInput"' not in html
    assert 'id="prepareLayersWorkspaceRoot"' not in html
    assert 'id="prepareProjectRoot"' not in html

    assert 'if (route === "features-import-new-trip") return renderImportNewTripPage();' in html
    assert "importTripDraft" in html
    assert "goldenRouteGpx: goldenRouteInput.value.trim()" in html
    assert "countryMaterialPool: countryPoolInput.value || \"TW\"" in html
    assert "referenceGpxSources: fieldValue(\"importReferenceGpxSources\")" in html
    assert "targetName: targetNameValue()" in html
    assert "workspaceRoot: workspaceRootValue()" in html
    assert "prepareWorkspaceRoot: workspaceRootValue()" in html
    assert "prepareProjectRoot: derivedProjectRoot()" in html
    assert "importTripProjectRoot(workspaceRoot, targetName)" in html
    assert "prepareLayers: fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert "fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert 'value="${escapeHtml(draft.goldenRouteGpx || "")}"' in html
    assert "Reference GPX sources must be absolute paths." in html
    assert "Use either one directory path or a list of .gpx absolute paths." in html
    assert "1 reference GPX directory" in html
    assert "explicit GPX paths" in html
    assert "At least one map preparation layer id is required." in html
    assert "GPX import numeric parameters must be greater than 0." in html
    assert "Map preparation corridor parameters must be greater than 0." in html
    assert 'bindImportTripControls();' in html
    assert 'bindCountryMaterialPoolControls();' in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "Trip id must use letters, numbers, underscore, dash or dot only." in html
    assert "Target name must use letters, numbers, underscore, dash or dot only." in html
    assert "importReferenceDirectory" not in html
    assert "importReferenceGpxPaths" not in html


def test_scout_dashboard_country_material_pool_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "countryMaterialPools",
        "countryMaterialPoolByCode",
        "countryMaterialPoolDefaults",
        "renderCountryMaterialPoolPage",
        "materialPoolCell",
        "renderMaterialResourceCard",
        "renderMaterialProviderRow",
        "bindCountryMaterialPoolControls",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Country Material Pool",
        "country-scoped material and API provider defaults",
        "Country Material Pool",
        "Material Classes",
        "Route Context References",
        "API / Provider Matrix",
        "Import Defaults",
        "Map Preparation Uses",
        "Taiwan",
        "Japan",
        "Global Fallback",
        "DTM",
        "Base Maps",
        "Government Sites",
        "Weather API",
        "Geology API",
        "Marine API",
        "Open Data Entry",
        "CWA",
        "JMA",
        "GSI Maps",
        "NLSC EMAP",
        "Central Geological Survey",
        "林業及自然保育署自然步道資料",
        "台灣山林悠遊網開放資料",
        "臺灣登山申請一站式服務網",
        "國家公園路線開放狀態",
        "內政部國土測繪中心 DEM / DTM / 地形圖",
        "中央氣象署 CODiS / 開放資料",
        "NCDR 災害潛勢資料",
        "消防署山域事故救援案件",
        "TBN 台灣生物多樣性網絡",
        "中研院臺灣百年歷史地圖",
        "尋路・循路－臺灣原住民族古道空間資訊網",
        "國家文化記憶庫",
        "臺灣記憶",
        "地質雲",
        "魯地圖",
        "健行筆記",
        "Hikingbook",
        "PTT Hiking",
        "登山補給站",
        "rescue_training_reference",
        "community_media_evidence",
        "country-specific Geofabrik extract",
        "material_root",
        "dtm_dirs",
        "osm_pbf_source_url",
        "weather_provider",
        "candidate evidence only",
        "no live safety",
    ):
        assert label in html

    for marker in (
        "const COUNTRY_MATERIAL_POOLS = [",
        'data-country-material-pool="true"',
        'data-country-material-code="${escapeHtml(candidate.code)}"',
        'role="tablist"',
        'class="material-pool-layout"',
        'class="material-resource-grid"',
        'data-route-context-references="true"',
        'class="material-provider-table"',
        'if (route === "features-country-material-pool") return renderCountryMaterialPoolPage();',
        "state.activeCountryMaterialPool = code;",
        "countryMaterialPoolDefaults(countryPoolInput.value)",
        "materialRoot: \"\"",
        "dtmDirs: \"\"",
        "osmPbfSourceUrl: \"\"",
    ):
        assert marker in html

    assert "Japan providers; no CWA" in html
    assert "routeContextSources" in html
    assert "These P0/P1 entries come from specs/scout-route-context-layer and source-catalog.md." in html
    assert "catalog entries are not evidence by themselves" in html
    assert "This page sets default hints for import and layer preparation." not in html
    assert "It does not fetch, mutate workspace files, load runtime packages, or change safety truth." not in html


def test_scout_dashboard_timeline_evidence_uses_pretrip_tree_categories() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PRETRIP_DATA_PROJECT_ID = "chilai_nanhua_day1";' in html
    assert "function pretripDataProjectIds()" in html
    assert "fetchFirstPretripJson" in html
    assert "renderPretripEvidencePanel" in html
    assert "pretripEvidenceGroups" in html
    assert 'data-pretrip-evidence-source="${escapeHtml(sourceProject)}"' in html
    for tab_id, label in (
        ("default", "CP / Timeline"),
        ("map_risk", "Map / Risk"),
        ("completed", "Completed GPX"),
        ("review", "Review / Queue"),
        ("info", "Info / Other"),
    ):
        assert f'id: "{tab_id}"' in html
        assert label in html

    for group_name in (
        "Evidence Timeline",
        "Reference Segment Timing",
        "Checkpoints",
        "AI GIS CP",
        "GIS CP Areas",
        "Major Critical Points",
        "Boss Points",
        "Mileage Tags",
        "Overpass Trail Corridors",
        "Overpass Terrain Risk",
        "OSM Trail Network",
        "Risk Score",
        "Baseline Risk",
        "Calibrated Heat",
        "Risk Delta",
        "Environmental Risk Derivatives",
        "CWA QPF",
        "CWA Weather",
        "Soil Moisture",
        "Antecedent Rain",
        "Segments",
        "Retreat Routes",
        "Reference GPX",
        "Capability Timeline",
        "Info Sections",
        "Review Groups",
        "Review Queue",
    ):
        assert group_name in html

    assert 'data-evidence-tab="${escapeHtml(tab.id)}"' in html
    assert "state.activeEvidenceTab = selectedTab;" in html
    assert "state.activeMapEvidenceTab = selectedTab;" in html


def test_scout_dashboard_map_tab_uses_pretrip_map_only_surface() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'if (route === "map") {' in html
    assert "ensurePretripMapFrame()" in html
    assert "function ensurePretripMapFrame()" in html
    assert "bindPretripMapOnlyFrame" in html
    assert "applyPretripMapOnlyFrame" in html
    assert "scout-dashboard-map-only-style" in html
    assert 'id="dashboardMap"' in html
    assert 'id="pretripMapFrame"' in html
    assert 'data-map-mode="pretrip-map-only"' in html
    assert 'data-map-source="/admin/pretrip"' in html
    assert 'hidden aria-hidden="true" tabindex="-1"' in html
    assert 'frame.dataset.projectId === currentProjectId' in html
    assert 'frame.dataset.mapOnlyBound' in html
    assert "is-frame-full" in html
    assert 'surfaceSrc("/admin/pretrip")' in html
    assert "data-map-connected" in html
    assert "pre-trip map only" in html
    assert 'id="dashboardMapEvidence"' in html
    assert "renderMapEvidenceRail" in html
    assert "Map Evidence" in html
    assert "mapEvidenceCollapsed" in html
    assert "data-map-evidence-toggle" in html
    assert 'aria-label="${collapsed ? "Expand Map Evidence" : "Collapse Map Evidence"}"' in html
    assert 'rail.classList.toggle("is-collapsed", collapsed);' in html
    assert "map-evidence-rail.is-collapsed" in html
    assert "focusDashboardMapEvidence" in html
    assert "pretripEvidenceGroupOpen" in html
    assert "renderPretripEvidenceGroup(group, index, {defaultOpen: false})" in html
    assert 'add("map_risk", "Segments", view.segments' in html
    assert "scheduleMapEvidenceFocusRetry" in html
    assert "pretripMapHasRenderedTargets" in html
    assert "Loading pre-trip timeline evidence for map focus." in html
    assert '["Checkpoints", "AI GIS CP", "Major Critical Points"].includes(group.title)' in html
    assert "mapWindow.focusMapFor" in html
    assert "mapWindow.selectEvidence" in html
    assert "data-map-evidence-source" in html
    assert "data-map-target-ids" in html
    assert 'const mapToolRight = state.mapEvidenceCollapsed ? "14px" : "418px";' in html
    assert "right: ${mapToolRight} !important;" in html
    assert "dashboardMapOnly" in html
    assert "mapOnlyReady" in html
    assert "grid-template-rows: minmax(0, 1fr);" in html
    assert ".dashboard-frame" in html
    assert 'dashboardShell?.classList.toggle("is-frame-full", frameFull);' in html
    assert 'document.body.classList.toggle("is-frame-full", frameFull);' in html
    assert "body.is-frame-full" in html
    assert ".dashboard-shell.is-frame-full .dashboard-sidebar" in html
    assert "height: 100%;" in html
    assert "min-height: 0;" in html
    assert "#readinessStrip" in html
    assert ".route-pane" in html
    assert ".detail-pane" in html

    assert "const MAX_RENDERED_SEGMENT_POINTS = 80;" in html
    assert "SCOUT_LAYER_IDS.map((layerId, index)" in html
    assert "function buildDashboardSegmentPaths(rawSegments, bounds)" in html
    assert "segment.display_geometry || {}" in html
    assert "display.coordinate_segments" in html
    assert "segmentPaths: buildDashboardSegmentPaths(state.project?.segments, bounds)" in html
    segment_branch = html.split('if (layerId === "segments") {', 1)[1].split(
        'if (["reference-tracks", "retreat"].includes(layerId)) {',
        1,
    )[0]
    assert "mapData.segmentPaths" in segment_branch
    assert 'data-segment-id="${escapeHtml(segment.id)}"' in segment_branch
    assert 'stroke="#00d4ff"' in segment_branch
    assert 'stroke-width="5.6"' in segment_branch
    assert 'stroke-dasharray="7 4"' in segment_branch
    assert "mapData.routePath" not in segment_branch


def test_scout_dashboard_map_exposes_cwa_imagery_bridge_and_controls() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    for marker in (
        'id="dashboardCwaImagery"',
        'data-dashboard-cwa-imagery-product',
        'data-dashboard-cwa-imagery-window',
        'data-dashboard-cwa-imagery-timeline',
        'data-dashboard-cwa-imagery-opacity="radar"',
        'data-dashboard-cwa-imagery-opacity="satellite"',
        'data-dashboard-cwa-rainfall-product',
        'data-dashboard-cwa-rainfall-opacity',
        'data-dashboard-cwa-rainfall-legend',
        'data-dashboard-cwa-rainfall-status',
        'data-dashboard-cwa-imagery-play',
        'data-dashboard-cwa-imagery-status',
        'aria-label="CWA radar and satellite imagery controls"',
        "bindDashboardCwaImageryBridge",
        "syncDashboardCwaImageryControls",
        "scoutCwaImageryController",
        'scout:cwa-imagery-state',
        "cache-only",
        "candidate-only",
    ):
        assert marker in html

    assert "window.scoutCwaImageryController" in pretrip_html
    assert "function cwaImageryStateSnapshot()" in pretrip_html
    assert 'new CustomEvent("scout:cwa-imagery-state"' in pretrip_html
    assert "/admin/pretrip/projects/${encodeURIComponent(projectId)}/weather-imagery" in pretrip_html
    assert "SCOUT_CWA_API_KEY" not in html


def test_scout_dashboard_cwa_imagery_documentation_contract() -> None:
    dashboard_doc = DOC.read_text(encoding="utf-8")
    layer_doc = LAYER_CONTRACT_DOC.read_text(encoding="utf-8")
    weather_doc = WEATHER_DOC.read_text(encoding="utf-8")

    assert "Dashboard MAP CWA imagery controls" in dashboard_doc
    assert "same-origin pretrip controller" in dashboard_doc
    assert "cache-only" in dashboard_doc
    assert "Dashboard MAP" in layer_doc
    assert "scoutCwaImageryController" in layer_doc
    assert "Dashboard MAP" in weather_doc
    assert "server-side" in weather_doc


def test_scout_dashboard_debug_message_runtime_details_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderDebugRuntimeDetails",
        "renderDebugRuntimeSummary",
        "renderDebugActiveDetail",
        "renderDebugStateDetail",
        "renderDebugMonitorDetail",
        "renderDebugSoftwareDetail",
        "renderDebugHardwareDetail",
        "renderDebugIngressDetail",
        "renderDebugIncidentDetail",
        "renderDebugSkillToolDetail",
        "renderDebugOutboundDetail",
        "renderDebugBoundaryDetail",
        "renderDebugApiDetail",
        "renderDebugVisualPanel",
        "renderDebugHardwareInterfaceNode",
        "renderDebugBoundaryGateGrid",
        "renderDebugApiTile",
        "debugRuntimeMatrix",
        "activeDebugRuntimeRecord",
        "debugEventMatchesCategory",
        "bindDebugDetailControls",
        "debugEndpointText",
        "debugAllEvents",
        "debugProviderEntries",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Runtime Details",
        "L0-L4",
        "Events",
        "Hardware",
        "Software",
        "Monitor",
        "Provider",
        "Ingress",
        "Incident",
        "Ln / Skill",
        "Skills",
        "Tools",
        "Outbound",
        "Boundary",
        "API",
        "Current L0-L4 State",
        "Monitoring Center",
        "Provider Degraded Status",
        "Runtime Software State",
        "Hardware Readiness",
        "Hardware Interface Bus",
        "Hardware Providers",
        "Hardware Boundary Gates",
        "Mobile/Wearable Ingress",
        "Ingress Boundary",
        "Incident And Bridge Status",
        "Ln And Skill Runs",
        "Agent Tool Trace",
        "Scout Skills",
        "Outbound Queue",
        "Boundary Snapshot",
        "API Payloads",
        "Runtime Sources",
        "Boundary Notes",
        "Debug Message Stream",
        "API Payload Matrix",
    ):
        assert label in html

    for source in (
        "/debug/events?limit=200",
        "/debug/state",
        "/debug/messages",
        "/debug/mobile-wearable/ingress",
        "/debug/monitoring",
        "/admin/hardware-readiness/context",
        "GPIO/I2C/I2S/TTS/Bluetooth/UART/power/GNSS/IMU/USB/SSD inventory",
    ):
        assert source in html

    assert "DEBUG_DETAIL_CATEGORIES" in html
    assert 'activeDebugDetail: "state"' in html
    for state_field in (
        "runtimeDebugEvents",
        "runtimeDebugEventPayload",
        "debugRuntimeState",
        "debugMessages",
        "debugMessagesPayload",
        "mobileWearableIngress",
        "monitoringCenter",
        "hardwareReadiness",
    ):
        assert state_field in html

    assert 'data-debug-runtime-details="true"' in html
    assert 'data-debug-message-details="true"' in html
    assert 'data-debug-message-sources="true"' in html
    assert 'data-debug-console="true"' in html
    assert 'data-debug-stream-tables="true"' in html
    assert 'data-debug-detail="${escapeHtml(record.id)}"' in html
    assert "debug-telemetry-bar" in html
    assert "debug-tab-shell" in html
    assert "debug-console-grid" in html
    assert "debug-drawer-stack" in html
    assert "debug-table-grid" in html
    assert "debug-slim-row" in html
    assert "debug-node-grid" in html
    assert "debug-flow" in html
    assert "debug-bus" in html
    assert "debug-level-strip" in html
    assert "debug-api-tile" in html
    assert "debug-pin-grid" in html
    assert "/admin/debug" in html
    assert "/admin/hardware-readiness/context" in html
    assert "debug-projection-events" in html
    assert "debug-projection" in html
    assert "not triggered from dashboard" in html
    assert "readiness metadata only" in html
    assert "mock / dry-run message evidence only" in html
    assert "state.activeDebugDetail = button.dataset.debugDetail || \"state\";" in html


def test_scout_dashboard_outdoor_six_forces_subtree_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for route, label, system_name in (
        ("outdoor-route-context", "Route Context", "Route Context Intelligence"),
        ("outdoor-pace-fit", "Pace Fit", "Pace Fit"),
        ("outdoor-permission", "Permission", "Contextual Permissioning"),
        ("outdoor-architecture", "Architecture", "Route Architecture Intelligence"),
        ("outdoor-weather", "Weather", "Weather-to-Decision Intelligence"),
        ("outdoor-navigation", "Navigation", "Navigation & Terrain Intelligence"),
    ):
        assert f'data-route="{route}"' in html
        assert label in html
        assert system_name in html

    for removed_label in ("戶外六力", "探索力", "自信力", "勇氣力", "路線力", "天氣力", "地圖力"):
        assert removed_label not in html

    for decision in (
        "GO",
        "CONDITIONAL_GO",
        "GUIDED_ONLY",
        "CHANGE_PLAN",
        "DELAY",
        "NO_GO",
        "ESCALATE",
    ):
        assert decision in html


def test_scout_dashboard_pace_fit_removes_low_information_blocks() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "Readiness & Pace Fit" not in html
    assert 'decisionBand(force.decision, "以最慢成員估算回程 buffer 偏低"' not in html
    assert 'renderMetricPanel("Readiness & Pace Fit"' not in html
    assert 'force.route === "outdoor-pace-fit" ? force.label' in html
    assert 'data-pace-fit-dashboard="true"' in html
    assert '<div class="pace-fit-card-head"><h3>Challenge Fit</h3></div>' not in html
    assert "Pace Controls" in html
    assert "Pace Evidence" in html
    assert "Risk Budget Calculator" in html
    assert "Current CP Status" in html
    assert "CP Timeline" in html
    assert "Pace Object Preview" in html
    assert "Synchronized Map" in html
    assert "slowestMemberBasis" in html
    assert "pace-fit-workbench" in html
    assert "pace-budget-table" in html
    assert "pace-cp-timeline" in html
    assert "pace-mini-map" in html
    assert "Data confidence" not in html


def test_scout_dashboard_pace_fit_body_index_dashboard_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "bodyIndexMetrics",
        "bodyIndexHealthCoverage",
        "bodyIndexHealthSignals",
        "bodyIndexPressureTimeline",
        "bodyIndexProviderMetrics",
        "bodyIndexStatusPath",
        "bodyIndexWatchStatusPath",
        "bodyIndexImportStatus",
        "bodyIndexWatchStatus",
        "bodyIndexWatchSummary",
        "bodyIndexWatchTone",
        "bodyIndexSummary",
        "bodyIndexRows",
        "bodyIndexScorePercent",
        "bodyIndexDisplayValue",
        "bodyIndexDefaultTrend",
        "normalizeBodyIndexHealthSignal",
        "bodyIndexTrendArrow",
        "bodyIndexTrendPercent",
        "renderBodyIndexSignalTrend",
        "scheduleBodyIndexWatchRefresh",
        "bindBodyIndexControls",
        "renderBodyIndexMetric",
        "renderBodyIndexHealthSignal",
        "renderBodyIndexProviderDrawer",
        "renderPaceFitBodyIndexPage",
    ):
        assert f"function {function_name}" in html

    for marker in (
        'data-route="outdoor-pace-fit-body-index"',
        'if (route === "outdoor-pace-fit-body-index") return renderPaceFitBodyIndexPage();',
        'paceFitSubTabs("outdoor-pace-fit-body-index")',
        'data-body-index-dashboard="true"',
        'data-scout-pace-coefficient="true"',
        'data-body-index-metric="${escapeHtml(metric.id)}"',
        "body-index-dashboard",
        "body-index-summary",
        "body-index-metric-grid",
        "body-index-layout",
        "body-index-ring",
        "body-index-impact-row",
        "body-index-health-strip",
        "body-index-health-grid",
        "body-index-pressure-timeline",
        "body-index-provider-drawer",
        "body-index-provider-grid",
        "body-index-import-button",
        "body-index-import-status",
        "body-index-watch-controls",
        "body-index-watch-button",
        ".body-index-signal-card em",
        "body-index-signal-trend",
        "body-index-trend-axis",
        "body-index-trend-marker",
        "body-index-trend-labels",
        'data-body-index-trend="${escapeHtml(direction)}"',
        'data-health-export-body-index-ui="true"',
        'data-body-index-provider-metrics="collapsed"',
        "BODY_INDEX_FETCH_TIMEOUT_MS = 180000",
        'BODY_INDEX_STATUS_PATH = "/admin/dashboard/body-index"',
        'BODY_INDEX_IMPORT_PATH = "/admin/dashboard/body-index/import"',
        'BODY_INDEX_WATCH_STATUS_PATH = "/admin/dashboard/body-index/watch/status"',
        'BODY_INDEX_WATCH_START_PATH = "/admin/dashboard/body-index/watch/start"',
        'BODY_INDEX_WATCH_STOP_PATH = "/admin/dashboard/body-index/watch/stop"',
        "fetchJson(bodyIndexStatusPath(), { timeoutMs: BODY_INDEX_FETCH_TIMEOUT_MS })",
        "fetchJson(bodyIndexWatchStatusPath())",
        'data-body-index-import',
        'data-body-index-watch-start',
        'data-body-index-watch-stop',
        'data-body-index-watch-controls="true"',
        "state.bodyIndexData = payload",
        "bodyIndexImportBusy",
        "bodyIndexWatchBusy",
        "confirm_import: true",
        "confirm_watch: true",
        "merged ${newCount} new / skipped ${duplicateCount} duplicates",
    ):
        assert marker in html

    for metric_id, english_label, spec_label in (
        ("flat_ground_speed", "Flat Ground Speed", "平地移動速度"),
        ("ascent_speed", "Ascent Speed", "上坡速度"),
        ("descent_speed", "Descent Speed", "下坡速度"),
        ("technical_slowdown", "Technical Terrain Slowdown", "技術地形降速率"),
        ("rest_frequency", "Rest Frequency", "休息頻率"),
        ("late_trip_decay", "Late-trip Decay", "行程後段速度衰退"),
        ("load_impact", "Load Impact", "負重影響"),
        ("weather_impact", "Weather Impact", "天候影響"),
        ("experience_confidence", "Experience Confidence", "經驗可信度"),
    ):
        assert metric_id in html
        assert english_label in html
        assert spec_label in html

    for label in (
        "Scout Pace Coefficient",
        "Energy Reserve",
        "Vulnerability",
        "Experience Trust",
        "Route Impact Mapping",
        "Evidence Matrix",
        "Challenge Fit",
        "slowest member basis",
        "advisory planning",
        "planning evidence",
        "source_provider only",
        "no diagnosis",
        "no Phase 1 mutation",
        "no safety endpoint",
        "no outbound",
        "completed_trip_gpx",
        "route_progress_frame",
        "terrain_time_model",
        "rest_stop_pattern",
        "weather_overlay",
        "team_slowest_member",
        "Body Index Overview",
        "Health Baseline Signals",
        "Window Pressure Timeline",
        "Health Provider Metrics",
        "HealthExport local aggregate",
        "HealthExport-aware",
        "HealthExport import idle",
        "Import HealthExport",
        "Start Watch",
        "watch stopped",
        "Scan sec",
        "Importing local HealthExport zip files",
        "median -- bpm",
        "median -- ms",
        "-- windows",
        "baseline position unavailable",
        "min --",
        "baseline --",
        "avg --",
        "max --",
        "↗",
        "↘",
        "→",
        "HealthAutoExport",
        "Health exports",
        "Walking sessions",
        "GPX tracks",
        "15-min windows",
        "Provider metrics",
        "no HealthExport evidence imported",
        "no sanitized windows imported",
        "No provider metrics imported.",
        "No Scout Pace Coefficient has been calculated.",
        "awaiting evidence",
        "unavailable until evidence import",
        "coefficient_metrics",
        "source value only",
        "not live oxygen uptake",
        "VO2max Baseline",
        "Resting HR",
        "HRV Baseline",
        "Walking HR Average",
        "Active Energy Reset Cue",
        "Recovery Debt Windows",
        "HR Pressure Windows",
        "Step + Distance Pattern",
    ):
        assert label in html


def test_scout_dashboard_pace_fit_emergency_ui_subtree_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'data-route="outdoor-pace-fit-emergency"' in html
    assert "function paceFitSubTabs(activeRoute)" in html
    assert "function renderPaceFitEmergencyPage()" in html
    assert 'if (route === "outdoor-pace-fit-emergency") return renderPaceFitEmergencyPage();' in html
    assert 'paceFitSubTabs("outdoor-pace-fit-emergency")' in html
    assert 'data-pace-fit-emergency-ui="true"' in html
    assert 'data-emergency-approval-frame="desktop"' in html
    assert 'src="/admin/dashboard/emergency-approval-desktop-v0"' in html
    assert 'href="/admin/dashboard/emergency-approval-desktop-v0"' in html
    assert "Emergency Approval Desktop UI v0" not in html
    assert "Scout Emergency Approval Console" not in html
    assert "Emergency approval desktop frame" in html
    assert "desktop only" in html
    assert "pace-emergency-toolbar" in html
    assert "sent=false" in html
    assert "no safety endpoint" in html
    assert "no outbound transport" in html
    assert "pending approval" in html
    assert 'return route === "agent" || route === "debug" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index" || route === "outdoor-pace-fit-emergency";' in html
    assert "decisionBand(" not in html
    assert ".decision-band" not in html
    assert "Primary output" not in html
    assert "Next action" not in html


def test_scout_dashboard_route_context_embeds_skill_trip_briefing() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function routeContextBriefingProjectId()" in html
    assert "function routeContextBriefingSrc()" in html
    assert "function renderRouteBriefingMetaBlock" in html
    assert "return candidate || PRETRIP_DATA_PROJECT_ID;" in html
    assert 'return route === "agent" || route === "debug" || route === "outdoor-route-context" || route === "outdoor-pace-fit" || route === "outdoor-pace-fit-body-index" || route === "outdoor-pace-fit-emergency";' in html
    assert 'decisionBand(force.decision, "Scout AI route-context trip briefing loaded"' not in html
    assert "/admin/pretrip/projects/${project}/briefings/route-context" in html
    assert "data-route-context-briefing=\"true\"" in html
    assert 'class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed"' in html
    assert '<details class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed" open>' not in html
    assert "Briefing metadata" in html
    assert "route-briefing-meta-grid" in html
    assert "route-briefing-meta-block" in html
    assert "Scout AI Trip Briefing" not in html
    assert "route-briefing-ops" in html
    assert "data-route-context-briefing-regenerate" in html
    assert "Regenerate with Scout AI" in html
    assert "/briefings/route-context/regenerate" in html
    assert "function routeContextBriefingVariantsPath()" in html
    assert "function routeContextBriefingVariantsGeneratePath()" in html
    assert "function routeContextBriefingVariantFileSrc(ref)" in html
    assert "/briefings/route-context/variants" in html
    assert "/briefings/route-context/variants/generate" in html
    assert "data-route-context-briefing-variants-generate" in html
    assert "Generate 5 variants with Scout AI" in html
    assert "Calling Scout AI route-context-intelligence skill for five variants" in html
    assert "model: \"nvidia:z-ai/glm-5.2\"" in html
    assert "model_max_tokens: 7000" in html
    assert "reference_variants_dir_ref" in html
    assert "max_reference_similarity: 0.6" in html
    assert "reference similarity" in html
    assert "reference_similarity_gate" in html
    assert "Open variants index" in html
    assert "Model audit" in html
    assert "single Scout AI model call" in html
    assert "canonical briefing unchanged" in html
    assert "Calling Scout AI, then rebuilding briefing artifact" in html
    assert "Calling Scout AI via OpenRouter" not in html
    assert "Open briefing" in html
    assert "outputs/briefings/route_context_briefing.html" in html
    assert "scout-route-context-briefing skill" in html
    assert "pretrip_route_context_collection" in html
    assert "candidate-only" in html
    assert "runtime_safety_truth=false" in html
    assert "stop permission, route open/closed decision" in html
    assert "no Phase 1 mutation, no safety endpoint write" in html
    assert '["Outbound", "closed"]' in html
    assert "no live safety automation" not in html
    assert '<div class="debug-main-stack">\n            ${renderMetricPanel("Briefing Source"' not in html


def test_scout_dashboard_emergency_boundary_and_mobile_independence_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "Emergency Package Draft only" not in html
    assert "mobile approval UI remains independent" not in html
    assert "sent=false" in html
    assert "external_send_performed=false" in html
    assert "/safety/" not in html
    assert "fetch(`${apiBase()}${path}`" in html
    assert 'method: "POST"' in html
    assert "/briefings/route-context/regenerate" in html
    assert "confirm_regenerate: true" in html


def test_scout_dashboard_layer_contract_ids_are_present() -> None:
    html = PAGE.read_text(encoding="utf-8")

    expected_layers = (
        "imagery",
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "completed-track",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "risk-score",
        "checkpoints",
        "pois",
        "hazards",
        "route-notes",
        "cwa-weather",
        "mcp",
        "boss-points",
        "events",
        "weather-api",
    )
    for layer_id in expected_layers:
        assert f'"{layer_id}"' in html
    assert "SCOUT_LAYER_IDS" in html
    assert "input type=\"checkbox\" data-layer" in html
    assert "data-layer-group" in html


def _write_body_index_health_export_zip(
    path: Path,
    *,
    day: str,
    workout_id: str,
    hour: int,
) -> Path:
    payload = {
        "data": {
            "workouts": [
                _body_index_walk_workout(
                    workout_id,
                    day=day,
                    hour=hour,
                    distances_km=[0.72, 0.89, 0.8],
                    step_counts=[1072, 1250, 1260],
                    active_energy_kj=[100, 110, 100],
                    heart_rates=[100] * 15 + [101] * 15 + [94] * 15,
                )
            ],
            "metrics": [
                _body_index_metric("vo2_max", [36.9, 37.1]),
                _body_index_metric("heart_rate_variability", [42.4, 34.1]),
                _body_index_metric("resting_heart_rate", [72]),
                _body_index_metric("walking_heart_rate_average", [106]),
            ],
        }
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("HealthAutoExport-body-index.json", json.dumps(payload, ensure_ascii=False))
        archive.writestr(
            "private-route.gpx",
            '<gpx><trk><trkseg><trkpt lat="40.0" lon="116.0" /></trkseg></trk></gpx>',
        )
    return path


def _body_index_walk_workout(
    workout_id: str,
    *,
    day: str,
    hour: int,
    distances_km: list[float],
    step_counts: list[int],
    active_energy_kj: list[int],
    heart_rates: list[int],
) -> dict[str, object]:
    duration_min = len(distances_km) * 15
    end_hour = hour + duration_min // 60
    end_min = duration_min % 60
    distance_rows: list[dict[str, object]] = []
    step_rows: list[dict[str, object]] = []
    energy_rows: list[dict[str, object]] = []
    hr_rows: list[dict[str, object]] = []
    for minute in range(duration_min):
        window = minute // 15
        row_date = f"{day} {hour + minute // 60:02d}:{minute % 60:02d}:00 +0800"
        distance_rows.append(
            {
                "date": row_date,
                "qty": distances_km[window] / 15.0,
                "units": "km",
                "source": "fixture.watch",
            }
        )
        step_rows.append(
            {
                "date": row_date,
                "qty": step_counts[window] / 15.0,
                "units": "count",
                "source": "fixture.watch",
            }
        )
        energy_rows.append(
            {
                "date": row_date,
                "qty": active_energy_kj[window] / 15.0,
                "units": "kJ",
                "source": "fixture.watch",
            }
        )
        hr_rows.append(
            {
                "date": row_date,
                "Avg": heart_rates[minute],
                "Max": heart_rates[minute],
                "Min": heart_rates[minute],
                "units": "bpm",
                "source": "fixture.watch",
            }
        )
    return {
        "id": workout_id,
        "name": "步行",
        "start": f"{day} {hour:02d}:00:00 +0800",
        "end": f"{day} {end_hour:02d}:{end_min:02d}:00 +0800",
        "duration": duration_min * 60,
        "distance": {"qty": sum(distances_km), "units": "km"},
        "avgHeartRate": {
            "qty": round(sum(heart_rates) / len(heart_rates), 1),
            "units": "bpm",
        },
        "maxHeartRate": {"qty": max(heart_rates), "units": "bpm"},
        "activeEnergyBurned": {"qty": sum(active_energy_kj), "units": "kJ"},
        "walkingAndRunningDistance": distance_rows,
        "stepCount": step_rows,
        "activeEnergy": energy_rows,
        "heartRateData": hr_rows,
        "route": [
            {
                "latitude": 40.0,
                "longitude": 116.0,
                "altitude": 600,
                "timestamp": f"{day}T{hour:02d}:00:00+08:00",
            }
        ],
    }


def _body_index_metric(name: str, values: list[float]) -> dict[str, object]:
    return {
        "name": name,
        "data": [{"qty": value, "source": "fixture.watch"} for value in values],
    }


def test_dashboard_cwa_truth_state_play_guard_and_single_product_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")

    for marker in (
        "CWA_UI_STATUSES",
        "dashboardCwaDerivedStatus",
        "stale_data",
        "no_coverage",
        "zero_precipitation",
        "unavailable",
        "formatCwaTimestamp",
        'data-dashboard-cwa-panel-toggle',
        'data-dashboard-cwa-sheet-state',
    ):
        assert marker in html

    assert 'productId: "radar"' in html
    assert 'play.disabled = !bridgeReady || Number(snapshot.maxFrameIndex || 0) < 1;' in html
    assert "freshness: snapshot.freshness" in html
    assert "coverageStatus: snapshot.coverageStatus" in html

    assert "function cwaDerivedStatus" in pretrip_html
    assert 'productId: "radar"' in pretrip_html
    assert "playableFrameCount < 2" in pretrip_html
    assert "button.disabled = playableFrameCount < 2" in pretrip_html
    assert "freshness:" in pretrip_html
    assert "coverageStatus:" in pretrip_html


def test_dashboard_weather_route_consumes_cache_only_live_cwa_data() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for marker in (
        "function loadWeatherData",
        "function renderWeatherLiveSummary",
        "/rainfall-grids",
        "/weather-imagery",
        'data-weather-status',
        'data-weather-open-map',
        "cache-only",
        "示例規則",
        "Preview",
    ):
        assert marker in html

    assert "CHANGE_PLAN" not in html.split("function renderWeatherPage", 1)[1].split(
        "function renderNavigationPage", 1
    )[0]


def test_dashboard_uses_strict_project_route_scoped_loading_and_truthful_debug_state() -> None:
    html = PAGE.read_text(encoding="utf-8")

    project_id_candidates = html.split("function pretripDataProjectIds()", 1)[1].split(
        "async function fetchJson", 1
    )[0]
    assert "replace(/_scoutAI$/" not in project_id_candidates
    assert "PRETRIP_DATA_PROJECT_ID" not in project_id_candidates
    assert "return [projectId()]" in project_id_candidates

    for marker in (
        "ROUTE_DATA_SCOPES",
        "loadDataForRoute",
        "loadedDataScopes",
        "debugEndpointStates",
        "DEGRADED",
        'data-debug-retry',
    ):
        assert marker in html


def test_dashboard_primary_information_architecture_and_mobile_shell_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert html.count("data-nav-primary") == 8
    for label in (
        "Overview",
        "Plan Trip",
        "Map & Evidence",
        "Team & Pace",
        "Safety Decisions",
        "Assistant",
        "System",
        "Labs / Preview",
    ):
        assert label in html

    assert 'data-route-truth="live"' in html
    assert 'data-route-truth="partial"' in html
    assert 'data-route-truth="preview"' in html
    assert 'id="dashboardNavToggle"' in html
    assert 'aria-controls="dashboardSidebar"' in html
    assert "bindMobileNavigation" in html
    assert "70dvh" in html
    assert "env(safe-area-inset-bottom)" in html


def test_dashboard_p0_p2_review_regressions_are_fail_closed() -> None:
    html = PAGE.read_text(encoding="utf-8")
    pretrip_html = PRETRIP_PAGE.read_text(encoding="utf-8")
    smoke = SMOKE_TOOL.read_text(encoding="utf-8")

    assert 'if (snapshot.status === "unavailable") return "unavailable";' in html
    assert "dataScopeErrors" in html
    assert "loadedDataScopes.add(scope);" in html.split(
        "async function loadDataScope", 1
    )[1].split("async function performDataScope", 1)[0].split(".then", 1)[1]
    assert "window.location.replace(nextUrl.toString())" in html
    assert "sidebar.inert = !open" in html
    assert 'sidebar.setAttribute("aria-hidden", open ? "false" : "true")' in html

    overlay_loader = pretrip_html.split(
        "async function loadCwaRainfallGridOverlay", 1
    )[1].split("function bindCwaWeatherImageryControls", 1)[0]
    assert 'grid_overlay_status: overlay.status' in overlay_loader
    assert 'overlay.status === "ready" && gridCells.length ? "ready" : "no_coverage"' not in overlay_loader

    assert "/admin/dashboard?projectId=chilai_nanhua_day1#map" in smoke
    assert 'replace(\n      "/projects/chilai_nanhua_day1_scoutAI"' not in smoke
