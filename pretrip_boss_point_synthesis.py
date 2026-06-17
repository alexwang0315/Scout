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
ROUTE_PRESSURE_PROFILE_REF = "outputs/route_pressure_profile.json"
ROUTE_PRESSURE_PROFILE_GEOJSON_REF = "outputs/route_pressure_profile.geojson"

DEFAULT_CHECKPOINTS_REF = "candidates/checkpoints.json"
DEFAULT_SEGMENTS_REF = "candidates/segments.json"
DEFAULT_ROUTE_NOTES_REF = "candidates/route_note_candidates.json"
DEFAULT_RISK_RIBBON_REF = "outputs/risk_ribbon.geojson"
DEFAULT_SEGMENT_DISPLAY_GEOMETRY_REF = "outputs/segment_display_geometry.json"
DEFAULT_MCP_CANDIDATES_REF = "outputs/mcp/mcp_candidates.json"
DEFAULT_NAMED_POINT_EVIDENCE_REF = "outputs/mcp/named_point_evidence.json"
DEFAULT_REST_AREA_REF = "outputs/rest_area_candidates.json"
DEFAULT_RESUME_SEGMENTS_REF = "outputs/resume_segments.json"
DEFAULT_INCIDENT_CONTEXT_REF = "outputs/incident_context.reviewed.json"
DEFAULT_WEATHER_DAYLIGHT_REF = "outputs/weather_daylight_evidence.json"
DEFAULT_TEAM_STATUS_REF = "outputs/team_status.json"
DEFAULT_ENERGY_VITALS_REF = "outputs/energy_vitals_snapshot.reviewed.json"
DEFAULT_PACE_COEFFICIENTS_REF = "normalized/pace/pace_coefficients.json"
DEFAULT_ROUTE_MILEAGE_K_ANCHORS_REF = "candidates/route_mileage_k_anchors.json"
DEFAULT_ROUTE_PRESSURE_EXTERNAL_CANDIDATES_REF = (
    "outputs/route_pressure_external_candidates.json"
)
DEFAULT_SLOW_PASSAGE_MIN_SPAN_M = 500.0
DEFAULT_PRESSURE_PROFILE_BIN_M = 500.0

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
REST_STOP_TERMS = ("休", "營地", "紮營", "山屋", "保線所", "水源", "午餐")
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
    "route_pressure_peak": 10.0,
}


def synthesize_pretrip_boss_points(
    project_root: Path | str,
    *,
    top_n: int = 5,
    route_note_radius_m: float = 300.0,
    risk_window_m: float = 300.0,
    slow_passage_min_span_m: float = DEFAULT_SLOW_PASSAGE_MIN_SPAN_M,
    pressure_profile_bin_m: float = DEFAULT_PRESSURE_PROFILE_BIN_M,
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
    segment_display_geometry_path = _project_path(
        root,
        project,
        "segment_display_geometry_ref",
        DEFAULT_SEGMENT_DISPLAY_GEOMETRY_REF,
    )
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
    route_mileage_anchors_path = _project_path(
        root,
        project,
        "route_mileage_k_anchors_ref",
        DEFAULT_ROUTE_MILEAGE_K_ANCHORS_REF,
    )
    external_pressure_path = _project_path(
        root,
        project,
        "route_pressure_external_candidates_ref",
        DEFAULT_ROUTE_PRESSURE_EXTERNAL_CANDIDATES_REF,
    )

    checkpoints = _load_json_list(checkpoints_path)
    segments = _load_json_list(segments_path)
    route_notes_payload = _load_json_object(route_notes_path)
    route_notes = _payload_list(route_notes_payload, "candidates")
    pressure_route_notes = _pressure_relevant_route_notes(route_notes)
    risk_ribbon = _load_json_object(risk_ribbon_path)
    segment_display_geometry = _load_json_object(segment_display_geometry_path)
    mcp_payload = _load_json_object(mcp_path)
    named_points_payload = _load_json_object(named_points_path)
    rest_area_payload = _load_json_object(rest_area_path)
    resume_payload = _load_json_object(resume_path)
    incident_context = _load_json_object(incident_path)
    weather_daylight = _load_json_object(weather_path)
    team_status = _load_json_object(team_status_path)
    energy_vitals = _load_json_object(energy_path)
    pace_coefficients = _load_json_object(pace_path)
    route_mileage_anchors = _load_json_object(route_mileage_anchors_path)
    external_pressure_payload = _load_json_object(external_pressure_path)

    cp_distance = _checkpoint_route_distances(checkpoints, segments)
    named_points = _named_points_by_id(named_points_payload)
    segments_with_distance = _segments_with_route_distance(segments, cp_distance)
    notes_with_distance = _route_notes_with_distance(
        pressure_route_notes,
        checkpoints,
        cp_distance,
    )
    rest_with_distance = _rest_areas_with_distance(
        _payload_list(rest_area_payload, "candidates"), checkpoints, cp_distance
    )
    resume_with_distance = _resume_segments_with_distance(
        _payload_list(resume_payload, "segments"), cp_distance
    )
    risk_features = _payload_list(risk_ribbon, "features")
    gpx_route_geometry = _route_display_geometry_from_segment_display_geometry(
        project_id=project_id,
        segment_display_geometry=segment_display_geometry,
        segments=segments_with_distance,
        source_path=str(
            segment_display_geometry_path.relative_to(root)
            if segment_display_geometry_path.is_relative_to(root)
            else segment_display_geometry_path
        ),
    )
    route_display_geometry = _route_display_geometry_from_risk_ribbon(
        project_id=project_id,
        risk_features=risk_features,
        source_path=str(
            risk_ribbon_path.relative_to(root)
            if risk_ribbon_path.is_relative_to(root)
            else risk_ribbon_path
        ),
    )
    route_mileage_alignment = _route_mileage_alignment_from_anchors(
        route_mileage_anchors,
        route_display_geometry=route_display_geometry,
        source_ref=str(
            route_mileage_anchors_path.relative_to(root)
            if route_mileage_anchors_path.is_relative_to(root)
            else route_mileage_anchors_path
        ),
    )
    segments_with_distance = _gpx_segments_projected_to_route(
        segments_with_distance,
        gpx_route_geometry,
        route_display_geometry,
    )
    notes_with_distance = _items_projected_to_route(notes_with_distance, route_display_geometry)
    rest_with_distance = _items_projected_to_route(rest_with_distance, route_display_geometry)
    resume_with_distance = _items_projected_to_route(resume_with_distance, route_display_geometry)
    mcp_payload = _mcp_payload_projected_to_route(mcp_payload, route_display_geometry)
    route_extent_m = _route_extent_m({}, risk_ribbon, mcp_payload)
    profile = _user_readiness_profile(
        pace_coefficients=pace_coefficients,
        team_status=team_status,
        energy_vitals=energy_vitals,
    )
    route_pressure_profile = _build_route_pressure_profile(
        project_id=project_id,
        generated_at=collected_at,
        segments=segments_with_distance,
        risk_features=risk_features,
        notes=notes_with_distance,
        rest_areas=rest_with_distance,
        resume_segments=resume_with_distance,
        mcp_payload=mcp_payload,
        route_display_geometry=route_display_geometry,
        route_extent_m=route_extent_m,
        pressure_profile_bin_m=pressure_profile_bin_m,
        slow_passage_min_span_m=slow_passage_min_span_m,
        route_mileage_alignment=route_mileage_alignment,
    )

    candidates = _boss_candidates_from_mcp(mcp_payload, named_points)
    candidates.extend(
        _external_pressure_candidates(
            external_pressure_payload,
            route_mileage_alignment=route_mileage_alignment,
            route_display_geometry=route_display_geometry,
        )
    )
    candidates = _merge_route_pressure_peaks_into_candidates(
        candidates,
        route_pressure_profile.get("peaks", []),
        merge_radius_m=max(route_note_radius_m, pressure_profile_bin_m),
    )
    if len(candidates) < top_n:
        candidates.extend(_warning_route_note_candidates(notes_with_distance, existing=candidates))
    local_extent_m = max(
        [route_extent_m, *[_float_or_none(candidate.get("distance_m")) or 0.0 for candidate in candidates]]
    )
    boss_points = []
    for candidate in candidates:
        distance_m = _float_or_none(candidate.get("distance_m"))
        coordinate = _boss_candidate_coordinate(
            candidate,
            distance_m=distance_m,
            route_display_geometry=route_display_geometry,
        )
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
            slow_passage_min_span_m=slow_passage_min_span_m,
        )
        challenge_fit = _challenge_fit(demand, profile, candidate)
        display_mileage = _boss_display_mileage(
            candidate,
            distance_m=distance_m,
            route_mileage_alignment=route_mileage_alignment,
        )
        boss_points.append(
            {
                "source_candidate_id": candidate.get("candidate_id"),
                "source_mcp_id": candidate.get("mcp_id"),
                "label": candidate.get("label") or "Unnamed boss point",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "human_review_required": True,
                "lat": coordinate["lat"],
                "lon": coordinate["lon"],
                "coordinate_source": coordinate["coordinate_source"],
                "source_coordinate": coordinate.get("source_coordinate"),
                "display_mileage": display_mileage,
                "route_position": {
                    "distance_m": _round(distance_m),
                    "route_progress_ratio": _round(_safe_ratio(distance_m, route_extent_m)),
                    "local_evidence_progress_ratio": _round(
                        _safe_ratio(distance_m, local_extent_m)
                    ),
                },
                "mcp_classes": candidate.get("mcp_classes") or [],
                "linked_named_points": candidate.get("linked_named_points") or [],
                "route_pressure_peak_id": (
                    candidate.get("route_pressure_profile") or {}
                ).get("pressure_peak_id"),
                "route_boss_demand": demand,
                "challenge_fit": challenge_fit,
                "evidence_summary": {
                    "nearby_route_note_count": len(nearby_notes),
                    "nearby_warning_note_count": sum(
                        1 for note in nearby_notes if _contains_terms(_note_text(note), WARNING_NAME_TERMS)
                    ),
                    "nearby_rest_area_count": len(nearby_rest),
                    "nearby_resume_segment_count": len(nearby_resume),
                    "slow_passage": demand["slow_passage"],
                    "rest_stop_context": demand["rest_stop_context"],
                    "route_pressure_profile": demand["route_pressure_profile"],
                    "max_risk_score": risk_summary["max_risk_score"],
                    "risk_feature_count": risk_summary["feature_count"],
                    "named_point_evidence": candidate.get("named_point_evidence"),
                    "external_pressure_candidate": candidate.get(
                        "external_pressure_candidate"
                    ),
                },
                "source_refs": _dedupe(
                    [
                        str(route_notes_path.relative_to(root)) if route_notes_path.is_relative_to(root) else str(route_notes_path),
                        str(mcp_path.relative_to(root)) if mcp_path.is_relative_to(root) else str(mcp_path),
                        str(risk_ribbon_path.relative_to(root)) if risk_ribbon_path.is_relative_to(root) else str(risk_ribbon_path),
                        str(segment_display_geometry_path.relative_to(root)) if segment_display_geometry_path.is_relative_to(root) else str(segment_display_geometry_path),
                        str(route_mileage_anchors_path.relative_to(root)) if route_mileage_anchors_path.is_relative_to(root) else str(route_mileage_anchors_path),
                        str(external_pressure_path.relative_to(root)) if external_pressure_path.is_relative_to(root) else str(external_pressure_path),
                    ]
                ),
            }
        )

    for point in boss_points:
        point["boss_selection"] = _boss_selection(point)
    boss_points = sorted(
        boss_points,
        key=lambda item: item["boss_selection"]["score"],
        reverse=True,
    )[: max(0, int(top_n))]
    for index, point in enumerate(boss_points):
        point["rank"] = index + 1
        point["boss_point_id"] = f"boss.{project_id}.{index + 1:03d}"
        point["display_theme"] = BOSS_THEMES[index % len(BOSS_THEMES)]
        point["map_label"] = _boss_map_label(point)

    payload = {
        "artifact_kind": BOSS_POINT_SYNTHESIS_ARTIFACT_KIND,
        "schema_version": BOSS_POINT_SYNTHESIS_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "status": "completed" if boss_points else "missing_candidate_evidence",
        "top_n": top_n,
        "policy": {
            "slow_passage_min_span_m": _round(float(slow_passage_min_span_m)),
            "slow_passage_method": (
                "slow movement must span at least the configured route distance "
                "before it can add observed impedance"
            ),
            "rest_stop_evidence_deemphasized": True,
            "rest_stop_terms": list(REST_STOP_TERMS),
            "pressure_profile_bin_m": _round(float(pressure_profile_bin_m)),
            "pressure_profile_method": (
                "score the full route in fixed distance bins, select local "
                "pressure peaks, then merge those peaks with MCP/named-point/"
                "review evidence before Boss ranking"
            ),
            "centerline": "overpass_risk_ribbon",
            "risk_distance_axis": "overpass_risk_ribbon_distance",
            "gpx_evidence_axis": "projected_to_overpass_risk_ribbon",
            "boss_coordinate_source": "overpass_risk_ribbon_route_distance_interpolation",
            "display_mileage_source": "route_mileage_k_anchors_when_available",
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "route_mileage_alignment": route_mileage_alignment,
        "route_pressure_profile_ref": ROUTE_PRESSURE_PROFILE_REF,
        "route_pressure_profile_geojson_ref": ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
        "route_pressure_profile_summary": _route_pressure_profile_summary(
            route_pressure_profile
        ),
        "boss_points_ref": BOSS_POINTS_REF,
        "boss_points_geojson_ref": BOSS_POINTS_GEOJSON_REF,
        "boss_point_count": len(boss_points),
        "boss_points": boss_points,
        "challenge_fit_summary": _challenge_fit_summary(boss_points, profile),
        "source_report": _source_report(
            [
                ("checkpoints", checkpoints_path, bool(checkpoints), True),
                ("segments", segments_path, bool(segments), True),
                ("route_notes", route_notes_path, bool(pressure_route_notes), False),
                ("risk_ribbon", risk_ribbon_path, bool(risk_features), False),
                (
                    "segment_display_geometry",
                    segment_display_geometry_path,
                    bool(route_display_geometry.get("display_point_count")),
                    False,
                ),
                ("route_pressure_profile", root / ROUTE_PRESSURE_PROFILE_REF, bool(route_pressure_profile.get("samples")), False),
                ("mcp_candidates", mcp_path, bool(mcp_payload), True),
                ("named_point_evidence", named_points_path, bool(named_points_payload), False),
                ("rest_area_candidates", rest_area_path, bool(rest_with_distance), False),
                ("resume_segments", resume_path, bool(resume_with_distance), False),
                ("incident_context", incident_path, bool(incident_context), False),
                ("weather_daylight", weather_path, bool(weather_daylight), False),
                ("pace_coefficients", pace_path, bool(pace_coefficients), False),
                ("team_status", team_status_path, bool(team_status), False),
                ("energy_vitals", energy_path, bool(energy_vitals), False),
                ("route_mileage_k_anchors", route_mileage_anchors_path, bool(route_mileage_anchors), False),
                ("route_pressure_external_candidates", external_pressure_path, bool(external_pressure_payload), False),
            ]
        ),
        "boundary": _closed_boundary(workspace_file_mutation_allowed=not dry_run),
    }
    geojson = _boss_points_geojson(payload)
    route_pressure_geojson = _route_pressure_profile_geojson(route_pressure_profile)

    if not dry_run:
        _write_json(root / ROUTE_PRESSURE_PROFILE_REF, route_pressure_profile)
        _write_json(root / ROUTE_PRESSURE_PROFILE_GEOJSON_REF, route_pressure_geojson)
        _write_json(root / BOSS_POINTS_REF, payload)
        _write_json(root / BOSS_POINTS_GEOJSON_REF, geojson)
        if project_path.exists():
            _write_json(
                project_path,
                {
                    **project,
                    "boss_points_ref": BOSS_POINTS_REF,
                    "boss_points_geojson_ref": BOSS_POINTS_GEOJSON_REF,
                    "route_pressure_profile_ref": ROUTE_PRESSURE_PROFILE_REF,
                    "route_pressure_profile_geojson_ref": ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
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


def _merge_route_pressure_peaks_into_candidates(
    candidates: list[dict[str, Any]],
    peaks: list[dict[str, Any]],
    *,
    merge_radius_m: float,
) -> list[dict[str, Any]]:
    merged = [dict(candidate) for candidate in candidates]
    consumed_peak_ids: set[str] = set()
    for candidate in merged:
        distance = _float_or_none(candidate.get("distance_m"))
        if distance is None:
            continue
        nearest = _nearest_pressure_peak(peaks, distance, merge_radius_m)
        if nearest is None:
            continue
        candidate["route_pressure_profile"] = nearest
        peak_lat = _float_or_none(nearest.get("lat"))
        peak_lon = _float_or_none(nearest.get("lon"))
        if peak_lat is not None and peak_lon is not None:
            candidate["lat"] = peak_lat
            candidate["lon"] = peak_lon
            candidate["coordinate_source"] = (
                nearest.get("coordinate_source")
                or "overpass_risk_ribbon_route_distance_interpolation"
            )
        if nearest.get("pressure_peak_id"):
            consumed_peak_ids.add(str(nearest["pressure_peak_id"]))
        score_components = dict(candidate.get("mcp_score_components") or {})
        profile_score = _float_or_none(nearest.get("route_pressure_score")) or 0.0
        score_components["route_pressure_profile_score"] = _round(profile_score)
        score_components["terrain_risk_support"] = max(
            _float_or_none(score_components.get("terrain_risk_support")) or 0.0,
            _clamp(profile_score / 6.0, 0.0, 18.0),
        )
        candidate["mcp_score_components"] = score_components

    for peak in peaks:
        peak_id = str(peak.get("pressure_peak_id") or "")
        if peak_id in consumed_peak_ids:
            continue
        distance = _float_or_none(peak.get("mid_distance_m"))
        if distance is None:
            continue
        if _nearest_candidate_by_distance(merged, distance, merge_radius_m) is not None:
            continue
        profile_score = _float_or_none(peak.get("route_pressure_score")) or 0.0
        classes = ["route_pressure_peak"]
        max_risk = _float_or_none(
            ((peak.get("components") or {}).get("risk_pressure") or 0.0) * 3.0
        ) or 0.0
        if max_risk >= 65.0:
            classes.append("extreme_terrain_hazard")
        merged.append(
            {
                "candidate_id": peak_id or f"route_pressure_peak.{int(distance):06d}",
                "mcp_id": None,
                "label": peak.get("label") or _pressure_peak_label(peak),
                "lat": peak.get("lat"),
                "lon": peak.get("lon"),
                "coordinate_source": (
                    peak.get("coordinate_source")
                    or "overpass_risk_ribbon_route_distance_interpolation"
                ),
                "distance_m": distance,
                "mcp_classes": classes,
                "linked_named_points": [],
                "linked_risk_segments": peak.get("risk_segment_ids") or [],
                "mcp_score_components": {
                    "total": _round(profile_score),
                    "terrain_risk_support": _clamp(profile_score / 6.0, 0.0, 18.0),
                    "route_pressure_profile_score": _round(profile_score),
                },
                "mention_ratio": None,
                "accepted_evidence_page_count": 0,
                "source_family_coverage": {},
                "named_point_evidence": [],
                "route_pressure_profile": peak,
            }
        )
    return merged


def _nearest_pressure_peak(
    peaks: list[dict[str, Any]],
    distance_m: float,
    radius_m: float,
) -> dict[str, Any] | None:
    return _nearest_candidate_by_distance(peaks, distance_m, radius_m, key="mid_distance_m")


def _nearest_candidate_by_distance(
    candidates: list[dict[str, Any]],
    distance_m: float,
    radius_m: float,
    *,
    key: str = "distance_m",
) -> dict[str, Any] | None:
    nearest: tuple[float, dict[str, Any]] | None = None
    for candidate in candidates:
        candidate_distance = _float_or_none(candidate.get(key))
        if candidate_distance is None:
            continue
        delta = abs(candidate_distance - distance_m)
        if delta > radius_m:
            continue
        if nearest is None or delta < nearest[0]:
            nearest = (delta, candidate)
    return nearest[1] if nearest else None


def _pressure_peak_label(peak: dict[str, Any]) -> str:
    display_mileage = peak.get("display_mileage")
    if isinstance(display_mileage, dict):
        label = str(display_mileage.get("label") or "").strip()
        status = str(display_mileage.get("alignment_status") or "")
        if label and status not in {"missing_alignment", "outside_anchor_range"}:
            band = {
                "pressure_extreme": "極高壓",
                "pressure_high": "高壓",
                "pressure_watch": "注意",
            }.get(str(peak.get("band") or ""), "壓力")
            return f"高壓路段 {label}（{band}）"
    km = (_float_or_none(peak.get("mid_distance_m")) or 0.0) / 1000.0
    band = {
        "pressure_extreme": "極高壓",
        "pressure_high": "高壓",
        "pressure_watch": "注意",
    }.get(str(peak.get("band") or ""), "壓力")
    return f"高壓路段 {km:.1f}K（{band}）"


def _route_coordinate_source(route_display_geometry: dict[str, Any]) -> str:
    if route_display_geometry.get("evidence_type") == "pretrip_overpass_risk_ribbon_centerline":
        return "overpass_risk_ribbon_route_distance_interpolation"
    return "route_distance_interpolation"


def _route_mileage_alignment_from_anchors(
    payload: dict[str, Any],
    *,
    route_display_geometry: dict[str, Any],
    source_ref: str,
) -> dict[str, Any]:
    anchors = []
    for anchor in _payload_list(payload, "anchors"):
        mileage_m = _float_or_none(anchor.get("mileage_m"))
        if mileage_m is None:
            mileage_k = _float_or_none(anchor.get("mileage_k"))
            mileage_m = mileage_k * 1000.0 if mileage_k is not None else None
        lat = _float_or_none(anchor.get("lat"))
        lon = _float_or_none(anchor.get("lon"))
        reasons = [str(value) for value in anchor.get("review_reasons") or []]
        if mileage_m is None or lat is None or lon is None:
            continue
        projection = _nearest_route_projection(route_display_geometry, {"lat": lat, "lon": lon})
        if projection is None:
            continue
        route_distance = _float_or_none(projection.get("route_distance_m"))
        route_offset = _float_or_none(projection.get("distance_to_route_m"))
        raw_labels = [str(value) for value in anchor.get("raw_label_examples") or []]
        rejected_reasons = []
        if any("exceeds_route_summary_distance" == reason for reason in reasons):
            rejected_reasons.append("exceeds_route_summary_distance")
        if route_offset is not None and route_offset > 500.0:
            rejected_reasons.append("far_from_route_centerline")
        if any("投85" in label or "公路" in label for label in raw_labels):
            rejected_reasons.append("road_mileage_label_not_trail_anchor")
        anchors.append(
            {
                "candidate_id": anchor.get("candidate_id"),
                "normalized_mileage_k": anchor.get("normalized_mileage_k")
                or anchor.get("display_label")
                or _format_mileage_label(mileage_m),
                "display_label": anchor.get("display_label")
                or _format_mileage_label(mileage_m),
                "mileage_m": _round(mileage_m),
                "lat": lat,
                "lon": lon,
                "route_distance_m": _round(route_distance),
                "route_projection_distance_m": _round(route_offset),
                "route_projection_status": _projection_alignment_status(route_offset),
                "route_context_key": anchor.get("route_context_key"),
                "source_evidence_count": int(
                    _float_or_none(anchor.get("source_evidence_count")) or 0
                ),
                "review_required": bool(anchor.get("review_required")),
                "review_reasons": reasons,
                "raw_label_examples": raw_labels[:4],
                "rejected_reasons": rejected_reasons,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    candidate_anchors = [
        anchor for anchor in anchors if not anchor.get("rejected_reasons")
    ]
    usable_anchors = _longest_monotonic_mileage_anchor_sequence(candidate_anchors)
    usable_ids = {str(anchor.get("candidate_id")) for anchor in usable_anchors}
    projected_anchors = []
    for anchor in anchors:
        copied = dict(anchor)
        copied["usable_for_interpolation"] = str(anchor.get("candidate_id")) in usable_ids
        if (
            not copied["usable_for_interpolation"]
            and not copied.get("rejected_reasons")
        ):
            copied["rejected_reasons"] = ["non_monotonic_with_main_trail_k_sequence"]
        projected_anchors.append(copied)

    return {
        "artifact_kind": "pretrip_route_mileage_alignment",
        "schema_version": "route_mileage_alignment.v1",
        "source_ref": source_ref,
        "projected_anchor_count": len(projected_anchors),
        "usable_anchor_count": len(usable_anchors),
        "rejected_anchor_count": len(projected_anchors) - len(usable_anchors),
        "usable_anchors": usable_anchors,
        "projected_anchors": projected_anchors,
        "policy": {
            "route_axis": "overpass_risk_ribbon_distance",
            "display_axis": "trail_mileage_k_anchor",
            "standalone_k_anchor_allowed": False,
            "main_sequence_selection": "longest_monotonic_route_distance_sequence",
            "public_k_labels_are_candidate_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _longest_monotonic_mileage_anchor_sequence(
    anchors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        anchors,
        key=lambda item: (
            _float_or_none(item.get("mileage_m")) or 0.0,
            _float_or_none(item.get("route_distance_m")) or 0.0,
        ),
    )
    if not ordered:
        return []
    tolerance_m = 750.0
    best_score = [1.0 for _ in ordered]
    previous_index: list[int | None] = [None for _ in ordered]
    for current_index, current in enumerate(ordered):
        current_mileage = _float_or_none(current.get("mileage_m"))
        current_route = _float_or_none(current.get("route_distance_m"))
        if current_mileage is None or current_route is None:
            continue
        for previous, previous_anchor in enumerate(ordered[:current_index]):
            previous_mileage = _float_or_none(previous_anchor.get("mileage_m"))
            previous_route = _float_or_none(previous_anchor.get("route_distance_m"))
            if previous_mileage is None or previous_route is None:
                continue
            if current_mileage < previous_mileage:
                continue
            if current_route + tolerance_m < previous_route:
                continue
            evidence_weight = min(
                0.25,
                ((_float_or_none(current.get("source_evidence_count")) or 0.0) / 40.0),
            )
            score = best_score[previous] + 1.0 + evidence_weight
            if score > best_score[current_index]:
                best_score[current_index] = score
                previous_index[current_index] = previous
    index = max(range(len(ordered)), key=lambda value: best_score[value])
    sequence = []
    while index is not None:
        sequence.append(dict(ordered[index]))
        index = previous_index[index]
    sequence.reverse()
    return sequence


def _route_distance_for_display_mileage(
    alignment: dict[str, Any],
    mileage_m: Any,
) -> dict[str, Any]:
    target = _float_or_none(mileage_m)
    anchors = _sorted_usable_mileage_anchors(alignment, key="mileage_m")
    if target is None or not anchors:
        return {
            "route_distance_m": None,
            "alignment_status": "missing_alignment",
            "source_ref": alignment.get("source_ref"),
        }
    exact = min(
        anchors,
        key=lambda item: abs((_float_or_none(item.get("mileage_m")) or 0.0) - target),
    )
    exact_delta = abs((_float_or_none(exact.get("mileage_m")) or 0.0) - target)
    if exact_delta <= 1.0:
        return {
            "route_distance_m": _round(_float_or_none(exact.get("route_distance_m"))),
            "alignment_status": "matched_mileage_anchor",
            "source_ref": alignment.get("source_ref"),
            "anchor_label": exact.get("display_label"),
        }
    lower = None
    upper = None
    for anchor in anchors:
        mileage = _float_or_none(anchor.get("mileage_m"))
        if mileage is None:
            continue
        if mileage < target:
            lower = anchor
        elif mileage > target and upper is None:
            upper = anchor
            break
    if lower is not None and upper is not None:
        route_distance = _interpolate_anchor_axis(
            lower,
            upper,
            target=target,
            source_key="mileage_m",
            target_key="route_distance_m",
        )
        return {
            "route_distance_m": _round(route_distance),
            "alignment_status": "interpolated_between_mileage_anchors",
            "source_ref": alignment.get("source_ref"),
            "lower_anchor_label": lower.get("display_label"),
            "upper_anchor_label": upper.get("display_label"),
        }
    if lower is not None:
        extrapolated = _extrapolate_from_anchor_tail(
            anchors,
            target=target,
            source_key="mileage_m",
            target_key="route_distance_m",
            tail="upper",
            max_delta_m=1000.0,
        )
        if extrapolated is not None:
            return {
                "route_distance_m": _round(extrapolated),
                "alignment_status": "extrapolated_after_last_mileage_anchor",
                "source_ref": alignment.get("source_ref"),
                "anchor_label": lower.get("display_label"),
            }
    if upper is not None:
        extrapolated = _extrapolate_from_anchor_tail(
            anchors,
            target=target,
            source_key="mileage_m",
            target_key="route_distance_m",
            tail="lower",
            max_delta_m=1000.0,
        )
        if extrapolated is not None:
            return {
                "route_distance_m": _round(extrapolated),
                "alignment_status": "extrapolated_before_first_mileage_anchor",
                "source_ref": alignment.get("source_ref"),
                "anchor_label": upper.get("display_label"),
            }
    return {
        "route_distance_m": _round(target),
        "alignment_status": "outside_trail_k_anchor_range_route_distance_passthrough",
        "source_ref": alignment.get("source_ref"),
    }


def _display_mileage_for_route_distance(
    alignment: dict[str, Any],
    distance_m: Any,
) -> dict[str, Any]:
    target = _float_or_none(distance_m)
    anchors = _sorted_usable_mileage_anchors(alignment, key="route_distance_m")
    if target is None or not anchors:
        return {
            "label": "K待校正",
            "mileage_m": None,
            "alignment_status": "missing_alignment",
            "source_ref": alignment.get("source_ref"),
        }
    exact = min(
        anchors,
        key=lambda item: abs((_float_or_none(item.get("route_distance_m")) or 0.0) - target),
    )
    exact_delta = abs((_float_or_none(exact.get("route_distance_m")) or 0.0) - target)
    if exact_delta <= 25.0:
        mileage = _float_or_none(exact.get("mileage_m"))
        return {
            "label": _format_mileage_label(mileage),
            "mileage_m": _round(mileage),
            "route_distance_m": _round(target),
            "alignment_status": "matched_mileage_anchor",
            "source_ref": alignment.get("source_ref"),
            "anchor_label": exact.get("display_label"),
        }
    lower = None
    upper = None
    for anchor in anchors:
        route_distance = _float_or_none(anchor.get("route_distance_m"))
        if route_distance is None:
            continue
        if route_distance < target:
            lower = anchor
        elif route_distance > target and upper is None:
            upper = anchor
            break
    mileage = None
    status = "outside_anchor_range"
    extra: dict[str, Any] = {}
    if lower is not None and upper is not None:
        mileage = _interpolate_anchor_axis(
            lower,
            upper,
            target=target,
            source_key="route_distance_m",
            target_key="mileage_m",
        )
        status = "interpolated_between_mileage_anchors"
        extra = {
            "lower_anchor_label": lower.get("display_label"),
            "upper_anchor_label": upper.get("display_label"),
        }
    elif lower is not None:
        mileage = _extrapolate_from_anchor_tail(
            anchors,
            target=target,
            source_key="route_distance_m",
            target_key="mileage_m",
            tail="upper",
            max_delta_m=1000.0,
        )
        if mileage is not None:
            status = "extrapolated_after_last_mileage_anchor"
            extra = {"anchor_label": lower.get("display_label")}
    elif upper is not None:
        mileage = _extrapolate_from_anchor_tail(
            anchors,
            target=target,
            source_key="route_distance_m",
            target_key="mileage_m",
            tail="lower",
            max_delta_m=1000.0,
        )
        if mileage is not None:
            status = "extrapolated_before_first_mileage_anchor"
            extra = {"anchor_label": upper.get("display_label")}
    return {
        "label": _format_mileage_label(mileage) if mileage is not None else "K待校正",
        "mileage_m": _round(mileage) if mileage is not None else None,
        "route_distance_m": _round(target),
        "alignment_status": status,
        "source_ref": alignment.get("source_ref"),
        **extra,
    }


def _sorted_usable_mileage_anchors(
    alignment: dict[str, Any],
    *,
    key: str,
) -> list[dict[str, Any]]:
    anchors = [
        anchor
        for anchor in alignment.get("usable_anchors") or []
        if _float_or_none(anchor.get("mileage_m")) is not None
        and _float_or_none(anchor.get("route_distance_m")) is not None
    ]
    return sorted(anchors, key=lambda item: _float_or_none(item.get(key)) or 0.0)


def _interpolate_anchor_axis(
    lower: dict[str, Any],
    upper: dict[str, Any],
    *,
    target: float,
    source_key: str,
    target_key: str,
) -> float | None:
    lower_source = _float_or_none(lower.get(source_key))
    upper_source = _float_or_none(upper.get(source_key))
    lower_target = _float_or_none(lower.get(target_key))
    upper_target = _float_or_none(upper.get(target_key))
    if None in {lower_source, upper_source, lower_target, upper_target}:
        return None
    denominator = upper_source - lower_source
    if abs(denominator) <= 0.0001:
        return lower_target
    ratio = (target - lower_source) / denominator
    return lower_target + (upper_target - lower_target) * ratio


def _extrapolate_from_anchor_tail(
    anchors: list[dict[str, Any]],
    *,
    target: float,
    source_key: str,
    target_key: str,
    tail: str,
    max_delta_m: float,
) -> float | None:
    if len(anchors) < 2:
        return None
    pair = anchors[:2] if tail == "lower" else anchors[-2:]
    anchor = pair[0] if tail == "lower" else pair[-1]
    anchor_source = _float_or_none(anchor.get(source_key))
    if anchor_source is None or abs(target - anchor_source) > max_delta_m:
        return None
    return _interpolate_anchor_axis(
        pair[0],
        pair[1],
        target=target,
        source_key=source_key,
        target_key=target_key,
    )


def _format_mileage_label(mileage_m: Any) -> str:
    value = _float_or_none(mileage_m)
    if value is None:
        return "K待校正"
    km = value / 1000.0
    if abs(km - round(km)) < 0.05:
        return f"{int(round(km))}K"
    return f"{km:.1f}K"


def _format_mileage_span_label(start_m: Any, end_m: Any) -> str:
    start = _float_or_none(start_m)
    end = _float_or_none(end_m)
    if start is None and end is None:
        return "K待校正"
    if start is None:
        return _format_mileage_label(end)
    if end is None or abs(start - end) <= 1.0:
        return _format_mileage_label(start)
    return f"{_format_mileage_label(start)}-{_format_mileage_label(end)}"


def _external_pressure_candidates(
    payload: dict[str, Any],
    *,
    route_mileage_alignment: dict[str, Any],
    route_display_geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for item in _payload_list(payload, "candidates"):
        start_m = _float_or_none(item.get("route_distance_start_m"))
        end_m = _float_or_none(item.get("route_distance_end_m"))
        if start_m is None and end_m is None:
            continue
        if start_m is None:
            start_m = end_m
        if end_m is None:
            end_m = start_m
        assert start_m is not None and end_m is not None
        midpoint_m = (start_m + end_m) / 2.0
        route_alignment = _route_distance_for_display_mileage(
            route_mileage_alignment,
            midpoint_m,
        )
        route_distance = _float_or_none(route_alignment.get("route_distance_m"))
        if route_distance is None:
            continue
        route_coordinate = _route_coordinate_at_distance(route_display_geometry, route_distance)
        classes = _external_pressure_classes(item)
        external_score = _float_or_none(item.get("external_pressure_score")) or 0.0
        candidates.append(
            {
                "candidate_id": item.get("candidate_id"),
                "label": item.get("label"),
                "lat": route_coordinate.get("lat") if route_coordinate else None,
                "lon": route_coordinate.get("lon") if route_coordinate else None,
                "coordinate_source": "route_mileage_anchor_interpolated_pressure_span",
                "distance_m": route_distance,
                "mcp_classes": classes,
                "linked_named_points": [],
                "linked_risk_segments": [],
                "mcp_score_components": {
                    "total": _round(external_score),
                    "terrain_risk_support": _round(_clamp(external_score / 5.0, 0, 18)),
                    "external_pressure_score": _round(external_score),
                },
                "mention_ratio": None,
                "accepted_evidence_page_count": len(item.get("source_refs") or []),
                "source_family_coverage": _external_source_family_coverage(item),
                "named_point_evidence": [],
                "external_pressure_score": _round(external_score),
                "external_pressure_candidate": _compact_external_pressure_candidate(item),
                "route_mileage_span": {
                    "label": _format_mileage_span_label(start_m, end_m),
                    "start_m": _round(start_m),
                    "end_m": _round(end_m),
                    "midpoint_m": _round(midpoint_m),
                    "public_route_distance_label": item.get("public_route_distance_label"),
                    "route_distance_m": _round(route_distance),
                    "route_alignment": route_alignment,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    return candidates


def _external_pressure_classes(item: dict[str, Any]) -> list[str]:
    reasons = {str(value) for value in item.get("pressure_reason") or []}
    classes = {"route_pressure_peak"}
    if reasons.intersection(
        {
            "collapse_wall",
            "loose_surface",
            "rockfall_attention",
            "steep_descent",
            "wet_slippery",
            "fall_attention",
            "rain_typhoon_sensitive",
        }
    ):
        classes.add("extreme_terrain_hazard")
    if reasons.intersection({"dense_bamboo", "route_ambiguity"}):
        classes.add("hidden_forest_route_loss")
    if reasons.intersection({"bridge_passage", "official_notice", "route_start_attention"}):
        classes.add("route_note_warning")
    if reasons.intersection({"heavy_pack", "long_distance", "energy_reserve", "training_requirement"}):
        classes.add("route_pressure_peak")
    return sorted(classes)


def _external_source_family_coverage(item: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ref in item.get("source_refs") or []:
        if not isinstance(ref, dict):
            continue
        family = str(ref.get("family") or ref.get("tier") or "unknown")
        counts[family] = counts.get(family, 0) + 1
    return counts


def _compact_external_pressure_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": item.get("candidate_id"),
        "label": item.get("label"),
        "public_route_distance_label": item.get("public_route_distance_label"),
        "pressure_reason": item.get("pressure_reason") or [],
        "summary": item.get("summary"),
        "external_pressure_score": item.get("external_pressure_score"),
        "confidence": item.get("confidence"),
        "source_ref_count": len(item.get("source_refs") or []),
        "source_refs": item.get("source_refs") or [],
        "requires_human_review": bool(item.get("requires_human_review", True)),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _boss_display_mileage(
    candidate: dict[str, Any],
    *,
    distance_m: float | None,
    route_mileage_alignment: dict[str, Any],
) -> dict[str, Any]:
    span = candidate.get("route_mileage_span")
    if isinstance(span, dict):
        return {
            "label": span.get("label") or "K待校正",
            "start_m": span.get("start_m"),
            "end_m": span.get("end_m"),
            "midpoint_m": span.get("midpoint_m"),
            "route_distance_m": _round(distance_m),
            "alignment_status": (
                (span.get("route_alignment") or {}).get("alignment_status")
                if isinstance(span.get("route_alignment"), dict)
                else "external_pressure_span"
            ),
            "source_ref": route_mileage_alignment.get("source_ref"),
            "public_route_distance_label": span.get("public_route_distance_label"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    display = _display_mileage_for_route_distance(
        route_mileage_alignment,
        distance_m,
    )
    return {
        **display,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _boss_map_label(point: dict[str, Any]) -> str:
    alias = str((point.get("display_theme") or {}).get("alias") or "Boss").strip()
    mileage = point.get("display_mileage") if isinstance(point.get("display_mileage"), dict) else {}
    mileage_label = str(mileage.get("label") or "").strip()
    if mileage_label and mileage_label != "K待校正":
        return f"{alias} {mileage_label}"
    return alias


def _boss_selection(point: dict[str, Any]) -> dict[str, Any]:
    demand_score = _float_or_none(
        (point.get("route_boss_demand") or {}).get("score")
    ) or 0.0
    display_mileage = (
        point.get("display_mileage")
        if isinstance(point.get("display_mileage"), dict)
        else {}
    )
    display_label = str(display_mileage.get("label") or "").strip()
    has_display_mileage = bool(display_label and display_label != "K待校正")
    external = bool(
        (point.get("evidence_summary") or {}).get("external_pressure_candidate")
    )
    source_candidate_id = str(point.get("source_candidate_id") or "")
    pure_route_pressure_peak = source_candidate_id.startswith("route_pressure_peak.")
    display_bonus = 8.0 if has_display_mileage else 0.0
    public_pressure_bonus = 18.0 if external else 0.0
    missing_display_penalty = (
        -25.0 if pure_route_pressure_peak and not has_display_mileage else 0.0
    )
    score = _clamp(
        demand_score + display_bonus + public_pressure_bonus + missing_display_penalty,
        0,
        120,
    )
    return {
        "score": _round(score),
        "route_boss_demand_score": _round(demand_score),
        "display_mileage_bonus": _round(display_bonus),
        "public_pressure_bonus": _round(public_pressure_bonus),
        "missing_display_mileage_penalty": _round(missing_display_penalty),
        "has_display_mileage": has_display_mileage,
        "external_pressure_supported": external,
        "formula": (
            "route_boss_demand + display_mileage_bonus + "
            "public_pressure_bonus + missing_display_mileage_penalty"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _boss_candidate_coordinate(
    candidate: dict[str, Any],
    *,
    distance_m: float | None,
    route_display_geometry: dict[str, Any],
) -> dict[str, Any]:
    source_coordinate = {
        "lat": _float_or_none(candidate.get("lat")),
        "lon": _float_or_none(candidate.get("lon")),
        "coordinate_source": candidate.get("coordinate_source"),
    }
    route_coordinate = _route_coordinate_at_distance(route_display_geometry, distance_m)
    if route_coordinate is not None:
        return {
            "lat": route_coordinate["lat"],
            "lon": route_coordinate["lon"],
            "coordinate_source": _route_coordinate_source(route_display_geometry),
            "source_coordinate": source_coordinate,
        }

    route_pressure = (
        candidate.get("route_pressure_profile")
        if isinstance(candidate.get("route_pressure_profile"), dict)
        else {}
    )
    pressure_lat = _float_or_none(route_pressure.get("lat"))
    pressure_lon = _float_or_none(route_pressure.get("lon"))
    if pressure_lat is not None and pressure_lon is not None:
        return {
            "lat": pressure_lat,
            "lon": pressure_lon,
            "coordinate_source": route_pressure.get("coordinate_source")
            or "route_pressure_profile_coordinate",
            "source_coordinate": source_coordinate,
        }

    if source_coordinate["lat"] is not None and source_coordinate["lon"] is not None:
        return {
            "lat": source_coordinate["lat"],
            "lon": source_coordinate["lon"],
            "coordinate_source": source_coordinate["coordinate_source"]
            or "source_candidate_coordinate_fallback",
            "source_coordinate": source_coordinate,
        }
    return {
        "lat": None,
        "lon": None,
        "coordinate_source": "missing_coordinate",
        "source_coordinate": source_coordinate,
    }


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
    slow_passage_min_span_m: float,
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
    slow_passage = _slow_passage_summary(
        nearby_notes,
        min_span_m=slow_passage_min_span_m,
    )
    effective_slow_note_count = int(slow_passage["effective_note_count"])
    rest_note_count = sum(1 for note in nearby_notes if _contains_terms(_note_text(note), REST_TERMS))

    mcp_score = _float_or_none((candidate.get("mcp_score_components") or {}).get("total")) or 0.0
    terrain_risk_support = _float_or_none(
        (candidate.get("mcp_score_components") or {}).get("terrain_risk_support")
    ) or 0.0
    route_pressure = (
        candidate.get("route_pressure_profile")
        if isinstance(candidate.get("route_pressure_profile"), dict)
        else {}
    )
    route_pressure_score = _float_or_none(route_pressure.get("route_pressure_score")) or 0.0
    external_pressure_score = (
        _float_or_none(candidate.get("external_pressure_score"))
        or _float_or_none(
            (candidate.get("mcp_score_components") or {}).get("external_pressure_score")
        )
        or 0.0
    )
    max_risk_score = _float_or_none(risk_summary.get("max_risk_score")) or 0.0
    incident_text = json.dumps(incident_context, ensure_ascii=False)
    weather_text = json.dumps(weather_daylight, ensure_ascii=False)
    incident_terms_present = _contains_terms(
        incident_text, ("山難", "救援", "迷途", "墜", "失溫", "落石", "事故", "near_miss")
    )
    weather_terms_present = _contains_terms(weather_text, ("fog", "霧", "雨", "wind", "低溫", "daylight", "摸黑"))

    class_bonus = max((TERRAIN_CLASS_BONUS.get(value, 0.0) for value in classes), default=0.0)
    rest_stop_likely = bool(
        nearby_rest
        or rest_note_count
        or classes.intersection({"camp_hut_structure", "water_source"})
    )
    hard_obstacle_evidence = bool(
        slow_passage["qualified"]
        or warning_note_count
        or _contains_terms(label, WARNING_NAME_TERMS)
        or class_bonus >= 8.0
        or route_pressure_score >= 45.0
        or terrain_risk_support > 0
        or max_risk_score >= 70.0
    )
    rest_stop_deemphasis_multiplier = (
        0.72 if rest_stop_likely and not hard_obstacle_evidence else 1.0
    )
    components = {
        "observed_impedance": _clamp(
            effective_slow_note_count * 3
            + warning_note_count * 3
            + (4 if slow_passage["qualified"] else 0),
            0,
            14,
        ),
        "route_note_consensus": _clamp(
            source_family_count * 3
            + warning_note_count * 3
            + effective_slow_note_count * 2
            + (_float_or_none(candidate.get("mention_ratio")) or 0.0) * 10,
            0,
            16,
        ),
        "rest_cluster": 0.0,
        "terrain_risk": _clamp(
            max_risk_score / 8 + terrain_risk_support / 2 + class_bonus,
            0,
            24,
        ),
        "route_pressure_profile": _clamp(route_pressure_score / 5.0, 0, 18),
        "public_pressure_consensus": _clamp(external_pressure_score / 5.0, 0, 18),
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
    score = _clamp(
        sum(components.values()) * late_multiplier * rest_stop_deemphasis_multiplier,
        0,
        100,
    )
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
        "route_pressure_profile": {
            "pressure_peak_id": route_pressure.get("pressure_peak_id"),
            "route_pressure_score": _round(route_pressure_score)
            if route_pressure
            else None,
            "rank": route_pressure.get("rank"),
            "band": route_pressure.get("band"),
            "start_distance_m": route_pressure.get("start_distance_m"),
            "end_distance_m": route_pressure.get("end_distance_m"),
            "mid_distance_m": route_pressure.get("mid_distance_m"),
            "sample_count": route_pressure.get("sample_count"),
            "coordinate_source": route_pressure.get("coordinate_source"),
        },
        "external_pressure_candidate": candidate.get("external_pressure_candidate"),
        "slow_passage": slow_passage,
        "rest_stop_context": {
            "nearby_rest_area_count": len(nearby_rest),
            "rest_note_count": rest_note_count,
            "rest_stop_likely": rest_stop_likely,
            "hard_obstacle_evidence": hard_obstacle_evidence,
            "rest_cluster_score_deemphasized": True,
            "rest_stop_deemphasis_multiplier": _round(rest_stop_deemphasis_multiplier),
        },
        "late_trip_multiplier": _round(late_multiplier),
        "evidence_state": "mixed_evidence" if missing_evidence else "multi_source_supported",
        "missing_evidence": missing_evidence,
        "formula": (
            "sum(component_scores) * late_trip_multiplier * "
            "rest_stop_deemphasis_multiplier"
        ),
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
                    "map_label": point.get("map_label"),
                    "display_mileage_label": (
                        point.get("display_mileage") or {}
                    ).get("label"),
                    "display_mileage_status": (
                        point.get("display_mileage") or {}
                    ).get("alignment_status"),
                    "public_route_distance_label": (
                        point.get("display_mileage") or {}
                    ).get("public_route_distance_label"),
                    "display_alias": point["display_theme"]["alias"],
                    "icon_key": point["display_theme"]["icon_key"],
                    "coordinate_source": point.get("coordinate_source"),
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


def _pressure_relevant_route_notes(
    route_notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    relevant_terms = WARNING_NAME_TERMS + REST_TERMS + SLOW_TERMS
    return [
        note
        for note in route_notes
        if _contains_terms(_note_text(note), relevant_terms)
    ]


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


def _segments_with_route_distance(
    segments: list[dict[str, Any]],
    cp_distance: dict[str, float],
) -> list[dict[str, Any]]:
    result = []
    for segment in segments:
        start = cp_distance.get(str(segment.get("from_candidate_id") or ""))
        end = cp_distance.get(str(segment.get("to_candidate_id") or ""))
        copied = dict(segment)
        if start is not None and end is None:
            distance = _float_or_none(segment.get("distance_m")) or 0.0
            end = start + distance
        if start is not None and end is not None:
            copied["start_distance_m"] = min(start, end)
            copied["end_distance_m"] = max(start, end)
            copied["route_distance_m"] = (start + end) / 2.0
        result.append(copied)
    return result


def _route_display_geometry_from_segment_display_geometry(
    *,
    project_id: str,
    segment_display_geometry: dict[str, Any],
    segments: list[dict[str, Any]],
    source_path: str,
) -> dict[str, Any]:
    segments_by_id = {
        str(segment.get("segment_candidate_id") or segment.get("candidate_id") or ""): segment
        for segment in segments
        if segment.get("segment_candidate_id") or segment.get("candidate_id")
    }
    coordinate_segments: list[list[dict[str, float]]] = []
    route_segments: list[dict[str, Any]] = []
    for segment in segment_display_geometry.get("segments") or []:
        if isinstance(segment, dict):
            normalized_segments = _display_coordinate_segments(segment)
            coordinate_segments.extend(normalized_segments)
            segment_id = str(segment.get("segment_candidate_id") or "")
            source_segment = segments_by_id.get(segment_id, {})
            start = _float_or_none(source_segment.get("start_distance_m"))
            end = _float_or_none(source_segment.get("end_distance_m"))
            for coordinate_segment in normalized_segments:
                route_segments.append(
                    {
                        "segment_candidate_id": segment_id,
                        "start_distance_m": start,
                        "end_distance_m": end,
                        "coordinates": coordinate_segment,
                    }
                )
    coordinates = [
        point
        for coordinate_segment in coordinate_segments
        for point in coordinate_segment
    ]
    return {
        "source_id": f"route_display_geometry.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_route_display_geometry",
        "display_point_count": len(coordinates),
        "display_segment_count": len(coordinate_segments),
        "coordinates": coordinates,
        "coordinate_segments": coordinate_segments,
        "route_segments": route_segments,
        "projection_edges": _route_projection_edges_from_segments(route_segments),
        "boundary": {
            "display_geometry_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "gpx_segment_boundary_preserved": True,
        },
    }


def _route_display_geometry_from_risk_ribbon(
    *,
    project_id: str,
    risk_features: list[dict[str, Any]],
    source_path: str,
) -> dict[str, Any]:
    coordinate_segments: list[list[dict[str, float]]] = []
    route_segments: list[dict[str, Any]] = []
    for feature in risk_features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        coordinates = _feature_coordinate_points(feature)
        if len(coordinates) < 2:
            continue
        start = _float_or_none(props.get("start_distance_m"))
        end = _float_or_none(props.get("end_distance_m"))
        coordinate_segments.append(coordinates)
        route_segments.append(
            {
                "segment_candidate_id": props.get("segment_id") or props.get("candidate_id"),
                "start_distance_m": start,
                "end_distance_m": end,
                "coordinates": coordinates,
            }
        )
    coordinates = [
        point
        for coordinate_segment in coordinate_segments
        for point in coordinate_segment
    ]
    return {
        "source_id": f"route_pressure_centerline.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_overpass_risk_ribbon_centerline",
        "display_point_count": len(coordinates),
        "display_segment_count": len(coordinate_segments),
        "coordinates": coordinates,
        "coordinate_segments": coordinate_segments,
        "route_segments": route_segments,
        "projection_edges": _route_projection_edges_from_segments(route_segments),
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "centerline_source": "overpass_risk_ribbon",
            "gpx_used_as_timing_and_behavior_evidence_only": True,
        },
    }


def _route_projection_edges_from_segments(
    route_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for route_segment in route_segments:
        if not isinstance(route_segment, dict):
            continue
        route_start = _float_or_none(route_segment.get("start_distance_m"))
        route_end = _float_or_none(route_segment.get("end_distance_m"))
        coordinates = _normalized_coordinate_segment(route_segment.get("coordinates", []))
        if route_start is None or route_end is None or len(coordinates) < 2:
            continue
        geometry_lengths = [
            _haversine_m(
                previous["lat"],
                previous["lon"],
                current["lat"],
                current["lon"],
            )
            or 0.0
            for previous, current in zip(coordinates, coordinates[1:])
        ]
        geometry_total_m = sum(geometry_lengths)
        if geometry_total_m <= 0:
            continue
        cumulative_m = 0.0
        for index, segment_m in enumerate(geometry_lengths):
            if segment_m <= 0:
                continue
            previous = coordinates[index]
            current = coordinates[index + 1]
            edge_start_ratio = cumulative_m / geometry_total_m
            edge_end_ratio = (cumulative_m + segment_m) / geometry_total_m
            edge_start_m = route_start + (route_end - route_start) * edge_start_ratio
            edge_end_m = route_start + (route_end - route_start) * edge_end_ratio
            edges.append(
                {
                    "segment_candidate_id": route_segment.get("segment_candidate_id"),
                    "start_distance_m": edge_start_m,
                    "end_distance_m": edge_end_m,
                    "start_lat": previous["lat"],
                    "start_lon": previous["lon"],
                    "end_lat": current["lat"],
                    "end_lon": current["lon"],
                    "length_m": segment_m,
                    "min_lat": min(previous["lat"], current["lat"]),
                    "max_lat": max(previous["lat"], current["lat"]),
                    "min_lon": min(previous["lon"], current["lon"]),
                    "max_lon": max(previous["lon"], current["lon"]),
                }
            )
            cumulative_m += segment_m
    return edges


def _items_projected_to_route(
    items: list[dict[str, Any]],
    route_display_geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for item in items:
        copied = dict(item)
        original_distance = _float_or_none(copied.get("route_distance_m")) or _float_or_none(
            copied.get("distance_m")
        )
        if original_distance is not None:
            copied["gpx_route_distance_m"] = original_distance
        lat = _float_or_none(copied.get("lat"))
        lon = _float_or_none(copied.get("lon"))
        projection = _nearest_route_projection(
            route_display_geometry,
            {"lat": lat, "lon": lon},
        )
        if projection is None:
            copied["route_distance_m"] = None
            copied["route_projection_status"] = "missing_coordinate_or_projection"
            projected.append(copied)
            continue
        copied["route_distance_m"] = _round(projection["route_distance_m"])
        copied["route_projection_status"] = _projection_alignment_status(
            projection.get("distance_to_route_m")
        )
        copied["route_projection_distance_m"] = _round(
            projection.get("distance_to_route_m")
        )
        copied["route_projection_axis"] = "overpass_risk_ribbon_centerline"
        copied["route_projection_source_segment_id"] = projection.get("segment_candidate_id")
        projected.append(copied)
    return projected


def _mcp_payload_projected_to_route(
    payload: dict[str, Any],
    route_display_geometry: dict[str, Any],
) -> dict[str, Any]:
    copied = dict(payload)
    copied["mcp_candidates"] = _items_projected_to_route(
        _payload_list(payload, "mcp_candidates"),
        route_display_geometry,
    )
    return copied


def _gpx_segments_projected_to_route(
    segments: list[dict[str, Any]],
    gpx_route_geometry: dict[str, Any],
    route_display_geometry: dict[str, Any],
) -> list[dict[str, Any]]:
    gpx_segments_by_id = {
        str(segment.get("segment_candidate_id") or ""): segment
        for segment in gpx_route_geometry.get("route_segments") or []
        if isinstance(segment, dict) and segment.get("segment_candidate_id")
    }
    projected: list[dict[str, Any]] = []
    for segment in segments:
        copied = dict(segment)
        segment_id = str(segment.get("candidate_id") or segment.get("segment_candidate_id") or "")
        copied["gpx_start_distance_m"] = _float_or_none(segment.get("start_distance_m"))
        copied["gpx_end_distance_m"] = _float_or_none(segment.get("end_distance_m"))
        gpx_geometry = gpx_segments_by_id.get(segment_id)
        coordinates = (
            _normalized_coordinate_segment(gpx_geometry.get("coordinates", []))
            if isinstance(gpx_geometry, dict)
            else []
        )
        if len(coordinates) < 2:
            copied["start_distance_m"] = None
            copied["end_distance_m"] = None
            copied["route_projection_status"] = "missing_gpx_segment_geometry"
            projected.append(copied)
            continue
        start_projection = _nearest_route_projection(route_display_geometry, coordinates[0])
        end_projection = _nearest_route_projection(route_display_geometry, coordinates[-1])
        if start_projection is None or end_projection is None:
            copied["start_distance_m"] = None
            copied["end_distance_m"] = None
            copied["route_projection_status"] = "missing_coordinate_or_projection"
            projected.append(copied)
            continue
        projected_start = start_projection["route_distance_m"]
        projected_end = end_projection["route_distance_m"]
        copied["start_distance_m"] = min(projected_start, projected_end)
        copied["end_distance_m"] = max(projected_start, projected_end)
        copied["route_distance_m"] = (projected_start + projected_end) / 2.0
        max_offset = max(
            start_projection.get("distance_to_route_m") or 0.0,
            end_projection.get("distance_to_route_m") or 0.0,
        )
        copied["route_projection_status"] = _projection_alignment_status(max_offset)
        copied["route_projection_distance_m"] = _round(max_offset)
        copied["route_projection_axis"] = "overpass_risk_ribbon_centerline"
        copied["gpx_interpretability"] = _gpx_segment_interpretability(
            segment,
            coordinates,
            max_projection_distance_m=max_offset,
        )
        projected.append(copied)
    return projected


def _display_coordinate_segments(
    display_geometry: dict[str, Any],
) -> list[list[dict[str, float]]]:
    coordinate_segments = display_geometry.get("coordinate_segments")
    if isinstance(coordinate_segments, list):
        normalized_segments = [
            _normalized_coordinate_segment(segment)
            for segment in coordinate_segments
            if isinstance(segment, list)
        ]
        normalized_segments = [
            segment for segment in normalized_segments if len(segment) >= 2
        ]
        if normalized_segments:
            return normalized_segments
    coordinates = _normalized_coordinate_segment(display_geometry.get("coordinates", []))
    return [coordinates] if len(coordinates) >= 2 else []


def _normalized_coordinate_segment(points: Any) -> list[dict[str, float]]:
    if not isinstance(points, list):
        return []
    result = []
    for point in points:
        if not isinstance(point, dict):
            continue
        lat = _float_or_none(point.get("lat"))
        lon = _float_or_none(point.get("lon"))
        if lat is None or lon is None:
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        result.append({"lat": lat, "lon": lon})
    return result


def _route_coordinate_at_distance(
    display_geometry: dict[str, Any] | None,
    distance_m: Any,
) -> dict[str, float] | None:
    if not isinstance(display_geometry, dict):
        return None
    target_m = _float_or_none(distance_m)
    if target_m is None or not math.isfinite(target_m):
        return None
    route_segments = [
        segment
        for segment in display_geometry.get("route_segments") or []
        if isinstance(segment, dict)
    ]
    if route_segments:
        first_segment = route_segments[0]
        last_segment = route_segments[-1]
        for segment in route_segments:
            start = _float_or_none(segment.get("start_distance_m"))
            end = _float_or_none(segment.get("end_distance_m"))
            coordinates = _normalized_coordinate_segment(segment.get("coordinates", []))
            if start is None or end is None or len(coordinates) < 2:
                continue
            lower = min(start, end)
            upper = max(start, end)
            if lower <= target_m <= upper:
                ratio = _safe_ratio(target_m - start, end - start) or 0.0
                return _coordinate_at_geometry_ratio(coordinates, ratio)
        first_start = _float_or_none(first_segment.get("start_distance_m")) or 0.0
        if target_m <= first_start:
            coordinates = _normalized_coordinate_segment(first_segment.get("coordinates", []))
            if coordinates:
                return dict(coordinates[0])
        coordinates = _normalized_coordinate_segment(last_segment.get("coordinates", []))
        if coordinates:
            return dict(coordinates[-1])
    segments = _display_coordinate_segments(display_geometry)
    first_point: dict[str, float] | None = None
    last_point: dict[str, float] | None = None
    cumulative_m = 0.0
    for segment in segments:
        if not segment:
            continue
        first_point = first_point or segment[0]
        last_point = segment[-1]
        if target_m <= 0:
            return dict(segment[0])
        for previous, current in zip(segment, segment[1:]):
            segment_m = _haversine_m(
                previous["lat"],
                previous["lon"],
                current["lat"],
                current["lon"],
            )
            if segment_m is None or segment_m <= 0:
                continue
            if cumulative_m + segment_m >= target_m:
                ratio = max(0.0, min(1.0, (target_m - cumulative_m) / segment_m))
                return {
                    "lat": previous["lat"] + (current["lat"] - previous["lat"]) * ratio,
                    "lon": previous["lon"] + (current["lon"] - previous["lon"]) * ratio,
                }
            cumulative_m += segment_m
    if first_point is None:
        return None
    return dict(last_point or first_point)


def _coordinate_at_geometry_ratio(
    coordinates: list[dict[str, float]],
    ratio: float,
) -> dict[str, float] | None:
    if not coordinates:
        return None
    ratio = max(0.0, min(1.0, ratio))
    if ratio <= 0:
        return dict(coordinates[0])
    if ratio >= 1:
        return dict(coordinates[-1])
    lengths: list[float] = []
    total_m = 0.0
    for previous, current in zip(coordinates, coordinates[1:]):
        segment_m = _haversine_m(
            previous["lat"],
            previous["lon"],
            current["lat"],
            current["lon"],
        )
        segment_m = segment_m or 0.0
        lengths.append(segment_m)
        total_m += segment_m
    if total_m <= 0:
        return dict(coordinates[0])
    target_m = ratio * total_m
    cumulative_m = 0.0
    for index, segment_m in enumerate(lengths):
        previous = coordinates[index]
        current = coordinates[index + 1]
        if segment_m <= 0:
            continue
        if cumulative_m + segment_m >= target_m:
            local_ratio = (target_m - cumulative_m) / segment_m
            return {
                "lat": previous["lat"] + (current["lat"] - previous["lat"]) * local_ratio,
                "lon": previous["lon"] + (current["lon"] - previous["lon"]) * local_ratio,
            }
        cumulative_m += segment_m
    return dict(coordinates[-1])


def _build_route_pressure_profile(
    *,
    project_id: str,
    generated_at: str,
    segments: list[dict[str, Any]],
    risk_features: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    rest_areas: list[dict[str, Any]],
    resume_segments: list[dict[str, Any]],
    mcp_payload: dict[str, Any],
    route_display_geometry: dict[str, Any],
    route_extent_m: float,
    pressure_profile_bin_m: float,
    slow_passage_min_span_m: float,
    route_mileage_alignment: dict[str, Any],
) -> dict[str, Any]:
    bin_m = max(100.0, float(pressure_profile_bin_m or DEFAULT_PRESSURE_PROFILE_BIN_M))
    extent_m = max(route_extent_m, bin_m)
    bin_count = max(1, int(math.ceil(extent_m / bin_m)))
    samples: list[dict[str, Any]] = []
    mcp_candidates = _payload_list(mcp_payload, "mcp_candidates")
    for index in range(bin_count):
        start_m = index * bin_m
        end_m = min(extent_m, start_m + bin_m)
        mid_m = (start_m + end_m) / 2.0
        risk_overlaps = _risk_features_overlapping(risk_features, start_m, end_m)
        segment_overlaps = _segments_overlapping(segments, start_m, end_m)
        bin_notes = _items_in_distance_window(notes, start_m, end_m)
        bin_rest = _items_in_distance_window(rest_areas, start_m, end_m)
        bin_resume = _items_in_distance_window(resume_segments, start_m, end_m)
        bin_mcp = _items_in_distance_window(
            mcp_candidates,
            start_m,
            end_m,
            key="distance_m",
        )
        risk_summary = _risk_profile_summary(risk_overlaps)
        segment_summary = _segment_pressure_summary(segment_overlaps)
        slow_passage = _slow_passage_summary(
            bin_notes,
            min_span_m=slow_passage_min_span_m,
        )
        warning_note_count = sum(
            1 for note in bin_notes if _contains_terms(_note_text(note), WARNING_NAME_TERMS)
        )
        rest_note_count = sum(
            1 for note in bin_notes if _contains_terms(_note_text(note), REST_TERMS)
        )
        mcp_summary = _mcp_profile_support(bin_mcp)
        progress = _safe_ratio(mid_m, extent_m) or 0.0
        rest_stop_likely = bool(bin_rest or rest_note_count or mcp_summary["rest_stop_class"])
        hard_evidence = bool(
            (risk_summary["max_risk_score"] or 0.0) >= 65.0
            or segment_summary["terrain_grade_pressure"] >= 12.0
            or warning_note_count
            or slow_passage["qualified"]
            or mcp_summary["max_class_bonus"] >= 8.0
        )
        rest_multiplier = 0.72 if rest_stop_likely and not hard_evidence else 1.0
        components = {
            "risk_pressure": _clamp((risk_summary["max_risk_score"] or 0.0) / 3.0, 0, 32),
            "terrain_grade_pressure": segment_summary["terrain_grade_pressure"],
            "route_note_warning": _clamp(warning_note_count * 4, 0, 14),
            "slow_passage_pressure": _clamp(
                (10 if slow_passage["qualified"] else 0)
                + int(slow_passage["effective_note_count"]) * 2,
                0,
                14,
            ),
            "mcp_named_support": _clamp(
                mcp_summary["max_class_bonus"] * 0.7
                + mcp_summary["max_mcp_total"] / 15.0
                + mcp_summary["max_mention_ratio"] * 10.0,
                0,
                16,
            ),
            "rescue_difficulty": _clamp(progress * 8 + len(bin_resume) * 3, 0, 10),
        }
        score = _clamp(sum(components.values()) * rest_multiplier, 0, 100)
        route_coordinate = _route_coordinate_at_distance(route_display_geometry, mid_m)
        risk_coordinate = _route_pressure_sample_coordinate(risk_overlaps)
        coordinate = route_coordinate or risk_coordinate
        route_coordinate_source = (
            "overpass_risk_ribbon_route_distance_interpolation"
            if route_display_geometry.get("evidence_type")
            == "pretrip_overpass_risk_ribbon_centerline"
            else "segment_display_geometry_route_distance_interpolation"
        )
        coordinate_source = (
            route_coordinate_source
            if route_coordinate is not None
            else "risk_ribbon_geometry_fallback"
            if risk_coordinate.get("lat") is not None and risk_coordinate.get("lon") is not None
            else "missing_coordinate"
        )
        display_mileage = _display_mileage_for_route_distance(
            route_mileage_alignment,
            mid_m,
        )
        samples.append(
            {
                "sample_id": f"route_pressure.{project_id}.sample.{index:04d}",
                "label": _route_pressure_sample_label(
                    index,
                    mid_m,
                    mcp_summary,
                    display_mileage=display_mileage,
                ),
                "start_distance_m": _round(start_m),
                "end_distance_m": _round(end_m),
                "mid_distance_m": _round(mid_m),
                "display_mileage": display_mileage,
                "route_progress_ratio": _round(progress),
                "lat": coordinate.get("lat"),
                "lon": coordinate.get("lon"),
                "coordinate_source": coordinate_source,
                "route_pressure_score": _round(score),
                "band": _pressure_band(score),
                "components": {key: _round(value) for key, value in components.items()},
                "rest_stop_context": {
                    "rest_stop_likely": rest_stop_likely,
                    "rest_stop_deemphasis_multiplier": _round(rest_multiplier),
                    "nearby_rest_area_count": len(bin_rest),
                    "rest_note_count": rest_note_count,
                },
                "slow_passage": slow_passage,
                "risk": risk_summary,
                "terrain": segment_summary,
                "mcp_support": mcp_summary,
                "risk_segment_ids": risk_summary["risk_segment_ids"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    peaks = _route_pressure_peaks(samples, min_spacing_m=bin_m)
    return {
        "artifact_kind": "pretrip_route_pressure_profile",
        "schema_version": "route_pressure_profile.v1",
        "project_id": project_id,
        "generated_at": generated_at,
        "route_pressure_profile_ref": ROUTE_PRESSURE_PROFILE_REF,
        "route_pressure_profile_geojson_ref": ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
        "policy": {
            "bin_m": _round(bin_m),
            "slow_passage_min_span_m": _round(float(slow_passage_min_span_m)),
            "centerline": "overpass_risk_ribbon",
            "risk_distance_axis": "overpass_risk_ribbon_distance",
            "gpx_evidence_axis": "projected_to_overpass_risk_ribbon",
            "display_mileage_source": "route_mileage_k_anchors_when_available",
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "counts": {
            "sample_count": len(samples),
            "peak_count": len(peaks),
            "risk_backed_sample_count": sum(1 for sample in samples if sample["risk"]["feature_count"]),
            "mcp_supported_sample_count": sum(
                1 for sample in samples if sample["mcp_support"]["candidate_count"]
            ),
        },
        "summary": _route_pressure_profile_summary({"samples": samples, "peaks": peaks}),
        "samples": samples,
        "peaks": peaks,
        "boundary": _closed_boundary(workspace_file_mutation_allowed=True),
    }


def _feature_coordinate_points(feature: dict[str, Any]) -> list[dict[str, float]]:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        lat = _float_or_none(coordinates[1])
        lon = _float_or_none(coordinates[0])
        return [{"lat": lat, "lon": lon}] if lat is not None and lon is not None else []
    if geometry.get("type") == "LineString" and isinstance(coordinates, list):
        points = [
            {"lat": _float_or_none(point[1]), "lon": _float_or_none(point[0])}
            for point in coordinates
            if isinstance(point, list) and len(point) >= 2
        ]
        return [
            point
            for point in points
            if point["lat"] is not None and point["lon"] is not None
        ]
    return []


def _nearest_route_projection(
    route_display_geometry: dict[str, Any],
    point: dict[str, float],
) -> dict[str, Any] | None:
    point_lat = _float_or_none(point.get("lat"))
    point_lon = _float_or_none(point.get("lon"))
    if point_lat is None or point_lon is None:
        return None
    indexed_edges = [
        edge
        for edge in route_display_geometry.get("projection_edges") or []
        if isinstance(edge, dict)
    ]
    if indexed_edges:
        return _nearest_route_projection_from_edges(indexed_edges, point_lat, point_lon)
    best: dict[str, Any] | None = None
    for route_segment in route_display_geometry.get("route_segments") or []:
        if not isinstance(route_segment, dict):
            continue
        start = _float_or_none(route_segment.get("start_distance_m"))
        end = _float_or_none(route_segment.get("end_distance_m"))
        coordinates = _normalized_coordinate_segment(route_segment.get("coordinates", []))
        if start is None or end is None or len(coordinates) < 2:
            continue
        geometry_lengths: list[float] = []
        geometry_total_m = 0.0
        for previous, current in zip(coordinates, coordinates[1:]):
            segment_m = _haversine_m(
                previous["lat"],
                previous["lon"],
                current["lat"],
                current["lon"],
            )
            segment_m = segment_m or 0.0
            geometry_lengths.append(segment_m)
            geometry_total_m += segment_m
        cumulative_m = 0.0
        for index, segment_m in enumerate(geometry_lengths):
            previous = coordinates[index]
            current = coordinates[index + 1]
            projection = _project_point_to_segment_m(
                point_lat,
                point_lon,
                previous["lat"],
                previous["lon"],
                current["lat"],
                current["lon"],
            )
            if projection is None:
                cumulative_m += segment_m
                continue
            geometry_ratio = (
                _safe_ratio(cumulative_m + projection["segment_offset_m"], geometry_total_m)
                or 0.0
            )
            route_distance_m = start + (end - start) * geometry_ratio
            candidate = {
                "route_distance_m": route_distance_m,
                "distance_to_route_m": projection["distance_to_segment_m"],
                "segment_candidate_id": route_segment.get("segment_candidate_id"),
                "lat": projection["lat"],
                "lon": projection["lon"],
            }
            if best is None or candidate["distance_to_route_m"] < best["distance_to_route_m"]:
                best = candidate
            cumulative_m += segment_m
    return best


def _nearest_route_projection_from_edges(
    edges: list[dict[str, Any]],
    point_lat: float,
    point_lon: float,
) -> dict[str, Any] | None:
    bbox_padding_deg = 0.02
    candidate_edges = [
        edge
        for edge in edges
        if (_float_or_none(edge.get("min_lat")) or -90.0) - bbox_padding_deg
        <= point_lat
        <= (_float_or_none(edge.get("max_lat")) or 90.0) + bbox_padding_deg
        and (_float_or_none(edge.get("min_lon")) or -180.0) - bbox_padding_deg
        <= point_lon
        <= (_float_or_none(edge.get("max_lon")) or 180.0) + bbox_padding_deg
    ]
    if not candidate_edges:
        candidate_edges = edges
    best: dict[str, Any] | None = None
    for edge in candidate_edges:
        start_lat = _float_or_none(edge.get("start_lat"))
        start_lon = _float_or_none(edge.get("start_lon"))
        end_lat = _float_or_none(edge.get("end_lat"))
        end_lon = _float_or_none(edge.get("end_lon"))
        start_m = _float_or_none(edge.get("start_distance_m"))
        end_m = _float_or_none(edge.get("end_distance_m"))
        length_m = _float_or_none(edge.get("length_m")) or 0.0
        if None in {start_lat, start_lon, end_lat, end_lon, start_m, end_m}:
            continue
        projection = _project_point_to_segment_m(
            point_lat,
            point_lon,
            start_lat,
            start_lon,
            end_lat,
            end_lon,
        )
        if projection is None:
            continue
        ratio = _safe_ratio(projection["segment_offset_m"], length_m) or 0.0
        candidate = {
            "route_distance_m": start_m + (end_m - start_m) * ratio,
            "distance_to_route_m": projection["distance_to_segment_m"],
            "segment_candidate_id": edge.get("segment_candidate_id"),
            "lat": projection["lat"],
            "lon": projection["lon"],
        }
        if best is None or candidate["distance_to_route_m"] < best["distance_to_route_m"]:
            best = candidate
    return best


def _project_point_to_segment_m(
    point_lat: float,
    point_lon: float,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> dict[str, float] | None:
    lat0 = math.radians(point_lat)
    scale = 111320.0

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        return (
            (lon - point_lon) * scale * math.cos(lat0),
            (lat - point_lat) * scale,
        )

    sx, sy = to_xy(start_lat, start_lon)
    ex, ey = to_xy(end_lat, end_lon)
    dx = ex - sx
    dy = ey - sy
    denom = dx * dx + dy * dy
    if denom <= 0:
        distance = math.hypot(sx, sy)
        return {
            "distance_to_segment_m": distance,
            "segment_offset_m": 0.0,
            "lat": start_lat,
            "lon": start_lon,
        }
    raw_t = -((sx * dx) + (sy * dy)) / denom
    t = max(0.0, min(1.0, raw_t))
    px = sx + dx * t
    py = sy + dy * t
    segment_length_m = _haversine_m(start_lat, start_lon, end_lat, end_lon) or 0.0
    return {
        "distance_to_segment_m": math.hypot(px, py),
        "segment_offset_m": segment_length_m * t,
        "lat": start_lat + (end_lat - start_lat) * t,
        "lon": start_lon + (end_lon - start_lon) * t,
    }


def _gpx_segment_interpretability(
    segment: dict[str, Any],
    coordinates: list[dict[str, float]],
    *,
    max_projection_distance_m: float,
) -> dict[str, Any]:
    path_distance_m = sum(
        _haversine_m(previous["lat"], previous["lon"], current["lat"], current["lon"]) or 0.0
        for previous, current in zip(coordinates, coordinates[1:])
    )
    straight_distance_m = (
        _haversine_m(
            coordinates[0]["lat"],
            coordinates[0]["lon"],
            coordinates[-1]["lat"],
            coordinates[-1]["lon"],
        )
        or 0.0
    )
    straightness_ratio = _safe_ratio(straight_distance_m, path_distance_m) or 0.0
    duration_seconds = _segment_duration_seconds(segment)
    quality = "usable"
    reasons: list[str] = []
    if max_projection_distance_m > 250.0:
        quality = "low"
        reasons.append("far_from_overpass_centerline")
    if duration_seconds is None:
        if straightness_ratio >= 0.985 and path_distance_m >= 500.0:
            quality = "weak"
            reasons.append("very_straight_long_gpx_geometry_without_time")
        else:
            reasons.append("not_assessed_missing_time")
    elif duration_seconds >= 300.0 and straightness_ratio >= 0.985 and path_distance_m >= 250.0:
        quality = "low"
        reasons.append("long_time_gap_on_nearly_straight_gpx_segment")
    return {
        "quality": quality,
        "reasons": reasons,
        "duration_seconds": _round(duration_seconds) if duration_seconds is not None else None,
        "path_distance_m": _round(path_distance_m),
        "straight_distance_m": _round(straight_distance_m),
        "straightness_ratio": _round(straightness_ratio),
        "projection_max_distance_m": _round(max_projection_distance_m),
        "policy": {
            "long_time_gap_threshold_seconds": 300,
            "straightness_ratio_threshold": 0.985,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _segment_duration_seconds(segment: dict[str, Any]) -> float | None:
    for key in (
        "duration_seconds",
        "elapsed_seconds",
        "time_delta_seconds",
        "duration_s",
    ):
        value = _float_or_none(segment.get(key))
        if value is not None:
            return value
    start = segment.get("started_at") or segment.get("start_time") or segment.get("time_start")
    end = segment.get("ended_at") or segment.get("end_time") or segment.get("time_end")
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def _projection_alignment_status(distance_m: float | None) -> str:
    if distance_m is None:
        return "missing_projection"
    if distance_m <= 100:
        return "aligned"
    if distance_m <= 250:
        return "nearby_offset"
    return "distant_offset"


def _risk_feature_distance_range(
    feature: dict[str, Any],
) -> tuple[float | None, float | None]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    projected_start = _float_or_none(props.get("projected_start_distance_m"))
    projected_end = _float_or_none(props.get("projected_end_distance_m"))
    if projected_start is not None and projected_end is not None:
        return projected_start, projected_end
    return _float_or_none(props.get("start_distance_m")), _float_or_none(
        props.get("end_distance_m")
    )


def _risk_features_overlapping(
    features: list[dict[str, Any]],
    start_m: float,
    end_m: float,
) -> list[dict[str, Any]]:
    result = []
    for feature in features:
        start, end = _risk_feature_distance_range(feature)
        if start is None or end is None:
            continue
        if max(start, end) < start_m or min(start, end) > end_m:
            continue
        result.append(feature)
    return result


def _segments_overlapping(
    segments: list[dict[str, Any]],
    start_m: float,
    end_m: float,
) -> list[dict[str, Any]]:
    result = []
    for segment in segments:
        start = _float_or_none(segment.get("start_distance_m"))
        end = _float_or_none(segment.get("end_distance_m"))
        if start is None or end is None:
            continue
        if max(start, end) < start_m or min(start, end) > end_m:
            continue
        result.append(segment)
    return result


def _items_in_distance_window(
    items: list[dict[str, Any]],
    start_m: float,
    end_m: float,
    *,
    key: str = "route_distance_m",
) -> list[dict[str, Any]]:
    result = []
    for item in items:
        distance = _float_or_none(item.get(key))
        if distance is None:
            continue
        if start_m <= distance <= end_m:
            result.append(item)
    return result


def _risk_profile_summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[tuple[float, dict[str, Any]]] = []
    segment_ids: list[str] = []
    alignment_status_counts: dict[str, int] = {}
    projection_distances: list[float] = []
    original_route_ids: set[str] = set()
    distance_axis = "overpass_risk_ribbon_distance"
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        score = _float_or_none(props.get("rs") or props.get("risk_score"))
        if score is None:
            continue
        scored.append((score, feature))
        if props.get("segment_id"):
            segment_ids.append(str(props["segment_id"]))
        if props.get("risk_distance_axis"):
            distance_axis = str(props["risk_distance_axis"])
        if props.get("route_id"):
            original_route_ids.add(str(props["route_id"]))
        status = str(props.get("projection_alignment_status") or "canonical_overpass")
        alignment_status_counts[status] = alignment_status_counts.get(status, 0) + 1
        projection_distance = _float_or_none(props.get("projection_max_distance_m"))
        if projection_distance is not None:
            projection_distances.append(projection_distance)
    scores = [score for score, _ in scored]
    return {
        "feature_count": len(scores),
        "max_risk_score": _round(max(scores)) if scores else None,
        "avg_risk_score": _round(sum(scores) / len(scores)) if scores else None,
        "risk_segment_ids": segment_ids[:8],
        "distance_axis": distance_axis,
        "alignment_status_counts": alignment_status_counts,
        "max_projection_distance_m": _round(max(projection_distances))
        if projection_distances
        else None,
        "original_route_ids": sorted(original_route_ids)[:4],
    }


def _segment_pressure_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    distance = sum(_float_or_none(segment.get("distance_m")) or 0.0 for segment in segments)
    gain = sum(_float_or_none(segment.get("elevation_gain_m")) or 0.0 for segment in segments)
    loss = sum(_float_or_none(segment.get("elevation_loss_m")) or 0.0 for segment in segments)
    ascent_ratio = gain / distance if distance > 0 else 0.0
    descent_ratio = loss / distance if distance > 0 else 0.0
    grade_pressure = _clamp(ascent_ratio * 75.0 + descent_ratio * 55.0, 0, 22)
    return {
        "segment_count": len(segments),
        "distance_m": _round(distance),
        "elevation_gain_m": _round(gain),
        "elevation_loss_m": _round(loss),
        "ascent_ratio": _round(ascent_ratio),
        "descent_ratio": _round(descent_ratio),
        "terrain_grade_pressure": _round(grade_pressure),
    }


def _mcp_profile_support(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    max_class_bonus = 0.0
    max_total = 0.0
    max_mention = 0.0
    labels = []
    ids = []
    rest_stop_class = False
    for candidate in candidates:
        classes = [str(value) for value in candidate.get("mcp_classes") or []]
        max_class_bonus = max(
            max_class_bonus,
            max((TERRAIN_CLASS_BONUS.get(value, 0.0) for value in classes), default=0.0),
        )
        max_total = max(
            max_total,
            _float_or_none((candidate.get("score_components") or {}).get("total")) or 0.0,
        )
        max_mention = max(max_mention, _float_or_none(candidate.get("mention_ratio")) or 0.0)
        rest_stop_class = rest_stop_class or bool(
            set(classes).intersection({"camp_hut_structure", "water_source"})
        )
        if candidate.get("label"):
            labels.append(str(candidate["label"]))
        if candidate.get("mcp_id"):
            ids.append(str(candidate["mcp_id"]))
    return {
        "candidate_count": len(candidates),
        "candidate_ids": ids[:8],
        "labels": labels[:4],
        "max_class_bonus": _round(max_class_bonus),
        "max_mcp_total": _round(max_total),
        "max_mention_ratio": _round(max_mention),
        "rest_stop_class": rest_stop_class,
    }


def _route_pressure_sample_coordinate(features: list[dict[str, Any]]) -> dict[str, float | None]:
    best_feature: dict[str, Any] | None = None
    best_score = -1.0
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        score = _float_or_none(props.get("rs") or props.get("risk_score")) or 0.0
        if score > best_score:
            best_score = score
            best_feature = feature
    if best_feature is None:
        return {"lat": None, "lon": None}
    return _feature_midpoint_coordinate(best_feature)


def _feature_midpoint_coordinate(feature: dict[str, Any]) -> dict[str, float | None]:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return {"lat": None, "lon": None}
    if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return {"lat": _float_or_none(coordinates[1]), "lon": _float_or_none(coordinates[0])}
    if geometry.get("type") == "LineString" and isinstance(coordinates, list):
        points = [point for point in coordinates if isinstance(point, list) and len(point) >= 2]
        if not points:
            return {"lat": None, "lon": None}
        point = points[len(points) // 2]
        return {"lat": _float_or_none(point[1]), "lon": _float_or_none(point[0])}
    return {"lat": None, "lon": None}


def _route_pressure_sample_label(
    index: int,
    mid_m: float,
    mcp_summary: dict[str, Any],
    *,
    display_mileage: dict[str, Any] | None = None,
) -> str:
    labels = mcp_summary.get("labels") or []
    if labels:
        return str(labels[0])
    mileage_label = ""
    if isinstance(display_mileage, dict):
        status = str(display_mileage.get("alignment_status") or "")
        if status not in {"missing_alignment", "outside_anchor_range"}:
            mileage_label = str(display_mileage.get("label") or "").strip()
    return f"路段壓力樣本 {index + 1:03d}（{mileage_label or f'{mid_m / 1000.0:.1f}K'}）"


def _route_pressure_peaks(
    samples: list[dict[str, Any]],
    *,
    min_spacing_m: float,
) -> list[dict[str, Any]]:
    peak_candidates: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        score = _float_or_none(sample.get("route_pressure_score")) or 0.0
        if score < 35.0:
            continue
        previous_score = (
            _float_or_none(samples[index - 1].get("route_pressure_score")) or 0.0
            if index > 0
            else -1.0
        )
        next_score = (
            _float_or_none(samples[index + 1].get("route_pressure_score")) or 0.0
            if index + 1 < len(samples)
            else -1.0
        )
        if score >= previous_score and score >= next_score:
            peak_candidates.append(sample)
    selected: list[dict[str, Any]] = []
    for sample in sorted(
        peak_candidates,
        key=lambda item: _float_or_none(item.get("route_pressure_score")) or 0.0,
        reverse=True,
    ):
        distance = _float_or_none(sample.get("mid_distance_m"))
        if distance is None:
            continue
        if any(
            abs(distance - (_float_or_none(existing.get("mid_distance_m")) or 0.0))
            < min_spacing_m
            for existing in selected
        ):
            continue
        selected.append(dict(sample))
        if len(selected) >= 20:
            break
    selected.sort(key=lambda item: _float_or_none(item.get("mid_distance_m")) or 0.0)
    for index, peak in enumerate(selected):
        peak["rank"] = index + 1
        peak["pressure_peak_id"] = f"route_pressure_peak.{index + 1:03d}"
        peak["sample_count"] = len(samples)
        peak["label"] = _pressure_peak_label(peak)
    return selected


def _pressure_band(score: float) -> str:
    if score >= 65:
        return "pressure_extreme"
    if score >= 50:
        return "pressure_high"
    if score >= 35:
        return "pressure_watch"
    return "pressure_low"


def _route_pressure_profile_summary(payload: dict[str, Any]) -> dict[str, Any]:
    samples = payload.get("samples") if isinstance(payload.get("samples"), list) else []
    peaks = payload.get("peaks") if isinstance(payload.get("peaks"), list) else []
    highest_sample = max(
        samples,
        key=lambda item: _float_or_none(item.get("route_pressure_score")) or 0.0,
        default={},
    )
    return {
        "sample_count": len(samples),
        "peak_count": len(peaks),
        "highest_route_pressure_score": highest_sample.get("route_pressure_score"),
        "highest_route_pressure_label": highest_sample.get("label"),
        "highest_route_pressure_distance_m": highest_sample.get("mid_distance_m"),
        "top_peak_labels": [peak.get("label") for peak in peaks[:5]],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _route_pressure_profile_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    features = []
    for sample in payload.get("samples") or []:
        if sample.get("lat") is None or sample.get("lon") is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [sample["lon"], sample["lat"]],
                },
                "properties": {
                    "sample_id": sample.get("sample_id"),
                    "label": sample.get("label"),
                    "start_distance_m": sample.get("start_distance_m"),
                    "end_distance_m": sample.get("end_distance_m"),
                    "mid_distance_m": sample.get("mid_distance_m"),
                    "display_mileage_label": (
                        sample.get("display_mileage") or {}
                    ).get("label"),
                    "display_mileage_status": (
                        sample.get("display_mileage") or {}
                    ).get("alignment_status"),
                    "route_pressure_score": sample.get("route_pressure_score"),
                    "band": sample.get("band"),
                    "coordinate_source": sample.get("coordinate_source"),
                    "is_peak": False,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    peak_ids = {peak.get("sample_id"): peak for peak in payload.get("peaks") or []}
    for feature in features:
        sample_id = feature["properties"].get("sample_id")
        if sample_id not in peak_ids:
            continue
        peak = peak_ids[sample_id]
        feature["properties"]["is_peak"] = True
        feature["properties"]["pressure_peak_id"] = peak.get("pressure_peak_id")
        feature["properties"]["peak_rank"] = peak.get("rank")
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "artifact_kind": "pretrip_route_pressure_profile_geojson",
            "source_artifact_kind": payload.get("artifact_kind"),
            "project_id": payload.get("project_id"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


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


def _slow_passage_summary(
    notes: list[dict[str, Any]],
    *,
    min_span_m: float,
) -> dict[str, Any]:
    moving_ranges: list[tuple[float, float, dict[str, Any]]] = []
    suppressed_rest_stop_notes = []
    for note in notes:
        text = _note_text(note)
        if not _contains_terms(text, SLOW_TERMS):
            continue
        if _contains_terms(text, REST_STOP_TERMS):
            suppressed_rest_stop_notes.append(note)
            continue
        distance_range = _route_distance_range(note)
        if distance_range is None:
            continue
        moving_ranges.append((*distance_range, note))

    if moving_ranges:
        start_m = min(start for start, _, _ in moving_ranges)
        end_m = max(end for _, end, _ in moving_ranges)
        span_m = max(0.0, end_m - start_m)
    else:
        start_m = None
        end_m = None
        span_m = 0.0
    qualified = span_m >= min_span_m
    return {
        "qualified": qualified,
        "min_span_m": _round(float(min_span_m)),
        "span_m": _round(span_m),
        "start_distance_m": _round(start_m) if start_m is not None else None,
        "end_distance_m": _round(end_m) if end_m is not None else None,
        "slow_movement_note_count": len(moving_ranges),
        "effective_note_count": len(moving_ranges) if qualified else 0,
        "suppressed_rest_stop_slow_note_count": len(suppressed_rest_stop_notes),
        "candidate_ids": [
            str(note.get("candidate_id"))
            for _, _, note in moving_ranges[:8]
            if note.get("candidate_id")
        ],
        "rest_stop_slow_candidate_ids": [
            str(note.get("candidate_id"))
            for note in suppressed_rest_stop_notes[:8]
            if note.get("candidate_id")
        ],
    }


def _route_distance_range(item: dict[str, Any]) -> tuple[float, float] | None:
    start = _float_or_none(item.get("start_distance_m"))
    if start is None:
        start = _float_or_none(item.get("route_start_distance_m"))
    end = _float_or_none(item.get("end_distance_m"))
    if end is None:
        end = _float_or_none(item.get("route_end_distance_m"))
    if start is not None and end is not None:
        return (min(start, end), max(start, end))
    distance = _float_or_none(item.get("route_distance_m")) or _float_or_none(
        item.get("distance_m")
    )
    if distance is None:
        return None
    return (distance, distance)


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
        start, end = _risk_feature_distance_range(feature)
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
        projected_start = _float_or_none(props.get("projected_start_distance_m"))
        projected_end = _float_or_none(props.get("projected_end_distance_m"))
        if projected_start is not None and projected_end is not None:
            for value in (projected_start, projected_end):
                values.append(value)
            continue
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
    parser.add_argument(
        "--slow-passage-min-span-m",
        type=float,
        default=DEFAULT_SLOW_PASSAGE_MIN_SPAN_M,
    )
    parser.add_argument(
        "--pressure-profile-bin-m",
        type=float,
        default=DEFAULT_PRESSURE_PROFILE_BIN_M,
    )
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
        slow_passage_min_span_m=args.slow_passage_min_span_m,
        pressure_profile_bin_m=args.pressure_profile_bin_m,
        generated_at=args.generated_at,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
