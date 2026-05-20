import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "golden_cases"
    / "reduced_metadata_only_cases.json"
)


def test_reduced_metadata_golden_cases_cover_phase4_boundary_scenarios():
    payload = _load_fixture()

    assert payload["artifact_kind"] == "pretrip_reduced_metadata_only_golden_cases"
    assert payload["schema_version"] == "0.1.0"
    assert payload["case_count"] == 4
    cases_by_spec = {case["spec_case"]: case for case in payload["cases"]}
    assert set(cases_by_spec) == {
        "missing_evidence_readiness",
        "unreviewed_model_hazard",
        "imagery_reference_only",
        "ai_project_synthesis",
    }

    assert cases_by_spec["missing_evidence_readiness"]["expected_outcome"][
        "hard_readiness_status"
    ] == "not_ready_until_review"
    assert cases_by_spec["unreviewed_model_hazard"]["expected_outcome"][
        "safety_critical_runtime_input"
    ] is False
    assert cases_by_spec["imagery_reference_only"]["expected_outcome"][
        "accepted_planning_assumption"
    ] is False
    assert cases_by_spec["ai_project_synthesis"]["expected_outcome"][
        "direct_brain_writeback"
    ] is False


def test_reduced_metadata_golden_cases_are_metadata_only_and_review_gated():
    payload = _load_fixture()

    for case in payload["cases"]:
        boundary = case["expected_boundary"]
        outcome = case["expected_outcome"]
        assert case["case_id"].startswith("pretrip_golden.")
        assert case["source_refs"]
        assert case["candidate_refs"]
        assert boundary["raw_payloads_embedded"] is False
        assert boundary["crawler_enabled"] is False
        assert boundary["network_call_count"] == 0
        assert boundary["observed_fact_created"] is False
        assert boundary["runtime_mutation_allowed"] is False
        assert boundary["phase1_runtime_mutation_allowed"] is False
        assert boundary["phase2_writeback_allowed"] is False
        assert outcome["requires_human_review"] is True

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "<gpx",
        "<trkpt",
        "coordinates",
        "features",
        "raw_samples",
        "source_payload",
        "snapshot_body",
        "raw_html",
        "catographydata",
        "PdrSample",
        "/safety/",
        "Phase1IncidentBridge",
        "ObservedFact",
    ):
        assert forbidden not in serialized


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
