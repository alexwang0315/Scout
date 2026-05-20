import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_review_decision_apply
from pretrip_review_decision_log import ReviewDecision, ReviewDecisionRecord
from pretrip_review_decision_apply import (
    PreTripReviewDecisionApplyPlan,
    build_chilai_review_decision_apply_plan,
    build_review_decision_apply_plan_from_paths,
    load_review_decision_apply_plan,
)
from pretrip_review_decision_store import append_review_decision


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
APPLY_PLAN_PATH = FIXTURE_ROOT / "outputs" / "review_decision_apply_plan.json"
REVIEW_DECISION_LOG_PATH = FIXTURE_ROOT / "reviews" / "review_decision_log.json"
PACKAGE_PATH = FIXTURE_ROOT / "outputs" / "pretrip_package.json"


def test_builds_deterministic_review_decision_apply_plan():
    first = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)
    second = build_chilai_review_decision_apply_plan(ROOT)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")

    payload = first.model_dump(mode="json")
    assert payload["plan_id"] == "review_decision_apply_plan.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_review_decision_apply_plan"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["review_decision_log_ref"] == "reviews/review_decision_log.json"
    assert payload["package_ref"] == "outputs/pretrip_package.json"
    assert payload["package_id"] == "pretrip.chilai_nanhua_day1.v0"
    assert payload["counts"] == {
        "decision_count": 3,
        "accepted": 1,
        "corrected": 1,
        "rejected": 1,
        "source_ref_count": 3,
        "package_candidate_apply_count": 0,
        "runtime_mutation_count": 0,
    }


def test_decision_apply_plan_records_decisions_without_package_application():
    plan = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)
    decisions_by_candidate = {
        decision.candidate_ref: decision for decision in plan.decisions
    }

    assert set(decisions_by_candidate) == {
        "contour.g11.seg_001_003",
        "policy_candidate.chilai_nanhua_day1.seg.001",
        "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage",
    }
    assert all(decision.package_candidate_matches == [] for decision in plan.decisions)
    assert all(decision.package_candidate_apply_count == 0 for decision in plan.decisions)
    assert all(decision.would_apply_to_package is False for decision in plan.decisions)

    accepted = decisions_by_candidate["contour.g11.seg_001_003"]
    assert accepted.decision == "accepted"
    assert accepted.target_ids == ["seg.001", "seg.002", "seg.003"]
    assert accepted.source_refs == ["outputs/contour_interpretation_candidates.json"]

    corrected = decisions_by_candidate["policy_candidate.chilai_nanhua_day1.seg.001"]
    assert corrected.decision == "corrected"
    assert corrected.target_ids == ["seg.001"]
    assert corrected.source_refs == ["outputs/segment_policy_candidates.json"]
    assert corrected.correction_summary == (
        "Keep the conservative daylight and retreat flags, but require water status to remain reviewer-confirmed."
    )

    rejected = decisions_by_candidate[
        "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage"
    ]
    assert rejected.decision == "rejected"
    assert rejected.target_ids == ["route_corridor_poi_coverage"]
    assert rejected.source_refs == ["outputs/poi_readiness_candidates.json"]


def test_review_decision_apply_plan_boundary_and_no_raw_payloads():
    plan = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)

    assert plan.boundary.model_dump(mode="json") == {
        "would_apply_only": True,
        "source_mutation_allowed": False,
        "package_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "compiles_mission_graph": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Decision apply plan is a deterministic local planning artifact only.",
            "It records what the append-only review decisions point at without mutating source artifacts, PreTripPackage, runtime state, Phase 2 Brain state, or MissionGraph outputs.",
            "Current decision candidate refs are contour, segment-policy, and POI-readiness candidates, not direct PreTripPackage candidate ids.",
        ],
    }

    payload_without_boundary_flag = plan.model_dump(mode="json")
    payload_without_boundary_flag["boundary"].pop("raw_payloads_embedded")
    serialized = json.dumps(payload_without_boundary_flag, ensure_ascii=False, sort_keys=True)
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
        "source_payload",
        "raw_payload",
        "elevation_grid",
        "terrain_tile",
        "payload_fragment",
    ]:
        assert fragment not in serialized


def test_review_decision_apply_fixture_matches_builder_output():
    fixture_payload = json.loads(APPLY_PLAN_PATH.read_text(encoding="utf-8"))
    fixture = load_review_decision_apply_plan(APPLY_PLAN_PATH)
    regenerated = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")
    PreTripReviewDecisionApplyPlan.model_validate(fixture_payload)


def test_builds_apply_plan_from_appended_local_decision_log(tmp_path):
    tmp_log_path = tmp_path / "review_decision_log.json"
    shutil.copy2(REVIEW_DECISION_LOG_PATH, tmp_log_path)
    protected_paths = [
        PACKAGE_PATH,
        FIXTURE_ROOT / "outputs" / "pretrip_package.reviewed.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.candidate.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.reviewed.json",
        APPLY_PLAN_PATH,
    ]
    before = _file_hashes(protected_paths)

    append_review_decision(
        tmp_log_path,
        ReviewDecisionRecord(
            decision_id="review_decision.chilai_nanhua_day1.accepted.local_extra_weather_policy",
            draft_action_id="review_draft.chilai_nanhua_day1.local_extra_weather_policy",
            decision=ReviewDecision.ACCEPTED,
            candidate_ref="local_extra_weather_policy.chilai_nanhua_day1.day1",
            target_ids=["route_corridor_weather_policy"],
            source_review_queue_item_refs=[
                {
                    "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
                    "item_id": "review_queue.chilai_nanhua_day1.local_extra_weather_policy",
                    "source_ref": "outputs/review_queue_manifest.json",
                    "candidate_ref": "local_extra_weather_policy.chilai_nanhua_day1.day1",
                }
            ],
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T10:15:00+08:00",
            summary="Accepted local appended weather policy pointer as candidate-only planning context.",
        ),
    )

    plan = build_review_decision_apply_plan_from_paths(
        project_id="chilai_nanhua_day1",
        review_decision_log_path=tmp_log_path,
        package_path=PACKAGE_PATH,
        review_decision_log_ref="tmp/review_decision_log.json",
        package_ref="outputs/pretrip_package.json",
    )

    assert plan.counts.decision_count == 4
    assert plan.counts.accepted == 2
    assert plan.counts.package_candidate_apply_count == 0
    assert plan.counts.runtime_mutation_count == 0
    assert all(decision.package_candidate_apply_count == 0 for decision in plan.decisions)
    assert all(decision.would_apply_to_package is False for decision in plan.decisions)
    assert _file_hashes(protected_paths) == before

    fixture_payload = json.loads(APPLY_PLAN_PATH.read_text(encoding="utf-8"))
    regenerated_fixture = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)
    assert fixture_payload == regenerated_fixture.model_dump(mode="json")


def test_decision_apply_builder_does_not_alter_package_or_mission_graph():
    protected_paths = [
        FIXTURE_ROOT / "outputs" / "pretrip_package.json",
        FIXTURE_ROOT / "outputs" / "pretrip_package.reviewed.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.candidate.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.reviewed.json",
    ]
    before = _file_hashes(protected_paths)

    plan = build_chilai_review_decision_apply_plan(FIXTURE_ROOT)

    assert _file_hashes(protected_paths) == before
    assert plan.counts.package_candidate_apply_count == 0
    assert plan.counts.runtime_mutation_count == 0
    assert plan.boundary.compiles_mission_graph is False

    source = inspect.getsource(pretrip_review_decision_apply)
    assert "import admin_api" not in source
    assert "from admin_api" not in source
    assert "from pretrip_mission_compiler" not in source
    assert "build_chilai_mission" not in source
    assert "compile_pretrip" not in source
    assert "MissionGraph(" not in source
    assert "resolve_pretrip_reviewed_package" not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "import httpx" not in source
    assert "from httpx" not in source


def test_review_decision_apply_plan_rejects_runtime_or_package_mutation_claims():
    payload = build_chilai_review_decision_apply_plan(FIXTURE_ROOT).model_dump(mode="json")
    payload["boundary"]["package_mutation_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDecisionApplyPlan.model_validate(payload)

    payload = build_chilai_review_decision_apply_plan(FIXTURE_ROOT).model_dump(mode="json")
    payload["boundary"]["compiles_mission_graph"] = True

    with pytest.raises(ValidationError):
        PreTripReviewDecisionApplyPlan.model_validate(payload)

    payload = build_chilai_review_decision_apply_plan(FIXTURE_ROOT).model_dump(mode="json")
    payload["notes"].append("Attach raw source payload from day1.gpx")

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        PreTripReviewDecisionApplyPlan.model_validate(payload)


def _file_hashes(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    }
