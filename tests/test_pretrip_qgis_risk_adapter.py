from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pretrip_qgis_risk_adapter import (
    QGIS_GRASS_RISK_OUTPUT_REFS,
    QgisGrassRiskAdapterError,
    prepare_qgis_grass_risk_outputs,
)


def test_prepares_candidate_risk_artifacts_from_qgis_grass_route_samples(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    overpass_path = project_root / "normalized/map/overpass.geojson"
    reference_gpx_path = project_root / "normalized/routes/reference.gpx"
    samples_ref = (
        "outputs/spatial/qgis/qgis-run-001/terrain_feature_route_samples.geojson"
    )
    samples_path = project_root / samples_ref
    _write_overpass(overpass_path)
    _write_reference_gpx(reference_gpx_path)
    _write_qgis_samples(samples_path)
    _write_qgis_run(
        project_root / "outputs/spatial/qgis/qgis-run-001/workflow_run.json",
        samples_ref=samples_ref,
        samples_path=samples_path,
    )

    result = prepare_qgis_grass_risk_outputs(
        project_root=project_root,
        project_id="dongqing_new_import",
        qgis_workflow_run_id="qgis-run-001",
        overpass_geojson_path=overpass_path,
        reference_gpx_path=reference_gpx_path,
        prepared_at="2026-08-28T12:00:00Z",
        route_corridor_m=500.0,
    )

    assert result["status"] == "completed"
    assert result["actual_processor"] == "qgis_processing_grass"
    assert result["adapter"] == "scout_qgis_grass_risk_profile_adapter.v1"
    assert result["fallback_used"] is False
    assert result["python_dtm_processing_used"] is False
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["operational"] is False
    assert result["adds_source_resolution"] is False
    assert result["counts"]["qgis_source_sample_count"] == 2
    assert result["counts"]["route_risk_sample_count"] > 2
    assert result["counts"]["risk_ribbon_segment_count"] > 0
    assert result["output_refs"] == QGIS_GRASS_RISK_OUTPUT_REFS

    for ref in QGIS_GRASS_RISK_OUTPUT_REFS.values():
        assert (project_root / ref).is_file()

    route_risk = _load(project_root / QGIS_GRASS_RISK_OUTPUT_REFS["risk_route_profile_ref"])
    route_metadata = _load(
        project_root / QGIS_GRASS_RISK_OUTPUT_REFS["risk_route_profile_metadata_ref"]
    )
    scores = [
        feature["properties"]["pretrip_risk"]
        for feature in route_risk["features"]
    ]
    assert max(scores) > min(scores)
    assert route_risk["features"][0]["properties"]["qgis_sample_id"]
    assert route_risk["features"][0]["properties"]["risk_score_applied"] is True
    assert route_risk["features"][0]["properties"]["runtime_safety_truth"] is False
    assert route_metadata["actual_processor"] == "qgis_processing_grass"
    assert route_metadata["adapter"] == "scout_qgis_grass_risk_profile_adapter.v1"
    assert route_metadata["route_base"]["sampling_strategy"] == (
        "reference_progress_projected_to_nearest_overpass_segment.v1"
    )
    assert route_metadata["score_profile"]["profile_id"] == (
        "qgis_grass_terrain_candidate_score.v1"
    )
    assert route_metadata["score_profile"]["visualization_packaging_only"] is False
    assert route_metadata["source_qgis_route_samples_sha256"] == (
        hashlib.sha256(samples_path.read_bytes()).hexdigest()
    )
    assert route_metadata["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "adds_source_resolution": False,
        "python_dtm_processing_used": False,
        "fallback_used": False,
    }


def test_qgis_grass_risk_adapter_fails_closed_for_fixture_samples(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    overpass_path = project_root / "normalized/map/overpass.geojson"
    reference_gpx_path = project_root / "normalized/routes/reference.gpx"
    samples_ref = (
        "outputs/spatial/qgis/qgis-run-fixture/terrain_feature_route_samples.geojson"
    )
    samples_path = project_root / samples_ref
    _write_overpass(overpass_path)
    _write_reference_gpx(reference_gpx_path)
    _write_qgis_samples(samples_path, fixture=True)
    _write_qgis_run(
        project_root / "outputs/spatial/qgis/qgis-run-fixture/workflow_run.json",
        samples_ref=samples_ref,
        samples_path=samples_path,
        fixture=True,
    )

    with pytest.raises(QgisGrassRiskAdapterError, match="fixture|synthetic"):
        prepare_qgis_grass_risk_outputs(
            project_root=project_root,
            project_id="dongqing_new_import",
            qgis_workflow_run_id="qgis-run-fixture",
            overpass_geojson_path=overpass_path,
            reference_gpx_path=reference_gpx_path,
            prepared_at="2026-08-28T12:00:00Z",
            route_corridor_m=500.0,
        )

    assert not (project_root / "outputs/risk/route_risk.geojson").exists()


def test_risk_provenance_stamp_binds_children_to_final_route_bytes(
    tmp_path: Path,
) -> None:
    from pretrip_layer_preparation import _stamp_synced_risk_output_provenance

    project_root, project = _prepare_risk_workspace(tmp_path)
    route_path = project_root / project["risk_route_profile_ref"]
    before_sha256 = hashlib.sha256(route_path.read_bytes()).hexdigest()
    before_features = {
        prefix: _load(project_root / project[prefix + "_ref"])["features"]
        for prefix in ("risk_score_points", "risk_ribbon")
    }

    _stamp_synced_risk_output_provenance(project_root=project_root, project=project)

    final_sha256 = hashlib.sha256(route_path.read_bytes()).hexdigest()
    assert final_sha256 != before_sha256
    for prefix, originals in before_features.items():
        metadata_path = project_root / project[prefix + "_metadata_ref"]
        metadata = _load(metadata_path)
        payload = _load(project_root / project[prefix + "_ref"])
        assert metadata["source_route_risk_sha256"] == final_sha256
        assert payload["metadata"]["source_route_risk_sha256"] == final_sha256
        for original, stamped in zip(originals, payload["features"], strict=True):
            assert stamped["geometry"] == original["geometry"]
            for key in ("rs", "pretrip_risk", "risk_level"):
                assert stamped["properties"].get(key) == original["properties"].get(key)
            refs = {ref["ref"]: ref for ref in stamped["properties"]["source_refs"]}
            assert refs[project["risk_route_profile_ref"]]["sha256"] == final_sha256
            assert refs[project[prefix + "_metadata_ref"]]["sha256"] == (
                hashlib.sha256(metadata_path.read_bytes()).hexdigest()
            )
            assert stamped["properties"]["candidate_only"] is True
            assert stamped["properties"]["runtime_safety_truth"] is False
    stamped_bytes = {
        ref: (project_root / ref).read_bytes()
        for ref in QGIS_GRASS_RISK_OUTPUT_REFS.values()
    }
    _stamp_synced_risk_output_provenance(project_root=project_root, project=project)
    assert {ref: (project_root / ref).read_bytes() for ref in stamped_bytes} == stamped_bytes


@pytest.mark.parametrize("changed_field", ["source_route_risk_ref", "source_route_risk_sha256"])
def test_risk_stamp_does_not_rebind_unrelated_or_inconsistent_parent(
    tmp_path: Path, changed_field: str,
) -> None:
    from pretrip_layer_preparation import _stamp_synced_risk_output_provenance

    project_root, project = _prepare_risk_workspace(tmp_path)
    metadata_path = project_root / project["risk_score_points_metadata_ref"]
    metadata = _load(metadata_path)
    metadata[changed_field] = "unrelated.geojson" if changed_field.endswith("_ref") else "0" * 64
    _write_json(metadata_path, metadata)
    expected_bytes = metadata_path.read_bytes()

    _stamp_synced_risk_output_provenance(project_root=project_root, project=project)

    assert metadata_path.read_bytes() == expected_bytes


def _prepare_risk_workspace(tmp_path: Path) -> tuple[Path, dict]:
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    overpass_path = project_root / "normalized/map/overpass.geojson"
    reference_gpx_path = project_root / "normalized/routes/reference.gpx"
    samples_ref = "outputs/spatial/qgis/qgis-run-001/terrain_feature_route_samples.geojson"
    samples_path = project_root / samples_ref
    _write_overpass(overpass_path)
    _write_reference_gpx(reference_gpx_path)
    _write_qgis_samples(samples_path)
    _write_qgis_run(
        project_root / "outputs/spatial/qgis/qgis-run-001/workflow_run.json",
        samples_ref=samples_ref,
        samples_path=samples_path,
    )
    result = prepare_qgis_grass_risk_outputs(
        project_root=project_root,
        project_id="dongqing_new_import",
        qgis_workflow_run_id="qgis-run-001",
        overpass_geojson_path=overpass_path,
        reference_gpx_path=reference_gpx_path,
        prepared_at="2026-08-28T12:00:00Z",
        route_corridor_m=500.0,
    )
    return project_root, result["output_refs"]


def _write_qgis_samples(path: Path, *, fixture: bool = False) -> None:
    features = []
    for index, (lon, distance_m, slope, elevation, geomorphon, flow) in enumerate(
        (
            (121.0000, 0.0, 8.0, 1200.0, "flat", 1.0),
            (121.0010, 102.0, 42.0, 1280.0, "hollow", 250.0),
        )
    ):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, 23.0]},
                "properties": {
                    "sample_id": f"qgis-run-001.sample.{index:04d}",
                    "distance_m": distance_m,
                    "elevation_m": elevation,
                    "slope_degrees": slope,
                    "aspect_degrees": 90.0,
                    "geomorphon_label": geomorphon,
                    "geomorphon_consensus_label": geomorphon,
                    "flow_accumulation_abs_cells": flow,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "risk_score_applied": False,
                    "fixture": fixture,
                    "synthetic": False,
                },
            }
        )
    _write_json(
        path,
        {
            "type": "FeatureCollection",
            "metadata": {
                "artifact_kind": "scout_qgis_terrain_feature_route_samples",
                "schema_version": "scout_qgis_terrain_feature_route_samples.v0_2",
                "workflow_id": "terrain_feature_stack.v1",
                "workflow_run_id": path.parent.name,
                "actual_processor": "qgis_processing_grass",
                "sample_count": len(features),
                "sampled_raster_fields": [
                    "elevation_m",
                    "slope_degrees",
                    "aspect_degrees",
                    "geomorphon_code",
                    "flow_accumulation_cells",
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
                "fixture": fixture,
                "synthetic": False,
                "adds_source_resolution": False,
            },
            "features": features,
        },
    )


def _write_qgis_run(
    path: Path,
    *,
    samples_ref: str,
    samples_path: Path,
    fixture: bool = False,
) -> None:
    _write_json(
        path,
        {
            "workflow_id": "terrain_feature_stack.v1",
            "workflow_run_id": path.parent.name,
            "state": "completed",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "artifacts": [
                {
                    "artifact_type": "terrain_feature_route_samples",
                    "artifact_ref": samples_ref,
                    "artifact_hash": hashlib.sha256(samples_path.read_bytes()).hexdigest(),
                    "fixture": fixture,
                    "synthetic": False,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                }
            ],
        },
    )


def _write_overpass(path: Path) -> None:
    _write_json(
        path,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.0, 23.0], [121.001, 23.0]],
                    },
                    "properties": {
                        "id": "way/fixture",
                        "candidate_type": "trail_corridor_candidate",
                    },
                }
            ],
        },
    )


def _write_reference_gpx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Scout test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>fixture</name><trkseg>
    <trkpt lat="23.0" lon="121.0"><ele>1200</ele></trkpt>
    <trkpt lat="23.0" lon="121.001"><ele>1280</ele></trkpt>
  </trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
