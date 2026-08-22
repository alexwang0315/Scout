from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.scout_prepare_route_dem_mosaic import (
    MosaicPreparationError,
    build_gdalwarp_command,
    candidate_authority,
    load_mosaic_plan,
)


def _write_coverage(path: Path, *, tile_ids: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "candidate_tiles": [
                    {
                        "tile_id": tile_id,
                        "grid_uri": f"/untrusted/original/{tile_id}dem.grd",
                        "header_uri": f"/untrusted/original/{tile_id}dem.hdr",
                        "resolution_x_m": 20.0,
                        "resolution_y_m": 20.0,
                    }
                    for tile_id in tile_ids
                ],
                "route_bbox_twd97": {
                    "crs": "TWD97 / TM2 zone 121 (EPSG:3826-compatible)",
                    "min_x": 250_001.0,
                    "min_y": 2_600_001.0,
                    "max_x": 250_399.0,
                    "max_y": 2_600_399.0,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tiles(root: Path, tile_ids: list[str]) -> None:
    root.mkdir()
    for tile_id in tile_ids:
        (root / f"{tile_id}dem.grd").write_bytes(b"grid")
        (root / f"{tile_id}dem.hdr").write_text("ncols 1\n", encoding="ascii")


def test_load_mosaic_plan_rebinds_manifest_paths_to_bounded_root(
    tmp_path: Path,
) -> None:
    tile_ids = ["96194002", "96194003"]
    coverage = tmp_path / "coverage.json"
    source_root = tmp_path / "dem"
    _write_coverage(coverage, tile_ids=tile_ids)
    _write_tiles(source_root, tile_ids)

    plan = load_mosaic_plan(
        coverage_summary=coverage,
        source_root=source_root,
        corridor_m=100.0,
        max_cells=10_000,
        max_sources=10,
    )

    assert plan.source_tile_count == 2
    assert plan.width == 30
    assert plan.height == 30
    assert plan.cell_count == 900
    assert all(path.parent == source_root.resolve() for path in plan.grid_paths)
    assert str(plan.grid_paths[0]).startswith(str(source_root.resolve()))


def test_load_mosaic_plan_accepts_county_scoped_duplicate_tiles_across_roots(
    tmp_path: Path,
) -> None:
    tile_id = "96194002"
    coverage = tmp_path / "coverage.json"
    roots = [
        tmp_path / "分幅_花蓮縣20MDEM(2025)",
        tmp_path / "分幅_南投縣20MDEM(2025)",
    ]
    coverage.write_text(
        json.dumps(
            {
                "candidate_tiles": [
                    {
                        "tile_id": tile_id,
                        "county": county,
                        "grid_uri": f"/untrusted/{county}/{tile_id}dem.grd",
                        "header_uri": f"/untrusted/{county}/{tile_id}dem.hdr",
                        "resolution_x_m": 20.0,
                        "resolution_y_m": 20.0,
                    }
                    for county in ("花蓮縣", "南投縣")
                ],
                "route_bbox_twd97": {
                    "crs": "TWD97 / TM2 zone 121 (EPSG:3826-compatible)",
                    "min_x": 250_001.0,
                    "min_y": 2_600_001.0,
                    "max_x": 250_399.0,
                    "max_y": 2_600_399.0,
                },
            }
        ),
        encoding="utf-8",
    )
    for root in roots:
        _write_tiles(root, [tile_id])

    plan = load_mosaic_plan(
        coverage_summary=coverage,
        source_roots=roots,
        corridor_m=100.0,
        max_cells=10_000,
        max_sources=10,
    )

    assert plan.source_tile_count == 2
    assert plan.unique_tile_id_count == 1
    assert plan.source_identities == ("花蓮縣:96194002", "南投縣:96194002")
    assert {path.parent for path in plan.grid_paths} == {
        root.resolve() for root in roots
    }


def test_load_mosaic_plan_rejects_invalid_tile_identity(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    source_root = tmp_path / "dem"
    _write_coverage(coverage, tile_ids=["../../escape"])
    source_root.mkdir()

    with pytest.raises(MosaicPreparationError, match="tile ID"):
        load_mosaic_plan(
            coverage_summary=coverage,
            source_root=source_root,
            corridor_m=100.0,
            max_cells=10_000,
            max_sources=10,
        )


def test_load_mosaic_plan_fails_closed_on_cell_limit(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    source_root = tmp_path / "dem"
    _write_coverage(coverage, tile_ids=["96194002"])
    _write_tiles(source_root, ["96194002"])

    with pytest.raises(MosaicPreparationError, match="cell limit"):
        load_mosaic_plan(
            coverage_summary=coverage,
            source_root=source_root,
            corridor_m=100.0,
            max_cells=899,
            max_sources=10,
        )


def test_build_gdalwarp_command_is_fixed_and_shell_free(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    source_root = tmp_path / "dem"
    _write_coverage(coverage, tile_ids=["96194002"])
    _write_tiles(source_root, ["96194002"])
    plan = load_mosaic_plan(
        coverage_summary=coverage,
        source_root=source_root,
        corridor_m=100.0,
        max_cells=10_000,
        max_sources=10,
    )

    command = build_gdalwarp_command(plan, tmp_path / "mosaic.tif")

    assert command[0] == "gdalwarp"
    assert "-s_srs" in command
    assert "EPSG:3826" in command
    assert "NUM_THREADS=1" in command
    assert str(plan.grid_paths[0]) in command
    assert not any(value in command for value in ("sh", "bash", "python", "-c"))


def test_candidate_authority_is_fail_closed() -> None:
    assert candidate_authority() == {
        "benchmark_only": True,
        "candidate_only": True,
        "operational": False,
        "runtime_safety_truth": False,
    }
