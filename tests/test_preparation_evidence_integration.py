"""Preparation sequencing and provenance; synthetic producers make no provider calls."""
import hashlib
import json
from pathlib import Path
import shutil

import pretrip_layer_preparation as preparation
import scout_analysis_subject


def test_preparation_publishes_mcp_before_consumers_and_binds_current_outputs(tmp_path, monkeypatch):
    source = Path(__file__).parent / "fixtures/pretrip/projects/chilai_nanhua_day1"
    root = tmp_path / source.name
    shutil.copytree(source, root)
    project_path = root / "project.json"
    old_project = json.loads(project_path.read_text())
    refs = {key: old_project[key] for key in (
        "mcp_named_point_evidence_ref", "mcp_candidates_ref", "mcp_cp_support_reconciliation_ref",
    )}
    refs["mcp_evidence_collection_receipt_ref"] = "outputs/mcp/collection-fixture.json"
    (root / refs["mcp_evidence_collection_receipt_ref"]).write_text('{"fixture":true}')
    order = []
    def collect(**kwargs):
        order.append("collect")
        return {"status": "completed", "output_refs": refs, "counts": {"mcp_accepted_source_count": 12}}
    def align(**kwargs):
        project = json.loads(project_path.read_text())
        assert project["mcp_evidence_collection_receipt_ref"] == refs["mcp_evidence_collection_receipt_ref"]
        assert project["mcp_accepted_source_count"] == 12
        order.append("align")
        return {"status": "completed", "output_refs": {"overpass_aligned_mcp_candidates_ref": refs["mcp_candidates_ref"]}}
    context_ref = "outputs/context-fixture.json"
    def context(**kwargs):
        order.append("context")
        assert order == ["collect", "align", "context"]
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
        project_id=source.name, project_root=root, layers=("mcp",),
        run_qgis_terrain_workflow=False, run_map_preparation_spec_artifacts=False,
        allow_network_fetch=False, prepared_at="2026-09-09T00:00:00Z",
    ))
    assert order == ["collect", "align", "context"]
    assert result["analysis_geometry_binding"] != result["analysis_geometry_binding_current"]
    assert result["analysis_geometry_drift"] is False
    rows = result["analysis_projection_outputs"]
    assert rows["architecture"] == rows["navigation"] == []
    assert rows["route_context"][0]["sha256"] == hashlib.sha256((root / context_ref).read_bytes()).hexdigest()
    assert rows["route_context"][0]["status"] == "ready"
    project = json.loads(project_path.read_text())
    assert project["overpass_aligned_mcp_candidates_ref"] == refs["mcp_candidates_ref"]
    assert result["boundary"]["runtime_safety_truth"] is False


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
