import json

import pytest
from pydantic import ValidationError

from pretrip_review_draft import (
    PreTripReviewDraftAction,
    PreTripReviewDraftLog,
    ReviewCorrectionPayload,
    ReviewQueueItemRef,
    build_pretrip_review_draft_log,
)


def test_review_draft_action_schema_is_strict_and_draft_only():
    action = _action("accepted")
    payload = action.model_dump(mode="json")

    assert payload["status"] == "accepted"
    assert payload["target_ids"] == ["cp.start"]
    assert payload["source_review_queue_item_refs"][0] == {
        "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
        "item_id": "review_queue.chilai_nanhua_day1.plan_validation.cp.start",
        "source_ref": "outputs/review_queue_manifest.json",
        "candidate_ref": "cp.start",
    }
    assert payload["reviewer_alias"] == "leader"
    assert payload["created_at"] == "2026-05-15T09:00:00+08:00"
    assert payload["draft_only"] is True
    assert payload["mutates_source_package"] is False
    assert payload["compiles_mission_graph"] is False
    assert payload["phase1_runtime_mutation_allowed"] is False

    with pytest.raises(ValidationError):
        PreTripReviewDraftAction.model_validate(
            {
                **payload,
                "unexpected": "not allowed",
            }
        )

    with pytest.raises(ValidationError):
        PreTripReviewDraftAction.model_validate(
            {
                **payload,
                "target_ids": "cp.start",
            }
        )

    with pytest.raises(ValidationError):
        PreTripReviewDraftAction.model_validate(
            {
                **payload,
                "created_at": "not a datetime",
            }
        )


@pytest.mark.parametrize(
    "status",
    ["accepted", "rejected", "corrected", "needs_info"],
)
def test_review_draft_allows_expected_statuses(status):
    action = _action(status)

    assert action.status == status


def test_review_draft_rejects_unknown_status_and_invalid_correction_use():
    with pytest.raises(ValidationError):
        _action("approved")

    with pytest.raises(ValidationError, match="corrected draft action requires correction_payload"):
        PreTripReviewDraftAction(
            draft_action_id="draft.corrected.missing_payload",
            status="corrected",
            target_ids=("cp.start",),
            source_review_queue_item_refs=(_review_queue_ref(),),
            reviewer_alias="leader",
            created_at="2026-05-15T09:00:00+08:00",
        )

    with pytest.raises(ValidationError, match="correction_payload is only allowed"):
        _action(
            "accepted",
            correction_payload=ReviewCorrectionPayload(
                summary="Move candidate label only.",
            ),
        )


def test_review_draft_rejects_raw_payload_fragments():
    with pytest.raises(ValidationError, match="forbidden raw payload fragment"):
        ReviewCorrectionPayload(
            summary="Paste raw source sample.",
            field_updates={"raw_payload": "full source candidate json"},
        )

    with pytest.raises(ValidationError, match="forbidden raw payload fragment"):
        _action(
            "needs_info",
            source_review_queue_item_refs=(
                ReviewQueueItemRef(
                    review_queue_manifest_id="review_queue.chilai_nanhua_day1.v0",
                    item_id="review_queue.chilai_nanhua_day1.runtime.raw_samples",
                    source_ref="outputs/review_queue_manifest.json",
                    candidate_ref="runtime.raw_samples",
                ),
            ),
        )

    serialized = json.dumps(_action("corrected").model_dump(mode="json"), sort_keys=True)
    for fragment in [
        "raw_payload",
        "payload_fragment",
        "source_payload",
        "raw_samples",
        '"coordinates"',
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "PdrSample",
        ".gpx",
    ]:
        assert fragment not in serialized


def test_build_review_draft_log_is_append_only_and_preserves_order():
    first = _action("accepted", draft_action_id="draft.001", target_ids=("cp.start",))
    second = _action("needs_info", draft_action_id="draft.002", target_ids=("seg.001",))
    third = _action("rejected", draft_action_id="draft.003", target_ids=("poi.water.01",))

    empty_log = PreTripReviewDraftLog(log_id="review_drafts.chilai_nanhua_day1.v0")
    appended_log = empty_log.append(first)
    built_log = build_pretrip_review_draft_log(
        [first, second, third],
        log_id="review_drafts.chilai_nanhua_day1.v0",
    )

    assert empty_log.actions == ()
    assert [action.draft_action_id for action in appended_log.actions] == ["draft.001"]
    assert [action.draft_action_id for action in built_log.actions] == [
        "draft.001",
        "draft.002",
        "draft.003",
    ]
    assert built_log.model_dump(mode="json")["draft_only"] is True
    assert built_log.model_dump(mode="json")["mutates_source_package"] is False
    assert built_log.model_dump(mode="json")["compiles_mission_graph"] is False
    assert built_log.model_dump(mode="json")["phase1_runtime_mutation_allowed"] is False


def _action(
    status: str,
    *,
    draft_action_id: str = "draft.cp.start.leader.20260515T090000",
    target_ids: tuple[str, ...] = ("cp.start",),
    source_review_queue_item_refs: tuple[ReviewQueueItemRef, ...] | None = None,
    correction_payload: ReviewCorrectionPayload | None = None,
) -> PreTripReviewDraftAction:
    if status == "corrected" and correction_payload is None:
        correction_payload = ReviewCorrectionPayload(
            summary="Correct candidate label from reviewed map note.",
            field_updates={"label": "Trailhead"},
            replacement_ref_ids=("field_note.cp.start.label",),
        )
    return PreTripReviewDraftAction(
        draft_action_id=draft_action_id,
        status=status,
        target_ids=target_ids,
        source_review_queue_item_refs=source_review_queue_item_refs or (_review_queue_ref(),),
        correction_payload=correction_payload,
        reviewer_alias="leader",
        created_at="2026-05-15T09:00:00+08:00",
    )


def _review_queue_ref() -> ReviewQueueItemRef:
    return ReviewQueueItemRef(
        review_queue_manifest_id="review_queue.chilai_nanhua_day1.v0",
        item_id="review_queue.chilai_nanhua_day1.plan_validation.cp.start",
        source_ref="outputs/review_queue_manifest.json",
        candidate_ref="cp.start",
    )
