import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from pretrip_admin_view import _cwa_weather_imagery_summary


ROOT = Path(__file__).resolve().parents[1]


def test_pretrip_map_renders_numeric_rainfall_cells_with_product_and_opacity_controls() -> None:
    html = (ROOT / "docs/admin/phase4-pretrip-planning.html").read_text(
        encoding="utf-8"
    )

    for marker in (
        "renderCwaRainfallGrid",
        "data-cwa-rainfall-product",
        "data-cwa-rainfall-opacity",
        "data-cwa-rainfall-legend",
        "data-cwa-rainfall-status",
        "qpe_past_1h",
        "qpf_next_1h",
        "CWA rainfall / radar / satellite",
    ):
        assert marker in html


def test_debug_and_after_action_disclose_persisted_rainfall_render_support() -> None:
    debug_html = (ROOT / "docs/admin/phase-3-5-runtime-debug.html").read_text(
        encoding="utf-8"
    )
    admin_html = (ROOT / "docs/admin/phase1-after-action.html").read_text(
        encoding="utf-8"
    )

    for html in (debug_html, admin_html):
        assert 'data-cwa-rainfall-support="legacy_projection"' in html
        assert "Persisted rainfall grid is available in Pre-trip and Dashboard Map" in html
        assert "candidate-only" in html


def test_admin_weather_imagery_manifest_and_asset_are_cache_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    manifest_path = project_root / "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    cache_root = tmp_path / "external-cache"
    asset_ref = "frames/radar/frame.display.png"
    asset_path = cache_root / asset_ref
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"cached-overlay")
    manifest = {
        "artifactKind": "weatherImageryTimelineManifest",
        "schemaVersion": "weatherImageryTimelineManifest.v1",
        "projectId": "fixture-route",
        "layerId": "cwa-weather",
        "animationWindowsHours": [3, 6, 9, 12],
        "childOverlays": {
            "radar": {
                "frames": [
                    {
                        "frameId": "radar.frame.001",
                        "sourceTimestamp": "2026-07-11T03:20:00Z",
                        "fetchedAt": "2026-07-11T03:27:00Z",
                        "imageType": "echo_no_terrain",
                        "extent": "taiwan",
                        "expectedDelayMinutes": 12,
                        "bboxWgs84": {"west": 118, "south": 20.5, "east": 124, "north": 26.5},
                        "mediaType": "image/jpeg",
                        "displayMediaType": "image/png",
                        "cacheRef": "frames/radar/raw.png",
                        "displayRef": asset_ref,
                        "assetRef": asset_ref,
                    }
                ]
            },
            "satellite": {
                "frames": [
                    {
                        "frameId": "satellite.full-disk.raw",
                        "sourceTimestamp": "2026-07-11T03:20:00Z",
                        "fetchedAt": "2026-07-11T03:27:00Z",
                        "imageType": "enhanced_color",
                        "extent": "full_disk",
                        "expectedDelayMinutes": 20,
                        "bboxWgs84": {"west": 60, "south": -90, "east": 240, "north": 90},
                        "mediaType": "image/jpeg",
                        "cacheRef": "frames/satellite/raw.jpg",
                        "mapOverlaySupported": False,
                    }
                ]
            },
        },
        "processingBoundary": {
            "adminReadIsCacheOnly": True,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "fixture-route",
                "cwa_weather_imagery_manifest_ref": (
                    "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
                ),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCOUT_CWA_IMAGERY_CACHE_ROOT", str(cache_root))
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.get("/admin/pretrip/projects/fixture-route/weather-imagery")
    assert response.status_code == 200
    payload = response.json()
    frame = payload["childOverlays"]["radar"]["frames"][0]
    assert frame["assetUrl"].endswith("/weather-imagery/radar.frame.001")
    assert "cacheRef" not in frame
    assert "displayRef" not in frame
    assert payload["processingBoundary"]["adminReadIsCacheOnly"] is True
    raw_full_disk = payload["childOverlays"]["satellite"]["frames"][0]
    assert "assetUrl" not in raw_full_disk

    asset = client.get(frame["assetUrl"])
    assert asset.status_code == 200
    assert asset.content == b"cached-overlay"
    assert asset.headers["content-type"] == "image/png"
    assert asset.headers["x-scout-candidate-only"] == "true"
    assert asset.headers["x-scout-runtime-safety-truth"] == "false"
    assert client.get(
        "/admin/pretrip/projects/fixture-route/weather-imagery/missing"
    ).status_code == 404
    assert client.get(
        "/admin/pretrip/projects/fixture-route/weather-imagery/satellite.full-disk.raw"
    ).status_code == 404


def test_admin_weather_imagery_recomputes_freshness_and_hides_missing_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    manifest_ref = "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
    manifest_path = project_root / manifest_ref
    manifest_path.parent.mkdir(parents=True)
    cache_root = tmp_path / "external-cache"
    asset_ref = "frames/radar/stale.display.png"
    asset_path = cache_root / asset_ref
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"stale-overlay")
    manifest_path.write_text(
        json.dumps(
            {
                "artifactKind": "weatherImageryTimelineManifest",
                "schemaVersion": "weatherImageryTimelineManifest.v1",
                "projectId": "fixture-route",
                "childOverlays": {
                    "radar": {
                        "frames": [
                            {
                                "frameId": "radar.stale.001",
                                "sourceTimestamp": "2026-07-11T03:20:00Z",
                                "fetchedAt": "2026-07-11T03:27:00Z",
                                "updateIntervalMinutes": 10,
                                "expectedDelayMinutes": 10,
                                "assetRef": asset_ref,
                                "mapOverlaySupported": True,
                            }
                        ]
                    },
                    "satellite": {"frames": []},
                },
                "processingBoundary": {"candidateOnly": True, "runtimeSafetyTruth": False},
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "fixture-route",
                "cwa_weather_imagery_manifest_ref": manifest_ref,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCOUT_CWA_IMAGERY_CACHE_ROOT", str(cache_root))
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            now_factory=lambda: datetime.fromisoformat("2026-07-11T06:30:00+00:00"),
        )
    )

    stale = client.get("/admin/pretrip/projects/fixture-route/weather-imagery").json()
    frame = stale["childOverlays"]["radar"]["frames"][0]
    assert stale["status"] == "stale_data"
    assert frame["freshness"]["status"] == "stale_data"
    assert frame["assetStatus"] == "available"
    assert frame["assetUrl"].endswith("/weather-imagery/radar.stale.001")

    asset_path.unlink()
    missing = client.get("/admin/pretrip/projects/fixture-route/weather-imagery").json()
    missing_frame = missing["childOverlays"]["radar"]["frames"][0]
    assert missing["status"] == "cache_missing"
    assert missing_frame["assetStatus"] == "cache_missing"
    assert "assetUrl" not in missing_frame


def test_pretrip_view_summary_keeps_only_compact_weather_imagery_features() -> None:
    summary = _cwa_weather_imagery_summary(
        "fixture-route",
        manifest={
            "animationWindowsHours": [3, 6, 9, 12],
            "childOverlays": {
                "radar": {
                    "latestFrameId": "radar.frame.001",
                    "frames": [
                        {
                            "frameId": "radar.frame.001",
                            "sourceTimestamp": "2026-07-11T03:20:00Z",
                            "fetchedAt": "2026-07-11T03:27:00Z",
                            "imageType": "echo_no_terrain",
                            "extent": "taiwan",
                            "expectedDelayMinutes": 12,
                            "dataDelayMinutes": 10,
                            "bboxWgs84": {"west": 118, "south": 20.5, "east": 124, "north": 26.5},
                            "cacheRef": "must-not-leak",
                        }
                    ],
                },
                "satellite": {"frames": []},
            },
        },
        risk_package={
            "imageryFeatures": {"currentRainOnRoute": True, "confidence": 0.8},
            "weatherTerrainInteractions": [],
        },
        source_refs={
            "cwa_weather_imagery_manifest": "outputs/environment/cwa/imagery/weather_imagery_manifest.json",
            "route_weather_risk_package": "outputs/route_weather_risk_package.json",
        },
    )

    assert summary["status"] == "ready"
    assert summary["imageryFeatures"]["currentRainOnRoute"] is True
    assert summary["childOverlays"]["radar"]["frameCount"] == 1
    assert "cacheRef" not in str(summary)
    assert summary["processingBoundary"]["adminReadIsCacheOnly"] is True
