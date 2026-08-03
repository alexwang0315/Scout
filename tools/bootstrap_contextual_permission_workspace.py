#!/usr/bin/env python3
"""Create a fail-closed Contextual Permission authoring bootstrap.

The bootstrap intentionally stops before itinerary acceptance. It exposes the
reference-GPX baseline editor in the Dashboard while every forward adjustment
policy remains ``review_only`` until a human reviews daily endpoints and the
remaining baseline gaps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scout_contextual_permission_workbench import (  # noqa: E402
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
    ShelterHoldProjection,
)


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
PLANNED_ETA_REF = "outputs/planned_eta.json"
BASELINE_ROOT_REF = "candidates/mission_baselines"
MODEL_REF = "normalized/permissions/contextual_permission_model.json"
RULES_REF = "candidates/contextual_permission_rules.json"
SEED_REF = "outputs/contextual_permission/workbench_seed.json"
RECEIPT_REF = "reviews/contextual_permission_bootstrap_receipt.json"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_file_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _json_file_sha256(value: object) -> str:
    return hashlib.sha256(_json_file_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fixed_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON object {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _resolve_ref(project_root: Path, ref: str, *, required: bool = True) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe project ref: {ref}")
    resolved = (project_root / candidate).resolve()
    if project_root != resolved and project_root not in resolved.parents:
        raise ValueError(f"Project ref escapes workspace: {ref}")
    if required and not resolved.is_file():
        raise ValueError(f"Required project artifact is missing: {ref}")
    return resolved


def _write_json(path: Path, payload: object, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"Refusing to replace existing artifact without --force: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json_file_bytes(payload).decode("utf-8")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        stream.write(encoded)
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _primary_gpx(project_root: Path, project: dict[str, Any]) -> tuple[str, str]:
    manifest_ref = str(project.get("source_inbox_manifest_ref") or "inbox/source_manifest.json")
    manifest = _read_object(_resolve_ref(project_root, manifest_ref))
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Source inbox manifest does not contain sources.")
    source = next(
        (
            item
            for item in sources
            if isinstance(item, dict) and item.get("role") == "golden_route_reference"
        ),
        None,
    )
    if not isinstance(source, dict):
        raise ValueError("Golden route GPX is missing from the source inbox manifest.")
    ref = str(source.get("workspace_ref") or "")
    path = _resolve_ref(project_root, ref)
    sha256 = _file_sha256(path)
    declared_sha = str(source.get("sha256") or "")
    if declared_sha and declared_sha != sha256:
        raise ValueError("Golden route GPX hash does not match the source manifest.")
    return ref, sha256


def _planned_eta(
    *,
    project_id: str,
    route_name: str,
    route_distance_m: float | None,
    timing: dict[str, Any],
    graph_ref: str,
    graph_sha: str,
    timing_ref: str,
    timing_sha: str,
    route_ref: str,
    route_sha: str,
    generated_at: str,
) -> dict[str, Any]:
    estimates: list[dict[str, Any]] = []
    missing_labels: list[str] = []
    for raw in timing.get("segments") or []:
        if not isinstance(raw, dict):
            continue
        duration = raw.get("duration_minutes")
        duration = duration if isinstance(duration, dict) else {}
        p50 = duration.get("p50")
        p75 = duration.get("p75")
        label = str(raw.get("label") or raw.get("segment_id") or "Unnamed segment")
        if p75 is None:
            missing_labels.append(label)
        estimates.append(
            {
                "segment_id": raw.get("segment_id"),
                "label": label,
                "from_node_name": raw.get("from_node_name"),
                "to_node_name": raw.get("to_node_name"),
                "p50_minutes": p50,
                "p75_minutes": p75,
                "sample_count": raw.get("sample_count", 0),
                "status": "usable_reference" if p75 is not None else "timing_gap",
            }
        )
    unresolved = [
        "D1 planned day-end target requires leader review.",
        "D1 turn-back and emergency-bivy targets require Safety / Emergency review.",
    ]
    if missing_labels:
        unresolved.append(
            f"{len(missing_labels)} of {len(estimates)} reference timing segments have no usable p75 estimate."
        )
    return {
        "artifact_kind": "pretrip_planned_eta",
        "schema_version": "plannedEta.v1",
        "project_id": project_id,
        "plan_id": f"eta.{project_id}.permission-bootstrap.v1",
        "route_name": route_name,
        "status": "needs_review",
        "generated_at": generated_at,
        "assumption": {
            "source_mode": "reference_gpx",
            "day1_target_node_name": "待確認：D1 當日預計最後位置",
            "turn_back_checkpoint_node_name": "待確認：D1 折返／後撤節點",
            "day_boundary_policy": "destination_receipt_only",
            "route_distance_m": route_distance_m,
            "calendar_time_does_not_close_mission_day": True,
        },
        "estimates": estimates,
        "unresolved_gaps": unresolved,
        "missing_timing_segments": missing_labels,
        "source_refs": [graph_ref, timing_ref, route_ref],
        "source_hashes": {
            graph_ref: graph_sha,
            timing_ref: timing_sha,
            route_ref: route_sha,
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "external_api_calls_made": False,
    }


def _baseline_candidate(
    *,
    project_id: str,
    route_name: str,
    primary_gpx_ref: str,
    primary_gpx_sha: str,
    graph_ref: str,
    graph_sha: str,
    timing_ref: str,
    timing_sha: str,
    eta_ref: str,
    eta_sha: str,
) -> tuple[str, dict[str, Any]]:
    baseline_id = f"baseline.{project_id}.permission-bootstrap"
    version_id = "version.reference-gpx.v1"
    version_ref = f"{BASELINE_ROOT_REF}/{baseline_id}/versions/{version_id}.json"
    unresolved = [
        "D1:planned_day_end_target",
        "D1:turn_back_checkpoint",
        "D1:overnight_and_day_boundary",
        "D1:emergency_bivy_candidates",
    ]
    day = {
        "mission_day_id": "D1",
        "source_text": f"{route_name} reference-GPX route axis",
        "day_kind": "on_trail",
        "ordered_place_mentions": ["Start", "待確認：D1 當日預計最後位置"],
        "resolved_targets": ["Start"],
        "resolved_target_refs": {"Start": "reviewed://mission-graph/checkpoint/cp.start"},
        "resolved_target_hashes": {"Start": _fixed_hash(f"{project_id}:cp.start")},
        "unresolved_names": unresolved,
        "operator_aliases": [],
        "coordinate_hints": [],
        "branch_candidates": [],
    }
    source_refs = [primary_gpx_ref, graph_ref, timing_ref, eta_ref]
    source_hashes = {
        primary_gpx_ref: primary_gpx_sha,
        graph_ref: graph_sha,
        timing_ref: timing_sha,
        eta_ref: eta_sha,
    }
    draft = {
        "artifact_kind": "mission_baseline_candidate",
        "schema_version": "missionBaselineCandidate.v1",
        "draft_id": "baseline-draft.reference-gpx.permission-bootstrap.v1",
        "source_mode": "reference_gpx",
        "source_sha256": primary_gpx_sha,
        "source_text": f"Reference GPX bootstrap: {primary_gpx_ref}",
        "source_refs": source_refs,
        "source_hashes": source_hashes,
        "route_axis_validation": {
            "track_order": "pass",
            "endpoint_continuity": "pass",
            "resume_gaps": "pass",
            "route_direction": "pass",
        },
        "days": [day],
        "assumptions": [
            "The GPX proves route order only; it does not define mission-day boundaries.",
            "No wall-clock date or time can close D1.",
        ],
        "conversation_refs": [],
        "base_candidate_ref": None,
        "base_candidate_sha256": None,
        "patch_sha256": None,
        "validation_state": "needs_review",
        "unresolved_gaps": unresolved,
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
        "supersedes_version_id": None,
        "request_sha256": _digest(
            {"operation": "permission_bootstrap", "project_id": project_id}
        ),
        "idempotency_key": f"permission-bootstrap-{project_id}-v1",
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
        "days": [day],
        "draft": draft,
        "unresolved_gaps": unresolved,
        "validation_state": "needs_review",
        "promotion_gates": {
            "route_critical_names_resolved": False,
            "route_axis_order_pass": True,
            "endpoint_continuity_pass": True,
            "resume_gap_pass": True,
            "route_direction_pass": True,
            "overnight_and_day_boundaries_reviewed": False,
            "graph_compilation_pass": True,
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


def _plan_nodes(
    *, project_id: str, timing_gap_count: int
) -> list[RemainingPlanNode]:
    definitions = [
        (
            "node.route-axis.D1",
            "route_axis",
            "東清路線主體（待每日切段）",
            100,
            f"{timing_gap_count} 個參考分段缺少可用 p75 ETA；完成補值前不得自動壓縮。",
        ),
        (
            "node.day-end.D1",
            "day_end_target",
            "D1 當日預計最後位置（待領隊確認）",
            100,
            "D1 planned day-end target still requires leader review.",
        ),
        (
            "node.reserve.D1",
            "weather_daylight_retreat_reserve",
            "天候／日照／後撤預留（待審核）",
            95,
            "Weather and daylight evidence is not current enough to size a reviewed reserve.",
        ),
    ]
    nodes: list[RemainingPlanNode] = []
    for node_id, kind, label, priority, gap in definitions:
        policy_ref = f"{RULES_REF}#{node_id}"
        policy_sha = _fixed_hash(f"{project_id}:{node_id}:review-only-bootstrap")
        nodes.append(
            RemainingPlanNode(
                node_id=node_id,
                action_id=kind,
                label=label,
                mission_day_id="D1",
                kind=kind,
                declared_adjustment_policy="review_only",
                adjustment_policy="review_only",
                cancellable=False,
                priority=priority,
                policy_reason=(
                    "Fail closed until the D1 baseline, endpoint, and reserve are reviewed."
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
                protected=kind != "route_axis",
                adjustment_state="review_required",
                source_rule_ref=policy_ref,
                source_rule_sha256=policy_sha,
                data_quality=[gap],
            )
        )
    return nodes


def _checklist(
    *, project_id: str, graph_ref: str, graph_sha: str, weather_ref: str, weather_sha: str
) -> DepartureChecklistProjection:
    rows = [
        DepartureChecklistRow(
            row_id="weather_threats",
            label="Weather / threats",
            source_mode="scout_auto",
            state="blocked",
            evidence_summary="Existing weather/daylight artifact is an imported placeholder, not a current forecast.",
            evidence_ref=weather_ref,
            evidence_sha256=weather_sha,
            freshness="stale",
            field_condition_differs_available=True,
            blocker="Refresh current weather evidence before departure review.",
        ),
        DepartureChecklistRow(
            row_id="route_navigation",
            label="Route / navigation",
            source_mode="scout_auto",
            state="blocked",
            evidence_summary="Reviewed route axis exists; the D1 endpoint and turn-back target do not.",
            evidence_ref=graph_ref,
            evidence_sha256=graph_sha,
            freshness="not_applicable",
            field_condition_differs_available=True,
            blocker="Review the D1 endpoint and turn-back target.",
        ),
        DepartureChecklistRow(
            row_id="team",
            label="Team",
            source_mode="leader_attestation",
            state="leader_check_required",
            evidence_summary="No team readiness assertion is included in this bootstrap.",
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
            evidence_summary="No equipment or power assertion is included in this bootstrap.",
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
        checklist_id="departure.checklist.D1.bootstrap.v1",
        checklist_sha256=_digest([row.model_dump(mode="json") for row in rows]),
        pending_day_plan_sha256=_fixed_hash(f"{project_id}:D1:pending-plan"),
        rows=rows,
        open_conflict_count=3,
        scout_suggestion_code="refresh_evidence",
        scout_suggestion="先完成 D1 終點、後撤點與六項行前檢核；目前不可確認出發。",
        scout_suggestion_suspended=False,
        can_confirm_departure=False,
        mission_day_started=False,
    )


def _seed(
    *,
    project_id: str,
    baseline_ref: str,
    baseline: dict[str, Any],
    receipt_ref: str,
    receipt_sha: str,
    rules_sha: str,
    eta_sha: str,
    graph_ref: str,
    graph_sha: str,
    timing_ref: str,
    timing_sha: str,
    weather_ref: str,
    weather_sha: str,
    timing_gap_count: int,
) -> ContextualPermissionWorkbenchSeed:
    baseline_sha = str(baseline["version_sha256"])
    target_ref = "candidate://permission/day-D1/end-unresolved"
    target_sha = _fixed_hash(f"{project_id}:D1:end-unresolved")
    membership_sha = _fixed_hash(f"{project_id}:group-main:bootstrap-membership")
    plan_nodes = _plan_nodes(project_id=project_id, timing_gap_count=timing_gap_count)
    checklist = _checklist(
        project_id=project_id,
        graph_ref=graph_ref,
        graph_sha=graph_sha,
        weather_ref=weather_ref,
        weather_sha=weather_sha,
    )
    group = MovementGroupProjection(
        group_id="group.main",
        group_label="東清主要行動群組（待確認）",
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
        mission_day_id="D1",
        mission_day_instance_id="D1.instance.bootstrap.001",
        day_end=DayEndProjection(
            planned_target_label="待確認：D1 當日預計最後位置",
            effective_target_label="待確認：D1 當日預計最後位置",
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
            next_step="先在 baseline 工作台確認 D1 終點與緊急扎營候選點。",
        ),
        pending_next_day=None,
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
            arrival_zone_ref="candidate://permission/day-D1/arrival-zone-unresolved",
            arrival_zone_sha256=_fixed_hash(f"{project_id}:D1:arrival-zone-unresolved"),
            route_progress_ref="evidence://movement/not-started",
            route_progress_sha256=_fixed_hash(f"{project_id}:movement:not-started"),
            dwell_policy_ref="reviewed://dwell-policy/default-600s",
            dwell_policy_sha256=_fixed_hash(f"{project_id}:dwell-policy:600s"),
            individual_activity_summary_ref="evidence://activity/not-started",
            individual_activity_summary_sha256=_fixed_hash(
                f"{project_id}:activity:not-started"
            ),
            target_match=False,
            gnss_confidence="unknown",
            manual_complete_available=False,
            blocked_by=["D1 day-end target has not been reviewed."],
        ),
        communication=CommunicationProjection(
            policy_id="comm-window.D1.bootstrap.v1",
            policy_sha256=_fixed_hash(f"{project_id}:communication:bootstrap"),
            state="unknown",
            membership_revision=1,
            route_scope_ref=graph_ref,
            route_scope_sha256=graph_sha,
            route_scope_label="東清已審閱路線軸；通訊區間待確認",
            viewpoint="local",
            next_check_in_target="待確認：D1 當日預計最後位置",
            baseline_window="待 baseline review",
            effective_window="待 baseline review",
            deadline_driver="Destination receipt only; wall-clock time cannot close D1.",
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
    return ContextualPermissionWorkbenchSeed(
        artifact_kind="contextual_permission_workbench_seed",
        schema_version="contextualPermissionWorkbenchSeed.v1",
        project_id=project_id,
        lens="baseline",
        replay_session_id="session.permission-bootstrap.reference-gpx.v1",
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
            source_hashes={
                "baseline_candidate_ref": _json_file_sha256(baseline),
                "planned_eta_ref": eta_sha,
                "compiled_mission_graph_reviewed_ref": graph_sha,
            },
        ),
        action_events=[],
        remaining_plan=plan_nodes,
        daily_review=DailyEmergencyReviewSession(
            session_id="daily-review.D1.bootstrap.001",
            project_id=project_id,
            mission_day_id="D1",
            mission_day_instance_id="D1.instance.bootstrap.001",
            movement_group_id="group.main",
            membership_revision=1,
            mission_day_plan_ref=baseline_ref,
            mission_day_plan_sha256=baseline_sha,
            review_generation=1,
            state="not_started",
            planned_day_end_target_ref=target_ref,
            planned_day_end_target_sha256=target_sha,
            planned_day_end_target_label="待確認：D1 當日預計最後位置",
            effective_day_end_target_ref=target_ref,
            effective_day_end_target_sha256=target_sha,
            day_end_state="day_end_at_risk",
            alternatives=[],
        ),
        movement_groups=[group],
        evidence=[
            BoundedSourceRef(
                source_id="source.reviewed-graph",
                source_kind="reviewed_mission_graph",
                source_ref=graph_ref,
                source_sha256=graph_sha,
                freshness="not_applicable",
                summary="已審閱路線節點與順序；不包含每日終點核准。",
            ),
            BoundedSourceRef(
                source_id="source.planned-eta",
                source_kind="planned_eta",
                source_ref=PLANNED_ETA_REF,
                source_sha256=eta_sha,
                freshness="unknown",
                summary="參考軌跡 ETA 骨架；缺值與每日切段仍待審核。",
            ),
            BoundedSourceRef(
                source_id="source.reference-segment-timing",
                source_kind="reference_segment_timing",
                source_ref=timing_ref,
                source_sha256=timing_sha,
                freshness="not_applicable",
                summary="歷史參考軌跡分段時間統計，僅供候選規劃。",
            ),
            BoundedSourceRef(
                source_id="source.weather-placeholder",
                source_kind="normalized_weather_fact",
                source_ref=weather_ref,
                source_sha256=weather_sha,
                freshness="stale",
                summary="匯入時的天候／日照 placeholder；不是目前天氣建議。",
            ),
        ],
    )


def bootstrap(project_root: Path, *, force: bool, dry_run: bool) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    project_path = root / "project.json"
    project = _read_object(project_path)
    project_id = str(project.get("project_id") or root.name)
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError("Project id is not safe for Contextual Permission storage.")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    graph_ref = str(project.get("compiled_mission_graph_reviewed_ref") or "")
    timing_ref = str(project.get("reference_segment_timing_ref") or "")
    route_ref = str(project.get("route_summary_ref") or "")
    weather_ref = str(project.get("weather_daylight_evidence_ref") or "")
    required_refs = [graph_ref, timing_ref, route_ref, weather_ref]
    if any(not ref for ref in required_refs):
        raise ValueError("Project is missing graph, timing, route, or weather refs.")
    graph_path = _resolve_ref(root, graph_ref)
    timing_path = _resolve_ref(root, timing_ref)
    route_path = _resolve_ref(root, route_ref)
    weather_path = _resolve_ref(root, weather_ref)
    graph_sha = _file_sha256(graph_path)
    timing_sha = _file_sha256(timing_path)
    route_sha = _file_sha256(route_path)
    weather_sha = _file_sha256(weather_path)
    timing = _read_object(timing_path)
    route = _read_object(route_path)
    primary_gpx_ref, primary_gpx_sha = _primary_gpx(root, project)

    route_name = str(project.get("route_name") or route.get("route_name") or project_id)
    distance_value = route.get("distance_m")
    route_distance_m = float(distance_value) if isinstance(distance_value, (int, float)) else None
    eta_payload = _planned_eta(
        project_id=project_id,
        route_name=route_name,
        route_distance_m=route_distance_m,
        timing=timing,
        graph_ref=graph_ref,
        graph_sha=graph_sha,
        timing_ref=timing_ref,
        timing_sha=timing_sha,
        route_ref=route_ref,
        route_sha=route_sha,
        generated_at=generated_at,
    )
    eta_sha = _json_file_sha256(eta_payload)
    baseline_ref, baseline_payload = _baseline_candidate(
        project_id=project_id,
        route_name=route_name,
        primary_gpx_ref=primary_gpx_ref,
        primary_gpx_sha=primary_gpx_sha,
        graph_ref=graph_ref,
        graph_sha=graph_sha,
        timing_ref=timing_ref,
        timing_sha=timing_sha,
        eta_ref=PLANNED_ETA_REF,
        eta_sha=eta_sha,
    )
    receipt_payload = {
        "artifact_kind": "contextual_permission_bootstrap_receipt",
        "schema_version": "contextualPermissionBootstrapReceipt.v1",
        "project_id": project_id,
        "requested_scope": "Create a Permission authoring bootstrap for Dongqing.",
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
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    receipt_sha = _json_file_sha256(receipt_payload)

    timing_gap_count = sum(
        1
        for item in eta_payload["estimates"]
        if item.get("status") == "timing_gap"
    )
    plan_nodes = _plan_nodes(project_id=project_id, timing_gap_count=timing_gap_count)
    policies = [
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
    ]
    rules = ContextualPermissionRulesArtifact(
        artifact_kind="pretrip_contextual_permission_rules",
        schema_version="contextual_permission_rules.v2",
        project_id=project_id,
        reviewed_baseline_ref=baseline_ref,
        reviewed_baseline_sha256=str(baseline_payload["version_sha256"]),
        reviewed_by_human=False,
        review_receipt_ref=RECEIPT_REF,
        review_receipt_sha256=receipt_sha,
        plan_node_policies=policies,
        candidate_only=True,
        runtime_safety_truth=False,
    )
    rules_payload = rules.model_dump(mode="json")
    rules_sha = _json_file_sha256(rules_payload)
    model_payload = {
        "artifact_kind": "pretrip_contextual_permission_model",
        "schema_version": "contextualPermissionModel.v2",
        "project_id": project_id,
        "status": "bootstrap_needs_itinerary_review",
        "source_mode": "reference_gpx",
        "baseline_candidate_ref": baseline_ref,
        "baseline_candidate_sha256": baseline_payload["version_sha256"],
        "contextual_permission_rules_ref": RULES_REF,
        "adjustment_contract": {
            "current_policy": "review_only",
            "automatic_reduction_enabled": False,
            "human_driven_causes_only_from": "Safety / Emergency trigger receipt",
            "automatic_fact_sources": ["weather", "IMU/PDR", "GNSS"],
            "scout_outputs": "candidate_advice_only",
            "day_boundary_policy": "destination_receipt_only",
        },
        "unresolved_gaps": baseline_payload["unresolved_gaps"],
        "source_refs": [graph_ref, timing_ref, PLANNED_ETA_REF, primary_gpx_ref],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
    }
    seed = _seed(
        project_id=project_id,
        baseline_ref=baseline_ref,
        baseline=baseline_payload,
        receipt_ref=RECEIPT_REF,
        receipt_sha=receipt_sha,
        rules_sha=rules_sha,
        eta_sha=eta_sha,
        graph_ref=graph_ref,
        graph_sha=graph_sha,
        timing_ref=timing_ref,
        timing_sha=timing_sha,
        weather_ref=weather_ref,
        weather_sha=weather_sha,
        timing_gap_count=timing_gap_count,
    )
    seed_payload = seed.model_dump(mode="json")
    project_updates = {
        "planned_eta_ref": PLANNED_ETA_REF,
        "contextual_permission_model_ref": MODEL_REF,
        "contextual_permission_rules_ref": RULES_REF,
        "contextual_permission_bootstrap_ref": SEED_REF,
        "contextual_permission_baseline_candidate_ref": baseline_ref,
        "contextual_permission_baseline_candidate_sha256": baseline_payload[
            "version_sha256"
        ],
        "contextual_permission_bootstrap_state": "needs_itinerary_review",
        "contextual_permission_rule_count": len(policies),
        "contextual_permission_collection_updated_at": generated_at,
        "contextual_permission_collection_schema_version": (
            "contextualPermissionWorkbenchSeed.v1"
        ),
    }
    written_refs = [
        PLANNED_ETA_REF,
        baseline_ref,
        RECEIPT_REF,
        MODEL_REF,
        RULES_REF,
        SEED_REF,
        "project.json",
    ]
    if not dry_run:
        artifact_targets = [
            _resolve_ref(root, ref, required=False)
            for ref in written_refs
            if ref != "project.json"
        ]
        baseline_target = _resolve_ref(root, baseline_ref, required=False)
        if baseline_target.exists() and force:
            raise FileExistsError(
                "--force cannot replace an immutable baseline candidate version; "
                "create a new version instead."
            )
        if not force:
            existing = [path for path in artifact_targets if path.exists()]
            if existing:
                refs = ", ".join(
                    path.relative_to(root).as_posix() for path in existing
                )
                raise FileExistsError(
                    f"Refusing to replace existing bootstrap artifacts without --force: {refs}"
                )
        _write_json(_resolve_ref(root, PLANNED_ETA_REF, required=False), eta_payload, force=force)
        _write_json(_resolve_ref(root, baseline_ref, required=False), baseline_payload, force=force)
        _write_json(_resolve_ref(root, RECEIPT_REF, required=False), receipt_payload, force=force)
        _write_json(_resolve_ref(root, MODEL_REF, required=False), model_payload, force=force)
        _write_json(_resolve_ref(root, RULES_REF, required=False), rules_payload, force=force)
        _write_json(_resolve_ref(root, SEED_REF, required=False), seed_payload, force=force)
        _write_json(project_path, {**project, **project_updates}, force=True)
    return {
        "status": "dry_run" if dry_run else "bootstrap_created",
        "project_id": project_id,
        "workspace_root": str(root),
        "written_refs": [] if dry_run else written_refs,
        "planned_refs": written_refs,
        "baseline_review_ready": False,
        "unresolved_gap_count": len(baseline_payload["unresolved_gaps"]),
        "timing_gap_count": timing_gap_count,
        "all_adjustment_policies": "review_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "external_api_calls_made": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = bootstrap(args.project_root, force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
