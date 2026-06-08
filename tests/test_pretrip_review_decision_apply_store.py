import inspect
import json
import shutil
from pathlib import Path

import pytest

import pretrip_review_decision_apply_store
from pretrip_review_decision_apply import load_review_decision_apply_plan
from pretrip_review_decision_apply_store import (
    write_review_decision_apply_plan_for_workspace,
)
from pretrip_review_decision_log import ReviewDecision, ReviewDecisionRecord
from pretrip_review_decision_store import append_review_decision


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
REPO_APPLY_PLAN_PATH = FIXTURE_ROOT / "outputs" / "review_decision_apply_plan.json"
REPO_DECISION_LOG_PATH = FIXTURE_ROOT / "reviews" / "review_decision_log.json"


def test_writes_workspace_apply_plan_after_local_decision_log_append(tmp_path):
    workspace = _copy_chilai_workspace(tmp_path)
    workspace_log_path = workspace / "reviews" / "review_decision_log.json"
    workspace_apply_plan_path = workspace / "outputs" / "review_decision_apply_plan.json"
    before_repo_apply_plan = REPO_APPLY_PLAN_PATH.read_text(encoding="utf-8")
    before_repo_decision_log = REPO_DECISION_LOG_PATH.read_text(encoding="utf-8")

    append_review_decision(workspace_log_path, _extra_decision())

    plan = write_review_decision_apply_plan_for_workspace(workspace)
    persisted = load_review_decision_apply_plan(workspace_apply_plan_path)

    assert plan.model_dump(mode="json") == persisted.model_dump(mode="json")
    assert json.loads(workspace_apply_plan_path.read_text(encoding="utf-8"))[
        "counts"
    ] == {
        "decision_count": 4,
        "accepted": 2,
        "corrected": 1,
        "rejected": 1,
        "source_ref_count": 4,
        "package_candidate_apply_count": 0,
        "runtime_mutation_count": 0,
    }
    assert plan.counts.decision_count == 4
    assert plan.counts.accepted == 2
    assert plan.counts.package_candidate_apply_count == 0
    assert plan.counts.runtime_mutation_count == 0
    assert REPO_APPLY_PLAN_PATH.read_text(encoding="utf-8") == before_repo_apply_plan
    assert REPO_DECISION_LOG_PATH.read_text(encoding="utf-8") == before_repo_decision_log


def test_workspace_apply_plan_writer_rejects_missing_required_paths(tmp_path):
    workspace = _copy_chilai_workspace(tmp_path)

    (workspace / "reviews" / "review_decision_log.json").unlink()
    with pytest.raises(FileNotFoundError, match="missing required review_decision_log_ref"):
        write_review_decision_apply_plan_for_workspace(workspace)

    workspace = _copy_chilai_workspace(tmp_path, name="missing_package")
    (workspace / "outputs" / "pretrip_package.json").unlink()
    with pytest.raises(FileNotFoundError, match="missing required package_ref"):
        write_review_decision_apply_plan_for_workspace(workspace)

    workspace = tmp_path / "missing_project"
    workspace.mkdir()
    with pytest.raises(FileNotFoundError, match="missing required project.json"):
        write_review_decision_apply_plan_for_workspace(workspace)


def test_workspace_apply_plan_writer_has_no_runtime_or_network_coupling():
    source = inspect.getsource(pretrip_review_decision_apply_store)

    assert "import admin_api" not in source
    assert "from admin_api" not in source
    assert "pretrip_mission_compiler" not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "import httpx" not in source
    assert "from httpx" not in source


def _copy_chilai_workspace(tmp_path: Path, name: str = "workspace") -> Path:
    workspace = tmp_path / name
    shutil.copytree(FIXTURE_ROOT, workspace)
    return workspace


def _extra_decision() -> ReviewDecisionRecord:
    return ReviewDecisionRecord(
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
    )
