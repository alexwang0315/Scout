import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from admin_api import _build_weather_dashboard_decision, create_admin_app
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
    cache_root = project_root / "cache" / "cwa-weather-imagery"
    asset_ref = "frames/radar/frame.display.png"
    asset_path = cache_root / asset_ref
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"cached-overlay")
    other_cache_root = (
        workspace_root / "other-route" / "cache" / "cwa-weather-imagery"
    )
    other_asset_path = other_cache_root / asset_ref
    other_asset_path.parent.mkdir(parents=True)
    other_asset_path.write_bytes(b"wrong-workspace-overlay")
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
    monkeypatch.setenv("SCOUT_CWA_IMAGERY_CACHE_ROOT", str(other_cache_root))
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
    cache_root = project_root / "cache" / "cwa-weather-imagery"
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
    monkeypatch.setenv(
        "SCOUT_CWA_IMAGERY_CACHE_ROOT",
        str(tmp_path / "legacy-global-cache"),
    )
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


def test_admin_weather_dashboard_combines_cached_route_decision_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    imagery_ref = "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
    trend_ref = "outputs/environment/cwa/rainfall/route_precipitation_trend.json"
    risk_ref = "outputs/route_weather_risk_package.json"
    alert_ref = "outputs/route_weather_lora_alert.json"
    cache_root = project_root / "cache" / "cwa-weather-imagery"
    asset_ref = "frames/radar/frame.display.png"
    asset_path = cache_root / asset_ref
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"weather-dashboard-overlay")

    imagery_path = project_root / imagery_ref
    imagery_path.parent.mkdir(parents=True)
    imagery_path.write_text(
        json.dumps(
            {
                "artifactKind": "weatherImageryTimelineManifest",
                "schemaVersion": "weatherImageryTimelineManifest.v1",
                "projectId": "fixture-route",
                "layerId": "cwa-weather",
                "animationWindowsHours": [3, 6, 9, 12],
                "childOverlays": {
                    "radar": {
                        "latestFrameId": "radar.frame.002",
                        "windows": {
                            "3h": ["radar.frame.001", "radar.frame.002"],
                            "6h": ["radar.frame.001", "radar.frame.002"],
                            "9h": ["radar.frame.001", "radar.frame.002"],
                            "12h": ["radar.frame.001", "radar.frame.002"],
                        },
                        "frames": [
                            {
                                "frameId": "radar.frame.001",
                                "sourceTimestamp": "2026-07-11T03:10:00Z",
                                "fetchedAt": "2026-07-11T03:17:00Z",
                                "imageType": "echo_no_terrain",
                                "extent": "taiwan",
                                "expectedDelayMinutes": 12,
                                "assetRef": asset_ref,
                            },
                            {
                                "frameId": "radar.frame.002",
                                "sourceTimestamp": "2026-07-11T03:20:00Z",
                                "fetchedAt": "2026-07-11T03:27:00Z",
                                "imageType": "echo_no_terrain",
                                "extent": "taiwan",
                                "expectedDelayMinutes": 12,
                                "assetRef": asset_ref,
                            },
                        ],
                    },
                    "satellite": {"frames": [], "windows": {}},
                },
                "processingBoundary": {
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                },
            }
        ),
        encoding="utf-8",
    )
    trend_path = project_root / trend_ref
    trend_path.parent.mkdir(parents=True, exist_ok=True)
    trend_path.write_text(
        json.dumps(
            {
                "schemaVersion": "route_precipitation_trend.v1",
                "artifactKind": "route_precipitation_trend",
                "projectId": "fixture-route",
                "status": "ready",
                "evaluatedAt": "2026-07-11T03:30:00Z",
                "currentPosition": {
                    "status": "ready",
                    "past1hMm": 2.0,
                    "next1hMm": 5.0,
                    "trend": "intensifying",
                },
                "target": {
                    "id": "CP-02",
                    "status": "ready",
                    "past1hMm": 4.0,
                    "next1hMm": 9.0,
                    "trend": "intensifying",
                },
                "corridor": {
                    "sampleCount": 12,
                    "coveredRouteSampleCount": 10,
                    "maxPast1hMm": 6.0,
                    "maxNext1hMm": 12.0,
                    "trend": "intensifying",
                },
                "dataDelayMinutes": 10,
                "confidence": 0.78,
                "boundary": {
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                    "rawCoordinatesPersisted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    risk_path = project_root / risk_ref
    risk_path.parent.mkdir(parents=True, exist_ok=True)
    lora_alert = {
        "artifactKind": "routeWeatherLoraAlert",
        "encoding": "json-utf8",
        "encoded": '{"v":1,"t":"wx","b":7,"a":35,"q":82}',
        "byteLength": 43,
        "sent": False,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }
    risk_path.write_text(
        json.dumps(
            {
                "artifact_kind": "route_weather_risk_package",
                "artifactVersion": "route_weather_risk_package.v1",
                "projectId": "fixture-route",
                "routeId": "fixture-route",
                "generatedAt": "2026-07-11T03:30:00Z",
                "status": "candidate_only",
                "imageryFeatures": {
                    "currentRainOnRoute": True,
                    "nearbyStrongEcho": True,
                    "rainBandApproaching": True,
                    "estimatedRainArrivalMinutes": 35,
                    "convectiveCellScore": 0.88,
                    "satelliteConvectiveCloudScore": 0.72,
                    "cloudMotionTowardRoute": None,
                    "dataDelayMinutes": 10,
                    "confidence": 0.82,
                },
                "weatherTerrainInteractions": [
                    {
                        "ruleCode": "THUNDER_RIDGE",
                        "segmentId": "seg.ridge.001",
                        "teii_20m": 91,
                        "weatherConfidence": 0.82,
                        "candidateOnly": True,
                        "runtimeSafetyTruth": False,
                    }
                ],
                "routeBuffer": {
                    "bufferM": 500,
                    "bboxWgs84": {"west": 120, "south": 23, "east": 121, "north": 24},
                },
                "radarFrameCount": 2,
                "satelliteFrameCount": 0,
                "loraAlert": lora_alert,
                "boundary": {
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                    "outboundSendAllowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (project_root / alert_ref).write_text(json.dumps(lora_alert), encoding="utf-8")
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "fixture-route",
                "cwa_weather_imagery_manifest_ref": imagery_ref,
                "cwa_rainfall_route_trend_ref": trend_ref,
                "route_weather_risk_package_ref": risk_ref,
                "route_weather_lora_alert_ref": alert_ref,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "SCOUT_CWA_IMAGERY_CACHE_ROOT",
        str(tmp_path / "legacy-global-cache"),
    )
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            now_factory=lambda: datetime.fromisoformat("2026-07-11T03:30:00+00:00"),
        )
    )

    response = client.get("/admin/pretrip/projects/fixture-route/weather-dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == "weatherDecisionDashboard.v1"
    assert payload["status"] == "partial"
    assert payload["decision"]["candidateDecision"] == "CHANGE_PLAN"
    assert payload["decision"]["humanReviewRequired"] is True
    assert payload["routeRisk"]["imageryFeatures"]["currentRainOnRoute"] is True
    assert payload["routeRisk"]["imageryFeatures"]["estimatedRainArrivalMinutes"] == 35
    assert payload["routeRisk"]["weatherTerrainInteractions"][0]["ruleCode"] == "THUNDER_RIDGE"
    assert payload["routeTrend"]["currentPosition"]["trend"] == "intensifying"
    assert payload["routeTrend"]["target"]["id"] == "CP-02"
    assert payload["loraAlert"]["sent"] is False
    assert payload["loraAlert"]["byteLength"] <= 160
    assert payload["imagery"]["childOverlays"]["radar"]["frames"][0][
        "assetUrl"
    ].endswith("/weather-imagery/radar.frame.001")
    assert payload["processingBoundary"]["upstreamFetchOnRead"] is False
    assert payload["processingBoundary"]["raspberryPiImageProcessing"] is False
    serialized = json.dumps(payload)
    assert "cacheRef" not in serialized
    assert "assetRef" not in serialized
    assert "bboxWgs84" not in serialized
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized

    updated_risk = json.loads(risk_path.read_text(encoding="utf-8"))
    updated_risk["generatedAt"] = "2026-07-11T03:29:00Z"
    updated_risk["imageryFeatures"] = {
        "currentRainOnRoute": False,
        "nearbyStrongEcho": False,
        "rainBandApproaching": False,
        "estimatedRainArrivalMinutes": None,
        "convectiveCellScore": 0.1,
        "satelliteConvectiveCloudScore": 0.1,
        "cloudMotionTowardRoute": False,
        "dataDelayMinutes": 1,
        "confidence": 0.9,
    }
    updated_risk["weatherTerrainInteractions"] = []
    risk_path.write_text(json.dumps(updated_risk), encoding="utf-8")

    reread = client.get("/admin/pretrip/projects/fixture-route/weather-dashboard").json()
    assert reread["routeRisk"]["generatedAt"] == "2026-07-11T03:29:00Z"
    assert reread["routeRisk"]["imageryFeatures"]["currentRainOnRoute"] is False
    assert reread["decision"]["candidateDecision"] == "DELAY"
    assert reread["decision"]["why"] != payload["decision"]["why"]


def test_admin_weather_dashboard_fails_closed_when_cache_is_not_prepared(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "fixture-route"}),
        encoding="utf-8",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.get("/admin/pretrip/projects/fixture-route/weather-dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["decision"]["candidateDecision"] == "DELAY"
    assert payload["decision"]["confidence"] == 0
    assert payload["routeRisk"]["imageryFeatures"] == {
        "currentRainOnRoute": None,
        "nearbyStrongEcho": None,
        "rainBandApproaching": None,
        "estimatedRainArrivalMinutes": None,
        "convectiveCellScore": None,
        "satelliteConvectiveCloudScore": None,
        "cloudMotionTowardRoute": None,
        "dataDelayMinutes": None,
        "confidence": 0,
    }
    assert payload["processingBoundary"]["runtimeSafetyTruth"] is False


def test_weather_dashboard_does_not_emit_go_with_unknown_hazard_classification() -> None:
    decision = _build_weather_dashboard_decision(
        status="ready",
        route_risk={
            "imageryFeatures": {
                "currentRainOnRoute": None,
                "nearbyStrongEcho": False,
                "rainBandApproaching": False,
                "estimatedRainArrivalMinutes": None,
                "convectiveCellScore": 0.1,
                "satelliteConvectiveCloudScore": None,
                "cloudMotionTowardRoute": None,
                "dataDelayMinutes": 5,
                "confidence": 0.9,
            },
            "weatherTerrainInteractions": [],
        },
        route_trend={"status": "ready"},
    )

    assert decision["candidateDecision"] == "DELAY"
    assert "classification" in " ".join(decision["uncertaintyNotes"]).lower()


@pytest.mark.parametrize("point_key,point_status", [
    ("target", "missing_cell"), ("target", "outside_grid"),
    ("currentPosition", "missing_cell"),
])
def test_weather_dashboard_target_missing_qpf_prevents_go_and_explains_unknown(
    point_key: str, point_status: str,
) -> None:
    points = {
        "currentPosition": {"status": "ready", "past1hMm": 10.0, "next1hMm": 37.6},
        "target": {"id": "CP-103", "status": "ready", "past1hMm": 0.0, "next1hMm": 0.0},
    }
    points[point_key] = {**points[point_key], "status": point_status, "next1hMm": None}
    decision = _build_weather_dashboard_decision(
        status="ready",
        route_risk={
            "imageryFeatures": {
                "currentRainOnRoute": False, "nearbyStrongEcho": False,
                "rainBandApproaching": False, "estimatedRainArrivalMinutes": None,
                "convectiveCellScore": 0.1, "satelliteConvectiveCloudScore": 0.1,
                "cloudMotionTowardRoute": False, "dataDelayMinutes": 5, "confidence": 0.9,
            },
            "weatherTerrainInteractions": [],
        },
        route_trend={
            "status": "missing_data",
            **points,
        },
    )
    assert decision["candidateDecision"] == "DELAY"
    assert "CP-103" in decision["where"]
    assert "UNKNOWN" in " ".join(decision["why"])
    assert point_status in " ".join(decision["uncertaintyNotes"])
    assert decision["confidence"] == 0


def test_weather_dashboard_target_zero_qpf_is_not_a_coverage_gap() -> None:
    decision = _build_weather_dashboard_decision(
        status="ready",
        route_risk={
            "imageryFeatures": {
                "currentRainOnRoute": False, "nearbyStrongEcho": False,
                "rainBandApproaching": False, "estimatedRainArrivalMinutes": None,
                "convectiveCellScore": 0.1, "satelliteConvectiveCloudScore": 0.1,
                "cloudMotionTowardRoute": False, "dataDelayMinutes": 5, "confidence": 0.9,
            },
            "weatherTerrainInteractions": [],
        },
        route_trend={
            "status": "ready", "confidence": 0.8,
            "target": {"id": "CP-103", "status": "ready", "past1hMm": 0.0, "next1hMm": 0.0},
            "validWindows": {"next1hQpf": ["2026-09-04T09:40:00+08:00", "2026-09-04T10:40:00+08:00"]},
        },
    )
    assert decision["candidateDecision"] == "GO"
    assert decision["confidence"] == 0.8
    assert "CP-103: past-hour QPE 0 mm; next-hour QPF 0 mm." in decision["why"]
    assert "UNKNOWN" not in " ".join(decision["why"])
    assert "2026-09-04T10:40:00+08:00" in decision["when"]
    assert decision["runtimeSafetyTruth"] is False


@pytest.mark.parametrize("stale_source", [None, "rainfall", "imagery", "trend"])
def test_target_review_replaces_old_trend_freshness_but_checks_consumed_sources(stale_source) -> None:
    from admin_api import _build_weather_decision_dashboard, _build_weather_target_dashboard

    frames = {"qpe_past_1h": "qpe.fixture", "qpf_next_1h": "qpf.fixture"}
    cached = _build_weather_decision_dashboard(
        project_id="fixture-route", evaluated_at="2026-09-04T01:45:00Z",
        rainfall={"status": "ready", "products": [
            {"gridKind": kind, "frameId": frame_id} for kind, frame_id in frames.items()
        ]},
        imagery={"status": "ready", "childOverlays": {"radar": {"frames": [{"frameId": "radar.fixture"}]}}},
        trend={"status": "stale_data"},
        risk={"status": "candidate_only", "imageryFeatures": {
            "currentRainOnRoute": False, "nearbyStrongEcho": False,
            "rainBandApproaching": False, "cloudMotionTowardRoute": False,
            "convectiveCellScore": 0.1, "satelliteConvectiveCloudScore": 0.1,
            "dataDelayMinutes": 5, "confidence": 0.9,
        }},
        alert=None, pair_verification={}, source_refs={},
    )
    assert cached["status"] == "stale_data"
    fresh_trend = {
        "status": "stale_data" if stale_source == "trend" else "ready",
        "confidence": 0.8,
        "target": {"id": "CP-103", "status": "ready", "past1hMm": 4.0, "next1hMm": 4.0},
    }
    if stale_source in {"rainfall", "imagery"}:
        cached = {**cached, stale_source: {**cached[stale_source], "status": "partially_stale"}}
    reviewed = _build_weather_target_dashboard(
        cached=cached, trend=fresh_trend, source_frame_ids=frames,
        source_project={"project_id": "fixture-route"},
    )
    assert reviewed["status"] == ("stale_data" if stale_source else "ready")
    assert reviewed["decision"]["candidateDecision"] == ("DELAY" if stale_source else "GO")
