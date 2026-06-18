from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_raster_label_adapter import build_raster_label_evidence
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_POINTS_REF,
    collect_pretrip_route_context,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_raster_label_adapter_normalizes_explicit_ocr_output(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    source = project_root / "outputs" / "layers" / "raw" / "rudy_ocr_labels.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(
            {
                "artifact_kind": "fixture_rudy_ocr_output",
                "labels": [
                    {
                        "id": "ocr.tile.k.001",
                        "label_text": "５．５Ｋ",
                        "bbox_px": [100, 80, 160, 112],
                        "tile_z": 15,
                        "tile_x": 27410,
                        "tile_y": 13909,
                        "tile_size_px": 256,
                        "source_ref": "rudy_twmap.z15.x27410.y13909",
                        "source_image_hash": "sha256:fixture-rudy-tile-k",
                        "confidence": 0.74,
                    },
                    {
                        "id": "ocr.tile.comm.001",
                        "label_text": "通訊點（遠傳,台哥大,112）",
                        "lat": 24.0533,
                        "lon": 121.2442,
                        "source_ref": "rudy_twmap.manual-georef",
                        "source_image_hash": "sha256:fixture-rudy-tile-comm",
                        "confidence": 0.82,
                    },
                    {
                        "id": "ocr.tile.contour.001",
                        "label_text": "1500",
                        "bbox_px": [80, 40, 130, 70],
                        "tile_bbox_wgs84": {
                            "west": 121.24,
                            "east": 121.25,
                            "south": 24.04,
                            "north": 24.05,
                            "tile_width_px": 256,
                            "tile_height_px": 256,
                        },
                        "source_ref": "rudy_twmap.tile_bbox_fixture",
                        "source_image_hash": "sha256:fixture-rudy-tile-contour",
                        "confidence": 0.69,
                    },
                    {
                        "id": "ocr.tile.road.001",
                        "label_text": "台14線94K",
                        "source_ref": "rudy_twmap.no-georef",
                        "source_image_hash": "sha256:fixture-rudy-tile-road",
                        "confidence": 0.62,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = build_raster_label_evidence(
        project_root,
        source_path=source,
        collected_at="2026-06-18T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["feature_count"] == 4
    evidence = _load(project_root / result["output_ref"])
    manifest = _load(project_root / result["manifest_ref"])
    project = _load(project_root / "project.json")
    assert project["raster_label_evidence_ref"] == result["output_ref"]
    assert project["raster_label_adapter_manifest_ref"] == result["manifest_ref"]
    assert project["raster_label_evidence_count"] == 4
    assert evidence["artifact_kind"] == "pretrip_raster_label_evidence"
    assert evidence["status"] == "normalized_from_explicit_ocr_adapter"
    assert evidence["boundary"]["candidate_only"] is True
    assert evidence["boundary"]["runtime_safety_truth"] is False
    assert evidence["network_policy"]["live_ocr_or_vision_performed"] is False
    assert evidence["source_refs"][0]["raw_payload_embedded"] is False
    assert manifest["raw_tile_embedded"] is False
    assert manifest["requires_external_ocr_engine"] is True

    features = {feature["id"]: feature for feature in evidence["features"]}
    k = features["ocr.tile.k.001"]
    assert k["properties"]["label_role"] == "trail_mileage_k_anchor"
    assert k["properties"]["normalized_mileage_k"] == "5.5K"
    assert k["properties"]["coordinate_source"] == "web_mercator_tile_pixel_bbox"
    assert k["geometry"]["type"] == "Point"
    comm = features["ocr.tile.comm.001"]
    assert comm["properties"]["label_role"] == "cellular_communication_point"
    assert comm["properties"]["communication_networks"] == ["遠傳", "台哥大", "112"]
    contour = features["ocr.tile.contour.001"]
    assert contour["properties"]["label_role"] == "contour_elevation_label"
    assert contour["properties"]["contour_elevation_m"] == 1500.0
    assert contour["properties"]["coordinate_source"] == "tile_bbox_wgs84_pixel_bbox"
    road = features["ocr.tile.road.001"]
    assert road["properties"]["label_role"] == "road_mileage_stone"
    assert road["geometry"] is None
    assert "missing_georeference" in road["properties"]["review_reasons"]


def test_raster_label_adapter_output_feeds_route_context_collection(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    source = project_root / "outputs" / "layers" / "raw" / "minimal_ocr_labels.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "id": "ocr.raster.k.5_5",
                        "label_text": "5.5K",
                        "lat": 24.0533,
                        "lon": 121.2442,
                        "source_ref": "rudy_twmap.fixture",
                        "source_image_hash": "sha256:fixture-k",
                        "confidence": 0.8,
                    },
                    {
                        "id": "ocr.raster.road.94",
                        "label_text": "台14線94K",
                        "lat": 24.0826,
                        "lon": 121.2157,
                        "source_ref": "rudy_twmap.fixture",
                        "source_image_hash": "sha256:fixture-road",
                        "confidence": 0.7,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    build_raster_label_evidence(
        project_root,
        source_path=source,
        collected_at="2026-06-18T00:00:00Z",
    )

    collect_pretrip_route_context(
        project_root,
        dry_run=False,
        limit_route_notes=1,
        collected_at="2026-06-18T00:00:00Z",
    )

    points = _load(project_root / ROUTE_CONTEXT_POINTS_REF)
    raster_points = [
        point
        for point in points["points"]
        if point["source_refs"][0]["source_kind"] == "raster_label_evidence"
    ]
    assert any(
        point["evidence_type"] == "trail_mileage_k_anchor"
        and point["normalized_mileage_k"] == "5.5K"
        for point in raster_points
    )
    assert any(
        point["evidence_type"] == "road_mileage_stone"
        and point["normalized_mileage_k"] == "94K"
        for point in raster_points
    )
