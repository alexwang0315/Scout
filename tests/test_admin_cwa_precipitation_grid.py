from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import admin_api
from admin_api import create_admin_app
from cwa_precipitation_grid import parse_qpesums_grid
from weather_grid_store import WeatherGridStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "cwa" / "qpesums"


def _freeze_admin_clock(
    monkeypatch: pytest.MonkeyPatch,
    value: datetime,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(admin_api, "datetime", FrozenDateTime)


def _prepare_workspace(tmp_path: Path) -> Path:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    rainfall_root = project_root / "outputs/environment/cwa/rainfall"
    store = WeatherGridStore(rainfall_root)
    grids = []
    for dataset_id in ("O-B0045-001", "F-B0046-001"):
        payload = json.loads((FIXTURE_ROOT / f"{dataset_id}.small.json").read_text())
        grids.append(
            parse_qpesums_grid(
                payload,
                fetched_at="2026-07-13T10:42:00+08:00",
                coordinate_transformer=lambda lat, lon: (lat, lon),
            )
        )
    manifest = store.update_manifest(grids)
    route_ref = "outputs/route/segment_display_geometry.json"
    route_path = project_root / route_ref
    route_path.parent.mkdir(parents=True)
    route_path.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "coordinate_segments": [
                            [
                                {"lat": 23.0, "lon": 121.0},
                                {"lat": 23.0125, "lon": 121.025},
                            ]
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    project = {
        "project_id": "fixture-route",
        "cwa_rainfall_grid_manifest_ref": (
            "outputs/environment/cwa/rainfall/rainfall_grid_manifest.json"
        ),
        "cwa_qpe_numeric_grid_ref": (
            "outputs/environment/cwa/rainfall/"
            + manifest["latestByKind"]["qpe_past_1h"]["dataRef"]
        ),
        "cwa_qpf_numeric_grid_ref": (
            "outputs/environment/cwa/rainfall/"
            + manifest["latestByKind"]["qpf_next_1h"]["dataRef"]
        ),
        "segment_display_geometry_ref": route_ref,
    }
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    return workspace_root


def test_admin_rainfall_grid_manifest_is_cache_only_and_redacted(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_admin_app(pretrip_workspace_root=_prepare_workspace(tmp_path))
    )

    response = client.get("/admin/pretrip/projects/fixture-route/rainfall-grids")
    assert response.status_code == 200
    payload = response.json()
    assert {item["gridKind"] for item in payload["products"]} == {
        "qpe_past_1h",
        "qpf_next_1h",
    }
    serialized = json.dumps(payload)
    assert "values" not in serialized
    assert "dataRef" not in serialized
    assert ".json.gz" not in serialized
    assert payload["processingBoundary"]["upstreamFetchOnRead"] is False
    assert payload["processingBoundary"]["raspberryPiGridProcessing"] is False
    assert payload["status"] in {"partially_stale", "stale_data"}
    freshness_by_kind = {
        item["gridKind"]: item["freshness"]["status"] for item in payload["products"]
    }
    assert freshness_by_kind["qpf_next_1h"] == "stale_data"


def test_rainfall_public_manifest_evaluates_product_freshness_at_read_time(
    tmp_path: Path,
) -> None:
    workspace_root = _prepare_workspace(tmp_path)
    store = WeatherGridStore(
        workspace_root / "fixture-route/outputs/environment/cwa/rainfall"
    )

    partially_stale = store.public_manifest(
        evaluated_at=datetime(2026, 7, 13, 3, 40, tzinfo=timezone.utc)
    )
    assert partially_stale["status"] == "partially_stale"
    assert {
        item["gridKind"]: item["freshness"]["status"]
        for item in partially_stale["products"]
    } == {
        "qpe_past_1h": "current",
        "qpf_next_1h": "stale_data",
    }

    expired = store.public_manifest(
        evaluated_at=datetime(2026, 7, 13, 4, 31, tzinfo=timezone.utc)
    )
    assert expired["status"] == "stale_data"
    assert all(
        item["freshness"]["status"] == "stale_data" for item in expired["products"]
    )


def test_admin_position_target_rainfall_trend_is_compact_and_does_not_persist_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_admin_clock(
        monkeypatch,
        datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc),
    )
    workspace_root = _prepare_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.post(
        "/admin/pretrip/projects/fixture-route/rainfall-trend",
        json={
            "currentPosition": {
                "lat": 23.0,
                "lon": 121.0,
                "observedAt": "2026-07-13T10:40:00+08:00",
                "accuracyM": 15,
            },
            "targetPosition": {"lat": 23.0125, "lon": 121.025, "id": "CP-02"},
            "confirmLocationAccess": True,
            "locationApprovalReference": "approval.test.001",
            "locationApprovedAt": "2026-07-13T10:39:00+08:00",
            "locationApprovalScope": "current_trip_rainfall_sampling",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPosition"]["past1hMm"] == 1.0
    assert payload["target"]["next1hMm"] == 24.0
    serialized = json.dumps(payload)
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized
    assert "values" not in serialized
    assert payload["boundary"]["rawCoordinatesPersisted"] is False
    assert payload["locationApproval"]["reference"] == "approval.test.001"
    audit_path = (
        workspace_root / "fixture-route" / payload["locationApproval"]["auditRef"]
    )
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "approval.test.001" in audit_text
    assert '"lat"' not in audit_text
    assert '"lon"' not in audit_text

    invalid = client.post(
        "/admin/pretrip/projects/fixture-route/rainfall-trend",
        json={
            "currentPosition": {
                "lat": 123,
                "lon": 121,
                "observedAt": "2026-07-13T10:40:00+08:00",
            },
            "targetPosition": {"lat": 23, "lon": 121, "id": "CP-02"},
            "confirmLocationAccess": True,
            "locationApprovalReference": "approval.test.001",
            "locationApprovedAt": "2026-07-13T10:39:00+08:00",
            "locationApprovalScope": "current_trip_rainfall_sampling",
        },
    )
    assert invalid.status_code == 422

    missing_approval = client.post(
        "/admin/pretrip/projects/fixture-route/rainfall-trend",
        json={
            "currentPosition": {
                "lat": 23,
                "lon": 121,
                "observedAt": "2026-07-13T10:40:00+08:00",
            },
            "targetPosition": {"lat": 23, "lon": 121, "id": "CP-02"},
        },
    )
    assert missing_approval.status_code == 422


def test_admin_rainfall_endpoints_reject_unsafe_or_wrong_project_ids(
    tmp_path: Path,
) -> None:
    workspace_root = _prepare_workspace(tmp_path)
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    assert client.get("/admin/pretrip/projects/../rainfall-grids").status_code in {
        404,
        422,
    }
    direct_client = TestClient(
        create_admin_app(pretrip_workspace_root=workspace_root / "fixture-route")
    )
    assert (
        direct_client.get(
            "/admin/pretrip/projects/another-project/rainfall-grids"
        ).status_code
        == 404
    )


def test_weather_imagery_manifest_project_id_must_match_requested_project(
    tmp_path: Path,
) -> None:
    workspace_root = _prepare_workspace(tmp_path)
    project_root = workspace_root / "fixture-route"
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    manifest_ref = "outputs/environment/cwa/imagery/weather_imagery_manifest.json"
    project["cwa_weather_imagery_manifest_ref"] = manifest_ref
    project_path.write_text(json.dumps(project), encoding="utf-8")
    manifest_path = project_root / manifest_ref
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "artifactKind": "weatherImageryTimelineManifest",
                "schemaVersion": "weatherImageryTimelineManifest.v1",
                "projectId": "legacy-project",
                "layerId": "cwa-weather",
                "status": "ready",
                "animationWindowsHours": [3, 6, 9, 12],
                "childOverlays": {
                    "radar": {"frames": [], "windows": {}},
                    "satellite": {"frames": [], "windows": {}},
                },
                "processingBoundary": {
                    "adminReadIsCacheOnly": True,
                    "upstreamFetchOnRead": False,
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                },
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_admin_app(pretrip_workspace_root=workspace_root))

    response = client.get(
        "/admin/pretrip/projects/fixture-route/weather-imagery"
    )

    assert response.status_code == 422
    assert "project" in response.json()["detail"].lower()


def test_location_approval_validation_uses_injected_clock(tmp_path: Path) -> None:
    workspace_root = _prepare_workspace(tmp_path)
    fixed_now = datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc)
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            now_factory=lambda: fixed_now,
        )
    )

    response = client.post(
        "/admin/pretrip/projects/fixture-route/rainfall-trend",
        json={
            "currentPosition": {
                "lat": 23.0,
                "lon": 121.0,
                "observedAt": "2026-07-13T10:40:00+08:00",
                "accuracyM": 15,
            },
            "targetPosition": {"lat": 23.0125, "lon": 121.025, "id": "CP-02"},
            "confirmLocationAccess": True,
            "locationApprovalReference": "approval.test.clock",
            "locationApprovedAt": "2026-07-13T10:59:00+08:00",
            "locationApprovalScope": "current_trip_rainfall_sampling",
        },
    )

    assert response.status_code == 200
    assert response.json()["evaluatedAt"] == fixed_now.isoformat()
