"""Recorded jobs use immutable observations and the existing durable receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest

import scout_planned_preparation as preparation
from scout_planned_analysis import ROLES, file_sha
from scout_planned_route_artifacts import canonical_bytes
from scout_planned_route_models import PlannedRouteConflict
from scout_planned_route_sources import fetch_trail_source_candidates
from scout_recorded_analysis import save_recorded_version, get_recorded_version
from scout_recorded_jobs import (
    RecordedAnalysisManager, RecordedAnalysisRunRequest, RecordedAnalysisResumeRequest,
    recorded_binding,
)
from test_scout_recorded_analysis import recorded, _files
from test_scout_planned_route_sources import _way


@pytest.fixture(autouse=True)
def _isolate_job_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("SCOUT_PLANNED_PREPARATION_LOCK_ROOT", str(tmp_path / "job-slots"))


def _run_request(bundle, key="recorded.analysis.one"):
    return RecordedAnalysisRunRequest(version_id=bundle["manifest"]["version_id"],
        expected_manifest_sha256=bundle["manifest"]["manifest_sha256"],idempotency_key=key,explicit_confirmation=True)


def _prepare(root,bundle,run_root,*,progress):
    result={"status":"completed","subject_binding":recorded_binding(bundle),"candidate_only":True,
            "runtime_safety_truth":False,"recorded_track":True,"coverage":{"recorded_point_count":len(bundle["preview"]["route_axis"])}}
    (run_root/"prepare.json").write_bytes(canonical_bytes(result))
    return result


def _analyse(root,bundle,run_root,prepared,*,progress):
    projections={}
    for role in ROLES:
        value={"role":role,"status":"partial" if role=="weather" else "ready","summary":f"{role} Recorded seam",
               "input_binding":recorded_binding(bundle),"missing_inputs":[{"code":"historical_weather_unavailable"}] if role=="weather" else [],
               "candidate_only":True,"runtime_safety_truth":False,"recorded_track":True}
        path=run_root/(role+".json")
        path.write_bytes(canonical_bytes(value))
        projections[role]={**value,"artifact_ref":path.name,"artifact_sha256":file_sha(path)}
    return {"projections":projections}


def _manager(root,**options):
    return RecordedAnalysisManager(root,prepare=options.get("prepare",_prepare),
        analyse=options.get("analyse",_analyse),launch=options.get("launch",lambda callback:callback()))


def test_recorded_run_get_resume_and_immutable_attempts(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    owner_before=_files(root)
    manager=_manager(root)
    result=manager.submit(_run_request(bundle))
    assert result["status"]=="completed_with_gaps",result
    assert result["recorded_track"] and result["binding"]["kind"]=="recorded_gpx"
    assert "review_sha256" not in result["binding"]
    assert set(result["projections"])==set(ROLES)
    report=root/result["report_ref"]
    first_report=report.read_bytes()
    assert "outputs/recorded_analysis/runs/" in result["report_ref"]
    assert json.loads(first_report)["recorded_track"]
    first_outputs=_files(root/(result["report_ref"].split("/reports/")[0])/"attempts/0001")
    assert not (root/"outputs/planned_analysis").exists()
    before_get=_files(root)
    assert manager.get(result["run_id"])["report_sha256"]==result["report_sha256"]
    assert manager.submit(_run_request(bundle))["run_id"]==result["run_id"]
    assert _files(root)==before_get
    resumed=manager.resume(result["run_id"],RecordedAnalysisResumeRequest(
        expected_manifest_sha256=bundle["manifest"]["manifest_sha256"],idempotency_key="resume.1",explicit_confirmation=True))
    assert resumed["attempt"]==2 and resumed["status"]=="completed_with_gaps",resumed
    assert report.read_bytes()==first_report
    assert _files(root/(result["report_ref"].split("/reports/")[0])/"attempts/0001")==first_outputs
    after=_files(root)
    assert all(after[ref]==sha for ref,sha in owner_before.items())


def test_recorded_interruption_requires_explicit_resume_and_get_never_writes(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    manager=_manager(root)
    original=manager._start
    manager._start=lambda run_id,lease: manager._release(lease)
    state=manager.submit(_run_request(bundle))
    assert state["status"]=="interrupted" and state["can_resume"]
    before=_files(root)
    assert _manager(root).get(state["run_id"])["status"]=="interrupted"
    assert _files(root)==before
    manager._start=original
    result=manager.resume(state["run_id"],RecordedAnalysisResumeRequest(
        expected_manifest_sha256=bundle["manifest"]["manifest_sha256"],idempotency_key="recover",explicit_confirmation=True))
    assert result["attempt"]==2 and result["status"]=="completed_with_gaps"


def test_recorded_source_change_rejects_submission_and_invalidates_existing(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    manager=_manager(root)
    result=manager.submit(_run_request(bundle))
    source=root/request["recordings"][0]["source_ref"]
    source.write_text(source.read_text().replace("121.002","121.0021"))
    state=manager.get(result["run_id"])
    assert state["status"]=="stale" and not state["projections"]
    with pytest.raises(PlannedRouteConflict,match="sources changed"):
        manager.submit(_run_request(bundle,"new.key"))


def test_recorded_artifact_tamper_cannot_be_read_as_current(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    manager=_manager(root)
    result=manager.submit(_run_request(bundle))
    ref=result["projections"]["navigation"]["artifact_ref"]
    data,_=manager.artifact(result["run_id"],ref)
    assert json.loads(data)["recorded_track"]
    (root/ref).write_text('{"other":true}')
    state=manager.get(result["run_id"])
    assert state["status"]=="stale" and not state["projections"]


def test_same_version_is_single_writer_and_conflicting_key_rejected(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    pending=[]
    manager=_manager(root,launch=lambda callback:pending.append(callback))
    state=manager.submit(_run_request(bundle))
    assert state["status"]=="queued"
    with pytest.raises(PlannedRouteConflict,match="already has a running"):
        manager.submit(_run_request(bundle,"second"))
    pending.pop()()
    assert manager.get(state["run_id"])["status"]=="completed_with_gaps"
    bad=_run_request(bundle).model_copy(update={"expected_manifest_sha256":"0"*64})
    with pytest.raises(PlannedRouteConflict,match="key already"):
        manager.submit(bad)


def test_preparation_uses_recorded_canonical_files_real_times_and_binding(recorded,tmp_path,monkeypatch):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    raw=tmp_path/"raw.tif"
    raw.write_bytes(b"explicit fake raster for isolated provider seam")
    source={"path":str(raw),"role":"raw_regional_dem","sha256":file_sha(raw),"crs":"EPSG:3826","source_resolution_m":20}
    path=root/"inbox/source_manifest.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"project_id":root.name,"preparation_inputs":{"dtm_rasters":[source],"dtm_dirs":[]}}))
    calls=[]
    def fetch(bbox):
        raw=json.dumps({"elements":[_way(10,[1,2],[(121,24),(121,24.003)])]}).encode()
        return fetch_trail_source_candidates(bbox,fetcher=lambda *_:raw,requested_at="2026-09-10T00:00:00Z")
    def terrain(part_root,*,backend,request_id):
        project=json.loads((part_root/"project.json").read_bytes())
        route=json.loads((part_root/project["route_evidence_bundle_ref"]).read_bytes())
        tree=ET.parse(part_root/route["golden_route"]["filtered_geometry_ref"])
        assert route["golden_route"]["gpx_provenance_role"]=="reference_observation"
        stamps=[n.text for n in tree.getroot().iter() if n.tag.rsplit("}",1)[-1]=="time"]
        assert stamps
        assert not any("planned-route" in n.tag for n in tree.getroot().iter())
        calls.append(stamps)
        output={"terrain_dem_route_bbox_raster_ref":"outputs/dem.tif","terrain_feature_manifest_ref":"outputs/terrain.json"}
        for ref in output.values():
            preparation._write(part_root,ref,b"test-raster" if ref.endswith(".tif") else {"candidate_only":True,"runtime_safety_truth":False})
        preparation._write(part_root,"project.json",{**project,**output},immutable=False)
        return {"status":"completed","actual_processor":"qgis_processing_grass","workflow_run_id":request_id,"output_refs":output}
    monkeypatch.setattr(preparation,"fetch_trail_source_candidates",fetch)
    monkeypatch.setattr(preparation,"_qgis_backend",lambda:object())
    monkeypatch.setattr(preparation,"_run_terrain_part",terrain)
    monkeypatch.setattr(preparation,"_sample_dem",lambda path,points:{"values":[100]*len(points),"resolution_m":[20,20],"crs":"EPSG:3826"})
    before=_files(root)
    run=root/"outputs/recorded_analysis/runs/example/attempts/0001"
    result=preparation.prepare_planned_inputs(root,bundle,run)
    assert result["status"]=="completed",result["gaps"]
    assert result["schema_version"]=="scout_recorded_preparation.v1"
    assert result["recorded_track"]
    assert result["subject_binding"]==recorded_binding(bundle)
    assert result["canonical_refs"]["recorded_gpx"]=="inputs/recorded.gpx"
    assert "planned_gpx" not in result["canonical_refs"]
    assert len(calls)==2
    assert result["coverage"]["recorded_point_count"]==97
    for part in result["terrain_parts"]:
        payload=json.loads((run/part["output_refs"]["terrain_samples_ref"]).read_bytes())
        assert payload["recorded_track"] and payload["sampling_method"]=="native_dem_cell_at_exact_recorded_point"
        assert all(p["recorded_point_index"]==p["planned_point_index"] for p in payload["points"])
    mapping=json.loads((run/result["mapping_ref"]).read_bytes())
    assert mapping["recorded_track"]
    assert all(part["recorded_point_indices"]==part["planned_point_indices"] for part in mapping["parts"])
    assert all(_files(root)[ref]==sha for ref,sha in before.items())
    with pytest.raises(preparation.PlannedPreparationError,match="isolated"):
        preparation.prepare_planned_inputs(root,bundle,root/"outputs/planned_analysis/runs/example/attempts/0001")


def test_recorded_binding_does_not_serialize_as_planned_or_require_review(recorded):
    root,request=recorded
    bundle=save_recorded_version(root,request)
    binding=recorded_binding(bundle)
    assert binding["manifest_file_sha256"]==file_sha(root/bundle["bundle_ref"]/"manifest.json")
    assert "recorded.gpx" in binding["canonical_files"] and "planned.gpx" not in binding["canonical_files"]
    assert binding["weather_evaluation_mode"]=="historical_at_observation_time"
    assert binding["recorded_track"] and "review_sha256" not in binding
