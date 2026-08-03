from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout_contextual_permission_workbench import (
    ArrivalDwellObservationRequest,
    BaselineAuthoringRequest,
    BaselineCandidateSaveRequest,
    BaselineReviewAcceptRequest,
    CanonicalCommandContext,
    CommunicationEventRequest,
    ContactLossReviewRequest,
    ContextualPermissionConflict,
    ContextualPermissionWorkbench,
    DepartureStartRequest,
    DayEndCloseCorrectionRequest,
    DayEndUnreachableRequest,
    EmergencyBivySelectionRequest,
    EmergencyReviewDecisionRequest,
    FieldConflictRequest,
    FieldConflictResolutionRequest,
    IndividualActionTransitionRequest,
    ManualDayEndConfirmationRequest,
    MovementGroupFormationRequest,
    MovementGroupMergeRequest,
    MovementGroupRevisionRequest,
    OfflineDayEndIntent,
    OfflineFieldConflictIntent,
    OfflineMovementGroupIntent,
    ShelterHoldReviewRequest,
    build_reference_workbench_seed,
)


NOW = datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc)
PROJECT_ID = "permission_state_fixture"


def _workbench(tmp_path: Path) -> ContextualPermissionWorkbench:
    project_root = tmp_path / "workspace" / PROJECT_ID
    seed_path = project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    seed_path.parent.mkdir(parents=True)
    rules_ref = "candidates/contextual_permission_rules.json"
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "compiled_mission_graph_reviewed_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
                "planned_eta_ref": "outputs/planned_eta.json",
                "contextual_permission_rules_ref": rules_ref,
            }
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps({"mission_id": f"mission.{PROJECT_ID}.v1"}),
        encoding="utf-8",
    )
    (project_root / "outputs" / "planned_eta.json").write_text(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "assumption": {
                    "day1_target_node_name": "Reviewed camp",
                    "turn_back_checkpoint_node_name": "Reviewed junction",
                },
                "estimates": [],
            }
        ),
        encoding="utf-8",
    )
    seed = build_reference_workbench_seed(PROJECT_ID)
    seed_path.write_text(seed.model_dump_json(indent=2), encoding="utf-8")
    rules_path = project_root / rules_ref
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_contextual_permission_rules",
                "schema_version": "contextual_permission_rules.v2",
                "project_id": PROJECT_ID,
                "reviewed_baseline_ref": seed.baseline.reviewed_receipt_ref,
                "reviewed_baseline_sha256": seed.baseline.baseline_sha256,
                "reviewed_by_human": True,
                "review_receipt_ref": "reviewed://contextual-permission/rules-v1",
                "review_receipt_sha256": "a" * 64,
                "plan_node_policies": [
                    {
                        "node_id": node.node_id,
                        "mission_day_id": node.mission_day_id,
                        "adjustment_policy": node.adjustment_policy,
                        "minimum_duration_minutes": node.minimum_duration_minutes,
                        "policy_ref": node.source_rule_ref,
                        "policy_sha256": node.source_rule_sha256,
                        "reviewed": True,
                    }
                    for node in seed.remaining_plan
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    return ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=tmp_path / "store",
        now_factory=lambda: NOW,
    )


def _context(
    workbench: ContextualPermissionWorkbench,
    group_id: str,
    idempotency_key: str,
) -> CanonicalCommandContext:
    aggregate = workbench.canonical_aggregate(group_id)
    return CanonicalCommandContext(
        session_id=aggregate.session_id,
        group_id=group_id,
        mission_day_instance_id=aggregate.mission_day_instance_id,
        membership_revision=aggregate.membership_revision,
        expected_baseline_sha256=aggregate.baseline_sha256,
        expected_aggregate_sha256=aggregate.aggregate_sha256,
        expected_sequence=aggregate.through_sequence,
        idempotency_key=idempotency_key,
    )


def test_permission_and_daily_review_share_one_canonical_group_aggregate(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    projection = workbench.projection(lens="replay")
    session = workbench.daily_emergency_review("D1.instance.001")
    packet = session.alternatives[0]

    assert projection.primary_aggregate == session.aggregate
    assert packet.aggregate == session.aggregate
    assert packet.movement_group_id == "group.ridge"
    assert packet.membership_revision == 1
    assert packet.sha256 == workbench.rebuild_packet_hash(packet)
    assert session.aggregate.contextual_permission_rules_ref == (
        "candidates/contextual_permission_rules.json"
    )
    assert len(session.aggregate.contextual_permission_rules_sha256) == 64
    assert any(
        item.source_kind == "reviewed_contextual_permission_rules"
        for item in projection.evidence
    )


def test_projection_exposes_canonical_od013_through_od018_contract(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    projection = workbench.projection(lens="replay")
    ridge, camp = projection.movement_groups[:2]

    assert projection.authority.model_dump() == {
        "runtime_authorization_performed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_action_performed": False,
        "outbound_transport_invoked": False,
        "external_send_performed": False,
        "hardware_control_performed": False,
    }
    assert ridge.day_end.state == "day_end_at_risk"
    assert camp.day_end.state == "day_closed_planned"
    assert ridge.shelter_hold.state == "not_required"
    assert camp.shelter_hold.state == "departure_review_candidate"
    assert camp.departure_checklist.scout_suggestion_code == "departure_review_ready"
    assert ridge.communication.state == "expected_blackout"
    assert camp.communication.state == "contact_available"
    assert ridge.communication.local_group_contact_state == "expected_blackout"
    assert ridge.communication.remote_observed_contact_state == "unknown"

    for group in (ridge, camp):
        assert group.formation_kind == "baseline_reviewed"
        assert group.participant_refs_hash == group.membership_sha256
        assert group.coordinator_ref.startswith("participant://")
        assert len(group.formation_receipt_sha256) == 64
        assert group.arrival_dwell.target_ref == group.day_end.effective_target_ref
        assert len(group.arrival_dwell.arrival_zone_sha256) == 64
        assert len(group.arrival_dwell.dwell_policy_sha256) == 64
        assert group.arrival_dwell.dwell_remaining_seconds == max(
            0,
            group.arrival_dwell.required_seconds
            - group.arrival_dwell.elapsed_seconds,
        )

    assert projection.authority.outbound_transport_invoked is False
    assert projection.authority.external_send_performed is False


def test_night_review_is_atomic_idempotent_and_rejects_stale_group_state(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    packet = workbench.daily_emergency_review("D1.instance.001").alternatives[0]
    context = _context(workbench, "group.ridge", "night-review-001")
    request = EmergencyReviewDecisionRequest(
        command_context=context,
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        mission_day_instance_id=packet.mission_day_instance_id,
        review_generation=packet.review_generation,
        reviewed_sequence=packet.reviewed_sequence,
        decision="select_hold_or_bivy",
        reviewer_alias="leader-01",
        explicit_confirmation=True,
    )

    first = workbench.record_night_decision(request)
    second = workbench.record_night_decision(request)

    assert first == second
    assert first.event_sequence == context.expected_sequence + 1
    assert first.human_review_recorded is True
    assert first.candidate_projection_updated is True
    assert first.runtime_authorization_performed is False
    refreshed = workbench.projection(lens="replay")
    assert refreshed.primary_aggregate.through_sequence == first.event_sequence
    assert refreshed.daily_review.reviewed_count == 1

    stale_context = context.model_copy(
        update={"idempotency_key": "night-review-stale-002"}
    )
    with pytest.raises(ContextualPermissionConflict) as stale:
        workbench.record_night_decision(
            request.model_copy(update={"command_context": stale_context})
        )
    assert stale.value.code == "already_decided"


def test_arrival_dwell_closes_only_at_600_seconds_and_activates_hold(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    target_sha = workbench.projection().movement_groups[0].day_end.planned_target_sha256

    pending = workbench.record_arrival_observation(
        ArrivalDwellObservationRequest(
            command_context=_context(workbench, "group.ridge", "arrival-599"),
            target_ref="target://reviewed-camp",
            target_sha256=target_sha,
            elapsed_seconds=599,
            target_match=True,
            route_progress_match=True,
            gnss_confidence="high",
            zone_exit=False,
            continued_route_travel=False,
            unexpected_separation=False,
        )
    )
    assert pending.event_kind == "arrival_dwell_observed"
    at_599 = workbench.projection().movement_groups[0]
    assert at_599.arrival_dwell.state == "counting"
    assert at_599.arrival_dwell.elapsed_seconds == 599
    assert at_599.day_end.completion == "open"

    completed = workbench.record_arrival_observation(
        ArrivalDwellObservationRequest(
            command_context=_context(workbench, "group.ridge", "arrival-600"),
            target_ref="target://reviewed-camp",
            target_sha256=target_sha,
            elapsed_seconds=600,
            target_match=True,
            route_progress_match=True,
            gnss_confidence="high",
            zone_exit=False,
            continued_route_travel=False,
            unexpected_separation=False,
        )
    )
    assert completed.event_kind == "day_end_closed"
    closed = workbench.projection().movement_groups[0]
    assert closed.day_end.completion == "planned_closed"
    assert closed.day_end.confirmation_mode == "automatic_gnss_dwell"
    assert closed.shelter_hold.state == "active"
    assert closed.pending_next_day == "D2"
    assert closed.mission_day_id == "D1"


def test_field_conflict_persists_until_separate_fresh_resolution(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.camp"
    weather_row = next(
        row
        for row in workbench.projection().movement_groups[1].departure_checklist.rows
        if row.row_id == "weather_threats"
    )
    conflict = workbench.report_field_conflict(
        FieldConflictRequest(
            command_context=_context(workbench, group_id, "conflict-weather-001"),
            checklist_id="departure.checklist.D2.camp-group.v1",
            row_id="weather_threats",
            category="actual_condition_worse",
            affected_fact_refs=[str(weather_row.evidence_ref)],
            affected_fact_hashes=[str(weather_row.evidence_sha256)],
            reporter_alias="leader-01",
            optional_note="Wind is stronger at the shelter.",
            explicit_confirmation=True,
        )
    )
    assert conflict.event_kind == "field_conflict_reported"
    blocked = workbench.projection().movement_groups[1].departure_checklist
    weather = next(row for row in blocked.rows if row.row_id == "weather_threats")
    assert weather.state == "blocked"
    assert blocked.open_conflict_count == 1
    assert blocked.scout_suggestion_suspended is True
    assert blocked.can_confirm_departure is False

    with pytest.raises(ContextualPermissionConflict) as no_fresh_evidence:
        workbench.resolve_field_conflict(
            FieldConflictResolutionRequest(
                command_context=_context(workbench, group_id, "resolve-weather-bad"),
                conflict_event_id=conflict.event_id,
                row_id="weather_threats",
                fresh_evidence_refs=[],
                fresh_evidence_hashes=[],
                leader_confirms_field_conflict_cleared=True,
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert no_fresh_evidence.value.code == "fresh_evidence_required"

    workbench.resolve_field_conflict(
        FieldConflictResolutionRequest(
            command_context=_context(workbench, group_id, "resolve-weather-001"),
            conflict_event_id=conflict.event_id,
            row_id="weather_threats",
            fresh_evidence_refs=["evidence://weather/departure-summary-v2"],
            fresh_evidence_hashes=["b" * 64],
            leader_confirms_field_conflict_cleared=True,
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    resolved = workbench.projection().movement_groups[1].departure_checklist
    assert resolved.open_conflict_count == 0
    assert resolved.scout_suggestion_suspended is False


def test_individual_activity_group_independence_and_privacy_boundary(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    ridge_before = workbench.canonical_aggregate("group.ridge")
    workbench.record_individual_activity(
        IndividualActionTransitionRequest(
            command_context=_context(workbench, "group.camp", "activity-camp-001"),
            participant_ref="participant://pseudo-03",
            device_ref="device://pseudo-field-03",
            activity_episode_id="episode-003",
            prior_state="resting",
            new_state="resumed_movement",
            transition_kind="resumed",
            confidence="high",
            freshness="fresh",
            evidence_hashes=["c" * 64],
            self_correction=False,
        )
    )

    projection = workbench.projection()
    ridge, camp = projection.movement_groups[:2]
    assert workbench.canonical_aggregate("group.ridge") == ridge_before
    assert camp.activity_summary.states["resumed_movement"] == 1
    assert ridge.activity_summary.states["resumed_movement"] == 0
    assert camp.activity_summary.leader_sleep_roll_call_required is False
    serialized = json.dumps(projection.model_dump(mode="json"))
    assert "raw_imu" not in serialized.casefold()
    assert "latitude" not in serialized.casefold()


def test_departure_requires_all_six_rows_and_starts_only_the_bound_group(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.camp"
    checklist = workbench.projection().movement_groups[1].departure_checklist
    with pytest.raises(ContextualPermissionConflict) as missing_checks:
        workbench.start_mission_day(
            DepartureStartRequest(
                command_context=_context(workbench, group_id, "start-D2-missing"),
                checklist_id=checklist.checklist_id,
                checklist_sha256=checklist.checklist_sha256,
                pending_mission_day_id="D2",
                pending_day_plan_sha256=checklist.pending_day_plan_sha256,
                leader_attestations={},
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert missing_checks.value.code == "departure_checklist_blocked"

    receipt = workbench.start_mission_day(
        DepartureStartRequest(
            command_context=_context(workbench, group_id, "start-D2-complete"),
            checklist_id=checklist.checklist_id,
            checklist_sha256=checklist.checklist_sha256,
            pending_mission_day_id="D2",
            pending_day_plan_sha256=checklist.pending_day_plan_sha256,
            leader_attestations={
                "team": True,
                "supplies_shelter": True,
            },
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    assert receipt.event_kind == "mission_day_started"
    ridge, camp = workbench.projection().movement_groups[:2]
    assert ridge.mission_day_id == "D1"
    assert camp.mission_day_id == "D2"
    assert camp.shelter_hold.state == "closed"
    assert camp.pending_next_day is None
    next_day_review = workbench.daily_emergency_review(camp.mission_day_instance_id)
    assert next_day_review.mission_day_id == "D2"
    assert next_day_review.state == "not_started"
    assert next_day_review.receipts == []
    assert next_day_review.alternatives == []


def test_contact_overdue_is_not_emergency_and_transport_attempt_is_not_checkin(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.ridge"
    workbench.record_communication_event(
        CommunicationEventRequest(
            command_context=_context(workbench, group_id, "contact-overdue-001"),
            event_kind="deadline_elapsed",
            communication_policy_id="comm-window.ridge.D1.v1",
            communication_policy_sha256=(
                workbench.projection().movement_groups[0].communication.policy_sha256
            ),
            route_scope_match=True,
            acknowledged_receipt_ref=None,
            compound_evidence_refs=[],
            retroactive=False,
        )
    )
    overdue = workbench.projection().movement_groups[0].communication
    assert overdue.state == "contact_overdue"
    assert overdue.contact_overdue is True
    assert overdue.emergency_declared is False

    with pytest.raises(ContextualPermissionConflict) as attempted:
        workbench.record_communication_event(
            CommunicationEventRequest(
                command_context=_context(workbench, group_id, "transport-attempt-001"),
                event_kind="verified_check_in",
                communication_policy_id="comm-window.ridge.D1.v1",
                communication_policy_sha256=overdue.policy_sha256,
                route_scope_match=True,
                acknowledged_receipt_ref="transport-attempt://message-001",
                compound_evidence_refs=[],
                retroactive=False,
            )
        )
    assert attempted.value.code == "acknowledged_receipt_required"


def test_movement_group_formation_is_explicit_and_never_inferred(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    receipt = workbench.form_movement_group(
        MovementGroupFormationRequest(
            command_context=_context(workbench, "group.ridge", "form-scout-001"),
            new_group_id="group.scout",
            display_name="Scout group",
            formation_kind="field_explicit",
            participant_refs_hash="d" * 64,
            coordinator_ref="participant://pseudo-01",
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.scout.001",
            target_ref="target://reviewed-camp",
            target_sha256="e" * 64,
            shared_dependency_refs=[],
            reporter_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    assert receipt.event_kind == "movement_group_formed"
    projection = workbench.projection()
    scout_group = next(group for group in projection.movement_groups if group.group_id == "group.scout")
    assert scout_group.membership_revision == 1
    assert scout_group.independent_day_state is True
    assert projection.expedition_rollup.group_count == 3


def test_baseline_save_and_accept_are_immutable_explicit_and_do_not_rebind_session(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    original = workbench.canonical_aggregate("group.ridge")
    draft = workbench.preview_baseline(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )
    saved = workbench.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="save-baseline-001",
            explicit_confirmation=True,
        )
    )
    assert saved.version_ref.endswith(".json")
    assert saved.writes_performed is True
    assert saved.runtime_safety_truth is False

    with pytest.raises(ContextualPermissionConflict) as no_confirmation:
        workbench.accept_reviewed_baseline(
            BaselineReviewAcceptRequest(
                candidate_ref=saved.version_ref,
                candidate_sha256=saved.version_sha256,
                reviewer_alias="leader-01",
                idempotency_key="accept-baseline-bad",
                explicit_confirmation=False,
            )
        )
    assert no_confirmation.value.code == "explicit_confirmation_required"

    accepted = workbench.accept_reviewed_baseline(
        BaselineReviewAcceptRequest(
            candidate_ref=saved.version_ref,
            candidate_sha256=saved.version_sha256,
            reviewer_alias="leader-01",
            idempotency_key="accept-baseline-001",
            explicit_confirmation=True,
        )
    )
    assert accepted.departure_approval_granted is False
    assert accepted.final_mission_graph_generated is False
    assert accepted.active_runtime_session_updated is False
    assert accepted.safety_api_called is False
    assert workbench.canonical_aggregate("group.ridge") == original
    assert accepted.stale_dependency_refs


def test_manual_arrived_closes_exact_target_without_person_sleep_attestation(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group = workbench.projection().movement_groups[0]
    receipt = workbench.confirm_day_end(
        ManualDayEndConfirmationRequest(
            command_context=_context(workbench, group.group_id, "manual-arrived-001"),
            target_ref=group.day_end.planned_target_ref,
            target_sha256=group.day_end.planned_target_sha256,
            target_label=group.day_end.planned_target_label,
            target_kind="planned_day_end",
            confirmation_kind="arrived",
            authorized_on_site_participant=True,
            participant_alias="participant-01",
            explicit_confirmation=True,
            uncertainty_acknowledgement=True,
        )
    )
    assert receipt.event_kind == "day_end_closed"
    closed = workbench.projection().movement_groups[0]
    assert closed.day_end.confirmation_mode == "manual_on_site"
    assert closed.day_end.completion == "planned_closed"
    assert closed.shelter_hold.state == "active"
    assert closed.pending_next_day == "D2"
    row_states = {row.row_id: row.state for row in closed.departure_checklist.rows}
    assert row_states == {
        "weather_threats": "pass",
        "route_navigation": "pass",
        "team": "leader_check_required",
        "equipment_power": "pass",
        "supplies_shelter": "leader_check_required",
        "communication_plan": "pass",
    }
    assert closed.activity_summary.leader_sleep_roll_call_required is False
    assert closed.activity_summary.team_safe_claimed is False


def test_unreachable_target_requires_bivy_selection_then_establishment(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.ridge"
    workbench.report_day_end_unreachable(
        DayEndUnreachableRequest(
            command_context=_context(workbench, group_id, "unreachable-001"),
            cause_kind="automatic_feasibility",
            cause_refs=["evidence://weather/extreme-cell"],
            cause_hashes=["f" * 64],
            reporter_alias=None,
            explicit_confirmation=False,
        )
    )
    review = workbench.projection().movement_groups[0]
    assert review.day_end.state == "emergency_bivy_review_required"
    assert review.day_end.completion == "open"
    bivy = workbench.daily_emergency_review(
        review.mission_day_instance_id
    ).alternatives[0].emergency_bivy_candidates[0]

    with pytest.raises(ContextualPermissionConflict) as unreviewed:
        workbench.select_emergency_bivy(
            EmergencyBivySelectionRequest(
                command_context=_context(workbench, group_id, "select-bivy-unreviewed"),
                target_ref="target://arbitrary-site",
                target_sha256="1" * 64,
                target_label="Arbitrary site",
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert unreviewed.value.code == "reviewed_emergency_bivy_required"

    selected = workbench.select_emergency_bivy(
        EmergencyBivySelectionRequest(
            command_context=_context(workbench, group_id, "select-bivy-001"),
            target_ref=bivy.target_ref,
            target_sha256=bivy.target_sha256,
            target_label=bivy.target_label,
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    assert selected.event_kind == "emergency_bivy_selected"
    assert workbench.projection().movement_groups[0].day_end.completion == "open"

    workbench.confirm_day_end(
        ManualDayEndConfirmationRequest(
            command_context=_context(workbench, group_id, "establish-bivy-001"),
            target_ref=bivy.target_ref,
            target_sha256=bivy.target_sha256,
            target_label=bivy.target_label,
            target_kind="emergency_bivy",
            confirmation_kind="camp_established",
            authorized_on_site_participant=True,
            participant_alias="participant-01",
            explicit_confirmation=True,
            uncertainty_acknowledgement=True,
        )
    )
    closed = workbench.projection().movement_groups[0]
    assert closed.day_end.completion == "contingency_closed"
    assert closed.day_end.baseline_day_end_reached is False
    assert closed.day_end.planned_target_ref == "target://reviewed-camp"
    assert closed.day_end.effective_target_ref == bivy.target_ref
    assert closed.pending_next_day == "D2"


def test_human_unreachable_reason_requires_safety_emergency_trigger_ref(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    with pytest.raises(ValueError, match="Safety / Emergency trigger"):
        DayEndUnreachableRequest(
            command_context=_context(workbench, "group.ridge", "bad-human-cause"),
            cause_kind="human_safety_trigger",
            cause_refs=["note://leader/free-text"],
            cause_hashes=["a" * 64],
            reporter_alias="leader-01",
            explicit_confirmation=True,
        )


def test_wrong_automatic_close_is_append_only_corrected_and_reopened(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group = workbench.projection().movement_groups[0]
    close = workbench.confirm_day_end(
        ManualDayEndConfirmationRequest(
            command_context=_context(workbench, group.group_id, "close-before-correction"),
            target_ref=group.day_end.planned_target_ref,
            target_sha256=group.day_end.planned_target_sha256,
            target_label=group.day_end.planned_target_label,
            target_kind="planned_day_end",
            confirmation_kind="arrived",
            authorized_on_site_participant=True,
            participant_alias="participant-01",
            explicit_confirmation=True,
            uncertainty_acknowledgement=True,
        )
    )
    correction = workbench.correct_day_end_close(
        DayEndCloseCorrectionRequest(
            command_context=_context(workbench, group.group_id, "correct-close-001"),
            close_event_id=close.event_id,
            reason="wrong_target",
            reporter_alias="participant-01",
            explicit_confirmation=True,
        )
    )
    assert correction.event_kind == "day_end_close_corrected"
    reopened = workbench.projection().movement_groups[0]
    assert reopened.day_end.completion == "open"
    assert reopened.day_end.correction_receipt_ref == f"event://{correction.event_id}"
    event_kinds = [
        event.event_kind for event in workbench._load_group_events(group.group_id)
    ]
    assert event_kinds == ["day_end_closed", "day_end_close_corrected"]


def test_shelter_hold_calendar_days_never_start_pending_mission_day(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.camp"
    workbench.review_shelter_hold(
        ShelterHoldReviewRequest(
            command_context=_context(workbench, group_id, "continue-hold-day4"),
            decision="continue_hold",
            calendar_days_elapsed=4,
            automatic_fact_refs=["evidence://weather/storm-remains"],
            human_trigger_refs=[],
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    held = workbench.projection().movement_groups[1]
    assert held.mission_day_id == "D1"
    assert held.pending_next_day == "D2"
    assert held.shelter_hold.calendar_days_elapsed == 4
    assert held.shelter_hold.mission_days_consumed == 0
    assert held.shelter_hold.state == "active"


def test_group_membership_revision_and_merge_preserve_independent_histories(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    old_camp_context = _context(workbench, "group.camp", "old-camp-command")
    workbench.revise_movement_group(
        MovementGroupRevisionRequest(
            command_context=old_camp_context.model_copy(
                update={"idempotency_key": "revise-camp-002"}
            ),
            expected_membership_sha256=(
                workbench.projection().movement_groups[1].membership_sha256
            ),
            participant_refs_hash="2" * 64,
            coordinator_ref="participant://pseudo-02",
            reporter_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    ridge, camp = workbench.projection().movement_groups[:2]
    assert ridge.membership_revision == 1
    assert camp.membership_revision == 2
    with pytest.raises(ContextualPermissionConflict) as stale_revision:
        workbench.record_individual_activity(
            IndividualActionTransitionRequest(
                command_context=old_camp_context,
                participant_ref="participant://pseudo-03",
                device_ref="device://pseudo-field-03",
                activity_episode_id="episode-old-membership",
                prior_state="resting",
                new_state="resumed_movement",
                transition_kind="resumed",
                confidence="high",
                freshness="fresh",
                evidence_hashes=["3" * 64],
                self_correction=False,
            )
        )
    assert stale_revision.value.code == "movement_group_revision_mismatch"

    with pytest.raises(ContextualPermissionConflict) as reconcile:
        workbench.merge_movement_groups(
            MovementGroupMergeRequest(
                command_context=_context(workbench, "group.ridge", "merge-bad"),
                source_group_ids=["group.ridge", "group.camp"],
                source_membership_revisions={"group.ridge": 1, "group.camp": 2},
                new_group_id="group.reunited",
                display_name="Reunited group",
                participant_refs_hash="4" * 64,
                mission_day_id="D1",
                mission_day_instance_id="D1.instance.reunited.001",
                target_ref="target://reviewed-camp",
                target_sha256="5" * 64,
                reconciliation_reviewed=False,
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert reconcile.value.code == "movement_group_reconciliation_required"

    workbench.merge_movement_groups(
        MovementGroupMergeRequest(
            command_context=_context(workbench, "group.ridge", "merge-good"),
            source_group_ids=["group.ridge", "group.camp"],
            source_membership_revisions={"group.ridge": 1, "group.camp": 2},
            new_group_id="group.reunited",
            display_name="Reunited group",
            participant_refs_hash="4" * 64,
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.reunited.001",
            target_ref="target://reviewed-camp",
            target_sha256="5" * 64,
            reconciliation_reviewed=True,
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    groups = workbench.projection().movement_groups
    assert {group.group_id for group in groups} >= {
        "group.ridge",
        "group.camp",
        "group.reunited",
    }


def test_reviewed_forward_event_adjusts_window_but_never_retroactively(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.ridge"
    communication = workbench.projection().movement_groups[0].communication
    workbench.record_communication_event(
        CommunicationEventRequest(
            command_context=_context(workbench, group_id, "window-forward-001"),
            event_kind="forward_window_adjusted",
            communication_policy_id=communication.policy_id,
            communication_policy_sha256=communication.policy_sha256,
            route_scope_match=True,
            acknowledged_receipt_ref=None,
            compound_evidence_refs=[],
            retroactive=False,
            new_effective_window="At reviewed camp arrival + 10m hold",
            adjustment_event_ref="event://reviewed/hold-001",
            adjustment_event_sha256="6" * 64,
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    adjusted = workbench.projection().movement_groups[0].communication
    assert adjusted.baseline_window != adjusted.effective_window
    assert adjusted.effective_window == "At reviewed camp arrival + 10m hold"

    workbench.record_communication_event(
        CommunicationEventRequest(
            command_context=_context(workbench, group_id, "window-overdue-after-adjust"),
            event_kind="deadline_elapsed",
            communication_policy_id=adjusted.policy_id,
            communication_policy_sha256=adjusted.policy_sha256,
            route_scope_match=True,
            acknowledged_receipt_ref=None,
            compound_evidence_refs=[],
            retroactive=False,
        )
    )
    with pytest.raises(ContextualPermissionConflict) as retroactive:
        workbench.record_communication_event(
            CommunicationEventRequest(
                command_context=_context(workbench, group_id, "window-retroactive"),
                event_kind="forward_window_adjusted",
                communication_policy_id=adjusted.policy_id,
                communication_policy_sha256=adjusted.policy_sha256,
                route_scope_match=True,
                acknowledged_receipt_ref=None,
                compound_evidence_refs=[],
                retroactive=True,
                new_effective_window="Later ad hoc deadline",
                adjustment_event_ref="event://client/ad-hoc",
                adjustment_event_sha256="7" * 64,
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert retroactive.value.code == "retroactive_window_adjustment_forbidden"


def test_offline_day_end_field_conflict_and_group_intents_revalidate_server_truth(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    ridge = workbench.projection().movement_groups[0]
    close_result = workbench.sync_offline_day_end_intent(
        OfflineDayEndIntent(
            intent_id="offline-day-end-001",
            idempotency_key="offline-day-end-001",
            command_context=_context(workbench, ridge.group_id, "offline-day-end-001"),
            target_ref=ridge.day_end.planned_target_ref,
            target_sha256=ridge.day_end.planned_target_sha256,
            target_label=ridge.day_end.planned_target_label,
            target_kind="planned_day_end",
            confirmation_kind="arrived",
            participant_alias="participant-01",
            uncertainty_acknowledgement=True,
            pending_sync=True,
            device_local_encrypted=True,
        )
    )
    assert close_result.status == "receipt_appended"
    assert close_result.runtime_authorization_performed is False
    assert close_result.outbound_transport_invoked is False
    assert workbench.projection().movement_groups[0].day_end.state == (
        "day_closed_planned"
    )

    camp = workbench.projection().movement_groups[1]
    weather = next(
        row
        for row in camp.departure_checklist.rows
        if row.row_id == "weather_threats"
    )
    conflict_result = workbench.sync_offline_field_conflict_intent(
        OfflineFieldConflictIntent(
            intent_id="offline-field-conflict-001",
            idempotency_key="offline-field-conflict-001",
            command_context=_context(
                workbench, camp.group_id, "offline-field-conflict-001"
            ),
            checklist_id=camp.departure_checklist.checklist_id,
            row_id="weather_threats",
            category="actual_condition_worse",
            affected_fact_refs=[str(weather.evidence_ref)],
            affected_fact_hashes=[str(weather.evidence_sha256)],
            reporter_alias="leader-01",
            optional_note=None,
            pending_sync=True,
            device_local_encrypted=True,
        )
    )
    assert conflict_result.status == "receipt_appended"
    refreshed_camp = workbench.projection().movement_groups[1]
    assert refreshed_camp.departure_checklist.open_conflict_count == 1

    group_result = workbench.sync_offline_movement_group_intent(
        OfflineMovementGroupIntent(
            intent_kind="formation",
            intent_id="offline-group-001",
            idempotency_key="offline-group-001",
            command_context=_context(
                workbench, "group.ridge", "offline-group-001"
            ),
            new_group_id="group.offline-scout",
            display_name="Offline scout group",
            formation_kind="field_explicit",
            participant_refs_hash="8" * 64,
            coordinator_ref="participant://pseudo-01",
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.offline-scout.001",
            target_ref="target://reviewed-camp",
            target_sha256="9" * 64,
            shared_dependency_refs=[],
            shared_dependency_hashes=[],
            reporter_alias="leader-01",
            expected_membership_sha256=None,
            pending_sync=True,
            device_local_encrypted=True,
        )
    )
    assert group_result.status == "receipt_appended"
    assert any(
        group.group_id == "group.offline-scout"
        for group in workbench.projection().movement_groups
    )


def test_contact_loss_review_is_explicit_and_never_sends_or_declares_emergency(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    group_id = "group.ridge"
    communication = workbench.projection().movement_groups[0].communication
    workbench.record_communication_event(
        CommunicationEventRequest(
            command_context=_context(workbench, group_id, "contact-overdue-review-001"),
            event_kind="deadline_elapsed",
            communication_policy_id=communication.policy_id,
            communication_policy_sha256=communication.policy_sha256,
            route_scope_match=True,
            acknowledged_receipt_ref=None,
            compound_evidence_refs=[],
            retroactive=False,
        )
    )
    overdue = workbench.projection().movement_groups[0].communication
    with pytest.raises(ContextualPermissionConflict) as no_basis:
        workbench.review_contact_loss(
            ContactLossReviewRequest(
                command_context=_context(workbench, group_id, "contact-review-bad"),
                communication_policy_id=overdue.policy_id,
                communication_policy_sha256=overdue.policy_sha256,
                decision="escalate_emergency_call_out",
                overdue_fact_refs=["automatic://communication/contact-overdue/ridge"],
                overdue_fact_hashes=["a" * 64],
                compound_evidence_refs=[],
                compound_evidence_hashes=[],
                safety_emergency_trigger_refs=[],
                safety_emergency_trigger_hashes=[],
                reviewer_alias="leader-01",
                explicit_confirmation=True,
            )
        )
    assert no_basis.value.code == "contact_escalation_basis_required"

    receipt = workbench.review_contact_loss(
        ContactLossReviewRequest(
            command_context=_context(workbench, group_id, "contact-review-good"),
            communication_policy_id=overdue.policy_id,
            communication_policy_sha256=overdue.policy_sha256,
            decision="escalate_emergency_call_out",
            overdue_fact_refs=["automatic://communication/contact-overdue/ridge"],
            overdue_fact_hashes=["a" * 64],
            compound_evidence_refs=["evidence://route/unexpected-deviation"],
            compound_evidence_hashes=["b" * 64],
            safety_emergency_trigger_refs=[],
            safety_emergency_trigger_hashes=[],
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    assert receipt.event_kind == "contact_loss_review_recorded"
    reviewed = workbench.projection().movement_groups[0].communication
    assert reviewed.state == "escalation_candidate"
    assert reviewed.emergency_declared is False
    assert receipt.authority.external_send_performed is False
