from __future__ import annotations

import json
from pathlib import Path
from typing import Any


POST_TRIP_REVIEW_TOOL_ID = "scout.ai.post_trip_review.assess.v0"
POST_TRIP_REVIEW_OUTPUT_KIND = "scout_ai_post_trip_review_tool_output"
POST_TRIP_REVIEW_REQUIRED_FIELDS = ("project_root",)
POST_TRIP_REVIEW_OPTIONAL_FIELDS = (
    "capability_timeline_path",
    "capability_capsule_path",
    "route_time_comparison_path",
    "share_preview_path",
    "after_action_candidates_path",
    "energy_feedback_path",
    "subjective_difficulty",
    "equipment_gaps",
    "near_miss_events",
    "incident_events",
    "weather_matched_expectation",
    "route_condition_notes",
    "route_context_updates",
    "user_feedback_items",
)


def assess_scout_post_trip_review(
    project_root: Path | str,
    *,
    query: str = "",
    capability_timeline_path: str | None = None,
    capability_capsule_path: str | None = None,
    route_time_comparison_path: str | None = None,
    share_preview_path: str | None = None,
    after_action_candidates_path: str | None = None,
    energy_feedback_path: str | None = None,
    subjective_difficulty: str | None = None,
    equipment_gaps: list[Any] | None = None,
    near_miss_events: list[Any] | None = None,
    incident_events: list[Any] | None = None,
    weather_matched_expectation: bool | str | None = None,
    route_condition_notes: list[Any] | None = None,
    route_context_updates: list[Any] | None = None,
    user_feedback_items: list[Any] | None = None,
) -> dict[str, Any]:
    """Assess post-trip review readiness without mutating learning/runtime state."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    timeline, timeline_source = _load_optional_json(
        root,
        explicit_path=capability_timeline_path,
        project=project,
        project_ref_keys=("capability_timeline_ref", "post_analysis_timeline_ref"),
        default_refs=("outputs/capability_timeline.json",),
        source_kind="capability_timeline",
        source_report=source_report,
    )
    capsule, capsule_source = _load_optional_json(
        root,
        explicit_path=capability_capsule_path,
        project=project,
        project_ref_keys=("capability_capsule_ref", "post_analysis_capsule_ref"),
        default_refs=("outputs/capability_capsule.json",),
        source_kind="capability_capsule",
        source_report=source_report,
    )
    comparison, comparison_source = _load_optional_json(
        root,
        explicit_path=route_time_comparison_path,
        project=project,
        project_ref_keys=("route_time_comparison_ref",),
        default_refs=("outputs/capability_route_time_comparison.json",),
        source_kind="route_time_comparison",
        source_report=source_report,
    )
    share_preview, share_preview_source = _load_optional_json(
        root,
        explicit_path=share_preview_path,
        project=project,
        project_ref_keys=("capability_share_preview_ref", "share_preview_ref"),
        default_refs=("outputs/capability_share_preview.json",),
        source_kind="share_preview",
        source_report=source_report,
    )
    after_action, after_action_source = _load_optional_json(
        root,
        explicit_path=after_action_candidates_path,
        project=project,
        project_ref_keys=("after_action_next_plan_candidates_ref",),
        default_refs=("outputs/after_action_next_plan_candidates.json",),
        source_kind="after_action_next_plan_candidates",
        source_report=source_report,
    )
    energy_feedback, energy_feedback_source = _load_optional_json(
        root,
        explicit_path=energy_feedback_path,
        project=project,
        project_ref_keys=("post_analysis_energy_feedback_ref",),
        default_refs=("outputs/post_analysis_energy_reserve_feedback.json",),
        source_kind="post_analysis_energy_feedback",
        source_report=source_report,
    )

    direct = {
        "subjective_difficulty": subjective_difficulty,
        "equipment_gaps": _normalized_text_list(equipment_gaps),
        "near_miss_events": _normalized_text_list(near_miss_events),
        "incident_events": _normalized_text_list(incident_events),
        "weather_matched_expectation": _bool_or_none(weather_matched_expectation),
        "route_condition_notes": _normalized_text_list(route_condition_notes),
        "route_context_updates": _normalized_text_list(route_context_updates),
        "user_feedback_items": _normalized_text_list(user_feedback_items),
    }

    completed_trip = _completed_trip_summary(
        timeline=timeline,
        capsule=capsule,
        comparison=comparison,
    )
    after_action_summary = _after_action_summary(after_action)
    feedback_summary = _feedback_summary(direct)
    model_update_candidates = _model_update_candidates(
        completed_trip=completed_trip,
        after_action_summary=after_action_summary,
        feedback_summary=feedback_summary,
        energy_feedback=energy_feedback,
    )
    missing_fields = _missing_fields(
        timeline=timeline,
        capsule=capsule,
        feedback_summary=feedback_summary,
    )
    governance = _review_governance(
        completed_trip=completed_trip,
        after_action_summary=after_action_summary,
        feedback_summary=feedback_summary,
        share_preview=share_preview,
        missing_fields=missing_fields,
    )
    decision = _decision(governance=governance, missing_fields=missing_fields)
    answerability = (
        "post_trip_review_missing_required_fields"
        if missing_fields
        else "post_trip_review_available"
    )
    field_answer = _field_answer(
        decision=decision,
        governance=governance,
        missing_fields=missing_fields,
    )

    return {
        "artifact_kind": POST_TRIP_REVIEW_OUTPUT_KIND,
        "tool_id": POST_TRIP_REVIEW_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_post_trip_review",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "post_trip_review": {
            "role": "Post-Trip Review / Learning Governance",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "learning_write_performed": False,
            "decision": decision,
            "critical_gaps": governance["critical_gaps"],
            "warning_gaps": governance["warning_gaps"],
            "required_conditions": governance["required_conditions"],
            "alternative_actions": governance["alternative_actions"],
            "next_action": governance["next_action"],
        },
        "completed_trip_summary": completed_trip,
        "post_trip_feedback": feedback_summary,
        "after_action_next_plan": after_action_summary,
        "model_update_candidates": model_update_candidates,
        "review_governance": governance,
        "privacy_share_policy": _privacy_share_policy(share_preview, capsule),
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "post-trip review decision",
                "decision": decision,
                "answerability": answerability,
                "critical_gaps": governance["critical_gaps"],
                "warning_gaps": governance["warning_gaps"],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "learning_write_performed": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 20 post-trip workflow",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 20.1 data to collect",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 20.2 model updates",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
        "debug_sources": {
            "capability_timeline_source": timeline_source,
            "capability_capsule_source": capsule_source,
            "route_time_comparison_source": comparison_source,
            "share_preview_source": share_preview_source,
            "after_action_candidates_source": after_action_source,
            "energy_feedback_source": energy_feedback_source,
        },
    }


def _completed_trip_summary(
    *,
    timeline: dict[str, Any],
    capsule: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    summary = timeline.get("summary") if isinstance(timeline.get("summary"), dict) else {}
    data_quality = (
        timeline.get("data_quality") if isinstance(timeline.get("data_quality"), dict) else {}
    )
    route_time_summary = (
        comparison.get("summary") if isinstance(comparison.get("summary"), dict) else {}
    )
    edges = timeline.get("edges") if isinstance(timeline.get("edges"), list) else []
    rest_intervals = (
        timeline.get("rest_intervals")
        if isinstance(timeline.get("rest_intervals"), list)
        else []
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "case_id": _first_text(timeline.get("case_id"), capsule.get("case_id")),
        "route_family": _first_text(timeline.get("route_family"), capsule.get("route_family")),
        "completion_status": _first_text(summary.get("completion_status")),
        "planned_segment_count": _int_or_none(summary.get("planned_segment_count")),
        "traversed_segment_count": _int_or_none(summary.get("traversed_segment_count")),
        "partial_segment_count": _int_or_none(summary.get("partial_segment_count")),
        "unreached_segment_count": _int_or_none(summary.get("unreached_segment_count")),
        "turnaround_edge_id": _first_text(summary.get("turnaround_edge_id")),
        "edge_count": len(edges),
        "observed_edge_count": sum(
            1 for edge in edges if isinstance(edge, dict) and edge.get("traversal_status") != "unreached"
        ),
        "rest_interval_count": len(rest_intervals),
        "moving_time_min": _first_int(
            capsule.get("moving_time_min"),
            _seconds_to_minutes(summary.get("moving_time_s")),
        ),
        "elapsed_time_min": _first_int(
            capsule.get("elapsed_time_min"),
            _seconds_to_minutes(summary.get("elapsed_time_s")),
        ),
        "rest_time_min": _first_int(
            capsule.get("rest_time_min"),
            _seconds_to_minutes(summary.get("rest_time_s")),
        ),
        "distance_km": _float_or_none(capsule.get("distance_km")),
        "moving_pace_min_per_km": _float_or_none(capsule.get("moving_pace_min_per_km")),
        "confidence": _first_text(capsule.get("confidence")),
        "data_quality": {
            "gps_gap_count": _int_or_none(data_quality.get("gps_gap_count")) or 0,
            "ambiguous_checkpoint_count": _int_or_none(
                data_quality.get("ambiguous_checkpoint_count")
            )
            or 0,
            "route_deviation_count": _int_or_none(data_quality.get("route_deviation_count"))
            or 0,
            "limitations": _normalized_text_list(data_quality.get("limitations")),
        },
        "route_time_comparison": {
            "comparison_count": _int_or_none(route_time_summary.get("comparison_count")) or 0,
            "slower_than_guide_count": _int_or_none(
                route_time_summary.get("slower_than_guide_count")
            )
            or 0,
            "faster_than_guide_count": _int_or_none(
                route_time_summary.get("faster_than_guide_count")
            )
            or 0,
            "informational_only": bool(route_time_summary.get("informational_only")),
        },
    }


def _after_action_summary(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    review_required = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("human_review_required") is True
    ]
    titles = [
        str(item.get("title") or item.get("candidate_id"))
        for item in candidates
        if isinstance(item, dict) and (item.get("title") or item.get("candidate_id"))
    ]
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "available": bool(payload),
        "candidate_count": len(candidates),
        "human_review_required_count": len(review_required),
        "top_candidates": titles[:5],
    }


def _feedback_summary(direct: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "subjective_difficulty": _first_text(direct.get("subjective_difficulty")),
        "equipment_gaps": direct["equipment_gaps"],
        "near_miss_events": direct["near_miss_events"],
        "incident_events": direct["incident_events"],
        "weather_matched_expectation": direct["weather_matched_expectation"],
        "route_condition_notes": direct["route_condition_notes"],
        "route_context_updates": direct["route_context_updates"],
        "user_feedback_items": direct["user_feedback_items"],
    }


def _model_update_candidates(
    *,
    completed_trip: dict[str, Any],
    after_action_summary: dict[str, Any],
    feedback_summary: dict[str, Any],
    energy_feedback: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if completed_trip.get("moving_pace_min_per_km") is not None:
        candidates.append(
            _update_candidate(
                "user_scout_pace_coefficient",
                "Use completed moving pace as reviewed input to user pace calibration.",
                "blocked_until_human_review",
            )
        )
    if completed_trip.get("observed_edge_count"):
        candidates.append(
            _update_candidate(
                "route_cp_elapsed_time",
                "Use observed CP/segment elapsed and moving time for future route timing.",
                "blocked_until_human_review",
            )
        )
    if completed_trip.get("rest_interval_count"):
        candidates.append(
            _update_candidate(
                "rest_stop_safety_and_duration",
                "Review actual rest intervals before changing rest-stop assumptions.",
                "blocked_until_human_review",
            )
        )
    if after_action_summary.get("candidate_count"):
        candidates.append(
            _update_candidate(
                "next_pretrip_after_action_candidates",
                "Carry reviewed after-action candidates into next pretrip planning.",
                "blocked_until_human_review",
            )
        )
    if feedback_summary["route_context_updates"]:
        candidates.append(
            _update_candidate(
                "route_context_intelligence",
                "Review user-noted natural, cultural, or historical context additions.",
                "blocked_until_human_review",
            )
        )
    if _actionable_items(feedback_summary["equipment_gaps"]):
        candidates.append(
            _update_candidate(
                "equipment_resource_readiness",
                "Update equipment checklist only after review of reported gaps.",
                "blocked_until_human_review",
            )
        )
    if energy_feedback:
        candidates.append(
            _update_candidate(
                "energy_reserve_model",
                "Compare pretrip projection with post-analysis energy feedback.",
                "blocked_until_human_review",
            )
        )
    return candidates


def _update_candidate(kind: str, summary: str, review_state: str) -> dict[str, Any]:
    return {
        "update_kind": kind,
        "summary": summary,
        "review_state": review_state,
        "observed_fact_writeback_allowed": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _missing_fields(
    *,
    timeline: dict[str, Any],
    capsule: dict[str, Any],
    feedback_summary: dict[str, Any],
) -> list[str]:
    missing = []
    if not timeline:
        missing.append("completed_trip_timeline")
    if not capsule:
        missing.append("capability_capsule")
    if not feedback_summary.get("subjective_difficulty"):
        missing.append("subjective_difficulty")
    if not feedback_summary.get("user_feedback_items"):
        missing.append("user_decision_feedback")
    if not feedback_summary.get("equipment_gaps"):
        missing.append("equipment_gap_review")
    if feedback_summary.get("weather_matched_expectation") is None:
        missing.append("weather_and_route_condition_feedback")
    if not feedback_summary.get("near_miss_events") and not feedback_summary.get(
        "incident_events"
    ):
        missing.append("near_miss_incident_review")
    return missing


def _review_governance(
    *,
    completed_trip: dict[str, Any],
    after_action_summary: dict[str, Any],
    feedback_summary: dict[str, Any],
    share_preview: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    critical_gaps: list[str] = []
    warning_gaps: list[str] = []
    required_conditions: list[str] = []
    alternative_actions: list[str] = []
    incident_events = _actionable_items(feedback_summary["incident_events"])
    near_miss_events = _actionable_items(feedback_summary["near_miss_events"])
    equipment_gaps = _actionable_items(feedback_summary["equipment_gaps"])

    if incident_events:
        critical_gaps.append("行後回顧包含 incident events，必須人工事故回顧。")
        required_conditions.append("先建立人工 review record，再考慮任何模型更新。")
    if near_miss_events:
        warning_gaps.append("有 near miss 回報，下一次規劃需降低風險預算。")
        required_conditions.append("將 near miss 對應到 CP/segment 後再更新路線模型。")
    if completed_trip.get("completion_status") == "partial":
        warning_gaps.append("完成軌跡顯示行程未完整完成或有折返。")
        required_conditions.append("標記 turnaround edge，下一次行前先調整路線或時間。")
        alternative_actions.append("下一次採短版、提早出發或降低目標 CP。")
    limitations = completed_trip.get("data_quality", {}).get("limitations", [])
    if limitations:
        warning_gaps.append("能力時間線有資料品質限制。")
        required_conditions.append("人工確認 GPS gap、ambiguous checkpoint 或 timestamp 限制。")
    if after_action_summary.get("human_review_required_count"):
        warning_gaps.append("after-action next-plan candidates 仍需人工審核。")
        required_conditions.append("審核候選後才能進入下一次 pretrip 或 MissionGraph。")
    if equipment_gaps:
        warning_gaps.append("有裝備缺口回報，下一次出發前需修正裝備清單。")
        alternative_actions.append("把裝備缺口加入下一次 departure gate。")
    if share_preview.get("export_requires_confirmation") is True:
        required_conditions.append("分享能力摘要前必須取得明確確認。")
    if missing_fields:
        required_conditions.extend(f"Provide {field}." for field in missing_fields)

    return {
        "critical_gaps": _dedupe(critical_gaps),
        "warning_gaps": _dedupe(warning_gaps)[:6],
        "required_conditions": _dedupe(required_conditions),
        "alternative_actions": _dedupe(alternative_actions)
        or ["保留候選更新，不寫入使用者/路線模型。", "補齊回饋後再做下一次 pretrip。"],
        "next_action": _next_action(
            critical_gaps=critical_gaps,
            warning_gaps=warning_gaps,
            missing_fields=missing_fields,
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "learning_write_performed": False,
        "mission_graph_rewrite_performed": False,
        "incident_package_rewrite_performed": False,
    }


def _decision(*, governance: dict[str, Any], missing_fields: list[str]) -> str:
    if governance["critical_gaps"]:
        return "ESCALATE"
    if missing_fields:
        return "DELAY"
    if any("未完整完成" in gap or "near miss" in gap for gap in governance["warning_gaps"]):
        return "CHANGE_PLAN"
    if governance["warning_gaps"] or governance["required_conditions"]:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    governance: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if missing_fields and not governance["critical_gaps"]:
        return (
            "行後回顧：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "；Scout 不能在缺少主觀回饋、near miss/incident、裝備或天氣路況回饋時直接更新模型。"
        )
    reasons = governance["critical_gaps"] or governance["warning_gaps"] or ["行後資料可進入人工審核。"]
    return (
        f"行後回顧：建議 {decision}。"
        f"{'；'.join(reasons[:2])} "
        f"下一步：{governance['next_action']} "
        "此為 post-analysis candidate-only 判斷，不會寫回使用者模型、路線模型、MissionGraph、incident package、Phase 1 runtime、/safety 或 Phase 2 Brain。"
    )


def _next_action(
    *,
    critical_gaps: list[str],
    warning_gaps: list[str],
    missing_fields: list[str],
) -> str:
    if critical_gaps:
        return "先做人工事故/near miss 回顧，不執行自動學習寫回。"
    if missing_fields:
        return "補齊實際感受、裝備缺口、天氣路況符合度與 near miss/incident 回饋。"
    if warning_gaps:
        return "將候選更新排入人工審核，下一次 pretrip 前再採用。"
    return "把候選更新交給人工 review，通過後才進入下一次 pretrip baseline。"


def _privacy_share_policy(share_preview: dict[str, Any], capsule: dict[str, Any]) -> dict[str, Any]:
    excluded = (
        share_preview.get("excluded_fields")
        if isinstance(share_preview.get("excluded_fields"), dict)
        else {}
    )
    return {
        "export_requires_confirmation": bool(share_preview.get("export_requires_confirmation")),
        "raw_track_shared": bool(capsule.get("raw_track_shared")),
        "exact_timestamps_shared": bool(capsule.get("exact_timestamps_shared")),
        "incident_details_shared": bool(capsule.get("incident_details_shared")),
        "excluded_fields": {
            "raw_gpx": bool(excluded.get("raw_gpx")),
            "exact_coordinates": bool(excluded.get("exact_coordinates")),
            "exact_timestamps": bool(excluded.get("exact_timestamps")),
            "incident_package_details": bool(excluded.get("incident_package_details")),
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _load_optional_json(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_keys: tuple[str, ...],
    default_refs: tuple[str, ...],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    refs = []
    if explicit_path:
        refs.append(explicit_path)
    refs.extend(str(project[key]) for key in project_ref_keys if project.get(key))
    refs.extend(default_refs)
    for ref in refs:
        path = _project_path(root, ref)
        payload = _load_json_object(path)
        if payload:
            source_report.append(
                {
                    "source_kind": source_kind,
                    "status": "loaded",
                    "source_path": ref,
                    "loaded_count": 1,
                    "raw_payloads_embedded": False,
                }
            )
            return payload, ref
    source_report.append(
        {
            "source_kind": source_kind,
            "status": "missing",
            "source_path": None,
            "loaded_count": 0,
            "raw_payloads_embedded": False,
        }
    )
    return {}, None


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _normalized_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _actionable_items(values: list[str]) -> list[str]:
    empty_markers = {"none", "no", "n/a", "na", "無", "沒有", "無事件", "無缺口"}
    return [value for value in values if value.strip().lower() not in empty_markers]


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _seconds_to_minutes(value: Any) -> int | None:
    seconds = _float_or_none(value)
    if seconds is None:
        return None
    return int(round(seconds / 60))


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "ok", "match", "matched"}:
        return True
    if normalized in {"0", "false", "no", "n", "mismatch", "not_matched"}:
        return False
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "post_analysis_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "learning_write_performed": False,
        "mission_graph_rewrite_performed": False,
        "incident_package_rewrite_performed": False,
        "phase2_brain_write_performed": False,
    }
