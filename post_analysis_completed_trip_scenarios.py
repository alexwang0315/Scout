from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from post_analysis_capability import build_capability_artifacts, summarize_capability_artifacts
from post_analysis_scout_reaction_simulation import (
    build_scout_reaction_simulation_from_gpx,
)


ROOT = Path(__file__).resolve().parent
CASE_ID = "chilai_nanhua_day1"
ROUTE_FAMILY = "nenggao_andongjun"
SCENARIO_RELATIVE_DIR = Path(
    "post_analysis/chilai_nanhua_day1/completed_trip_scenarios"
)
MATERIAL_RELATIVE_DIR = Path(
    "materials/post_analysis/chilai_nanhua_day1/completed_trip_scenarios"
)
FIXTURE_SCENARIO_DIR = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_completed_trip_scenarios"
)
CHECKPOINT_DEFINITIONS_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "checkpoints.json"
)
ROUTE_TIME_ENTRIES_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "route_time_entries.json"
)


def list_completed_trip_scenarios(
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    scenario_dir = _resolve_scenario_dir(data_root=data_root, root=root)
    manifest_path = scenario_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    active = load_active_completed_trip_scenario_projection(data_root=data_root, root=root)
    scenarios = [
        _scenario_public_projection(item, manifest_path=manifest_path)
        for item in manifest.get("generated_files", [])
    ]
    return {
        "artifact_kind": "completed_trip_scenario_catalog",
        "case_id": CASE_ID,
        "route_family": ROUTE_FAMILY,
        "scenario_count": len(scenarios),
        "source_path": _relpath_or_abs(manifest_path, root),
        "source_dir": _relpath_or_abs(scenario_dir, root),
        "scenarios": scenarios,
        "active_scenario": active.get("scenario") if active else None,
        "boundary": _boundary(),
    }


def select_completed_trip_scenario_for_post_analysis(
    scenario_id: str,
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    scenario_dir = _resolve_scenario_dir(data_root=data_root, root=root)
    manifest_path = scenario_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    item = _find_scenario(manifest, scenario_id)
    scenario = _scenario_public_projection(item, manifest_path=manifest_path)
    source_gpx = Path(item["path"])
    if not source_gpx.exists():
        fallback = scenario_dir / Path(item["path"]).name
        source_gpx = fallback if fallback.exists() else source_gpx
    if not source_gpx.exists():
        raise FileNotFoundError(f"completed trip scenario GPX not found: {item['path']}")

    inbox_dir = data_root / "post_analysis" / "inbox"
    active_dir = data_root / SCENARIO_RELATIVE_DIR / "active"
    outputs_dir = data_root / SCENARIO_RELATIVE_DIR / scenario_id / "outputs"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    active_dir.mkdir(parents=True, exist_ok=True)
    active_gpx = inbox_dir / "latest_completed_trip.gpx"
    shutil.copy2(source_gpx, active_gpx)

    activated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    active_record = {
        "artifact_kind": "active_completed_trip_scenario",
        "case_id": CASE_ID,
        "scenario": scenario,
        "activated_at": activated_at,
        "source_gpx": _relpath_or_abs(source_gpx, root),
        "active_completed_track_gpx": str(active_gpx),
        "outputs_dir": str(outputs_dir),
        "boundary": _boundary(),
        "mutation": _mutation(),
    }
    _write_json(active_dir / "active_completed_trip_scenario.json", active_record)
    _write_json(inbox_dir / "latest_completed_trip_scenario.json", active_record)

    files = build_capability_artifacts(
        case_id=f"{CASE_ID}.{scenario_id}",
        completed_track_gpx=active_gpx,
        checkpoint_definitions_path=CHECKPOINT_DEFINITIONS_PATH,
        route_family=ROUTE_FAMILY,
        output_dir=outputs_dir,
        route_time_entries_path=ROUTE_TIME_ENTRIES_PATH,
        root=root,
    )
    reaction_simulation_path = outputs_dir / "scout_reaction_simulation.json"
    reaction_simulation = build_scout_reaction_simulation_from_gpx(
        active_gpx,
        scenario_id=scenario_id,
        case_id=CASE_ID,
        output_path=reaction_simulation_path,
        root=root,
    )
    capability = summarize_capability_artifacts(
        timeline_path=Path(files.timeline_path),
        capsule_path=Path(files.capsule_path),
        root=root,
    )
    active_record["capability_timeline"] = capability
    active_record["scout_reaction_simulation"] = reaction_simulation
    _write_json(active_dir / "active_completed_trip_scenario.json", active_record)
    _write_json(inbox_dir / "latest_completed_trip_scenario.json", active_record)
    return {
        "artifact_kind": "completed_trip_scenario_post_analysis_result",
        "case_id": CASE_ID,
        "scenario": scenario,
        "capability_timeline": capability,
        "scout_reaction_simulation": reaction_simulation,
        "paths": {
            "active_completed_track_gpx": str(active_gpx),
            "active_scenario_record": str(active_dir / "active_completed_trip_scenario.json"),
            "outputs_dir": str(outputs_dir),
            "capability_timeline": files.timeline_path,
            "capability_capsule": files.capsule_path,
            "capability_segments_csv": files.csv_summary_path,
            "scout_reaction_simulation": str(reaction_simulation_path),
        },
        "boundary": _boundary(),
        "mutation": _mutation(),
    }


def load_active_completed_trip_scenario_projection(
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any] | None:
    active_path = (
        data_root
        / SCENARIO_RELATIVE_DIR
        / "active"
        / "active_completed_trip_scenario.json"
    )
    if not active_path.exists():
        return None
    active = _load_json(active_path)
    outputs_dir = Path(active.get("outputs_dir", ""))
    timeline_path = outputs_dir / "capability_timeline.json"
    capsule_path = outputs_dir / "capability_capsule.json"
    if timeline_path.exists() and capsule_path.exists():
        active["capability_timeline"] = summarize_capability_artifacts(
            timeline_path=timeline_path,
            capsule_path=capsule_path,
            root=root,
        )
    simulation_path = outputs_dir / "scout_reaction_simulation.json"
    if simulation_path.exists():
        active["scout_reaction_simulation"] = _load_json(simulation_path)
    return active


def _resolve_scenario_dir(*, data_root: Path, root: Path) -> Path:
    material_dir = data_root / MATERIAL_RELATIVE_DIR
    if (material_dir / "manifest.json").exists():
        return material_dir
    fixture_dir = root / FIXTURE_SCENARIO_DIR.relative_to(ROOT)
    if (fixture_dir / "manifest.json").exists():
        return fixture_dir
    raise FileNotFoundError(
        f"completed trip scenario manifest not found under {material_dir} or {fixture_dir}"
    )


def _find_scenario(manifest: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    for item in manifest.get("generated_files", []):
        if item.get("scenario_id") == scenario_id:
            return item
    raise KeyError(scenario_id)


def _scenario_public_projection(
    item: dict[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    profile = item.get("fitness_profile") or {}
    return {
        "scenario_id": item["scenario_id"],
        "scenario_name": item.get("scenario_name") or item.get("title") or item["scenario_id"],
        "scenario_content": item.get("scenario_content") or "",
        "title": item.get("title"),
        "outcome": item.get("outcome"),
        "gpx_filename": Path(item["path"]).name,
        "gpx_path": item["path"],
        "sha256": item.get("sha256"),
        "source_routes": item.get("source_routes", []),
        "track_point_count": item.get("track_point_count"),
        "distance_m": item.get("distance_m"),
        "duration_seconds": item.get("duration_seconds"),
        "total_moving_duration_seconds": item.get("total_moving_duration_seconds"),
        "total_hold_duration_seconds": item.get("total_hold_duration_seconds"),
        "scout_note_waypoint_count": item.get("scout_note_waypoint_count", 0),
        "fitness_profile": {
            "label": profile.get("label"),
            "description": profile.get("description"),
        },
        "manifest_path": str(manifest_path),
        "boundary": _boundary(),
    }


def _boundary() -> dict[str, bool]:
    return {
        "fixture_only": True,
        "post_analysis_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "operator_trigger_required": True,
    }


def _mutation() -> dict[str, bool]:
    return {
        "active_completed_trip_inbox_written": True,
        "post_analysis_artifacts_written": True,
        "runtime_mutated": False,
        "phase1_runtime_mutated": False,
        "safety_api_called": False,
        "brain_fact_written": False,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relpath_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
