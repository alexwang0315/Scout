from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.scout_terrain_benchmark import TerrainBenchmarkError, run_benchmark


def test_scout_terrain_benchmark_measures_workspace_and_python_kernel(
    tmp_path: Path,
) -> None:
    workspace = _write_workspace(tmp_path)

    report = run_benchmark(
        project_root=workspace,
        iterations=2,
        synthetic_dem_sizes=(8,),
        probe_external_tools=True,
    )

    assert report["schema_version"] == "scout_terrain_benchmark.v0_1"
    assert report["status"] == "completed"
    assert report["project_id"] == "terrain_benchmark_fixture"
    assert report["benchmark_scope"]["workspace_preparation_metadata"] is True
    assert report["benchmark_scope"]["synthetic_python_terrain_kernel"] is True
    assert report["benchmark_scope"]["external_tool_execution"] is False
    assert report["benchmark_scope"]["qgis_processing_executed"] is False
    assert report["benchmark_scope"]["grass_processing_executed"] is False
    assert report["benchmark_scope"]["gdal_processing_executed"] is False
    assert report["authority"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "benchmark_only": True,
    }
    assert report["decision_summary"]["classification_status"] in {
        "pi_measured",
        "requires_pi_run",
    }
    assert report["decision_summary"]["external_processing_executed"] is False
    assert report["decision_summary"]["authority"]["runtime_safety_truth"] is False

    workspace_report = report["workspace_preparation"]
    assert workspace_report["refs"]["dtm_coverage_summary"]["status"] == "loaded"
    assert (
        workspace_report["refs"]["dtm_coverage_summary"]["summary"][
            "candidate_tile_count"
        ]
        == 2
    )
    assert (
        workspace_report["refs"]["segment_dtm_coverage"]["summary"]["segment_count"]
        == 1
    )
    assert (
        workspace_report["refs"]["terrain_route_samples"]["summary"]["feature_count"]
        == 2
    )

    kernel = report["synthetic_terrain_kernels"][0]
    assert kernel["grid_size"] == 8
    assert kernel["fixture"] is True
    assert kernel["synthetic"] is True
    assert kernel["authority"]["runtime_safety_truth"] is False
    assert kernel["operation"]["summary"]["duration_ms_p50"] >= 0
    assert report["external_tool_capabilities"]["execution_policy"] == (
        "path_probe_only_no_processing"
    )
    if not report["host"]["is_raspberry_pi"]:
        assert report["decision_summary"]["classification_status"] == "requires_pi_run"
        assert "Run this same benchmark on the Scout Raspberry Pi" in (
            report["decision_summary"]["next_actions"][0]
        )


def test_scout_terrain_benchmark_marks_missing_workspace_refs_without_fabricating(
    tmp_path: Path,
) -> None:
    workspace = _write_workspace(tmp_path, missing_terrain_samples=True)

    report = run_benchmark(
        project_root=workspace,
        iterations=1,
        include_synthetic=False,
    )

    terrain_samples = report["workspace_preparation"]["refs"]["terrain_route_samples"]
    assert terrain_samples["status"] == "missing_file"
    assert "terrain_route_samples" in report["decision_summary"]["workspace_refs"][
        "missing"
    ]
    assert any(
        "missing workspace refs" in action
        for action in report["decision_summary"]["next_actions"]
    )
    assert report["workspace_preparation"]["warnings"] == [
        {
            "code": "WORKSPACE_REF_MISSING_FILE",
            "message": (
                "terrain_route_samples points to missing file "
                "outputs/layers/normalized/terrain_route_samples.geojson"
            ),
        }
    ]
    assert report["authority"]["candidate_only"] is True
    assert report["authority"]["runtime_safety_truth"] is False


def test_scout_terrain_benchmark_can_run_synthetic_only() -> None:
    report = run_benchmark(
        iterations=1,
        synthetic_dem_sizes=(8, 9),
    )

    assert report["project_id"] == "synthetic-only"
    assert report["workspace_preparation"] is None
    assert [item["grid_size"] for item in report["synthetic_terrain_kernels"]] == [8, 9]
    assert report["pi_compatibility"]["status"] in {
        "measured_on_pi",
        "requires_pi_run",
    }


def test_scout_terrain_benchmark_exposes_handoff_next_action_for_non_pi() -> None:
    report = run_benchmark(iterations=1, synthetic_dem_sizes=(8,))

    if not report["host"]["is_raspberry_pi"]:
        assert report["decision_summary"]["classification_status"] == "requires_pi_run"
        assert report["decision_summary"]["operations"][0]["tier"] == (
            "unclassified_requires_pi_run"
        )


def test_scout_terrain_benchmark_fails_closed_for_bad_inputs(tmp_path: Path) -> None:
    with pytest.raises(TerrainBenchmarkError, match="iterations"):
        run_benchmark(iterations=0)

    with pytest.raises(TerrainBenchmarkError, match="project.json"):
        run_benchmark(project_root=tmp_path, iterations=1, include_synthetic=False)


def _write_workspace(
    tmp_path: Path,
    *,
    missing_terrain_samples: bool = False,
) -> Path:
    root = tmp_path / "terrain-benchmark-fixture"
    (root / "normalized" / "terrain").mkdir(parents=True)
    (root / "outputs" / "layers" / "normalized").mkdir(parents=True)
    (root / "outputs" / "risk").mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "terrain_benchmark_fixture",
                "dtm_coverage_summary_ref": "normalized/terrain/dtm_coverage_summary.json",
                "segment_dtm_coverage_ref": "normalized/terrain/segment_dtm_coverage.json",
                "terrain_route_samples_ref": (
                    "outputs/layers/normalized/terrain_route_samples.geojson"
                ),
                "terrain_visualization_ref": (
                    "outputs/layers/normalized/terrain_visualization.geojson"
                ),
                "risk_route_profile_ref": "outputs/risk/route_risk.geojson",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "normalized" / "terrain" / "dtm_coverage_summary.json").write_text(
        json.dumps(
            {
                "summary_id": "dtm.fixture",
                "route_artifact_id": "route.fixture",
                "candidate_tiles": [
                    {"tile_id": "tile-a", "resolution_x_m": 20, "resolution_y_m": 20},
                    {"tile_id": "tile-b", "resolution_x_m": 20, "resolution_y_m": 20},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "normalized" / "terrain" / "segment_dtm_coverage.json").write_text(
        json.dumps(
            {
                "summary_id": "segment.fixture",
                "segment_metadata": [
                    {
                        "segment_candidate_id": "seg.001",
                        "candidate_tiles": [{"tile_ref": "fixture:tile-a"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if not missing_terrain_samples:
        (
            root / "outputs" / "layers" / "normalized" / "terrain_route_samples.geojson"
        ).write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "artifact_kind": "pretrip_layer_terrain_route_samples",
                    "features": [
                        _terrain_sample("terrain.sample.001", 0.0),
                        _terrain_sample("terrain.sample.002", 100.0),
                    ],
                    "boundary": {
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                }
            ),
            encoding="utf-8",
        )
    (
        root / "outputs" / "layers" / "normalized" / "terrain_visualization.geojson"
    ).write_text(
        json.dumps(
            {
                "raster_overlays": [
                    {"mode": "hillshade"},
                    {"mode": "slope_shading"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "outputs" / "risk" / "route_risk.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    return root


def _terrain_sample(sample_id: str, distance_m: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [121.0, 24.0]},
        "properties": {
            "sample_id": sample_id,
            "distance_m": distance_m,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }
