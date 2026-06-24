from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from admin_map_layers import build_after_action_map_layers
from admin_evidence_timeline import (
    build_admin_evidence_timeline,
    build_scout_agent_skill_summary,
)
from incident_store import IncidentStore
from mission_graph import load_mission_graph
from offline_map import load_offline_map_context
from post_analysis_capability import summarize_capability_artifacts
from pretrip_admin_view import (
    CHILAI_NANHUA_DAY1_PROJECT_ID,
    build_pretrip_admin_view,
    resolve_pretrip_project_artifacts,
    resolve_pretrip_project_root,
)
from replay_runner import ReplayResult, replay_route
from risk_rules import load_risk_rules
from route_matching import load_gpx_route
from safety_models import IncidentPackage
from scout_energy_reserve_monitor import build_energy_reserve_monitor_from_view
from scout_runtime_state_store_projection import build_runtime_safety_state_store_projection


ROOT = Path(__file__).resolve().parent
FIELD_CASE_ID = "scout_260512_field_golden"
PRETRIP_CASE_ID = CHILAI_NANHUA_DAY1_PROJECT_ID


@dataclass(frozen=True)
class AdminCaseArtifacts:
    case_id: str
    golden_case_path: Path
    route_path: Path
    map_context_path: Path
    mission_graph_path: Path
    risk_rules_path: Path
    mission_context_path: Path
    route_progress_config_path: Path
    incident_store_path: Path | None = None


def resolve_admin_case_artifacts(
    case_id: str,
    *,
    root: Path = ROOT,
    incident_store_path: Path | None = None,
) -> AdminCaseArtifacts:
    if case_id != FIELD_CASE_ID:
        raise KeyError(case_id)

    return AdminCaseArtifacts(
        case_id=case_id,
        golden_case_path=root / "tests" / "fixtures" / "field_cases" / "scout_260512_golden.json",
        route_path=root / "tests" / "fixtures" / "routes" / "scout_260512_field_route.gpx",
        map_context_path=root / "tests" / "fixtures" / "maps" / "scout_260512_overpass_map_context.geojson",
        mission_graph_path=root / "tests" / "fixtures" / "mission_graph" / "scout_260512_field_mission.json",
        risk_rules_path=root / "tests" / "fixtures" / "risk_rules" / "scout_260512_field_rules.json",
        mission_context_path=root / "tests" / "fixtures" / "mission_context" / "scout_260512_field_normal.json",
        route_progress_config_path=root / "tests" / "fixtures" / "route_progress" / "scout_260512_field_config.json",
        incident_store_path=incident_store_path,
    )


def build_admin_case_view(
    case_id: str,
    *,
    root: Path = ROOT,
    incident_store_path: Path | None = None,
    pretrip_project_root: Path | None = None,
) -> dict[str, Any]:
    if case_id == PRETRIP_CASE_ID:
        return _build_pretrip_admin_case_view(
            case_id,
            root=root,
            project_root=pretrip_project_root,
        )

    artifacts = resolve_admin_case_artifacts(case_id, root=root, incident_store_path=incident_store_path)
    golden = json.loads(artifacts.golden_case_path.read_text(encoding="utf-8"))
    route = load_gpx_route(artifacts.route_path)
    mission = load_mission_graph(artifacts.mission_graph_path)
    map_context = load_offline_map_context(artifacts.map_context_path)
    risk_rules = load_risk_rules(artifacts.risk_rules_path)
    incidents = _load_incidents(artifacts.incident_store_path)
    map_metadata = map_context.source_metadata.model_dump(mode="json")
    replay_result = _cached_replay_result(
        str(artifacts.mission_graph_path),
        str(artifacts.route_path),
        str(artifacts.map_context_path),
        str(artifacts.risk_rules_path),
        str(artifacts.mission_context_path),
        str(artifacts.route_progress_config_path),
    )

    return {
        "case_id": case_id,
        "artifacts": _artifact_refs(artifacts, root),
        "summary": {
            "description": golden.get("description"),
            "source_files": golden.get("source_files", []),
            "map_context": golden.get("map_context"),
            "bbox": golden.get("bbox"),
            "segments": [
                {
                    "id": segment["id"],
                    "duration_s": segment["duration_s"],
                    "records": segment["records"],
                    "valid_location_records": segment["valid_location_records"],
                    "horizontal_accuracy_p90_m": segment["horizontal_accuracy_p90_m"],
                    "map_inside_corridor_with_hacc_pct": segment["map_inside_corridor_with_hacc_pct"],
                    "source_id": segment["id"],
                    "source_path": _relpath(artifacts.golden_case_path, root),
                }
                for segment in golden.get("segments", [])
            ],
        },
        "mission": {
            "mission_id": mission.mission_id,
            "name": mission.name,
            "route_source": mission.route_source,
            "checkpoints": [
                {
                    **checkpoint.model_dump(mode="json"),
                    "source_id": checkpoint.checkpoint_id,
                    "source_path": _relpath(artifacts.mission_graph_path, root),
                    "evidence_type": "mission_checkpoint",
                }
                for checkpoint in mission.checkpoints
            ],
            "segments": [
                {
                    **segment.model_dump(mode="json"),
                    "source_id": segment.segment_id,
                    "source_path": _relpath(artifacts.mission_graph_path, root),
                    "evidence_type": "mission_segment",
                }
                for segment in mission.segments
            ],
            "control_zones": [
                {
                    **zone.model_dump(mode="json"),
                    "source_id": zone.zone_id,
                    "source_path": _relpath(artifacts.mission_graph_path, root),
                    "evidence_type": "control_zone",
                }
                for zone in mission.control_zones
            ],
        },
        "route": {
            "source_path": _relpath(artifacts.route_path, root),
            "bounds": _bounds([(point.lat, point.lon) for point in route.points]),
            "point_count": len(route.points),
            "total_progress_m": route.points[-1].progress_m,
            "points": [
                {
                    "index": index,
                    "lat": point.lat,
                    "lon": point.lon,
                    "elevation_m": point.elevation_m,
                    "timestamp": point.timestamp,
                    "progress_m": round(point.progress_m, 2),
                    "gps_horizontal_accuracy_m": point.gps_horizontal_accuracy_m,
                    "course_deg": point.course_deg,
                    "pedometer_distance_m": point.pedometer_distance_m,
                    "source_id": f"route_point_{index}",
                    "source_path": _relpath(artifacts.route_path, root),
                    "evidence_type": "device_observation",
                }
                for index, point in enumerate(route.points)
            ],
        },
        "map": {
            "source_path": _relpath(artifacts.map_context_path, root),
            "metadata": map_metadata,
            "corridors": [
                {
                    "corridor_id": corridor.corridor_id,
                    "name": corridor.name,
                    "route_level": corridor.route_level,
                    "corridor_half_width_m": corridor.corridor_half_width_m,
                    "coordinates": [coordinate.model_dump(mode="json") for coordinate in corridor.coordinates],
                    "source_metadata": corridor.source_metadata.model_dump(mode="json"),
                    "source_id": corridor.corridor_id,
                    "source_path": _relpath(artifacts.map_context_path, root),
                    "evidence_type": "map_corridor",
                }
                for corridor in map_context.corridors
            ],
            "hazards": [
                {
                    "hazard_id": hazard.hazard_id,
                    "hazard_type": hazard.hazard_type,
                    "name": hazard.name,
                    "polygon": [coordinate.model_dump(mode="json") for coordinate in hazard.polygon],
                    "l2_duration_s": hazard.l2_duration_s,
                    "source_metadata": hazard.source_metadata.model_dump(mode="json"),
                    "source_id": hazard.hazard_id,
                    "source_path": _relpath(artifacts.map_context_path, root),
                    "evidence_type": "map_hazard",
                }
                for hazard in map_context.hazards
            ],
            "pois": [
                {
                    "poi_id": poi.poi_id,
                    "poi_type": poi.poi_type,
                    "name": poi.name,
                    "coordinate": poi.coordinate.model_dump(mode="json"),
                    "source_metadata": poi.source_metadata.model_dump(mode="json"),
                    "source_id": poi.poi_id,
                    "source_path": _relpath(artifacts.map_context_path, root),
                    "evidence_type": "map_poi",
                }
                for poi in map_context.pois
            ],
        },
        "map_layers": build_after_action_map_layers(
            map_source_path=_relpath(artifacts.map_context_path, root),
            map_metadata=map_metadata,
            route_source_path=_relpath(artifacts.route_path, root),
            mission_graph_source_path=_relpath(artifacts.mission_graph_path, root),
            incident_store_path=str(artifacts.incident_store_path)
            if artifacts.incident_store_path
            else None,
        ),
        "risk_rules": [
            {
                **rule.model_dump(mode="json"),
                "source_id": rule.rule_id,
                "source_path": _relpath(artifacts.risk_rules_path, root),
                "evidence_type": "risk_rule",
            }
            for rule in risk_rules.rules
        ],
        "replay": _replay_summary(replay_result, artifacts, root),
        "safety_timeline": _safety_timeline(replay_result, incidents, artifacts, root),
        "segment_capsules": _segment_capsules(replay_result, incidents, artifacts, root),
        "capability_timeline": _load_capability_summary_for_case(case_id, root=root),
        "incident_packages": [
            {
                "incident_id": package.incident_id,
                "trigger_level": package.trigger_level,
                "triggered_at": package.triggered_at,
                "trigger_event": package.trigger_event.model_dump(mode="json"),
                "raw_window_start": package.raw_window_start,
                "raw_window_end": package.raw_window_end,
                "raw_sample_count": len(package.raw_samples),
                "segment_capsule_ids": package.segment_capsule_ids,
                "source_id": package.incident_id,
                "source_path": str(artifacts.incident_store_path / f"{package.incident_id}.json") if artifacts.incident_store_path else None,
                "evidence_type": "incident_package",
            }
            for package in incidents
        ],
    }


def list_admin_cases() -> list[dict[str, str]]:
    return [
        {
            "case_id": PRETRIP_CASE_ID,
            "name": "chilai_nanhua_day1 GPX set",
            "kind": "pretrip_gpx_projection",
        },
        {
            "case_id": FIELD_CASE_ID,
            "name": "Scout 2026-05-12 field golden case",
            "kind": "field_fixture",
        }
    ]


def _build_pretrip_admin_case_view(
    case_id: str,
    *,
    root: Path,
    project_root: Path | None = None,
) -> dict[str, Any]:
    project_root = resolve_pretrip_project_root(
        case_id,
        root=root,
        project_root=project_root,
    )
    artifacts = resolve_pretrip_project_artifacts(
        case_id,
        root=root,
        project_root=project_root,
    )
    source_refs = _pretrip_artifact_refs(artifacts, project_root)
    project = _load_json(artifacts["project"])
    pretrip_view = build_pretrip_admin_view(
        case_id,
        root=root,
        project_root=project_root,
    )
    route_summary = _load_json(artifacts["route_summary"])
    map_context = _load_json(artifacts["map_context"])
    checkpoints = _load_json(artifacts["checkpoints"])
    segments = _load_json(artifacts["segments"])
    segment_display_geometry = _load_json(artifacts["segment_display_geometry"])
    reference_tracks = _load_json(artifacts["reference_tracks"])
    checkpoint_events = _load_json(artifacts["checkpoint_events"])
    admin_projection = (
        _load_json(artifacts["admin_projection"])
        if "admin_projection" in artifacts
        else _synthetic_pretrip_admin_projection(
            case_id=case_id,
            route_summary=route_summary,
            reference_track_count=reference_tracks.get("reference_track_count", 0),
            checkpoint_count=len(checkpoints),
            segment_count=len(segments),
        )
    )
    debug_projection_events = (
        _load_jsonl(artifacts["debug_projection_events"])
        if "debug_projection_events" in artifacts
        else _synthetic_pretrip_debug_projection_events(
            case_id=case_id,
            route_summary=route_summary,
            reference_track_count=reference_tracks.get("reference_track_count", 0),
            checkpoint_count=len(checkpoints),
            segment_count=len(segments),
        )
    )
    admin_projection_ref = source_refs.get(
        "admin_projection",
        "project.json#synthetic-admin-projection",
    )
    debug_projection_ref = source_refs.get(
        "debug_projection_events",
        "project.json#synthetic-debug-projection-events",
    )
    runtime_safety_state_store_projection = (
        build_runtime_safety_state_store_projection(
            case_id,
            project_root=project_root,
            state_store_index_ref=project.get("runtime_safety_state_store_index_ref"),
            state_store_dir_ref=project.get("runtime_safety_state_store_dir_ref"),
            shadow_replay_result_ref=project.get("runtime_shadow_replay_result_ref"),
            surface_targets=["/admin", "/admin/debug"],
        ).model_dump(mode="json")
    )
    pretrip_summary_source_files = [
        source_refs["route_summary"],
        source_refs["reference_tracks"],
        source_refs["segment_display_geometry"],
        debug_projection_ref,
    ]
    state_store_source_path = runtime_safety_state_store_projection.get("source_path")
    if state_store_source_path:
        pretrip_summary_source_files.append(str(state_store_source_path))

    route_points = _pretrip_route_points(segment_display_geometry, route_summary, source_refs)
    mission_checkpoints = _pretrip_mission_checkpoints(checkpoints, source_refs)
    mission_segments = _pretrip_mission_segments(segments, source_refs)
    map_payload = _pretrip_map_payload(map_context, source_refs)
    route_bounds = _bounds([(point["lat"], point["lon"]) for point in route_points])

    replay = {
        "observations_processed": route_summary["point_count"],
        "safety_level": "L0_NORMAL",
        "safety_events": [],
        "checkpoint_count": len(mission_checkpoints),
        "checkpoint_hit_count": len(mission_checkpoints),
        "progressed_checkpoints": [checkpoint["checkpoint_id"] for checkpoint in mission_checkpoints],
        "segment_capsule_count": len(mission_segments),
        "segment_capsules": [
            f"candidate_capsule.{segment['segment_id']}" for segment in mission_segments
        ],
        "incident_count": 0,
        "recording_profiles": ["pretrip_projection"],
        "completed_mission_replay": False,
        "source_id": "admin_surface_projection.chilai_nanhua_day1",
        "source_path": admin_projection_ref,
        "evidence_type": "replay_summary",
    }

    view = {
        "case_id": case_id,
        "project_id": case_id,
        "artifacts": {
            "golden_case": source_refs["project"],
            "route": source_refs["segment_display_geometry"],
            "route_summary": source_refs["route_summary"],
            "map_context": source_refs["map_context"],
            "mission_graph": source_refs["package"],
            "risk_rules": None,
            "mission_context": None,
            "route_progress_config": None,
            "incident_store": None,
            "admin_projection": admin_projection_ref,
            "debug_projection_events": debug_projection_ref,
            "runtime_safety_state_store": runtime_safety_state_store_projection.get(
                "source_path",
                "",
            ),
        },
        "summary": {
            "description": (
                f"{case_id} | {route_summary['route_name']} | "
                f"{reference_tracks['reference_track_count']} reference tracks"
            ),
            "source_files": pretrip_summary_source_files,
            "map_context": project.get("map_context_ref"),
            "bbox": route_summary["bbox_wgs84"],
            "segments": [
                {
                    "id": segment["candidate_id"],
                    "duration_s": None,
                    "records": None,
                    "valid_location_records": segment_display_geometry["segments"][index]["source_point_count"]
                    if index < len(segment_display_geometry["segments"])
                    else None,
                    "horizontal_accuracy_p90_m": None,
                    "map_inside_corridor_with_hacc_pct": None,
                    "source_id": segment["candidate_id"],
                    "source_path": source_refs["segments"],
                }
                for index, segment in enumerate(segments)
            ],
        },
        "mission": {
            "mission_id": case_id,
            "name": route_summary["route_name"],
            "route_source": "artifact.gpx.chilai_nanhua_day1",
            "checkpoints": mission_checkpoints,
            "segments": mission_segments,
            "control_zones": [
                {
                    "zone_id": "zone_pretrip_projection",
                    "name": "Pretrip projection boundary",
                    "source_id": "zone_pretrip_projection",
                    "source_path": admin_projection_ref,
                    "evidence_type": "control_zone",
                }
            ],
        },
        "route": {
            "source_path": source_refs["segment_display_geometry"],
            "bounds": route_bounds,
            "point_count": route_summary["point_count"],
            "total_progress_m": route_summary["distance_m"],
            "points": route_points,
        },
        "map": map_payload,
        "map_layers": pretrip_view["map_layers"],
        "map_candidates": pretrip_view["map_candidates"],
        "retreat_routes": pretrip_view["retreat_routes"],
        "route_notes": pretrip_view["route_notes"],
        "reference_tracks": pretrip_view["reference_tracks"],
        "reference_segment_timing": pretrip_view["reference_segment_timing"],
        "terrain_visualization": pretrip_view["terrain_visualization"],
        "segment_terrain": (
            pretrip_view.get("tabs", {})
            .get("post_analysis", {})
            .get("segment_terrain", {})
        ),
        "overpass_evidence": pretrip_view["overpass_evidence"],
        "gis_perception_timeline": pretrip_view["gis_perception_timeline"],
        "major_critical_points": pretrip_view.get("major_critical_points"),
        "boss_points": pretrip_view.get("boss_points"),
        "mileage_tag_alignment": pretrip_view.get("mileage_tag_alignment"),
        "review_queue": pretrip_view["review_queue"],
        "review_workbench": pretrip_view["review_workbench"],
        "departure_reviewed_candidates": pretrip_view.get(
            "departure_reviewed_candidates"
        ),
        "mcp_review_actions": pretrip_view.get("mcp_review_actions"),
        "departure_bundle": pretrip_view["departure_bundle"],
        "risk_score": pretrip_view["risk_score"],
        "risk_ribbon": pretrip_view["risk_ribbon"],
        "risk_heatmap": pretrip_view["risk_heatmap"],
        "risk_delta": pretrip_view["risk_delta"],
        "cwa_qpf": pretrip_view.get("cwa_qpf"),
        "cwa_weather": pretrip_view.get("cwa_weather"),
        "soil_moisture": pretrip_view.get("soil_moisture"),
        "antecedent_rain": pretrip_view.get("antecedent_rain"),
        "environment_values": pretrip_view.get("environment_values"),
        "environment_risk_derivative_layers": pretrip_view.get(
            "environment_risk_derivative_layers"
        ),
        "risk_rules": [],
        "replay": replay,
        "safety_timeline": _pretrip_safety_timeline(
            checkpoint_events,
            source_refs,
            debug_projection_ref=debug_projection_ref,
            runtime_safety_state_store_projection=runtime_safety_state_store_projection,
        ),
        "segment_capsules": _pretrip_segment_capsules(mission_segments, source_refs),
        "capability_timeline": _load_capability_summary_for_case(case_id, root=root),
        "incident_packages": [],
        "admin_surface_projection": {
            **admin_projection,
            "source_id": "admin_surface_projection.chilai_nanhua_day1",
            "source_path": admin_projection_ref,
            "evidence_type": "pretrip_admin_surface_projection",
        },
        "debug_projection": {
            "source_id": "debug_projection_events",
            "source_path": debug_projection_ref,
            "evidence_type": "pretrip_debug_projection_events",
            "event_count": len(debug_projection_events),
        },
        "runtime_safety_state_store_projection": runtime_safety_state_store_projection,
    }
    view["evidence_timeline"] = build_admin_evidence_timeline(view)
    view["scout_agent_skills"] = build_scout_agent_skill_summary(root=root)
    view["energy_reserve_monitor"] = build_energy_reserve_monitor_from_view(
        view,
        surface="admin",
    )
    return view


def _pretrip_artifact_refs(artifacts: dict[str, Path], project_root: Path) -> dict[str, str]:
    return {key: _relpath(path, project_root) for key, path in artifacts.items()}


def _pretrip_route_points(
    segment_display_geometry: dict[str, Any],
    route_summary: dict[str, Any],
    source_refs: dict[str, str],
) -> list[dict[str, Any]]:
    points_by_index: dict[int, dict[str, Any]] = {}
    total_distance = max(float(route_summary.get("distance_m") or 0.0), 0.0)
    point_count = max(int(route_summary.get("point_count") or 1), 1)
    for segment in segment_display_geometry.get("segments", []):
        start_index = int(segment.get("route_point_start_index") or 0)
        for offset, coordinate in enumerate(segment.get("coordinates", [])):
            route_index = start_index + offset
            if route_index in points_by_index:
                continue
            progress_m = total_distance * (route_index / max(point_count - 1, 1))
            points_by_index[route_index] = {
                "index": route_index,
                "lat": coordinate["lat"],
                "lon": coordinate["lon"],
                "elevation_m": None,
                "timestamp": None,
                "progress_m": round(progress_m, 2),
                "gps_horizontal_accuracy_m": None,
                "course_deg": None,
                "pedometer_distance_m": None,
                "source_id": f"route_point_{route_index}",
                "source_path": source_refs["segment_display_geometry"],
                "evidence_type": "device_observation",
            }
    return [points_by_index[index] for index in sorted(points_by_index)]


def _pretrip_mission_checkpoints(
    checkpoints: list[dict[str, Any]],
    source_refs: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "checkpoint_id": checkpoint["candidate_id"],
            "name": checkpoint.get("label") or checkpoint["candidate_id"],
            "checkpoint_type": _checkpoint_type(checkpoint),
            "lat": checkpoint["lat"],
            "lon": checkpoint["lon"],
            "arrival_radius_m": checkpoint.get("arrival_radius_m", 30.0),
            "compression_boundary": checkpoint.get("compression_boundary", True),
            "control_zone_after": "zone_pretrip_projection",
            "must_emit_checkin": checkpoint.get("checkpoint_type") in {"start", "finish"},
            "route_point_index": checkpoint.get("route_point_index"),
            "source": "artifact.gpx.chilai_nanhua_day1",
            "source_id": checkpoint["candidate_id"],
            "source_path": source_refs["checkpoints"],
            "evidence_type": "mission_checkpoint",
        }
        for checkpoint in checkpoints
    ]


def _pretrip_mission_segments(
    segments: list[dict[str, Any]],
    source_refs: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "segment_id": segment["candidate_id"],
            "name": segment.get("label") or segment["candidate_id"],
            "from_checkpoint_id": segment["from_candidate_id"],
            "to_checkpoint_id": segment["to_candidate_id"],
            "distance_m": segment.get("distance_m", 0.0),
            "elevation_gain_m": segment.get("elevation_gain_m"),
            "elevation_loss_m": segment.get("elevation_loss_m"),
            "route_point_start_index": segment.get("route_point_start_index"),
            "route_point_end_index": segment.get("route_point_end_index"),
            "source": "artifact.gpx.chilai_nanhua_day1",
            "source_id": segment["candidate_id"],
            "source_path": source_refs["segments"],
            "evidence_type": "mission_segment",
        }
        for segment in segments
    ]


def _pretrip_map_payload(
    map_context: dict[str, Any],
    source_refs: dict[str, str],
) -> dict[str, Any]:
    metadata = {
        "source": map_context.get("properties", {}).get("source", "twmap_gpx_corpus_fixture"),
        "source_version": map_context.get("properties", {}).get("source_version", "unknown"),
        "confidence": map_context.get("properties", {}).get("confidence", 0.66),
        "last_verified_at": map_context.get("properties", {}).get("last_verified_at"),
        "known_staleness_risk": map_context.get("properties", {}).get(
            "known_staleness_risk",
            "medium",
        ),
    }
    corridors: list[dict[str, Any]] = []
    hazards: list[dict[str, Any]] = []
    pois: list[dict[str, Any]] = []
    for feature in map_context.get("features", []):
        properties = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        feature_id = feature.get("id") or properties.get("id")
        feature_metadata = {
            **metadata,
            "source": properties.get("source", metadata["source"]),
            "source_version": properties.get("source_version", metadata["source_version"]),
            "confidence": properties.get("confidence", metadata["confidence"]),
            "known_staleness_risk": properties.get(
                "known_staleness_risk",
                metadata["known_staleness_risk"],
            ),
        }
        if properties.get("feature_type") == "approved_corridor":
            corridors.append(
                {
                    "corridor_id": feature_id,
                    "name": properties.get("name", feature_id),
                    "route_level": properties.get("route_level"),
                    "corridor_half_width_m": properties.get("corridor_half_width_m", 30.0),
                    "coordinates": _geojson_line_coordinates(geometry),
                    "source_metadata": feature_metadata,
                    "source_id": feature_id,
                    "source_path": source_refs["map_context"],
                    "evidence_type": "map_corridor",
                }
            )
        elif properties.get("feature_type") == "hazard_zone":
            coordinates = geometry.get("coordinates", [[]])
            hazards.append(
                {
                    "hazard_id": feature_id,
                    "hazard_type": properties.get("hazard_type", "unknown"),
                    "name": properties.get("name", feature_id),
                    "polygon": _geojson_coordinates(coordinates[0] if coordinates else []),
                    "l2_duration_s": properties.get("l2_duration_s", 30.0),
                    "source_metadata": feature_metadata,
                    "source_id": feature_id,
                    "source_path": source_refs["map_context"],
                    "evidence_type": "map_hazard",
                }
            )
        elif properties.get("feature_type") == "poi":
            coordinate = _geojson_point_coordinate(geometry)
            pois.append(
                {
                    "poi_id": feature_id,
                    "poi_type": properties.get("poi_type", "unknown"),
                    "name": properties.get("name", feature_id),
                    "coordinate": coordinate,
                    "source_metadata": feature_metadata,
                    "source_id": feature_id,
                    "source_path": source_refs["map_context"],
                    "evidence_type": "map_poi",
                }
            )
    return {
        "source_path": source_refs["map_context"],
        "metadata": metadata,
        "corridors": corridors,
        "hazards": hazards,
        "pois": pois,
    }


def _pretrip_safety_timeline(
    checkpoint_events: dict[str, Any],
    source_refs: dict[str, str],
    *,
    debug_projection_ref: str,
    runtime_safety_state_store_projection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    timeline = [
        {
            "timestamp": 0.0,
            "label": "L0_NORMAL",
            "reason": (
                "Pretrip GPX projection is candidate-only; no Phase 1 runtime "
                "safety event was replayed."
            ),
            "source_id": "debug_projection_events",
            "source_path": debug_projection_ref,
            "evidence_type": "runtime_decision",
        }
    ]
    for event in checkpoint_events.get("events", []):
        timeline.append(
            {
                "timestamp": event.get("progress_m"),
                "label": event.get("checkpoint_candidate_id"),
                "reason": (
                    f"Checkpoint candidate {event.get('checkpoint_candidate_id')} "
                    "is projected from the chilai_nanhua_day1 GPX set."
                ),
                "checkpoint": {
                    "checkpoint_id": event.get("checkpoint_candidate_id"),
                    "checkpoint_type": event.get("checkpoint_type"),
                    "lat": event.get("lat"),
                    "lon": event.get("lon"),
                    "name": event.get("label"),
                },
                "distance_m": 0.0,
                "source_id": event.get("checkpoint_candidate_id"),
                "source_path": source_refs["checkpoint_events"],
                "evidence_type": "replay_checkpoint",
            }
        )
    projection = runtime_safety_state_store_projection or {}
    latest = projection.get("latest_snapshot") if isinstance(projection, dict) else None
    if projection.get("status") == "ready" and isinstance(latest, dict):
        timeline.append(
            {
                "timestamp": None,
                "label": latest.get("ln_level_candidate") or "runtime_state_store",
                "reason": (
                    "Runtime safety state-store replay projection is available "
                    "for admin review; this is not Phase 1 runtime truth."
                ),
                "source_id": latest.get("snapshot_id"),
                "source_path": projection.get("source_path", ""),
                "source_refs": projection.get("source_refs", []),
                "evidence_type": "runtime_safety_state_store_replay",
                "runtime_safety_truth": False,
                "phase1_runtime_safety_truth": False,
                "phase1_l0_l4_state_mutated": False,
                "safety_api_called": False,
                "selected_gate_id": latest.get("selected_gate_id"),
                "reducer_state": latest.get("reducer_state"),
                "recommendation": latest.get("recommendation"),
                "route_id": latest.get("route_id"),
                "segment_id": latest.get("segment_id"),
                "checkpoint_id": latest.get("checkpoint_id"),
                "map_target_ids": latest.get("map_target_ids", []),
            }
        )
    return timeline


def _pretrip_segment_capsules(
    mission_segments: list[dict[str, Any]],
    source_refs: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {
            "capsule_id": f"candidate_capsule.{segment['segment_id']}",
            "segment_id": segment["segment_id"],
            "start_checkpoint_id": segment["from_checkpoint_id"],
            "end_checkpoint_id": segment["to_checkpoint_id"],
            "source_id": f"candidate_capsule.{segment['segment_id']}",
            "source_path": source_refs["segments"],
            "evidence_type": "segment_capsule",
        }
        for segment in mission_segments
    ]


def _checkpoint_type(checkpoint: dict[str, Any]) -> str:
    checkpoint_type = checkpoint.get("checkpoint_type")
    if checkpoint_type in {"start", "finish"}:
        return checkpoint_type
    return "waypoint"


def _geojson_line_coordinates(geometry: dict[str, Any]) -> list[dict[str, float]]:
    if geometry.get("type") != "LineString":
        return []
    return _geojson_coordinates(geometry.get("coordinates", []))


def _geojson_coordinates(coordinates: list[list[float]]) -> list[dict[str, float]]:
    return [{"lat": float(lat), "lon": float(lon)} for lon, lat in coordinates]


def _geojson_point_coordinate(geometry: dict[str, Any]) -> dict[str, float]:
    lon, lat = geometry.get("coordinates", [0.0, 0.0])
    return {"lat": float(lat), "lon": float(lon)}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_capability_summary_for_case(case_id: str, *, root: Path) -> dict[str, Any] | None:
    output_dir = root / "tests" / "fixtures" / "post_analysis" / f"{case_id}_post_analysis" / "outputs"
    timeline_path = output_dir / "capability_timeline.json"
    capsule_path = output_dir / "capability_capsule.json"
    if not timeline_path.exists() or not capsule_path.exists():
        return None
    return summarize_capability_artifacts(
        timeline_path=timeline_path,
        capsule_path=capsule_path,
        root=root,
    )


def _synthetic_pretrip_admin_projection(
    *,
    case_id: str,
    route_summary: dict[str, Any],
    reference_track_count: int,
    checkpoint_count: int,
    segment_count: int,
) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_admin_surface_projection",
        "schema_version": "0.1.0",
        "project_id": case_id,
        "surface_targets": ["/admin", "/admin/pretrip", "/admin/debug"],
        "projection_only": True,
        "import_stage": "pretrip",
        "route": {
            "route_role": "golden_route_reference",
            "route_name": route_summary["route_name"],
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "bbox_wgs84": route_summary["bbox_wgs84"],
            "route_summary_ref": "normalized/routes/route_summary.json",
            "map_context_ref": "normalized/map/map_context.geojson",
        },
        "candidate_counts": {
            "checkpoint_candidate_count": checkpoint_count,
            "segment_candidate_count": segment_count,
            "reference_track_count": reference_track_count,
        },
        "pretrip_surface": {
            "project_ref": "project.json",
            "package_ref": "outputs/pretrip_package.json",
        },
        "after_action_surface": {
            "after_action_style_projection": True,
            "completed_mission_replay": False,
            "incident_package_source": False,
            "pretrip_actual_user_track_available": False,
            "pretrip_golden_route_replacement_expected_after_return": True,
        },
        "debug_surface": {
            "debug_projection_events_ref": "project.json#synthetic-debug-projection-events",
            "file_runtime_debug_log_compatible": True,
            "live_runtime_events": False,
        },
        "boundary": _pretrip_projection_boundary(),
    }


def _synthetic_pretrip_debug_projection_events(
    *,
    case_id: str,
    route_summary: dict[str, Any],
    reference_track_count: int,
    checkpoint_count: int,
    segment_count: int,
) -> list[dict[str, Any]]:
    boundary = _pretrip_projection_boundary()
    base_payload = {
        "project_id": case_id,
        "profile": "pi-offline",
        "import_stage": "pretrip",
        "route_role": "golden_route_reference",
        "projection_only": True,
        "boundary": boundary,
    }
    events = [
        ("debug_session_started", "chilai_nanhua_day1 GPX projection started.", {}),
        (
            "provider_status_recorded",
            "Local GPX corpus projection sources were inspected.",
            {
                "provider": "local_gpx_corpus",
                "golden_route_count": 1,
                "reference_track_count": reference_track_count,
                "network_calls_allowed": False,
            },
        ),
        (
            "progress_update_recorded",
            "Pretrip route candidates were generated from the GPX set.",
            {
                "route_point_count": route_summary["point_count"],
                "distance_m": route_summary["distance_m"],
                "checkpoint_candidate_count": checkpoint_count,
                "segment_candidate_count": segment_count,
            },
        ),
        (
            "debug_session_completed",
            "chilai_nanhua_day1 GPX projection completed without runtime mutation.",
            {
                "safety_level": "L0_NORMAL",
                "observations_processed": route_summary["point_count"],
                "mission_graph_compiled": False,
                "actual_user_track_available": False,
            },
        ),
    ]
    return [
        {
            "event_id": f"debug_event.pretrip_import.{case_id}.{index:06d}",
            "session_id": f"debug_session.pretrip_import.{case_id}",
            "mission_id": None,
            "timestamp": "2026-05-21T00:00:00+00:00",
            "sequence": index,
            "kind": kind,
            "source": "pretrip_import",
            "phase": "phase35",
            "severity": "info",
            "subject_ref": case_id,
            "correlation_refs": ["artifact.gpx.chilai_nanhua_day1"],
            "summary": summary,
            "payload": {**base_payload, **payload},
        }
        for index, (kind, summary, payload) in enumerate(events, start=1)
    ]


def _pretrip_projection_boundary() -> dict[str, bool]:
    return {
        "projection_only": True,
        "golden_route_is_reference_evidence": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "mission_graph_compiled": False,
    }


def _load_incidents(incident_store_path: Path | None) -> list[IncidentPackage]:
    if incident_store_path is None or not incident_store_path.exists():
        return []
    store = IncidentStore(incident_store_path)
    return [store.load(incident_id) for incident_id in store.list_ids()]


@lru_cache(maxsize=8)
def _cached_replay_result(
    mission_graph_path: str,
    route_path: str,
    map_context_path: str,
    risk_rules_path: str,
    mission_context_path: str,
    route_progress_config_path: str,
) -> ReplayResult:
    return replay_route(
        mission_graph_path,
        route_path,
        map_context_path=map_context_path,
        risk_rules_path=risk_rules_path,
        mission_context_path=mission_context_path,
        route_progress_config_path=route_progress_config_path,
    )


def _artifact_refs(artifacts: AdminCaseArtifacts, root: Path) -> dict[str, str | None]:
    return {
        "golden_case": _relpath(artifacts.golden_case_path, root),
        "route": _relpath(artifacts.route_path, root),
        "map_context": _relpath(artifacts.map_context_path, root),
        "mission_graph": _relpath(artifacts.mission_graph_path, root),
        "risk_rules": _relpath(artifacts.risk_rules_path, root),
        "mission_context": _relpath(artifacts.mission_context_path, root),
        "route_progress_config": _relpath(artifacts.route_progress_config_path, root),
        "incident_store": str(artifacts.incident_store_path) if artifacts.incident_store_path else None,
    }


def _bounds(points: list[tuple[float, float]]) -> dict[str, float]:
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    return {
        "south": min(lats),
        "west": min(lons),
        "north": max(lats),
        "east": max(lons),
    }


def _replay_summary(
    replay_result: ReplayResult,
    artifacts: AdminCaseArtifacts,
    root: Path,
) -> dict[str, Any]:
    progressed_checkpoints = [
        update.checkpoint.checkpoint_id
        for update in replay_result.progress_updates
        if update.checkpoint is not None
    ]
    return {
        "observations_processed": replay_result.observations_processed,
        "safety_level": str(replay_result.safety_state.level),
        "safety_events": [str(event.event_type) for event in replay_result.safety_events],
        "checkpoint_count": len(progressed_checkpoints),
        "checkpoint_hit_count": len(replay_result.checkpoint_hits),
        "progressed_checkpoints": progressed_checkpoints,
        "segment_capsule_count": len(replay_result.segment_capsules),
        "segment_capsules": [capsule.capsule_id for capsule in replay_result.segment_capsules],
        "incident_count": len(replay_result.incident_packages),
        "recording_profiles": sorted({str(decision.profile) for decision in replay_result.recording_decisions}),
        "source_id": "field_replay_result",
        "source_path": _relpath(artifacts.route_progress_config_path, root),
        "evidence_type": "replay_summary",
    }


def _safety_timeline(
    replay_result: ReplayResult,
    incidents: list[IncidentPackage],
    artifacts: AdminCaseArtifacts,
    root: Path,
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for arrival in replay_result.checkpoint_hits:
        timeline.append(
            {
                "timestamp": arrival.segment_capsule.started_at if arrival.segment_capsule else None,
                "label": arrival.checkpoint.checkpoint_id,
                "reason": f"Checkpoint {arrival.checkpoint.checkpoint_id} reached within {arrival.distance_m:.1f}m.",
                "checkpoint": arrival.checkpoint.model_dump(mode="json"),
                "distance_m": arrival.distance_m,
                "source_id": arrival.checkpoint.checkpoint_id,
                "source_path": _relpath(artifacts.mission_graph_path, root),
                "evidence_type": "replay_checkpoint",
            }
        )
    for capsule in replay_result.segment_capsules:
        timeline.append(
            {
                "timestamp": capsule.ended_at,
                "label": capsule.segment_id,
                "reason": f"Segment capsule {capsule.segment_id} sealed.",
                "capsule": capsule.model_dump(mode="json"),
                "source_id": capsule.capsule_id,
                "source_path": _relpath(artifacts.mission_graph_path, root),
                "evidence_type": "segment_capsule",
            }
        )
    for package in incidents:
        for transition in package.safety_transitions:
            timeline.append(
                {
                    **transition.model_dump(mode="json"),
                    "source_id": package.incident_id,
                    "source_path": str(artifacts.incident_store_path / f"{package.incident_id}.json") if artifacts.incident_store_path else None,
                    "evidence_type": "runtime_decision",
                }
            )
        if not package.safety_transitions:
            timeline.append(
                {
                    "from_level": None,
                    "to_level": package.trigger_level,
                    "timestamp": package.triggered_at,
                    "reason": package.trigger_event.reason,
                    "event": package.trigger_event.model_dump(mode="json"),
                    "source_id": package.incident_id,
                    "source_path": str(artifacts.incident_store_path / f"{package.incident_id}.json") if artifacts.incident_store_path else None,
                    "evidence_type": "runtime_decision",
                }
            )
    if not replay_result.safety_events:
        timeline.insert(
            0,
            {
                "timestamp": 0.0,
                "label": str(replay_result.safety_state.level),
                "reason": "Replay completed with no Ln safety events.",
                "source_id": "field_replay_result",
                "source_path": _relpath(artifacts.route_progress_config_path, root),
                "evidence_type": "runtime_decision",
            },
        )
    return sorted(timeline, key=_timeline_sort_key)


def _timeline_sort_key(item: dict[str, Any]) -> tuple[float, int]:
    if item["evidence_type"] == "runtime_decision" and item.get("source_id") == "field_replay_result":
        return (-1.0, 0)
    timestamp = item.get("timestamp")
    if timestamp is None:
        return (float("inf"), 9)
    return (float(timestamp), 1)


def _segment_capsules(
    replay_result: ReplayResult,
    incidents: list[IncidentPackage],
    artifacts: AdminCaseArtifacts,
    root: Path,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    capsules: list[dict[str, Any]] = []
    for capsule in replay_result.segment_capsules:
        seen.add(capsule.capsule_id)
        capsules.append(
            {
                **capsule.model_dump(mode="json"),
                "source_id": capsule.capsule_id,
                "source_path": _relpath(artifacts.mission_graph_path, root),
                "evidence_type": "segment_capsule",
            }
        )
    for package in incidents:
        for capsule_id in package.segment_capsule_ids:
            if capsule_id in seen:
                continue
            seen.add(capsule_id)
            capsules.append(
                {
                    "capsule_id": capsule_id,
                    "incident_id": package.incident_id,
                    "source_id": capsule_id,
                    "source_path": str(artifacts.incident_store_path / f"{package.incident_id}.json") if artifacts.incident_store_path else None,
                    "evidence_type": "segment_capsule",
                }
            )
    return capsules


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
