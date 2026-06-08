import inspect
import json
import socket
import urllib.request
from pathlib import Path

import pytest

import pretrip_decision_register
from pretrip_decision_register import (
    PreTripDecisionRegister,
    REQUIRED_OPEN_QUESTION_IDS,
    REQUIRED_RESOLVED_DECISION_IDS,
    load_pretrip_decision_register,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "tests" / "fixtures" / "pretrip" / "decision_register.json"


def test_decision_register_fixture_captures_required_phase4_decisions():
    register = load_pretrip_decision_register(REGISTER_PATH)
    payload = register.model_dump(mode="json")

    assert payload["register_id"] == "pretrip.decision_register.phase4.v0"
    assert payload["artifact_kind"] == "pretrip_decision_register"
    assert payload["phase"] == "phase_4_pretrip"
    assert payload["metadata_only"] is True
    assert payload["alpha_workable_mode"] is True
    assert payload["no_network"] is False
    assert payload["no_crawler"] is False
    assert payload["ui_scope"] == "alpha_workable_admin"
    assert payload["no_runtime_effects"] is False
    assert payload["runtime_operator_confirmation_required"] is True
    assert {item["decision_id"] for item in payload["resolved_decisions"]} == (
        REQUIRED_RESOLVED_DECISION_IDS
    )
    assert {item["decision_id"] for item in payload["open_questions"]} == (
        REQUIRED_OPEN_QUESTION_IDS
    )
    assert len(payload["resolved_decisions"]) == 16
    assert len(payload["open_questions"]) == 0
    assert json.loads(register.to_json()) == payload
    assert register.to_json().endswith("\n")


def test_decision_register_is_metadata_only_and_has_no_provider_or_ui_dependencies(monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("decision register must not use network")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(urllib.request, "urlopen", reject_network)

    register = load_pretrip_decision_register(REGISTER_PATH)
    source = inspect.getsource(pretrip_decision_register)

    assert register.metadata_only is True
    forbidden_fragments = [
        "requests",
        "httpx",
        "urlopen",
        "create_connection",
        "BeautifulSoup",
        "selenium",
        "playwright",
        "safety_api",
        "server",
        "phase1_incident_bridge",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source


def test_decision_register_records_expected_resolutions_and_open_backlog():
    register = load_pretrip_decision_register(REGISTER_PATH)
    resolved = {item.decision_id: item for item in register.resolved_decisions}
    open_questions = {item.decision_id: item for item in register.open_questions}

    assert "Chilai-Nanhua" in resolved[
        "phase4.decision.primary_fixture.chilai_nanhua_day1"
    ].resolution
    assert "scout_260512" in resolved[
        "phase4.decision.regression_fixture.scout_260512"
    ].resolution
    assert "metadata-only" in resolved["phase4.decision.dtm.metadata_only"].resolution
    assert "return-to-entry" in resolved[
        "phase4.decision.retreat.return_to_entry"
    ].resolution
    assert "Joyhike and PTT" in resolved[
        "phase4.decision.sources.joyhike_ptt_reference_only"
    ].resolution
    assert "optional" in resolved["phase4.decision.timing.optional_fields"].resolution
    assert resolved["phase4.decision.ui.fixture_backed_read_only"].impact == "ui_boundary"
    assert "read-only" in resolved[
        "phase4.decision.ui.fixture_backed_read_only"
    ].resolution
    assert resolved["phase4.decision.ui.scale_assisted_review"].impact == "ui_boundary"
    assert "filter-first, group-first, AI-assisted triage" in resolved[
        "phase4.decision.ui.scale_assisted_review"
    ].resolution
    assert "/safety/*" in resolved[
        "phase4.decision.ui.scale_assisted_review"
    ].constraints[2]
    assert "1000m corridor distance" in resolved[
        "phase4.decision.poi.corridor_coverage_policy"
    ].resolution
    assert "CWA-style reference thresholds" in resolved[
        "phase4.decision.weather_daylight.quantitative_thresholds"
    ].resolution
    assert "AI-assisted" in resolved[
        "phase4.decision.contour.ai_assisted_admin_review"
    ].resolution
    assert "metadata-only" in resolved[
        "phase4.decision.route_comparison.derived_summary_only"
    ].resolution
    assert resolved[
        "phase4.decision.review_log.fixture_only_append_only"
    ].impact == "review_decision_log"
    assert "append-only" in resolved[
        "phase4.decision.review_log.fixture_only_append_only"
    ].resolution
    assert "no MissionGraph compile" in resolved[
        "phase4.decision.review_log.fixture_only_append_only"
    ].resolution
    assert resolved[
        "phase4.decision.external_import_queue.url_request_only"
    ].impact == "external_import_queue"
    assert "no fetch, no crawler, no raw payload" in resolved[
        "phase4.decision.external_import_queue.url_request_only"
    ].resolution
    assert "planning-reference candidate" in resolved[
        "phase4.decision.external_import_queue.url_request_only"
    ].resolution
    assert resolved[
        "phase4.decision.backlog.current_policy_set_closed"
    ].impact == "scope_boundary"
    assert "route-corridor POI coverage only" in resolved[
        "phase4.decision.backlog.current_policy_set_closed"
    ].resolution
    assert "derived-summary-only" in resolved[
        "phase4.decision.backlog.current_policy_set_closed"
    ].resolution
    assert "Open Phase 4 alpha product boundaries" in resolved[
        "phase4.decision.alpha.workable_boundaries_open"
    ].resolution
    assert open_questions == {}

def test_decision_register_rejects_missing_required_or_misfiled_records():
    payload = json.loads(REGISTER_PATH.read_text())
    payload["resolved_decisions"] = payload["resolved_decisions"][1:]

    with pytest.raises(ValueError, match="missing resolved decisions"):
        PreTripDecisionRegister.model_validate(payload)

    payload = json.loads(REGISTER_PATH.read_text())
    payload["open_questions"] = [
        {
            **payload["resolved_decisions"][0],
            "decision_id": "phase4.decision.test_misfiled_open_record",
            "status": "resolved",
            "resolution": "incorrectly resolved",
        }
    ]

    with pytest.raises(ValueError, match="open_questions must only contain open records"):
        PreTripDecisionRegister.model_validate(payload)


def test_decision_register_schema_is_strict():
    payload = json.loads(REGISTER_PATH.read_text())
    payload["network_probe"] = "not allowed"

    with pytest.raises(ValueError):
        PreTripDecisionRegister.model_validate(payload)

    payload = json.loads(REGISTER_PATH.read_text())
    payload["resolved_decisions"][0]["runtime_hook"] = "not allowed"

    with pytest.raises(ValueError):
        PreTripDecisionRegister.model_validate(payload)
