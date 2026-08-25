from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

from admin_local_raster_tiles import raster_tile_cache_path
from pretrip_raster_label_adapter import build_raster_label_evidence
from pretrip_raster_label_ocr import extract_raster_label_ocr
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


def test_raster_label_ocr_extractor_writes_explicit_adapter_input(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project_path = project_root / "project.json"
    project = _load(project_path)

    cache_root = tmp_path / "raster-tiles"
    tile_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        13,
        6853,
        3534,
        cache_root=cache_root,
    )
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    Image.new("RGB", (256, 256), (255, 255, 255)).save(tile_path)

    tile_plan_ref = "outputs/layers/plans/rudy_twmap_tile_cache_plan.json"
    raster_plan_ref = "outputs/layers/plans/raster_label_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
                "source_id": "happyman_rudy_twmap",
                "source_kind": "wmts_kvp_tile",
                "cache_root": str(cache_root),
                "tile_size": 256,
                "zoom_ranges": [
                    {
                        "z": 13,
                        "x_min": 6853,
                        "x_max": 6853,
                        "y_min": 3534,
                        "y_max": 3534,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_root / raster_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_plan",
                "preferred_ocr_source_ids": ["happyman_rudy_twmap"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project["imagery_tile_cache_plan_ref"] = tile_plan_ref
    project["raster_label_plan_ref"] = raster_plan_ref
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    def fake_ocr_runner(image_path: Path) -> list[dict]:
        assert image_path == tile_path
        return [
            {"label_text": "5.5K", "bbox_px": [10, 20, 50, 36], "confidence": 0.92},
            {"label_text": "台14線94K", "bbox_px": [60, 20, 140, 38], "confidence": 0.88},
            {"label_text": "遠傳 112", "bbox_px": [20, 80, 90, 102], "confidence": 0.86},
            {"label_text": "1500", "bbox_px": [120, 120, 160, 136], "confidence": 0.75},
        ]

    result = extract_raster_label_ocr(
        project_root,
        ocr_runner=fake_ocr_runner,
        collected_at="2026-06-20T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["label_count"] == 4
    assert result["ocr_cache_miss_count"] == 1
    assert result["ocr_cache_write_count"] == 1
    ocr_output = _load(project_root / result["output_ref"])
    assert ocr_output["artifact_kind"] == "pretrip_raster_label_ocr_output"
    assert ocr_output["raw_tile_embedded"] is False
    assert ocr_output["boundary"]["runtime_safety_truth"] is False
    labels = {label["label_text"]: label for label in ocr_output["labels"]}
    assert labels["5.5K"]["label_role"] == "trail_mileage_k_anchor"
    assert labels["台14線94K"]["label_role"] == "road_mileage_stone"
    assert labels["遠傳 112"]["label_role"] == "cellular_communication_point"
    assert labels["1500"]["label_role"] == "contour_elevation_label"
    assert all(label["source_image_hash"].startswith("sha256:") for label in labels.values())
    assert all("tile_bbox_wgs84" in label for label in labels.values())

    adapter_result = build_raster_label_evidence(
        project_root,
        source_path=result["output_ref"],
        collected_at="2026-06-20T00:00:01Z",
    )
    evidence = _load(project_root / adapter_result["output_ref"])
    features = {feature["properties"]["label_text"]: feature for feature in evidence["features"]}
    assert features["5.5K"]["properties"]["label_role"] == "trail_mileage_k_anchor"
    assert features["台14線94K"]["properties"]["label_role"] == "road_mileage_stone"
    assert features["遠傳 112"]["properties"]["communication_emergency_hint"] is True
    assert features["1500"]["properties"]["contour_elevation_m"] == 1500.0


def test_raster_label_ocr_can_process_cache_misses_with_bounded_workers(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project_path = project_root / "project.json"
    project = _load(project_path)
    cache_root = project_root / "cache" / "raster-tiles"
    from PIL import Image

    for x, color in ((6853, (255, 255, 255)), (6854, (235, 235, 235))):
        tile_path = raster_tile_cache_path(
            "chilai_nanhua_day1",
            "rudy-twmap",
            13,
            x,
            3534,
            cache_root=cache_root,
        )
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (256, 256), color).save(tile_path)

    tile_plan_ref = "outputs/layers/plans/rudy_twmap_parallel_plan.json"
    raster_plan_ref = "outputs/layers/plans/raster_label_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "rudy-twmap",
                "source_id": "happyman_rudy_twmap",
                "source_kind": "xyz_tile",
                "cache_root": str(cache_root),
                "tile_size": 256,
                "zoom_ranges": [
                    {
                        "z": 13,
                        "x_min": 6853,
                        "x_max": 6854,
                        "y_min": 3534,
                        "y_max": 3534,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_root / raster_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_plan",
                "preferred_ocr_source_ids": ["happyman_rudy_twmap"],
            }
        ),
        encoding="utf-8",
    )
    project["raster_label_tile_cache_plan_ref"] = tile_plan_ref
    project["raster_label_plan_ref"] = raster_plan_ref
    project_path.write_text(json.dumps(project), encoding="utf-8")
    both_workers_started = threading.Barrier(2, timeout=2)

    def synchronized_runner(image_path: Path) -> list[dict]:
        both_workers_started.wait()
        return [
            {
                "label_text": f"tile-{image_path.parent.name}",
                "bbox_px": [10, 10, 80, 30],
                "confidence": 0.9,
            }
        ]

    result = extract_raster_label_ocr(
        project_root,
        ocr_runner=synchronized_runner,
        max_workers=2,
        collected_at="2026-08-25T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["label_count"] == 2
    output = _load(project_root / result["output_ref"])
    assert output["counts"]["ocr_worker_count"] == 2
    assert output["counts"]["ocr_cache_write_count"] == 2


def test_raster_label_ocr_extractor_skips_timed_out_tile(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project_path = project_root / "project.json"
    project = _load(project_path)

    cache_root = tmp_path / "raster-tiles"
    tile_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        13,
        6853,
        3534,
        cache_root=cache_root,
    )
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    Image.new("RGB", (256, 256), (255, 255, 255)).save(tile_path)

    tile_plan_ref = "outputs/layers/plans/rudy_twmap_tile_cache_plan.json"
    raster_plan_ref = "outputs/layers/plans/raster_label_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
                "source_id": "happyman_rudy_twmap",
                "source_kind": "wmts_kvp_tile",
                "cache_root": str(cache_root),
                "tile_size": 256,
                "zoom_ranges": [
                    {
                        "z": 13,
                        "x_min": 6853,
                        "x_max": 6853,
                        "y_min": 3534,
                        "y_max": 3534,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_root / raster_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_plan",
                "preferred_ocr_source_ids": ["happyman_rudy_twmap"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project["imagery_tile_cache_plan_ref"] = tile_plan_ref
    project["raster_label_plan_ref"] = raster_plan_ref
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    def timing_out_runner(_image_path: Path) -> list[dict]:
        raise RuntimeError("Tesseract process timeout")

    result = extract_raster_label_ocr(
        project_root,
        ocr_runner=timing_out_runner,
        collected_at="2026-06-20T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["label_count"] == 0
    assert result["ocr_timeout_count"] == 1
    assert result["ocr_failure_count"] == 1
    output = _load(project_root / result["output_ref"])
    assert output["counts"]["ocr_timeout_count"] == 1
    assert output["skipped_tiles"][0]["reason"] == "ocr_timeout"
    assert output["labels"] == []


def test_raster_label_ocr_extractor_reuses_tile_ocr_cache(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project_path = project_root / "project.json"
    project = _load(project_path)

    cache_root = tmp_path / "raster-tiles"
    tile_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        13,
        6853,
        3534,
        cache_root=cache_root,
    )
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    Image.new("RGB", (256, 256), (255, 255, 255)).save(tile_path)

    tile_plan_ref = "outputs/layers/plans/rudy_twmap_tile_cache_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
                "source_id": "happyman_rudy_twmap",
                "source_kind": "wmts_kvp_tile",
                "cache_root": str(cache_root),
                "tile_size": 256,
                "zoom_ranges": [
                    {
                        "z": 13,
                        "x_min": 6853,
                        "x_max": 6853,
                        "y_min": 3534,
                        "y_max": 3534,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project["imagery_tile_cache_plan_ref"] = tile_plan_ref
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    calls = 0

    def first_runner(_image_path: Path) -> list[dict]:
        nonlocal calls
        calls += 1
        return [
            {"label_text": "6K", "bbox_px": [10, 20, 42, 36], "confidence": 0.9},
        ]

    first = extract_raster_label_ocr(
        project_root,
        ocr_runner=first_runner,
        collected_at="2026-06-20T00:00:00Z",
    )

    def exploding_runner(_image_path: Path) -> list[dict]:  # pragma: no cover - must not run
        raise AssertionError("cache hit should avoid OCR runner")

    second = extract_raster_label_ocr(
        project_root,
        ocr_runner=exploding_runner,
        collected_at="2026-06-20T00:01:00Z",
    )
    output = _load(project_root / second["output_ref"])

    assert calls == 1
    assert first["ocr_cache_miss_count"] == 1
    assert first["ocr_cache_write_count"] == 1
    assert second["ocr_cache_hit_count"] == 1
    assert second["ocr_cache_miss_count"] == 0
    assert second["label_count"] == 1
    assert output["counts"]["ocr_cache_hit_count"] == 1
    assert output["labels"][0]["label_text"] == "6K"
    assert output["raw_tile_embedded"] is False


def test_raster_label_ocr_extractor_reuses_empty_tile_ocr_cache(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project_path = project_root / "project.json"
    project = _load(project_path)

    cache_root = tmp_path / "raster-tiles"
    tile_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        13,
        6853,
        3534,
        cache_root=cache_root,
    )
    tile_path.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    Image.new("RGB", (256, 256), (255, 255, 255)).save(tile_path)

    tile_plan_ref = "outputs/layers/plans/rudy_twmap_tile_cache_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
                "source_id": "happyman_rudy_twmap",
                "source_kind": "wmts_kvp_tile",
                "cache_root": str(cache_root),
                "tile_size": 256,
                "zoom_ranges": [
                    {
                        "z": 13,
                        "x_min": 6853,
                        "x_max": 6853,
                        "y_min": 3534,
                        "y_max": 3534,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project["imagery_tile_cache_plan_ref"] = tile_plan_ref
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    calls = 0

    def empty_runner(_image_path: Path) -> list[dict]:
        nonlocal calls
        calls += 1
        return []

    first = extract_raster_label_ocr(
        project_root,
        ocr_runner=empty_runner,
        collected_at="2026-06-20T00:00:00Z",
    )

    def exploding_runner(_image_path: Path) -> list[dict]:  # pragma: no cover - must not run
        raise AssertionError("empty cache hit should avoid OCR runner")

    second = extract_raster_label_ocr(
        project_root,
        ocr_runner=exploding_runner,
        collected_at="2026-06-20T00:01:00Z",
    )
    output = _load(project_root / second["output_ref"])

    assert calls == 1
    assert first["ocr_cache_miss_count"] == 1
    assert first["ocr_cache_write_count"] == 1
    assert first["label_count"] == 0
    assert second["ocr_cache_hit_count"] == 1
    assert second["ocr_cache_miss_count"] == 0
    assert second["label_count"] == 0
    assert output["counts"]["ocr_cache_hit_count"] == 1
    assert output["labels"] == []
    assert output["raw_tile_embedded"] is False


def test_raster_label_ocr_extractor_reports_missing_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    project = _load(project_root / "project.json")
    tile_plan_ref = "outputs/layers/plans/empty_tile_cache_plan.json"
    (project_root / tile_plan_ref).parent.mkdir(parents=True, exist_ok=True)
    (project_root / tile_plan_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
                "source_id": "happyman_rudy_twmap",
                "cache_root": str(tmp_path / "raster-tiles"),
                "zoom_ranges": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    project["imagery_tile_cache_plan_ref"] = tile_plan_ref
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    import pretrip_raster_label_ocr as module

    monkeypatch.setattr(
        module,
        "_build_ocr_runner",
        lambda engine, *, tesseract_lang: (None, ["pytesseract", "tesseract"]),
    )

    result = extract_raster_label_ocr(
        project_root,
        collected_at="2026-06-20T00:00:00Z",
    )

    assert result["status"] == "blocked_dependency_missing"
    assert result["missing_dependencies"] == ["pytesseract", "tesseract"]
    output = _load(project_root / result["output_ref"])
    assert output["labels"] == []
    assert output["boundary"]["ocr_or_vision_performed"] is False
    assert output["candidate_only"] is True


def test_raster_label_ocr_uses_tesseract_cli_when_python_wrapper_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pretrip_raster_label_ocr as module

    monkeypatch.setattr(
        module,
        "_build_pytesseract_runner",
        lambda *, tesseract_lang: (None, ["Pillow", "pytesseract"]),
    )
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/local/bin/tesseract")
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t88.5\t八通關\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    image_path = tmp_path / "tile.png"
    image_path.write_bytes(b"fixture")

    runner, missing = module._build_ocr_runner(
        "tesseract",
        tesseract_lang="chi_tra+eng",
    )

    assert missing == []
    assert runner is not None
    assert runner(image_path) == [
        {
            "label_text": "八通關",
            "confidence": "88.5",
            "bbox_px": [10, 20, 40, 60],
            "ocr_engine": "tesseract_cli",
        }
    ]
    assert calls == [
        [
            "/usr/local/bin/tesseract",
            str(image_path),
            "stdout",
            "-l",
            "chi_tra+eng",
            "tsv",
        ]
    ]


def test_raster_label_ocr_derives_tile_records_from_map_preparation_plan(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    (project_root / "outputs" / "layers" / "plans").mkdir(parents=True)
    project = {
        "project_id": "chilai_nanhua_day1",
        "raster_label_plan_ref": "outputs/layers/plans/raster_label_plan.json",
        "imagery_tile_cache_root": str(tmp_path / "isolated-raster-cache"),
    }
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_root / project["raster_label_plan_ref"]).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_plan",
                "preferred_ocr_source_ids": ["happyman_rudy_twmap"],
                "raster_bbox_wgs84": {
                    "west": 121.2,
                    "south": 24.03,
                    "east": 121.201,
                    "north": 24.031,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = extract_raster_label_ocr(
        project_root,
        max_tiles=1,
        ocr_runner=lambda _path: [],
        collected_at="2026-06-18T00:00:00Z",
    )

    assert result["status"] == "completed"
    assert result["tile_record_count"] == 1
    assert result["tile_skipped_count"] == 1
    ocr_output = _load(project_root / result["output_ref"])
    assert ocr_output["tile_manifest_ref"] == "derived_from:raster_label_plan"
    assert ocr_output["skipped_tiles"][0]["reason"] == "tile_image_missing"
    assert ocr_output["candidate_only"] is True
    assert ocr_output["runtime_safety_truth"] is False


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
