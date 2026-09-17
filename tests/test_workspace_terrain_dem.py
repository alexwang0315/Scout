from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from workspace_terrain_dem import (
    GdalWorkspaceDemAdapter,
    WorkspaceDemConfig,
    WorkspaceDemError,
    load_workspace_dem,
    prepare_workspace_dem,
    require_analysis_coverage,
    _resolve_source_crs,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeGdal:
    def __init__(self):
        self.calls = []
        self.nodata = False
        self.crs = 3826
        self.insufficient_extent = False

    def inspect(self, path, *, statistics=False):
        if not statistics:
            size = [10, 10] if self.insufficient_extent else [10_000, 10_000]
            transform = [200_010, 20, 0, 2_700_010, 0, -20]
        else:
            window = self.calls[-1][1]
            transform = [window[0], 20, 0, window[1], 0, -20]
            size = [
                round((window[2] - window[0]) / 20),
                round((window[1] - window[3]) / 20),
            ]
        return {
            "size": size,
            "geoTransform": transform,
            "stac": {"proj:epsg": self.crs},
            "inventory": {
                "finite_cell_count": size[0] * size[1] - int(self.nodata),
                "nodata_cell_count": int(self.nodata),
            },
            "bands": [
                {
                    "metadata": {
                        "": {
                            "STATISTICS_VALID_PERCENT": "99" if self.nodata else "100",
                            "STATISTICS_MINIMUM": "10",
                            "STATISTICS_MAXIMUM": "2000",
                        }
                    }
                }
            ],
        }

    def clip(self, source, output, *, window, crs_override=None):
        self.calls.append((source, window))
        output.write_bytes(json.dumps(window).encode())
        return [
            "gdal_translate",
            "-projwin",
            *map(str, window),
            str(source),
            str(output),
        ]

    def version(self):
        return "fake-gdal"


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    source = tmp_path / "source.tif"
    source.write_bytes(b"source")
    refs = {
        "parent.json": b"parent",
        "prepared.tif": b"prepared",
        "coverage.json": b"coverage",
    }
    for ref, data in refs.items():
        (root / ref).write_bytes(data)
    return {
        "project_root": root,
        "project_id": "workspace",
        "source_path": source,
        "source_ref": "coverage.json#raster_sources/0/full_dem",
        "source_hashes": {
            **{ref: _sha(root / ref) for ref in refs},
            "coverage.json#raster_sources/0/full_dem": _sha(source),
        },
        "parent_ref": "parent.json",
        "parent_dem_ref": "prepared.tif",
        "coverage_ref": "coverage.json",
        "route_bounds": {
            "min_x": 242479.596,
            "min_y": 2581030.537,
            "max_x": 277868.065,
            "max_y": 2606119.118,
        },
        "resolution_m": 20,
    }


def test_prepare_stores_route_plus_maximum_analysis_margin_in_workspace(inputs):
    adapter = FakeGdal()
    result = prepare_workspace_dem(**inputs, adapter=adapter)
    root = inputs["project_root"]
    assert (root / result.dem_ref).is_file()
    assert (root / result.manifest_ref).is_file()
    assert result.authority == "candidate_only"
    assert result.runtime_safety_truth is False
    assert result.adds_source_resolution is False
    assert result.resolution_m == 20
    assert result.max_analysis_margin_m == 5000
    for x in (inputs["route_bounds"]["min_x"], inputs["route_bounds"]["max_x"]):
        for y in (inputs["route_bounds"]["min_y"], inputs["route_bounds"]["max_y"]):
            require_analysis_coverage(
                result, projected_points=[(x, y), (x + 0.1, y)], margin_m=5000
            )
    assert result.nodata_cell_count == 0
    assert result.finite_cell_count == result.width * result.height
    assert (result.bounds["min_x"] - 200010) % 20 == 0
    assert len(adapter.calls) == 1


def test_original_failed_ab_is_inside_route_but_requires_more_than_250m(inputs):
    from pretrip_source_ingest import wgs84_to_twd97

    points = [
        wgs84_to_twd97(lat, lon)
        for lon, lat in [(121.27166904, 23.33401754), (121.23066591, 23.35160555)]
    ]
    route = inputs["route_bounds"]
    assert all(
        route["min_x"] <= x <= route["max_x"] and route["min_y"] <= y <= route["max_y"]
        for x, y in points
    )
    assert max(x for x, _ in points) + 1000 > route["max_x"] + 250
    result = prepare_workspace_dem(**inputs, adapter=FakeGdal())
    require_analysis_coverage(result, projected_points=points, margin_m=1000)


def test_cache_is_reusable_without_original_material_and_is_hash_checked(inputs):
    adapter = FakeGdal()
    result = prepare_workspace_dem(**inputs, adapter=adapter)
    inputs["source_path"].unlink()
    loaded = load_workspace_dem(
        inputs["project_root"],
        manifest_ref=result.manifest_ref,
        expected_hashes=inputs["source_hashes"],
        project_id="workspace",
    )
    assert loaded == result
    assert len(adapter.calls) == 1
    (inputs["project_root"] / result.dem_ref).write_bytes(b"tampered")
    with pytest.raises(WorkspaceDemError, match="hash"):
        load_workspace_dem(
            inputs["project_root"],
            manifest_ref=result.manifest_ref,
            expected_hashes=inputs["source_hashes"],
            project_id="workspace",
        )


@pytest.mark.parametrize("damage", ["nodata", "crs", "extent", "hash"])
def test_incomplete_sources_do_not_publish_a_dem(inputs, damage):
    adapter = FakeGdal()
    if damage == "nodata":
        adapter.nodata = True
    elif damage == "crs":
        adapter.crs = 4326
    elif damage == "extent":
        adapter.insufficient_extent = True
    else:
        inputs["source_path"].write_bytes(b"changed")
    with pytest.raises(WorkspaceDemError):
        prepare_workspace_dem(**inputs, adapter=adapter)
    assert not list(inputs["project_root"].rglob("manifest.json"))


def test_stale_binding_and_out_of_coverage_are_explicit(inputs):
    result = prepare_workspace_dem(**inputs, adapter=FakeGdal())
    with pytest.raises(WorkspaceDemError, match="binding"):
        load_workspace_dem(
            inputs["project_root"],
            manifest_ref=result.manifest_ref,
            expected_hashes={**inputs["source_hashes"], "parent.json": "0" * 64},
            project_id="workspace",
        )
    with pytest.raises(WorkspaceDemError, match="analysis extent"):
        require_analysis_coverage(
            result,
            projected_points=[(200000, 2600000), (210000, 2600000)],
            margin_m=1000,
        )


def test_same_inputs_reuse_same_preparation(inputs):
    adapter = FakeGdal()
    first = prepare_workspace_dem(**inputs, adapter=adapter)
    second = prepare_workspace_dem(**inputs, adapter=adapter)
    assert first == second
    assert len(adapter.calls) == 1


def test_gdal_clip_does_not_resample_or_fill_missing_cells(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        GdalWorkspaceDemAdapter,
        "_run",
        lambda self, tool, args: calls.append((tool, args)) or "",
    )
    adapter = GdalWorkspaceDemAdapter()
    adapter.clip(tmp_path / "in.tif", tmp_path / "out.tif", window=(10, 110, 90, 30))
    tool, args = calls[0]
    assert tool == "gdal_translate"
    assert "-epo" in args
    assert "-tr" not in args
    assert "-outsize" not in args
    assert "-a_srs" not in args
    assert "-projwin" in args
    assert WorkspaceDemConfig().max_analysis_margin_m == 5000


@pytest.fixture
def provider_crs(tmp_path):
    path = tmp_path / "Metadata.xml"
    path.write_text(
        "<metadata><referenceSystemInfo><code><CharacterString>EPSG:3826</CharacterString></code></referenceSystemInfo></metadata>"
    )
    metadata = {
        "stac": {
            "proj:epsg": None,
            "proj:wkt2": "original TM121 WKT",
            "proj:projjson": {
                "type": "ProjectedCRS",
                "base_crs": {"id": {"authority": "EPSG", "code": 4326}},
                "conversion": {
                    "method": {"id": {"code": 9807}},
                    "parameters": [
                        {"id": {"code": code}, "value": value, "unit": unit}
                        for code, value, unit in [
                            (8801, 0, "degree"),
                            (8802, 121, "degree"),
                            (8805, 0.9999, "unity"),
                            (8806, 250000, "metre"),
                            (8807, 0, "metre"),
                        ]
                    ],
                },
                "coordinate_system": {
                    "axis": [
                        {"direction": direction, "unit": "metre"}
                        for direction in ("east", "north")
                    ]
                },
            },
        }
    }
    return metadata, path


def test_provider_resolution_records_original_crs_and_metadata_hash(provider_crs):
    metadata, path = provider_crs
    result = _resolve_source_crs(metadata, path)
    assert result["method"] == "registered_provider_metadata_tm121"
    assert result["metadata_sha256"] == _sha(path)
    assert result["original_wkt"] == "original TM121 WKT"


@pytest.mark.parametrize(
    "damage",
    ["known_other_crs", "wrong_meridian", "wrong_metadata", "missing_metadata"],
)
def test_crs_normalization_is_not_a_generic_mismatch_override(provider_crs, damage):
    metadata, path = provider_crs
    if damage == "known_other_crs":
        metadata["stac"]["proj:epsg"] = 4326
    elif damage == "wrong_meridian":
        metadata["stac"]["proj:projjson"]["conversion"]["parameters"][1]["value"] = 119
    elif damage == "wrong_metadata":
        path.write_text(
            "<metadata><referenceSystemInfo><code><CharacterString>EPSG:3828</CharacterString></code></referenceSystemInfo></metadata>"
        )
    else:
        path = None
    with pytest.raises(WorkspaceDemError):
        _resolve_source_crs(metadata, path)
