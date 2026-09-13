"""Recorded sets preserve real point/time roles and all prior route versions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from scout_planned_route import compile_planned_route
from scout_planned_route_artifacts import PlannedSaveRequest, save_planned_version
from scout_planned_route_models import PlannedRouteConflict, PlannedRouteRequest
from scout_recorded_analysis import (
    RecordedSetRequest, build_recorded_analysis_inputs, get_recorded_selection,
    get_recorded_version, list_recorded_sources, list_recorded_versions,
    save_recorded_version, select_recorded_version,
)
from test_scout_planned_route import planned_workspace


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _files(root):
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def _gpx(path, parts, *, root_attributes=None, metadata=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.Element("gpx", {"xmlns": "http://www.topografix.com/GPX/1/1", "version": "1.1", **(root_attributes or {})})
    if metadata:
        tree.append(ET.fromstring(metadata))
    track = ET.SubElement(tree, "trk")
    for part in parts:
        segment = ET.SubElement(track, "trkseg")
        for lat, lon, stamp in part:
            point = ET.SubElement(segment, "trkpt", lat=str(lat), lon=str(lon))
            ET.SubElement(point, "ele").text = str(100 + (lat - 24) * 10000)
            if stamp:
                ET.SubElement(point, "time").text = stamp
    path.write_bytes(ET.tostring(tree, encoding="utf-8", xml_declaration=True))


@pytest.fixture
def recorded(tmp_path):
    root = planned_workspace(tmp_path)
    request = PlannedRouteRequest(departure_at="2026-10-01T06:00:00+08:00",
                                  human_text="在觀景點 C 多停 40 分鐘")
    preview = compile_planned_route(root, request)
    plan = save_planned_version(root, PlannedSaveRequest(request=request,
        expected_preview_sha256=preview["preview_sha256"], idempotency_key="plan", explicit_confirmation=True))
    t0 = datetime(2026, 10, 1, 6, tzinfo=timezone(timedelta(hours=8)))
    coords = [(24,121), (24.001,121), (24.001,121.001), (24.001,121.002),
              (24.001,121.002), (24.001,121.002), (24.001,121.001), (24.001,121),
              (24.002,121), (24.001,121), (24,121)]
    first = [(a,b,(t0+timedelta(minutes=i*5)).isoformat()) for i,(a,b) in enumerate(coords)]
    _gpx(root/"post_analysis/completed_trips/recorded/day1.gpx", [first])
    day2 = [(24,121,(t0+timedelta(days=1,minutes=i*5)).isoformat()) for i in range(85)]
    day2.append((24.001,121,(t0+timedelta(days=1,minutes=425)).isoformat()))
    _gpx(root/"post_analysis/completed_trips/recorded/day2.gpx", [day2])
    _gpx(root/"post_analysis/completed_trips/recorded/watch.gpx", [first])
    _gpx(root/"post_analysis/completed_trips/recorded/member.gpx", [first[:3]])
    payload = {"project_id":root.name, "primary_member_id":"alice", "planned_version_id":plan["version_id"],
               "golden_source_ref":"normalized/golden.gpx", "idempotency_key":"recorded.one", "recordings":[
        {"source_ref":"post_analysis/completed_trips/recorded/day1.gpx","member_id":"alice","device_id":"phone","observation_kind":"device_observation","role":"primary"},
        {"source_ref":"post_analysis/completed_trips/recorded/day2.gpx","member_id":"alice","device_id":"phone","observation_kind":"device_observation","role":"primary"},
        {"source_ref":"post_analysis/completed_trips/recorded/watch.gpx","member_id":"alice","device_id":"watch","observation_kind":"device_observation","role":"backup"},
        {"source_ref":"post_analysis/completed_trips/recorded/member.gpx","member_id":"bob","device_id":"watch","observation_kind":"device_observation","role":"member_context"},
    ]}
    return root,payload


def test_multi_file_member_day_comparison_and_no_original_mutation(recorded):
    root, request = recorded
    before = _files(root)
    value = save_recorded_version(root, request)
    after = _files(root)
    assert all(after[ref] == sha for ref,sha in before.items())
    assert len(value["preview"]["recordings"]) == 4
    preview, manifest = value["preview"], value["manifest"]
    assert len(preview["route_axis"]) == 97
    assert {p["member_id"] for p in preview["route_axis"]} == {"alice"}
    assert {p["device_id"] for p in preview["route_axis"]} == {"phone"}
    assert [d["date"] for d in preview["itinerary"]["days"]] == ["2026-10-01","2026-10-02"]
    assert preview["metrics"]["rest_seconds"] == 600 + 7*3600
    assert preview["metrics"]["camp_candidate_seconds"] == 7*3600
    assert preview["metrics"]["camp_confirmed_seconds"] is None
    assert preview["metrics"]["unobserved_seconds"] == 23*3600+10*60
    assert len(preview["graph"]["gaps"]) == 1
    assert all(not g["connector_created"] and not g["moving_or_camp_inferred"] for g in preview["graph"]["gaps"])
    assert preview["comparison"]["golden"]["deviation_point_count"] >= 5
    assert preview["comparison"]["planned"]["turnback_detected"]
    assert "cp.finish" in preview["comparison"]["golden"]["unreached_checkpoint_ids"]
    junction_visits = [v for v in preview["comparison"]["golden"]["checkpoint_visits"] if v["baseline_checkpoint_id"]=="cp.junction"]
    assert len(junction_visits) >= 3
    assert manifest["kind"] == "recorded_gpx" and manifest["source_times_role"] == "device_recorded_time"
    assert manifest["actual_user_recorded_activity"] and not preview["physical_activity_authenticity_verified"]
    assert manifest["weather_evaluation_mode"] == "historical_at_observation_time"
    assert manifest["candidate_only"] and not manifest["runtime_safety_truth"]
    assert any(name.startswith("capability/") for name in manifest["files"])
    bundle_root = root/value["bundle_ref"]
    gpx = ET.parse(bundle_root/"recorded.gpx")
    stamps = [n.text for n in gpx.getroot().iter() if n.tag.rsplit("}",1)[-1]=="time"]
    assert stamps == [p["timestamp"] for p in preview["route_axis"]]
    assert not any(e["start_point_index"] < 11 <= e["end_point_index"] for e in preview["graph"]["edges"])


def test_save_idempotency_reads_and_selection_restore(recorded):
    root, request = recorded
    value = save_recorded_version(root, request)
    first_files = _files(root)
    retry = save_recorded_version(root, request)
    assert retry["replayed"] and retry["manifest"] == value["manifest"]
    assert _files(root) == first_files
    selected = select_recorded_version(root, value["manifest"]["version_id"], value["manifest"]["manifest_sha256"])
    assert selected["status"] == "selected" and not selected["original_golden_replaced"]
    before_reads = _files(root)
    assert get_recorded_selection(root)["version_id"] == value["manifest"]["version_id"]
    assert len(list_recorded_versions(root)["versions"]) == 1
    assert len(list_recorded_sources(root)["recordings"]) == 4
    assert _files(root) == before_reads


def test_source_changes_create_new_version_and_preserve_previous_bytes(recorded):
    root, request = recorded
    one = save_recorded_version(root, request)
    original_version_files = _files(root/one["bundle_ref"])
    source = root/request["recordings"][0]["source_ref"]
    source.write_text(source.read_text().replace("121.002", "121.0021"))
    assert get_recorded_version(root, one["manifest"]["version_id"])["source_status"]["status"] == "stale"
    with pytest.raises(PlannedRouteConflict, match="idempotency"):
        save_recorded_version(root, request)
    with pytest.raises(PlannedRouteConflict, match="changed"):
        select_recorded_version(root, one["manifest"]["version_id"])
    two = save_recorded_version(root, {**request, "idempotency_key":"recorded.two"})
    assert two["manifest"]["version_id"] != one["manifest"]["version_id"]
    assert _files(root/one["bundle_ref"]) == original_version_files
    assert len(list_recorded_versions(root)["versions"]) == 2


def test_input_adapter_actual_timing_graph_identity_and_readonly_owner(recorded, tmp_path):
    root, request = recorded
    bundle = save_recorded_version(root, request)
    owner_before = _files(root)
    run = tmp_path/"run"
    inputs = build_recorded_analysis_inputs(root, bundle, run)
    assert _files(root) == owner_before
    assert inputs["subject_binding"]["kind"] == "recorded_gpx"
    assert inputs["planned_eta"]["artifact_kind"] == "recorded_observation_timing"
    assert inputs["planned_eta"]["time_role"] == "device_recorded_time"
    assert inputs["weather_evaluation_mode"] == "historical_at_observation_time"
    assert not inputs["itinerary"]["forecast_requested"]
    assert all(p["time_role"] == "device_recorded_time" for p in inputs["route_axis"])
    same = build_recorded_analysis_inputs(root, bundle, run)
    assert same == inputs
    with pytest.raises(PlannedRouteConflict, match="another Recorded"):
        build_recorded_analysis_inputs(root,bundle,tmp_path/"bad",{"subject_binding":{"version_id":"other"}})
    with pytest.raises(PlannedRouteConflict, match="separate"):
        build_recorded_analysis_inputs(root,bundle,root)


@pytest.mark.parametrize("attrs,metadata", [
    ({"creator":"Scout Planned Route"},""),
    ({},"<metadata><extensions><provenance xmlns='https://scout.local/schemas/planned-route/v1' role='planned'/></extensions></metadata>"),
    ({},"<metadata><extensions><provenance role='planned_gpx'/></extensions></metadata>"),
    ({},"<metadata><extensions><time_role>planned_estimate</time_role></extensions></metadata>"),
    ({},"<metadata><extensions><synthetic_timestamp>true</synthetic_timestamp></extensions></metadata>"),
    ({},"<metadata><extensions><provenance role='synthetic'/></extensions></metadata>"),
])
def test_renamed_planned_or_synthetic_xml_with_fake_times_is_rejected(recorded, attrs, metadata):
    root,request=recorded
    _gpx(root/"renamed.data", [[(24,121,"2026-10-01T06:00:00+08:00"),(24.001,121,"2026-10-01T06:10:00+08:00")]],
         root_attributes=attrs,metadata=metadata)
    request={**request,"recordings":[{**request["recordings"][0],"source_ref":"renamed.data"}]}
    with pytest.raises(PlannedRouteConflict,match="Planned or synthetic"):
        save_recorded_version(root,request)


def test_actual_planned_export_reimport_rejected(recorded):
    root, request = recorded
    from scout_planned_route_artifacts import export_planned_version
    raw,_,_ = export_planned_version(root,request["planned_version_id"],"gpx")
    source = root/"looks-like-phone.gpx"
    source.write_bytes(raw)
    request={**request,"recordings":[{**request["recordings"][0],"source_ref":source.name}]}
    with pytest.raises(PlannedRouteConflict,match="Planned"):
        save_recorded_version(root,request)


def test_project_isolation_symlink_and_baseline_integrity(recorded, tmp_path):
    root, request=recorded
    with pytest.raises(PlannedRouteConflict,match="another project"):
        save_recorded_version(root,{**request,"project_id":"different"})
    outside=tmp_path/"external.gpx"
    outside.write_bytes((root/request["recordings"][0]["source_ref"]).read_bytes())
    (root/"linked.gpx").symlink_to(outside)
    for ref in ("../external.gpx",str(outside),"linked.gpx"):
        with pytest.raises(PlannedRouteConflict):
            save_recorded_version(root,{**request,"recordings":[{**request["recordings"][0],"source_ref":ref}]})
    value=save_recorded_version(root,request)
    mirror=tmp_path/"other"
    shutil.copytree(root,mirror,symlinks=True)
    (mirror/"project.json").write_text('{"project_id":"other"}')
    with pytest.raises(PlannedRouteConflict,match="binding"):
        get_recorded_version(mirror,value["manifest"]["version_id"])


def test_overlapping_primary_sources_rejected_backup_not_double_counted(recorded):
    root,request=recorded
    source=[{**r,"role":"primary"} if r["role"]=="backup" else r for r in request["recordings"]]
    with pytest.raises(PlannedRouteConflict,match="overlap"):
        save_recorded_version(root,{**request,"recordings":source})
    with pytest.raises(ValidationError):
        RecordedSetRequest.model_validate({**request,"primary_member_id":"bob"})


def test_fixture_and_historical_roles_never_claim_user_completed(recorded):
    root,request=recorded
    for kind in ("fixture_replay","historical_recording"):
        altered={**request,"idempotency_key":kind,"recordings":[{**r,"observation_kind":kind} for r in request["recordings"]]}
        value=save_recorded_version(root,altered)
        assert not value["manifest"]["actual_user_recorded_activity"]
        assert value["manifest"]["source_times_role"] == ("fixture_replay_time" if kind=="fixture_replay" else "device_recorded_time")
        if kind=="fixture_replay":
            assert {p["time_role"] for p in value["preview"]["route_axis"]}=={"fixture_replay_time"}


def test_missing_or_naive_times_and_timestamp_regression_rejected(recorded):
    root,request=recorded
    for timestamps in ((None,None),("2026-01-01T06:00:00","2026-01-01T06:10:00"),
                       ("2026-01-01T06:10:00Z","2026-01-01T06:00:00Z")):
        path=root/"bad.gpx"
        _gpx(path,[[(24,121,timestamps[0]),(24.001,121,timestamps[1])]])
        with pytest.raises(PlannedRouteConflict):
            save_recorded_version(root,{**request,"recordings":[{**request["recordings"][0],"source_ref":path.name}]})


def test_sampling_dropout_does_not_become_observed_camp(recorded):
    root,request=recorded
    path=root/"gap.gpx"
    _gpx(path,[[(24,121,"2026-10-01T06:00:00Z"),(24,121,"2026-10-01T14:00:00Z"),
                (24.001,121,"2026-10-01T14:10:00Z")]])
    value=save_recorded_version(root,{**request,"recordings":[{**request["recordings"][0],"source_ref":path.name}]})
    metrics=value["preview"]["metrics"]
    assert metrics["camp_candidate_seconds"]==0
    assert metrics["unobserved_seconds"]==8*3600
    assert value["preview"]["graph"]["gaps"][0]["code"]=="sampling_time_gap"


def test_concurrent_saves_publish_one_version(recorded):
    root,request=recorded
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(lambda _:save_recorded_version(root,request),range(2)))
    assert values[0]["manifest"]==values[1]["manifest"]
    assert {v["replayed"] for v in values}=={True,False}
    assert len(list_recorded_versions(root)["versions"])==1


def test_saved_output_tamper_and_manifest_mismatch_fail_closed(recorded):
    root,request=recorded
    value=save_recorded_version(root,request)
    version=value["manifest"]["version_id"]
    with pytest.raises(PlannedRouteConflict):
        get_recorded_version(root,version,"0"*64)
    path=root/value["bundle_ref"]/"itinerary.json"
    path.write_text('{"time_role":"planned_estimate"}')
    with pytest.raises(PlannedRouteConflict,match="changed"):
        get_recorded_version(root,version)




def test_operator_confirmed_camp_is_bound_to_stationarity_without_double_counting(recorded):
    root,request=recorded
    confirmation={"source_ref":request["recordings"][1]["source_ref"],"start_point_index":12,"end_point_index":72,
                  "observer_alias":"fixture-human","explicit_confirmation":True,"note":"fixture-observed camp"}
    bundle=save_recorded_version(root,{**request,"camp_confirmations":[confirmation]})
    preview=bundle["preview"]
    assert preview["metrics"]["camp_confirmed_seconds"]==5*3600
    assert preview["metrics"]["camp_candidate_seconds"]==7*3600
    assert preview["metrics"]["rest_seconds"]==600+7*3600
    event=preview["itinerary"]["camp_confirmations"][0]
    assert event["duration_seconds"]==5*3600 and event["included_in_rest_seconds"]
    assert {event["start_point_index"], event["end_point_index"]} <= {node["point_index"] for node in preview["graph"]["nodes"]}
    assert event["evidence_role"]=="operator_statement_bound_to_device_stationarity"
    assert preview["comparison"]["planned"]["camp_time_comparison"]["recorded_confirmed_seconds"]==5*3600
    with pytest.raises(PlannedRouteConflict,match="double-count"):
        save_recorded_version(root,{**request,"camp_confirmations":[confirmation,confirmation],"idempotency_key":"duplicate.camp"})
    with pytest.raises(PlannedRouteConflict,match="stationary"):
        save_recorded_version(root,{**request,"camp_confirmations":[{**confirmation,"source_ref":request["recordings"][0]["source_ref"],
            "start_point_index":0,"end_point_index":2}],"idempotency_key":"moving.camp"})


def test_spatial_dropout_remains_gap_even_with_short_timestamp_interval(recorded):
    root,request=recorded
    path=root/"jump.gpx"
    _gpx(path,[[(24,121,"2026-10-01T06:00:00Z"),(24.001,121,"2026-10-01T06:01:00Z"),
                (24.021,121,"2026-10-01T06:02:00Z"),(24.022,121,"2026-10-01T06:03:00Z")]])
    value=save_recorded_version(root,{**request,"recordings":[{**request["recordings"][0],"source_ref":path.name}]})
    preview=value["preview"]
    assert preview["graph"]["gaps"][0]["code"]=="recorded_geometry_gap"
    assert preview["metrics"]["distance_m"]<300
    assert preview["metrics"]["unobserved_seconds"]==60
    assert not any(e["start_point_index"]<2<=e["end_point_index"] for e in preview["graph"]["edges"])
