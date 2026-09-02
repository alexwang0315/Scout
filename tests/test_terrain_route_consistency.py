from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

import admin_api
from admin_api import create_admin_app
from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_tool_contracts import default_tool_contracts
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_terrain_route_hypothesis_tool import (
    TERRAIN_ROUTE_COMPARE_OUTPUT_KIND,
    TERRAIN_ROUTE_COMPARE_TOOL_ID,
    TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND,
    TERRAIN_ROUTE_CONSISTENCY_TOOL_ID,
    TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND,
    TERRAIN_ROUTE_EXPLAIN_TOOL_ID,
    TERRAIN_ROUTE_GENERATE_OUTPUT_KIND,
    TERRAIN_ROUTE_GENERATE_TOOL_ID,
    compare_scout_terrain_route_hypotheses,
    explain_scout_terrain_route_hypothesis,
    inspect_scout_route_terrain_consistency,
)
from terrain_route_consistency import (
    GpxTerrainConsistency,
    TerrainConsistencySample,
    TerrainRouteConsistencyRequest,
    evaluate_terrain_route_consistency,
)
from terrain_route_hypothesis_models import TerrainRouteHypothesisRun
from qgis_spatial_contracts import SpatialWorkflowRun


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sample(
    *,
    inside: bool | None = True,
    deviation_m: float | None = 5.0,
    slope: float | None = 12.0,
    drainage: float | None = 0.0,
    teii: float | None = None,
) -> TerrainConsistencySample:
    return TerrainConsistencySample(
        lon=121.0,
        lat=23.0,
        inside_candidate_corridor=inside,
        deviation_from_hypothesis_m=deviation_m,
        slope_degrees=slope,
        drainage_pressure=drainage,
        teii=teii,
    )


def _request(
    samples: list[TerrainConsistencySample],
) -> TerrainRouteConsistencyRequest:
    return TerrainRouteConsistencyRequest(
        known_gpx_id="known-gpx-1",
        known_gpx_sha256="a" * 64,
        terrain_hypothesis_id="terrain-route-hypothesis-r1-test",
        terrain_hypothesis_sha256="b" * 64,
        dem_resolution_m=20.0,
        samples=samples,
    )


def test_gpx_consistency_is_typed_candidate_evidence_not_gpx_validity() -> None:
    result = evaluate_terrain_route_consistency(
        _request([_sample(), _sample(slope=19.0), _sample(deviation_m=12.0)])
    )

    assert result.terrain_consistency is GpxTerrainConsistency.CONSISTENT
    assert result.assessment_semantics == "terrain_consistency_not_gpx_validity"
    assert result.known_gpx_mutated is False
    assert result.authority.value == "candidate_only"
    assert result.source_type.value == "known_gpx"
    assert result.runtime_safety_truth is False
    assert result.safe_or_walkable == "not_determined"
    assert result.boundary.promotion_allowed is False


def test_gpx_mismatch_preserves_multiple_possible_explanations() -> None:
    result = evaluate_terrain_route_consistency(
        _request(
            [
                _sample(inside=False, deviation_m=140.0, slope=43.0),
                _sample(inside=False, deviation_m=165.0, slope=46.0, drainage=8.0),
                _sample(inside=True, deviation_m=20.0, slope=18.0),
            ]
        )
    )

    assert result.terrain_consistency is GpxTerrainConsistency.TERRAIN_ANOMALY
    assert {item.code for item in result.observations} >= {
        "gpx_exits_candidate_corridor",
        "gpx_crosses_extreme_slope_cell",
        "gpx_enters_dem_drainage_pressure",
    }
    assert set(result.possible_explanations) >= {
        "gps_drift",
        "dem_error",
        "official_engineered_trail",
        "rope_route",
        "bridge",
        "tunnel",
        "old_route",
        "landslide",
        "historical_trail",
        "data_mismatch",
    }
    assert "invalid" not in result.summary.casefold()


def test_missing_evidence_is_unknown_and_deterministic() -> None:
    request = _request([_sample(inside=None, deviation_m=None, slope=None, drainage=None)])

    first = evaluate_terrain_route_consistency(request)
    second = evaluate_terrain_route_consistency(request)

    assert first == second
    assert first.terrain_consistency is GpxTerrainConsistency.UNKNOWN
    assert first.status == "unavailable"
    assert "terrain_evidence_unavailable" in {item.code for item in first.unknowns}


def test_consistency_contract_rejects_authority_promotion() -> None:
    result = evaluate_terrain_route_consistency(_request([_sample()]))
    payload = result.model_dump(mode="json")

    with pytest.raises(ValidationError):
        type(result).model_validate({**payload, "authority": "human_verified"})
    with pytest.raises(ValidationError):
        type(result).model_validate({**payload, "safe_or_walkable": "safe"})


class _FakeRasterSampler:
    backend_id = "fake_raster_sampler.v0"

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]:
        values = {
            "terrain_route_top_10_percent_corridor.tif": (1.0, 1.0, 0.0),
            "terrain_route_slope.tif": (12.0, 18.0, 44.0),
            "terrain_route_drainage_pressure.tif": (0.0, 0.0, 3.0),
        }
        return values[raster_path.name][: len(points_wgs84)]


def _metrics(relative_cost: float, distance_m: float) -> dict[str, object]:
    return {
        "relative_score": None,
        "relative_cost": relative_cost,
        "distance_m": distance_m,
        "elevation_gain_m": 120.0,
        "elevation_loss_m": 80.0,
        "max_slope_degrees": 44.0,
        "median_slope_degrees": 18.0,
        "high_cost_fraction": 0.1,
        "ridge_fraction": None,
        "valley_fraction": None,
        "drainage_pressure_fraction": 0.1,
        "high_drainage_pressure_fraction": 0.0,
        "teii_stats": {},
    }


def _hypothesis(
    candidate: str,
    index: int,
    strategy: str,
    drainage_multiplier: float,
    *,
    corridor_sha: str | None,
) -> dict[str, object]:
    corridor = None
    if corridor_sha is not None:
        corridor = {
            "bands": [
                {
                    "name": "top_10_percent_corridor",
                    "percentile": 10.0,
                    "max_relative_corridor_cost": 4.0,
                    "cell_count": 3,
                    "sampled_cells": [],
                    "contains_best_path": True,
                    "raster_ref": {
                        "artifact_ref": (
                            "outputs/spatial/qgis/cache/"
                            "terrain_route_top_10_percent_corridor.tif"
                        ),
                        "sha256": corridor_sha,
                        "media_type": "image/tiff",
                        "crs": "EPSG:3826",
                        "bbox_wgs84": {
                            "west": 120.99,
                            "south": 22.99,
                            "east": 121.01,
                            "north": 23.01,
                        },
                    },
                }
            ]
        }
    return {
        "id": f"terrain-route-hypothesis-{candidate.lower()}-test",
        "label": f"{candidate} terrain hypothesis",
        "alternative_index": index,
        "strategy": strategy,
        "drainage_penalty_multiplier": drainage_multiplier,
        "start": {"x": 121.0, "y": 23.0, "crs": "EPSG:4326", "label": "A"},
        "destination": {
            "x": 121.002,
            "y": 23.002,
            "crs": "EPSG:4326",
            "label": "B",
        },
        "best_path": {
            "coordinates": [[121.0, 23.0], [121.001, 23.001], [121.002, 23.002]],
            "crs": "EPSG:4326",
        },
        "corridor": corridor,
        "score": None,
        "metrics": _metrics(1000.0 + index * 100.0, 300.0 + index),
        "reasons": [
            {
                "code": "moderate_slope",
                "polarity": "positive",
                "description": "Candidate trace has moderate DEM slope evidence.",
            },
            {
                "code": "steep_slope",
                "polarity": "negative",
                "description": "Candidate trace includes a high terrain-cost slope cell.",
            },
        ],
        "unknowns": [
            {
                "code": "vegetation_unknown",
                "description": "Vegetation is not represented by this DEM evidence.",
            }
        ],
        "dem_resolution_m": 20.0,
        "resolution_class": "macro_terrain_only",
        "confidence_limits": ["20 m DEM is macro terrain evidence only."],
        "cost_model_version": "terrain_routing_cost.v0_2",
        "provenance": {
            "dem_dataset_id": "dem-1",
            "dem_sha256": "d" * 64,
            "dem_resolution_m": 20.0,
            "dem_crs": "EPSG:3826",
            "dem_extent": {"x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100},
            "input_endpoints": {},
            "cost_model_version": "terrain_routing_cost.v0_2",
            "weights": {"slope_weight": 1.0},
            "weights_hash": "e" * 64,
            "grass_version": "8.5.0",
            "qgis_version": "3.44.13",
            "backend_id": "test",
            "modules_executed": ["grass:r.walk.coords", "grass:r.path"],
            "timestamp": "2026-09-01T00:00:00Z",
            "algorithm_version": "terrain_route_hypothesis.v0_3",
            "processing_manifest": {},
            "cache_key": "f" * 64,
        },
    }


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    cache = tmp_path / "outputs" / "spatial" / "qgis" / "cache"
    cache.mkdir(parents=True)
    corridor_raw = b"corridor-raster"
    (cache / "terrain_route_top_10_percent_corridor.tif").write_bytes(corridor_raw)
    (cache / "terrain_route_slope.tif").write_bytes(b"slope-raster")
    (cache / "terrain_route_drainage_pressure.tif").write_bytes(b"drainage-raster")
    run = TerrainRouteHypothesisRun.model_validate(
        {
            "status": "completed",
            "created_at": "2026-09-01T00:00:00Z",
            "hypotheses": [
                _hypothesis(
                    "R1",
                    1,
                    "drainage_averse",
                    4.0,
                    corridor_sha=_sha(corridor_raw),
                ),
                _hypothesis("R2", 2, "balanced", 1.5, corridor_sha=None),
                _hypothesis(
                    "R3",
                    3,
                    "terrain_only_baseline",
                    0.0,
                    corridor_sha=None,
                ),
            ],
        }
    )
    hypothesis_raw = run.model_dump_json(indent=2).encode()
    hypothesis_ref = "outputs/spatial/qgis/cache/terrain_route_hypothesis.json"
    (tmp_path / hypothesis_ref).write_bytes(hypothesis_raw)
    gpx_ref = "inbox/gpx/reference.gpx"
    gpx_path = tmp_path / gpx_ref
    gpx_path.parent.mkdir(parents=True)
    gpx_path.write_text(
        """<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="23.0000" lon="121.0000"/>
    <trkpt lat="23.0010" lon="121.0010"/>
    <trkpt lat="23.0020" lon="121.0020"/>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )
    gpx_sha256 = _sha(gpx_path.read_bytes())
    gpx_index_ref = "sources/historical_gpx_source_index.json"
    gpx_index_path = tmp_path / gpx_index_ref
    gpx_index_path.parent.mkdir(parents=True)
    gpx_index_path.write_text(
        json.dumps(
            {
                "artifact_kind": "historical_gpx_source_index",
                "boundary": {
                    "pretrip_candidate_evidence_only": True,
                    "runtime_safety_truth": False,
                },
                "sources": [
                    {
                        "role": "golden_route_reference",
                        "workspace_ref": gpx_ref,
                        "sha256": gpx_sha256,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "project_id": "test-project",
                "terrain_route_hypothesis_ref": hypothesis_ref,
                "terrain_route_hypothesis_sha256": _sha(hypothesis_raw),
                "terrain_route_hypothesis_candidate_only": True,
                "terrain_route_hypothesis_runtime_safety_truth": False,
                "historical_gpx_source_index_ref": gpx_index_ref,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, gpx_ref


def test_workspace_tools_explain_compare_and_inspect_without_promoting_truth(
    tmp_path: Path,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)

    explanation = explain_scout_terrain_route_hypothesis(
        project_root,
        candidate_id="R1",
    )
    comparison = compare_scout_terrain_route_hypotheses(project_root)
    consistency = inspect_scout_route_terrain_consistency(
        project_root,
        gpx_path=gpx_ref,
        candidate_id="R1",
        raster_sampler=_FakeRasterSampler(),
    )

    assert explanation["candidate"] == "R1"
    assert explanation["positive_evidence"] == ["moderate_slope"]
    assert explanation["negative_evidence"] == ["steep_slope"]
    assert explanation["unknowns"] == ["vegetation_unknown"]
    assert explanation["candidate_only"] is True
    assert explanation["runtime_safety_truth"] is False

    assert [item["candidate"] for item in comparison["hypotheses"]] == [
        "R1",
        "R2",
        "R3",
    ]
    assert comparison["safety_ranking_performed"] is False
    assert comparison["cross_profile_cost_ranking_performed"] is False

    assert consistency["terrain_consistency"] == "partially_consistent"
    assert consistency["known_gpx_mutated"] is False
    assert consistency["candidate_only"] is True
    assert consistency["runtime_safety_truth"] is False
    assert consistency["provenance"]["raster_sampler_backend"] == (
        "fake_raster_sampler.v0"
    )
    assert len(consistency["sample_evidence"]["features"]) == 1
    sample_properties = consistency["sample_evidence"]["features"][0]["properties"]
    assert sample_properties["source_type"] == "known_gpx"
    assert sample_properties["gpx_validity_determined"] is False


def test_explain_guided_r4_reports_reviewed_anchor_alignment_and_conflicts(
    tmp_path: Path,
) -> None:
    project_root, _gpx_ref = _workspace(tmp_path)
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text())
    hypothesis_path = project_root / project["terrain_route_hypothesis_ref"]
    run_payload = json.loads(hypothesis_path.read_text())
    guided = _hypothesis(
        "R4",
        4,
        "historical_narrative_guided",
        1.5,
        corridor_sha=None,
    )
    guided["provenance"]["processing_manifest"] = {
        "guidance_execution": {
            "guidance_id": "terrain-guidance-demo",
            "guidance_review_sha256": "a" * 64,
            "cost_model_version": "reviewed_local_cost_preferences.v0_1",
            "anchors": [
                {
                    "constraint_id": "G1",
                    "sequence_index": 0,
                    "point": {"x": 121.001, "y": 23.001, "crs": "EPSG:4326"},
                    "selection_source": "human_map_annotation",
                },
                {
                    "constraint_id": "G2",
                    "sequence_index": 1,
                    "point": {"x": 121.1, "y": 23.1, "crs": "EPSG:4326"},
                    "selection_source": "human_map_annotation",
                },
            ],
            "cost_modifiers": [
                {"constraint_id": "G1"},
                {"constraint_id": "G2"},
            ],
            "review_decision_count": 3,
            "review_decisions": [
                {
                    "constraint_id": "G1",
                    "ai_map_selection_performed": False,
                    "human_selected_feature_id": "manual-g1",
                },
                {
                    "constraint_id": "G2",
                    "ai_map_selection_performed": False,
                    "human_selected_feature_id": "manual-g2",
                },
                {
                    "constraint_id": "G3",
                    "ai_map_selection_performed": False,
                    "human_selected_feature_id": None,
                },
            ],
            "disabled_constraint_ids": ["G3"],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
            "raw_narrative_forwarded_to_worker": False,
        }
    }
    run_payload["hypotheses"].append(guided)
    run = TerrainRouteHypothesisRun.model_validate(run_payload)
    hypothesis_raw = run.model_dump_json(indent=2).encode()
    hypothesis_path.write_bytes(hypothesis_raw)
    project["terrain_route_hypothesis_sha256"] = _sha(hypothesis_raw)
    project_path.write_text(json.dumps(project))

    explanation = explain_scout_terrain_route_hypothesis(
        project_root,
        candidate_id="R4",
    )

    assessment = explanation["guidance_assessment"]
    assert assessment["status"] == "conflict"
    assert assessment["aligned_constraint_ids"] == ["G1"]
    assert assessment["conflicting_constraint_ids"] == ["G2"]
    assert assessment["disabled_constraint_ids"] == ["G3"]
    assert assessment["raw_narrative_forwarded_to_worker"] is False
    assert assessment["review_decision_count"] == 3
    assert assessment["ai_map_selection_performed"] is False
    assert assessment["candidate_only"] is True
    assert assessment["runtime_safety_truth"] is False
    assert assessment["safe_or_walkable"] == "not_determined"


def test_workspace_inspection_fails_closed_on_stale_hypothesis_hash(
    tmp_path: Path,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)
    project = json.loads((project_root / "project.json").read_text())
    project["terrain_route_hypothesis_sha256"] = "0" * 64
    (project_root / "project.json").write_text(json.dumps(project))

    result = inspect_scout_route_terrain_consistency(
        project_root,
        gpx_path=gpx_ref,
        raster_sampler=_FakeRasterSampler(),
    )

    assert result["status"] == "unavailable"
    assert result["terrain_consistency"] == "unknown"
    assert result["failure_code"] == "hypothesis_hash_mismatch"
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False


def test_missing_optional_drainage_raster_is_preserved_as_unknown(
    tmp_path: Path,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)
    (
        project_root
        / "outputs/spatial/qgis/cache/terrain_route_drainage_pressure.tif"
    ).unlink()

    result = inspect_scout_route_terrain_consistency(
        project_root,
        gpx_path=gpx_ref,
        raster_sampler=_FakeRasterSampler(),
    )

    assert result["status"] == "completed"
    assert result["terrain_consistency"] == "partially_consistent"
    assert "drainage_evidence_unknown" in {
        item["code"] for item in result["unknowns"]
    }
    assert result["provenance"]["drainage_raster_sha256"] is None


def test_admin_api_exposes_trh_explain_compare_and_default_gpx_consistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)
    captured: dict[str, object] = {}

    def fake_inspect(root: Path, **kwargs: object) -> dict[str, object]:
        captured["root"] = root
        captured.update(kwargs)
        return {
            "artifact_kind": TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND,
            "status": "completed",
            "terrain_consistency": "partially_consistent",
            "assessment_semantics": "terrain_consistency_not_gpx_validity",
            "known_gpx_mutated": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
            "source_type": "known_gpx",
            "sample_evidence": {"type": "FeatureCollection", "features": []},
            "writes_performed": [],
        }

    monkeypatch.setattr(
        admin_api,
        "inspect_scout_route_terrain_consistency",
        fake_inspect,
    )
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=project_root,
            runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-api-audit",
        )
    )
    base = "/admin/pretrip/projects/test-project"

    explanation = client.get(
        f"{base}/terrain-route-hypotheses/explain",
        params={"candidate_id": "R1"},
    )
    comparison = client.get(f"{base}/terrain-route-hypotheses/compare")
    consistency = client.post(
        f"{base}/terrain-route-consistency",
        json={"candidate_id": "R1"},
    )

    assert explanation.status_code == 200
    assert explanation.json()["candidate"] == "R1"
    assert comparison.status_code == 200
    assert len(comparison.json()["hypotheses"]) == 3
    assert consistency.status_code == 200
    assert consistency.json()["terrain_consistency"] == "partially_consistent"
    assert consistency.json()["default_gpx_source_selected"] is True
    assert consistency.headers["x-scout-candidate-only"] == "true"
    assert consistency.headers["x-scout-gpx-assessment"] == (
        "terrain-consistency-not-validity"
    )
    assert captured["root"] == project_root.resolve()
    assert captured["gpx_path"] == gpx_ref
    assert captured["candidate_id"] == "R1"


def test_admin_api_returns_typed_unknown_when_default_gpx_hash_is_stale(
    tmp_path: Path,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)
    (project_root / gpx_ref).write_text("changed", encoding="utf-8")
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=project_root,
            runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-stale-audit",
        )
    )

    response = client.post(
        "/admin/pretrip/projects/test-project/terrain-route-consistency",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["terrain_consistency"] == "unknown"
    assert response.json()["failure_code"] == "known_gpx_source_unavailable"
    assert response.json()["source_type"] == "known_gpx"
    assert response.json()["runtime_safety_truth"] is False


def test_scout_ai_registry_and_executor_expose_trh_read_only_tools(
    tmp_path: Path,
) -> None:
    project_root, gpx_ref = _workspace(tmp_path)
    contracts = default_tool_contracts()

    assert contracts[TERRAIN_ROUTE_EXPLAIN_TOOL_ID].output_artifact_kind == (
        TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND
    )
    assert contracts[TERRAIN_ROUTE_COMPARE_TOOL_ID].output_artifact_kind == (
        TERRAIN_ROUTE_COMPARE_OUTPUT_KIND
    )
    assert contracts[TERRAIN_ROUTE_CONSISTENCY_TOOL_ID].output_artifact_kind == (
        TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND
    )
    for tool_id in (
        TERRAIN_ROUTE_EXPLAIN_TOOL_ID,
        TERRAIN_ROUTE_COMPARE_TOOL_ID,
        TERRAIN_ROUTE_CONSISTENCY_TOOL_ID,
    ):
        assert contracts[tool_id].implementation_status == "ready_current_tool"
        assert contracts[tool_id].boundary.read_only is True
        assert contracts[tool_id].boundary.runtime_safety_truth is False

    explanation = execute_scout_ai_tool(
        {
            "tool_id": "explain_route_hypothesis",
            "project_root": str(project_root),
            "arguments": {"candidate_id": "R1"},
        }
    )
    comparison = execute_scout_ai_tool(
        {
            "tool_id": "compare_route_hypotheses",
            "project_root": str(project_root),
        }
    )
    missing_gpx = execute_scout_ai_tool(
        {
            "tool_id": "inspect_route_terrain_consistency",
            "project_root": str(project_root),
        }
    )

    assert explanation.status == "completed"
    assert explanation.payload["candidate"] == "R1"
    assert comparison.status == "completed"
    assert len(comparison.payload["hypotheses"]) == 3
    assert missing_gpx.status == "missing_input"
    assert missing_gpx.missing_fields == ["gpx_path"]
    assert gpx_ref

    invalid_tolerance = execute_scout_ai_tool(
        {
            "tool_id": "inspect_route_terrain_consistency",
            "project_root": str(project_root),
            "arguments": {
                "gpx_path": gpx_ref,
                "endpoint_tolerance_m": 0,
            },
        }
    )
    assert invalid_tolerance.status == "completed"
    assert invalid_tolerance.payload["status"] == "unavailable"
    assert invalid_tolerance.payload["failure_code"] == "invalid_endpoint_tolerance"
    assert invalid_tolerance.payload["source_type"] == "known_gpx"


class _FakeGenerationBackend:
    def __init__(self) -> None:
        self.request = None

    def start_workflow(self, **kwargs: object) -> SpatialWorkflowRun:
        self.request = kwargs["request"]
        return SpatialWorkflowRun(
            project_id=str(kwargs["project_id"]),
            workflow_id="terrain_route_hypothesis.v1",
            workflow_version="1.0.0",
            workflow_run_id="qgis-spatial-test-run",
            backend_run_id="qgis-worker-test-run",
            request_id="request-test",
            requested_by="scout_ai_operator_request",
            state="queued",
            created_at="2026-09-01T00:00:00Z",
            updated_at="2026-09-01T00:00:00Z",
        )


def test_generate_tool_submits_only_candidate_workspace_workflow(
    tmp_path: Path,
) -> None:
    project_root, _ = _workspace(tmp_path)
    backend = _FakeGenerationBackend()

    from scout_terrain_route_hypothesis_tool import (
        generate_scout_terrain_route_hypotheses,
    )

    result = generate_scout_terrain_route_hypotheses(
        project_root,
        start_lon=121.0,
        start_lat=23.0,
        destination_lon=121.002,
        destination_lat=23.002,
        analysis_margin_m=1000.0,
        qgis_backend=backend,
    )

    assert result["status"] == "queued"
    assert result["workflow_run_id"] == "qgis-spatial-test-run"
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["operational"] is False
    assert result["local_candidate_workspace_write_performed"] is True
    assert result["writes_to_official_trail_db"] is False
    assert result["writes_to_safety_truth"] is False
    assert backend.request.terrain_route_endpoints.start.x == 121.0
    assert backend.request.terrain_route_endpoints.destination.y == 23.002


def test_generate_tool_registry_declares_bounded_effect_and_missing_inputs(
    tmp_path: Path,
) -> None:
    contract = default_tool_contracts()[TERRAIN_ROUTE_GENERATE_TOOL_ID]

    assert contract.output_artifact_kind == TERRAIN_ROUTE_GENERATE_OUTPUT_KIND
    assert contract.implementation_status == "ready_current_tool"
    assert contract.boundary.read_only is False
    assert contract.boundary.local_candidate_workspace_write_allowed is True
    assert contract.boundary.route_truth_mutation_allowed is False
    assert contract.boundary.runtime_safety_truth is False

    result = execute_scout_ai_tool(
        {
            "tool_id": "generate_terrain_route_hypotheses",
            "project_root": str(tmp_path),
            "arguments": {"start_lon": 121.0, "start_lat": 23.0},
        }
    )

    assert result.status == "missing_input"
    assert result.missing_fields == ["destination_lon", "destination_lat"]
    assert result.boundary.read_only is False
    assert result.boundary.local_candidate_workspace_write_allowed is True
    assert result.boundary.runtime_safety_truth is False


@pytest.mark.parametrize(
    ("question", "expected_tool_id"),
    [
        ("請解釋 R1 Terrain Route Hypothesis 的證據與未知", TERRAIN_ROUTE_EXPLAIN_TOOL_ID),
        ("比較 R1 R2 R3 三條 TRH 候選，不要做安全排名", TERRAIN_ROUTE_COMPARE_TOOL_ID),
        ("檢查這份 GPX 與 TRH corridor 的 terrain consistency", TERRAIN_ROUTE_CONSISTENCY_TOOL_ID),
        ("以 A B 座標產生三條 candidate TRH hypotheses", TERRAIN_ROUTE_GENERATE_TOOL_ID),
    ],
)
def test_scout_ai_planner_selects_specific_trh_tools(
    tmp_path: Path,
    question: str,
    expected_tool_id: str,
) -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=question,
        context_ref="test-project",
        project_id="test-project",
    )

    plan = plan_scout_ai_tools(query, project_root=tmp_path)

    assert expected_tool_id in {item.tool_id for item in plan.selected_tools}
    assert plan.boundary.runtime_safety_truth is False
