"""Preparation sequencing and provenance; synthetic producers make no provider calls."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import pretrip_layer_preparation as preparation
import scout_analysis_subject


@pytest.mark.parametrize("stale_osm", [False, True])
def test_preparation_publishes_mcp_before_consumers_and_binds_current_outputs(tmp_path, monkeypatch, stale_osm):
    source = Path(__file__).parent / "fixtures/pretrip/projects/chilai_nanhua_day1"
    root = tmp_path / source.name
    shutil.copytree(source, root)
    project_path = root / "project.json"
    old_project = json.loads(project_path.read_text())
    refs = {key: old_project[key] for key in (
        "mcp_named_point_evidence_ref", "mcp_candidates_ref", "mcp_cp_support_reconciliation_ref",
    )}
    payload = json.loads((root / refs["mcp_candidates_ref"]).read_text())
    payload["mcp_candidates"] = payload["mcp_candidates"][:2]
    refs["mcp_candidates_ref"] = "outputs/mcp/current-collection-candidates.json"
    refs["mcp_evidence_collection_receipt_ref"] = "outputs/mcp/collection-fixture.json"
    for key in list(old_project):
        if key.startswith("mcp_") or key == "overpass_aligned_mcp_candidates_ref":
            old_project.pop(key)
    old_project["route_evidence_bundle_ref"] = "outputs/route-evidence-fixture.json"
    route = json.loads((root / old_project["route_summary_ref"]).read_text())
    (root / old_project["route_evidence_bundle_ref"]).write_text(json.dumps({
        "fixture": True, "project_id": source.name,
        "route_scope_for_map_preparation": {"bbox_wgs84": route["bbox_wgs84"]},
        "boundary": {"candidate_only": True, "runtime_safety_truth": False},
    }))
    if stale_osm:
        old_project.update({
            "osm_pbf_extracted_at": "2026-09-09T00:00:00Z",
            "osm_pbf_cache_status": "stale_refresh_recommended",
            "osm_pbf_cache_expires_at": "2026-07-25T05:27:06Z",
            "osm_pbf_refresh_required": True,
        })
    project_path.write_text(json.dumps(old_project))
    aligned_ref = "outputs/mcp/current-aligned-candidates.json"
    order = []
    def collect(**kwargs):
        initial_mcp = next(row for row in kwargs["manifest"]["layers"] if row["layer_id"] == "mcp")
        assert initial_mcp["status"] == "missing_source"
        assert initial_mcp["lifecycle"]["fetch"]["status"] == "blocked_missing_source"
        (root / refs["mcp_candidates_ref"]).write_text(json.dumps(payload))
        (root / refs["mcp_evidence_collection_receipt_ref"]).write_text('{"fixture":true}')
        order.append("collect")
        return {"status": "completed", "output_refs": refs, "counts": {
            "mcp_accepted_source_count": 12, "mcp_candidate_count": 2,
        }}
    def align(**kwargs):
        if "collect" not in order:
            order.append("initial_align")
            return {"status": "completed", "output_refs": {}, "counts": {"snapped_point_count": 999}}
        project = json.loads(project_path.read_text())
        assert project["mcp_evidence_collection_receipt_ref"] == refs["mcp_evidence_collection_receipt_ref"]
        assert project["mcp_accepted_source_count"] == 12
        (root / aligned_ref).write_text(json.dumps({**payload, "current_alignment_fixture": True}))
        order.append("align")
        return {"status": "completed", "output_refs": {"overpass_aligned_mcp_candidates_ref": aligned_ref},
                "counts": {"snapped_point_count": 2}}
    expected_order = (["initial_align"] if stale_osm else []) + ["collect", "align", "context"]
    context_ref = "outputs/context-fixture.json"
    def context(**kwargs):
        order.append("context")
        assert order == expected_order
        (root / context_ref).write_text('{"candidate_only":true,"runtime_safety_truth":false}')
        return {"status": "completed", "route_context_collection": {
            "status": "completed", "output_refs": {"route_context_index_ref": context_ref},
        }}
    for name, producer in (
        ("_run_mcp_evidence_collection_after_layer_preparation", collect),
        ("_run_overpass_route_alignment_after_layer_preparation", align),
        ("_run_raster_label_preparation_after_layer_preparation", context),
    ):
        monkeypatch.setattr(preparation, name, producer)
    for name in (
        "_run_boss_point_synthesis_after_layer_preparation",
        "_run_mileage_tag_alignment_after_layer_preparation",
        "_run_reference_segment_timing_after_layer_preparation",
        "_run_architecture_preparation_after_layer_preparation",
    ):
        monkeypatch.setattr(preparation, name, lambda **kwargs: {"status": "not_requested", "output_refs": {}})
    captures = []
    def capture(project_root):
        assert project_root == root
        captures.append(len(captures))
        return {"geometry_fingerprint": "geometry", "timing_fingerprint": "timing",
                "sources": {"recorded_pace": {"sha256": str(len(captures))}}}
    monkeypatch.setattr(scout_analysis_subject, "capture_analysis_geometry_binding", capture)
    result = preparation.run_layer_preparation(preparation.LayerPreparationRequest(
        project_id=source.name, project_root=root, layers=("mcp", "overpass") if stale_osm else ("mcp",),
        run_qgis_terrain_workflow=False, run_map_preparation_spec_artifacts=False,
        allow_network_fetch=False, prepared_at="2026-09-09T00:00:00Z",
    ))
    assert order == expected_order
    assert result["analysis_geometry_binding"] != result["analysis_geometry_binding_current"]
    assert result["analysis_geometry_drift"] is False
    rows = result["analysis_projection_outputs"]
    assert rows["architecture"] == rows["navigation"] == []
    assert rows["route_context"][0]["sha256"] == hashlib.sha256((root / context_ref).read_bytes()).hexdigest()
    assert rows["route_context"][0]["status"] == "ready"
    project = json.loads(project_path.read_text())
    assert project["overpass_aligned_mcp_candidates_ref"] == aligned_ref
    assert result["boundary"]["runtime_safety_truth"] is False
    mcp = next(row for row in result["layers"] if row["layer_id"] == "mcp")
    assert mcp["status"] == "ready_from_project_ref"
    assert mcp["counts"] == {
        "mcp_accepted_source_count": 12, "mcp_candidate_count": 2,
        "overpass_aligned": True, "overpass_alignment_snapped_point_count": 2,
    }
    assert mcp["source_refs"][0]["ref"] == aligned_ref
    assert mcp["source_refs"][0]["sha256"] == hashlib.sha256((root / aligned_ref).read_bytes()).hexdigest()
    assert mcp["output_refs"] == {"overpass_aligned_mcp_candidates_ref": aligned_ref}
    assert mcp["warnings"] == mcp["blockers"] == []
    assert mcp["lifecycle"]["fetch"]["status"] == "read_local_project_ref"
    assert mcp["lifecycle"]["import"]["status"] == mcp["lifecycle"]["normalize"]["status"] == "completed"
    assert mcp["lifecycle"]["summarize"]["counts"] == mcp["counts"]
    assert result["counts"]["missing_layer_count"] == 0
    assert result["validation"]["status"] == ("ready_with_warnings" if stale_osm else "ready")
    assert result["validation"]["warning_count"] == int(stale_osm)
    if stale_osm:
        assert result["validation"]["warnings"] == [{
            "layer_id": "overpass",
            "message": "Local OSM PBF cache is older than the configured TTL; refresh recommended before new pretrip fetch.",
        }]
    def persisted(ref_key):
        return json.loads((root / result["outputs"][ref_key]).read_text())
    assert persisted("layer_preparation_manifest_ref")["layers"] == result["layers"]
    assert persisted("layer_validation_report_ref") == result["validation"]
    for ref_key in ("layer_preparation_summary_ref", "map_preparation_summary_ref"):
        assert persisted(ref_key)["counts"] == result["counts"]
        assert persisted(ref_key)["status"] == result["validation"]["status"]
    summary_mcp = next(row for row in persisted("layer_preparation_summary_ref")["layers"] if row["layer_id"] == "mcp")
    assert summary_mcp["counts"] == mcp["counts"]
    adapter_mcp = next(row for row in persisted("layer_adapter_manifest_ref")["adapters"] if row["layer_id"] == "mcp")
    assert adapter_mcp["lifecycle"] == mcp["lifecycle"]
    assert adapter_mcp["source_refs"] == mcp["source_refs"]
    projection_mcp = next(row for row in persisted("layer_map_projection_ref")["layers"] if row["layer_id"] == "mcp")
    for key in ("status", "counts", "source_refs", "output_refs"):
        assert projection_mcp[key] == mcp[key]


@pytest.mark.parametrize("failure", [
    "collection_failed", "insufficient_evidence", "receipt_gap", "alignment_failed",
    "missing_candidate_file", "missing_aligned_file", "missing_aligned_ref",
])
def test_current_mcp_gaps_cannot_be_hidden_by_existing_outputs(tmp_path, failure):
    old_ref = "old-aligned.json"
    base_ref, aligned_ref = "current-candidates.json", "current-aligned.json"
    for ref, count in ((old_ref, 9), (base_ref, 2), (aligned_ref, 2)):
        if (failure == "missing_candidate_file" and ref == base_ref) or (
            failure == "missing_aligned_file" and ref == aligned_ref
        ):
            continue
        (tmp_path / ref).write_text(json.dumps({"mcp_candidates": [{"id": i} for i in range(count)]}))
    collection = {"status": "completed", "output_refs": {"mcp_candidates_ref": base_ref}, "receipt": {"gaps": []}}
    alignment = {"status": "completed", "output_refs": {"overpass_aligned_mcp_candidates_ref": aligned_ref}}
    project = {"mcp_candidates_ref": base_ref, "overpass_aligned_mcp_candidates_ref": aligned_ref}
    if failure == "collection_failed":
        collection.update(status="failed", output_refs={}, reason="mcp_evidence_collection_failed")
        alignment = {}
        project.update(mcp_candidates_ref=old_ref, overpass_aligned_mcp_candidates_ref=old_ref)
    elif failure in {"insufficient_evidence", "receipt_gap"}:
        collection["receipt"]["gaps"] = ["accepted independent source documents 4 < required 11"]
        if failure == "insufficient_evidence":
            collection["status"] = "insufficient_evidence"
    elif failure == "alignment_failed":
        alignment = {"status": "failed", "output_refs": {"overpass_aligned_mcp_candidates_ref": old_ref}}
        project["overpass_aligned_mcp_candidates_ref"] = old_ref
    elif failure == "missing_candidate_file":
        alignment = {"status": "not_requested"}
        project["overpass_aligned_mcp_candidates_ref"] = old_ref
    elif failure == "missing_aligned_ref":
        alignment = {"status": "completed", "output_refs": {}}
        project["overpass_aligned_mcp_candidates_ref"] = old_ref
    (tmp_path / "project.json").write_text(json.dumps(project))
    manifest = {
        "layers": [preparation._with_lifecycle({
            "layer_id": "mcp", "status": "ready_from_project_ref", "source_refs": [{"ref": old_ref}],
            "output_refs": {"overpass_aligned_mcp_candidates_ref": old_ref},
            "counts": {"mcp_candidate_count": 9}, "warnings": [], "blockers": [],
        })],
        "mcp_evidence_collection": collection,
        "mcp_overpass_route_alignment": alignment,
        "overpass_route_alignment": {"status": "completed", "output_refs": {
            "overpass_aligned_mcp_candidates_ref": old_ref,
        }, "counts": {"snapped_point_count": 999}},
    }
    preparation._refresh_mcp_layer_record_after_collection(project_root=tmp_path, manifest=manifest)
    row = manifest["layers"][0]
    assert row["status"] not in preparation.READY_STATUSES
    assert row["warnings"] or row["blockers"]
    assert row["counts"].get("mcp_candidate_count", 0) in {0, 2}
    assert all(source["ref"] != old_ref for source in row["source_refs"])
    assert row["lifecycle"]["normalize"]["status"] == "skipped"
    validation = preparation._validation_report(
        request=preparation.LayerPreparationRequest(project_id="fixture", project_root=tmp_path, layers=("mcp",)),
        layers=manifest["layers"], project_root=tmp_path, workspace_file_mutation_allowed=False,
        route_evidence_bundle={"available": True},
    )
    assert validation["status"] != "ready"
    projections = [preparation._map_projection_layer(row)]
    preparation._augment_map_projection_layers(manifest, projections)
    assert old_ref not in projections[0]["output_refs"].values()
    assert projections[0]["counts"].get("overpass_aligned") is not True


def test_failed_or_retained_projection_is_not_relabelled_current(tmp_path):
    (tmp_path / "old.json").write_text('{"fixture":true}')
    stage = {"status": "completed", "output_refs": {"ref": "old.json"}}
    manifest = {
        "raster_label_preparation": {"route_context_collection": {**stage, "fresh": False}},
        "architecture_preparation": {**stage, "status": "failed"},
        "navigation_terrain_projection": stage,
        "qgis_terrain_feature_stack": {"status": "failed"},
    }
    assert preparation._capture_preparation_projection_outputs(
        project_root=tmp_path, manifest=manifest,
    ) == {"route_context": [], "architecture": [], "navigation": []}
