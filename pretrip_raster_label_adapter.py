from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pretrip_route_context_collection import (
    _map_label_evidence_type,
    _map_label_role_from_raw,
    _mileage_anchor_from_text,
)


ADAPTER_VERSION = "pretrip_raster_label_adapter.v0.1"
DEFAULT_RASTER_LABEL_EVIDENCE_REF = "outputs/layers/normalized/raster_label_evidence.geojson"
DEFAULT_ADAPTER_MANIFEST_REF = "outputs/layers/raster_label_adapter_manifest.json"
DEFAULT_TILE_SIZE_PX = 256
CONTOUR_ONLY_PATTERN = re.compile(r"^(?:[1-3]\d{2,3})$")
FULLWIDTH_DIGIT_TRANSLATION = str.maketrans("０１２３４５６７８９．", "0123456789.")
KNOWN_LABEL_ROLES = {
    "trail_mileage_k_anchor",
    "road_mileage_stone",
    "trail_name_label",
    "named_place_label",
    "cellular_communication_point",
    "trail_annotation_label",
    "contour_elevation_label",
    "hazard_annotation_label",
}


def build_raster_label_evidence(
    project_root: Path | str,
    *,
    source_path: Path | str,
    output_ref: str = DEFAULT_RASTER_LABEL_EVIDENCE_REF,
    manifest_ref: str = DEFAULT_ADAPTER_MANIFEST_REF,
    collected_at: str | None = None,
    update_project: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(project_root)
    collected_at = collected_at or _utc_now()
    source = _resolve_project_path(root, source_path)
    raw_payload = _load_json(source)
    records = _label_records(raw_payload)
    source_sha256 = _sha256(source)
    features: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            skipped.append({"index": index, "reason": "non_object_record"})
            continue
        feature = _feature_from_record(
            record,
            index=index,
            source_path=_project_ref_for_path(root, source),
            source_sha256=source_sha256,
            collected_at=collected_at,
        )
        if not feature:
            skipped.append({"index": index, "reason": "empty_label"})
            continue
        features.append(feature)

    project = _load_json(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    evidence = {
        "type": "FeatureCollection",
        "artifact_kind": "pretrip_raster_label_evidence",
        "schema_version": "route_corridor_map_preparation.v1",
        "adapter_version": ADAPTER_VERSION,
        "project_id": project_id,
        "source_path": output_ref,
        "source_id": f"{project_id}.raster_label_adapter",
        "status": "normalized_from_explicit_ocr_adapter",
        "evidence_type": "pretrip_raster_label_candidate",
        "generated_at": collected_at,
        "features": features,
        "counts": {
            "feature_count": len(features),
            "input_record_count": len(records),
            "skipped_record_count": len(skipped),
            "review_required_count": sum(
                1
                for feature in features
                if feature["properties"].get("review_required") is True
            ),
        },
        "source_refs": [
            {
                "source_kind": _source_kind(raw_payload),
                "source_path": _project_ref_for_path(root, source),
                "sha256": source_sha256,
                "raw_payload_embedded": False,
                "raw_tile_embedded": False,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "adapter_manifest_ref": manifest_ref,
        "network_policy": {
            "network_calls_allowed": False,
            "network_calls_made": False,
            "live_ocr_or_vision_performed": False,
            "explicit_adapter_input_required": True,
        },
        "boundary": _candidate_boundary(),
    }
    manifest = {
        "artifact_kind": "pretrip_raster_label_adapter_manifest",
        "schema_version": "route_corridor_map_preparation.v1",
        "adapter_version": ADAPTER_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_ref": _project_ref_for_path(root, source),
        "source_sha256": source_sha256,
        "output_ref": output_ref,
        "feature_count": len(features),
        "skipped_records": skipped,
        "label_roles": sorted(
            {
                str(feature["properties"].get("label_role") or "map_label")
                for feature in features
            }
        ),
        "ocr_or_vision_performed_by_this_adapter": False,
        "requires_external_ocr_engine": True,
        "raw_payload_embedded": False,
        "raw_tile_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "boundary": _candidate_boundary(),
    }

    if not dry_run:
        _write_json(root / output_ref, evidence)
        _write_json(root / manifest_ref, manifest)
    if update_project and not dry_run:
        project = _load_json(root / "project.json")
        project["raster_label_evidence_ref"] = output_ref
        project["raster_label_adapter_manifest_ref"] = manifest_ref
        project["raster_label_evidence_count"] = len(features)
        _write_json(root / "project.json", project)

    return {
        "status": "completed",
        "project_id": project_id,
        "source_ref": _project_ref_for_path(root, source),
        "output_ref": output_ref,
        "manifest_ref": manifest_ref,
        "feature_count": len(features),
        "skipped_record_count": len(skipped),
        "writes_performed": not dry_run,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _feature_from_record(
    record: dict[str, Any],
    *,
    index: int,
    source_path: str,
    source_sha256: str,
    collected_at: str,
) -> dict[str, Any] | None:
    props = record.get("properties") if isinstance(record.get("properties"), dict) else record
    label = _first_text(
        props.get("label"),
        props.get("label_text"),
        props.get("text"),
        props.get("name"),
        props.get("id"),
    )
    if not label:
        return None

    geometry, coordinate_source = _geometry_from_record(record, props)
    label_role = _infer_label_role(props, label)
    mileage = _mileage_anchor_from_text(label, label_role=label_role)
    if mileage:
        label_role = mileage["label_role"]
    evidence_type = _map_label_evidence_type(
        label_role,
        mileage,
        "raster_map_label",
    )
    review_reasons = _review_reasons(
        label=label,
        label_role=label_role,
        geometry=geometry,
        coordinate_source=coordinate_source,
        props=props,
    )
    candidate_id = _first_text(
        props.get("candidate_id"),
        props.get("ocr_label_id"),
        props.get("id"),
        f"raster_label.{index:04d}",
    )
    feature_props = {
        "candidate_id": candidate_id,
        "label": label,
        "label_text": label,
        "label_role": label_role,
        "evidence_type": evidence_type,
        "confidence": _float_or_none(props.get("confidence")),
        "review_required": True,
        "review_state": "needs_human_review",
        "review_reasons": review_reasons,
        "coordinate_source": coordinate_source,
        "source_ref": _first_text(props.get("source_ref"), source_path),
        "source_kind": _first_text(props.get("source_kind"), "raster_label_ocr_adapter"),
        "source_image_hash": _first_text(props.get("source_image_hash")),
        "source_payload_ref": source_path,
        "source_payload_sha256": source_sha256,
        "tile_id": _tile_id(props),
        "tile_z": _int_or_none(props.get("tile_z") or props.get("z")),
        "tile_x": _int_or_none(props.get("tile_x") or props.get("x")),
        "tile_y": _int_or_none(props.get("tile_y") or props.get("y")),
        "bbox_px": _bbox_px(props),
        "adapter_version": ADAPTER_VERSION,
        "collected_at": collected_at,
        "raw_payload_embedded": False,
        "raw_tile_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if mileage:
        feature_props.update(
            {
                "mileage_anchor_kind": mileage["mileage_anchor_kind"],
                "normalized_mileage_k": mileage["normalized_mileage_k"],
                "mileage_k": mileage["mileage_k"],
                "mileage_m": mileage["mileage_m"],
                "raw_mileage_text": mileage["raw_mileage_text"],
            }
        )
    contour_elevation_m = _contour_elevation_m(label_role, label)
    if contour_elevation_m is not None:
        feature_props["contour_elevation_m"] = contour_elevation_m
    networks = _communication_networks(label_role, label)
    if networks:
        feature_props["communication_networks"] = networks
        feature_props["communication_emergency_hint"] = "112" in networks

    return {
        "type": "Feature",
        "id": candidate_id,
        "geometry": geometry,
        "properties": feature_props,
    }


def _geometry_from_record(
    record: dict[str, Any],
    props: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    geometry = record.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            lon = _float_or_none(coordinates[0])
            lat = _float_or_none(coordinates[1])
            if lat is not None and lon is not None:
                return _point(lon, lat), "input_geojson_point"

    lat = _float_or_none(props.get("lat") or props.get("latitude"))
    lon = _float_or_none(props.get("lon") or props.get("lng") or props.get("longitude"))
    if lat is not None and lon is not None:
        return _point(lon, lat), "input_lat_lon"

    tile_bbox = props.get("tile_bbox_wgs84")
    bbox_px = _bbox_px(props)
    if isinstance(tile_bbox, dict) and bbox_px:
        point = _point_from_tile_bbox(tile_bbox, bbox_px)
        if point:
            return point, "tile_bbox_wgs84_pixel_bbox"

    z = _int_or_none(props.get("tile_z") or props.get("z"))
    x = _int_or_none(props.get("tile_x") or props.get("x"))
    y = _int_or_none(props.get("tile_y") or props.get("y"))
    if z is not None and x is not None and y is not None and bbox_px:
        tile_size = _int_or_none(props.get("tile_size_px") or props.get("tile_size")) or DEFAULT_TILE_SIZE_PX
        point = _point_from_xyz_bbox(z=z, x=x, y=y, bbox_px=bbox_px, tile_size=tile_size)
        if point:
            return point, "web_mercator_tile_pixel_bbox"

    return None, "missing_georeference"


def _point_from_tile_bbox(
    tile_bbox: dict[str, Any],
    bbox_px: tuple[float, float, float, float],
) -> dict[str, Any] | None:
    west = _float_or_none(tile_bbox.get("west") or tile_bbox.get("min_lon"))
    east = _float_or_none(tile_bbox.get("east") or tile_bbox.get("max_lon"))
    south = _float_or_none(tile_bbox.get("south") or tile_bbox.get("min_lat"))
    north = _float_or_none(tile_bbox.get("north") or tile_bbox.get("max_lat"))
    width = _float_or_none(tile_bbox.get("tile_width_px") or tile_bbox.get("width_px")) or DEFAULT_TILE_SIZE_PX
    height = _float_or_none(tile_bbox.get("tile_height_px") or tile_bbox.get("height_px")) or DEFAULT_TILE_SIZE_PX
    if None in (west, east, south, north):
        return None
    center_x = (bbox_px[0] + bbox_px[2]) / 2.0
    center_y = (bbox_px[1] + bbox_px[3]) / 2.0
    lon = west + (east - west) * (center_x / width)
    lat = north - (north - south) * (center_y / height)
    return _point(lon, lat)


def _point_from_xyz_bbox(
    *,
    z: int,
    x: int,
    y: int,
    bbox_px: tuple[float, float, float, float],
    tile_size: int,
) -> dict[str, Any] | None:
    if z < 0 or tile_size <= 0:
        return None
    center_x = (bbox_px[0] + bbox_px[2]) / 2.0
    center_y = (bbox_px[1] + bbox_px[3]) / 2.0
    scale = 2**z * tile_size
    global_x = x * tile_size + center_x
    global_y = y * tile_size + center_y
    lon = global_x / scale * 360.0 - 180.0
    mercator_y = math.pi * (1.0 - 2.0 * global_y / scale)
    lat = math.degrees(math.atan(math.sinh(mercator_y)))
    return _point(lon, lat)


def _label_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return payload["features"]
    for key in ("labels", "ocr_labels", "features", "points", "candidates"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _source_kind(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("artifact_kind") or payload.get("source_kind") or "raster_label_adapter_input")
    return "raster_label_adapter_input"


def _infer_label_role(props: dict[str, Any], label: str) -> str:
    role = _map_label_role_from_raw(props, label)
    if role:
        return role
    normalized = str(label or "").translate(FULLWIDTH_DIGIT_TRANSLATION).strip()
    if CONTOUR_ONLY_PATTERN.match(normalized):
        return "contour_elevation_label"
    explicit = str(props.get("label_role") or props.get("role") or "").strip()
    if explicit in KNOWN_LABEL_ROLES:
        return explicit
    return ""


def _review_reasons(
    *,
    label: str,
    label_role: str,
    geometry: dict[str, Any] | None,
    coordinate_source: str,
    props: dict[str, Any],
) -> list[str]:
    reasons = ["explicit_ocr_adapter_output_requires_review"]
    if not label.strip():
        reasons.append("empty_label")
    if geometry is None or coordinate_source == "missing_georeference":
        reasons.append("missing_georeference")
    if label_role == "contour_elevation_label" and _contour_elevation_m(label_role, label) is None:
        reasons.append("unparsed_contour_elevation")
    if not props.get("source_image_hash"):
        reasons.append("missing_source_image_hash")
    return reasons


def _bbox_px(props: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = props.get("bbox_px") or props.get("bbox")
    if isinstance(value, dict):
        value = [value.get("x0"), value.get("y0"), value.get("x1"), value.get("y1")]
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    numbers = tuple(_float_or_none(item) for item in value[:4])
    if any(number is None for number in numbers):
        return None
    return numbers  # type: ignore[return-value]


def _tile_id(props: dict[str, Any]) -> str | None:
    explicit = _first_text(props.get("tile_id"))
    if explicit:
        return explicit
    z = _int_or_none(props.get("tile_z") or props.get("z"))
    x = _int_or_none(props.get("tile_x") or props.get("x"))
    y = _int_or_none(props.get("tile_y") or props.get("y"))
    if z is None or x is None or y is None:
        return None
    return f"z{z}.x{x}.y{y}"


def _contour_elevation_m(label_role: str, label: str) -> float | None:
    if label_role != "contour_elevation_label":
        return None
    normalized = str(label or "").translate(FULLWIDTH_DIGIT_TRANSLATION).strip()
    match = CONTOUR_ONLY_PATTERN.match(normalized)
    return _float_or_none(match.group(0)) if match else None


def _communication_networks(label_role: str, label: str) -> list[str]:
    if label_role != "cellular_communication_point":
        return []
    networks = []
    for keyword in ("中華", "遠傳", "台哥大", "台灣大", "亞太", "台灣之星", "112"):
        if keyword in label:
            networks.append(keyword)
    return networks


def _point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [round(lon, 8), round(lat, 8)]}


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "raw_payloads_embedded": False,
        "raw_tiles_embedded": False,
        "workspace_file_mutation_allowed": True,
    }


def _resolve_project_path(root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    project_relative = root / candidate
    if project_relative.exists():
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
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    if number is None:
        return None
    return int(number)


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize explicit OCR/map-label output into Scout raster label evidence."
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-ref", default=DEFAULT_RASTER_LABEL_EVIDENCE_REF)
    parser.add_argument("--manifest-ref", default=DEFAULT_ADAPTER_MANIFEST_REF)
    parser.add_argument("--collected-at")
    parser.add_argument("--no-project-update", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = build_raster_label_evidence(
        args.project_root,
        source_path=args.source,
        output_ref=args.output_ref,
        manifest_ref=args.manifest_ref,
        collected_at=args.collected_at,
        update_project=not args.no_project_update,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(result["output_ref"])


if __name__ == "__main__":
    main()
