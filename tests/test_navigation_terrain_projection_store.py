from __future__ import annotations

import json
import os
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

import navigation_terrain_projection_store
from navigation_terrain_projection_store import (
    NAVIGATION_TERRAIN_PROJECTION_REF,
    NavigationTerrainProjectionCoordinator,
    compile_navigation_terrain_projection,
)


class _ManualExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []
        self.future: Future[dict[str, Any]] = Future()

    def submit(
        self,
        function: Callable[..., dict[str, Any]],
        *args: Any,
    ) -> Future[dict[str, Any]]:
        self.calls.append((function, args))
        return self.future


def _project(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    project_root = tmp_path / "navigation-demo"
    terrain_ref = "outputs/layers/normalized/terrain_visualization.geojson"
    route_ref = "outputs/layers/normalized/terrain_route_samples.geojson"
    risk_ref = "outputs/layers/candidates/terrain_risk_candidates.json"
    project = {
        "project_id": "navigation-demo",
        "terrain_visualization_ref": terrain_ref,
        "terrain_route_samples_ref": route_ref,
        "terrain_risk_candidates_ref": risk_ref,
    }
    _write_json(project_root / "project.json", project)
    _write_json(project_root / terrain_ref, {"features": []})
    _write_json(project_root / route_ref, {"type": "FeatureCollection", "features": []})
    _write_json(project_root / risk_ref, {"candidates": []})
    return project_root, project


def _ready_projection() -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_terrain_intelligence.v0",
        "artifact_kind": "navigation_terrain_intelligence_projection",
        "project_id": "navigation-demo",
        "status": "ready",
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compile_persists_complete_projection_and_project_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root, project = _project(tmp_path)
    build_calls = 0

    def fake_build(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal build_calls
        build_calls += 1
        return _ready_projection()

    monkeypatch.setattr(
        navigation_terrain_projection_store,
        "build_navigation_terrain_projection",
        fake_build,
    )

    payload = compile_navigation_terrain_projection(
        project_root,
        project=project,
        project_id="navigation-demo",
        compiled_at="2026-07-29T07:00:00Z",
    )

    artifact_path = project_root / NAVIGATION_TERRAIN_PROJECTION_REF
    persisted_project = json.loads((project_root / "project.json").read_text())
    persisted_payload = json.loads(artifact_path.read_text())
    assert build_calls == 1
    assert payload == persisted_payload
    assert payload["projection_state"] == "ready"
    assert payload["projection_compilation"]["input_fingerprint"]
    assert persisted_project["navigation_terrain_projection_ref"] == (
        NAVIGATION_TERRAIN_PROJECTION_REF
    )
    assert persisted_project["navigation_terrain_projection_status"] == "ready"
    assert persisted_project["navigation_terrain_projection_compiled_at"] == (
        "2026-07-29T07:00:00Z"
    )


def test_coordinator_coalesces_identical_cold_requests(
    tmp_path: Path,
) -> None:
    project_root, project = _project(tmp_path)
    executor = _ManualExecutor()
    coordinator = NavigationTerrainProjectionCoordinator(executor=executor)

    first = coordinator.resolve(
        project_root,
        project,
        project_id="navigation-demo",
    )
    second = coordinator.resolve(
        project_root,
        project,
        project_id="navigation-demo",
    )

    assert first.http_status == 202
    assert second.http_status == 202
    assert first.payload["status"] == "preparing"
    assert second.payload["status"] == "preparing"
    assert first.payload["input_fingerprint"] == second.payload["input_fingerprint"]
    assert first.payload["retry_after_ms"] == 1000
    assert len(executor.calls) == 1


def test_coordinator_serves_valid_persisted_projection_without_scheduling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root, project = _project(tmp_path)
    monkeypatch.setattr(
        navigation_terrain_projection_store,
        "build_navigation_terrain_projection",
        lambda *_args, **_kwargs: _ready_projection(),
    )
    compile_navigation_terrain_projection(
        project_root,
        project=project,
        project_id="navigation-demo",
        compiled_at="2026-07-29T07:00:00Z",
    )
    persisted_project = json.loads((project_root / "project.json").read_text())
    executor = _ManualExecutor()
    coordinator = NavigationTerrainProjectionCoordinator(executor=executor)

    resolution = coordinator.resolve(
        project_root,
        persisted_project,
        project_id="navigation-demo",
    )

    assert resolution.http_status == 200
    assert resolution.payload["projection_state"] == "ready"
    assert resolution.payload["projection_delivery"]["served_from"] == (
        "persisted_workspace_artifact"
    )
    assert executor.calls == []


def test_fingerprint_tracks_expert_reference_lists_and_acceptance_policy(
    tmp_path: Path,
) -> None:
    project_root, project = _project(tmp_path)
    expert_ref = "reviews/navigation/expert-a.json"
    policy_ref = "reviews/navigation/acceptance-policy.json"
    project = {
        **project,
        "terrain_expert_annotation_refs": [expert_ref],
        "terrain_acceptance_policy_ref": policy_ref,
    }
    _write_json(project_root / expert_ref, {"version": 1})
    _write_json(project_root / policy_ref, {"version": 1})
    first = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    _write_json(project_root / expert_ref, {"version": 2, "changed": True})
    second = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    assert first != second


def test_fingerprint_tracks_observed_passage_sources(tmp_path: Path) -> None:
    project_root, project = _project(tmp_path)
    reference_ref = "outputs/reference_track_display_geometry.json"
    overpass_ref = "outputs/layers/normalized/overpass_vector_evidence.geojson"
    project = {
        **project,
        "reference_track_display_geometry_ref": reference_ref,
        "overpass_vector_evidence_ref": overpass_ref,
    }
    _write_json(project_root / reference_ref, {"reference_tracks": []})
    _write_json(project_root / overpass_ref, {"features": []})
    first = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    _write_json(project_root / overpass_ref, {"features": [{"id": "changed"}]})
    second = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    assert first != second


def test_fingerprint_ignores_mtime_only_refreshes(tmp_path: Path) -> None:
    project_root, project = _project(tmp_path)
    source_path = project_root / project["terrain_visualization_ref"]
    first = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    stat = source_path.stat()
    os.utime(
        source_path,
        ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000),
    )
    second = navigation_terrain_projection_store.navigation_terrain_input_fingerprint(
        project_root,
        project,
    )

    assert second == first
