from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scout_contextual_permission_tool import (
    OutdoorAction,
    assess_scout_contextual_permission,
)


CONTEXTUAL_PERMISSION_COLLECTION_ARTIFACT_KIND = (
    "pretrip_contextual_permission_collection"
)
CONTEXTUAL_PERMISSION_MODEL_ARTIFACT_KIND = "pretrip_contextual_permission_model"
CONTEXTUAL_PERMISSION_RULES_ARTIFACT_KIND = "pretrip_contextual_permission_rules"
CONTEXTUAL_PERMISSION_SCHEMA_VERSION = "contextual_permission_collection.v1"

CONTEXTUAL_PERMISSION_MODEL_REF = "normalized/permissions/contextual_permission_model.json"
CONTEXTUAL_PERMISSION_RULES_REF = "candidates/contextual_permission_rules.json"


SEC8_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "sections": [
        "Sec. 8 Contextual Permissioning / Courage as Permission",
        "Sec. 16 field decision output",
        "Sec. 17 ContextualPermission schema",
        "Sec. 23 acceptance criteria",
    ],
    "workspace_layout_refs": [
        CONTEXTUAL_PERMISSION_MODEL_REF,
        CONTEXTUAL_PERMISSION_RULES_REF,
        "outputs/compiled_mission_graph.*.json",
        "runtime/sessions/{session_id}/contextual_permission_events.jsonl",
    ],
}


def collect_pretrip_contextual_permission(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    current_time: str | None = None,
    current_cp_id: str | None = None,
    next_cp_id: str | None = None,
    communication_status: str | None = None,
    equipment_status: str | None = None,
    remaining_safety_buffer_minutes: float | int | str | None = None,
    requested_duration_minutes: float | int | str | None = None,
    current_delay_minutes: float | int | str | None = None,
    next_segment_uncertainty_minutes: float | int | str | None = None,
    weather_reserve_minutes: float | int | str | None = None,
    daylight_reserve_minutes: float | int | str | None = None,
    retreat_reserve_minutes: float | int | str | None = None,
    slowest_member_reserve_minutes: float | int | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Materialize Sec. 8 contextual permission candidates for a pretrip workspace.

    The collector is intentionally candidate-only. It runs the deterministic
    contextual permission assessor against local workspace evidence and stores
    reviewable rules; it does not authorize live actions or mutate runtime truth.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()

    model_ref = str(
        project.get("contextual_permission_model_ref")
        or CONTEXTUAL_PERMISSION_MODEL_REF
    )
    rules_ref = str(
        project.get("contextual_permission_rules_ref")
        or CONTEXTUAL_PERMISSION_RULES_REF
    )
    planned_refs = [model_ref, rules_ref]

    source_refs = _source_refs(project)
    source_report = [
        _source_report(root, source_kind=kind, ref=ref, required=required)
        for kind, ref, required in source_refs
    ]
    probe_context = _probe_context(
        root,
        project,
        current_time=current_time,
        current_cp_id=current_cp_id,
        next_cp_id=next_cp_id,
        communication_status=communication_status,
        equipment_status=equipment_status,
        planned_eta_ref=_ref_for(source_refs, "planned_eta"),
        generated_at=collected_at,
    )
    rules = _rules_from_assessor(
        root,
        source_refs=source_refs,
        probe_context=probe_context,
        remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
        requested_duration_minutes=requested_duration_minutes,
        current_delay_minutes=current_delay_minutes,
        next_segment_uncertainty_minutes=next_segment_uncertainty_minutes,
        weather_reserve_minutes=weather_reserve_minutes,
        daylight_reserve_minutes=daylight_reserve_minutes,
        retreat_reserve_minutes=retreat_reserve_minutes,
        slowest_member_reserve_minutes=slowest_member_reserve_minutes,
    )
    counts = _counts(rules)
    boundary = _closed_boundary(workspace_file_mutation_allowed=not dry_run)
    reviewed_baseline_ref = project.get("reviewed_mission_baseline_ref")
    reviewed_baseline_sha256 = project.get("reviewed_mission_baseline_sha256")
    baseline_binding_state = (
        "bound"
        if isinstance(reviewed_baseline_ref, str)
        and reviewed_baseline_ref
        and isinstance(reviewed_baseline_sha256, str)
        and len(reviewed_baseline_sha256) == 64
        else "missing_reviewed_baseline"
    )

    model_payload = _model_payload(
        project_id=project_id,
        generated_at=collected_at,
        source_report=source_report,
        rules_ref=rules_ref,
        boundary=boundary,
    )
    rules_payload = {
        "artifact_kind": CONTEXTUAL_PERMISSION_RULES_ARTIFACT_KIND,
        "schema_version": CONTEXTUAL_PERMISSION_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "contextual_permission_model_ref": model_ref,
        "source_report": source_report,
        "probe_context": probe_context,
        "counts": counts,
        "rules": rules,
        "reviewed_baseline_ref": reviewed_baseline_ref,
        "reviewed_baseline_sha256": reviewed_baseline_sha256,
        "reviewed_baseline_binding_state": baseline_binding_state,
        "reviewed_by_human": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "standard_alignment": SEC8_ALIGNMENT,
        "boundary": boundary,
    }
    collection_payload = {
        "artifact_kind": CONTEXTUAL_PERMISSION_COLLECTION_ARTIFACT_KIND,
        "schema_version": CONTEXTUAL_PERMISSION_SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": planned_refs,
        "outputs": {
            "contextual_permission_model_ref": model_ref,
            "contextual_permission_rules_ref": rules_ref,
        },
        "rule_count": counts["rule_count"],
        "bounded_permission_count": counts["bounded_permission_count"],
        "source_report": source_report,
        "standard_alignment": SEC8_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / model_ref, model_payload)
        _write_json(root / rules_ref, rules_payload)
        _update_project_refs(
            project_path,
            project,
            {
                "contextual_permission_model_ref": model_ref,
                "contextual_permission_rules_ref": rules_ref,
                "contextual_permission_rule_count": counts["rule_count"],
                "contextual_permission_bounded_rule_count": counts[
                    "bounded_permission_count"
                ],
                "contextual_permission_collection_updated_at": collected_at,
                "contextual_permission_collection_schema_version": (
                    CONTEXTUAL_PERMISSION_SCHEMA_VERSION
                ),
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_refs

    return collection_payload


def _model_payload(
    *,
    project_id: str,
    generated_at: str,
    source_report: list[dict[str, Any]],
    rules_ref: str,
    boundary: dict[str, Any],
) -> dict[str, Any]:
    input_signals = [
        "current_position_or_cp",
        "current_time",
        "checkpoint_progress",
        "plan_vs_actual_delta",
        "pace_and_slowest_member",
        "next_segment_difficulty",
        "retreat_point",
        "weather_window",
        "sunset_or_daylight_window",
        "terrain_risk_level",
        "communication_status",
        "equipment_status",
        "available_buffer",
        "requested_action_purpose",
        "requested_action_risk",
    ]
    return {
        "artifact_kind": CONTEXTUAL_PERMISSION_MODEL_ARTIFACT_KIND,
        "schema_version": CONTEXTUAL_PERMISSION_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": generated_at,
        "decision_object_schema": "ContextualPermission",
        "supported_actions": [action.value for action in OutdoorAction],
        "input_signals": input_signals,
        "input_signal_count": len(input_signals),
        "rules_ref": rules_ref,
        "source_report": source_report,
        "budget_policy": {
            "formula": (
                "authorized_duration = remaining_safety_buffer - "
                "next_segment_uncertainty - weather_reserve - daylight_reserve - "
                "retreat_reserve - slowest_member_reserve"
            ),
            "caller_buffer_precedence": True,
            "planned_eta_fallback_allowed": True,
            "workspace_reserves_are_candidate_only": True,
            "default_unreviewed_weather_reserve_minutes": 15,
            "default_unreviewed_segment_policy_reserve_minutes": 10,
            "default_unreviewed_daylight_reserve_minutes": 60,
        },
        "field_output_contract": {
            "first_layer": ["decision", "limit", "reason", "nextStep"],
            "second_layer": [
                "details",
                "uncertaintyNotes",
                "residualRisk",
                "requiredConditions",
                "alternativeActions",
            ],
            "decision_phrases": [
                "可以，但最多 X 分鐘，HH:MM 前必須離開",
                "不建議；請先前往下一個安全點再重新評估",
                "必須撤退或升級處理",
            ],
        },
        "standard_alignment": SEC8_ALIGNMENT,
        "boundary": boundary,
    }


def _rules_from_assessor(
    root: Path,
    *,
    source_refs: list[tuple[str, str, bool]],
    probe_context: dict[str, Any],
    remaining_safety_buffer_minutes: float | int | str | None,
    requested_duration_minutes: float | int | str | None,
    current_delay_minutes: float | int | str | None,
    next_segment_uncertainty_minutes: float | int | str | None,
    weather_reserve_minutes: float | int | str | None,
    daylight_reserve_minutes: float | int | str | None,
    retreat_reserve_minutes: float | int | str | None,
    slowest_member_reserve_minutes: float | int | str | None,
) -> list[dict[str, Any]]:
    budget_kwargs = _budget_kwargs(
        remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
        requested_duration_minutes=requested_duration_minutes,
        current_delay_minutes=current_delay_minutes,
        next_segment_uncertainty_minutes=next_segment_uncertainty_minutes,
        weather_reserve_minutes=weather_reserve_minutes,
        daylight_reserve_minutes=daylight_reserve_minutes,
        retreat_reserve_minutes=retreat_reserve_minutes,
        slowest_member_reserve_minutes=slowest_member_reserve_minutes,
    )
    common_kwargs: dict[str, Any] = {
        "current_time": probe_context["current_time"],
        "current_cp_id": probe_context.get("current_cp_id"),
        "next_cp_id": probe_context.get("next_cp_id"),
        "communication_status": probe_context.get("communication_status"),
        "equipment_status": probe_context.get("equipment_status"),
        "planned_eta_path": _ref_for(source_refs, "planned_eta"),
        "weather_daylight_evidence_path": _ref_for(
            source_refs,
            "weather_daylight_evidence",
        ),
        "plan_validation_path": _ref_for(source_refs, "plan_validation_candidates"),
        "energy_vitals_path": _ref_for(source_refs, "energy_vitals"),
        "team_status_path": _ref_for(source_refs, "team_status"),
        **budget_kwargs,
    }
    probe_specs = [
        {
            "rule_id": "contextual_permission.film.stop_for_video",
            "action": "film",
            "query": "我可以在這裡停下來拍一段影片嗎?",
        },
        {
            "rule_id": "contextual_permission.lunch.short_lunch",
            "action": "lunch",
            "query": "可以現在吃午餐嗎?",
        },
        {
            "rule_id": "contextual_permission.summit.turnaround",
            "action": "summit",
            "query": "還能攻頂嗎?",
        },
        {
            "rule_id": "contextual_permission.wait.weather_or_team",
            "action": "wait",
            "query": "可以在這裡等隊友或等天氣嗎?",
        },
        {
            "rule_id": "contextual_permission.cross_stream.high_risk",
            "action": "cross_stream",
            "query": "這裡溪水暴漲，可以過溪嗎?",
            "overrides": {
                "remaining_safety_buffer_minutes": max(
                    50.0,
                    _float_or_none(remaining_safety_buffer_minutes) or 0.0,
                ),
                "terrain_risk_level": "critical",
                "communication_status": "weak",
                "equipment_status": "unknown",
            },
        },
    ]

    rules = []
    for spec in probe_specs:
        kwargs = dict(common_kwargs)
        kwargs.update(spec.get("overrides") or {})
        result = assess_scout_contextual_permission(
            root,
            query=str(spec["query"]),
            action=str(spec["action"]),
            **{key: value for key, value in kwargs.items() if value is not None},
        )
        rules.append(_rule_from_assessment(spec, result, source_refs))
    return rules


def _rule_from_assessment(
    spec: dict[str, Any],
    result: dict[str, Any],
    source_refs: list[tuple[str, str, bool]],
) -> dict[str, Any]:
    decision_object = (
        result.get("decision_object")
        if isinstance(result.get("decision_object"), dict)
        else {}
    )
    return {
        "rule_id": spec["rule_id"],
        "query": spec["query"],
        "action": result.get("action") or spec["action"],
        "decision": result.get("decision"),
        "allowed": result.get("allowed"),
        "maxDurationMinutes": result.get("max_duration_minutes"),
        "leaveBy": result.get("leave_by"),
        "answerability": result.get("answerability"),
        "field_answer": result.get("field_answer"),
        "decision_object": decision_object,
        "mainReasons": list(decision_object.get("mainReasons") or []),
        "nextAction": decision_object.get("nextAction"),
        "cost": decision_object.get("cost"),
        "risk_budget": result.get("risk_budget") or {},
        "risk_budget_source": result.get("risk_budget_source") or {},
        "missing_fields": list(result.get("missing_fields") or []),
        "warnings": list(result.get("warnings") or []),
        "source_refs": [
            {"source_kind": kind, "source_path": ref}
            for kind, ref, _ in source_refs
            if ref
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "external_api_calls_made": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def _counts(rules: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [str(rule.get("decision") or "") for rule in rules]
    return {
        "rule_count": len(rules),
        "allowed_count": sum(1 for rule in rules if rule.get("allowed") is True),
        "bounded_permission_count": sum(
            1
            for rule in rules
            if rule.get("allowed") is True and rule.get("maxDurationMinutes") is not None
        ),
        "no_go_count": decisions.count("NO_GO"),
        "change_plan_count": decisions.count("CHANGE_PLAN"),
        "escalate_count": decisions.count("ESCALATE"),
        "missing_field_count": sum(len(rule.get("missing_fields") or []) for rule in rules),
        "actions": sorted({str(rule.get("action")) for rule in rules if rule.get("action")}),
    }


def _source_refs(project: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [
        ("planned_eta", str(project.get("planned_eta_ref") or "outputs/planned_eta.json"), True),
        (
            "weather_daylight_evidence",
            str(project.get("weather_daylight_evidence_ref") or "outputs/weather_daylight_evidence.json"),
            True,
        ),
        (
            "plan_validation_candidates",
            str(project.get("plan_validation_candidates_ref") or "outputs/plan_validation_candidates.json"),
            True,
        ),
        (
            "energy_vitals",
            str(project.get("energy_vitals_ref") or project.get("energy_vitals_snapshot_ref") or "outputs/energy_vitals.json"),
            False,
        ),
        (
            "team_status",
            str(project.get("team_status_ref") or project.get("team_pace_ref") or "outputs/team_status.json"),
            False,
        ),
        (
            "route_context_points",
            str(project.get("route_context_points_ref") or "candidates/route_context_points.json"),
            False,
        ),
        (
            "weather_decision_candidates",
            str(project.get("weather_decision_candidates_ref") or "candidates/weather_decision_candidates.json"),
            False,
        ),
    ]


def _source_report(
    root: Path,
    *,
    source_kind: str,
    ref: str,
    required: bool,
) -> dict[str, Any]:
    path = root / ref
    if not path.exists():
        return {
            "source_kind": source_kind,
            "status": "missing",
            "source_path": ref,
            "loaded_count": 0,
            "required_by_standard_sec8": required,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    payload = _load_json_value(path)
    return {
        "source_kind": source_kind,
        "status": "loaded",
        "source_path": ref,
        "loaded_count": _payload_count(payload),
        "artifact_kind": payload.get("artifact_kind") if isinstance(payload, dict) else None,
        "required_by_standard_sec8": required,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "sha256": _sha256(path),
    }


def _probe_context(
    root: Path,
    project: dict[str, Any],
    *,
    current_time: str | None,
    current_cp_id: str | None,
    next_cp_id: str | None,
    communication_status: str | None,
    equipment_status: str | None,
    planned_eta_ref: str | None,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "current_time": current_time
        or _default_probe_time(root, planned_eta_ref, generated_at=generated_at),
        "current_cp_id": current_cp_id or project.get("current_cp_id") or "current_position",
        "next_cp_id": next_cp_id or _default_next_cp_id(root, planned_eta_ref),
        "communication_status": communication_status or "ok",
        "equipment_status": equipment_status or "ok",
        "runtime_safety_truth": False,
    }


def _default_probe_time(root: Path, planned_eta_ref: str | None, *, generated_at: str) -> str:
    payload = _load_json_object(root / planned_eta_ref) if planned_eta_ref else {}
    assumption = payload.get("assumption") if isinstance(payload.get("assumption"), dict) else {}
    for candidate in (
        assumption.get("turn_back_checkpoint_eta"),
        *_eta_values(payload),
    ):
        parsed = _parse_datetime(str(candidate or ""))
        if parsed is not None:
            return (parsed - timedelta(minutes=6)).isoformat()
    return generated_at


def _default_next_cp_id(root: Path, planned_eta_ref: str | None) -> str | None:
    payload = _load_json_object(root / planned_eta_ref) if planned_eta_ref else {}
    assumption = payload.get("assumption") if isinstance(payload.get("assumption"), dict) else {}
    value = assumption.get("turn_back_checkpoint_node_name")
    if value:
        return str(value)
    estimates = payload.get("estimates")
    if isinstance(estimates, list):
        for estimate in estimates:
            if isinstance(estimate, dict) and estimate.get("to_node_name"):
                return str(estimate["to_node_name"])
    return None


def _eta_values(payload: dict[str, Any]) -> list[str]:
    estimates = payload.get("estimates")
    if not isinstance(estimates, list):
        return []
    return [
        str(estimate.get("eta"))
        for estimate in estimates
        if isinstance(estimate, dict) and estimate.get("eta")
    ]


def _budget_kwargs(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _ref_for(
    source_refs: list[tuple[str, str, bool]],
    source_kind: str,
) -> str | None:
    for kind, ref, _ in source_refs:
        if kind == source_kind:
            return ref
    return None


def _payload_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    for key in (
        "rules",
        "candidates",
        "estimates",
        "findings",
        "points",
        "members",
        "forecast_snapshots",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 1


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_json_value(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _update_project_refs(
    project_path: Path,
    project: dict[str, Any],
    updates: dict[str, Any],
) -> None:
    if not project_path.exists():
        return
    _write_json(project_path, {**project, **updates})


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _closed_boundary(
    *,
    workspace_file_mutation_allowed: bool,
) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "external_api_calls_made": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "workspace_file_mutation_allowed": workspace_file_mutation_allowed,
        "raw_payloads_embedded": False,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Scout contextual permission candidates.",
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--current-time", default=None)
    parser.add_argument("--current-cp-id", default=None)
    parser.add_argument("--next-cp-id", default=None)
    parser.add_argument("--communication-status", default=None)
    parser.add_argument("--equipment-status", default=None)
    parser.add_argument("--remaining-safety-buffer-minutes", default=None)
    parser.add_argument("--requested-duration-minutes", default=None)
    parser.add_argument("--current-delay-minutes", default=None)
    parser.add_argument("--next-segment-uncertainty-minutes", default=None)
    parser.add_argument("--weather-reserve-minutes", default=None)
    parser.add_argument("--daylight-reserve-minutes", default=None)
    parser.add_argument("--retreat-reserve-minutes", default=None)
    parser.add_argument("--slowest-member-reserve-minutes", default=None)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_contextual_permission(
        args.project_root,
        dry_run=args.dry_run,
        current_time=args.current_time,
        current_cp_id=args.current_cp_id,
        next_cp_id=args.next_cp_id,
        communication_status=args.communication_status,
        equipment_status=args.equipment_status,
        remaining_safety_buffer_minutes=args.remaining_safety_buffer_minutes,
        requested_duration_minutes=args.requested_duration_minutes,
        current_delay_minutes=args.current_delay_minutes,
        next_segment_uncertainty_minutes=args.next_segment_uncertainty_minutes,
        weather_reserve_minutes=args.weather_reserve_minutes,
        daylight_reserve_minutes=args.daylight_reserve_minutes,
        retreat_reserve_minutes=args.retreat_reserve_minutes,
        slowest_member_reserve_minutes=args.slowest_member_reserve_minutes,
        generated_at=args.generated_at,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['status']}: rules={payload.get('rule_count')} "
            f"writes={payload.get('writes_performed')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
