from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from admin_local_raster_tiles import tile_bounds_wgs84
from navigation_terrain_raster_dem import (
    TerrainDemPreparationError,
    decode_mapbox_terrain_rgb,
    encode_mapbox_terrain_rgb,
    largest_complete_tile_block,
    load_navigation_terrain_dem_manifest,
    prepare_navigation_terrain_dem_tiles,
)


def test_mapbox_terrain_rgb_round_trip_preserves_decimetre_elevation() -> None:
    encoded = encode_mapbox_terrain_rgb(1234.56)

    assert encoded == (1, 182, 218)
    assert decode_mapbox_terrain_rgb(encoded) == pytest.approx(1234.6)


def test_largest_complete_tile_block_does_not_bridge_missing_tiles() -> None:
    complete = {
        (10, 20),
        (11, 20),
        (12, 20),
        (10, 21),
        (11, 21),
        (12, 21),
        (10, 22),
        (12, 22),
    }

    block = largest_complete_tile_block(complete)

    assert block == {"x_min": 10, "x_max": 12, "y_min": 20, "y_max": 21}


def test_prepare_navigation_terrain_dem_tiles_writes_only_fully_supported_tiles(
    tmp_path: Path,
) -> None:
    project_id = "terrain-dem-demo"
    project_root = tmp_path / project_id
    source_root = tmp_path / "dtm-source"
    source_root.mkdir(parents=True)
    z, x, y = 13, 6854, 3532
    bounds = tile_bounds_wgs84(z, x, y)
    terrain_ref = "outputs/layers/normalized/terrain_visualization.geojson"
    coverage_ref = "normalized/terrain/dtm_coverage_summary.json"
    grid_path = source_root / "demo.grd"
    grid_path.write_text(
        "".join(
            f"{column * 20} {160 - row * 20} {3107.1 if column < 4 else 3107.2}\n"
            for row in range(8)
            for column in range(8)
        ),
        encoding="utf-8",
    )
    (project_root / Path(terrain_ref).parent).mkdir(parents=True)
    (project_root / terrain_ref).write_text(
        json.dumps(
            {
                "dtm_grid": {
                    "cell_resolution_m": 20,
                    "full_route_corridor_bbox_twd97": {
                        "min_x": 0,
                        "min_y": 0,
                        "max_x": 160,
                        "max_y": 160,
                    },
                    "bbox_wgs84": bounds,
                }
            }
        ),
        encoding="utf-8",
    )
    (project_root / Path(coverage_ref).parent).mkdir(parents=True)
    (project_root / coverage_ref).write_text(
        json.dumps(
            {
                "source_dirs": [str(source_root)],
                "candidate_tiles": [
                    {
                        "tile_id": "demo",
                        "grid_uri": str(grid_path),
                        "bbox_twd97": {
                            "min_x": 0,
                            "min_y": 0,
                            "max_x": 160,
                            "max_y": 160,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "terrain_visualization_ref": terrain_ref,
                "dtm_coverage_summary_ref": coverage_ref,
            }
        ),
        encoding="utf-8",
    )

    result = prepare_navigation_terrain_dem_tiles(
        project_root,
        project_id=project_id,
        zoom=z,
        tile_size=16,
        prepared_at="2026-08-07T06:00:00Z",
    )

    assert result["status"] == "ready"
    assert result["encoding"] == "mapbox"
    assert result["resampling"] == "nearest"
    assert result["nodata_policy"] == "exclude_incomplete_tiles"
    assert result["tile_block"] == {
        "x_min": x,
        "x_max": x,
        "y_min": y,
        "y_max": y,
    }
    tile_path = project_root / result["tiles_ref"] / str(z) / str(x) / f"{y}.png"
    with Image.open(tile_path) as image:
        rgba = image.convert("RGBA")
        assert rgba.size == (16, 16)
        assert set(rgba.getchannel("A").get_flattened_data()) == {255}
        decoded = [
            decode_mapbox_terrain_rgb(pixel[:3])
            for pixel in rgba.get_flattened_data()
        ]
        assert min(decoded) >= 3107.0
        assert max(decoded) <= 3107.3

    project = json.loads((project_root / "project.json").read_text())
    assert project["navigation_terrain_dem_manifest_ref"] == result["manifest_ref"]
    assert load_navigation_terrain_dem_manifest(project_root, project) == result


def test_prepare_navigation_terrain_dem_tiles_rejects_partial_alpha_as_nodata(
    tmp_path: Path,
) -> None:
    project_id = "terrain-dem-gap"
    project_root = tmp_path / project_id
    source_root = tmp_path / "dtm-source"
    source_root.mkdir(parents=True)
    z, x, y = 13, 6854, 3532
    bounds = tile_bounds_wgs84(z, x, y)
    terrain_ref = "terrain.json"
    coverage_ref = "coverage.json"
    grid_path = source_root / "gap.grd"
    grid_path.write_text(
        "".join(
            f"{column * 20} {160 - row * 20} {1000 + row + column}\n"
            for row in range(8)
            for column in range(8)
            if not (row == 3 and column == 3)
        ),
        encoding="utf-8",
    )
    (project_root).mkdir(parents=True)
    (project_root / terrain_ref).write_text(
        json.dumps(
            {
                "dtm_grid": {
                    "cell_resolution_m": 20,
                    "full_route_corridor_bbox_twd97": {
                        "min_x": 0,
                        "min_y": 0,
                        "max_x": 160,
                        "max_y": 160,
                    },
                    "bbox_wgs84": bounds,
                }
            }
        ),
        encoding="utf-8",
    )
    (project_root / coverage_ref).write_text(
        json.dumps(
            {
                "source_dirs": [str(source_root)],
                "candidate_tiles": [
                    {
                        "tile_id": "gap",
                        "grid_uri": str(grid_path),
                        "bbox_twd97": {
                            "min_x": 0,
                            "min_y": 0,
                            "max_x": 160,
                            "max_y": 160,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "terrain_visualization_ref": terrain_ref,
                "dtm_coverage_summary_ref": coverage_ref,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        TerrainDemPreparationError,
        match="fully-supported",
    ):
        prepare_navigation_terrain_dem_tiles(
            project_root,
            project_id=project_id,
            zoom=z,
            tile_size=8,
            prepared_at="2026-08-07T06:00:00Z",
        )

    assert not (project_root / "outputs/navigation/terrain_rgb/manifest.json").exists()
