import inspect
import shutil
from pathlib import Path

import pytest

import pretrip_review_decision_store
from pretrip_review_decision_log import (
    ReviewDecisionRecord,
    load_review_decision_log,
)
from pretrip_review_decision_store import append_review_decision
from pretrip_review_decision_store import rebuild_review_decision_log


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_LOG_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "reviews"
    / "review_decision_log.json"
)


def test_append_review_decision_rebuilds_counts_summary_and_writes_copy(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    decision_log = load_review_decision_log(log_path)
    record = _new_record(decision_log.decisions[0])

    rebuilt = append_review_decision(log_path, record)
    persisted = load_review_decision_log(log_path)

    assert rebuilt.model_dump(mode="json") == persisted.model_dump(mode="json")
    assert [decision.decision_id for decision in persisted.decisions][-1] == record.decision_id
    assert persisted.counts.action_count == 4
    assert persisted.counts.accepted_count == 2
    assert persisted.counts.corrected_count == 1
    assert persisted.counts.rejected_count == 1
    assert persisted.counts.source_ref_count == 3
    assert persisted.apply_summary.accepted_candidate_refs == [
        "contour.g11.seg_001_003",
        "contour.g11.seg_004_006",
    ]
    assert persisted.apply_summary.runtime_mutation_count == 0
    assert persisted.apply_summary.package_mutation_count == 0
    assert persisted.apply_summary.phase1_runtime_mutation_allowed is False
    assert persisted.apply_summary.phase2_writeback_allowed is False
    assert persisted.apply_summary.compiles_mission_graph is False


def test_append_review_decision_leaves_repo_fixture_untouched(tmp_path):
    before = FIXTURE_LOG_PATH.read_text(encoding="utf-8")
    log_path = _copy_fixture_log(tmp_path)
    append_review_decision(log_path, _new_record(load_review_decision_log(log_path).decisions[0]))

    assert FIXTURE_LOG_PATH.read_text(encoding="utf-8") == before
    assert load_review_decision_log(FIXTURE_LOG_PATH).counts.action_count == 3


def test_append_review_decision_rejects_duplicate_decision_id(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    decision_log = load_review_decision_log(log_path)

    with pytest.raises(ValueError, match="duplicate review decision_id"):
        append_review_decision(log_path, decision_log.decisions[0])


def test_append_review_decision_rejects_duplicate_candidate_ref_with_new_decision_id(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    decision_log = load_review_decision_log(log_path)
    record = _duplicate_candidate_record(decision_log.decisions[0])

    with pytest.raises(ValueError, match="duplicate candidate_ref"):
        append_review_decision(log_path, record)


def test_rebuild_review_decision_log_rejects_duplicate_candidate_ref(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    decision_log = load_review_decision_log(log_path)
    record = _duplicate_candidate_record(decision_log.decisions[0])

    with pytest.raises(ValueError, match="duplicate candidate_ref"):
        rebuild_review_decision_log(decision_log, [*decision_log.decisions, record])


def test_append_review_decision_rejects_runtime_and_package_mutation(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    base_record = load_review_decision_log(log_path).decisions[0]

    runtime_record = _new_record(base_record)
    runtime_record = ReviewDecisionRecord.model_construct(
        **{
            **runtime_record.model_dump(mode="python"),
            "decision_id": "review_decision.chilai_nanhua_day1.accepted.runtime_mutation",
            "runtime_mutation_allowed": True,
        }
    )
    with pytest.raises(ValueError, match="runtime_mutation_allowed=true"):
        append_review_decision(log_path, runtime_record)

    package_record = _new_record(base_record)
    package_record = ReviewDecisionRecord.model_construct(
        **{
            **package_record.model_dump(mode="python"),
            "decision_id": "review_decision.chilai_nanhua_day1.accepted.package_mutation",
            "package_mutation_allowed": True,
        }
    )
    with pytest.raises(ValueError, match="package_mutation_allowed=true"):
        append_review_decision(log_path, package_record)


def test_append_review_decision_rejects_cross_project_record(tmp_path):
    log_path = _copy_fixture_log(tmp_path)
    record = _new_record(load_review_decision_log(log_path).decisions[0])
    record = record.model_copy(
        update={
            "decision_id": "review_decision.other_project.accepted.contour.g11.seg_004_006",
        }
    )

    with pytest.raises(ValueError, match="decision_id does not reference project_id"):
        append_review_decision(log_path, record)


def test_review_decision_store_has_no_runtime_or_network_coupling():
    source = inspect.getsource(pretrip_review_decision_store)

    assert "import admin_api" not in source
    assert "from admin_api" not in source
    assert "pretrip_mission_compiler" not in source
    assert "import requests" not in source
    assert "import httpx" not in source


def _copy_fixture_log(tmp_path: Path) -> Path:
    log_path = tmp_path / "workspace" / "reviews" / "review_decision_log.json"
    log_path.parent.mkdir(parents=True)
    shutil.copy2(FIXTURE_LOG_PATH, log_path)
    return log_path


def _new_record(base_record: ReviewDecisionRecord) -> ReviewDecisionRecord:
    source_ref = base_record.source_review_queue_item_refs[0].model_copy(
        update={
            "item_id": "review_queue.chilai_nanhua_day1.contour.contour.g11.seg_004_006",
            "candidate_ref": "contour.g11.seg_004_006",
        }
    )
    return base_record.model_copy(
        update={
            "decision_id": "review_decision.chilai_nanhua_day1.accepted.contour.g11.seg_004_006",
            "draft_action_id": "review_draft.chilai_nanhua_day1.contour.contour.g11.seg_004_006",
            "candidate_ref": "contour.g11.seg_004_006",
            "target_ids": ["seg.004", "seg.005", "seg.006"],
            "source_review_queue_item_refs": [source_ref],
            "decided_at": "2026-05-15T10:15:00+08:00",
            "summary": "Accepted an additional contour review note in the local workspace copy.",
        },
        deep=True,
    )


def _duplicate_candidate_record(base_record: ReviewDecisionRecord) -> ReviewDecisionRecord:
    return base_record.model_copy(
        update={
            "decision_id": f"{base_record.decision_id}.second",
            "decided_at": "2026-05-15T10:20:00+08:00",
            "summary": "Second local review decision for the same candidate ref.",
        },
        deep=True,
    )
