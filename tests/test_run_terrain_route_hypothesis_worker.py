from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from qgis_spatial_contracts import SpatialWorkflowState
from qgis_worker_contracts import QgisWorkerResult, QgisWorkerRun
from terrain_route_guidance import (
    TerrainGuidanceCostModifier,
    TerrainGuidanceCostModifierKind,
    TerrainGuidanceConstraintKind,
    TerrainGuidanceExecutionAnchor,
    TerrainGuidanceExecutionPlan,
    TerrainGuidanceLandform,
    TerrainGuidanceResolutionStatus,
    TerrainGuidanceReviewDecision,
    TerrainGuidanceReviewDecisionKind,
    TerrainGuidanceRoutingEffect,
)
from terrain_route_hypothesis_models import GeoPoint, TerrainRoutingCostConfig
from tools.run_terrain_route_hypothesis_worker import (
    TerrainRouteWorkerError,
    _input_contract_receipt_fields,
    build_execution_receipt,
    build_worker_request,
    load_guidance_execution_plan,
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


def _write_guidance_execution_plan(
    path: Path,
    *,
    dem_sha256: str,
    dem_resolution_m: float = 20.0,
    anchor: tuple[float, float] = (121.24, 23.347),
) -> TerrainGuidanceExecutionPlan:
    plan = TerrainGuidanceExecutionPlan(
        guidance_id="terrain-guidance-portable-demo",
        review_id="terrain-guidance-review-portable-demo",
        guidance_review_sha256="a" * 64,
        plan_sha256="b" * 64,
        resolution_sha256="c" * 64,
        feature_index_sha256="d" * 64,
        dem_sha256=dem_sha256,
        dem_resolution_m=dem_resolution_m,
        dem_crs="EPSG:3826",
        reviewed_by="dashboard_operator",
        reviewed_at="2026-09-01T00:00:00Z",
        review_decisions=[
            TerrainGuidanceReviewDecision(
                constraint_id="G1",
                sequence_index=0,
                resolver_status_before_review=TerrainGuidanceResolutionStatus.RESOLVED,
                resolver_candidate_feature_ids=["manual-g1"],
                human_selected_feature_id="manual-g1",
                selected_feature_source="human_map_annotation",
                decision_kind=(
                    TerrainGuidanceReviewDecisionKind.HUMAN_MAP_ANCHOR_CONFIRMED
                ),
                differs_from_ai_map_selection=True,
            )
        ],
        anchors=[
            TerrainGuidanceExecutionAnchor(
                constraint_id="G1",
                sequence_index=0,
                kind=TerrainGuidanceConstraintKind.ORDERED_ANCHOR,
                landform=TerrainGuidanceLandform.SADDLE,
                routing_effect=TerrainGuidanceRoutingEffect.ORDERED_GATE,
                required_anchor=True,
                feature_id="manual-g1",
                point=GeoPoint(x=anchor[0], y=anchor[1], crs="EPSG:4326"),
                source_layer="dashboard_human_map_annotations",
                source_layer_sha256="e" * 64,
            )
        ],
        cost_modifiers=[
            TerrainGuidanceCostModifier(
                constraint_id="G1",
                sequence_index=0,
                modifier_kind=TerrainGuidanceCostModifierKind.RIDGE_LOCAL_PREFERENCE,
                influence_radius_m=100,
                minimum_friction_multiplier=0.78,
            )
        ],
    )
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return plan


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


def test_build_worker_request_cache_identity_is_host_path_independent(
    tmp_path: Path,
) -> None:
    requests = []
    for host_name in ("mac", "scout"):
        root = tmp_path / host_name
        root.mkdir()
        dem = root / "terrain.tif"
        dem.write_bytes(b"same-dem-on-both-hosts")
        manifest = root / "terrain_feature_manifest.json"
        _write_parent_manifest(manifest, dem_name=dem.name)
        requests.append(
            build_worker_request(
                project_id="iroko-local",
                request_id=f"iroko-local.{host_name}",
                requested_by="pytest",
                dem_path=dem,
                parent_manifest_path=manifest,
                dem_resolution_m=20.0,
                start=(121.25, 23.34),
                destination=(121.23, 23.35),
                corridor_m=500.0,
            )
        )

    assert (
        requests[0].terrain_route_cache_keys
        == requests[1].terrain_route_cache_keys
    )
    assert (
        _input_contract_receipt_fields(requests[0])["input_contract_sha256"]
        == _input_contract_receipt_fields(requests[1])["input_contract_sha256"]
    )


def test_build_worker_request_binds_reviewed_r4_plan_without_raw_narrative(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"deterministic-dem-fixture")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    plan_path = tmp_path / "terrain_guidance_execution_plan.json"
    plan = _write_guidance_execution_plan(
        plan_path,
        dem_sha256=hashlib.sha256(dem.read_bytes()).hexdigest(),
    )

    baseline = build_worker_request(
        project_id="iroko-local",
        request_id="iroko-local.baseline",
        requested_by="pytest",
        dem_path=dem,
        parent_manifest_path=manifest,
        dem_resolution_m=20.0,
        start=(121.25622601185889, 23.3445199857792),
        destination=(121.23041872103398, 23.352571034657494),
        corridor_m=500.0,
    )
    guided = build_worker_request(
        project_id="iroko-local",
        request_id="iroko-local.guided",
        requested_by="pytest",
        dem_path=dem,
        parent_manifest_path=manifest,
        dem_resolution_m=20.0,
        start=(121.25622601185889, 23.3445199857792),
        destination=(121.23041872103398, 23.352571034657494),
        corridor_m=500.0,
        guidance_execution_plan_path=plan_path,
    )

    assert guided.route_geojson["features"][0]["geometry"]["coordinates"] == [
        [121.25622601185889, 23.3445199857792],
        [121.24, 23.347],
        [121.23041872103398, 23.352571034657494],
    ]
    assert guided.terrain_route_guidance_execution_plan == plan
    assert guided.source_hashes[str(plan_path.resolve())]
    assert guided.terrain_route_cache_keys is not None
    assert baseline.terrain_route_cache_keys is not None
    assert (
        guided.terrain_route_cache_keys.derived_terrain
        == baseline.terrain_route_cache_keys.derived_terrain
    )
    assert (
        guided.terrain_route_cache_keys.friction
        == baseline.terrain_route_cache_keys.friction
    )
    assert (
        guided.terrain_route_cache_keys.cost_raster
        != baseline.terrain_route_cache_keys.cost_raster
    )
    assert "narrative" not in guided.model_dump_json()


def test_build_worker_request_rejects_guidance_for_different_dem(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    plan_path = tmp_path / "terrain_guidance_execution_plan.json"
    _write_guidance_execution_plan(plan_path, dem_sha256="f" * 64)

    with pytest.raises(TerrainRouteWorkerError, match="different DEM"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.guidance-dem-mismatch",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
            guidance_execution_plan_path=plan_path,
        )


def test_build_worker_request_rejects_guidance_anchor_equal_to_endpoint(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    plan_path = tmp_path / "terrain_guidance_execution_plan.json"
    _write_guidance_execution_plan(
        plan_path,
        dem_sha256=hashlib.sha256(dem.read_bytes()).hexdigest(),
        anchor=(121.25, 23.34),
    )

    with pytest.raises(TerrainRouteWorkerError, match="distinct from A, B"):
        build_worker_request(
            project_id="iroko-local",
            request_id="iroko-local.guidance-duplicate-anchor",
            requested_by="pytest",
            dem_path=dem,
            parent_manifest_path=manifest,
            dem_resolution_m=20.0,
            start=(121.25, 23.34),
            destination=(121.23, 23.35),
            corridor_m=500.0,
            guidance_execution_plan_path=plan_path,
        )


def test_load_guidance_execution_plan_rejects_raw_narrative(tmp_path: Path) -> None:
    plan_path = tmp_path / "terrain_guidance_execution_plan.json"
    _write_guidance_execution_plan(plan_path, dem_sha256="f" * 64)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["raw_narrative"] = "must never reach the GIS worker"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="raw_narrative"):
        load_guidance_execution_plan(plan_path)


def test_execution_receipt_records_reviewed_r4_without_promoting_authority(
    tmp_path: Path,
) -> None:
    dem = tmp_path / "terrain.tif"
    dem.write_bytes(b"dem")
    manifest = tmp_path / "terrain_feature_manifest.json"
    _write_parent_manifest(manifest, dem_name=dem.name)
    plan_path = tmp_path / "terrain_guidance_execution_plan.json"
    _write_guidance_execution_plan(
        plan_path,
        dem_sha256=hashlib.sha256(dem.read_bytes()).hexdigest(),
    )
    request = build_worker_request(
        project_id="iroko-local",
        request_id="iroko-local.guided-receipt",
        requested_by="pytest",
        dem_path=dem,
        parent_manifest_path=manifest,
        dem_resolution_m=20.0,
        start=(121.25, 23.34),
        destination=(121.23, 23.35),
        corridor_m=500.0,
        guidance_execution_plan_path=plan_path,
    )
    run = QgisWorkerRun(
        worker_run_id="qgis-worker-guided-receipt",
        project_id="iroko-local",
        workflow_id="terrain_route_hypothesis.v1",
        request_id=request.request_id,
        requested_by="pytest",
        state=SpatialWorkflowState.COMPLETED,
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:01:00Z",
        completed_at="2026-09-01T00:01:00Z",
        result=QgisWorkerResult(
            maplibre_geojson={"type": "FeatureCollection", "features": []},
            artifacts=[],
            qgis_version="3.44.13",
            processing_algorithms=["grass:r.walk.coords", "grass:r.path"],
        ),
    )

    receipt = build_execution_receipt(
        run=run,
        duration_s=60.0,
        worker_root=tmp_path / "worker",
        request=request,
    )

    assert receipt["guided_hypothesis_id"] == "R4"
    assert receipt["guidance_review_sha256"] == "a" * 64
    assert receipt["human_reviewed_interpretation_binding"] is True
    assert receipt["source_dem_sha256s"] == [hashlib.sha256(b"dem").hexdigest()]
    assert receipt["terrain_parent_manifest_sha256"] == hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert len(receipt["input_contract_sha256"]) == 64
    assert receipt["authority"] == "candidate_only"
    assert receipt["runtime_safety_truth"] is False
    assert receipt["safe_or_walkable"] == "not_determined"


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
