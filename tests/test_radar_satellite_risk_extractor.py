import json
from pathlib import Path

import pytest

import radar_satellite_risk_extractor as extractor
from radar_satellite_risk_extractor import (
    build_route_weather_risk_package,
    encode_compact_lora_alert,
    run_server_side_cwa_imagery_job,
    write_route_weather_risk_outputs,
)
from cwa_imagery_registry import build_cwa_imagery_registry
from cwa_radar_ingestor import CwaRadarIngestor
from cwa_satellite_ingestor import CwaSatelliteIngestor
from route_imagery_sampler import RasterGrid, build_route_buffer
from weather_imagery_tile_cache import WeatherImageryTileCache


def test_risk_extractor_outputs_requested_features_and_teii_interactions(tmp_path: Path) -> None:
    route_buffer = build_route_buffer([(24.0, 121.0), (24.0, 121.02)], buffer_m=1_000)
    radar_samples = [
        {
            "sourceTimestamp": "2026-07-11T03:20:00Z",
            "fetchedAt": "2026-07-11T03:27:00Z",
            "currentRainOnRoute": True,
            "nearbyStrongEcho": True,
            "convectiveCellScore": 0.88,
            "coverageConfidence": 0.9,
        }
    ]
    satellite_samples = [
        {
            "sourceTimestamp": "2026-07-11T03:20:00Z",
            "fetchedAt": "2026-07-11T03:28:00Z",
            "satelliteConvectiveCloudScore": 0.82,
            "coverageConfidence": 0.8,
        }
    ]
    radar_motion = {
        "movingTowardRoute": True,
        "estimatedArrivalMinutes": 35,
        "confidence": 0.75,
    }
    cloud_motion = {"movingTowardRoute": True, "confidence": 0.6}
    terrain_segments = [
        {
            "segmentId": "seg.001",
            "teii_20m": 91,
            "hazardTypes": ["dry_creek", "scree", "cliff", "ridge"],
            "gradePercent": -28,
            "terrainSourceRefs": ["outputs/risk_score_points.geojson"],
        }
    ]

    package = build_route_weather_risk_package(
        route_id="fixture-route",
        route_buffer=route_buffer,
        radar_samples=radar_samples,
        satellite_samples=satellite_samples,
        radar_motion=radar_motion,
        cloud_motion=cloud_motion,
        terrain_segments=terrain_segments,
        evaluated_at="2026-07-11T03:30:00Z",
    )

    features = package["imageryFeatures"]
    assert features == {
        "currentRainOnRoute": True,
        "nearbyStrongEcho": True,
        "rainBandApproaching": True,
        "estimatedRainArrivalMinutes": 35,
        "convectiveCellScore": 0.88,
        "satelliteConvectiveCloudScore": 0.82,
        "cloudMotionTowardRoute": True,
        "dataDelayMinutes": 10,
        "confidence": features["confidence"],
    }
    assert 0 < features["confidence"] <= 1
    assert {item["ruleCode"] for item in package["weatherTerrainInteractions"]} == {
        "RAIN_DRY_CREEK",
        "RAIN_SCREE_CLIFF",
        "THUNDER_RIDGE",
        "STRONG_ECHO_STEEP_DESCENT",
    }
    assert package["boundary"]["candidateOnly"] is True
    assert package["boundary"]["runtimeSafetyTruth"] is False

    output = write_route_weather_risk_outputs(tmp_path, package)
    assert output["route_weather_risk_package_ref"] == "outputs/route_weather_risk_package.json"
    written = json.loads((tmp_path / output["route_weather_risk_package_ref"]).read_text())
    assert written["routeId"] == "fixture-route"
    alert = encode_compact_lora_alert(package)
    assert len(alert["encoded"].encode("utf-8")) <= 160
    assert alert["sent"] is False
    assert alert["runtimeSafetyTruth"] is False


def test_teii_alone_does_not_invent_terrain_classification() -> None:
    package = build_route_weather_risk_package(
        route_id="fixture-route",
        route_buffer=build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500),
        radar_samples=[
            {
                "sourceTimestamp": "2026-07-11T03:20:00Z",
                "fetchedAt": "2026-07-11T03:27:00Z",
                "currentRainOnRoute": True,
                "nearbyStrongEcho": True,
                "convectiveCellScore": 0.9,
                "coverageConfidence": 1.0,
            }
        ],
        satellite_samples=[],
        radar_motion={},
        cloud_motion={},
        terrain_segments=[{"segmentId": "seg.001", "teii_20m": 99}],
        evaluated_at="2026-07-11T03:30:00Z",
    )

    assert package["weatherTerrainInteractions"] == []


def test_compact_lora_alert_rejects_impossible_byte_budget() -> None:
    with pytest.raises(ValueError, match="exceeds byte budget"):
        encode_compact_lora_alert(
            {
                "routeId": "fixture-route",
                "imageryFeatures": {
                    "currentRainOnRoute": True,
                    "confidence": 0.8,
                },
            },
            max_bytes=1,
        )


def test_fresh_satellite_does_not_hide_stale_radar_delay_or_confidence() -> None:
    package = build_route_weather_risk_package(
        route_id="fixture-route",
        route_buffer=build_route_buffer([(24.0, 121.0), (24.0, 121.01)], buffer_m=500),
        radar_samples=[
            {
                "sourceTimestamp": "2026-07-11T01:30:00Z",
                "fetchedAt": "2026-07-11T03:29:00Z",
                "expectedDelayMinutes": 12,
                "currentRainOnRoute": True,
                "nearbyStrongEcho": True,
                "convectiveCellScore": 0.8,
                "coverageConfidence": 1.0,
            }
        ],
        satellite_samples=[
            {
                "sourceTimestamp": "2026-07-11T03:25:00Z",
                "fetchedAt": "2026-07-11T03:29:00Z",
                "expectedDelayMinutes": 20,
                "satelliteConvectiveCloudScore": 0.8,
                "coverageConfidence": 1.0,
            }
        ],
        radar_motion={"confidence": 1.0},
        cloud_motion={"confidence": 1.0},
        terrain_segments=[],
        evaluated_at="2026-07-11T03:30:00Z",
    )

    assert package["imageryFeatures"]["dataDelayMinutes"] == 120
    assert package["dataDelayBySource"] == {
        "radarMinutes": 120,
        "satelliteMinutes": 5,
    }
    assert package["imageryFeatures"]["confidence"] <= 0.2


def test_server_job_writes_compact_manifests_and_rejects_pi_processing(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace" / "route"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text('{"project_id":"fixture-route"}\n')
    cache = WeatherImageryTileCache(tmp_path / "external-cache")
    registry = build_cwa_imagery_registry()
    radar_spec = registry["radar.integrated.taiwan.transparent"]
    satellite_spec = registry["satellite.enhanced_color.taiwan"]

    def metadata(spec):
        return {"sourceTimestamp": "2026-07-11T03:20:00Z", "url": spec.latest_url}

    def history(spec, _hours):
        return [metadata(spec)]

    def image_bytes(url):
        media_type = "image/png" if url.endswith(".png") else "image/jpeg"
        return b"fixture-image", media_type, "fixture-etag"

    radar_ingestor = CwaRadarIngestor(
        registry=registry,
        cache=cache,
        latest_metadata_fetcher=metadata,
        history_metadata_fetcher=history,
        bytes_fetcher=image_bytes,
    )
    satellite_ingestor = CwaSatelliteIngestor(
        registry=registry,
        cache=cache,
        latest_metadata_fetcher=metadata,
        history_metadata_fetcher=history,
        bytes_fetcher=image_bytes,
    )
    radar_grid = RasterGrid(
        west=118,
        south=20.5,
        east=124,
        north=26.5,
        values=((25.0, 48.0), (30.0, 52.0)),
    )
    satellite_grid = RasterGrid(
        west=117,
        south=19,
        east=126,
        north=27,
        values=((0.7, 0.9), (0.8, 0.95)),
    )

    refs = run_server_side_cwa_imagery_job(
        project_root=project_root,
        route_id="fixture-route",
        route_identity={
            "projectId": "fixture-route",
            "routeRef": "outputs/segments/overpass_aligned.json",
            "routeSha256": "a" * 64,
            "routeBasis": "overpass_aligned_segment_display_geometry",
            "pointCount": 2,
        },
        route_points=[(24.0, 121.0), (24.0, 121.02)],
        terrain_segments=[],
        radar_ingestor=radar_ingestor,
        satellite_ingestor=satellite_ingestor,
        cache=cache,
        registry=registry,
        radar_product_id=radar_spec.product_id,
        satellite_product_id=satellite_spec.product_id,
        evaluated_at="2026-07-11T03:30:00Z",
        allow_network_fetch=True,
        processing_profile="mac-workstation",
        server_capability_attested=True,
        min_job_interval_seconds=0,
        frame_grid_decoder=lambda frame, _cache: (
            radar_grid if frame.product_id == radar_spec.product_id else satellite_grid
        ),
        build_display_assets=False,
    )

    assert refs["route_weather_risk_package_ref"] == "outputs/route_weather_risk_package.json"
    assert refs["cwa_weather_imagery_manifest_ref"].endswith("weather_imagery_manifest.json")
    project = json.loads((project_root / "project.json").read_text())
    assert project["route_weather_risk_package_ref"] == refs["route_weather_risk_package_ref"]
    manifest = json.loads((project_root / refs["cwa_weather_imagery_manifest_ref"]).read_text())
    assert manifest["animationWindowsHours"] == [3, 6, 9, 12]
    assert manifest["processingBoundary"]["raspberryPiImageProcessing"] is False
    assert manifest["childOverlays"]["radar"]["frames"]
    assert manifest["childOverlays"]["satellite"]["frames"]
    assert "fixture-image" not in json.dumps(manifest)
    assert manifest["projectId"] == "fixture-route"
    assert manifest["routeRef"] == "outputs/segments/overpass_aligned.json"
    assert manifest["routeSha256"] == "a" * 64
    assert manifest["routeBasis"] == "overpass_aligned_segment_display_geometry"
    assert manifest["pairId"]
    assert set(manifest["sourceFrameIds"]) == {"radar", "satellite"}
    for ref_key in (
        "cwa_radar_frames_manifest_ref",
        "cwa_satellite_frames_manifest_ref",
        "route_imagery_sampling_ref",
        "route_weather_risk_package_ref",
    ):
        artifact = json.loads((project_root / refs[ref_key]).read_text())
        assert artifact["projectId"] == "fixture-route"
        assert artifact["routeRef"] == "outputs/segments/overpass_aligned.json"
        assert artifact["routeSha256"] == "a" * 64
        assert artifact["pairId"] == manifest["pairId"]

    try:
        run_server_side_cwa_imagery_job(
            project_root=project_root,
            route_id="fixture-route",
            route_points=[(24.0, 121.0), (24.0, 121.02)],
            terrain_segments=[],
            radar_ingestor=radar_ingestor,
            satellite_ingestor=satellite_ingestor,
            cache=cache,
            registry=registry,
            radar_product_id=radar_spec.product_id,
            satellite_product_id=satellite_spec.product_id,
            evaluated_at="2026-07-11T03:30:00Z",
            allow_network_fetch=True,
            processing_profile="pi-online-explicit",
            server_capability_attested=True,
            frame_grid_decoder=lambda frame, _cache: radar_grid,
            build_display_assets=False,
        )
    except RuntimeError as exc:
        assert "server-side" in str(exc)
    else:
        raise AssertionError("Pi profile must not run image-heavy weather processing")


def test_server_job_rejects_actual_raspberry_pi_host_even_with_mac_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "radar_satellite_risk_extractor._is_raspberry_pi_host",
        lambda: True,
    )

    try:
        run_server_side_cwa_imagery_job(
            project_root=tmp_path / "workspace",
            route_id="fixture-route",
            route_points=[(24.0, 121.0), (24.0, 121.01)],
            terrain_segments=[],
            radar_ingestor=None,
            satellite_ingestor=None,
            cache=WeatherImageryTileCache(tmp_path / "cache"),
            registry={},
            evaluated_at="2026-07-11T03:30:00Z",
            allow_network_fetch=True,
            processing_profile="mac-workstation",
            server_capability_attested=True,
        )
    except RuntimeError as exc:
        assert "Raspberry Pi" in str(exc)
    else:
        raise AssertionError("actual Raspberry Pi host detection must fail closed")


def test_server_job_fails_closed_without_trusted_capability(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="attestation"):
        run_server_side_cwa_imagery_job(
            project_root=tmp_path / "workspace",
            route_id="fixture-route",
            route_points=[(24.0, 121.0), (24.0, 121.01)],
            terrain_segments=[],
            radar_ingestor=None,
            satellite_ingestor=None,
            cache=WeatherImageryTileCache(tmp_path / "cache"),
            registry={},
            evaluated_at="2026-07-11T03:30:00Z",
            allow_network_fetch=True,
            processing_profile="mac-workstation",
        )


def test_unlocked_server_job_rejects_network_denial_and_workspace_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extractor, "_is_raspberry_pi_host", lambda: False)
    project_root = tmp_path / "workspace"
    external_cache = WeatherImageryTileCache(tmp_path / "external-cache")
    common = {
        "project_root": project_root,
        "route_id": "fixture-route",
        "route_identity": None,
        "route_points": [(24.0, 121.0), (24.0, 121.01)],
        "terrain_segments": [],
        "radar_ingestor": None,
        "satellite_ingestor": None,
        "registry": {},
        "radar_product_id": "radar.fixture",
        "satellite_product_id": "satellite.fixture",
        "evaluated_at": "2026-07-11T03:30:00Z",
        "processing_profile": "mac-workstation",
        "route_buffer_m": 500.0,
        "frame_grid_decoder": lambda _frame, _cache: None,
        "build_display_assets": False,
    }

    with pytest.raises(PermissionError, match="network approval"):
        extractor._run_server_side_cwa_imagery_job_unlocked(
            **common,
            cache=external_cache,
            allow_network_fetch=False,
        )

    workspace_cache = WeatherImageryTileCache(project_root / "raw-cache")
    with pytest.raises(ValueError, match="cache must live outside"):
        extractor._run_server_side_cwa_imagery_job_unlocked(
            **common,
            cache=workspace_cache,
            allow_network_fetch=True,
        )


@pytest.mark.parametrize(
    ("route_id", "identity", "message"),
    [
        (" ", None, "route_id must not be empty"),
        (
            "fixture-route",
            {
                "projectId": "other-route",
                "routeRef": "outputs/route.json",
                "routeSha256": "a" * 64,
                "routeBasis": "segment_display_geometry",
            },
            "project mismatch",
        ),
        (
            "fixture-route",
            {
                "projectId": "fixture-route",
                "routeRef": "../route.json",
                "routeSha256": "a" * 64,
                "routeBasis": "segment_display_geometry",
            },
            "ref is unsafe",
        ),
        (
            "fixture-route",
            {
                "projectId": "fixture-route",
                "routeRef": "outputs/route.json",
                "routeSha256": "invalid",
                "routeBasis": "segment_display_geometry",
            },
            "hash is invalid",
        ),
        (
            "fixture-route",
            {
                "projectId": "fixture-route",
                "routeRef": "outputs/route.json",
                "routeSha256": "a" * 64,
                "routeBasis": " ",
            },
            "basis is missing",
        ),
    ],
)
def test_imagery_route_provenance_rejects_invalid_identity(
    route_id: str,
    identity: dict[str, object] | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        extractor._imagery_route_provenance(
            route_id=route_id,
            route_identity=identity,
            radar_frames=[],
            satellite_frames=[],
        )


def test_empty_frame_manifest_and_latest_fallback_are_explicit() -> None:
    manifest = extractor._frames_manifest(
        "radar",
        [],
        evaluated_at="2026-07-11T03:30:00Z",
    )
    assert manifest["latestFrameId"] is None
    assert manifest["frames"] == []
    assert manifest["windows"] == {}

    sentinel = object()

    class EmptyWindowIngestor:
        def ingest_recent(self, *_args, **_kwargs):
            return []

        def ingest_latest(self, *_args, **_kwargs):
            return sentinel

    assert extractor._ingest_window_or_latest(
        EmptyWindowIngestor(),
        "radar.fixture",
        evaluated_at="2026-07-11T03:30:00Z",
        build_display_assets=False,
    ) == [sentinel]


def test_imagery_artifact_set_rolls_back_if_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"version":"old-first"}\n', encoding="utf-8")
    second.write_text('{"version":"old-second"}\n', encoding="utf-8")
    previous = {first: first.read_bytes(), second: second.read_bytes()}
    real_write = extractor._write_bytes_atomically

    def fail_second_new_publish(path: Path, content: bytes) -> None:
        if path == second and b'"new-second"' in content:
            raise OSError("injected publish failure")
        real_write(path, content)

    monkeypatch.setattr(extractor, "_write_bytes_atomically", fail_second_new_publish)

    with pytest.raises(OSError, match="injected publish failure"):
        extractor._publish_json_artifact_set(
            [
                (first, {"version": "new-first"}),
                (second, {"version": "new-second"}),
            ]
        )

    assert {path: path.read_bytes() for path in previous} == previous


def test_imagery_artifact_rollback_removes_newly_created_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    real_write = extractor._write_bytes_atomically

    def fail_second_publish(path: Path, content: bytes) -> None:
        if path == second:
            raise OSError("injected second publish failure")
        real_write(path, content)

    monkeypatch.setattr(extractor, "_write_bytes_atomically", fail_second_publish)

    with pytest.raises(OSError, match="second publish failure"):
        extractor._publish_json_artifact_set(
            [
                (first, {"version": "new-first"}),
                (second, {"version": "new-second"}),
            ]
        )

    assert not first.exists()
    assert not second.exists()
