from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from admin_local_raster_tiles import (
    DEFAULT_RASTER_TILE_CACHE_ROOT,
    build_imagery_tile_cache_plan,
    iter_raster_plan_tiles,
    raster_tile_cache_path,
    tile_bounds_wgs84,
)
from admin_imagery_sources import imagery_source_for_project
from pretrip_route_context_collection import (
    _map_label_role_from_raw,
    _mileage_anchor_from_text,
)


OCR_ENGINE_VERSION = "pretrip_raster_label_ocr.v0.1"
DEFAULT_OCR_OUTPUT_REF = "outputs/layers/raster_label_ocr_output.json"
DEFAULT_OCR_TILE_CACHE_REF = "outputs/layers/cache/raster_label_ocr_tiles"
DEFAULT_RASTER_LABEL_PLAN_REF = "outputs/layers/plans/raster_label_plan.json"
DEFAULT_TESSERACT_LANG = "chi_tra+eng"
DEFAULT_MIN_CONFIDENCE = 0.35
DEFAULT_TESSERACT_TIMEOUT_S = 10.0
DEFAULT_OCR_MAX_WORKERS = 4
DEFAULT_OCR_SOURCE_IDS = ("happyman_rudy_twmap", "happyman_rudy")
CELLULAR_KEYWORDS = ("通訊點", "通信點", "遠傳", "台哥大", "台灣大", "中華", "亞太", "台灣之星", "112")
CONTOUR_TEXT_MIN = 100
CONTOUR_TEXT_MAX = 3999

OcrRunner = Callable[[Path], Sequence[Mapping[str, Any]]]


def extract_raster_label_ocr(
    project_root: Path | str,
    *,
    tile_manifest_path: Path | str | None = None,
    raster_label_plan_path: Path | str | None = None,
    output_ref: str = DEFAULT_OCR_OUTPUT_REF,
    engine: str = "tesseract",
    tesseract_lang: str = DEFAULT_TESSERACT_LANG,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    source_ids: Sequence[str] | None = None,
    max_tiles: int | None = None,
    max_workers: int | None = None,
    dry_run: bool = False,
    ocr_runner: OcrRunner | None = None,
    collected_at: str | None = None,
    update_project: bool = True,
) -> dict[str, Any]:
    root = Path(project_root)
    collected_at = collected_at or _utc_now()
    project = _load_json(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    cache_ref = str(project.get("raster_label_ocr_cache_ref") or DEFAULT_OCR_TILE_CACHE_REF)
    cache_dir = _resolve_project_path(root, cache_ref)
    runner_kind = "injected_runner" if ocr_runner is not None else "runtime_runner"

    plan_ref = _resolve_plan_ref(project, raster_label_plan_path)
    plan_path = _resolve_project_path(root, plan_ref)
    raster_plan = _load_json(plan_path) if plan_path.exists() else {}
    allowed_source_ids = _source_ids_from_request(source_ids, raster_plan)

    tile_ref = _resolve_tile_manifest_ref(project, tile_manifest_path)
    if not tile_ref:
        tile_path = None
        tile_manifest_ref = "derived_from:raster_label_plan"
        tile_records = _tile_records_from_raster_label_plan(
            root,
            project=project,
            project_id=project_id,
            raster_plan=raster_plan,
            allowed_source_ids=allowed_source_ids,
        )
        if not tile_records:
            payload = _blocked_payload(
                status="blocked_missing_tile_manifest",
                project_id=project_id,
                output_ref=output_ref,
                collected_at=collected_at,
                engine=engine,
                raster_label_plan_ref=_project_ref_for_path(root, plan_path),
                tile_manifest_ref=None,
                missing_dependencies=[],
                warnings=[
                    "tile_manifest_path_or_project_imagery_tile_cache_plan_ref_required"
                ],
            )
            return _finish(root, payload, output_ref=output_ref, dry_run=dry_run, update_project=update_project)
    else:
        tile_path = _resolve_project_path(root, tile_ref)
        tile_manifest_ref = _project_ref_for_path(root, tile_path)
        tile_manifest = _load_json(tile_path)
        tile_records = _tile_records_from_manifest(root, tile_manifest)
    if allowed_source_ids:
        tile_records = [
            record
            for record in tile_records
            if not record.get("source_id") or str(record.get("source_id")) in allowed_source_ids
        ]
    if max_tiles is not None:
        tile_records = tile_records[: max(0, max_tiles)]

    runner = ocr_runner
    missing_dependencies: list[str] = []
    if runner is None:
        runner, missing_dependencies = _build_ocr_runner(
            engine,
            tesseract_lang=tesseract_lang,
        )
    if runner is None:
        payload = _blocked_payload(
            status="blocked_dependency_missing",
            project_id=project_id,
            output_ref=output_ref,
            collected_at=collected_at,
            engine=engine,
            raster_label_plan_ref=_project_ref_for_path(root, plan_path),
            tile_manifest_ref=tile_manifest_ref,
            missing_dependencies=missing_dependencies,
            warnings=["ocr_runtime_dependency_missing"],
        )
        return _finish(root, payload, output_ref=output_ref, dry_run=dry_run, update_project=update_project)

    labels: list[dict[str, Any]] = []
    skipped_tiles: list[dict[str, Any]] = []
    cache_hit_count = 0
    cache_miss_count = 0
    cache_write_count = 0
    worker_count = _ocr_worker_count(
        max_workers if max_workers is not None or ocr_runner is None else 1,
        tile_count=len(tile_records),
    )

    def process_tile(item: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        tile_index, tile = item
        image_path = _resolve_project_path(root, str(tile.get("image_path") or ""))
        if not image_path.is_file():
            return {
                "status": "skipped",
                "skipped_tile": {
                    "tile_index": tile_index,
                    "reason": "tile_image_missing",
                    "image_path": str(tile.get("image_path") or ""),
                    "tile_id": _tile_id(tile),
                },
            }
        image_hash = _sha256(image_path)
        cached_labels = _read_cached_tile_ocr(
            cache_dir,
            image_hash=image_hash,
            engine=engine,
            tesseract_lang=tesseract_lang,
            runner_kind=runner_kind,
        )
        if cached_labels is not None:
            return {
                "status": "cache_hit",
                "tile_index": tile_index,
                "tile": tile,
                "image_path": image_path,
                "image_hash": image_hash,
                "raw_labels": cached_labels,
            }
        try:
            raw_labels = [dict(raw_label) for raw_label in runner(image_path)]
        except Exception as exc:  # pragma: no cover - runtime OCR guard.
            return {
                "status": "cache_miss_failed",
                "skipped_tile": {
                        "tile_index": tile_index,
                        "reason": (
                            "ocr_timeout"
                            if _is_ocr_timeout_error(exc)
                            else "ocr_runner_failed"
                        ),
                        "image_path": _project_ref_for_path(root, image_path),
                        "tile_id": _tile_id(tile),
                        "error_type": type(exc).__name__,
                        "error_summary": _safe_error_summary(exc),
                },
            }
        return {
            "status": "cache_miss",
            "tile_index": tile_index,
            "tile": tile,
            "image_path": image_path,
            "image_hash": image_hash,
            "raw_labels": raw_labels,
        }

    indexed_tiles = list(enumerate(tile_records, start=1))
    if worker_count == 1:
        processed_tiles = map(process_tile, indexed_tiles)
    else:
        executor = ThreadPoolExecutor(max_workers=worker_count)
        processed_tiles = executor.map(process_tile, indexed_tiles)
    try:
        for processed in processed_tiles:
            status = str(processed["status"])
            if status == "skipped":
                skipped_tiles.append(processed["skipped_tile"])
                continue
            if status == "cache_miss_failed":
                cache_miss_count += 1
                skipped_tiles.append(processed["skipped_tile"])
                continue
            tile_index = int(processed["tile_index"])
            tile = processed["tile"]
            image_path = processed["image_path"]
            image_hash = str(processed["image_hash"])
            raw_labels = processed["raw_labels"]
            if status == "cache_hit":
                cache_hit_count += 1
            else:
                cache_miss_count += 1
                if not dry_run:
                    _write_cached_tile_ocr(
                        cache_dir,
                        image_hash=image_hash,
                        engine=engine,
                        tesseract_lang=tesseract_lang,
                        runner_kind=runner_kind,
                        raw_labels=raw_labels,
                        image_path=_project_ref_for_path(root, image_path),
                        tile=tile,
                        collected_at=collected_at,
                    )
                    cache_write_count += 1
            for label_index, raw_label in enumerate(raw_labels, start=1):
                label = _label_from_ocr_record(raw_label)
                confidence = _confidence_from_ocr_record(raw_label)
                if not label:
                    continue
                if confidence is not None and confidence < min_confidence:
                    continue
                labels.append(
                    _label_record(
                        raw_label,
                        label=label,
                        confidence=confidence,
                        project_root=root,
                        image_path=image_path,
                        image_hash=image_hash,
                        tile=tile,
                        tile_index=tile_index,
                        label_index=label_index,
                        collected_at=collected_at,
                    )
                )
    finally:
        if worker_count > 1:
            executor.shutdown(wait=True)

    payload = {
        "artifact_kind": "pretrip_raster_label_ocr_output",
        "schema_version": "route_corridor_map_preparation.v1",
        "ocr_engine_version": OCR_ENGINE_VERSION,
        "status": "completed",
        "project_id": project_id,
        "source_path": output_ref,
        "generated_at": collected_at,
        "engine": {
            "name": engine,
            "tesseract_lang": tesseract_lang if engine == "tesseract" else None,
            "tesseract_timeout_s": (
                _tesseract_timeout_s() if engine == "tesseract" else None
            ),
            "runtime_dependency_status": "available" if ocr_runner is None else "injected_runner",
            "missing_dependencies": [],
            "min_confidence": min_confidence,
            "worker_count": worker_count,
        },
        "source_plan_ref": _project_ref_for_path(root, plan_path),
        "tile_manifest_ref": tile_manifest_ref,
        "preferred_ocr_source_ids": list(allowed_source_ids),
        "labels": labels,
        "counts": {
            "tile_record_count": len(tile_records),
            "ocr_worker_count": worker_count,
            "tile_skipped_count": len(skipped_tiles),
            "ocr_cache_hit_count": cache_hit_count,
            "ocr_cache_miss_count": cache_miss_count,
            "ocr_cache_write_count": cache_write_count,
            "ocr_failure_count": sum(
                1
                for tile in skipped_tiles
                if tile.get("reason") in {"ocr_runner_failed", "ocr_timeout"}
            ),
            "ocr_timeout_count": sum(
                1 for tile in skipped_tiles if tile.get("reason") == "ocr_timeout"
            ),
            "label_count": len(labels),
            "review_required_count": len(labels),
        },
        "ocr_tile_cache_ref": cache_ref,
        "skipped_tiles": skipped_tiles,
        "raw_tile_embedded": False,
        "raw_payload_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _candidate_boundary(ocr_performed=bool(labels)),
    }
    return _finish(root, payload, output_ref=output_ref, dry_run=dry_run, update_project=update_project)


def _read_cached_tile_ocr(
    cache_dir: Path,
    *,
    image_hash: str,
    engine: str,
    tesseract_lang: str,
    runner_kind: str,
) -> list[dict[str, Any]] | None:
    path = _ocr_tile_cache_path(
        cache_dir,
        image_hash=image_hash,
        engine=engine,
        tesseract_lang=tesseract_lang,
        runner_kind=runner_kind,
    )
    if not path.exists():
        return None
    try:
        payload = _load_json(path)
    except (json.JSONDecodeError, OSError):
        return None
    if payload.get("artifact_kind") != "pretrip_raster_label_ocr_tile_cache":
        return None
    if payload.get("ocr_engine_version") != OCR_ENGINE_VERSION:
        return None
    if payload.get("source_image_sha256") != image_hash:
        return None
    if payload.get("engine") != engine:
        return None
    if payload.get("tesseract_lang") != tesseract_lang:
        return None
    if payload.get("runner_kind") != runner_kind:
        return None
    raw_labels = payload.get("raw_labels")
    if not isinstance(raw_labels, list):
        return None
    return [dict(item) for item in raw_labels if isinstance(item, Mapping)]


def _write_cached_tile_ocr(
    cache_dir: Path,
    *,
    image_hash: str,
    engine: str,
    tesseract_lang: str,
    runner_kind: str,
    raw_labels: Sequence[Mapping[str, Any]],
    image_path: str,
    tile: Mapping[str, Any],
    collected_at: str,
) -> None:
    path = _ocr_tile_cache_path(
        cache_dir,
        image_hash=image_hash,
        engine=engine,
        tesseract_lang=tesseract_lang,
        runner_kind=runner_kind,
    )
    payload = {
        "artifact_kind": "pretrip_raster_label_ocr_tile_cache",
        "schema_version": "route_corridor_map_preparation.v1",
        "ocr_engine_version": OCR_ENGINE_VERSION,
        "generated_at": collected_at,
        "engine": engine,
        "tesseract_lang": tesseract_lang,
        "runner_kind": runner_kind,
        "source_image_sha256": image_hash,
        "source_image_ref": image_path,
        "source_id": tile.get("source_id"),
        "tile_z": _int_or_none(tile.get("tile_z") or tile.get("z")),
        "tile_x": _int_or_none(tile.get("tile_x") or tile.get("x")),
        "tile_y": _int_or_none(tile.get("tile_y") or tile.get("y")),
        "raw_labels": [dict(item) for item in raw_labels],
        "raw_label_count": len(raw_labels),
        "raw_tile_embedded": False,
        "raw_payload_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    _write_json(path, payload)


def _ocr_tile_cache_path(
    cache_dir: Path,
    *,
    image_hash: str,
    engine: str,
    tesseract_lang: str,
    runner_kind: str,
) -> Path:
    key_payload = {
        "engine": engine,
        "image_hash": image_hash,
        "ocr_engine_version": OCR_ENGINE_VERSION,
        "runner_kind": runner_kind,
        "tesseract_lang": tesseract_lang,
    }
    key = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return cache_dir / key[:2] / f"{key}.json"


def _finish(
    root: Path,
    payload: dict[str, Any],
    *,
    output_ref: str,
    dry_run: bool,
    update_project: bool,
) -> dict[str, Any]:
    if not dry_run:
        _write_json(root / output_ref, payload)
    if update_project and not dry_run:
        project_path = root / "project.json"
        project = _load_json(project_path)
        project["raster_label_ocr_output_ref"] = output_ref
        project["raster_label_ocr_cache_ref"] = payload.get("ocr_tile_cache_ref") or DEFAULT_OCR_TILE_CACHE_REF
        project["raster_label_ocr_status"] = payload["status"]
        project["raster_label_ocr_label_count"] = int(payload.get("counts", {}).get("label_count") or 0)
        project["raster_label_ocr_cache_hit_count"] = int(payload.get("counts", {}).get("ocr_cache_hit_count") or 0)
        project["raster_label_ocr_cache_miss_count"] = int(payload.get("counts", {}).get("ocr_cache_miss_count") or 0)
        _write_json(project_path, project)
    return {
        "status": payload["status"],
        "project_id": payload.get("project_id"),
        "output_ref": output_ref,
        "label_count": int(payload.get("counts", {}).get("label_count") or 0),
        "tile_record_count": int(payload.get("counts", {}).get("tile_record_count") or 0),
        "tile_skipped_count": int(payload.get("counts", {}).get("tile_skipped_count") or 0),
        "ocr_cache_hit_count": int(payload.get("counts", {}).get("ocr_cache_hit_count") or 0),
        "ocr_cache_miss_count": int(payload.get("counts", {}).get("ocr_cache_miss_count") or 0),
        "ocr_cache_write_count": int(payload.get("counts", {}).get("ocr_cache_write_count") or 0),
        "ocr_failure_count": int(payload.get("counts", {}).get("ocr_failure_count") or 0),
        "ocr_timeout_count": int(payload.get("counts", {}).get("ocr_timeout_count") or 0),
        "writes_performed": not dry_run,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "missing_dependencies": payload.get("engine", {}).get("missing_dependencies", []),
    }


def _blocked_payload(
    *,
    status: str,
    project_id: str,
    output_ref: str,
    collected_at: str,
    engine: str,
    raster_label_plan_ref: str | None,
    tile_manifest_ref: str | None,
    missing_dependencies: Sequence[str],
    warnings: Sequence[str],
) -> dict[str, Any]:
    return {
        "artifact_kind": "pretrip_raster_label_ocr_output",
        "schema_version": "route_corridor_map_preparation.v1",
        "ocr_engine_version": OCR_ENGINE_VERSION,
        "status": status,
        "project_id": project_id,
        "source_path": output_ref,
        "generated_at": collected_at,
        "engine": {
            "name": engine,
            "runtime_dependency_status": "missing",
            "missing_dependencies": list(missing_dependencies),
        },
        "source_plan_ref": raster_label_plan_ref,
        "tile_manifest_ref": tile_manifest_ref,
        "labels": [],
        "counts": {
            "tile_record_count": 0,
            "tile_skipped_count": 0,
            "label_count": 0,
            "review_required_count": 0,
        },
        "warnings": list(warnings),
        "raw_tile_embedded": False,
        "raw_payload_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _candidate_boundary(ocr_performed=False),
    }


def _build_ocr_runner(
    engine: str,
    *,
    tesseract_lang: str,
) -> tuple[OcrRunner | None, list[str]]:
    if engine != "tesseract":
        return None, [f"unsupported_ocr_engine:{engine}"]
    tesseract_bin = shutil.which("tesseract")
    if tesseract_bin is None:
        return None, ["tesseract"]

    runner, missing = _build_pytesseract_runner(
        tesseract_lang=tesseract_lang,
    )
    if runner is not None:
        return runner, []
    return _build_tesseract_cli_runner(
        tesseract_bin=Path(tesseract_bin),
        tesseract_lang=tesseract_lang,
    ), []


def _build_pytesseract_runner(
    *,
    tesseract_lang: str,
) -> tuple[OcrRunner | None, list[str]]:
    missing: list[str] = []
    try:
        from PIL import Image
    except Exception:  # pragma: no cover - environment dependent
        Image = None  # type: ignore[assignment]
        missing.append("Pillow")
    try:
        import pytesseract
    except Exception:  # pragma: no cover - environment dependent
        pytesseract = None  # type: ignore[assignment]
        missing.append("pytesseract")
    if missing:
        return None, missing

    def _run(image_path: Path) -> list[dict[str, Any]]:
        with Image.open(image_path) as image:  # type: ignore[union-attr]
            data = pytesseract.image_to_data(  # type: ignore[union-attr]
                image,
                lang=tesseract_lang,
                output_type=pytesseract.Output.DICT,  # type: ignore[union-attr]
                timeout=_tesseract_timeout_s(),
            )
        records = []
        for index, text in enumerate(data.get("text", [])):
            records.append(
                {
                    "label_text": text,
                    "confidence": data.get("conf", [None])[index],
                    "bbox_px": [
                        data.get("left", [0])[index],
                        data.get("top", [0])[index],
                        data.get("left", [0])[index] + data.get("width", [0])[index],
                        data.get("top", [0])[index] + data.get("height", [0])[index],
                    ],
                    "ocr_engine": "tesseract",
                }
            )
        return records

    return _run, []


def _build_tesseract_cli_runner(
    *,
    tesseract_bin: Path,
    tesseract_lang: str,
) -> OcrRunner:
    def _run(image_path: Path) -> list[dict[str, Any]]:
        result = subprocess.run(
            [
                str(tesseract_bin),
                str(image_path),
                "stdout",
                "-l",
                tesseract_lang,
                "tsv",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=_tesseract_timeout_s(),
        )
        if result.returncode != 0:
            error = (result.stderr or "tesseract CLI failed").replace("\n", " ")[:200]
            raise RuntimeError(error)
        return _tesseract_tsv_records(result.stdout)

    return _run


def _tesseract_tsv_records(payload: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(payload), delimiter="\t"):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        left = _int_or_zero(row.get("left"))
        top = _int_or_zero(row.get("top"))
        width = _int_or_zero(row.get("width"))
        height = _int_or_zero(row.get("height"))
        records.append(
            {
                "label_text": text,
                "confidence": row.get("conf"),
                "bbox_px": [left, top, left + width, top + height],
                "ocr_engine": "tesseract_cli",
            }
        )
    return records


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _ocr_worker_count(requested: int | None, *, tile_count: int) -> int:
    if tile_count <= 1:
        return 1
    value: int | None = requested
    if value is None:
        raw = os.environ.get("SCOUT_RASTER_LABEL_OCR_WORKERS")
        if raw and raw.strip():
            try:
                value = int(raw)
            except ValueError:
                value = None
    if value is None:
        value = min(DEFAULT_OCR_MAX_WORKERS, os.cpu_count() or 1)
    if value <= 0:
        raise ValueError("max_workers must be positive")
    return min(value, tile_count)


def _tesseract_timeout_s() -> float:
    raw = os.environ.get("SCOUT_TESSERACT_TIMEOUT_S")
    if raw is None or not raw.strip():
        return DEFAULT_TESSERACT_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_TESSERACT_TIMEOUT_S


def _is_ocr_timeout_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in text or "timed out" in text


def _safe_error_summary(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:200]


def _tile_records_from_manifest(root: Path, manifest: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(manifest, list):
        return [_normalize_explicit_tile_record(root, item) for item in manifest if isinstance(item, dict)]
    if not isinstance(manifest, dict):
        return []
    if manifest.get("artifact_kind") == "admin_imagery_tile_cache_plan":
        return _tile_records_from_cache_plan(manifest)
    for key in ("tiles", "tile_records", "images", "sources"):
        value = manifest.get(key)
        if isinstance(value, list):
            return [_normalize_explicit_tile_record(root, item) for item in value if isinstance(item, dict)]
    return []


def _tile_records_from_cache_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    project_id = str(plan.get("project_id") or "")
    layer_id = str(plan.get("layer_id") or "imagery")
    cache_root = Path(str(plan.get("cache_root") or "")).expanduser()
    records = []
    for tile in iter_raster_plan_tiles(plan):
        z = int(tile["z"])
        x = int(tile["x"])
        y = int(tile["y"])
        image_path = raster_tile_cache_path(
            project_id,
            layer_id,
            z,
            x,
            y,
            cache_root=cache_root,
        )
        records.append(
            {
                "image_path": image_path.as_posix(),
                "source_ref": image_path.as_posix(),
                "source_id": plan.get("source_id"),
                "source_kind": plan.get("source_kind") or "raster_tile_cache",
                "tile_z": z,
                "tile_x": x,
                "tile_y": y,
                "tile_bbox_wgs84": tile_bounds_wgs84(z, x, y),
                "tile_size_px": int(plan.get("tile_size") or 256),
                "cache_plan_id": plan.get("plan_id"),
            }
        )
    return records


def _normalize_explicit_tile_record(root: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    image_path = item.get("image_path") or item.get("path") or item.get("cache_path")
    record = dict(item)
    if image_path:
        record["image_path"] = _project_ref_for_path(root, _resolve_project_path(root, str(image_path)))
        record.setdefault("source_ref", record["image_path"])
    if "tile_bbox_wgs84" not in record and all(key in record for key in ("tile_z", "tile_x", "tile_y")):
        record["tile_bbox_wgs84"] = tile_bounds_wgs84(
            int(record["tile_z"]),
            int(record["tile_x"]),
            int(record["tile_y"]),
        )
    return record


def _tile_records_from_raster_label_plan(
    root: Path,
    *,
    project: Mapping[str, Any],
    project_id: str,
    raster_plan: Mapping[str, Any],
    allowed_source_ids: set[str],
) -> list[dict[str, Any]]:
    bbox = _bbox_from_raster_label_plan(project, raster_plan)
    if not bbox:
        return []
    source_ids = allowed_source_ids or {
        str(source_id)
        for source_id in raster_plan.get("preferred_ocr_source_ids", [])
        if str(source_id).strip()
    }
    if not source_ids:
        source_ids = set(DEFAULT_OCR_SOURCE_IDS)
    records: list[dict[str, Any]] = []
    for source_id in sorted(source_ids):
        try:
            imagery_source = imagery_source_for_project({"imagery_source_id": source_id})
            plan = build_imagery_tile_cache_plan(
                bbox,
                project_id=project_id,
                layer_id="imagery",
                imagery_source=imagery_source,
                cache_root=_raster_tile_cache_root(project),
            )
        except Exception:
            continue
        for record in _tile_records_from_cache_plan(plan):
            record["source_id"] = source_id
            record["source_kind"] = imagery_source.get("source_kind") or record.get("source_kind")
            record["source_ref"] = str(record.get("image_path") or "")
            record["derived_from_raster_label_plan"] = True
            records.append(record)
    return records


def _bbox_from_raster_label_plan(
    project: Mapping[str, Any],
    raster_plan: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for key in ("raster_bbox_wgs84", "bbox_wgs84"):
        value = raster_plan.get(key)
        if isinstance(value, Mapping):
            return value
    route_corridor = raster_plan.get("route_corridor")
    if isinstance(route_corridor, Mapping):
        for key in (
            "bbox_wgs84",
            "bbox",
            "bbox_boundary",
            "query_bbox_wgs84",
            "route_bbox_wgs84",
        ):
            value = route_corridor.get(key)
            if isinstance(value, Mapping):
                return value
    value = project.get("imagery_bbox_wgs84")
    if isinstance(value, Mapping):
        return value
    return None


def _raster_tile_cache_root(project: Mapping[str, Any]) -> Path:
    return Path(
        str(
            project.get("imagery_tile_cache_root")
            or os.environ.get("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT")
            or DEFAULT_RASTER_TILE_CACHE_ROOT
        )
    ).expanduser()


def _label_record(
    raw_label: Mapping[str, Any],
    *,
    label: str,
    confidence: float | None,
    project_root: Path,
    image_path: Path,
    image_hash: str,
    tile: Mapping[str, Any],
    tile_index: int,
    label_index: int,
    collected_at: str,
) -> dict[str, Any]:
    bbox_px = _bbox_px(raw_label)
    role = _classify_label_role(label, raw_label)
    record = {
        "id": str(raw_label.get("id") or f"ocr_label.{tile_index:04d}.{label_index:04d}"),
        "label_text": label,
        "label_role": role,
        "confidence": confidence,
        "bbox_px": bbox_px,
        "tile_z": _int_or_none(tile.get("tile_z") or tile.get("z")),
        "tile_x": _int_or_none(tile.get("tile_x") or tile.get("x")),
        "tile_y": _int_or_none(tile.get("tile_y") or tile.get("y")),
        "tile_bbox_wgs84": tile.get("tile_bbox_wgs84"),
        "tile_size_px": _int_or_none(tile.get("tile_size_px") or tile.get("tile_size")) or 256,
        "source_ref": str(tile.get("source_ref") or _project_ref_for_path(project_root, image_path)),
        "source_kind": str(tile.get("source_kind") or "raster_tile_ocr"),
        "source_id": tile.get("source_id"),
        "source_image_hash": str(tile.get("source_image_hash") or f"sha256:{image_hash}"),
        "ocr_engine": raw_label.get("ocr_engine") or "tesseract",
        "collected_at": collected_at,
        "review_required": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "raw_tile_embedded": False,
        "raw_payload_embedded": False,
    }
    if raw_label.get("lat") is not None and raw_label.get("lon") is not None:
        record["lat"] = raw_label.get("lat")
        record["lon"] = raw_label.get("lon")
    return {key: value for key, value in record.items() if value is not None}


def _classify_label_role(label: str, raw_label: Mapping[str, Any]) -> str:
    explicit = _map_label_role_from_raw(dict(raw_label), label)
    if explicit:
        return explicit
    mileage = _mileage_anchor_from_text(label)
    if mileage:
        return str(mileage["label_role"])
    normalized = _normalize_label(label)
    if any(keyword in normalized for keyword in CELLULAR_KEYWORDS):
        return "cellular_communication_point"
    if normalized.isdigit():
        value = int(normalized)
        if CONTOUR_TEXT_MIN <= value <= CONTOUR_TEXT_MAX:
            return "contour_elevation_label"
    if any(keyword in normalized for keyword in ("崩", "斷崖", "落石", "危險", "警告")):
        return "hazard_annotation_label"
    if any(keyword in normalized for keyword in ("步道", "越嶺", "山徑", "線")):
        return "trail_name_label"
    return "named_place_label"


def _source_ids_from_request(source_ids: Sequence[str] | None, raster_plan: Any) -> set[str]:
    if source_ids:
        return {str(source_id) for source_id in source_ids if str(source_id).strip()}
    if isinstance(raster_plan, dict):
        return {
            str(source_id)
            for source_id in raster_plan.get("preferred_ocr_source_ids", [])
            if str(source_id).strip()
        }
    return set()


def _resolve_plan_ref(project: Mapping[str, Any], override: Path | str | None) -> str:
    return str(override or project.get("raster_label_plan_ref") or DEFAULT_RASTER_LABEL_PLAN_REF)


def _resolve_tile_manifest_ref(project: Mapping[str, Any], override: Path | str | None) -> str:
    return str(
        override
        or project.get("raster_label_tile_cache_plan_ref")
        or project.get("imagery_tile_cache_plan_ref")
        or project.get("raster_tile_manifest_ref")
        or ""
    )


def _label_from_ocr_record(record: Mapping[str, Any]) -> str:
    for key in ("label_text", "text", "label", "name"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _confidence_from_ocr_record(record: Mapping[str, Any]) -> float | None:
    number = _float_or_none(record.get("confidence") or record.get("conf") or record.get("score"))
    if number is None:
        return None
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _bbox_px(record: Mapping[str, Any]) -> list[float] | None:
    value = record.get("bbox_px") or record.get("bbox")
    if isinstance(value, Mapping):
        value = [value.get("x0"), value.get("y0"), value.get("x1"), value.get("y1")]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) >= 4:
        numbers = [_float_or_none(item) for item in value[:4]]
        if all(number is not None for number in numbers):
            return [round(float(number), 3) for number in numbers if number is not None]
    left = _float_or_none(record.get("left"))
    top = _float_or_none(record.get("top"))
    width = _float_or_none(record.get("width"))
    height = _float_or_none(record.get("height"))
    if None not in (left, top, width, height):
        return [left, top, left + width, top + height]  # type: ignore[operator]
    return None


def _tile_id(tile: Mapping[str, Any]) -> str | None:
    z = _int_or_none(tile.get("tile_z") or tile.get("z"))
    x = _int_or_none(tile.get("tile_x") or tile.get("x"))
    y = _int_or_none(tile.get("tile_y") or tile.get("y"))
    if z is None or x is None or y is None:
        return None
    return f"z{z}.x{x}.y{y}"


def _candidate_boundary(*, ocr_performed: bool) -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "raw_payloads_embedded": False,
        "raw_tiles_embedded": False,
        "workspace_file_mutation_allowed": True,
        "ocr_or_vision_performed": ocr_performed,
        "live_safety_api_calls_allowed": False,
    }


def _normalize_label(value: str) -> str:
    return str(value or "").translate(str.maketrans("０１２３４５６７８９．Ｋｋ", "0123456789.Kk")).strip()


def _resolve_project_path(root: Path, path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    project_relative = root / candidate
    if project_relative.exists() or not candidate.exists():
        return project_relative
    return candidate


def _project_ref_for_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> dict[str, Any] | list[Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    if number is None:
        return None
    return int(number)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run optional OCR over cached Rudy/Rudy+TW raster tiles and emit explicit OCR JSON."
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--tile-manifest", default=None)
    parser.add_argument("--raster-label-plan", default=None)
    parser.add_argument("--output-ref", default=DEFAULT_OCR_OUTPUT_REF)
    parser.add_argument("--engine", default="tesseract")
    parser.add_argument("--tesseract-lang", default=DEFAULT_TESSERACT_LANG)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--max-tiles", type=int, default=None)
    parser.add_argument("--no-project-update", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = extract_raster_label_ocr(
        args.project_root,
        tile_manifest_path=args.tile_manifest,
        raster_label_plan_path=args.raster_label_plan,
        output_ref=args.output_ref,
        engine=args.engine,
        tesseract_lang=args.tesseract_lang,
        min_confidence=args.min_confidence,
        source_ids=args.source_id,
        max_tiles=args.max_tiles,
        dry_run=args.dry_run,
        update_project=not args.no_project_update,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result["output_ref"])


if __name__ == "__main__":
    main()
