from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from datetime import datetime
from math import cos, radians
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from cwa_imagery_registry import (
    ANIMATION_WINDOWS_HOURS,
    ImageryProductSpec,
    public_registry_contract,
)
from cwa_radar_ingestor import CwaRadarIngestor
from cwa_satellite_ingestor import CwaSatelliteIngestor
from radar_motion_estimator import estimate_motion_toward_route
from route_imagery_sampler import (
    RasterGrid,
    RouteBuffer,
    build_route_buffer,
    decode_cached_frame_grid,
    sample_radar_grid,
    sample_satellite_grid,
)
from weather_imagery_tile_cache import CachedImageryFrame, WeatherImageryTileCache


def build_route_weather_risk_package(
    *,
    route_id: str,
    route_buffer: RouteBuffer,
    radar_samples: list[dict[str, Any]],
    satellite_samples: list[dict[str, Any]],
    radar_motion: dict[str, Any],
    cloud_motion: dict[str, Any],
    terrain_segments: Iterable[dict[str, Any]],
    evaluated_at: str,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    radar = radar_samples[-1] if radar_samples else {}
    satellite = satellite_samples[-1] if satellite_samples else {}
    radar_delay = _data_delay_minutes(evaluated_at, [radar.get("sourceTimestamp")])
    satellite_delay = _data_delay_minutes(
        evaluated_at, [satellite.get("sourceTimestamp")]
    )
    available_delays = [
        item for item in (radar_delay, satellite_delay) if item is not None
    ]
    data_delay = max(available_delays) if available_delays else None
    base_confidence = _mean(
        [
            radar.get("coverageConfidence"),
            satellite.get("coverageConfidence"),
            radar_motion.get("confidence"),
            cloud_motion.get("confidence"),
        ]
    )
    freshness_confidence = min(
        _freshness_ratio(radar_delay, radar.get("expectedDelayMinutes")),
        _freshness_ratio(
            satellite_delay,
            satellite.get("expectedDelayMinutes"),
        ),
    )
    confidence = base_confidence * freshness_confidence
    features = {
        "currentRainOnRoute": radar.get("currentRainOnRoute"),
        "nearbyStrongEcho": radar.get("nearbyStrongEcho"),
        "rainBandApproaching": radar_motion.get("movingTowardRoute"),
        "estimatedRainArrivalMinutes": radar_motion.get("estimatedArrivalMinutes"),
        "convectiveCellScore": radar.get("convectiveCellScore"),
        "satelliteConvectiveCloudScore": satellite.get("satelliteConvectiveCloudScore"),
        "cloudMotionTowardRoute": cloud_motion.get("movingTowardRoute"),
        "dataDelayMinutes": data_delay,
        "confidence": round(confidence, 4),
    }
    interactions = _weather_terrain_interactions(features, terrain_segments)
    package = {
        "artifact_kind": "route_weather_risk_package",
        "artifactVersion": "route_weather_risk_package.v1",
        "routeId": route_id,
        "generatedAt": evaluated_at,
        "status": "candidate_only",
        "imageryFeatures": features,
        "weatherTerrainInteractions": interactions,
        "routeBuffer": {
            "bufferM": route_buffer.buffer_m,
            "bboxWgs84": route_buffer.bbox_wgs84,
        },
        "radarFrameCount": len(radar_samples),
        "satelliteFrameCount": len(satellite_samples),
        "sourceRefs": _source_refs(radar_samples, satellite_samples),
        "dataDelayBySource": {
            "radarMinutes": radar_delay,
            "satelliteMinutes": satellite_delay,
        },
        "humanReviewRequired": True,
        "boundary": {
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "phase1MutationAllowed": False,
            "outboundSendAllowed": False,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
        },
    }
    if provenance:
        package.update(dict(provenance))
    package["loraAlert"] = encode_compact_lora_alert(package)
    return package


def encode_compact_lora_alert(
    package: dict[str, Any],
    *,
    max_bytes: int = 160,
) -> dict[str, Any]:
    features = package.get("imageryFeatures") or {}
    bits = 0
    for index, key in enumerate(
        (
            "currentRainOnRoute",
            "nearbyStrongEcho",
            "rainBandApproaching",
            "cloudMotionTowardRoute",
        )
    ):
        if features.get(key) is True:
            bits |= 1 << index
    compact = {
        "v": 1,
        "t": "wx",
        "r": str(package.get("routeId") or "")[:12],
        "b": bits,
        "a": features.get("estimatedRainArrivalMinutes"),
        "c": _score_100(features.get("convectiveCellScore")),
        "s": _score_100(features.get("satelliteConvectiveCloudScore")),
        "d": features.get("dataDelayMinutes"),
        "q": _score_100(features.get("confidence")),
    }
    encoded = json.dumps(compact, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        compact.pop("r", None)
        encoded = json.dumps(compact, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("compact weather LoRa alert exceeds byte budget")
    return {
        "artifactKind": "routeWeatherLoraAlert",
        "encoding": "json-utf8",
        "encoded": encoded,
        "byteLength": len(encoded.encode("utf-8")),
        "sent": False,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def write_route_weather_risk_outputs(
    project_root: Path | str,
    package: dict[str, Any],
) -> dict[str, str]:
    root = Path(project_root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    package_ref = "outputs/route_weather_risk_package.json"
    alert_ref = "outputs/route_weather_lora_alert.json"
    _write_json(root / package_ref, package)
    _write_json(
        root / alert_ref, package.get("loraAlert") or encode_compact_lora_alert(package)
    )
    return {
        "route_weather_risk_package_ref": package_ref,
        "route_weather_lora_alert_ref": alert_ref,
    }


FrameGridDecoder = Callable[[CachedImageryFrame, WeatherImageryTileCache], RasterGrid]


def run_server_side_cwa_imagery_job(
    *,
    project_root: Path | str,
    route_id: str,
    route_identity: Mapping[str, Any] | None = None,
    route_points: Iterable[tuple[float, float]],
    terrain_segments: Iterable[dict[str, Any]],
    radar_ingestor: CwaRadarIngestor,
    satellite_ingestor: CwaSatelliteIngestor,
    cache: WeatherImageryTileCache,
    registry: Mapping[str, ImageryProductSpec],
    radar_product_id: str = "radar.integrated.taiwan.transparent",
    satellite_product_id: str = "satellite.enhanced_color.taiwan",
    evaluated_at: str,
    allow_network_fetch: bool,
    processing_profile: str = "mac-workstation",
    route_buffer_m: float = 500.0,
    frame_grid_decoder: FrameGridDecoder = decode_cached_frame_grid,
    build_display_assets: bool = True,
    server_capability_attested: bool = False,
    min_job_interval_seconds: int = 30,
) -> dict[str, str]:
    if not server_capability_attested:
        raise RuntimeError("trusted server imagery capability attestation is required")
    if processing_profile not in {"mac-workstation", "server-workstation"}:
        raise RuntimeError(
            "CWA imagery processing is server-side only; Pi/mobile consume prepared artifacts"
        )
    architecture = platform.machine().lower()
    if architecture.startswith(("arm", "aarch64")) or _is_raspberry_pi_host():
        raise RuntimeError(
            "CWA imagery processing is disabled on ARM and Raspberry Pi hosts"
        )
    with cache.server_job_guard(min_interval_seconds=min_job_interval_seconds):
        return _run_server_side_cwa_imagery_job_unlocked(
            project_root=project_root,
            route_id=route_id,
            route_identity=route_identity,
            route_points=route_points,
            terrain_segments=terrain_segments,
            radar_ingestor=radar_ingestor,
            satellite_ingestor=satellite_ingestor,
            cache=cache,
            registry=registry,
            radar_product_id=radar_product_id,
            satellite_product_id=satellite_product_id,
            evaluated_at=evaluated_at,
            allow_network_fetch=allow_network_fetch,
            processing_profile=processing_profile,
            route_buffer_m=route_buffer_m,
            frame_grid_decoder=frame_grid_decoder,
            build_display_assets=build_display_assets,
        )


def _run_server_side_cwa_imagery_job_unlocked(
    *,
    project_root: Path | str,
    route_id: str,
    route_identity: Mapping[str, Any] | None,
    route_points: Iterable[tuple[float, float]],
    terrain_segments: Iterable[dict[str, Any]],
    radar_ingestor: CwaRadarIngestor,
    satellite_ingestor: CwaSatelliteIngestor,
    cache: WeatherImageryTileCache,
    registry: Mapping[str, ImageryProductSpec],
    radar_product_id: str,
    satellite_product_id: str,
    evaluated_at: str,
    allow_network_fetch: bool,
    processing_profile: str,
    route_buffer_m: float,
    frame_grid_decoder: FrameGridDecoder,
    build_display_assets: bool,
) -> dict[str, str]:
    if _is_raspberry_pi_host():
        raise RuntimeError(
            "CWA imagery processing is disabled on actual Raspberry Pi hosts"
        )
    if processing_profile.startswith("pi-") or "mobile" in processing_profile.lower():
        raise RuntimeError(
            "CWA imagery processing is server-side only; Pi/mobile consume prepared artifacts"
        )
    if not allow_network_fetch:
        raise PermissionError(
            "explicit network approval is required for the CWA imagery server job"
        )
    root = Path(project_root).resolve()
    try:
        cache.root.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError(
            "raw CWA imagery cache must live outside the project workspace"
        )
    route_buffer = build_route_buffer(route_points, buffer_m=route_buffer_m)
    radar_frames = _ingest_window_or_latest(
        radar_ingestor,
        radar_product_id,
        evaluated_at=evaluated_at,
        build_display_assets=build_display_assets,
    )
    satellite_frames = _ingest_window_or_latest(
        satellite_ingestor,
        satellite_product_id,
        evaluated_at=evaluated_at,
        build_display_assets=build_display_assets,
    )
    radar_samples: list[dict[str, Any]] = []
    sampling_bbox = _expanded_route_bbox(route_buffer, radius_km=25.0)
    for frame in radar_frames:
        grid = _decode_frame_for_route(frame, cache, frame_grid_decoder, sampling_bbox)
        sample = sample_radar_grid(
            grid,
            route_buffer,
            source_timestamp=frame.source_timestamp,
            fetched_at=frame.fetched_at,
        )
        max_dbz = _float(sample.get("maxReflectivityDbz"))
        radar_samples.append(
            {
                **sample,
                "convectiveCellScore": round(max(0.0, min(1.0, max_dbz / 60.0)), 4),
                "frameId": frame.frame_id,
                "frameRef": frame.cache_ref,
                "expectedDelayMinutes": frame.expected_delay_minutes,
            }
        )
    satellite_samples: list[dict[str, Any]] = []
    for frame in satellite_frames:
        if not frame.route_sampling_supported:
            continue
        sample = sample_satellite_grid(
            _decode_frame_for_route(frame, cache, frame_grid_decoder, sampling_bbox),
            route_buffer,
            source_timestamp=frame.source_timestamp,
            fetched_at=frame.fetched_at,
        )
        satellite_samples.append(
            {
                **sample,
                "frameId": frame.frame_id,
                "frameRef": frame.cache_ref,
                "expectedDelayMinutes": frame.expected_delay_minutes,
            }
        )
    radar_motion = estimate_motion_toward_route(radar_samples, route_buffer)
    cloud_motion = estimate_motion_toward_route(
        satellite_samples,
        route_buffer,
        centroid_key="convectiveCloudCentroid",
    )
    provenance = _imagery_route_provenance(
        route_id=route_id,
        route_identity=route_identity,
        radar_frames=radar_frames,
        satellite_frames=satellite_frames,
    )
    package = build_route_weather_risk_package(
        route_id=route_id,
        route_buffer=route_buffer,
        radar_samples=radar_samples,
        satellite_samples=satellite_samples,
        radar_motion=radar_motion,
        cloud_motion=cloud_motion,
        terrain_segments=list(terrain_segments),
        evaluated_at=evaluated_at,
        provenance=provenance,
    )
    imagery_dir = root / "outputs" / "environment" / "cwa" / "imagery"
    imagery_dir.mkdir(parents=True, exist_ok=True)
    package_ref = "outputs/route_weather_risk_package.json"
    alert_ref = "outputs/route_weather_lora_alert.json"
    registry_ref = "outputs/environment/cwa/imagery/registry_snapshot.json"
    radar_ref = "outputs/environment/cwa/imagery/radar_frames_manifest.json"
    satellite_ref = "outputs/environment/cwa/imagery/satellite_frames_manifest.json"
    sampling_ref = "outputs/environment/cwa/imagery/route_imagery_sampling.json"
    motion_ref = "outputs/environment/cwa/imagery/radar_motion_estimate.json"
    manifest_ref = "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
    radar_manifest = _frames_manifest(
        "radar",
        radar_frames,
        evaluated_at=evaluated_at,
        provenance=provenance,
    )
    satellite_manifest = _frames_manifest(
        "satellite",
        satellite_frames,
        evaluated_at=evaluated_at,
        provenance=provenance,
    )
    sampling_payload = {
        "artifactKind": "routeImagerySampling",
        "generatedAt": evaluated_at,
        "routeBuffer": route_buffer.to_geojson(),
        "radarSamples": radar_samples,
        "satelliteSamples": satellite_samples,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
        **provenance,
    }
    motion_payload = {
        "artifactKind": "routeImageryMotionEstimate",
        "generatedAt": evaluated_at,
        "radar": radar_motion,
        "satellite": cloud_motion,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
        **provenance,
    }
    combined_manifest = {
        "artifactKind": "weatherImageryTimelineManifest",
        "schemaVersion": "weatherImageryTimelineManifest.v1",
        "generatedAt": evaluated_at,
        "layerId": "cwa-weather",
        "animationWindowsHours": list(ANIMATION_WINDOWS_HOURS),
        "childOverlays": {
            "radar": {**radar_manifest, "defaultOpacity": 0.62},
            "satellite": {**satellite_manifest, "defaultOpacity": 0.48},
        },
        "routeWeatherRiskPackageRef": package_ref,
        "processingBoundary": {
            "serverSideOnly": True,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
            "adminReadIsCacheOnly": True,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
        },
        **provenance,
    }
    refs = {
        "route_weather_risk_package_ref": package_ref,
        "route_weather_lora_alert_ref": alert_ref,
        "cwa_imagery_registry_ref": registry_ref,
        "cwa_radar_frames_manifest_ref": radar_ref,
        "cwa_satellite_frames_manifest_ref": satellite_ref,
        "route_imagery_sampling_ref": sampling_ref,
        "radar_motion_estimate_ref": motion_ref,
        "cwa_weather_imagery_manifest_ref": manifest_ref,
    }
    project_path = root / "project.json"
    project = (
        json.loads(project_path.read_text(encoding="utf-8"))
        if project_path.exists()
        else {}
    )
    project_update = {
        **project,
        **refs,
        "cwa_weather_imagery_updated_at": evaluated_at,
        "cwa_weather_imagery_pair_id": provenance["pairId"],
        "cwa_weather_imagery_route_ref": provenance.get("routeRef"),
        "cwa_weather_imagery_route_sha256": provenance.get("routeSha256"),
        "cwa_weather_imagery_route_basis": provenance.get("routeBasis"),
    }
    _publish_json_artifact_set(
        [
            (root / registry_ref, public_registry_contract(registry)),
            (root / radar_ref, radar_manifest),
            (root / satellite_ref, satellite_manifest),
            (root / sampling_ref, sampling_payload),
            (root / motion_ref, motion_payload),
            (root / package_ref, package),
            (root / alert_ref, package["loraAlert"]),
            # The active manifest is the commit marker for the artifact set.
            (root / manifest_ref, combined_manifest),
            # Project pointers publish only after the complete artifact set.
            (project_path, project_update),
        ]
    )
    return refs


def _ingest_window_or_latest(
    ingestor: Any,
    product_id: str,
    *,
    evaluated_at: str,
    build_display_assets: bool,
) -> list[CachedImageryFrame]:
    frames = ingestor.ingest_recent(
        product_id,
        hours=12,
        allow_network_fetch=True,
        fetched_at=evaluated_at,
        build_display_asset=build_display_assets,
    )
    if frames:
        return frames
    return [
        ingestor.ingest_latest(
            product_id,
            allow_network_fetch=True,
            fetched_at=evaluated_at,
            build_display_asset=build_display_assets,
        )
    ]


def _decode_frame_for_route(
    frame: CachedImageryFrame,
    cache: WeatherImageryTileCache,
    decoder: FrameGridDecoder,
    sampling_bbox: dict[str, float],
) -> RasterGrid:
    if decoder is decode_cached_frame_grid:
        return decode_cached_frame_grid(
            frame,
            cache,
            max_grid_dimension=160,
            sample_bbox_wgs84=sampling_bbox,
        )
    return decoder(frame, cache)


def _expanded_route_bbox(
    route_buffer: RouteBuffer, *, radius_km: float
) -> dict[str, float]:
    center_lat = sum(point[0] for point in route_buffer.route_points) / len(
        route_buffer.route_points
    )
    lat_pad = radius_km / 110.574
    lon_scale = max(1.0, 111.320 * abs(cos(radians(center_lat))))
    lon_pad = radius_km / lon_scale
    bbox = route_buffer.bbox_wgs84
    return {
        "west": bbox["west"] - lon_pad,
        "south": bbox["south"] - lat_pad,
        "east": bbox["east"] + lon_pad,
        "north": bbox["north"] + lat_pad,
    }


def _imagery_route_provenance(
    *,
    route_id: str,
    route_identity: Mapping[str, Any] | None,
    radar_frames: Iterable[CachedImageryFrame],
    satellite_frames: Iterable[CachedImageryFrame],
) -> dict[str, Any]:
    project_id = route_id.strip()
    if not project_id:
        raise ValueError("CWA imagery route_id must not be empty")
    provenance: dict[str, Any] = {"projectId": project_id}
    if route_identity is not None:
        identity_project = str(route_identity.get("projectId") or "").strip()
        if identity_project != project_id:
            raise ValueError("CWA imagery route identity project mismatch")
        route_ref = str(route_identity.get("routeRef") or "").strip()
        route_ref_path = Path(route_ref)
        if (
            not route_ref
            or route_ref_path.is_absolute()
            or any(part in {".", ".."} for part in route_ref_path.parts)
        ):
            raise ValueError("CWA imagery route identity ref is unsafe")
        route_sha256 = str(route_identity.get("routeSha256") or "").strip().lower()
        if len(route_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in route_sha256
        ):
            raise ValueError("CWA imagery route identity hash is invalid")
        route_basis = str(route_identity.get("routeBasis") or "").strip()
        if not route_basis:
            raise ValueError("CWA imagery route identity basis is missing")
        provenance.update(
            {
                "routeRef": route_ref,
                "routeSha256": route_sha256,
                "routeBasis": route_basis,
            }
        )
        point_count = route_identity.get("pointCount")
        if (
            isinstance(point_count, int)
            and not isinstance(point_count, bool)
            and point_count > 0
        ):
            provenance["routePointCount"] = point_count
    source_frame_ids = {
        "radar": sorted({frame.frame_id for frame in radar_frames}),
        "satellite": sorted({frame.frame_id for frame in satellite_frames}),
    }
    provenance["sourceFrameIds"] = source_frame_ids
    pair_material = json.dumps(
        provenance,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    provenance["pairId"] = (
        f"cwa.imagery.{hashlib.sha256(pair_material).hexdigest()[:24]}"
    )
    return provenance


def _frames_manifest(
    family: str,
    frames: list[CachedImageryFrame],
    *,
    evaluated_at: str,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(frames, key=lambda frame: _parse_time(frame.source_timestamp))
    latest = ordered[-1] if ordered else None
    windows: dict[str, list[str]] = {}
    if latest is not None:
        latest_time = _parse_time(latest.source_timestamp)
        for hours in ANIMATION_WINDOWS_HOURS:
            windows[f"{hours}h"] = [
                frame.frame_id
                for frame in ordered
                if (latest_time - _parse_time(frame.source_timestamp)).total_seconds()
                <= hours * 3600
            ]
    frame_payloads = []
    for frame in ordered:
        item = frame.to_dict()
        item["dataDelayMinutes"] = _data_delay_minutes(
            evaluated_at, [frame.source_timestamp]
        )
        if frame.map_overlay_supported:
            item["assetRef"] = frame.display_ref or frame.cache_ref
        frame_payloads.append(item)
    manifest = {
        "artifactKind": f"cwa{family.title()}FramesManifest",
        "family": family,
        "latestFrameId": latest.frame_id if latest else None,
        "frames": frame_payloads,
        "windows": windows,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }
    if provenance:
        manifest.update(dict(provenance))
    return manifest


def _weather_terrain_interactions(
    features: dict[str, Any],
    terrain_segments: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []
    raining = features.get("currentRainOnRoute") is True
    strong_echo = features.get("nearbyStrongEcho") is True
    convective = (
        max(
            _float(features.get("convectiveCellScore")),
            _float(features.get("satelliteConvectiveCloudScore")),
        )
        >= 0.7
    )
    for segment in terrain_segments:
        hazards = {str(item).lower() for item in segment.get("hazardTypes") or []}
        grade = _float(segment.get("gradePercent"), default=0.0)
        rules: list[tuple[str, bool]] = [
            ("RAIN_DRY_CREEK", raining and "dry_creek" in hazards),
            ("RAIN_SCREE_CLIFF", raining and bool(hazards & {"scree", "cliff"})),
            ("THUNDER_RIDGE", convective and "ridge" in hazards),
            ("STRONG_ECHO_STEEP_DESCENT", strong_echo and grade <= -15.0),
        ]
        for code, matched in rules:
            if not matched:
                continue
            interactions.append(
                {
                    "ruleCode": code,
                    "segmentId": segment.get("segmentId"),
                    "teii_20m": segment.get("teii_20m"),
                    "weatherConfidence": features.get("confidence"),
                    "terrainSourceRefs": list(segment.get("terrainSourceRefs") or []),
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                }
            )
    return interactions


def _data_delay_minutes(evaluated_at: str, timestamps: list[Any]) -> int | None:
    parsed = [_parse_time(item) for item in timestamps if isinstance(item, str)]
    if not parsed:
        return None
    delay = (_parse_time(evaluated_at) - min(parsed)).total_seconds() / 60.0
    return max(0, round(delay))


def _source_refs(
    radar_samples: list[dict[str, Any]],
    satellite_samples: list[dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    for sample in [*radar_samples, *satellite_samples]:
        for key in ("frameRef", "sourceRef", "tileManifestRef"):
            value = sample.get(key)
            if isinstance(value, str) and value and value not in refs:
                refs.append(value)
    return refs


def _mean(values: list[Any]) -> float:
    numeric = [_float(value) for value in values if value is not None]
    return sum(numeric) / len(numeric) if numeric else 0.0


def _freshness_ratio(delay_minutes: int | None, expected_delay: Any) -> float:
    if delay_minutes is None:
        return 1.0
    expected = max(1.0, _float(expected_delay, default=20.0))
    return max(0.15, min(1.0, expected / max(expected, float(delay_minutes))))


def _is_raspberry_pi_host() -> bool:
    for path in (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    ):
        try:
            if (
                "raspberry pi"
                in path.read_text(encoding="utf-8", errors="ignore").lower()
            ):
                return True
        except OSError:
            continue
    return False


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_100(value: Any) -> int | None:
    return round(max(0.0, min(1.0, _float(value))) * 100) if value is not None else None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_json(path: Path, payload: Any) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_bytes_atomically(path, content)


def _publish_json_artifact_set(
    artifacts: Iterable[tuple[Path, Any]],
) -> None:
    serialized = [
        (
            path,
            (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
        )
        for path, payload in artifacts
    ]
    backups = {
        path: path.read_bytes() if path.is_file() else None
        for path, _content in serialized
    }
    published: list[Path] = []
    try:
        for path, content in serialized:
            _write_bytes_atomically(path, content)
            published.append(path)
    except Exception:
        for path in reversed(published):
            previous = backups[path]
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                _write_bytes_atomically(path, previous)
        raise


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
