from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from incident_store import IncidentStore
from mission_graph import load_mission_graph
from offline_map import load_offline_map_context
from replay_runner import ReplayResult, replay_route
from risk_rules import load_risk_rules
from route_matching import load_gpx_route
from safety_models import IncidentPackage


ROOT = Path(__file__).resolve().parent
FIELD_CASE_ID = "scout_260512_field_golden"


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
) -> dict[str, Any]:
    artifacts = resolve_admin_case_artifacts(case_id, root=root, incident_store_path=incident_store_path)
    golden = json.loads(artifacts.golden_case_path.read_text(encoding="utf-8"))
    route = load_gpx_route(artifacts.route_path)
    mission = load_mission_graph(artifacts.mission_graph_path)
    map_context = load_offline_map_context(artifacts.map_context_path)
    risk_rules = load_risk_rules(artifacts.risk_rules_path)
    incidents = _load_incidents(artifacts.incident_store_path)
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
            "metadata": map_context.source_metadata.model_dump(mode="json"),
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
            "case_id": FIELD_CASE_ID,
            "name": "Scout 2026-05-12 field golden case",
            "kind": "field_fixture",
        }
    ]


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
