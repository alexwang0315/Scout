from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from terrain_route_hypothesis_models import TerrainRoutingCostConfig
from tools.run_terrain_route_hypothesis_worker import (
    TerrainRouteWorkerError,
    build_worker_request,
    parse_wgs84_point,
    resolve_qgis_mcp_server_root,
)


def _write_parent_manifest(
    path: Path,
    *,
    dem_name: str,
    candidate_only: bool = True,
) -> None:
    path.write_text(
        """{
  "artifacts": {"dem_route_bbox": "%s"},
  "candidate_only": %s,
  "operational": false,
  "parameters": {"analysis_extent": {"resolution_m": 20.0}},
  "runtime_safety_truth": false,
  "source_resolution": {
    "adds_source_resolution": false,
    "crs": "EPSG:3826",
    "status": "reported",
    "x_m": 20.0,
    "y_m": 20.0
  }
}
"""
        % (dem_name, str(candidate_only).lower()),
        encoding="utf-8",
    )


def _request(tmp_path: Path):
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"deterministic-dem-fixture")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    return build_worker_request(
        project_id="iroko-local",
        request_id="iroko-local.20260831",
        requested_by="pytest",
        dem_path=dem,
        parent_manifest_path=manifest,
        dem_resolution_m=20.0,
        start=(121.25622601185889, 23.3445199857792),
        destination=(121.23041872103398, 23.352571034657494),
        corridor_m=500.0,
        cost_config=TerrainRoutingCostConfig(),
    )


def test_build_worker_request_is_candidate_only_and_uses_two_arbitrary_points(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    assert request.workflow_id == "terrain_route_hypothesis.v1"
    assert request.candidate_only is True
    assert request.runtime_safety_truth is False
    assert request.operational is False
    feature = request.route_geojson["features"][0]
    assert feature["geometry"]["coordinates"] == [
        [121.25622601185889, 23.3445199857792],
        [121.23041872103398, 23.352571034657494],
    ]
    assert feature["properties"] == {
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
    }
    assert request.terrain_route_cache_keys is not None


def test_build_worker_request_is_deterministic_for_same_inputs(tmp_path: Path) -> None:
    first = _request(tmp_path)
    second = _request(tmp_path)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_build_worker_request_fails_closed_for_missing_dem(tmp_path: Path) -> None:
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name="missing.tif")
    with pytest.raises(FileNotFoundError):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.missing-dem",
            requested_by="pytest",
            dem_path=tmp_path / "missing.tif",
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
        )


def test_build_worker_request_rejects_coincident_endpoints(tmp_path: Path) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    with pytest.raises(TerrainRouteWorkerError, match="must differ"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.same-endpoint",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.25, 23.34),
            corridor_m=500.0,
        )


def test_build_worker_request_requires_exact_parent_manifest_name(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    wrong_manifest = tmp_path / "manifest.json"
    _write_parent_manifest(wrong_manifest, dem_name=dem.name)

    with pytest.raises(TerrainRouteWorkerError, match="immutable DEM parent"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.bad-parent",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=wrong_manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
        )


def test_build_worker_request_rejects_parent_manifest_dem_mismatch(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name="different-dem.tif")

    with pytest.raises(TerrainRouteWorkerError, match="does not bind"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.parent-mismatch",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
        )


def test_build_worker_request_rejects_promoted_parent_manifest(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name, candidate_only=False)

    with pytest.raises(TerrainRouteWorkerError, match="does not bind"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.parent-promoted",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("121.25,23.34", (121.25, 23.34)),
        (" 121.25 , 23.34 ", (121.25, 23.34)),
    ],
)
def test_parse_wgs84_point(value: str, expected: tuple[float, float]) -> None:
    assert parse_wgs84_point(value) == expected


def test_runner_help_works_outside_repository_root(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "run_terrain_route_hypothesis_worker.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "candidate-only A/B terrain route hypothesis" in completed.stdout


def test_resolve_qgis_mcp_server_root_uses_explicit_portable_path(
    tmp_path: Path,
) -> None:
    server_root = tmp_path / "qgis_agent_mcp" / "_server"
    (server_root / "qgis_mcp").mkdir(parents=True)

    assert resolve_qgis_mcp_server_root(server_root) == server_root.resolve()


def test_resolve_qgis_mcp_server_root_uses_environment_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_root = tmp_path / "mac-profile" / "qgis_agent_mcp" / "_server"
    (server_root / "qgis_mcp").mkdir(parents=True)
    monkeypatch.setenv("SCOUT_QGIS_MCP_PYTHONPATH", str(server_root))

    assert resolve_qgis_mcp_server_root() == server_root.resolve()


def test_resolve_qgis_mcp_server_root_fails_closed_for_missing_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(TerrainRouteWorkerError, match="server package is unavailable"):
        resolve_qgis_mcp_server_root(tmp_path / "missing")
