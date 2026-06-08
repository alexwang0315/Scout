import json
import shutil
from pathlib import Path

from pretrip_departure_reviewed_candidates import (
    DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF,
    build_departure_reviewed_candidates_from_apply_plan,
    write_departure_reviewed_candidates_for_workspace,
)
from pretrip_review_decision_apply import load_review_decision_apply_plan


PROJECT_ID = "chilai_nanhua_day1"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
REPO_APPLY_PLAN = FIXTURE_PROJECT_ROOT / "outputs" / "review_decision_apply_plan.json"


def test_departure_reviewed_candidates_promotes_only_reviewed_positive_decisions():
    apply_plan = load_review_decision_apply_plan(REPO_APPLY_PLAN)

    package = build_departure_reviewed_candidates_from_apply_plan(
        project_id=PROJECT_ID,
        source_apply_plan_ref="outputs/review_decision_apply_plan.json",
        apply_plan=apply_plan,
    )

    assert package.artifact_kind == "pretrip_departure_reviewed_candidates"
    assert package.counts.model_dump(mode="json") == {
        "source_decision_count": 3,
        "promoted_candidate_count": 2,
        "accepted_count": 1,
        "corrected_count": 1,
        "rejected_audit_count": 1,
        "runtime_truth_count": 0,
    }
    assert [candidate.decision for candidate in package.candidates] == [
        "accepted",
        "corrected",
    ]
    assert {candidate.promotion_scope for candidate in package.candidates} == {
        "planning_assumption_candidate",
    }
    assert package.rejected_audit_refs == [
        "poi_readiness_policy.chilai_nanhua_day1.route_corridor_poi_coverage"
    ]
    assert package.boundary.not_departure_approval is True
    assert package.boundary.package_addendum_only is True
    assert package.boundary.runtime_mutation_allowed is False
    assert package.boundary.phase1_runtime_mutation_allowed is False
    assert package.boundary.phase2_writeback_allowed is False
    assert package.boundary.runtime_safety_truth is False
    assert all(candidate.runtime_safety_truth is False for candidate in package.candidates)


def test_departure_reviewed_candidates_writer_writes_workspace_only(tmp_path):
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(FIXTURE_PROJECT_ROOT, workspace_project_root)
    destination = workspace_project_root / DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF
    original_fixture_files = {
        path: path.read_bytes()
        for path in sorted(FIXTURE_PROJECT_ROOT.rglob("*"))
        if path.is_file()
    }

    package = write_departure_reviewed_candidates_for_workspace(workspace_project_root)

    assert package.counts.promoted_candidate_count == 2
    assert destination.is_file()
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["artifact_kind"] == "pretrip_departure_reviewed_candidates"
    assert payload["counts"]["promoted_candidate_count"] == 2
    assert payload["boundary"]["not_departure_approval"] is True
    assert payload["boundary"]["runtime_mutation_allowed"] is False
    assert {
        path: path.read_bytes()
        for path in sorted(FIXTURE_PROJECT_ROOT.rglob("*"))
        if path.is_file()
    } == original_fixture_files
