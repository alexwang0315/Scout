from __future__ import annotations

import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout_contextual_permission_workbench import (
    BaselineAuthoringRequest,
    BaselineCandidateSaveRequest,
    BaselinePatchPreviewRequest,
    BaselinePatchSaveRequest,
    BaselineReviewAcceptRequest,
    CandidateSimulationRequest,
    CanonicalCommandContext,
    ContextualPermissionConflict,
    ContextualPermissionRulesArtifact,
    ContextualPermissionWorkbench,
    DailyReviewInvalidationRequest,
    EmergencyReviewDecisionRequest,
    OfflineEmergencyReviewIntent,
    build_reference_workbench_seed,
)


NOW = datetime(2026, 8, 2, 6, 0, tzinfo=timezone.utc)
PROJECT_ID = "permission_fixture"


def _append_only_race_worker(
    path_text: str,
    payload: dict[str, str],
    start: object,
    results: object,
) -> None:
    start.wait()
    try:
        ContextualPermissionWorkbench._write_new_json(  # noqa: SLF001
            None, Path(path_text), payload
        )
    except ContextualPermissionConflict as exc:
        results.put(exc.code)
    else:
        results.put("written")


def _canonical_event_race_worker(
    project_root_text: str,
    store_root_text: str,
    context_payload: dict[str, object],
    writer_id: int,
    start: object,
    results: object,
) -> None:
    workbench = ContextualPermissionWorkbench(
        project_root=Path(project_root_text),
        store_root=Path(store_root_text),
        now_factory=lambda: NOW,
    )
    context = CanonicalCommandContext.model_validate(
        {
            **context_payload,
            "idempotency_key": f"canonical-race-{writer_id:02d}",
        }
    )
    start.wait()
    try:
        workbench._append_canonical_event(  # noqa: SLF001
            context=context,
            event_kind="canonical_race_probe",
            payload={"writer_id": writer_id},
        )
    except ContextualPermissionConflict as exc:
        results.put(exc.code)
    else:
        results.put("written")


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / PROJECT_ID
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
                "plan_id": f"eta.{PROJECT_ID}.v1",
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
    return project_root, tmp_path / "store"


def test_contextual_permission_rules_are_required_and_baseline_bound(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    rules_path = project_root / "candidates" / "contextual_permission_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rules["reviewed_baseline_sha256"] = "0" * 64
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    with pytest.raises(ContextualPermissionConflict) as mismatch:
        ContextualPermissionWorkbench(
            project_root=project_root,
            store_root=store_root,
            now_factory=lambda: NOW,
        )
    assert mismatch.value.code == "contextual_permission_rules_baseline_mismatch"


def test_workbench_rejects_unsafe_project_identity_before_store_path_use(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    unsafe_project_id = "../outside"
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["project_id"] = unsafe_project_id
    project_path.write_text(json.dumps(project), encoding="utf-8")
    seed_path = (
        project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["project_id"] = unsafe_project_id
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    rules_path = project_root / "candidates" / "contextual_permission_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rules["project_id"] = unsafe_project_id
    rules_path.write_text(json.dumps(rules), encoding="utf-8")

    with pytest.raises(ContextualPermissionConflict) as invalid:
        ContextualPermissionWorkbench(
            project_root=project_root,
            store_root=store_root,
            now_factory=lambda: NOW,
        )

    assert invalid.value.code == "invalid_project_id"
    assert not (tmp_path / "outside").exists()


def _workbench(tmp_path: Path) -> ContextualPermissionWorkbench:
    project_root, store_root = _workspace(tmp_path)
    return ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    )


def test_reference_replay_reduces_only_discretionary_future_nodes_once(
    tmp_path: Path,
) -> None:
    projection = _workbench(tmp_path).projection()

    assert projection.current_decision.action_id == "rest"
    assert projection.current_decision.authorized_duration_minutes == 6
    assert projection.current_decision.observed_duration_minutes == 16
    assert projection.risk_budget.time_debt_minutes == 10
    assert projection.risk_budget.unabsorbed_debt_minutes == 0

    by_id = {node.node_id: node for node in projection.remaining_plan}
    assert by_id["node.photo_stop"].baseline_duration_minutes == 8
    assert by_id["node.photo_stop"].effective_duration_minutes == 2
    assert by_id["node.wait_view"].baseline_duration_minutes == 7
    assert by_id["node.wait_view"].effective_duration_minutes == 3
    assert by_id["node.route_floor"].effective_duration_minutes == 45
    assert by_id["node.daylight_reserve"].effective_duration_minutes == 30
    assert by_id["node.route_floor"].adjustment_policy == "protected_floor"
    assert by_id["node.daylight_reserve"].protected is True
    assert sum(item.debt_minutes for item in projection.action_events) == 10


def test_unreviewed_bootstrap_is_degraded_and_never_projects_go(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    seed_path = (
        project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    )
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["lens"] = "baseline"
    seed["action_events"] = []
    seed["baseline"]["accepted_by_human"] = False
    seed["baseline"]["immutable"] = False
    seed["remaining_plan"][0]["data_quality"] = [
        "D1 planned day-end target still requires leader review."
    ]
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    projection = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    ).projection()

    assert projection.status == "degraded"
    assert projection.current_decision.decision == "ESCALATE"
    assert projection.scout_pace_advice.recommendation == "insufficient_evidence"
    assert projection.missing_inputs == [
        "D1 planned day-end target still requires leader review."
    ]
    assert "review pending" in projection.lens_notice.casefold()


def test_unreviewed_rule_artifact_only_accepts_fail_closed_review_only() -> None:
    payload = {
        "artifact_kind": "pretrip_contextual_permission_rules",
        "schema_version": "contextual_permission_rules.v2",
        "project_id": PROJECT_ID,
        "reviewed_baseline_ref": "candidate://baseline/bootstrap",
        "reviewed_baseline_sha256": "a" * 64,
        "reviewed_by_human": False,
        "review_receipt_ref": "receipt://permission/bootstrap",
        "review_receipt_sha256": "b" * 64,
        "plan_node_policies": [
            {
                "node_id": "node.bootstrap",
                "mission_day_id": "D1",
                "adjustment_policy": "review_only",
                "minimum_duration_minutes": 0,
                "policy_ref": "candidate://permission/node.bootstrap",
                "policy_sha256": "c" * 64,
                "reviewed": False,
            }
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }

    artifact = ContextualPermissionRulesArtifact.model_validate(payload)
    assert artifact.reviewed_by_human is False

    payload["plan_node_policies"][0]["adjustment_policy"] = "auto_reduce"
    with pytest.raises(ValueError, match="fail-closed review_only"):
        ContextualPermissionRulesArtifact.model_validate(payload)


def test_simulation_is_ephemeral_and_fails_closed_when_debt_cannot_be_absorbed(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    before_files = sorted(workbench.store_root.rglob("*"))

    simulation = workbench.simulate(
        CandidateSimulationRequest(
            action_id="rest",
            authorized_duration_minutes=6,
            observed_duration_minutes=36,
            causes=[
                {
                    "cause_id": "fact.weather.heavy_rain",
                    "source_kind": "weather_fact",
                    "source_ref": "evidence://weather/heavy-rain",
                    "source_sha256": "a" * 64,
                    "verified": True,
                }
            ],
        )
    )

    assert simulation.candidate_only is True
    assert simulation.writes_performed is False
    assert simulation.replaces_current_decision is False
    assert simulation.projection.risk_budget.time_debt_minutes == 30
    assert simulation.projection.risk_budget.unabsorbed_debt_minutes == 20
    assert simulation.projection.current_decision.decision == "CHANGE_PLAN"
    assert simulation.projection.current_decision.next_step == (
        "Open the bounded alternative in Safety / Emergency for human review."
    )
    assert sorted(workbench.store_root.rglob("*")) == before_files


def test_human_cause_is_rejected_without_verified_safety_emergency_receipt(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)

    with pytest.raises(ContextualPermissionConflict) as exc_info:
        workbench.simulate(
            CandidateSimulationRequest(
                action_id="rest",
                authorized_duration_minutes=6,
                observed_duration_minutes=16,
                causes=[
                    {
                        "cause_id": "operator.delay",
                        "source_kind": "human_operation",
                        "source_ref": "browser://unchecked-toggle",
                        "source_sha256": "b" * 64,
                        "verified": True,
                    }
                ],
            )
        )

    assert exc_info.value.code == "verified_safety_trigger_required"


@pytest.mark.parametrize(
    ("verified", "source_ref", "expected_code"),
    [
        (False, "evidence://weather/heavy-rain", "verified_automatic_fact_required"),
        (True, "gps://24.123,121.456", "normalized_automatic_fact_required"),
    ],
)
def test_automatic_causes_require_verified_privacy_bounded_fact_refs(
    tmp_path: Path,
    verified: bool,
    source_ref: str,
    expected_code: str,
) -> None:
    workbench = _workbench(tmp_path)

    with pytest.raises(ContextualPermissionConflict) as exc_info:
        workbench.simulate(
            CandidateSimulationRequest(
                action_id="rest",
                authorized_duration_minutes=6,
                observed_duration_minutes=16,
                causes=[
                    {
                        "cause_id": "fact.weather.heavy_rain",
                        "source_kind": "weather_fact",
                        "source_ref": source_ref,
                        "source_sha256": "a" * 64,
                        "verified": verified,
                    }
                ],
            )
        )

    assert exc_info.value.code == expected_code


def test_verified_human_trigger_and_automatic_facts_keep_distinct_lineage(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    canonical_trigger = next(
        cause
        for cause in workbench.projection().action_events[0].causes
        if cause.source_kind == "safety_emergency_trigger"
    )
    result = workbench.simulate(
        CandidateSimulationRequest(
            action_id="rest",
            authorized_duration_minutes=6,
            observed_duration_minutes=16,
            causes=[
                {
                    "cause_id": "trigger.leader.extended_rest",
                    "source_kind": "safety_emergency_trigger",
                    "source_ref": canonical_trigger.source_ref,
                    "source_sha256": canonical_trigger.source_sha256,
                    "verified": True,
                },
                {
                    "cause_id": "fact.movement.stationary",
                    "source_kind": "movement_fact",
                    "source_ref": "evidence://movement/stationary-001",
                    "source_sha256": "d" * 64,
                    "verified": True,
                },
            ],
        )
    )

    causes = result.projection.action_events[0].causes
    assert [cause.source_kind for cause in causes] == [
        "safety_emergency_trigger",
        "movement_fact",
    ]
    assert result.projection.action_events[0].debt_minutes == 10
    assert result.projection.scout_pace_advice.authority == "candidate_advice"
    assert result.projection.scout_pace_advice.safety_subordinate is True


def test_projection_is_privacy_bounded_candidate_state(tmp_path: Path) -> None:
    projection = _workbench(tmp_path).projection()
    payload = projection.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)

    assert projection.candidate_only is True
    assert projection.runtime_safety_truth is False
    assert projection.authority.runtime_authorization_performed is False
    assert projection.authority.phase1_l0_l4_state_mutated is False
    assert projection.authority.safety_api_called is False
    assert projection.authority.outbound_action_performed is False
    assert projection.expedition_rollup.state == "partially_closed"
    assert projection.movement_groups[0].group_id != projection.movement_groups[1].group_id
    assert "latitude" not in serialized.casefold()
    assert "longitude" not in serialized.casefold()
    assert "raw_imu" not in serialized.casefold()
    assert "heart_rate" not in serialized.casefold()


def test_night_packet_expiry_uses_earliest_required_evidence(tmp_path: Path) -> None:
    session = _workbench(tmp_path).daily_emergency_review("D1.instance.001")
    packet = session.alternatives[0]

    assert packet.freshness_state == "fresh"
    assert packet.expires_at == min(item.valid_until for item in packet.freshness_inputs)
    assert packet.expiry_driver is not None
    assert packet.expiry_driver.gate_id == "gate.weather_window"
    assert packet.eligibility == "eligible_for_human_review"
    assert packet.approval_granted is False


def test_night_decision_revalidates_packet_and_is_idempotent(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path)
    packet = workbench.daily_emergency_review("D1.instance.001").alternatives[0]
    request = EmergencyReviewDecisionRequest(
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        mission_day_instance_id="D1.instance.001",
        review_generation=1,
        reviewed_sequence=12,
        decision="select_hold_or_bivy",
        reviewer_alias="leader-01",
        idempotency_key="review-hold-001",
        explicit_confirmation=True,
    )

    first = workbench.record_night_decision(request)
    second = workbench.record_night_decision(request)

    assert first.receipt_sha256 == second.receipt_sha256
    assert first.human_review_recorded is True
    assert first.runtime_authorization_performed is False
    assert first.phase1_l0_l4_state_mutated is False
    assert first.safety_api_called is False
    assert first.outbound_action_performed is False
    refreshed = workbench.projection()
    assert refreshed.daily_review.reviewed_count == 1
    assert refreshed.daily_review.state == "reviewed"
    assert refreshed.daily_review.selected_alternative_state == "hold_or_bivy_selected"


def test_night_decision_rejects_stale_hash_and_same_key_different_request(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    packet = workbench.daily_emergency_review("D1.instance.001").alternatives[0]
    baseline = {
        "packet_id": packet.packet_id,
        "mission_day_instance_id": "D1.instance.001",
        "review_generation": 1,
        "reviewed_sequence": 12,
        "decision": "reject_night_travel",
        "reviewer_alias": "leader-01",
        "idempotency_key": "review-conflict-001",
        "explicit_confirmation": True,
    }

    with pytest.raises(ContextualPermissionConflict) as stale:
        workbench.record_night_decision(
            EmergencyReviewDecisionRequest(packet_sha256="0" * 64, **baseline)
        )
    assert stale.value.code == "packet_replaced"

    workbench.record_night_decision(
        EmergencyReviewDecisionRequest(packet_sha256=packet.sha256, **baseline)
    )
    with pytest.raises(ContextualPermissionConflict) as reused:
        workbench.record_night_decision(
            EmergencyReviewDecisionRequest(
                packet_sha256=packet.sha256,
                **{**baseline, "decision": "select_hold_or_bivy"},
            )
        )
    assert reused.value.code == "idempotency_conflict"


def test_offline_intent_never_accepts_approval_and_syncs_conservative_choice(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    packet = workbench.daily_emergency_review("D1.instance.001").alternatives[0]

    rejected = workbench.sync_offline_intent(
        OfflineEmergencyReviewIntent(
            intent_id="offline-approve-001",
            idempotency_key="offline-approve-001",
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            mission_day_instance_id="D1.instance.001",
            review_generation=1,
            reviewed_sequence=12,
            decision="approve_for_runtime_consideration",
            reviewer_alias="leader-01",
            device_instance_id="field-device-01",
            pending_sync=True,
        )
    )
    assert rejected.status == "rejected_sync_audit"
    assert rejected.reasons == ["offline_approval_forbidden"]
    packet = workbench.daily_emergency_review("D1.instance.001").alternatives[0]

    synced = workbench.sync_offline_intent(
        OfflineEmergencyReviewIntent(
            intent_id="offline-hold-001",
            idempotency_key="offline-hold-001",
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            mission_day_instance_id="D1.instance.001",
            review_generation=1,
            reviewed_sequence=packet.reviewed_sequence,
            decision="select_hold_or_bivy",
            reviewer_alias="leader-01",
            device_instance_id="field-device-01",
            pending_sync=True,
            supersedes_intent_id="offline-approve-001",
        )
    )
    assert synced.status == "receipt_appended"
    assert synced.runtime_authorization_performed is False
    assert synced.outbound_action_performed is False


def test_baseline_human_and_reference_modes_converge_without_implicit_write(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    human = workbench.preview_baseline(
        BaselineAuthoringRequest(
            mode="human_text",
            human_text=(
                "D0: Taipei - trailhead C0\n"
                "D1: C0 - reviewed junction - Reviewed camp C1"
            ),
        )
    )
    reference = workbench.preview_baseline(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )

    assert human.schema_version == reference.schema_version
    assert human.artifact_kind == reference.artifact_kind
    assert human.writes_performed is False
    assert reference.writes_performed is False
    assert human.candidate_only is True
    assert reference.candidate_only is True
    assert human.source_mode == "human_text"
    assert reference.source_mode == "reference_gpx"
    assert not list(workbench.store_root.rglob("baseline_candidates/*.json"))


def test_destination_and_group_states_are_not_clock_driven(tmp_path: Path) -> None:
    projection = _workbench(tmp_path).projection()
    ridge_group, camp_group = projection.movement_groups

    assert ridge_group.day_end.state == "day_end_at_risk"
    assert ridge_group.day_end.completion == "open"
    assert camp_group.day_end.state == "day_closed_planned"
    assert camp_group.day_end.completion == "planned_closed"
    assert camp_group.pending_next_day == "D2"
    assert camp_group.shelter_hold.calendar_days_elapsed == 3
    assert camp_group.shelter_hold.mission_days_consumed == 0
    assert camp_group.departure_checklist.can_confirm_departure is False
    assert len(camp_group.departure_checklist.rows) == 6
    assert projection.expedition_rollup.state == "partially_closed"
    assert projection.day_boundary_policy == "destination_receipt_only"


def test_activity_and_communication_projections_do_not_claim_team_safety(
    tmp_path: Path,
) -> None:
    projection = _workbench(tmp_path).projection()
    ridge_group = projection.movement_groups[0]

    assert ridge_group.activity_summary.leader_sleep_roll_call_required is False
    assert ridge_group.activity_summary.team_safe_claimed is False
    assert ridge_group.activity_summary.states["unknown"] == 1
    assert ridge_group.arrival_dwell.required_seconds == 600
    assert ridge_group.communication.continuous_heartbeat_required is False
    assert ridge_group.communication.state == "expected_blackout"
    assert ridge_group.communication.emergency_declared is False
    assert ridge_group.communication.transport_attempt_counts_as_check_in is False


def test_missing_policy_fails_closed_and_protected_floor_uses_only_declared_excess(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    seed_path = project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["remaining_plan"][0].pop("adjustment_policy", None)
    seed["remaining_plan"][0].pop("declared_adjustment_policy", None)
    seed["remaining_plan"][1]["adjustment_policy"] = "review_only"
    seed["remaining_plan"][1]["declared_adjustment_policy"] = "review_only"
    protected = seed["remaining_plan"][2]
    protected.update(
        {
            "baseline_duration_minutes": 50,
            "minimum_duration_minutes": 45,
            "effective_duration_minutes": 50,
            "discretionary_excess_minutes": 5,
        }
    )
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    rules_path = project_root / "candidates" / "contextual_permission_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    for policy in rules["plan_node_policies"]:
        if policy["node_id"] in {"node.photo_stop", "node.wait_view"}:
            policy["adjustment_policy"] = "review_only"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    )

    projection = workbench.projection(lens="replay")
    nodes = {node.node_id: node for node in projection.remaining_plan}

    assert nodes["node.photo_stop"].declared_adjustment_policy is None
    assert nodes["node.photo_stop"].adjustment_policy == "review_only"
    assert nodes["node.photo_stop"].available_reducible_minutes == 0
    assert nodes["node.route_floor"].effective_duration_minutes == 45
    assert nodes["node.route_floor"].applied_reduction_minutes == 5
    assert projection.risk_budget.unabsorbed_debt_minutes == 5
    assert projection.current_decision.decision == "CHANGE_PLAN"
    assert any("effective policy is review_only" in item for item in projection.missing_inputs)


def test_baseline_patch_preview_is_no_write_and_saved_version_preserves_parent(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    draft = workbench.generate_baseline_draft(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )
    first = workbench.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="baseline-parent-001",
            explicit_confirmation=True,
        )
    )
    files_before_preview = sorted(workbench.project_root.rglob("*.json"))
    patch = workbench.preview_baseline_patch(
        BaselinePatchPreviewRequest(
            base_candidate_ref=first.version_ref,
            base_candidate_sha256=first.version_sha256,
            operations=[
                {
                    "operation": "add_assumption",
                    "assumption": "Use the reviewed water fallback only after field review.",
                }
            ],
            conversation_refs=["conversation://baseline/review-001"],
            conversation_hashes=["a" * 64],
        )
    )

    assert patch.writes_performed is False
    assert patch.draft.base_candidate_sha256 == first.version_sha256
    assert patch.new_assumptions == [
        "Use the reviewed water fallback only after field review."
    ]
    assert sorted(workbench.project_root.rglob("*.json")) == files_before_preview

    saved = workbench.save_baseline_patch(
        BaselinePatchSaveRequest(
            patch=patch,
            expected_base_candidate_sha256=first.version_sha256,
            idempotency_key="baseline-child-002",
            explicit_confirmation=True,
        )
    )
    payload = json.loads(
        (workbench.project_root / saved.version_ref).read_text(encoding="utf-8")
    )
    assert payload["parent_version_id"] == first.version_id
    assert payload["supersedes_version_id"] == first.version_id
    assert payload["draft"]["conversation_refs"] == [
        "conversation://baseline/review-001"
    ]


def test_baseline_patch_rejects_tampered_candidate_payload(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path)
    draft = workbench.generate_baseline_draft(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )
    saved = workbench.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="baseline-tamper-parent-001",
            explicit_confirmation=True,
        )
    )
    candidate_path = workbench.project_root / saved.version_ref
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["source_text"] = "tampered after immutable save"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(ContextualPermissionConflict) as invalid:
        workbench.preview_baseline_patch(
            BaselinePatchPreviewRequest(
                base_candidate_ref=saved.version_ref,
                base_candidate_sha256=saved.version_sha256,
                operations=[
                    {
                        "operation": "add_assumption",
                        "assumption": "This must not bypass the immutable hash.",
                    }
                ],
            )
        )

    assert invalid.value.code == "baseline_candidate_hash_mismatch"


def test_baseline_accept_rejects_unsafe_candidate_storage_id(tmp_path: Path) -> None:
    workbench = _workbench(tmp_path)
    draft = workbench.generate_baseline_draft(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )
    saved = workbench.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="baseline-unsafe-id-parent-001",
            explicit_confirmation=True,
        )
    )
    candidate_path = workbench.project_root / saved.version_ref
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["baseline_id"] = "../../outside"
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(ContextualPermissionConflict) as invalid:
        workbench.accept_reviewed_baseline(
            BaselineReviewAcceptRequest(
                candidate_ref=saved.version_ref,
                candidate_sha256=saved.version_sha256,
                reviewer_alias="leader-01",
                idempotency_key="baseline-unsafe-id-accept-001",
                explicit_confirmation=True,
            )
        )

    assert invalid.value.code == "invalid_baseline_candidate_id"
    assert not (tmp_path / "outside").exists()


def test_baseline_save_rejects_symlinked_candidate_storage_root(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    mission_baselines = (
        workbench.project_root / "candidates" / "mission_baselines"
    )
    mission_baselines.symlink_to(outside, target_is_directory=True)
    draft = workbench.generate_baseline_draft(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )

    with pytest.raises(ContextualPermissionConflict) as invalid:
        workbench.save_baseline_candidate(
            BaselineCandidateSaveRequest(
                draft=draft,
                expected_source_sha256=draft.source_sha256,
                idempotency_key="baseline-symlink-save-001",
                explicit_confirmation=True,
            )
        )

    assert invalid.value.code == "unsafe_project_write_path"
    assert list(outside.iterdir()) == []


def test_human_baseline_preserves_alias_coordinate_and_branch_as_review_gaps(
    tmp_path: Path,
) -> None:
    draft = _workbench(tmp_path).preview_baseline(
        BaselineAuthoringRequest(
            mode="human_text",
            human_text=(
                "D0：台北 - 瑞穗 C0\n"
                "D1：C0 - 石礦鞍部 - 森林鞍C1 (273734/2589025)\n"
                "D2：C1 - 單攻阿桑來戛 - 巨石獵營 C2"
            ),
        )
    )

    assert draft.days[0].day_kind == "logistics"
    assert draft.days[1].operator_aliases == ["C0", "C1"]
    assert draft.days[1].coordinate_hints == [
        {
            "raw_text": "273734/2589025",
            "confirmed_crs": None,
            "reviewed": False,
        }
    ]
    assert draft.days[2].branch_candidates[0]["kind"] == "out_and_back_candidate"
    assert draft.validation_state == "needs_review"
    assert any("coordinate_crs" in gap for gap in draft.unresolved_gaps)
    assert any("branch_review" in gap for gap in draft.unresolved_gaps)


def test_missing_freshness_is_ineligible_and_exact_expiry_is_server_authoritative(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    seed_path = project_root / "outputs" / "contextual_permission" / "workbench_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    seed["daily_review"]["alternatives"][0]["freshness_inputs"][0][
        "valid_until"
    ] = None
    seed_path.write_text(json.dumps(seed), encoding="utf-8")
    unknown = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    ).daily_emergency_review("D1.instance.001").alternatives[0]
    assert unknown.freshness_state == "freshness_unknown"
    assert unknown.eligibility == "ineligible"

    project_root_2, store_root_2 = _workspace(tmp_path / "expiry")
    seed_2 = json.loads(
        (
            project_root_2
            / "outputs"
            / "contextual_permission"
            / "workbench_seed.json"
        ).read_text(encoding="utf-8")
    )
    exact_expiry = datetime.fromisoformat(
        seed_2["daily_review"]["alternatives"][0]["freshness_inputs"][0][
            "valid_until"
        ]
    )
    expired = ContextualPermissionWorkbench(
        project_root=project_root_2,
        store_root=store_root_2,
        now_factory=lambda: exact_expiry,
    ).daily_emergency_review("D1.instance.001").alternatives[0]
    assert expired.freshness_state == "expired"
    assert expired.eligibility == "ineligible"


def test_same_day_out_of_envelope_change_renews_generation_and_preserves_receipt(
    tmp_path: Path,
) -> None:
    workbench = _workbench(tmp_path)
    session = workbench.daily_emergency_review("D1.instance.001")
    packet = session.alternatives[0]
    aggregate = session.aggregate
    assert aggregate is not None
    context = CanonicalCommandContext(
        session_id=aggregate.session_id,
        group_id=aggregate.group_id,
        mission_day_instance_id=aggregate.mission_day_instance_id,
        membership_revision=aggregate.membership_revision,
        expected_baseline_sha256=aggregate.baseline_sha256,
        expected_aggregate_sha256=aggregate.aggregate_sha256,
        expected_sequence=aggregate.through_sequence,
        idempotency_key="daily-review-first-001",
    )
    receipt = workbench.record_night_decision(
        EmergencyReviewDecisionRequest(
            command_context=context,
            packet_id=packet.packet_id,
            packet_sha256=packet.sha256,
            mission_day_instance_id=packet.mission_day_instance_id,
            review_generation=packet.review_generation,
            reviewed_sequence=packet.reviewed_sequence,
            decision="reject_night_travel",
            reviewer_alias="leader-01",
            explicit_confirmation=True,
        )
    )
    current = workbench.canonical_aggregate("group.ridge")
    workbench.invalidate_daily_review(
        DailyReviewInvalidationRequest(
            command_context=CanonicalCommandContext(
                session_id=current.session_id,
                group_id=current.group_id,
                mission_day_instance_id=current.mission_day_instance_id,
                membership_revision=current.membership_revision,
                expected_baseline_sha256=current.baseline_sha256,
                expected_aggregate_sha256=current.aggregate_sha256,
                expected_sequence=current.through_sequence,
                idempotency_key="daily-review-invalidate-002",
            ),
            reason_kind="route_or_direction_changed",
            source_refs=["evidence://route/changed-direction"],
            source_hashes=["b" * 64],
            reviewed_envelope_crossed=True,
            explicit_confirmation=False,
        )
    )

    renewed = workbench.daily_emergency_review("D1.instance.001")
    assert renewed.review_generation == 2
    assert renewed.state == "re_review_required"
    assert renewed.receipts == []
    historical = workbench._load_receipts("group.ridge")
    assert historical[0].receipt_sha256 == receipt.receipt_sha256


def test_append_only_json_creation_is_atomic_across_processes(tmp_path: Path) -> None:
    target = tmp_path / "append-only" / "event.json"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_append_only_race_worker,
            args=(str(target), {"writer": str(index)}, start, results),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    outcomes = sorted(results.get(timeout=2) for _ in processes)
    assert outcomes == ["append_only_conflict", "written"]
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in {"0", "1"}


def test_canonical_compare_and_append_is_atomic_across_processes(
    tmp_path: Path,
) -> None:
    project_root, store_root = _workspace(tmp_path)
    workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    )
    aggregate = workbench.canonical_aggregate("group.ridge")
    context_payload = CanonicalCommandContext(
        session_id=aggregate.session_id,
        group_id=aggregate.group_id,
        mission_day_instance_id=aggregate.mission_day_instance_id,
        membership_revision=aggregate.membership_revision,
        expected_baseline_sha256=aggregate.baseline_sha256,
        expected_aggregate_sha256=aggregate.aggregate_sha256,
        expected_sequence=aggregate.through_sequence,
        idempotency_key="placeholder",
    ).model_dump(mode="json")

    process_context = multiprocessing.get_context("spawn")
    start = process_context.Event()
    results = process_context.Queue()
    processes = [
        process_context.Process(
            target=_canonical_event_race_worker,
            args=(
                str(project_root),
                str(store_root),
                context_payload,
                writer_id,
                start,
                results,
            ),
        )
        for writer_id in range(8)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in processes]
    assert outcomes.count("written") == 1
    assert set(outcomes) <= {"written", "stale_sequence", "stale_aggregate"}
    events = workbench._load_group_events("group.ridge")  # noqa: SLF001
    assert len(events) == 1
    assert events[0].sequence == aggregate.through_sequence + 1
