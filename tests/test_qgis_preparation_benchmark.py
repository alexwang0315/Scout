from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qgis_preparation_benchmark import QgisPreparationBenchmarkError, run_benchmark


def _workspace(tmp_path: Path, *, include_dem: bool = True) -> Path:
    project_root = tmp_path / "qgis_benchmark"
    outputs = project_root / "outputs"
    terrain = project_root / "normalized" / "terrain"
    outputs.mkdir(parents=True)
    terrain.mkdir(parents=True)
    (outputs / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps(
            {
                "checkpoints": [
                    {"checkpoint_id": "start", "lat": 24.05, "lon": 121.21},
                    {"checkpoint_id": "finish", "lat": 24.06, "lon": 121.22},
                ]
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "qgis_benchmark",
                "compiled_mission_graph_reviewed_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
            }
        ),
        encoding="utf-8",
    )
    candidate_tiles = []
    if include_dem:
        for index, payload in enumerate((b"dem-a", b"dem-b")):
            path = tmp_path / f"tile-{index}.grd"
            path.write_bytes(payload)
            candidate_tiles.append(
                {
                    "tile_id": f"tile-{index}",
                    "grid_uri": str(path),
                    "intersects_route_bbox": True,
                    "resolution_x_m": 20,
                    "resolution_y_m": 20,
                }
            )
    (terrain / "dtm_coverage_summary.json").write_text(
        json.dumps({"candidate_tiles": candidate_tiles}),
        encoding="utf-8",
    )
    return project_root


def test_qgis_preparation_benchmark_measures_bounded_pre_qgis_work(tmp_path: Path) -> None:
    report = run_benchmark(
        project_root=_workspace(tmp_path),
        project_id="qgis_benchmark",
        iterations=2,
    )

    assert report["status"] == "completed"
    assert report["benchmark_scope"] == "pre_qgis_input_preparation_only"
    assert report["qgis_processing_executed"] is False
    assert report["mcp_invoked"] is False
    assert report["input_summary"]["dem_source_count"] == 2
    assert report["input_summary"]["route_point_count"] == 2
    assert report["input_summary"]["source_hash_count"] == 5
    assert report["input_summary"]["source_resolution"]["x_m"] == 20
    assert len(report["samples"]) == 2
    assert report["authority"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
    }
    assert all(sample["total_ms"] >= 0 for sample in report["samples"])


def test_qgis_preparation_benchmark_fails_closed_without_dem(tmp_path: Path) -> None:
    with pytest.raises(QgisPreparationBenchmarkError, match="DEM"):
        run_benchmark(
            project_root=_workspace(tmp_path, include_dem=False),
            project_id="qgis_benchmark",
            iterations=1,
        )
