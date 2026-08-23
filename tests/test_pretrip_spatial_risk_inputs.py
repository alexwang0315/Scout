from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pretrip_spatial_risk_inputs import (
    QGIS_SPATIAL_RISK_INPUT_REFS,
    SpatialRiskInputError,
    build_qgis_spatial_risk_inputs,
    sync_reviewed_qgis_spatial_risk_inputs,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _route_risk(path: Path) -> None:
    _write_json(
        path,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [121.21, 24.05]},
                    "properties": {
                        "sample_id": "route.sample.0000",
                        "route_id": "route",
                        "distance_m": 0,
                        "pretrip_risk": 42,
                        "teii_20m": 40,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [121.22, 24.04]},
                    "properties": {
                        "sample_id": "route.sample.0001",
                        "route_id": "route",
                        "distance_m": 1500,
                        "pretrip_risk": 61,
                        "teii_20m": 58,
                    },
                },
            ],
        },
    )


def _qgis_samples(path: Path, *, candidate_only: bool = True) -> None:
    _write_json(
        path,
        {
            "type": "FeatureCollection",
            "metadata": {
                "workflow_id": "terrain_feature_stack.v1",
                "workflow_run_id": "qgis-run-reviewed",
                "candidate_only": candidate_only,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [121.21001, 24.05001]},
                    "properties": {
                        "sample_id": "qgis.sample.0000",
                        "slope_degrees": 35.0,
                        "aspect_degrees": 180.0,
                        "geomorphon_code": 3,
                        "geomorphon_label": "ridge",
                        "flow_accumulation_cells": -42.0,
                        "flow_accumulation_abs_cells": 42.0,
                        "flow_accumulation_likely_underestimated": True,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                        "risk_score_applied": False,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [121.22001, 24.04001]},
                    "properties": {
                        "sample_id": "qgis.sample.0001",
                        "slope_degrees": 18.0,
                        "aspect_degrees": 90.0,
                        "geomorphon_code": 9,
                        "geomorphon_label": "valley",
                        "flow_accumulation_cells": 121.0,
                        "flow_accumulation_abs_cells": 121.0,
                        "flow_accumulation_likely_underestimated": False,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                        "risk_score_applied": False,
                    },
                },
            ],
        },
    )


def _reviewed_run(path: Path, samples_ref: str, samples_path: Path, *, fixture: bool = False) -> None:
    _write_json(
        path,
        {
            "workflow_id": "terrain_feature_stack.v1",
            "workflow_run_id": "qgis-run-reviewed",
            "state": "completed",
            "completed_at": "2026-08-22T05:00:00Z",
            "human_review_status": "completed",
            "visual_review_status": "completed",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "artifacts": [
                {
                    "artifact_type": "terrain_feature_route_samples",
                    "artifact_ref": samples_ref,
                    "artifact_hash": hashlib.sha256(samples_path.read_bytes()).hexdigest(),
                    "status": "reviewed_evidence",
                    "fixture": fixture,
                    "synthetic": fixture,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                }
            ],
        },
    )


def test_qgis_spatial_risk_inputs_align_reviewed_features_without_changing_scores(
    tmp_path: Path,
) -> None:
    route_path = tmp_path / "route_risk.geojson"
    samples_path = tmp_path / "terrain_feature_route_samples.geojson"
    _route_risk(route_path)
    _qgis_samples(samples_path)

    payload = build_qgis_spatial_risk_inputs(
        route_risk_path=route_path,
        qgis_route_samples_path=samples_path,
        qgis_workflow_run_id="qgis-run-reviewed",
        qgis_workflow_run_ref="outputs/spatial/qgis/qgis-run-reviewed/workflow_run.json",
    )

    assert payload["metadata"]["status"] == "ready_for_calibration"
    assert payload["metadata"]["aligned_sample_count"] == 2
    assert payload["metadata"]["risk_score_applied"] is False
    assert payload["metadata"]["baseline_scores_modified"] is False
    assert payload["metadata"]["runtime_safety_truth"] is False
    assert payload["features"][0]["properties"]["baseline_pretrip_risk"] == 42
    assert payload["features"][0]["properties"]["geomorphon_label"] == "ridge"
    assert payload["features"][0]["properties"]["risk_v2_status"] == "calibration_required"


def test_qgis_spatial_risk_inputs_reject_authority_violation(tmp_path: Path) -> None:
    route_path = tmp_path / "route_risk.geojson"
    samples_path = tmp_path / "terrain_feature_route_samples.geojson"
    _route_risk(route_path)
    _qgis_samples(samples_path, candidate_only=False)

    with pytest.raises(SpatialRiskInputError, match="candidate authority"):
        build_qgis_spatial_risk_inputs(
            route_risk_path=route_path,
            qgis_route_samples_path=samples_path,
            qgis_workflow_run_id="qgis-run-reviewed",
            qgis_workflow_run_ref="workflow_run.json",
        )


def test_sync_uses_latest_reviewed_non_fixture_qgis_run(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    route_ref = "outputs/risk/route_risk.geojson"
    route_path = project_root / route_ref
    samples_ref = (
        "outputs/spatial/qgis/qgis-run-reviewed/terrain_feature_route_samples.geojson"
    )
    samples_path = project_root / samples_ref
    run_path = project_root / "outputs/spatial/qgis/qgis-run-reviewed/workflow_run.json"
    _route_risk(route_path)
    _qgis_samples(samples_path)
    _reviewed_run(run_path, samples_ref, samples_path)

    updated = sync_reviewed_qgis_spatial_risk_inputs(
        project_root=project_root,
        project={"project_id": "demo", "risk_route_profile_ref": route_ref},
    )

    assert updated["qgis_spatial_risk_input_status"] == "ready_for_calibration"
    assert updated["qgis_spatial_risk_input_aligned_count"] == 2
    output_path = project_root / QGIS_SPATIAL_RISK_INPUT_REFS["qgis_spatial_risk_inputs_ref"]
    assert output_path.is_file()
    assert json.loads(output_path.read_text())["metadata"]["risk_score_applied"] is False


def test_sync_ignores_unreviewed_or_fixture_qgis_runs(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    route_ref = "outputs/risk/route_risk.geojson"
    route_path = project_root / route_ref
    samples_ref = "outputs/spatial/qgis/qgis-fixture/terrain_feature_route_samples.geojson"
    samples_path = project_root / samples_ref
    run_path = project_root / "outputs/spatial/qgis/qgis-fixture/workflow_run.json"
    _route_risk(route_path)
    _qgis_samples(samples_path)
    _reviewed_run(run_path, samples_ref, samples_path, fixture=True)

    updated = sync_reviewed_qgis_spatial_risk_inputs(
        project_root=project_root,
        project={"project_id": "demo", "risk_route_profile_ref": route_ref},
    )

    assert updated["qgis_spatial_risk_input_status"] == "not_available"
    assert "qgis_spatial_risk_inputs_ref" not in updated
