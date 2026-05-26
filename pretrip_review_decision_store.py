from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path

from pretrip_review_decision_log import (
    PreTripReviewDecisionLog,
    ReviewApplySummary,
    ReviewDecision,
    ReviewDecisionBoundary,
    ReviewDecisionCounts,
    ReviewDecisionRecord,
    load_review_decision_log,
)


def append_review_decision(
    log_path: Path | str,
    record: ReviewDecisionRecord,
) -> PreTripReviewDecisionLog:
    return append_review_decisions(log_path, [record])


def append_review_decisions(
    log_path: Path | str,
    records: list[ReviewDecisionRecord],
) -> PreTripReviewDecisionLog:
    path = Path(log_path)
    decision_log = load_review_decision_log(path)
    for record in records:
        _reject_duplicate_decision(decision_log, record)
        _validate_append_record(decision_log, record)

    rebuilt = rebuild_review_decision_log(
        decision_log,
        [*decision_log.decisions, *records],
    )
    _replace_json(path, rebuilt.to_json())
    return rebuilt


def rebuild_review_decision_log(
    decision_log: PreTripReviewDecisionLog,
    decisions: list[ReviewDecisionRecord] | None = None,
) -> PreTripReviewDecisionLog:
    rebuilt_decisions = list(decision_log.decisions if decisions is None else decisions)
    _validate_append_only_boundaries(decision_log.boundary)
    for record in rebuilt_decisions:
        _validate_append_record(decision_log, record)
    _reject_duplicate_decision_ids(rebuilt_decisions)
    _reject_duplicate_candidate_refs(rebuilt_decisions)

    counts_by_decision = Counter(record.decision.value for record in rebuilt_decisions)
    source_refs = sorted(
        {
            source_ref.source_ref
            for record in rebuilt_decisions
            for source_ref in record.source_review_queue_item_refs
        }
    )

    return PreTripReviewDecisionLog(
        log_id=decision_log.log_id,
        artifact_kind=decision_log.artifact_kind,
        project_id=decision_log.project_id,
        source_draft_log_ref=decision_log.source_draft_log_ref,
        source_review_queue_manifest_ref=decision_log.source_review_queue_manifest_ref,
        decisions=rebuilt_decisions,
        counts=ReviewDecisionCounts(
            action_count=len(rebuilt_decisions),
            accepted_count=counts_by_decision[ReviewDecision.ACCEPTED.value],
            corrected_count=counts_by_decision[ReviewDecision.CORRECTED.value],
            rejected_count=counts_by_decision[ReviewDecision.REJECTED.value],
            source_ref_count=len(source_refs),
        ),
        apply_summary=ReviewApplySummary(
            accepted_candidate_refs=[
                record.candidate_ref
                for record in rebuilt_decisions
                if record.decision == ReviewDecision.ACCEPTED
            ],
            corrected_candidate_refs=[
                record.candidate_ref
                for record in rebuilt_decisions
                if record.decision == ReviewDecision.CORRECTED
            ],
            rejected_candidate_refs=[
                record.candidate_ref
                for record in rebuilt_decisions
                if record.decision == ReviewDecision.REJECTED
            ],
            source_refs=source_refs,
            notes=list(decision_log.apply_summary.notes),
        ),
        boundary=decision_log.boundary,
        notes=list(decision_log.notes),
    )


def _reject_duplicate_decision(
    decision_log: PreTripReviewDecisionLog,
    record: ReviewDecisionRecord,
) -> None:
    if record.decision_id in {decision.decision_id for decision in decision_log.decisions}:
        raise ValueError(f"duplicate review decision_id: {record.decision_id}")


def _reject_duplicate_decision_ids(decisions: list[ReviewDecisionRecord]) -> None:
    seen_ids: set[str] = set()
    for decision in decisions:
        if decision.decision_id in seen_ids:
            raise ValueError(f"duplicate review decision_id: {decision.decision_id}")
        seen_ids.add(decision.decision_id)


def _reject_duplicate_candidate_refs(decisions: list[ReviewDecisionRecord]) -> None:
    seen_candidate_refs: set[str] = set()
    for decision in decisions:
        if decision.candidate_ref in seen_candidate_refs:
            raise ValueError(f"duplicate candidate_ref: {decision.candidate_ref}")
        seen_candidate_refs.add(decision.candidate_ref)


def _validate_append_record(
    decision_log: PreTripReviewDecisionLog,
    record: ReviewDecisionRecord,
) -> None:
    _validate_append_only_boundaries(record)
    _validate_project_refs(decision_log, record)


def _validate_append_only_boundaries(
    value: ReviewDecisionRecord | ReviewDecisionBoundary,
) -> None:
    if value.append_only is not True:
        raise ValueError("review decision store only accepts append-only records")
    for field in (
        "source_mutation_allowed",
        "package_mutation_allowed",
        "runtime_mutation_allowed",
        "phase1_runtime_mutation_allowed",
        "phase2_writeback_allowed",
        "compiles_mission_graph",
    ):
        if getattr(value, field) is not False:
            raise ValueError(f"review decision store rejects {field}=true")


def _validate_project_refs(
    decision_log: PreTripReviewDecisionLog,
    record: ReviewDecisionRecord,
) -> None:
    project_id = decision_log.project_id
    _require_project_token("decision_id", record.decision_id, project_id)
    _require_project_token("draft_action_id", record.draft_action_id, project_id)
    for source_ref in record.source_review_queue_item_refs:
        _require_project_token(
            "review_queue_manifest_id",
            source_ref.review_queue_manifest_id,
            project_id,
        )
        _require_relative_ref("source_ref", source_ref.source_ref)
        if source_ref.candidate_ref != record.candidate_ref:
            raise ValueError("source review queue candidate_ref must match decision candidate_ref")


def _require_project_token(field: str, value: str, project_id: str) -> None:
    if project_id not in value:
        raise ValueError(f"{field} does not reference project_id {project_id}")


def _require_relative_ref(field: str, value: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a project-relative path")


def _replace_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()
