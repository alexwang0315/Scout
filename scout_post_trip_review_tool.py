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
    post_trip_learning_package = _post_trip_learning_package(
        completed_trip=completed_trip,
        feedback_summary=feedback_summary,
        after_action_summary=after_action_summary,
        model_update_candidates=model_update_candidates,
        governance=governance,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=decision,
        field_answer=field_answer,
        governance=governance,
        missing_fields=missing_fields,
        post_trip_learning_package=post_trip_learning_package,
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
        "decision_output": decision_output,
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
        "post_trip_learning_package": post_trip_learning_package,
        "review_governance": governance,
        "privacy_share_policy": _privacy_share_policy(share_preview, capsule),
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "post-trip review decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "critical_gaps": governance["critical_gaps"],
                "warning_gaps": governance["warning_gaps"],
                "field_answer": field_answer,
                "post_trip_learning_package": post_trip_learning_package,
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
    event_taxonomy = _post_trip_event_taxonomy(
        near_miss_events=direct["near_miss_events"],
        incident_events=direct["incident_events"],
        equipment_gaps=direct["equipment_gaps"],
        route_condition_notes=direct["route_condition_notes"],
    )
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
        "event_taxonomy": event_taxonomy,
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
    if _actionable_items(feedback_summary["route_condition_notes"]) or (
        feedback_summary.get("weather_matched_expectation") is False
    ):
        candidates.append(
            _update_candidate(
                "route_condition_risk_layer",
                "Review post-trip weather and route condition mismatches before changing risk layers.",
                "blocked_until_human_review",
            )
        )
    if completed_trip.get("moving_pace_min_per_km") is not None and feedback_summary.get(
        "subjective_difficulty"
    ):
        candidates.append(
            _update_candidate(
                "team_pace_fit_model",
                "Use subjective difficulty with actual pace only after review of party fit.",
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
    event_types = set(
        feedback_summary.get("event_taxonomy", {}).get("matched_event_types", [])
    )
    if "lost_or_navigation_uncertainty" in event_types:
        candidates.append(
            _update_candidate(
                "navigation_terrain_readiness_model",
                "Review missed junction, lost-position, or off-route event before changing navigation readiness assumptions.",
                "blocked_until_human_review",
            )
        )
    if "slip_or_fall" in event_types:
        candidates.append(
            _update_candidate(
                "terrain_risk_layer",
                "Review slip/fall evidence against terrain, wet-surface, and exposure layers before changing risk scoring.",
                "blocked_until_human_review",
            )
        )
    if "cold_or_hypothermia" in event_types:
        candidates.append(
            _update_candidate(
                "weather_cold_exposure_policy",
                "Review cold exposure or hypothermia signals before changing weather and insulation gates.",
                "blocked_until_human_review",
            )
        )
    if "team_separation" in event_types:
        candidates.append(
            _update_candidate(
                "team_status_governance",
                "Review team separation or lost-contact event before changing check-in and no-split policies.",
                "blocked_until_human_review",
            )
        )
    if "darkness_or_daylight_overrun" in event_types:
        candidates.append(
            _update_candidate(
                "daylight_turnaround_policy",
                "Review darkness or late-arrival event before tightening turnaround and daylight-buffer policy.",
                "blocked_until_human_review",
            )
        )
    if "equipment_failure" in event_types:
        candidates.append(
            _update_candidate(
                "equipment_resource_readiness",
                "Review gear failure before changing equipment checklist and departure gate requirements.",
                "blocked_until_human_review",
            )
        )
    if "medical_or_altitude_symptom" in event_types:
        candidates.append(
            _update_candidate(
                "energy_vitals_and_medical_escalation_policy",
                "Review altitude, medical, or serious-injury signals with a human reviewer before changing vitals or escalation policy.",
                "blocked_until_human_review",
            )
        )
    return _dedupe_update_candidates(candidates)


def _update_candidate(kind: str, summary: str, review_state: str) -> dict[str, Any]:
    return {
        "update_kind": kind,
        "summary": summary,
        "review_state": review_state,
        "observed_fact_writeback_allowed": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _post_trip_learning_package(
    *,
    completed_trip: dict[str, Any],
    feedback_summary: dict[str, Any],
    after_action_summary: dict[str, Any],
    model_update_candidates: list[dict[str, Any]],
    governance: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    route_time_comparison = completed_trip.get("route_time_comparison", {})
    if not isinstance(route_time_comparison, dict):
        route_time_comparison = {}
    return {
        "role": "Post-Trip Learning Proposal",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "learning_write_performed": False,
        "mission_graph_rewrite_performed": False,
        "incident_package_rewrite_performed": False,
        "phase2_brain_write_performed": False,
        "data_to_collect": {
            "actual_cp_pass_times": {
                "status": "available"
                if completed_trip.get("observed_edge_count")
                else "missing",
                "observed_edge_count": completed_trip.get("observed_edge_count") or 0,
                "planned_segment_count": completed_trip.get("planned_segment_count"),
                "traversed_segment_count": completed_trip.get("traversed_segment_count"),
                "partial_segment_count": completed_trip.get("partial_segment_count"),
                "unreached_segment_count": completed_trip.get("unreached_segment_count"),
            },
            "actual_stop_duration": {
                "status": "available"
                if completed_trip.get("rest_interval_count")
                else "missing",
                "rest_interval_count": completed_trip.get("rest_interval_count") or 0,
                "rest_time_min": completed_trip.get("rest_time_min"),
            },
            "slower_than_expected_segments": {
                "status": "available"
                if route_time_comparison.get("comparison_count")
                else "missing",
                "slower_than_guide_count": route_time_comparison.get(
                    "slower_than_guide_count"
                )
                or 0,
                "comparison_count": route_time_comparison.get("comparison_count") or 0,
            },
            "subjective_difficulty": feedback_summary.get("subjective_difficulty")
            or "missing",
            "equipment_gaps": feedback_summary.get("equipment_gaps") or [],
            "weather_route_condition_match": _feedback_value_or_missing(
                feedback_summary.get("weather_matched_expectation")
            ),
            "route_condition_notes": feedback_summary.get("route_condition_notes") or [],
            "near_miss_events": feedback_summary.get("near_miss_events") or [],
            "incident_events": feedback_summary.get("incident_events") or [],
            "event_taxonomy": feedback_summary.get("event_taxonomy") or {},
            "route_context_updates": feedback_summary.get("route_context_updates") or [],
            "user_feedback_items": feedback_summary.get("user_feedback_items") or [],
        },
        "model_update_proposals": model_update_candidates,
        "model_update_target_coverage": {
            "user_scout_pace_coefficient": _has_update_kind(
                model_update_candidates, "user_scout_pace_coefficient"
            ),
            "team_pace_fit_model": _has_update_kind(
                model_update_candidates, "team_pace_fit_model"
            ),
            "route_cp_elapsed_time": _has_update_kind(
                model_update_candidates, "route_cp_elapsed_time"
            ),
            "rest_stop_safety_and_duration": _has_update_kind(
                model_update_candidates, "rest_stop_safety_and_duration"
            ),
            "route_condition_risk_layer": _has_update_kind(
                model_update_candidates, "route_condition_risk_layer"
            ),
            "route_context_intelligence": _has_update_kind(
                model_update_candidates, "route_context_intelligence"
            ),
            "navigation_terrain_readiness_model": _has_update_kind(
                model_update_candidates, "navigation_terrain_readiness_model"
            ),
            "terrain_risk_layer": _has_update_kind(
                model_update_candidates, "terrain_risk_layer"
            ),
            "weather_cold_exposure_policy": _has_update_kind(
                model_update_candidates, "weather_cold_exposure_policy"
            ),
            "team_status_governance": _has_update_kind(
                model_update_candidates, "team_status_governance"
            ),
            "daylight_turnaround_policy": _has_update_kind(
                model_update_candidates, "daylight_turnaround_policy"
            ),
            "equipment_resource_readiness": _has_update_kind(
                model_update_candidates, "equipment_resource_readiness"
            ),
            "energy_vitals_and_medical_escalation_policy": _has_update_kind(
                model_update_candidates,
                "energy_vitals_and_medical_escalation_policy",
            ),
        },
        "review_required": {
            "missing_fields": missing_fields,
            "critical_gaps": governance["critical_gaps"],
            "warning_gaps": governance["warning_gaps"],
            "after_action_human_review_required_count": after_action_summary.get(
                "human_review_required_count"
            )
            or 0,
            "required_conditions": governance["required_conditions"],
        },
        "writeback_policy": {
            "automatic_user_model_update_allowed": False,
            "automatic_route_model_update_allowed": False,
            "automatic_team_model_update_allowed": False,
            "automatic_route_context_update_allowed": False,
            "human_review_required": True,
            "allowed_destination_after_review": "next_pretrip_baseline_candidates",
        },
        "traceability": {
            "case_id": completed_trip.get("case_id"),
            "route_family": completed_trip.get("route_family"),
            "completion_status": completed_trip.get("completion_status"),
            "confidence": completed_trip.get("confidence"),
            "data_quality": completed_trip.get("data_quality"),
        },
        "acceptance_coverage": {
            "section_20_1_data_to_collect": True,
            "section_20_1_incident_event_taxonomy": True,
            "section_20_2_model_update_targets": True,
            "section_22_reviewable_reasoning": True,
            "section_23_no_runtime_safety_truth": True,
        },
    }


def _feedback_value_or_missing(value: Any) -> Any:
    return value if value is not None else "missing"


def _post_trip_event_taxonomy(
    *,
    near_miss_events: list[str],
    incident_events: list[str],
    equipment_gaps: list[str],
    route_condition_notes: list[str],
) -> dict[str, Any]:
    classified_events: list[dict[str, Any]] = []
    for source, values in (
        ("near_miss", near_miss_events),
        ("incident", incident_events),
        ("equipment_gap", equipment_gaps),
        ("route_condition", route_condition_notes),
    ):
        for value in _actionable_items(values):
            event_types = _post_trip_event_types(value, source=source)
            if not event_types:
                continue
            classified_events.append(
                {
                    "source": source,
                    "text": value,
                    "event_types": event_types,
                    "review_state": "requires_human_review",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            )
    matched_event_types = _dedupe(
        [
            event_type
            for event in classified_events
            for event_type in event["event_types"]
        ]
    )
    by_type = {
        event_type: sum(
            1 for event in classified_events if event_type in event["event_types"]
        )
        for event_type in matched_event_types
    }
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "classification_schema": "scout_post_trip_event_taxonomy.v0",
        "event_count": len(classified_events),
        "matched_event_types": matched_event_types,
        "by_type": by_type,
        "events": classified_events[:12],
        "review_required": bool(classified_events),
    }


def _post_trip_event_types(value: str, *, source: str) -> list[str]:
    text = value.lower().replace(" ", "")
    event_types: list[str] = []

    def add(event_type: str) -> None:
        if event_type not in event_types:
            event_types.append(event_type)

    if _has_any_text(
        text,
        (
            "迷路",
            "走錯",
            "錯過岔路",
            "岔路",
            "不確定自己在哪",
            "偏離路線",
            "offroute",
            "lost",
            "wrongturn",
        ),
    ):
        add("lost_or_navigation_uncertainty")
    if _has_any_text(
        text,
        ("滑倒", "跌倒", "摔倒", "滑墜", "墜落", "slip", "fall"),
    ):
        add("slip_or_fall")
    if _has_any_text(
        text,
        (
            "失溫",
            "低溫",
            "濕冷",
            "冷到",
            "濕衣",
            "hypothermia",
            "coldexposure",
        ),
    ):
        add("cold_or_hypothermia")
    if _has_any_text(
        text,
        (
            "脫隊",
            "走散",
            "分隊",
            "快慢組",
            "失聯",
            "後隊",
            "teamseparation",
            "splitteam",
            "lostcontact",
        ),
    ):
        add("team_separation")
    if _has_any_text(
        text,
        ("摸黑", "天黑", "日落", "夜間", "頭燈前", "dark", "nightfall"),
    ):
        add("darkness_or_daylight_overrun")
    if source == "equipment_gap" or _has_any_text(
        text,
        (
            "裝備失效",
            "失效",
            "故障",
            "壞掉",
            "沒電",
            "電量不足",
            "不足",
            "缺",
            "頭燈",
            "雨衣",
            "手套",
            "gearfailure",
            "equipmentfailure",
            "batterydead",
        ),
    ):
        add("equipment_failure")
    if _has_any_text(text, ("高山症", "氣喘", "低血糖", "重大傷病", "ams")):
        add("medical_or_altitude_symptom")
    return event_types


def _has_update_kind(candidates: list[dict[str, Any]], update_kind: str) -> bool:
    return any(candidate.get("update_kind") == update_kind for candidate in candidates)


def _dedupe_update_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for candidate in candidates:
        key = candidate.get("update_kind")
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _decision_output(
    *,
    decision: str,
    field_answer: str,
    governance: dict[str, Any],
    missing_fields: list[str],
    post_trip_learning_package: dict[str, Any],
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(governance=governance, missing_fields=missing_fields)
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    required_conditions = governance["required_conditions"]
    alternatives = governance["alternative_actions"]
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": governance["next_action"],
    }
    second_layer = {
        "details": _decision_details(
            post_trip_learning_package=post_trip_learning_package,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Post-trip learning evidence is candidate-only.",
            "Human review is required before any model, MissionGraph, or route context update.",
            "No runtime safety truth was created.",
        ],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
    }
    return {
        "role": "Micro-Decision Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": second_layer,
        "action": "post_trip_learning_review",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "modelWritebackImpact": "No automatic model writeback is allowed.",
            "nextPretripImpact": "Reviewed candidates may seed the next pretrip baseline.",
            "incidentReviewImpact": "Incident or near-miss signals must remain review-gated.",
        },
        "nextAction": governance["next_action"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 20 post-trip workflow",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *, governance: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    reasons = []
    reasons.extend(governance["critical_gaps"])
    reasons.extend(governance["warning_gaps"])
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("行後資料可形成候選學習提案，但仍需人工審核。")
    return _dedupe(reasons)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "ESCALATE":
        return "先升級人工事故回顧。"
    if decision == "DELAY":
        return "暫緩學習寫回。"
    if decision == "CHANGE_PLAN":
        return "下一次規劃需調整。"
    if decision == "CONDITIONAL_GO":
        return "可有條件送人工學習審核。"
    if decision == "GO" and allowed:
        return "可送人工學習審核。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str) -> str:
    base = (
        "不得自動寫回使用者模型、隊伍模型、路線模型、MissionGraph、"
        "incident package、Phase 1 runtime、/safety 或 Phase 2 Brain。"
    )
    if decision == "ESCALATE":
        return "事故或 near miss 未完成人工回顧前，" + base
    return base


def _decision_details(
    *,
    post_trip_learning_package: dict[str, Any],
    field_answer: str,
) -> list[str]:
    coverage = post_trip_learning_package.get("model_update_target_coverage", {})
    if not isinstance(coverage, dict):
        coverage = {}
    enabled_targets = [
        name for name, available in coverage.items() if available
    ]
    data_to_collect = post_trip_learning_package.get("data_to_collect", {})
    details = [field_answer]
    if enabled_targets:
        details.append("候選更新目標：" + "、".join(enabled_targets))
    if isinstance(data_to_collect, dict):
        cp_data = data_to_collect.get("actual_cp_pass_times", {})
        stop_data = data_to_collect.get("actual_stop_duration", {})
        if isinstance(cp_data, dict):
            details.append(
                "實際 CP/segment 資料："
                f"{cp_data.get('status')}，observed_edge_count="
                f"{cp_data.get('observed_edge_count')}"
            )
        if isinstance(stop_data, dict):
            details.append(
                "實際停留資料："
                f"{stop_data.get('status')}，rest_interval_count="
                f"{stop_data.get('rest_interval_count')}"
            )
    return details


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
    event_taxonomy = feedback_summary.get("event_taxonomy", {})
    event_types = (
        set(event_taxonomy.get("matched_event_types", []))
        if isinstance(event_taxonomy, dict)
        else set()
    )

    if incident_events:
        critical_gaps.append("行後回顧包含 incident events，必須人工事故回顧。")
        required_conditions.append("先建立人工 review record，再考慮任何模型更新。")
    if near_miss_events:
        warning_gaps.append("有 near miss 回報，下一次規劃需降低風險預算。")
        required_conditions.append("將 near miss 對應到 CP/segment 後再更新路線模型。")
    if "lost_or_navigation_uncertainty" in event_types:
        warning_gaps.append("事件分類包含迷路、錯過岔路或導航不確定。")
        required_conditions.append("回顧離線地圖、GPX、岔路點與撤退方向後再更新地圖力模型。")
    if "slip_or_fall" in event_types:
        warning_gaps.append("事件分類包含滑倒、跌倒或滑墜風險。")
        required_conditions.append("將事件對到地形/天候/路面條件後再更新風險圖層。")
    if "cold_or_hypothermia" in event_types:
        warning_gaps.append("事件分類包含失溫、低溫或濕冷暴露。")
        required_conditions.append("回顧保暖裝備、天氣窗口與營地/停留政策後再更新模型。")
    if "team_separation" in event_types:
        warning_gaps.append("事件分類包含脫隊、快慢組分裂或失聯。")
        required_conditions.append("回顧隊伍 check-in、no-split 與留守策略後再更新隊伍模型。")
    if "darkness_or_daylight_overrun" in event_types:
        warning_gaps.append("事件分類包含摸黑或日照 buffer 失守。")
        required_conditions.append("回顧折返時間、最晚通過 CP 與頭燈電量後再更新 daylight policy。")
    if "equipment_failure" in event_types:
        warning_gaps.append("事件分類包含裝備失效、缺件或電量不足。")
        required_conditions.append("回顧裝備清單與 departure gate 後再更新資源模型。")
    if "medical_or_altitude_symptom" in event_types:
        warning_gaps.append("事件分類包含高山症、醫療或重大傷病訊號。")
        required_conditions.append("人工醫療/領隊回顧完成前，不更新 vitals 或 escalation policy。")
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


def _has_any_text(value: str, fragments: tuple[str, ...]) -> bool:
    normalized = value.lower().replace(" ", "")
    return any(fragment.lower().replace(" ", "") in normalized for fragment in fragments)


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
