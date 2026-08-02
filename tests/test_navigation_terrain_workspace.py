from __future__ import annotations

import json
from pathlib import Path

import pytest

from navigation_terrain_workspace import (
    WorkspaceTerrainEvidenceError,
    build_workspace_route_terrain_events,
    build_workspace_route_topology,
    build_workspace_source_ledger,
    build_workspace_terrain_hierarchy,
    classify_structure_neighborhood,
    extract_dem_structure_candidates,
    load_workspace_terrain_grid,
    project_route_sample_points_twd97,
    route_sample_points,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_grid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    elevations = {
        (3, 3): 130.0,
        (7, 7): 70.0,
        (11, 12): 120.0,
        (11, 10): 120.0,
        (12, 11): 80.0,
        (10, 11): 80.0,
    }
    rows = []
    for row in range(15):
        for col in range(15):
            x = 250_000 + col * 20
            y = 2_600_000 + row * 20
            rows.append(f"{x} {y} {elevations.get((row, col), 100.0)}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, dict]:
    project_root = tmp_path / "route-demo"
    terrain_ref = "outputs/layers/normalized/terrain_visualization.geojson"
    coverage_ref = "normalized/terrain/dtm_coverage_summary.json"
    route_samples_ref = "outputs/layers/normalized/terrain_route_samples.geojson"
    grid_root = tmp_path / "dtm"
    grid_path = grid_root / "syntheticdem.grd"
    _write_grid(grid_path)
    _write_json(
        project_root / terrain_ref,
        {
            "dtm_grid": {
                "crs": "TWD97 / TM2 zone 121 (EPSG:3826-compatible)",
                "cell_resolution_m": 20,
                "full_route_corridor_bbox_twd97": {
                    "min_x": 250_000,
                    "min_y": 2_600_000,
                    "max_x": 250_280,
                    "max_y": 2_600_280,
                },
            }
        },
    )
    _write_json(
        project_root / coverage_ref,
        {
            "source_dirs": [str(grid_root)],
            "candidate_tiles": [
                {
                    "tile_id": "synthetic",
                    "grid_uri": str(grid_path),
                    "horizontal_datum": "TWD97[2020]",
                    "vertical_datum": "TWVD2001",
                    "resolution_x_m": 20,
                    "resolution_y_m": 20,
                    "bbox_twd97": {
                        "min_x": 250_000,
                        "min_y": 2_600_000,
                        "max_x": 250_280,
                        "max_y": 2_600_280,
                    },
                }
            ],
        },
    )
    _write_json(
        project_root / route_samples_ref,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [121.0 + index / 10_000, 23.5 + index / 20_000],
                    },
                    "properties": {
                        "candidate_id": f"sample-{index:03d}",
                        "distance_m": index * 100,
                        "elevation_m": 800 + index * 10,
                    },
                }
                for index in range(20)
            ],
        },
    )
    return project_root, {
        "project_id": "route-demo",
        "terrain_visualization_ref": terrain_ref,
        "dtm_coverage_summary_ref": coverage_ref,
        "terrain_route_samples_ref": route_samples_ref,
    }


def test_neighborhood_classifier_distinguishes_ridge_valley_and_saddle() -> None:
    ridge = classify_structure_neighborhood(
        130,
        [100, 100, 100, 100, 100, 100, 100, 100],
    )
    valley = classify_structure_neighborhood(
        70,
        [100, 100, 100, 100, 100, 100, 100, 100],
    )
    saddle = classify_structure_neighborhood(
        100,
        [120, 100, 80, 100, 120, 100, 80, 100],
    )

    assert ridge["feature_kind"] == "ridge"
    assert valley["feature_kind"] == "valley"
    assert saddle["feature_kind"] == "saddle"
    assert saddle["sign_changes"] == 4


def test_extractor_reads_bounded_grid_and_returns_candidate_points(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)

    result = extract_dem_structure_candidates(
        project_root,
        project,
        max_per_kind=8,
    )

    assert result["status"] == "candidate_points"
    assert result["grid"]["cell_resolution_m"] == 20
    assert 0 < result["grid"]["selected_cell_count"] <= 225
    assert result["grid"]["route_corridor_filter_applied"] is True
    assert result["counts"]["ridge"] >= 1
    assert result["counts"]["valley"] >= 1
    assert result["counts"]["saddle"] >= 1
    assert {
        point["feature_kind"] for point in result["points"]
    } == {"ridge", "valley", "saddle"}
    assert all(point["candidate_only"] is True for point in result["points"])
    assert all(point["runtime_safety_truth"] is False for point in result["points"])
    assert all("grid_uri" not in point for point in result["points"])
    assert result["boundary"]["safe_or_walkable"] == "not_determined"


def test_projection_stages_reuse_one_loaded_dem_and_route_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, project = _workspace(tmp_path)
    route_payload = json.loads(
        (project_root / project["terrain_route_samples_ref"]).read_text(
            encoding="utf-8"
        )
    )
    route_points = route_sample_points(route_payload)
    projected_route_points = project_route_sample_points_twd97(route_points)
    terrain_grid = load_workspace_terrain_grid(project_root, project)

    def unexpected_read(*_args, **_kwargs):
        pytest.fail("shared projection inputs must not reread workspace JSON")

    monkeypatch.setattr("navigation_terrain_dem._read_project_json", unexpected_read)
    monkeypatch.setattr("navigation_terrain_topology._read_project_json", unexpected_read)
    monkeypatch.setattr(
        "navigation_route_terrain_events._read_project_json",
        unexpected_read,
    )

    structures = extract_dem_structure_candidates(
        project_root,
        project,
        max_per_kind=8,
        workspace_grid=terrain_grid,
        route_points=route_points,
        projected_route_points=projected_route_points,
    )
    hierarchy = build_workspace_terrain_hierarchy(
        project_root,
        project,
        workspace_grid=terrain_grid,
        relief_threshold_m=6,
        minimum_component_cells=3,
    )
    topology = build_workspace_route_topology(
        project_root,
        project,
        structures,
        route_points=route_points,
    )
    events = build_workspace_route_terrain_events(
        project_root,
        project,
        hierarchy,
        projected_route_points=projected_route_points,
    )

    assert 0 < structures["grid"]["selected_cell_count"] <= len(
        terrain_grid.elevations
    )
    assert hierarchy["grid"]["selected_cell_count"] == len(
        terrain_grid.elevations
    )
    assert topology["status"] == "observed_baseline_topology"
    assert events["route_point_count"] == len(projected_route_points)


def test_extractor_rejects_grid_outside_declared_source_directories(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    coverage_path = project_root / project["dtm_coverage_summary_ref"]
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    outside = tmp_path / "outside.grd"
    _write_grid(outside)
    coverage["candidate_tiles"][0]["grid_uri"] = str(outside)
    _write_json(coverage_path, coverage)

    with pytest.raises(
        WorkspaceTerrainEvidenceError,
        match="outside declared DTM source directories",
    ):
        extract_dem_structure_candidates(project_root, project)


def test_source_ledger_separates_dtm_gpx_and_ordered_waypoint_clues(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    source_index_ref = "sources/historical_gpx_source_index.json"
    route_notes_ref = "normalized/notes/gpx_route_note_candidates.json"
    _write_json(
        project_root / source_index_ref,
        {
            "sources": [
                {
                    "source_id": "gpx.primary",
                    "provider": "operator_supplied_local_file",
                    "role": "golden_route_reference",
                    "route_role": "golden_route",
                    "sha256": "a" * 64,
                    "imported_at": "2026-07-23T00:00:00Z",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "source_id": "gpx.reference.001",
                    "provider": "operator_supplied_local_file",
                    "role": "reference_track",
                    "route_role": "reference_track",
                    "sha256": "b" * 64,
                    "imported_at": "2026-07-23T00:00:00Z",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ]
        },
    )
    _write_json(
        project_root / route_notes_ref,
        {
            "candidates": [
                {
                    "candidate_id": "note-2",
                    "name": "Second landmark",
                    "normalized_note": "Second landmark",
                    "note_category": "landmark_hint",
                    "source_waypoint_index": 2,
                    "ele_m": 1200,
                    "source_refs": ["gpx.primary"],
                    "source_attribution": [{"source_key": "golden_route"}],
                },
                {
                    "candidate_id": "note-0",
                    "name": "Trailhead",
                    "normalized_note": "Trailhead",
                    "note_category": "landmark_hint",
                    "source_waypoint_index": 0,
                    "ele_m": 800,
                    "source_refs": ["gpx.primary"],
                    "source_attribution": [{"source_key": "golden_route"}],
                },
            ]
        },
    )
    project.update(
        {
            "historical_gpx_source_index_ref": source_index_ref,
            "normalized_route_note_candidates_ref": route_notes_ref,
        }
    )

    result = build_workspace_source_ledger(project_root, project)

    assert result["status"] == "ready_with_historical_source_gap"
    assert result["source_tier_counts"] == {"P0": 1, "P1": 0, "P2": 2}
    assert [clue["label"] for clue in result["ordered_clues"]] == [
        "Trailhead",
        "Second landmark",
    ]
    assert result["ordered_clue_chain_kind"] == "gpx_waypoint_clues"
    assert result["coordinate_audit"]["dtm"]["crs"] == "EPSG:3826"
    assert result["coordinate_audit"]["gpx"]["crs"] == "EPSG:4326"
    assert "No archival or historical prose source" in result["evidence_gaps"][0]
    rendered = json.dumps(result)
    assert str(tmp_path) not in rendered
    assert result["boundary"]["runtime_safety_truth"] is False


def test_source_ledger_projects_traceable_p1_route_narratives(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    source_ledger_ref = "sources/navigation_historical_source_ledger.json"
    _write_json(
        project_root / source_ledger_ref,
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "sources": [
                {
                    "id": "samejan-qilai-nanhua",
                    "tier": "P1",
                    "family": "professional_route_narrative",
                    "provider": "看鯊旅 SameJan Travel",
                    "url": "https://www.samejantravel.tw/trails/example",
                    "source_location": "行程內容與路線說明",
                    "retrieved_at": "2026-07-23",
                    "claim": "公開行程描述共同進山段與兩座山峰的分流組合。",
                    "limitations": "行程敘事不是現況通行證明。",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "id": "keepon-completed-trip",
                    "tier": "P1",
                    "family": "public_completed_trip_gpx",
                    "provider": "登山補給站 Keepon",
                    "url": "https://www.keepon.com.tw/thread/example.html",
                    "source_location": "已完成行程 GPX 附件",
                    "retrieved_at": "2026-07-23",
                    "claim": "公開落地頁對應一份已完成行程的高繞軌跡。",
                    "sha256": "c" * 64,
                    "limitations": "歷史軌跡不證明目前可通行。",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ],
        },
    )
    project["historical_route_source_ledger_ref"] = source_ledger_ref

    result = build_workspace_source_ledger(project_root, project)

    assert result["status"] == "ready"
    assert result["source_tier_counts"] == {"P0": 1, "P1": 2, "P2": 0}
    assert {
        source["family"]
        for source in result["sources"]
        if source["tier"] == "P1"
    } == {"professional_route_narrative", "public_completed_trip_gpx"}
    assert not any(
        "public/professional" in gap for gap in result["evidence_gaps"]
    )
    assert all(
        source["candidate_only"] is True
        and source["runtime_safety_truth"] is False
        for source in result["sources"]
    )


def test_route_topology_uses_reusable_observed_edges_without_inventing_detours(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    structures = {
        "points": [
            {
                "id": "terrain-structure.saddle.001",
                "feature_kind": "saddle",
                "lon": 121.001,
                "lat": 23.5005,
            }
        ]
    }

    result = build_workspace_route_topology(
        project_root,
        project,
        structures,
        target_node_count=6,
    )

    assert result["status"] == "observed_baseline_topology"
    assert len(result["nodes"]) == 6
    assert len(result["edges"]) == 5
    assert result["route_options"] == [
        {
            "id": "observed-baseline",
            "label": "Prepared GPX baseline",
            "edge_ids": [
                "OBS-00-01",
                "OBS-01-02",
                "OBS-02-03",
                "OBS-03-04",
                "OBS-04-05",
            ],
            "evidence_kind": "gpx_observed",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    assert result["shared_edge_ids"] == []
    assert all(edge["kind"] == "gpx_observed" for edge in result["edges"])
    assert result["limitations"][0].startswith("Only one prepared route geometry")
    assert result["boundary"]["raw_gpx_embedded"] is False


def test_route_topology_preserves_precompiled_shared_historical_edges(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    historical_ref = "outputs/navigation/historical_route_hypothesis.json"
    _write_json(
        project_root / historical_ref,
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "topology": {
                "nodes": [
                    {"id": "A", "source_refs": ["source-a"]},
                    {"id": "switch", "source_refs": ["source-dem"]},
                    {"id": "B", "source_refs": ["source-b"]},
                ],
                "edges": [
                    {
                        "id": "H5",
                        "from": "A",
                        "to": "switch",
                        "kind": "dem_horizontal_band",
                        "coordinates": [[121.0, 23.5], [121.01, 23.51]],
                        "source_refs": ["source-dem"],
                    },
                    {
                        "id": "H4",
                        "from": "switch",
                        "to": "B",
                        "kind": "historical_trace",
                        "coordinates": [[121.01, 23.51], [121.02, 23.52]],
                        "source_refs": ["source-b"],
                    },
                    {
                        "id": "V1",
                        "from": "A",
                        "to": "switch",
                        "kind": "dem_valley_transfer",
                        "coordinates": [[121.0, 23.5], [121.01, 23.51]],
                        "source_refs": ["source-dem"],
                    },
                ],
                "route_options_edge_ids": [["H5", "H4"], ["V1", "H4"]],
                "shared_edge_ids": ["H4"],
            },
            "contradictions": [{"claim": "datum requires review"}],
            "evidence_gaps": ["V1 has no field observation."],
        },
    )
    project["historical_route_hypothesis_ref"] = historical_ref

    result = build_workspace_route_topology(project_root, project, {"points": []})

    historical = result["prepared_historical_topology"]
    assert historical["status"] == "candidate_topology"
    assert historical["route_option_count"] == 2
    assert historical["shared_edge_ids"] == ["H4"]
    assert historical["route_options"][1]["edge_ids"] == ["V1", "H4"]
    assert historical["boundary"]["safe_or_walkable"] == "not_determined"


def test_route_topology_bounds_malformed_precompiled_collections(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    historical_ref = "outputs/navigation/malformed_historical_route_hypothesis.json"
    _write_json(
        project_root / historical_ref,
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "coordinate_context": {
                "source_crs": "EPSG:3826",
                "nested": {"must": "not leak"},
            },
            "topology": {
                "nodes": {"unexpected": "mapping"},
                "edges": "unexpected string",
                "route_options_edge_ids": {"unexpected": "mapping"},
                "shared_edge_ids": "unexpected string",
            },
            "contradictions": {"unexpected": "mapping"},
            "evidence_gaps": {"unexpected": "mapping"},
        },
    )
    project["historical_route_hypothesis_ref"] = historical_ref

    result = build_workspace_route_topology(project_root, project, {"points": []})

    historical = result["prepared_historical_topology"]
    assert historical["status"] == "candidate_topology"
    assert historical["nodes"] == []
    assert historical["edges"] == []
    assert historical["route_options"] == []
    assert historical["contradictions"] == []
    assert historical["evidence_gaps"] == []
    assert historical["coordinate_context"] == {"source_crs": "EPSG:3826"}
