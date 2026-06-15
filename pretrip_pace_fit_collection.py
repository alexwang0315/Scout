from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scout_pace_guardian_tool import assess_scout_pace_guardian


PACE_FIT_COLLECTION_ARTIFACT_KIND = "pretrip_pace_fit_collection"
PACE_COEFFICIENTS_ARTIFACT_KIND = "pretrip_pace_coefficients"
TEAM_PACE_FIT_ARTIFACT_KIND = "pretrip_team_pace_fit"
PACE_FIT_SCHEMA_VERSION = "pace_fit_collection.v1"

PACE_COEFFICIENTS_REF = "normalized/pace/pace_coefficients.json"
TEAM_PACE_FIT_REF = "normalized/pace/team_pace_fit.json"


SEC7_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "sections": [
        "Sec. 7 Readiness & Pace Fit",
        "Sec. 7.2 Scout Pace Coefficient",
        "Sec. 7.3 Team Pace Fit",
        "Sec. 15.1 Pace Guardian",
        "Sec. 18.1 member experience and pace inputs",
        "Sec. 23 acceptance criteria",
    ],
    "workspace_layout_refs": [
        PACE_COEFFICIENTS_REF,
        TEAM_PACE_FIT_REF,
        "outputs/resource_plan.json",
        "outputs/planned_eta.json",
        "outputs/timing_measurements.json",
        "outputs/weather_daylight_evidence.json",
        "post-analysis imported refs",
    ],
}


COEFFICIENT_SCHEMA = [
    {
        "indicator_id": "flat_speed_mps",
        "label": "flat speed",
        "description": "Observed or reviewed flat-ground moving speed.",
        "required_for_confident_fit": True,
    },
    {
        "indicator_id": "ascent_speed_vertical_m_per_hour",
        "label": "ascent speed",
        "description": "Observed or reviewed vertical ascent speed.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "descent_speed_mps",
        "label": "descent speed",
        "description": "Observed or reviewed descent pace.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "technical_terrain_slowdown_ratio",
        "label": "technical terrain slowdown",
        "description": "Slowdown factor for rope, exposure, mud, roots, or scramble terrain.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "rest_frequency_minutes",
        "label": "rest frequency",
        "description": "Expected interval between meaningful rests.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "late_trip_decay_ratio",
        "label": "late-trip pace decay",
        "description": "Expected pace loss after cumulative fatigue.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "load_impact_ratio",
        "label": "load impact",
        "description": "Pack-weight or carried-load impact on pace.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "weather_impact_ratio",
        "label": "weather impact",
        "description": "Rain, heat, wind, or cold impact on pace.",
        "required_for_confident_fit": False,
    },
    {
        "indicator_id": "experience_credibility",
        "label": "experience credibility",
        "description": "Whether the pace claim is credible for similar route class.",
        "required_for_confident_fit": True,
    },
]


def collect_pretrip_pace_fit(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    team_members: list[Any] | None = None,
    current_time: str | None = None,
    next_cp_id: str | None = None,
    minutes_to_next_cp: float | int | str | None = None,
    current_delay_minutes: float | int | str | None = None,
    leader_accepts_slowest_basis: bool | str | None = None,
    team_rest_sync: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Materialize Sec. 7 Readiness & Pace Fit into the pretrip workspace.

    The collector wraps the deterministic Pace Guardian assessor and stores
    reviewable planning evidence. It intentionally does not write runtime safety
    truth, make medical diagnoses, send messages, or activate safety actions.
    """

    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()
    pace_coefficients_ref = str(
        project.get("pace_coefficients_ref") or PACE_COEFFICIENTS_REF
    )
    team_pace_fit_ref = str(project.get("team_pace_fit_ref") or TEAM_PACE_FIT_REF)
    planned_refs = [pace_coefficients_ref, team_pace_fit_ref]

    assessment = assess_scout_pace_guardian(
        root,
        query="Sec. 7 pretrip readiness and team pace fit collection",
        team_members=team_members,
        current_time=current_time,
        next_cp_id=next_cp_id,
        minutes_to_next_cp=minutes_to_next_cp,
        current_delay_minutes=current_delay_minutes,
        leader_accepts_slowest_basis=leader_accepts_slowest_basis,
        team_rest_sync=team_rest_sync,
    )
    team_pace_fit = (
        assessment.get("team_pace_fit")
        if isinstance(assessment.get("team_pace_fit"), dict)
        else {}
    )
    pace_guardian = (
        assessment.get("pace_guardian")
        if isinstance(assessment.get("pace_guardian"), dict)
        else {}
    )
    source_report = list(assessment.get("source_report") or [])
    missing_fields = list(assessment.get("missing_fields") or [])
    boundary = _closed_boundary(workspace_file_mutation_allowed=not dry_run)
    member_coefficients = _member_coefficients(
        team_members=team_members,
        team_pace_fit=team_pace_fit,
    )
    counts = _counts(
        team_pace_fit=team_pace_fit,
        member_coefficients=member_coefficients,
        missing_fields=missing_fields,
    )

    pace_coefficients_payload = {
        "artifact_kind": PACE_COEFFICIENTS_ARTIFACT_KIND,
        "schema_version": PACE_FIT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "status": "completed" if not missing_fields else "missing_required_inputs",
        "coefficient_schema": COEFFICIENT_SCHEMA,
        "coefficient_schema_count": len(COEFFICIENT_SCHEMA),
        "member_coefficients": member_coefficients,
        "counts": {
            "member_coefficient_count": len(member_coefficients),
            "missing_field_count": len(missing_fields),
        },
        "missing_fields": missing_fields,
        "source_report": source_report,
        "standard_alignment": SEC7_ALIGNMENT,
        "boundary": boundary,
    }
    team_pace_fit_payload = {
        "artifact_kind": TEAM_PACE_FIT_ARTIFACT_KIND,
        "schema_version": PACE_FIT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "decision": assessment.get("decision"),
        "answerability": assessment.get("answerability"),
        "field_answer": assessment.get("field_answer"),
        "pace_guardian": pace_guardian,
        "team_pace_fit": team_pace_fit,
        "schedule_pressure": assessment.get("schedule_pressure"),
        "team_context": assessment.get("team_context"),
        "counts": counts,
        "missing_fields": missing_fields,
        "source_report": source_report,
        "human_review_required": True,
        "standard_alignment": SEC7_ALIGNMENT,
        "boundary": boundary,
    }
    collection_payload = {
        "artifact_kind": PACE_FIT_COLLECTION_ARTIFACT_KIND,
        "schema_version": PACE_FIT_SCHEMA_VERSION,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": planned_refs,
        "outputs": {
            "pace_coefficients_ref": pace_coefficients_ref,
            "team_pace_fit_ref": team_pace_fit_ref,
        },
        "decision": assessment.get("decision"),
        "answerability": assessment.get("answerability"),
        "member_count": counts["member_count"],
        "members_with_pace_count": counts["members_with_pace_count"],
        "vulnerable_member_count": counts["vulnerable_member_count"],
        "missing_fields": missing_fields,
        "source_report": source_report,
        "standard_alignment": SEC7_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / pace_coefficients_ref, pace_coefficients_payload)
        _write_json(root / team_pace_fit_ref, team_pace_fit_payload)
        _update_project_refs(
            project_path,
            project,
            {
                "pace_coefficients_ref": pace_coefficients_ref,
                "team_pace_fit_ref": team_pace_fit_ref,
                "team_pace_fit_decision": assessment.get("decision"),
                "team_pace_fit_member_count": counts["member_count"],
                "team_pace_fit_vulnerable_member_count": counts[
                    "vulnerable_member_count"
                ],
                "pace_fit_collection_updated_at": collected_at,
                "pace_fit_collection_schema_version": PACE_FIT_SCHEMA_VERSION,
            },
        )
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_refs

    return collection_payload


def _member_coefficients(
    *,
    team_members: list[Any] | None,
    team_pace_fit: dict[str, Any],
) -> list[dict[str, Any]]:
    if isinstance(team_members, list) and team_members:
        return [
            _coefficient_from_raw_member(raw, index=index)
            for index, raw in enumerate(team_members)
            if isinstance(raw, dict)
        ]

    members = _summarized_members(team_pace_fit)
    return [
        _coefficient_from_public_summary(member, index=index)
        for index, member in enumerate(members)
    ]


def _coefficient_from_raw_member(raw: dict[str, Any], *, index: int) -> dict[str, Any]:
    pace = _float_or_none(
        _first_present(
            raw.get("pace_mps"),
            raw.get("current_pace_mps"),
            raw.get("planned_pace_mps"),
            raw.get("moving_speed_mps"),
            raw.get("speed_mps"),
        )
    )
    first_time = _bool_or_none(
        _first_present(
            raw.get("first_time_similar_route"),
            raw.get("first_time_route"),
            raw.get("first_time_on_route_type"),
        )
    )
    review_state = raw.get("review_state")
    return {
        "member_id": str(raw.get("member_id") or raw.get("id") or f"member_{index + 1}"),
        "label": str(
            raw.get("display_label")
            or raw.get("label")
            or raw.get("name")
            or raw.get("member_id")
            or f"member_{index + 1}"
        ),
        "role": raw.get("role"),
        "flat_speed_mps": pace,
        "ascent_speed_vertical_m_per_hour": _float_or_none(
            _first_present(
                raw.get("ascent_speed_vertical_m_per_hour"),
                raw.get("ascent_m_per_hour"),
                raw.get("vertical_ascent_speed_mph"),
            )
        ),
        "descent_speed_mps": _float_or_none(raw.get("descent_speed_mps")),
        "technical_terrain_slowdown_ratio": _float_or_none(
            raw.get("technical_terrain_slowdown_ratio")
        ),
        "rest_frequency_minutes": _float_or_none(
            _first_present(raw.get("rest_frequency_minutes"), raw.get("rest_need_minutes"))
        ),
        "late_trip_decay_ratio": _float_or_none(raw.get("late_trip_decay_ratio")),
        "load_impact_ratio": _float_or_none(raw.get("load_impact_ratio")),
        "weather_impact_ratio": _float_or_none(raw.get("weather_impact_ratio")),
        "experience_credibility": _experience_credibility(
            first_time_similar_route=first_time,
            review_state=review_state,
        ),
        "reserve_minutes": _float_or_none(
            _first_present(
                raw.get("reserve_minutes"),
                raw.get("remaining_reserve_minutes"),
                raw.get("slowest_member_reserve_minutes"),
            )
        ),
        "first_time_similar_route": first_time,
        "vulnerable_link": _public_vulnerable_hint(raw),
        "raw_health_payload_embedded": False,
        "medical_diagnosis": False,
    }


def _coefficient_from_public_summary(
    member: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    first_time = _bool_or_none(member.get("first_time_similar_route"))
    return {
        "member_id": str(member.get("member_id") or f"member_{index + 1}"),
        "label": str(member.get("label") or member.get("member_id") or f"member_{index + 1}"),
        "role": member.get("role"),
        "flat_speed_mps": _float_or_none(member.get("pace_mps")),
        "ascent_speed_vertical_m_per_hour": None,
        "descent_speed_mps": None,
        "technical_terrain_slowdown_ratio": None,
        "rest_frequency_minutes": None,
        "late_trip_decay_ratio": None,
        "load_impact_ratio": None,
        "weather_impact_ratio": None,
        "experience_credibility": _experience_credibility(
            first_time_similar_route=first_time,
            review_state=member.get("review_state"),
        ),
        "reserve_minutes": _float_or_none(member.get("reserve_minutes")),
        "first_time_similar_route": first_time,
        "vulnerable_link": member.get("vulnerable_link"),
        "raw_health_payload_embedded": False,
        "medical_diagnosis": False,
    }


def _summarized_members(team_pace_fit: dict[str, Any]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for member in (
        team_pace_fit.get("slowest_member"),
        team_pace_fit.get("fastest_member"),
        *(team_pace_fit.get("vulnerable_members") or []),
    ):
        if not isinstance(member, dict):
            continue
        key = str(member.get("member_id") or member.get("label") or len(by_key))
        by_key[key] = member
    return list(by_key.values())


def _counts(
    *,
    team_pace_fit: dict[str, Any],
    member_coefficients: list[dict[str, Any]],
    missing_fields: list[str],
) -> dict[str, Any]:
    warnings = team_pace_fit.get("warnings")
    warnings = warnings if isinstance(warnings, list) else []
    vulnerable_members = team_pace_fit.get("vulnerable_members")
    vulnerable_members = vulnerable_members if isinstance(vulnerable_members, list) else []
    member_count = team_pace_fit.get("member_count")
    members_with_pace_count = team_pace_fit.get("members_with_pace_count")
    return {
        "member_count": int(member_count or len(member_coefficients)),
        "members_with_pace_count": int(
            members_with_pace_count
            if members_with_pace_count is not None
            else sum(
                1
                for member in member_coefficients
                if _float_or_none(member.get("flat_speed_mps")) is not None
            )
        ),
        "member_coefficient_count": len(member_coefficients),
        "vulnerable_member_count": len(vulnerable_members),
        "missing_field_count": len(missing_fields),
        "warning_count": len(warnings),
    }


def _experience_credibility(
    *,
    first_time_similar_route: bool | None,
    review_state: Any,
) -> str:
    if first_time_similar_route is True:
        return "needs_similar_route_review"
    if str(review_state or "").lower() in {"reviewed", "approved", "verified"}:
        return "reviewed"
    return "unknown"


def _public_vulnerable_hint(raw: dict[str, Any]) -> bool | None:
    explicit = _bool_or_none(raw.get("vulnerable_link"))
    if explicit is not None:
        return explicit
    fatigue = str(raw.get("fatigue_band") or raw.get("fatigue") or "").lower()
    if fatigue in {"tired", "very_tired", "rest_suggested", "manual_check", "slow_down"}:
        return True
    conditions = raw.get("conditions") or raw.get("condition_flags")
    if isinstance(conditions, list) and conditions:
        return True
    return None


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


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
        "raw_health_payload_embedded": False,
        "medical_diagnosis": False,
        "average_pace_used": False,
    }


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout pace fit evidence.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--team-members-json", default=None)
    parser.add_argument("--current-time", default=None)
    parser.add_argument("--next-cp-id", default=None)
    parser.add_argument("--minutes-to-next-cp", default=None)
    parser.add_argument("--current-delay-minutes", default=None)
    parser.add_argument("--leader-accepts-slowest-basis", default=None)
    parser.add_argument("--team-rest-sync", default=None)
    parser.add_argument("--generated-at", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    team_members = json.loads(args.team_members_json) if args.team_members_json else None
    payload = collect_pretrip_pace_fit(
        args.project_root,
        dry_run=args.dry_run,
        team_members=team_members,
        current_time=args.current_time,
        next_cp_id=args.next_cp_id,
        minutes_to_next_cp=args.minutes_to_next_cp,
        current_delay_minutes=args.current_delay_minutes,
        leader_accepts_slowest_basis=args.leader_accepts_slowest_basis,
        team_rest_sync=args.team_rest_sync,
        generated_at=args.generated_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
