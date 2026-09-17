from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pretrip_eta_plan import PreTripEtaPlan
from scout_contextual_permission_workbench import (
    ActivitySummary,
    ArrivalDwellProjection,
    BaselineIdentity,
    BoundedSourceRef,
    CommunicationProjection,
    ContextualPermissionRulesArtifact,
    ContextualPermissionWorkbenchSeed,
    DailyEmergencyReviewSession,
    DayEndProjection,
    DepartureChecklistProjection,
    DepartureChecklistRow,
    MovementGroupProjection,
    RemainingPlanNode,
    ReviewedPlanNodePolicy,
    ReviewedTargetRef,
    ShelterHoldProjection,
    build_fail_closed_night_alternative_packet,
)

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
PLANNED_ETA_REF = "outputs/planned_eta.json"
BASELINE_ROOT_REF = "candidates/mission_baselines"
MODEL_REF = "normalized/permissions/contextual_permission_model.json"
RULES_REF = "candidates/contextual_permission_rules.json"
SEED_REF = "outputs/contextual_permission/workbench_seed.json"
RECEIPT_REF = "reviews/contextual_permission_bootstrap_receipt.json"
JOURNAL_REF = "outputs/contextual_permission/initialization_transaction.json"
PROTECTED_REVIEW_KEYS = (
    "reviewed_mission_baseline_ref",
    "reviewed_mission_baseline_sha256",
    "reviewed_mission_baseline_receipt_id",
)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _fixed_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_file_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_ref(root: Path, ref: str, *, required: bool = True) -> Path:
    path = Path(ref)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe project ref: {ref}")
    resolved = (root / path).resolve(strict=False)
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"Project ref escapes project root: {ref}")
    if required and not resolved.is_file():
        raise FileNotFoundError(ref)
    return resolved


def _write_new_json(path: Path, payload: object) -> str:
    encoded = _canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp_name, path)
        except FileExistsError:
            if path.read_bytes() == encoded:
                return "already_present"
            raise
        return "written"
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def _replace_json_if_changed(path: Path, payload: object) -> bool:
    encoded = _canonical_json_bytes(payload)
    if path.is_file() and path.read_bytes() == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
        tmp_name = ""
        return True
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def _source_report(
    root: Path,
    ref: str | None,
    *,
    key: str,
    required: bool = False,
) -> dict[str, Any]:
    if not ref:
        return {
            "key": key,
            "status": "missing",
            "required": required,
            "ref": None,
            "sha256": None,
        }
    try:
        path = _resolve_ref(root, ref, required=required)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "key": key,
            "status": "missing",
            "required": required,
            "ref": ref,
            "sha256": None,
            "error": str(exc),
        }
    if not path.is_file():
        return {
            "key": key,
            "status": "missing",
            "required": required,
            "ref": ref,
            "sha256": None,
        }
    return {
        "key": key,
        "status": "available",
        "required": required,
        "ref": ref,
        "sha256": _file_sha256(path),
    }


def _primary_gpx(root: Path, project: dict[str, Any]) -> tuple[str, str]:
    manifest_ref = str(project.get("source_inbox_manifest_ref") or "inbox/source_manifest.json")
    manifest_path = _resolve_ref(root, manifest_ref)
    manifest = _read_json(manifest_path)
    sources = manifest.get("sources") if isinstance(manifest, dict) else None
    if not isinstance(sources, list):
        raise ValueError("source inbox manifest has no sources list")
    for item in sources:
        if not isinstance(item, dict) or item.get("role") != "golden_route_reference":
            continue
        ref = str(item.get("workspace_ref") or item.get("ref") or "")
        if not ref:
            continue
        path = _resolve_ref(root, ref)
        sha = _file_sha256(path)
        expected = item.get("sha256")
        if isinstance(expected, str) and expected and expected != sha:
            raise ValueError(f"golden_route_reference hash mismatch: {ref}")
        return ref, sha
    raise ValueError("source inbox manifest has no golden_route_reference")


def _mission_day_ids(project: dict[str, Any]) -> list[str]:
    route_days = project.get("route_days")
    if isinstance(route_days, int) and route_days > 1:
        return [f"D{index}" for index in range(1, min(route_days, 30) + 1)]
    return ["D1"]


def _planned_eta(
    project_id: str,
    route_name: str,
    day_ids: list[str],
    source_refs: list[str],
    generated_at: str,
) -> dict[str, Any]:
    estimates = []
    for index, day_id in enumerate(day_ids):
        estimates.append(
            {
                "segment_id": f"permission-bootstrap.{day_id}.route-axis",
                "from_node_name": (
                    "Reference route axis start"
                    if index == 0
                    else f"{day_ids[index - 1]} unresolved day end"
                ),
                "to_node_name": f"{day_id} unresolved day end",
                "status": "timing_gap",
                "eta_minutes_p50": None,
                "eta_minutes_p75": None,
                "reason": "No reviewed day boundary or reference segment timing is bound yet.",
            }
        )
    return {
        "artifact_kind": "pretrip_planned_eta",
        "schema_version": "plannedEta.bootstrap.v1",
        "project_id": project_id,
        "plan_id": f"eta.{project_id}.permission-bootstrap.v1",
        "route_name": route_name,
        "generated_at": generated_at,
        "assumption": {
            "day1_target_node_name": "待確認：D1 當日預計最後位置",
            "turn_back_checkpoint_node_name": "待確認：D1 折返檢查點",
            "source_route_days_metadata": len(day_ids),
            "source_route_days_planning_authority": False,
        },
        "estimates": estimates,
        "source_refs": source_refs,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }


def _baseline_candidate(
    project_id: str,
    route_name: str,
    primary_gpx_ref: str,
    primary_gpx_sha: str,
    day_ids: list[str],
    source_hashes: dict[str, str],
    *,
    version_id: str | None = None,
    supersedes_version_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    baseline_id = f"baseline.{project_id}.permission-initialization"
    version_id = version_id or "version.reference-gpx.authoring-seed.v1"
    version_ref = f"{BASELINE_ROOT_REF}/{baseline_id}/versions/{version_id}.json"
    days = []
    unresolved: list[str] = []
    for day_id in day_ids:
        day_unresolved = [
            f"{day_id}:planned_day_end_target",
            f"{day_id}:turn_back_checkpoint",
            f"{day_id}:overnight_and_day_boundary",
            f"{day_id}:emergency_bivy_candidates",
        ]
        unresolved.extend(day_unresolved)
        days.append(
            {
                "mission_day_id": day_id,
                "source_text": (
                    f"{route_name} reference-GPX route axis; {day_id} boundary unresolved"
                ),
                "day_kind": "on_trail",
                "ordered_place_mentions": [
                    "Reference route axis start",
                    f"待確認：{day_id} 當日預計最後位置",
                ],
                "resolved_targets": [],
                "resolved_target_refs": {},
                "resolved_target_hashes": {},
                "unresolved_names": day_unresolved,
                "operator_aliases": [],
                "coordinate_hints": [],
                "branch_candidates": [],
            }
        )
    source_refs = list(source_hashes)
    draft = {
        "artifact_kind": "mission_baseline_candidate",
        "schema_version": "missionBaselineCandidate.v1",
        "draft_id": "baseline-draft.reference-gpx.permission-initialization.v1",
        "source_mode": "reference_gpx",
        "source_sha256": primary_gpx_sha,
        "source_text": f"Reference GPX authoring seed: {primary_gpx_ref}",
        "source_refs": source_refs,
        "source_hashes": source_hashes,
        "route_axis_validation": {
            "track_order": "unknown",
            "endpoint_continuity": "unknown",
            "resume_gaps": "unknown",
            "route_direction": "unknown",
        },
        "days": days,
        "assumptions": [
            "The GPX is reference evidence only; it does not prove live route authority.",
            "Imported route_days metadata can size an authoring checklist but is not planning authority.",
        ],
        "conversation_refs": [],
        "base_candidate_ref": None,
        "base_candidate_sha256": None,
        "patch_sha256": None,
        "validation_state": "needs_review",
        "unresolved_gaps": unresolved,
        "proposal_profile": "legacy_sparse",
        "capability_version": "legacy_sparse.v1",
        "migration_state": "none",
        "writes_performed": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }
    payload: dict[str, Any] = {
        "artifact_kind": "mission_baseline_candidate_version",
        "schema_version": "missionBaselineCandidate.v1",
        "baseline_id": baseline_id,
        "version_id": version_id,
        "parent_version_id": None,
        "supersedes_version_id": supersedes_version_id,
        "request_sha256": _digest(
            {
                "operation": "permission_initialization",
                "project_id": project_id,
                "source_sha256": primary_gpx_sha,
            }
        ),
        "idempotency_key": f"permission-initialization-{project_id}-v1",
        "source_mode": "reference_gpx",
        "source_sha256": primary_gpx_sha,
        "source_text": draft["source_text"],
        "source_refs": source_refs,
        "source_hashes": source_hashes,
        "source_draft_id": draft["draft_id"],
        "base_candidate_ref": None,
        "base_candidate_sha256": None,
        "patch_sha256": None,
        "conversation_refs": [],
        "route_axis_validation": draft["route_axis_validation"],
        "days": days,
        "draft": draft,
        "unresolved_gaps": unresolved,
        "validation_state": "needs_review",
        "promotion_gates": {
            "route_critical_names_resolved": False,
            "route_axis_order_pass": False,
            "endpoint_continuity_pass": False,
            "resume_gap_pass": False,
            "route_direction_pass": False,
            "overnight_and_day_boundaries_reviewed": False,
            "graph_compilation_pass": False,
            "deterministic_validation_pass": False,
        },
        "review_ready": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "writes_performed": True,
        "version_sha256": "0" * 64,
    }
    payload["version_sha256"] = _digest(
        {key: value for key, value in payload.items() if key != "version_sha256"}
    )
    return version_ref, payload


def _plan_nodes(project_id: str, day_ids: list[str]) -> list[RemainingPlanNode]:
    definitions = (
        (
            "route-axis",
            "route_axis",
            "reference route axis（待每日切段）",
            100,
            False,
            "Reference route axis is authoring evidence only; reviewed day boundaries are pending.",
        ),
        (
            "day-end",
            "day_end_target",
            "當日預計最後位置（待領隊確認）",
            100,
            True,
            "Planned day-end target requires human review.",
        ),
        (
            "reserve",
            "weather_daylight_retreat_reserve",
            "天候／日照／後撤預留（待審核）",
            95,
            True,
            "Weather, daylight and retreat reserves are not reviewed.",
        ),
        (
            "night-alternative",
            "night_alternative",
            "夜間替代方案審核",
            90,
            False,
            "Safety / Emergency gates must be reviewed before night alternatives.",
        ),
    )
    nodes: list[RemainingPlanNode] = []
    for day_id in day_ids:
        for suffix, kind, label, priority, protected, gap in definitions:
            node_id = f"node.{suffix}.{day_id}"
            policy_ref = f"{RULES_REF}#{node_id}"
            policy_sha = _fixed_hash(f"{project_id}:{node_id}:review-only-initialization")
            nodes.append(
                RemainingPlanNode(
                    node_id=node_id,
                    action_id=kind,
                    label=f"{day_id} {label}",
                    mission_day_id=day_id,
                    kind=kind,
                    declared_adjustment_policy="review_only",
                    adjustment_policy="review_only",
                    cancellable=False,
                    priority=priority,
                    policy_reason=(
                        "Fail closed until the route day, endpoint, reserve, and "
                        "safety handoff are reviewed."
                    ),
                    policy_source=policy_ref,
                    source_refs=[policy_ref],
                    baseline_duration_minutes=0,
                    minimum_duration_minutes=0,
                    discretionary_excess_minutes=0,
                    available_reducible_minutes=0,
                    applied_reduction_minutes=0,
                    effective_duration_minutes=0,
                    absorbed_debt_minutes=0,
                    protected=protected,
                    adjustment_state="review_required",
                    source_rule_ref=policy_ref,
                    source_rule_sha256=policy_sha,
                    data_quality=[gap],
                )
            )
    return nodes


def _checklist(
    project_id: str,
    day_id: str,
    baseline_sha: str,
    route_ref: str,
    route_sha: str,
    weather_ref: str | None,
    weather_sha: str | None,
) -> DepartureChecklistProjection:
    rows = [
        DepartureChecklistRow(
            row_id="weather_threats",
            label="Weather / threats",
            source_mode="scout_auto",
            state="blocked",
            evidence_summary="No reviewed current weather/daylight departure evidence is bound yet.",
            evidence_ref=weather_ref,
            evidence_sha256=weather_sha,
            freshness="unknown" if weather_ref else "not_applicable",
            field_condition_differs_available=True,
            blocker="Refresh and review current weather evidence before departure review.",
        ),
        DepartureChecklistRow(
            row_id="route_navigation",
            label="Route / navigation",
            source_mode="scout_auto",
            state="blocked",
            evidence_summary="Reference GPX exists, but day-end and turn-back targets are unresolved.",
            evidence_ref=route_ref,
            evidence_sha256=route_sha,
            freshness="not_applicable",
            field_condition_differs_available=True,
            blocker="Review route axis, daily endpoint, and turn-back target.",
        ),
        DepartureChecklistRow(
            row_id="team",
            label="Team",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="No team readiness assertion is included in this initialization.",
            evidence_ref=None,
            freshness="not_applicable",
            field_condition_differs_available=False,
            blocker="Leader review required.",
        ),
        DepartureChecklistRow(
            row_id="equipment_power",
            label="Equipment / power",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="No equipment or power assertion is included in this initialization.",
            evidence_ref=None,
            freshness="not_applicable",
            field_condition_differs_available=False,
            blocker="Leader review required.",
        ),
        DepartureChecklistRow(
            row_id="supplies_shelter",
            label="Supplies / shelter fallback",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="Emergency-bivy and shelter fallbacks are unresolved.",
            evidence_ref=None,
            freshness="not_applicable",
            field_condition_differs_available=False,
            blocker="Safety / Emergency review required.",
        ),
        DepartureChecklistRow(
            row_id="communication_plan",
            label="Communication / next-day plan",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="No route-scoped communication window is accepted yet.",
            evidence_ref=None,
            freshness="not_applicable",
            field_condition_differs_available=False,
            blocker="Leader review required.",
        ),
    ]
    return DepartureChecklistProjection(
        checklist_id=f"departure.checklist.{day_id}.permission-initialization.v1",
        checklist_sha256=_digest([row.model_dump(mode="json") for row in rows]),
        pending_day_plan_sha256=baseline_sha,
        rows=rows,
        open_conflict_count=3,
        scout_suggestion_code="refresh_evidence",
        scout_suggestion="先完成每日終點、後撤點、天候日照與六項行前檢核；目前不可確認出發。",
        scout_suggestion_suspended=False,
        can_confirm_departure=False,
        mission_day_started=False,
    )


def _seed(
    project_id: str,
    day_ids: list[str],
    baseline_ref: str,
    baseline: dict[str, Any],
    receipt_ref: str,
    receipt_sha: str,
    rules_sha: str,
    route_ref: str,
    route_sha: str,
    weather_ref: str | None,
    weather_sha: str | None,
    evidence: list[BoundedSourceRef],
) -> ContextualPermissionWorkbenchSeed:
    baseline_sha = str(baseline["version_sha256"])
    day_id = day_ids[0]
    target_ref = f"candidate://permission/{day_id}/end-unresolved"
    target_sha = _fixed_hash(f"{project_id}:{day_id}:end-unresolved")
    start_ref = f"candidate://permission/{day_id}/start-unresolved"
    start_sha = _fixed_hash(f"{project_id}:{day_id}:start-unresolved")
    membership_sha = _fixed_hash(f"{project_id}:group-main:permission-initialization")
    checklist = _checklist(
        project_id,
        day_id,
        baseline_sha,
        route_ref,
        route_sha,
        weather_ref,
        weather_sha,
    )
    daily_session_id = f"daily-review.{day_id}.permission-initialization.001"
    group = MovementGroupProjection(
        group_id="group.main",
        group_label="主要行動群組（待確認）",
        formation_kind="field_explicit",
        membership_revision=1,
        membership_sha256=membership_sha,
        participant_refs_hash=membership_sha,
        coordinator_ref="participant://leader-unassigned",
        shared_dependency_refs=[],
        shared_dependency_hashes=[],
        formation_receipt_ref=receipt_ref,
        formation_receipt_sha256=receipt_sha,
        status="not_started",
        mission_day_id=day_id,
        mission_day_instance_id=f"{day_id}.instance.permission-initialization.001",
        day_end=DayEndProjection(
            planned_target_label=f"待確認：{day_id} 當日預計最後位置",
            effective_target_label=f"待確認：{day_id} 當日預計最後位置",
            planned_target_ref=target_ref,
            planned_target_sha256=target_sha,
            effective_target_ref=target_ref,
            effective_target_sha256=target_sha,
            feasibility="unknown",
            state="day_end_at_risk",
            completion="open",
            baseline_day_end_reached=False,
            close_receipt_ref=None,
        ),
        shelter_hold=ShelterHoldProjection(
            hold_id=None,
            state="not_required",
            target_label=None,
            calendar_days_elapsed=0,
            mission_days_consumed=0,
            next_step="先在 baseline 工作台確認每日終點與緊急扎營候選點。",
        ),
        pending_next_day=day_ids[1] if len(day_ids) > 1 else None,
        departure_checklist=checklist,
        activity_summary=ActivitySummary(
            states={
                "route_travel": 0,
                "resting": 0,
                "lying": 0,
                "sleeping": 0,
                "resumed_movement": 0,
                "unknown": 1,
            },
            fresh_count=0,
            stale_count=0,
            contradiction_count=0,
        ),
        arrival_dwell=ArrivalDwellProjection(
            state="blocked",
            elapsed_seconds=0,
            dwell_remaining_seconds=600,
            target_ref=target_ref,
            target_sha256=target_sha,
            arrival_zone_ref=f"candidate://permission/{day_id}/arrival-zone-unresolved",
            arrival_zone_sha256=_fixed_hash(f"{project_id}:{day_id}:arrival-zone-unresolved"),
            route_progress_ref="evidence://movement/not-started",
            route_progress_sha256=_fixed_hash(f"{project_id}:movement:not-started"),
            dwell_policy_ref="reviewed://dwell-policy/default-600s",
            dwell_policy_sha256=_fixed_hash(f"{project_id}:dwell-policy:600s"),
            individual_activity_summary_ref="evidence://activity/not-started",
            individual_activity_summary_sha256=_fixed_hash(f"{project_id}:activity:not-started"),
            target_match=False,
            gnss_confidence="unknown",
            manual_complete_available=False,
            blocked_by=[f"{day_id} day-end target has not been reviewed."],
        ),
        communication=CommunicationProjection(
            policy_id=f"comm-window.{day_id}.permission-initialization.v1",
            policy_sha256=_fixed_hash(
                f"{project_id}:{day_id}:communication:permission-initialization"
            ),
            state="unknown",
            membership_revision=1,
            route_scope_ref=route_ref,
            route_scope_sha256=route_sha,
            route_scope_label="Reference route axis; communication windows pending review",
            viewpoint="local",
            next_check_in_target=f"待確認：{day_id} 當日預計最後位置",
            baseline_window="待 baseline review",
            effective_window="待 baseline review",
            deadline_driver="Destination receipt only; wall-clock time cannot close a mission day.",
            next_check_in_target_ref=target_ref,
            next_check_in_target_sha256=target_sha,
            last_verified_receipt_ref=None,
            local_group_contact_state="unknown",
            remote_observed_contact_state="unknown",
            scout_recommendation="monitor_reviewed_window",
            contact_overdue=False,
            emergency_declared=False,
        ),
        unexpected_separation=False,
    )
    night_alternatives = [
        build_fail_closed_night_alternative_packet(
            project_id=project_id,
            session_id=daily_session_id,
            mission_day_id=day_id,
            mission_day_instance_id=f"{day_id}.instance.permission-initialization.001",
            movement_group_id="group.main",
            membership_revision=1,
            membership_sha256=membership_sha,
            review_generation=1,
            reviewed_sequence=0,
            from_target=ReviewedTargetRef(
                target_ref=start_ref,
                target_sha256=start_sha,
                target_label=f"{day_id} 起點待確認",
            ),
            to_target=ReviewedTargetRef(
                target_ref=target_ref,
                target_sha256=target_sha,
                target_label=f"待確認：{day_id} 當日預計最後位置",
            ),
            retreat_candidates=[
                ReviewedTargetRef(
                    target_ref=f"candidate://safety-emergency/{day_id}/retreat-unresolved",
                    target_sha256=_fixed_hash(f"{project_id}:{day_id}:retreat-unresolved"),
                    target_label="後撤點待審核",
                )
            ],
            emergency_bivy_candidates=[
                ReviewedTargetRef(
                    target_ref=f"candidate://safety-emergency/{day_id}/emergency-bivy-unresolved",
                    target_sha256=_fixed_hash(f"{project_id}:{day_id}:bivy-unresolved"),
                    target_label="緊急扎營點待審核",
                )
            ],
            route_scope_ref=route_ref,
            route_scope_sha256=route_sha,
            mission_day_plan_ref=baseline_ref,
            mission_day_plan_sha256=baseline_sha,
            reviewed_alternative_complete=False,
            built_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
            maximum_night_duration_minutes=60,
            requires_daylight=None,
            source_refs=[ref for ref in [receipt_ref, route_ref, weather_ref] if ref],
        )
    ]
    daily_review = DailyEmergencyReviewSession(
        session_id=daily_session_id,
        project_id=project_id,
        mission_day_id=day_id,
        mission_day_instance_id=f"{day_id}.instance.permission-initialization.001",
        movement_group_id="group.main",
        membership_revision=1,
        mission_day_plan_ref=baseline_ref,
        mission_day_plan_sha256=baseline_sha,
        review_generation=1,
        state="not_started",
        planned_day_end_target_ref=target_ref,
        planned_day_end_target_sha256=target_sha,
        planned_day_end_target_label=f"待確認：{day_id} 當日預計最後位置",
        effective_day_end_target_ref=target_ref,
        effective_day_end_target_sha256=target_sha,
        day_end_state="day_end_at_risk",
        alternatives=night_alternatives,
    )
    return ContextualPermissionWorkbenchSeed(
        artifact_kind="contextual_permission_workbench_seed",
        schema_version="contextualPermissionWorkbenchSeed.v1",
        project_id=project_id,
        lens="baseline",
        replay_session_id="session.permission-initialization.reference-gpx.v1",
        baseline=BaselineIdentity(
            baseline_id=str(baseline["baseline_id"]),
            revision_id=str(baseline["version_id"]),
            baseline_sha256=baseline_sha,
            reviewed_receipt_ref=receipt_ref,
            source_mode="reference_gpx",
            baseline_candidate_id=str(baseline["baseline_id"]),
            baseline_version_id=str(baseline["version_id"]),
            accepted_receipt_id=None,
            immutable=False,
            accepted_by_human=False,
            candidate_only=True,
            runtime_safety_truth=False,
            departure_approval_granted=False,
            contextual_permission_rules_ref=RULES_REF,
            contextual_permission_rules_sha256=rules_sha,
            contextual_permission_rules_reviewed_by_human=False,
            source_hashes={
                baseline_ref: baseline_sha,
                RULES_REF: rules_sha,
            },
        ),
        action_events=[],
        remaining_plan=_plan_nodes(project_id, day_ids),
        daily_review=daily_review,
        movement_groups=[group],
        evidence=evidence,
    )


def _validate_existing(
    root: Path, project: dict[str, Any]
) -> tuple[ContextualPermissionWorkbenchSeed, str, str, str] | dict[str, Any] | None:
    seed_path = _resolve_ref(root, SEED_REF, required=False)
    if not seed_path.exists():
        return None
    try:
        seed = ContextualPermissionWorkbenchSeed.model_validate(_read_json(seed_path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        return _blocked("existing_contextual_permission_seed_invalid", error=str(exc))

    project_id = str(project.get("project_id") or root.name)
    if seed.project_id != project_id:
        return _blocked("existing_contextual_permission_seed_project_mismatch")
    if project.get("contextual_permission_bootstrap_ref") != SEED_REF:
        return _blocked("contextual_permission_project_seed_ref_missing")

    candidate_ref = str(project.get("contextual_permission_baseline_candidate_ref") or "")
    candidate_sha = str(project.get("contextual_permission_baseline_candidate_sha256") or "")
    if not candidate_ref or candidate_sha != seed.baseline.baseline_sha256:
        return _blocked("contextual_permission_project_candidate_binding_mismatch")
    try:
        candidate = _read_json(_resolve_ref(root, candidate_ref))
    except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError) as exc:
        return _blocked("contextual_permission_baseline_candidate_missing", error=str(exc))
    if not isinstance(candidate, dict) or candidate.get("version_sha256") != candidate_sha:
        return _blocked("contextual_permission_baseline_candidate_hash_mismatch")
    if candidate.get("project_id") not in {None, project_id}:
        return _blocked("contextual_permission_baseline_candidate_project_mismatch")

    rules_ref = str(project.get("contextual_permission_rules_ref") or RULES_REF)
    try:
        rules_path = _resolve_ref(root, rules_ref)
        rules = ContextualPermissionRulesArtifact.model_validate_json(
            rules_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError, FileNotFoundError) as exc:
        return _blocked("contextual_permission_rules_missing_or_invalid", error=str(exc))
    rules_sha = _file_sha256(rules_path)
    if rules.project_id != project_id:
        return _blocked("contextual_permission_rules_project_mismatch")
    if rules.reviewed_baseline_sha256 != seed.baseline.baseline_sha256:
        return _blocked("contextual_permission_rules_baseline_mismatch")
    if seed.baseline.contextual_permission_rules_sha256 != rules_sha:
        return _blocked("contextual_permission_rules_seed_hash_mismatch")
    policies = {policy.node_id: policy for policy in rules.plan_node_policies}
    if len(policies) != len(rules.plan_node_policies):
        return _blocked("contextual_permission_rules_duplicate_node")
    for node in seed.remaining_plan:
        policy = policies.get(node.node_id)
        if policy is None:
            return _blocked("contextual_permission_rule_missing")
        if (
            policy.mission_day_id != node.mission_day_id
            or policy.adjustment_policy != node.adjustment_policy
            or policy.minimum_duration_minutes != node.minimum_duration_minutes
            or policy.policy_ref != node.source_rule_ref
            or policy.policy_sha256 != node.source_rule_sha256
        ):
            return _blocked("contextual_permission_rule_mismatch")

    for source in seed.evidence:
        if source.source_ref.startswith(("candidate://", "reviewed://", "evidence://")):
            continue
        try:
            source_path = _resolve_ref(root, source.source_ref)
        except (ValueError, FileNotFoundError) as exc:
            return _blocked("contextual_permission_seed_source_missing", error=str(exc))
        if _file_sha256(source_path) != source.source_sha256:
            return _blocked(
                "contextual_permission_seed_source_hash_mismatch",
                ref=source.source_ref,
                source_kind=source.source_kind,
            )

    return seed, candidate_ref, candidate_sha, rules_ref


def _blocked(code: str, **extra: object) -> dict[str, Any]:
    return {
        "status": "blocked",
        "authoring_ready": False,
        "projection_ready": False,
        "root_causes": [code],
        "writes_performed": False,
        **extra,
    }


def _already_initialized(
    root: Path,
    seed: ContextualPermissionWorkbenchSeed,
    candidate_ref: str,
    candidate_sha: str,
    rules_ref: str,
) -> dict[str, Any]:
    return {
        "status": "already_initialized",
        "authoring_ready": True,
        "projection_ready": False,
        "project_id": seed.project_id,
        "seed_ref": SEED_REF,
        "seed_sha256": _file_sha256(_resolve_ref(root, SEED_REF)),
        "baseline_candidate_ref": candidate_ref,
        "baseline_candidate_sha256": candidate_sha,
        "contextual_permission_rules_ref": rules_ref,
        "reviewed": seed.baseline.accepted_by_human,
        "runtime_safety_truth": seed.baseline.runtime_safety_truth,
        "writes_performed": False,
        "root_causes": [],
    }


def _eta_binding(
    root: Path,
    project: dict[str, Any],
    project_id: str,
    route_name: str,
    day_ids: list[str],
    source_refs: list[str],
    generated_at: str,
) -> tuple[str, dict[str, Any] | None, str, bool] | dict[str, Any]:
    existing_ref = project.get("planned_eta_ref")
    if isinstance(existing_ref, str) and existing_ref.strip():
        try:
            path = _resolve_ref(root, existing_ref)
            payload = _read_json(path)
            try:
                PreTripEtaPlan.model_validate(payload)
            except ValidationError:
                if not (
                    isinstance(payload, dict)
                    and payload.get("artifact_kind") == "pretrip_planned_eta"
                    and payload.get("schema_version") == "plannedEta.bootstrap.v1"
                    and payload.get("candidate_only") is True
                    and payload.get("runtime_safety_truth") is False
                ):
                    raise
        except (OSError, json.JSONDecodeError, ValidationError, ValueError, FileNotFoundError) as exc:
            return _blocked("planned_eta_ref_invalid_or_missing", error=str(exc))
        return existing_ref, None, _file_sha256(path), False
    payload = _planned_eta(project_id, route_name, day_ids, source_refs, generated_at)
    return PLANNED_ETA_REF, payload, _json_file_sha256(payload), True


def _make_journal(
    root: Path,
    project: dict[str, Any],
    *,
    refresh_unreviewed: bool = False,
) -> dict[str, Any] | dict[str, Any]:
    project_id = str(project.get("project_id") or root.name)
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        return _blocked("invalid_project_id")
    if any(project.get(key) for key in PROTECTED_REVIEW_KEYS):
        return _blocked("reviewed_baseline_exists_without_authoring_seed")
    if project.get("contextual_permission_baseline_candidate_ref") and not project.get(
        "contextual_permission_bootstrap_ref"
    ):
        return _blocked("baseline_candidate_exists_without_authoring_seed")

    try:
        primary_gpx_ref, primary_gpx_sha = _primary_gpx(root, project)
    except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError) as exc:
        return _blocked("golden_route_reference_unavailable", error=str(exc))

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    route_name = str(project.get("route_name") or project.get("title") or project_id)
    day_ids = _mission_day_ids(project)
    source_reports = [
        _source_report(root, primary_gpx_ref, key="golden_route_reference", required=True),
        _source_report(
            root,
            project.get("compiled_mission_graph_reviewed_ref"),
            key="compiled_mission_graph_reviewed_ref",
        ),
        _source_report(
            root,
            project.get("reference_segment_timing_ref"),
            key="reference_segment_timing_ref",
        ),
        _source_report(
            root,
            project.get("weather_daylight_evidence_ref"),
            key="weather_daylight_evidence_ref",
        ),
        _source_report(root, project.get("route_summary_ref"), key="route_summary_ref"),
        _source_report(
            root,
            project.get("reference_pace_energy_analysis_ref"),
            key="reference_pace_energy_analysis_ref",
        ),
        _source_report(root, project.get("checkpoint_events_ref"), key="checkpoint_events_ref"),
    ]
    available_refs = [
        str(item["ref"])
        for item in source_reports
        if item["status"] == "available" and item["ref"]
    ]
    eta = _eta_binding(root, project, project_id, route_name, day_ids, available_refs, generated_at)
    if isinstance(eta, dict):
        return eta
    eta_ref, eta_payload, eta_sha, writes_eta = eta

    source_hashes = {
        str(item["ref"]): str(item["sha256"])
        for item in source_reports
        if item["status"] == "available" and item["ref"] and item["sha256"]
    }
    source_hashes[eta_ref] = eta_sha
    refresh_suffix = _digest(source_hashes)[:12] if refresh_unreviewed else None
    previous_version_id = None
    if refresh_unreviewed:
        previous_ref = str(project.get("contextual_permission_baseline_candidate_ref") or "")
        try:
            previous = _read_json(_resolve_ref(root, previous_ref)) if previous_ref else {}
            if isinstance(previous, dict):
                previous_version_id = str(previous.get("version_id") or "") or None
        except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError):
            previous_version_id = None
    baseline_ref, baseline_payload = _baseline_candidate(
        project_id,
        route_name,
        primary_gpx_ref,
        primary_gpx_sha,
        day_ids,
        source_hashes,
        version_id=(
            f"version.reference-gpx.authoring-seed.{refresh_suffix}"
            if refresh_suffix
            else None
        ),
        supersedes_version_id=previous_version_id,
    )
    receipt_ref = (
        f"reviews/contextual_permission_initialization_receipts/{baseline_payload['version_id']}.json"
        if refresh_unreviewed
        else RECEIPT_REF
    )
    receipt_payload = {
        "artifact_kind": "contextual_permission_initialization_receipt",
        "schema_version": "contextualPermissionInitializationReceipt.v1",
        "project_id": project_id,
        "requested_scope": "Create the first candidate-only Contextual Permission authoring seed after Golden preparation.",
        "rule_scope": "fail_closed_review_only",
        "baseline_source_mode": "reference_gpx",
        "baseline_candidate_ref": baseline_ref,
        "baseline_candidate_sha256": baseline_payload["version_sha256"],
        "human_itinerary_review_completed": False,
        "departure_approval_granted": False,
        "runtime_authorization_performed": False,
        "safety_api_called": False,
        "outbound_action_performed": False,
        "recorded_at": generated_at,
        "source_reports": source_reports,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    receipt_sha = _json_file_sha256(receipt_payload)
    plan_nodes = _plan_nodes(project_id, day_ids)
    rules = ContextualPermissionRulesArtifact(
        artifact_kind="pretrip_contextual_permission_rules",
        schema_version="contextual_permission_rules.v2",
        project_id=project_id,
        reviewed_baseline_ref=baseline_ref,
        reviewed_baseline_sha256=str(baseline_payload["version_sha256"]),
        reviewed_by_human=False,
        review_receipt_ref=receipt_ref,
        review_receipt_sha256=receipt_sha,
        plan_node_policies=[
            ReviewedPlanNodePolicy(
                node_id=node.node_id,
                mission_day_id=node.mission_day_id,
                adjustment_policy=node.adjustment_policy,
                minimum_duration_minutes=node.minimum_duration_minutes,
                policy_ref=node.source_rule_ref,
                policy_sha256=node.source_rule_sha256,
                reviewed=False,
            )
            for node in plan_nodes
        ],
        candidate_only=True,
        runtime_safety_truth=False,
    )
    rules_payload = rules.model_dump(mode="json")
    rules_sha = _json_file_sha256(rules_payload)
    evidence = [
        BoundedSourceRef(
            source_id="source.golden-route-reference",
            source_kind="golden_route_reference",
            source_ref=primary_gpx_ref,
            source_sha256=primary_gpx_sha,
            freshness="not_applicable",
            summary="Golden route GPX is pretrip reference evidence only; it is not runtime safety truth.",
        ),
        BoundedSourceRef(
            source_id="source.planned-eta",
            source_kind="planned_eta",
            source_ref=eta_ref,
            source_sha256=eta_sha,
            freshness="unknown",
            summary="Planned ETA evidence bound for authoring; review is still required.",
        ),
    ]
    for report in source_reports[1:]:
        if report["status"] != "available" or not report["ref"] or not report["sha256"]:
            continue
        evidence.append(
            BoundedSourceRef(
                source_id=f"source.{report['key']}",
                source_kind=str(report["key"]),
                source_ref=str(report["ref"]),
                source_sha256=str(report["sha256"]),
                freshness="unknown",
                summary=(
                    "Optional prepared source bound for Contextual Permission authoring: "
                    f"{report['key']}"
                ),
            )
        )
    weather_report = next(
        item for item in source_reports if item["key"] == "weather_daylight_evidence_ref"
    )
    seed = _seed(
        project_id,
        day_ids,
        baseline_ref,
        baseline_payload,
        receipt_ref,
        receipt_sha,
        rules_sha,
        primary_gpx_ref,
        primary_gpx_sha,
        str(weather_report["ref"] or "") or None,
        str(weather_report["sha256"] or "") or None,
        evidence,
    )
    seed_payload = seed.model_dump(mode="json")
    model_payload = {
        "artifact_kind": "pretrip_contextual_permission_model",
        "schema_version": "contextualPermissionModel.v2",
        "project_id": project_id,
        "status": "authoring_seed_needs_human_review",
        "source_mode": "reference_gpx",
        "baseline_candidate_ref": baseline_ref,
        "baseline_candidate_sha256": baseline_payload["version_sha256"],
        "contextual_permission_rules_ref": RULES_REF,
        "adjustment_contract": {
            "current_policy": "review_only",
            "automatic_reduction_enabled": False,
            "scout_outputs": "candidate_advice_only",
            "day_boundary_policy": "destination_receipt_only",
        },
        "source_reports": source_reports,
        "unresolved_gaps": baseline_payload["unresolved_gaps"],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }
    project_updates = {
        "planned_eta_ref": eta_ref,
        "contextual_permission_model_ref": MODEL_REF,
        "contextual_permission_rules_ref": RULES_REF,
        "contextual_permission_bootstrap_ref": SEED_REF,
        "contextual_permission_baseline_candidate_ref": baseline_ref,
        "contextual_permission_baseline_candidate_sha256": baseline_payload["version_sha256"],
        "contextual_permission_bootstrap_state": "needs_human_review",
        "contextual_permission_authoring_ready": True,
        "contextual_permission_rule_count": len(plan_nodes),
        "contextual_permission_collection_updated_at": generated_at,
        "contextual_permission_collection_schema_version": "contextualPermissionWorkbenchSeed.v1",
    }
    write_plan = []
    if writes_eta and eta_payload is not None:
        write_plan.append({"ref": eta_ref, "payload": eta_payload, "mode": "create"})
    write_plan.extend(
        [
            {"ref": baseline_ref, "payload": baseline_payload, "mode": "create"},
            {"ref": receipt_ref, "payload": receipt_payload, "mode": "create"},
            {"ref": MODEL_REF, "payload": model_payload, "mode": "replace" if refresh_unreviewed else "create"},
            {"ref": RULES_REF, "payload": rules_payload, "mode": "replace" if refresh_unreviewed else "create"},
            {"ref": SEED_REF, "payload": seed_payload, "mode": "replace" if refresh_unreviewed else "create"},
        ]
    )
    source_snapshot_items = list(source_reports)
    if not writes_eta:
        source_snapshot_items.append(
            {
                "key": "planned_eta_ref",
                "ref": eta_ref,
                "sha256": eta_sha,
                "status": "available",
                "required": True,
            }
        )
    source_snapshot = [
        item
        for item in source_snapshot_items
        if item.get("status") == "available" and item.get("ref") and item.get("sha256")
    ]
    project_ref_bindings = {
        key: project.get(key)
        for key in (
            "source_inbox_manifest_ref",
            "compiled_mission_graph_reviewed_ref",
            "reference_segment_timing_ref",
            "weather_daylight_evidence_ref",
            "route_summary_ref",
            "reference_pace_energy_analysis_ref",
            "checkpoint_events_ref",
            "planned_eta_ref",
        )
        if key in project
    }
    journal = {
        "artifact_kind": "contextual_permission_initialization_transaction",
        "schema_version": "contextualPermissionInitializationTransaction.v1",
        "project_id": project_id,
        "created_at": generated_at,
        "status": "pending_or_recoverable",
        "refresh_unreviewed": refresh_unreviewed,
        "project_ref_bindings": project_ref_bindings,
        "project_updates": project_updates,
        "source_snapshot": source_snapshot,
        "write_plan": write_plan,
        "write_plan_sha256": "0" * 64,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }
    journal["write_plan_sha256"] = _digest(write_plan)
    return journal


def _load_journal(root: Path) -> dict[str, Any] | None | dict[str, Any]:
    path = _resolve_ref(root, JOURNAL_REF, required=False)
    if not path.is_file():
        return None
    try:
        journal = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return _blocked("contextual_permission_initialization_journal_invalid", error=str(exc))
    if not isinstance(journal, dict) or journal.get("artifact_kind") != "contextual_permission_initialization_transaction":
        return _blocked("contextual_permission_initialization_journal_invalid")
    if journal.get("write_plan_sha256") != _digest(journal.get("write_plan") or []):
        return _blocked("contextual_permission_initialization_journal_hash_mismatch")
    return journal


def _validate_journal_sources(
    root: Path, project: dict[str, Any], journal: dict[str, Any]
) -> dict[str, Any] | None:
    if journal.get("project_id") != str(project.get("project_id") or root.name):
        return _blocked("contextual_permission_initialization_journal_project_mismatch")
    for key, value in dict(journal.get("project_ref_bindings") or {}).items():
        if project.get(key) != value:
            return _blocked("contextual_permission_initialization_project_ref_changed", ref_key=key)
    for item in journal.get("source_snapshot") or []:
        if not isinstance(item, dict):
            return _blocked("contextual_permission_initialization_journal_invalid")
        ref = item.get("ref")
        expected = item.get("sha256")
        if not isinstance(ref, str) or not isinstance(expected, str):
            return _blocked("contextual_permission_initialization_journal_invalid")
        try:
            actual = _file_sha256(_resolve_ref(root, ref))
        except (OSError, ValueError, FileNotFoundError) as exc:
            return _blocked("contextual_permission_initialization_source_missing", error=str(exc))
        if actual != expected:
            return _blocked("contextual_permission_initialization_source_stale", ref=ref)
    return None


def _apply_journal(root: Path, project: dict[str, Any], journal: dict[str, Any]) -> dict[str, Any]:
    blocked = _validate_journal_sources(root, project, journal)
    if blocked is not None:
        return blocked
    if any(project.get(key) for key in PROTECTED_REVIEW_KEYS):
        return _blocked("reviewed_baseline_exists_without_authoring_seed")

    written_refs: list[str] = []
    already_present_refs: list[str] = []
    write_plan = journal.get("write_plan")
    if not isinstance(write_plan, list):
        return _blocked("contextual_permission_initialization_journal_invalid")
    conflicts = []
    for item in write_plan:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            return _blocked("contextual_permission_initialization_journal_invalid")
        target = _resolve_ref(root, str(item["ref"]), required=False)
        payload = item.get("payload")
        mode = str(item.get("mode") or "create")
        if mode not in {"create", "replace"}:
            return _blocked("contextual_permission_initialization_journal_invalid")
        if mode == "create" and target.is_file() and target.read_bytes() != _canonical_json_bytes(payload):
            conflicts.append(str(item["ref"]))
    if conflicts:
        return _blocked(
            "existing_contextual_permission_artifact_conflict",
            conflicting_refs=conflicts,
        )

    try:
        for item in write_plan:
            ref = str(item["ref"])
            target = _resolve_ref(root, ref, required=False)
            if str(item.get("mode") or "create") == "replace":
                if _replace_json_if_changed(target, item["payload"]):
                    written_refs.append(ref)
                else:
                    already_present_refs.append(ref)
                continue
            result = _write_new_json(target, item["payload"])
            (written_refs if result == "written" else already_present_refs).append(ref)
    except FileExistsError as exc:
        return _blocked(
            "existing_contextual_permission_artifact_conflict",
            error=str(exc),
            written_refs=written_refs,
            already_present_refs=already_present_refs,
        )

    current_project_obj = _read_json(root / "project.json")
    if not isinstance(current_project_obj, dict):
        return _blocked("project_manifest_invalid")
    project_updates = dict(journal.get("project_updates") or {})
    refresh_unreviewed = bool(journal.get("refresh_unreviewed"))
    for key, value in project_updates.items():
        current = current_project_obj.get(key)
        if key.startswith("contextual_permission_") and current not in {None, value}:
            if not refresh_unreviewed:
                return _blocked("contextual_permission_project_update_conflict", ref_key=key)
        if key == "planned_eta_ref" and current not in {None, value}:
            return _blocked("contextual_permission_project_update_conflict", ref_key=key)
    updated_project = {**current_project_obj, **project_updates}
    if _replace_json_if_changed(root / "project.json", updated_project):
        written_refs.append("project.json")
    else:
        already_present_refs.append("project.json")

    status = _validate_existing(root, updated_project)
    if isinstance(status, dict) or status is None:
        return status or _blocked("contextual_permission_seed_missing_after_recovery")
    seed, candidate_ref, candidate_sha, rules_ref = status
    return {
        "status": "initialized",
        "authoring_ready": True,
        "projection_ready": False,
        "project_id": seed.project_id,
        "seed_ref": SEED_REF,
        "baseline_candidate_ref": candidate_ref,
        "baseline_candidate_sha256": candidate_sha,
        "contextual_permission_rules_ref": rules_ref,
        "reviewed": seed.baseline.accepted_by_human,
        "runtime_safety_truth": seed.baseline.runtime_safety_truth,
        "departure_approval_granted": seed.baseline.departure_approval_granted,
        "mission_day_ids": sorted({node.mission_day_id for node in seed.remaining_plan}),
        "source_reports": journal.get("source_snapshot") or [],
        "written_refs": written_refs,
        "already_present_refs": already_present_refs,
        "root_causes": [],
        "writes_performed": bool(written_refs),
        "recovered_from_journal": bool(already_present_refs),
    }


def _can_refresh_unreviewed(root: Path, project: dict[str, Any], status: dict[str, Any]) -> bool:
    if status.get("root_causes") not in (
        ["contextual_permission_seed_source_hash_mismatch"],
        ["contextual_permission_initialization_source_stale"],
    ):
        return False
    if any(project.get(key) for key in PROTECTED_REVIEW_KEYS):
        return False
    try:
        seed = ContextualPermissionWorkbenchSeed.model_validate(
            _read_json(_resolve_ref(root, SEED_REF))
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, FileNotFoundError):
        return False
    stale_ref = status.get("ref")
    if stale_ref:
        stale_sources = [
            source
            for source in seed.evidence
            if source.source_ref == stale_ref
        ]
        if any(source.source_kind == "golden_route_reference" for source in stale_sources):
            return False
    return (
        seed.baseline.accepted_by_human is False
        and seed.baseline.candidate_only is True
        and seed.baseline.runtime_safety_truth is False
        and seed.baseline.departure_approval_granted is False
    )


def ensure_contextual_permission_authoring(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    project_path = root / "project.json"
    if not project_path.is_file():
        return _blocked("project_manifest_missing")
    try:
        project_obj = _read_json(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        return _blocked("project_manifest_invalid", error=str(exc))
    if not isinstance(project_obj, dict):
        return _blocked("project_manifest_invalid")
    project = dict(project_obj)

    journal = _load_journal(root)
    if isinstance(journal, dict) and journal.get("status") == "blocked":
        return journal

    existing = _validate_existing(root, project)
    if existing is not None and not isinstance(existing, dict):
        seed, candidate_ref, candidate_sha, rules_ref = existing
        return _already_initialized(root, seed, candidate_ref, candidate_sha, rules_ref)
    if any(project.get(key) for key in PROTECTED_REVIEW_KEYS):
        return _blocked("reviewed_baseline_exists_without_authoring_seed")
    if isinstance(existing, dict) and _can_refresh_unreviewed(root, project, existing):
        journal = _make_journal(root, project, refresh_unreviewed=True)
        if isinstance(journal, dict) and journal.get("status") == "blocked":
            return journal
        _replace_json_if_changed(_resolve_ref(root, JOURNAL_REF, required=False), journal)
        return _apply_journal(root, project, journal)
    if isinstance(journal, dict):
        return _apply_journal(root, project, journal)
    if isinstance(existing, dict):
        return existing

    journal = _make_journal(root, project)
    if isinstance(journal, dict) and journal.get("status") == "blocked":
        return journal
    _write_new_json(_resolve_ref(root, JOURNAL_REF, required=False), journal)
    return _apply_journal(root, project, journal)
