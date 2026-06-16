from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BOSS_POINT_SYNTHESIS_ARTIFACT_KIND = "pretrip_boss_point_synthesis"
BOSS_POINT_SYNTHESIS_SCHEMA_VERSION = "boss_point_synthesis.v1"
BOSS_POINTS_REF = "outputs/boss_points.json"
BOSS_POINTS_GEOJSON_REF = "outputs/boss_points.geojson"

DEFAULT_CHECKPOINTS_REF = "candidates/checkpoints.json"
DEFAULT_SEGMENTS_REF = "candidates/segments.json"
DEFAULT_ROUTE_NOTES_REF = "candidates/route_note_candidates.json"
DEFAULT_RISK_RIBBON_REF = "outputs/risk_ribbon.geojson"
DEFAULT_MCP_CANDIDATES_REF = "outputs/mcp/mcp_candidates.json"
DEFAULT_NAMED_POINT_EVIDENCE_REF = "outputs/mcp/named_point_evidence.json"
DEFAULT_REST_AREA_REF = "outputs/rest_area_candidates.json"
DEFAULT_RESUME_SEGMENTS_REF = "outputs/resume_segments.json"
DEFAULT_INCIDENT_CONTEXT_REF = "outputs/incident_context.reviewed.json"
DEFAULT_WEATHER_DAYLIGHT_REF = "outputs/weather_daylight_evidence.json"
DEFAULT_TEAM_STATUS_REF = "outputs/team_status.json"
DEFAULT_ENERGY_VITALS_REF = "outputs/energy_vitals_snapshot.reviewed.json"
DEFAULT_PACE_COEFFICIENTS_REF = "normalized/pace/pace_coefficients.json"

BOSS_THEMES = [
    {
        "theme": "three_kingdoms_generals",
        "alias": "呂布關",
        "icon_key": "lu_bu",
        "avatar_style": "scout_original_silhouette",
        "decorative_only": True,
    },
    {
        "theme": "three_kingdoms_generals",
        "alias": "關羽門",
        "icon_key": "guan_yu",
        "avatar_style": "scout_original_silhouette",
        "decorative_only": True,
    },
    {
        "theme": "three_kingdoms_generals",
        "alias": "張飛坡",
        "icon_key": "zhang_fei",
        "avatar_style": "scout_original_silhouette",
        "decorative_only": True,
    },
    {
        "theme": "three_kingdoms_generals",
        "alias": "趙雲稜",
        "icon_key": "zhao_yun",
        "avatar_style": "scout_original_silhouette",
        "decorative_only": True,
    },
    {
        "theme": "three_kingdoms_generals",
        "alias": "馬超壁",
        "icon_key": "ma_chao",
        "avatar_style": "scout_original_silhouette",
        "decorative_only": True,
    },
]

WARNING_NAME_TERMS = (
    "斷崖",
    "崩壁",
    "崩塌",
    "崩",
    "好漢坡",
    "軟腳坡",
    "坡",
    "細瘦稜",
    "稜線",
    "瘦稜",
    "拉繩",
    "繩",
    "高繞",
    "暴露",
    "落石",
    "碎石",
    "泥濘",
    "迷途",
    "隱蔽",
)
REST_TERMS = ("休", "營地", "紮營", "山屋", "保線所", "水源", "午餐", "等")
SLOW_TERMS = ("慢", "累", "耗力", "軟腳", "喘", "陡", "難", "小心")
TERRAIN_CLASS_BONUS = {
    "extreme_terrain_hazard": 18.0,
    "hidden_forest_route_loss": 14.0,
    "viewpoint_trailhead_pass": 8.0,
    "water_source": 4.0,
    "camp_hut_structure": 4.0,
    "fork_junction": 2.0,
    "mobile_reception": 1.0,
    "route_note_warning": 10.0,
}


def synthesize_pretrip_boss_points(
    project_root: Path | str,
    *,
    top_n: int = 5,
    route_note_radius_m: float = 300.0,
    risk_window_m: float = 300.0,
    generated_at: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(project_root)
    project_path = root / "project.json"
    project = _load_json_object(project_path)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()

    checkpoints_path = _project_path(
        root, project, "checkpoint_candidates_ref", DEFAULT_CHECKPOINTS_REF
    )
    segments_path = _project_path(
        root, project, "segment_candidates_ref", DEFAULT_SEGMENTS_REF
    )
    route_notes_path = _project_path(
        root, project, "route_note_candidates_ref", DEFAULT_ROUTE_NOTES_REF
    )
    risk_ribbon_path = _project_path(root, project, "risk_ribbon_ref", DEFAULT_RISK_RIBBON_REF)
    mcp_path = _project_path(root, project, "mcp_candidates_ref", DEFAULT_MCP_CANDIDATES_REF)
    named_points_path = _project_path(
        root, project, "mcp_named_point_evidence_ref", DEFAULT_NAMED_POINT_EVIDENCE_REF
    )
    rest_area_path = _project_path(root, project, "rest_area_candidates_ref", DEFAULT_REST_AREA_REF)
    resume_path = _project_path(root, project, "resume_segments_ref", DEFAULT_RESUME_SEGMENTS_REF)
    incident_path = _project_path(root, project, "incident_context_ref", DEFAULT_INCIDENT_CONTEXT_REF)
    weather_path = _project_path(
        root, project, "weather_daylight_evidence_ref", DEFAULT_WEATHER_DAYLIGHT_REF
    )
    team_status_path = _project_path(root, project, "team_status_ref", DEFAULT_TEAM_STATUS_REF)
    energy_path = _project_path(root, project, "energy_vitals_ref", DEFAULT_ENERGY_VITALS_REF)
    pace_path = _project_path(
        root, project, "pace_coefficients_ref", DEFAULT_PACE_COEFFICIENTS_REF
    )

    checkpoints = _load_json_list(checkpoints_path)
    segments = _load_json_list(segments_path)
    route_notes_payload = _load_json_object(route_notes_path)
    route_notes = _payload_list(route_notes_payload, "candidates")
    risk_ribbon = _load_json_object(risk_ribbon_path)
    mcp_payload = _load_json_object(mcp_path)
    named_points_payload = _load_json_object(named_points_path)
    rest_area_payload = _load_json_object(rest_area_path)
    resume_payload = _load_json_object(resume_path)
    incident_context = _load_json_object(incident_path)
    weather_daylight = _load_json_object(weather_path)
    team_status = _load_json_object(team_status_path)
    energy_vitals = _load_json_object(energy_path)
    pace_coefficients = _load_json_object(pace_path)

    cp_distance = _checkpoint_route_distances(checkpoints, segments)
    route_extent_m = _route_extent_m(cp_distance, risk_ribbon, mcp_payload)
    named_points = _named_points_by_id(named_points_payload)
    notes_with_distance = _route_notes_with_distance(route_notes, checkpoints, cp_distance)
    rest_with_distance = _rest_areas_with_distance(
        _payload_list(rest_area_payload, "candidates"), checkpoints, cp_distance
    )
    resume_with_distance = _resume_segments_with_distance(
        _payload_list(resume_payload, "segments"), cp_distance
    )
    risk_features = _payload_list(risk_ribbon, "features")
    profile = _user_readiness_profile(
        pace_coefficients=pace_coefficients,
        team_status=team_status,
        energy_vitals=energy_vitals,
    )

    candidates = _boss_candidates_from_mcp(mcp_payload, named_points)
    if len(candidates) < top_n:
        candidates.extend(_warning_route_note_candidates(notes_with_distance, existing=candidates))
    local_extent_m = max(
        [route_extent_m, *[_float_or_none(candidate.get("distance_m")) or 0.0 for candidate in candidates]]
    )
    boss_points = []
    for candidate in candidates:
        distance_m = _float_or_none(candidate.get("distance_m"))
        lat = _float_or_none(candidate.get("lat"))
        lon = _float_or_none(candidate.get("lon"))
        nearby_notes = _nearby_by_distance(notes_with_distance, distance_m, route_note_radius_m)
        nearby_rest = _nearby_by_distance(rest_with_distance, distance_m, route_note_radius_m)
        nearby_resume = _nearby_by_distance(resume_with_distance, distance_m, route_note_radius_m)
        risk_summary = _risk_summary_near(risk_features, distance_m, risk_window_m)
        demand = _route_boss_demand(
            candidate=candidate,
            nearby_notes=nearby_notes,
            nearby_rest=nearby_rest,
            nearby_resume=nearby_resume,
            risk_summary=risk_summary,
            incident_context=incident_context,
            weather_daylight=weather_daylight,
            route_extent_m=route_extent_m,
            local_extent_m=local_extent_m,
        )
        challenge_fit = _challenge_fit(demand, profile, candidate)
        boss_points.append(
            {
                "source_candidate_id": candidate.get("candidate_id"),
                "source_mcp_id": candidate.get("mcp_id"),
                "label": candidate.get("label") or "Unnamed boss point",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "human_review_required": True,
                "lat": lat,
                "lon": lon,
                "route_position": {
                    "distance_m": _round(distance_m),
                    "route_progress_ratio": _round(_safe_ratio(distance_m, route_extent_m)),
                    "local_evidence_progress_ratio": _round(
                        _safe_ratio(distance_m, local_extent_m)
                    ),
                },
                "mcp_classes": candidate.get("mcp_classes") or [],
                "linked_named_points": candidate.get("linked_named_points") or [],
                "route_boss_demand": demand,
                "challenge_fit": challenge_fit,
                "evidence_summary": {
                    "nearby_route_note_count": len(nearby_notes),
                    "nearby_warning_note_count": sum(
                        1 for note in nearby_notes if _contains_terms(_note_text(note), WARNING_NAME_TERMS)
                    ),
                    "nearby_rest_area_count": len(nearby_rest),
                    "nearby_resume_segment_count": len(nearby_resume),
                    "max_risk_score": risk_summary["max_risk_score"],
                    "risk_feature_count": risk_summary["feature_count"],
                    "named_point_evidence": candidate.get("named_point_evidence"),
                },
                "source_refs": _dedupe(
                    [
                        str(route_notes_path.relative_to(root)) if route_notes_path.is_relative_to(root) else str(route_notes_path),
                        str(mcp_path.relative_to(root)) if mcp_path.is_relative_to(root) else str(mcp_path),
                        str(risk_ribbon_path.relative_to(root)) if risk_ribbon_path.is_relative_to(root) else str(risk_ribbon_path),
                    ]
                ),
            }
        )

    boss_points = sorted(
        boss_points,
        key=lambda item: item["route_boss_demand"]["score"],
        reverse=True,
    )[: max(0, int(top_n))]
    for index, point in enumerate(boss_points):
        point["rank"] = index + 1
        point["boss_point_id"] = f"boss.{project_id}.{index + 1:03d}"
        point["display_theme"] = BOSS_THEMES[index % len(BOSS_THEMES)]

    payload = {
        "artifact_kind": BOSS_POINT_SYNTHESIS_ARTIFACT_KIND,
        "schema_version": BOSS_POINT_SYNTHESIS_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "status": "completed" if boss_points else "missing_candidate_evidence",
        "top_n": top_n,
        "boss_points_ref": BOSS_POINTS_REF,
        "boss_points_geojson_ref": BOSS_POINTS_GEOJSON_REF,
        "boss_point_count": len(boss_points),
        "boss_points": boss_points,
        "challenge_fit_summary": _challenge_fit_summary(boss_points, profile),
        "source_report": _source_report(
            [
                ("checkpoints", checkpoints_path, bool(checkpoints), True),
                ("segments", segments_path, bool(segments), True),
                ("route_notes", route_notes_path, bool(route_notes), False),
                ("risk_ribbon", risk_ribbon_path, bool(risk_features), False),
                ("mcp_candidates", mcp_path, bool(mcp_payload), True),
                ("named_point_evidence", named_points_path, bool(named_points_payload), False),
                ("rest_area_candidates", rest_area_path, bool(rest_with_distance), False),
                ("resume_segments", resume_path, bool(resume_with_distance), False),
                ("incident_context", incident_path, bool(incident_context), False),
                ("weather_daylight", weather_path, bool(weather_daylight), False),
                ("pace_coefficients", pace_path, bool(pace_coefficients), False),
                ("team_status", team_status_path, bool(team_status), False),
                ("energy_vitals", energy_path, bool(energy_vitals), False),
            ]
        ),
        "boundary": _closed_boundary(workspace_file_mutation_allowed=not dry_run),
    }
    geojson = _boss_points_geojson(payload)

    if not dry_run:
        _write_json(root / BOSS_POINTS_REF, payload)
        _write_json(root / BOSS_POINTS_GEOJSON_REF, geojson)
        if project_path.exists():
            _write_json(
                project_path,
                {
                    **project,
                    "boss_points_ref": BOSS_POINTS_REF,
                    "boss_points_geojson_ref": BOSS_POINTS_GEOJSON_REF,
                    "boss_point_count": len(boss_points),
                    "boss_point_synthesis_updated_at": collected_at,
                    "boss_point_synthesis_schema_version": BOSS_POINT_SYNTHESIS_SCHEMA_VERSION,
                },
            )

    return payload


def _boss_candidates_from_mcp(
    mcp_payload: dict[str, Any],
    named_points: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for item in _payload_list(mcp_payload, "mcp_candidates"):
        linked_ids = [str(value) for value in item.get("linked_named_points") or []]
        evidence = [named_points[named_id] for named_id in linked_ids if named_id in named_points]
        classes = [str(value) for value in item.get("mcp_classes") or []]
        terrain_support = _float_or_none((item.get("score_components") or {}).get("terrain_risk_support")) or 0.0
        if (
            set(classes).issubset({"fork_junction", "mobile_reception"})
            and terrain_support <= 0
            and not _contains_terms(str(item.get("label") or ""), WARNING_NAME_TERMS)
        ):
            continue
        candidates.append(
            {
                "candidate_id": item.get("mcp_id"),
                "mcp_id": item.get("mcp_id"),
                "label": item.get("label"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "distance_m": item.get("distance_m"),
                "mcp_classes": classes,
                "linked_named_points": linked_ids,
                "linked_risk_segments": list(item.get("linked_risk_segments") or []),
                "mcp_score_components": item.get("score_components") or {},
                "mention_ratio": item.get("mention_ratio"),
                "accepted_evidence_page_count": item.get("accepted_evidence_page_count"),
                "source_family_coverage": item.get("source_family_coverage") or {},
                "named_point_evidence": evidence,
            }
        )
    return candidates


def _warning_route_note_candidates(
    notes: list[dict[str, Any]],
    *,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_distances = [
        _float_or_none(item.get("distance_m"))
        for item in existing
        if _float_or_none(item.get("distance_m")) is not None
    ]
    candidates = []
    for note in notes:
        text = _note_text(note)
        if not _contains_terms(text, WARNING_NAME_TERMS):
            continue
        distance = _float_or_none(note.get("route_distance_m"))
        if distance is None:
            continue
        if any(abs(distance - existing_distance) <= 250 for existing_distance in existing_distances):
            continue
        candidates.append(
            {
                "candidate_id": note.get("candidate_id"),
                "label": _compact_route_note_label(text),
                "lat": note.get("lat"),
                "lon": note.get("lon"),
                "distance_m": distance,
                "mcp_classes": ["route_note_warning"],
                "linked_named_points": [],
                "linked_risk_segments": [],
                "mcp_score_components": {},
                "mention_ratio": None,
                "accepted_evidence_page_count": 0,
                "source_family_coverage": {},
                "named_point_evidence": [],
            }
        )
    return candidates


def _route_boss_demand(
    *,
    candidate: dict[str, Any],
    nearby_notes: list[dict[str, Any]],
    nearby_rest: list[dict[str, Any]],
    nearby_resume: list[dict[str, Any]],
    risk_summary: dict[str, Any],
    incident_context: dict[str, Any],
    weather_daylight: dict[str, Any],
    route_extent_m: float,
    local_extent_m: float,
) -> dict[str, Any]:
    label = str(candidate.get("label") or "")
    classes = {str(value) for value in candidate.get("mcp_classes") or []}
    distance_m = _float_or_none(candidate.get("distance_m"))
    route_progress = _safe_ratio(distance_m, route_extent_m) or 0.0
    local_progress = _safe_ratio(distance_m, local_extent_m) or 0.0
    named_evidence = candidate.get("named_point_evidence") or []
    source_family_count = len(
        {
            family
            for evidence in named_evidence
            if isinstance(evidence, dict)
            for family in (evidence.get("source_families") or [])
        }
    )
    warning_note_count = sum(
        1 for note in nearby_notes if _contains_terms(_note_text(note), WARNING_NAME_TERMS)
    )
    slow_note_count = sum(1 for note in nearby_notes if _contains_terms(_note_text(note), SLOW_TERMS))
    rest_note_count = sum(1 for note in nearby_notes if _contains_terms(_note_text(note), REST_TERMS))

    mcp_score = _float_or_none((candidate.get("mcp_score_components") or {}).get("total")) or 0.0
    terrain_risk_support = _float_or_none(
        (candidate.get("mcp_score_components") or {}).get("terrain_risk_support")
    ) or 0.0
    max_risk_score = _float_or_none(risk_summary.get("max_risk_score")) or 0.0
    incident_text = json.dumps(incident_context, ensure_ascii=False)
    weather_text = json.dumps(weather_daylight, ensure_ascii=False)
    incident_terms_present = _contains_terms(
        incident_text, ("山難", "救援", "迷途", "墜", "失溫", "落石", "事故", "near_miss")
    )
    weather_terms_present = _contains_terms(weather_text, ("fog", "霧", "雨", "wind", "低溫", "daylight", "摸黑"))

    class_bonus = max((TERRAIN_CLASS_BONUS.get(value, 0.0) for value in classes), default=0.0)
    components = {
        "observed_impedance": _clamp(slow_note_count * 3 + warning_note_count * 3, 0, 14),
        "route_note_consensus": _clamp(
            source_family_count * 3
            + warning_note_count * 3
            + slow_note_count * 2
            + rest_note_count
            + (_float_or_none(candidate.get("mention_ratio")) or 0.0) * 10,
            0,
            16,
        ),
        "rest_cluster": _clamp(len(nearby_rest) * 4 + rest_note_count, 0, 8),
        "terrain_risk": _clamp(
            max_risk_score / 8 + terrain_risk_support / 2 + class_bonus,
            0,
            24,
        ),
        "environment_hardness": _clamp(
            (6 if weather_terms_present else 0)
            + (4 if "mobile_reception" not in classes and local_progress >= 0.55 else 0),
            0,
            10,
        ),
        "rescue_difficulty": _clamp(local_progress * 8 + route_progress * 8 + len(nearby_resume) * 3, 0, 12),
        "incident_evidence": 8 if incident_terms_present else 0,
        "named_point_warning": _clamp(
            (12 if _contains_terms(label, WARNING_NAME_TERMS) else 0)
            + source_family_count * 1.5,
            0,
            15,
        ),
        "mcp_strength": _clamp(mcp_score / 10, 0, 10),
    }
    late_multiplier = 1.0 + _clamp(local_progress - 0.5, 0, 0.5) * 0.18
    score = _clamp(sum(components.values()) * late_multiplier, 0, 100)
    missing_evidence = []
    if not nearby_notes:
        missing_evidence.append("nearby_route_notes")
    if risk_summary["feature_count"] == 0:
        missing_evidence.append("route_aligned_risk_window")
    if not named_evidence:
        missing_evidence.append("named_point_web_evidence")
    if not incident_terms_present:
        missing_evidence.append("route_specific_incident_records")
    return {
        "score": _round(score),
        "band": _demand_band(score),
        "components": {key: _round(value) for key, value in components.items()},
        "late_trip_multiplier": _round(late_multiplier),
        "evidence_state": "mixed_evidence" if missing_evidence else "multi_source_supported",
        "missing_evidence": missing_evidence,
        "formula": "sum(component_scores) * late_trip_multiplier",
    }


def _challenge_fit(
    demand: dict[str, Any],
    profile: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    demand_score = _float_or_none(demand.get("score")) or 0.0
    components = demand.get("components") if isinstance(demand.get("components"), dict) else {}
    coefficient = profile.get("slowest_pace_coefficient") or {}
    technical = _float_or_none(coefficient.get("technical_terrain_slowdown_ratio")) or 0.0
    late_decay = _float_or_none(coefficient.get("late_trip_speed_decay_ratio")) or _float_or_none(
        coefficient.get("late_trip_decay_ratio")
    ) or 0.0
    flat = _float_or_none(coefficient.get("flat_speed_mps"))
    downhill = _float_or_none(coefficient.get("downhill_speed_mps"))
    downhill_drag = 0.0
    if flat and downhill is not None and downhill < flat * 0.75:
        downhill_drag = _clamp(1.0 - downhill / (flat * 0.75), 0.0, 0.5)
    energy = profile.get("energy_reserve") or {}
    reserve_score = _float_or_none(energy.get("reserve_score"))
    reserve_vulnerability = _clamp((55.0 - reserve_score) / 55.0, 0.0, 0.8) if reserve_score is not None else 0.2
    if str(energy.get("reserve_band") or "").lower() in {"rest_suggested", "manual_check", "slow_down"}:
        reserve_vulnerability += 0.15

    technical_weight = _clamp((_float_or_none(components.get("terrain_risk")) or 0.0) / 22.0, 0.0, 1.0)
    late_weight = _clamp((_float_or_none(components.get("rescue_difficulty")) or 0.0) / 12.0, 0.0, 1.0)
    energy_weight = 0.45 + late_weight * 0.25
    vulnerability = _clamp(
        technical * technical_weight
        + late_decay * late_weight
        + downhill_drag * technical_weight
        + reserve_vulnerability * energy_weight,
        0,
        0.95,
    )
    score = _clamp(demand_score * (1.0 + vulnerability), 0, 100)
    return {
        "score": _round(score),
        "band": _challenge_fit_band(score),
        "formula": "route_boss_demand_score * (1 + pace_energy_vulnerability)",
        "route_boss_demand_score": _round(demand_score),
        "pace_energy_vulnerability": _round(vulnerability),
        "user_basis": profile.get("basis"),
        "slowest_member_id": profile.get("slowest_member_id"),
        "slowest_member_label": profile.get("slowest_member_label"),
        "pace_factors": {
            "technical_terrain_slowdown_ratio": _round(technical),
            "late_trip_decay_ratio": _round(late_decay),
            "downhill_drag_ratio": _round(downhill_drag),
            "technical_weight": _round(technical_weight),
            "late_weight": _round(late_weight),
        },
        "energy_factors": {
            "reserve_score": reserve_score,
            "reserve_band": energy.get("reserve_band"),
            "reserve_vulnerability": _round(reserve_vulnerability),
            "energy_weight": _round(energy_weight),
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def _user_readiness_profile(
    *,
    pace_coefficients: dict[str, Any],
    team_status: dict[str, Any],
    energy_vitals: dict[str, Any],
) -> dict[str, Any]:
    members = []
    for member in _payload_list(pace_coefficients, "member_coefficients"):
        members.append(
            {
                "member_id": member.get("member_id"),
                "label": member.get("label"),
                "pace_mps": member.get("flat_speed_mps"),
                "reserve_minutes": member.get("reserve_minutes"),
                "coefficient": member,
                "source": "pace_coefficients",
            }
        )
    for member in team_status.get("members") or []:
        if not isinstance(member, dict):
            continue
        coefficient = member.get("scout_pace_coefficient")
        coefficient = coefficient if isinstance(coefficient, dict) else {}
        members.append(
            {
                "member_id": member.get("member_id"),
                "label": member.get("display_label") or member.get("label"),
                "pace_mps": member.get("pace_mps") or coefficient.get("flat_speed_mps"),
                "reserve_minutes": member.get("reserve_minutes"),
                "coefficient": coefficient,
                "source": "team_status",
            }
        )
    slowest = sorted(
        members,
        key=lambda item: _float_or_none(item.get("pace_mps")) or 999.0,
    )[0] if members else {}
    return {
        "basis": "slowest_member_or_private_energy_reserve",
        "slowest_member_id": slowest.get("member_id"),
        "slowest_member_label": slowest.get("label"),
        "slowest_pace_mps": _float_or_none(slowest.get("pace_mps")),
        "slowest_pace_coefficient": slowest.get("coefficient") or {},
        "energy_reserve": {
            "reserve_score": energy_vitals.get("reserve_score"),
            "reserve_band": energy_vitals.get("reserve_band"),
            "source_provider": energy_vitals.get("source_provider"),
            "raw_health_payload_embedded": False,
            "medical_diagnosis": False,
        },
    }


def _challenge_fit_summary(
    boss_points: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    if not boss_points:
        return {
            "decision": "INSUFFICIENT_EVIDENCE",
            "highest_challenge_fit_score": None,
            "review_required": True,
        }
    highest = max(
        boss_points,
        key=lambda item: item["challenge_fit"]["score"],
    )
    score = highest["challenge_fit"]["score"]
    if score >= 75:
        decision = "CHANGE_PLAN_OR_ADD_BUFFER"
    elif score >= 55:
        decision = "HUMAN_REVIEW_REQUIRED"
    else:
        decision = "WATCH_WITH_REVIEWED_BUFFERS"
    return {
        "decision": decision,
        "highest_challenge_fit_score": score,
        "highest_challenge_fit_boss_point_id": highest["boss_point_id"],
        "highest_challenge_fit_label": highest["label"],
        "basis": profile.get("basis"),
        "slowest_member_id": profile.get("slowest_member_id"),
        "energy_reserve_band": (profile.get("energy_reserve") or {}).get("reserve_band"),
        "review_required": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _boss_points_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    features = []
    for point in payload.get("boss_points") or []:
        if point.get("lat") is None or point.get("lon") is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [point["lon"], point["lat"]],
                },
                "properties": {
                    "boss_point_id": point["boss_point_id"],
                    "rank": point["rank"],
                    "label": point["label"],
                    "display_alias": point["display_theme"]["alias"],
                    "icon_key": point["display_theme"]["icon_key"],
                    "route_boss_demand_score": point["route_boss_demand"]["score"],
                    "route_boss_demand_band": point["route_boss_demand"]["band"],
                    "challenge_fit_score": point["challenge_fit"]["score"],
                    "challenge_fit_band": point["challenge_fit"]["band"],
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "artifact_kind": "pretrip_boss_points_geojson",
            "source_artifact_kind": payload.get("artifact_kind"),
            "project_id": payload.get("project_id"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _checkpoint_route_distances(
    checkpoints: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, float]:
    distances: dict[str, float] = {}
    if checkpoints:
        distances[str(checkpoints[0].get("candidate_id") or "cp.start")] = 0.0
    changed = True
    while changed:
        changed = False
        for segment in segments:
            start = str(segment.get("from_candidate_id") or "")
            end = str(segment.get("to_candidate_id") or "")
            distance = _float_or_none(segment.get("distance_m")) or 0.0
            if start in distances and end and end not in distances:
                distances[end] = distances[start] + distance
                changed = True
    return distances


def _route_notes_with_distance(
    notes: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    cp_distance: dict[str, float],
) -> list[dict[str, Any]]:
    result = []
    for note in notes:
        lat = _float_or_none(note.get("lat"))
        lon = _float_or_none(note.get("lon"))
        distance = _nearest_checkpoint_distance(lat, lon, checkpoints, cp_distance)
        copied = dict(note)
        copied["route_distance_m"] = distance
        result.append(copied)
    return result


def _rest_areas_with_distance(
    rest_areas: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    cp_distance: dict[str, float],
) -> list[dict[str, Any]]:
    result = []
    for rest in rest_areas:
        lat = _float_or_none(rest.get("lat"))
        lon = _float_or_none(rest.get("lon"))
        copied = dict(rest)
        copied["route_distance_m"] = _nearest_checkpoint_distance(lat, lon, checkpoints, cp_distance)
        result.append(copied)
    return result


def _resume_segments_with_distance(
    segments: list[dict[str, Any]],
    cp_distance: dict[str, float],
) -> list[dict[str, Any]]:
    result = []
    for segment in segments:
        start = cp_distance.get(str(segment.get("from_candidate_id") or ""))
        end = cp_distance.get(str(segment.get("to_candidate_id") or ""))
        copied = dict(segment)
        copied["route_distance_m"] = _safe_ratio((start or 0.0) + (end or 0.0), 2.0)
        result.append(copied)
    return result


def _nearest_checkpoint_distance(
    lat: float | None,
    lon: float | None,
    checkpoints: list[dict[str, Any]],
    cp_distance: dict[str, float],
) -> float | None:
    if lat is None or lon is None:
        return None
    nearest = None
    for checkpoint in checkpoints:
        cp_id = str(checkpoint.get("candidate_id") or "")
        if cp_id not in cp_distance:
            continue
        cp_lat = _float_or_none(checkpoint.get("lat"))
        cp_lon = _float_or_none(checkpoint.get("lon"))
        distance = _haversine_m(lat, lon, cp_lat, cp_lon)
        if distance is None:
            continue
        if nearest is None or distance < nearest[0]:
            nearest = (distance, cp_distance[cp_id])
    return nearest[1] if nearest else None


def _nearby_by_distance(
    items: list[dict[str, Any]],
    distance_m: float | None,
    radius_m: float,
) -> list[dict[str, Any]]:
    if distance_m is None:
        return []
    return [
        item
        for item in items
        if _float_or_none(item.get("route_distance_m")) is not None
        and abs((_float_or_none(item.get("route_distance_m")) or 0.0) - distance_m) <= radius_m
    ]


def _risk_summary_near(
    features: list[dict[str, Any]],
    distance_m: float | None,
    radius_m: float,
) -> dict[str, Any]:
    if distance_m is None:
        return {"feature_count": 0, "max_risk_score": None, "avg_risk_score": None}
    scores = []
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        start = _float_or_none(props.get("start_distance_m"))
        end = _float_or_none(props.get("end_distance_m"))
        if start is None or end is None:
            continue
        if end < distance_m - radius_m or start > distance_m + radius_m:
            continue
        score = _float_or_none(props.get("rs") or props.get("risk_score"))
        if score is not None:
            scores.append(score)
    return {
        "feature_count": len(scores),
        "max_risk_score": _round(max(scores)) if scores else None,
        "avg_risk_score": _round(sum(scores) / len(scores)) if scores else None,
    }


def _route_extent_m(
    cp_distance: dict[str, float],
    risk_ribbon: dict[str, Any],
    mcp_payload: dict[str, Any],
) -> float:
    values = list(cp_distance.values())
    for feature in _payload_list(risk_ribbon, "features"):
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        for key in ("start_distance_m", "end_distance_m"):
            value = _float_or_none(props.get(key))
            if value is not None:
                values.append(value)
    for mcp in _payload_list(mcp_payload, "mcp_candidates"):
        value = _float_or_none(mcp.get("distance_m"))
        if value is not None:
            values.append(value)
    return max(values) if values else 0.0


def _named_points_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(point.get("named_point_id")): point
        for point in _payload_list(payload, "named_points")
        if point.get("named_point_id")
    }


def _note_text(note: dict[str, Any]) -> str:
    return " | ".join(
        str(note.get(key) or "")
        for key in ("route_note_summary", "normalized_note", "name", "desc", "label")
        if note.get(key)
    )


def _compact_route_note_label(text: str) -> str:
    parts = [
        part.strip()
        for part in str(text or "").replace("\n", " ").split("|")
        if part.strip()
    ]
    for part in parts:
        if _contains_terms(part, WARNING_NAME_TERMS):
            return _trim_label(_strip_timestamp(part))
    return _trim_label(_strip_timestamp(parts[0] if parts else "Route note warning point"))


def _strip_timestamp(text: str) -> str:
    tokens = [
        token
        for token in text.split()
        if not (len(token) >= 8 and token[:4].isdigit() and "-" in token)
    ]
    return " ".join(tokens) or text


def _trim_label(text: str, limit: int = 24) -> str:
    value = text.strip()
    return value if len(value) <= limit else value[:limit]


def _contains_terms(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _haversine_m(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    if None in {lat1, lon1, lat2, lon2}:
        return None
    radius = 6371000.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _source_report(rows: list[tuple[str, Path, bool, bool]]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": source_id,
            "path": str(path),
            "status": "loaded" if loaded else "missing",
            "required": required,
        }
        for source_id, path, loaded, required in rows
    ]


def _project_path(root: Path, project: dict[str, Any], key: str, default_ref: str) -> Path:
    value = str(project.get(key) or default_ref)
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return _payload_list(payload, "items")


def _payload_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key) if isinstance(payload, dict) else []
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    return value


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _demand_band(score: float) -> str:
    if score >= 75:
        return "boss_extreme"
    if score >= 55:
        return "boss_hard"
    if score >= 35:
        return "boss_watch"
    return "candidate"


def _challenge_fit_band(score: float) -> str:
    if score >= 75:
        return "not_ready_without_plan_change"
    if score >= 55:
        return "hard_requires_reviewed_buffer"
    if score >= 35:
        return "watch_requires_group_discipline"
    return "manageable_with_review"


def _closed_boundary(*, workspace_file_mutation_allowed: bool) -> dict[str, Any]:
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthesize Scout pretrip boss points.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--route-note-radius-m", type=float, default=300.0)
    parser.add_argument("--risk-window-m", type=float, default=300.0)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = synthesize_pretrip_boss_points(
        args.project_root,
        top_n=args.top_n,
        route_note_radius_m=args.route_note_radius_m,
        risk_window_m=args.risk_window_m,
        generated_at=args.generated_at,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
