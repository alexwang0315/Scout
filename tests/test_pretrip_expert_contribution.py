import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_expert_contribution
from pretrip_expert_contribution import (
    ExpertContributionLog,
    build_chilai_expert_contribution_log,
    expert_contribution_log_to_json,
    load_expert_contribution_log,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "expert_contribution_log.json"
)


def test_builds_expert_contribution_log_for_candidate_and_import_edits():
    log = build_chilai_expert_contribution_log()
    payload = log.model_dump(mode="json")

    assert payload["log_id"] == "expert_contribution_log.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_expert_contribution_log"
    assert payload["status"] == "candidate_memory_seed_only"
    assert payload["counts"] == {
        "brain_writeback_count": 0,
        "candidate_set_edit_count": 2,
        "contribution_count": 3,
        "external_import_edit_count": 1,
        "memory_seed_candidate_count": 3,
        "raw_payload_count": 0,
    }

    operations = {record["operation"] for record in payload["records"]}
    target_kinds = {record["target_kind"] for record in payload["records"]}
    assert operations == {"add_candidate", "update_candidate", "add_import_request"}
    assert target_kinds == {
        "checkpoint_candidate",
        "retreat_route_candidate",
        "external_import_request",
    }
    assert all(record["ai_assist"]["memory_seed_candidate"] is True for record in payload["records"])
    assert all(record["ai_assist"]["memory_writeback_allowed"] is False for record in payload["records"])
    assert all(record["review_state"] == "needs_human_review" for record in payload["records"])


def test_expert_contribution_log_boundaries_prevent_runtime_brain_and_raw_writes():
    log = build_chilai_expert_contribution_log()
    payload = log.model_dump(mode="json")

    assert payload["boundary"]["candidate_set_edit_intent_only"] is True
    assert payload["boundary"]["external_import_edit_intent_only"] is True
    assert payload["boundary"]["requires_human_review_before_apply"] is True
    assert payload["boundary"]["memory_seed_candidate_only"] is True
    assert payload["boundary"]["brain_writeback_allowed"] is False
    assert payload["boundary"]["package_mutation_allowed"] is False
    assert payload["boundary"]["mission_graph_mutation_allowed"] is False
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert payload["boundary"]["phase2_writeback_allowed"] is False
    assert payload["boundary"]["external_api_calls_made"] is False
    assert payload["boundary"]["raw_payloads_embedded"] is False

    serialized = expert_contribution_log_to_json(log)
    for forbidden_fragment in [
        "ObservedFact",
        "raw_html",
        "snapshot_body",
        "raw_gpx",
        "raw_photo",
        "raw_dtm",
        "brain_writeback_allowed\": true",
        "phase2_writeback_allowed\": true",
        "runtime_mutation_allowed\": true",
    ]:
        assert forbidden_fragment not in serialized

    source = inspect.getsource(pretrip_expert_contribution)
    for forbidden_source in [
        "import requests\n",
        "import requests as",
        "requests.get",
        "requests.post",
        "httpx.",
        "urllib.request",
        "urlopen",
        "BeautifulSoup",
        "selenium",
        "playwright",
        "Phase2Brain",
    ]:
        assert forbidden_source not in source


def test_expert_contribution_fixture_matches_builder_output():
    fixture_payload = FIXTURE_PATH.read_text(encoding="utf-8")
    fixture = load_expert_contribution_log(FIXTURE_PATH)
    regenerated = build_chilai_expert_contribution_log()

    assert fixture == regenerated
    assert fixture_payload == expert_contribution_log_to_json(regenerated)


def test_expert_contribution_schema_rejects_misaligned_targets_and_counts():
    payload = build_chilai_expert_contribution_log().model_dump(mode="json")
    payload["records"][0]["operation"] = "add_import_request"
    with pytest.raises(ValidationError):
        ExpertContributionLog.model_validate(payload)

    payload = build_chilai_expert_contribution_log().model_dump(mode="json")
    payload["counts"]["brain_writeback_count"] = 1
    with pytest.raises(ValidationError):
        ExpertContributionLog.model_validate(payload)

    payload = build_chilai_expert_contribution_log().model_dump(mode="json")
    payload["records"][0]["ai_assist"]["memory_writeback_allowed"] = True
    with pytest.raises(ValidationError):
        ExpertContributionLog.model_validate(payload)

    payload = build_chilai_expert_contribution_log().model_dump(mode="json")
    payload["counts"]["candidate_set_edit_count"] = 1
    with pytest.raises(ValidationError):
        ExpertContributionLog.model_validate(payload)
