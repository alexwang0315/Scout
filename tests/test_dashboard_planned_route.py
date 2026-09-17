"""Exercise shipped Planned controls in a DOM; real browser evidence is separate."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/admin/scout-planned-route.js"


def _probe(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for Dashboard DOM checks")
    setup = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {JSDOM} = require("jsdom");
const dom = new JSDOM("<!doctype html><html><head></head><body><main id='root'></main></body></html>", {url:"http://localhost/",runScripts:"outside-only"});
const win = dom.window;
win.eval(fs.readFileSync(process.argv[1],"utf8"));
const ui = win.ScoutPlannedRoute;
let project = "project-a", pendingPreview = null, failSaveOnce = false, refreshes = 0;
const calls = [], versions = [], runs = [];
let selection = {subject_kind:"golden_gpx",selection_sha256:null}, saved = null;
const points = [{lat:24,lon:121},{lat:24.001,lon:121.001},{lat:24.002,lon:121.002}];
const anchors = [{anchor_id:"golden.p0.i0",label:"起點",source_id:"golden",part_index:0,point_index:0,...points[0]},
 {anchor_id:"golden.p0.i1",label:"岔路",source_id:"golden",part_index:0,point_index:1,...points[1]},
 {anchor_id:"ref.one.p0.i0",label:"支線岔路",source_id:"ref.one",part_index:0,point_index:0,...points[1]},
 {anchor_id:"ref.one.p0.i2",label:"山頭",source_id:"ref.one",part_index:0,point_index:2,...points[2]}];
const catalog = {source_snapshot_sha256:"c".repeat(64),source_hashes:{"golden.gpx":"g".repeat(64)},golden_source_id:"golden",anchors,
 sources:[{source_id:"golden",label:"Golden",kind:"golden",parts:[points]},{source_id:"ref.one",label:"支線Ref",kind:"reference_gpx",parts:[points]}]};
function analysisJob(status="queued", extra={}) {
 const binding={project_id:project,version_id:saved.manifest.version_id,manifest_sha256:saved.manifest.manifest_sha256,geometry_sha256:"g".repeat(64),itinerary_sha256:"t".repeat(64)};
 return {...binding,run_id:"analysis."+"b".repeat(32),binding,status,stage:status==="queued"?"prepare":"analysis",attempt:1,can_resume:status==="interrupted",execution_location:"scout",candidate_only:true,runtime_safety_truth:false,...extra};
}
const route = {type:"FeatureCollection",features:[
 {type:"Feature",properties:{source_id:"ref.one",source_kind:"reference_gpx",part_index:0,source_start_index:0,source_end_index:2,length_m:300,direction:"forward"},geometry:{type:"LineString",coordinates:[[121,24],[121.001,24.001]]}},
 {type:"Feature",properties:{source_id:"ref.one",source_kind:"reference_gpx",part_index:0,source_start_index:2,source_end_index:0,length_m:300,direction:"reverse"},geometry:{type:"LineString",coordinates:[[121.004,24.004],[121.003,24.003]]}}]};
function preview(request) {return {project_id:project,status:"needs_review",preview_sha256:"p".repeat(64),request,
 route_geojson:route,golden_geojson:{type:"FeatureCollection",features:[route.features[0]]},
 comparison:{geometry_changed:true,golden_length_m:300,planned_length_m:600,added_distance_m:300},
 itinerary:{days:[{day_id:"D1",departure_at:"2026-09-12T06:00:00+08:00",arrival_at:"2026-09-12T08:40:00+08:00",moving_minutes:120,rest_minutes:40}],timeline:[{kind:"fixed_stop",label:"岔路",duration_minutes:40,start_at:"2026-09-12T07:00:00+08:00",end_at:"2026-09-12T07:40:00+08:00"}]},
 issues:[{issue_id:"gap.1",code:"recording_gap",message:"source gap remains"}],review_requirements:{required_issue_ids:["gap.1"]}};}
const tick = () => new Promise(resolve=>setTimeout(resolve,0));
async function flush(){for(let i=0;i<8;i++) await tick();}
function el(selector){const found=win.document.querySelector(selector);assert.ok(found,selector);return found;}
function fill(selector,value){const input=el(selector);input.value=value;input.dispatchEvent(new win.Event(input.tagName==="SELECT"?"change":"input",{bubbles:true}));}
function click(action){el(`[data-planned-action="${action}"]`).click();}
function check(selector){const input=el(selector);input.checked=true;input.dispatchEvent(new win.Event("change",{bubbles:true}));}
const host = {projectId:()=>project,apiBase:()=>"",refreshAnalysis:async()=>{refreshes++;},
 fetchJson:async path=>{calls.push({method:"GET",path});if(path.endsWith("/catalog"))return {...catalog,project_id:project};if(path.endsWith("/versions"))return {versions,head_version_id:versions[0]?.version_id||null};if(path.endsWith("/analysis-selection"))return selection;if(path.includes("/versions/"))return saved;if(/\/analysis-runs(?:\?|$)/.test(path))return {project_id:project,runs:runs.map(job=>({...job}))};if(path.includes("/analysis-runs/"))return {...runs.find(job=>path.endsWith(job.run_id))};throw Error(path);},
 postJson:async(path,body)=>{calls.push({method:"POST",path,body:JSON.parse(JSON.stringify(body))});
  if(path.endsWith("/preview")){if(pendingPreview)return pendingPreview;return preview(body);}
  if(path.endsWith("/versions")){if(failSaveOnce){failSaveOnce=false;throw Error("response timeout");}saved={manifest:{version_id:"plan."+"a".repeat(16),manifest_sha256:"m".repeat(64)},preview:preview(body.request),review:null,source_status:{status:"current"}};if(!versions.length)versions.push({...saved.manifest,status:"needs_review"});return {...saved.manifest};}
  if(path.endsWith("/review")){saved.review={status:"reviewed_planning_candidate",review_sha256:"r".repeat(64)};return saved.review;}
  if(path.endsWith("/analysis-selection")){selection={...body,selection_sha256:"s".repeat(64)};return selection;}
  if(path.endsWith("/analysis-runs")){const job=analysisJob();runs.unshift(job);return job;}
  if(path.endsWith("/resume")){const job=runs.find(item=>path.includes(item.run_id));Object.assign(job,{status:"queued",attempt:job.attempt+1,can_resume:false});return {...job};}
  throw Error(path);},
 render:()=>{win.document.getElementById("root").innerHTML=ui.render({projectId:project});ui.bind(host);}};
host.render();
'''
    code = setup + "\n(async()=>{ await flush();\n" + probe + r'''
})().then(result=>{process.stdout.write(JSON.stringify(result));dom.window.close();},error=>{console.error(error);dom.window.close();process.exitCode=1;});
'''
    run = subprocess.run([node, "-e", code, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(run.stdout)


def test_named_segment_preview_save_review_selection_and_gap_paths():
    result = _probe(r'''
fill("[data-planned-human-text]","沿 Golden");
fill('[data-planned-field="departure"]',"2026-09-12T06:00");
fill('[data-planned-editor="kind"]',"branch");
fill('[data-planned-editor="at"]',"golden.p0.i1");
fill('[data-planned-editor="sourceId"]',"ref.one");
fill('[data-planned-editor="sourceFrom"]',"ref.one.p0.i0:0");
fill('[data-planned-editor="sourceTo"]',"ref.one.p0.i2:2");
click("add-operation");click("preview");await flush();
const requested=calls.find(call=>call.path.endsWith("/preview")).body;
assert.equal(requested.departure_at,"2026-09-12T06:00:00+08:00");
assert.deepEqual(requested.operations[0].selection,{source_id:"ref.one",part_index:0,start_index:0,end_index:2,round_trip:true});
assert.equal(win.document.querySelectorAll('[data-planned-map-layer="planned"]').length,2);
for(const path of win.document.querySelectorAll('[data-planned-map-layer="planned"]'))assert.equal((path.getAttribute("d").match(/M/g)||[]).length,1);
assert.ok(el('[data-planned-itinerary]').textContent.includes("07:40:00"));
click("save");await flush();
assert.equal(el('[data-planned-action="review"]').disabled,true);
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
assert.equal(el('[data-planned-action="review"]').disabled,true);
check('[data-planned-review-issue="gap.1"]');click("review");await flush();
assert.equal(el('[data-planned-action="select"]').disabled,false);
click("select");await flush();
assert.equal(refreshes,1);
assert.equal(calls.find(call=>call.path.endsWith("/review")).body.expected_manifest_sha256,"m".repeat(64));
assert.equal(calls.find(call=>call.path.endsWith("/analysis-selection")&&call.method==="POST").body.subject_kind,"planned_gpx");
assert.equal(el('[data-planned-export="gpx"]').tagName,"BUTTON");
assert.ok(el('[data-planned-export="gpx"]').dataset.plannedExportUrl.includes("/export/plan."));
return {named_selection:true,separate_gap_paths:2,review_bound:true,analysis_refreshes:refreshes};
''')
    assert result == {"named_selection": True, "separate_gap_paths": 2, "review_bound": True, "analysis_refreshes": 1}


def test_late_preview_cannot_enter_another_workspace():
    result = _probe(r'''
let finish;pendingPreview=new Promise(resolve=>{finish=resolve;});
click("preview");await tick();
project="project-b";host.render();await flush();
finish({...preview({human_text:"old A"}),project_id:"project-a"});await flush();
assert.equal(el("[data-planned-workbench]").dataset.plannedWorkbench,"project-b");
assert.equal(win.document.querySelector("[data-planned-preview]"),null);
assert.equal(el('[data-planned-action="save"]').disabled,true);
return {old_project_ignored:true};
''')
    assert result == {"old_project_ignored": True}


def test_uncertain_save_reuses_identity_and_input_edit_invalidates_review():
    result = _probe(r'''
click("preview");await flush();failSaveOnce=true;click("save");await flush();
assert.ok(el("[data-planned-status]").textContent.includes("response timeout"));
click("save");await flush();
const saves=calls.filter(call=>call.method==="POST"&&call.path.endsWith("/versions"));
assert.equal(saves.length,2);assert.equal(saves[0].body.idempotency_key,saves[1].body.idempotency_key);
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
check('[data-planned-review-issue="gap.1"]');
assert.equal(el('[data-planned-action="review"]').disabled,false);
fill('[data-planned-human-text]',"改營地");
assert.equal(el('[data-planned-action="save"]').disabled,true);
assert.equal(el('[data-planned-action="review"]').disabled,true);
assert.equal(el('[data-planned-action="select"]').disabled,true);
assert.ok(el('[data-planned-preview-status]').textContent.includes("過期"));
return {reused_identity:true,stale_actions_disabled:true};
''')
    assert result == {"reused_identity": True, "stale_actions_disabled": True}


def test_six_axis_subject_displays_new_axis_and_labels_historical_content():
    result = _probe(r'''
const subject={project_id:project,subject_kind:"planned_gpx",subject_id:"planned.a",selected_plan_version_id:"plan."+"a".repeat(16),analysis_revision:"a".repeat(64),geometry_fingerprint:"g".repeat(64),
 planned_route_geojson:route,checkpoints:[{candidate_id:"planned.cp.branch",label:"新支線CP",point_index:9,lat:24.004,lon:121.004}],segments:[{segment_id:"new.branch",start_point_index:3,end_point_index:9,length_m:300}],itinerary:preview({}).itinerary,
 dependencies:{navigation:{status:"coverage_needed",reason:"新支線需要追加 DEM"}}};
const header=ui.renderSubject(subject,"outdoor-navigation");
assert.ok(header.includes("新支線CP"));assert.ok(header.includes("new.branch"));assert.ok(header.includes("coverage_needed"));
const wrapped=ui.wrapHistorical(header+"<section>old golden map</section>",header,"outdoor-navigation",subject);
const parsed=new JSDOM(wrapped).window.document;
assert.equal(parsed.querySelectorAll("[data-analysis-subject]").length,1);
assert.equal(parsed.querySelector("[data-planned-legacy-golden]").hasAttribute("open"),false);
assert.ok(parsed.querySelector("[data-planned-legacy-golden]").textContent.includes("old golden map"));
return {new_axis_visible:true,historical_content_labeled:true};
''')
    assert result == {"new_axis_visible": True, "historical_content_labeled": True}


def test_analysis_run_controls_restore_resume_and_only_update_job_panel():
    result = _probe(r'''
assert.equal(el('[data-planned-run-action="start"]').disabled,true);
click("preview");await flush();click("save");await flush();
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
check('[data-planned-review-issue="gap.1"]');click("review");await flush();
const savedVersion=saved.manifest.version_id;
assert.ok(calls.some(call=>call.method==="GET"&&call.path.endsWith(`/analysis-runs?version_id=${savedVersion}`)));
assert.equal(el('[data-planned-run-action="start"]').disabled,false);
const input=el('[data-planned-human-text]');input.focus();
el('[data-planned-run-action="start"]').click();await flush();
assert.equal(el('[data-planned-human-text]'),input);
assert.equal(win.document.activeElement,input);
assert.equal(el('[data-planned-analysis-run]').dataset.plannedAnalysisRunState,"queued");
assert.ok(el('[data-planned-analysis-run]').textContent.includes("scout"));
assert.equal(el('[data-planned-run-action="start"]').disabled,true);
const started=calls.find(call=>call.method==="POST"&&call.path.endsWith("/analysis-runs"));
assert.equal(started.body.version_id,savedVersion);
assert.equal(started.body.expected_manifest_sha256,saved.manifest.manifest_sha256);
assert.equal(started.body.explicit_confirmation,true);
const runId=runs[0].run_id;
Object.assign(runs[0],{status:"interrupted",can_resume:true,error:{code:"worker_interrupted",message:"persisted job is recoverable"}});
el('[data-planned-run-action="read"]').click();await flush();
assert.equal(el('[data-planned-human-text]'),input);
assert.ok(el('[data-planned-analysis-run]').textContent.includes("worker_interrupted"));
assert.equal(el('[data-planned-run-action="resume"]').disabled,false);
el('[data-planned-run-action="resume"]').click();await flush();
assert.equal(el('[data-planned-analysis-run]').dataset.plannedAnalysisRun,runId);
assert.equal(runs[0].attempt,2);
assert.equal(calls.filter(call=>call.method==="POST"&&call.path.endsWith("/analysis-runs")).length,1);
Object.assign(runs[0],{status:"completed_with_gaps",stage:"complete",can_resume:true,updated_at:"2026-09-10T08:00:00Z",preparation:{status:"partial",summary:"DEM incomplete"},projections:{navigation:{status:"partial",summary:"新支線 DEM 待補"}}});
el('[data-planned-run-action="read"]').click();await flush();
assert.equal(refreshes,1);assert.ok(el('[data-planned-analysis-run]').textContent.includes("新支線 DEM 待補"));
el('[data-planned-run-action="read"]').click();await flush();assert.equal(refreshes,1);
project="project-b";host.render();await flush();project="project-a";host.render();await flush();
fill('[data-planned-version]',savedVersion);click("restore");await flush();
assert.equal(el('[data-planned-analysis-run]').dataset.plannedAnalysisRun,runId);
assert.equal(el('[data-planned-run-action="resume"]').disabled,false);
assert.equal(calls.filter(call=>call.method==="POST"&&call.path.endsWith("/analysis-runs")).length,1);
fill('[data-planned-human-text]',"edited draft");
assert.equal(el('[data-planned-run-action="start"]').disabled,true);
assert.equal(el('[data-planned-run-action="resume"]').disabled,true);
return {version_filtered:true,original_form_retained:true,persisted_same_run:true,explicit_resume:true,dirty_guard:true};
''')
    assert result == {"version_filtered": True, "original_form_retained": True, "persisted_same_run": True, "explicit_resume": True, "dirty_guard": True}


def test_uncertain_analysis_start_reuses_request_and_source_conflict_is_visible():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
check('[data-planned-review-issue="gap.1"]');click("review");await flush();
const posted=[],basePost=host.postJson;
host.postJson=async(path,body)=>{if(!path.endsWith("/analysis-runs"))return basePost(path,body);posted.push(JSON.parse(JSON.stringify(body)));throw Error(posted.length===1?"connection interrupted":"HTTP 409 planned_analysis_sources_changed");};
el('[data-planned-run-action="start"]').click();await flush();
assert.ok(el('[data-planned-analysis-run-status]').textContent.includes("connection interrupted"));
el('[data-planned-run-action="start"]').click();await flush();
assert.equal(posted.length,2);assert.equal(posted[0].idempotency_key,posted[1].idempotency_key);
assert.ok(el('[data-planned-analysis-run-status]').textContent.includes("HTTP 409 planned_analysis_sources_changed"));
assert.equal(win.document.querySelector('[data-planned-analysis-run]'),null);
assert.equal(el('[data-planned-run-action="start"]').disabled,true);
return {request_identity_reused:true,source_conflict_visible:true};
''')
    assert result == {"request_identity_reused": True, "source_conflict_visible": True}


def test_completed_run_metadata_waits_for_receipt_without_claiming_reanalysis_needed():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
const job=analysisJob("completed_with_gaps",{stage:"complete",can_resume:true,preparation:{status:"completed",summary:"5/5 terrain parts prepared"},projections:Object.fromEntries(["permission","pace_fit","architecture","navigation","weather","route_context"].map(role=>[role,{status:"partial",summary:`${role} assessed with explicit gaps`}])),artifact_ref:"outputs/report.json"});
const baseFetch=host.fetchJson;
host.fetchJson=async path=>{
 if(/\/analysis-runs(?:\?|$)/.test(path)){const {preparation,projections,...metadata}=job;return {project_id:project,runs:[metadata]};}
 if(path.endsWith(job.run_id))return job;
 return baseFetch(path);
};
el('[data-planned-run-action="list"]').click();await flush();
const panel=el('[data-planned-analysis-run]');
assert.equal(panel.dataset.plannedAnalysisRunState,"completed_with_gaps");
assert.ok(el('[data-planned-run-receipt="pending"]').textContent.includes("作業已完成"));
assert.ok(panel.textContent.includes("結果尚未讀取"));
assert.ok(!panel.textContent.includes("尚未完成"));assert.ok(!panel.textContent.includes("needs_reanalysis"));
assert.equal(el('[data-planned-run-action="read"]').disabled,false);
el('[data-planned-run-action="read"]').click();await flush();
assert.equal(win.document.querySelector('[data-planned-run-receipt="pending"]'),null);
assert.ok(el('[data-planned-analysis-run]').textContent.includes("5/5 terrain parts prepared"));
assert.ok(el('[data-planned-analysis-run]').textContent.includes("permission assessed with explicit gaps"));
return {metadata_not_misclassified:true,explicit_read_loads_receipt:true};
''')
    assert result == {"metadata_not_misclassified": True, "explicit_read_loads_receipt": True}


def test_late_analysis_detail_cannot_enter_another_project_or_version():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
check('[data-planned-review-issue="gap.1"]');click("review");await flush();
el('[data-planned-run-action="start"]').click();await flush();
const oldJob={...runs[0]},baseFetch=host.fetchJson;let finish;
host.fetchJson=path=>path.endsWith(oldJob.run_id)?new Promise(resolve=>{finish=resolve;}):baseFetch(path);
el('[data-planned-run-action="read"]').click();await tick();
project="project-b";host.render();await flush();
finish({...oldJob,status:"completed",updated_at:"late A"});await flush();
assert.equal(el('[data-planned-workbench]').dataset.plannedWorkbench,"project-b");
assert.equal(win.document.querySelector('[data-planned-analysis-run]'),null);assert.equal(refreshes,0);
project="project-a";host.render();await flush();fill('[data-planned-version]',saved.manifest.version_id);click("restore");await flush();
el('[data-planned-run-action="read"]').click();await tick();
const nextVersion="plan."+"c".repeat(16);
saved={...saved,manifest:{...saved.manifest,version_id:nextVersion,manifest_sha256:"n".repeat(64)}};
versions.push({...saved.manifest});click("refresh");await flush();fill('[data-planned-version]',nextVersion);click("restore");await flush();
finish({...oldJob,status:"completed",updated_at:"late old version"});await flush();
assert.equal(el('[data-planned-review-version]').dataset.plannedReviewVersion,nextVersion);
assert.equal(win.document.querySelector('[data-planned-analysis-run]'),null);
assert.equal(refreshes,0);
return {late_project_ignored:true,late_version_ignored:true};
''')
    assert result == {"late_project_ignored": True, "late_version_ignored": True}


def test_six_force_results_require_exact_version_geometry_timing_and_authority():
    result = _probe(r'''
saved={manifest:{version_id:"plan."+"a".repeat(16),manifest_sha256:"m".repeat(64)}};
const job=analysisJob("completed_with_gaps"),roles=["permission","pace_fit","architecture","navigation","weather","route_context"];
job.projections=Object.fromEntries(roles.map(role=>[role,{status:role==="navigation"?"partial":"ready",summary:`${role} 真實評估摘要`,artifact_ref:`outputs/planned_analysis/${job.run_id}/${role}.json`,artifact_sha256:"f".repeat(64),input_binding:{...job.binding},candidate_only:true,runtime_safety_truth:false,missing_inputs:role==="navigation"?[{code:"dem_missing",reason:"新支線缺少 DEM",source_ref:"dem.tif"}]:[],result:{decision:"candidate_review",answerability:"partial",field_answer:`${role} field evidence`,deep_payload:"lazy evidence",...(role==="architecture"?{cp_graph:{nodes:[{candidate_id:"planned.new.cp",point_index:9}],edges:[{segment_id:"planned.new.edge"}]}}:{})}}]));
job.projections.permission.result.field_answer="不要在此停留，請先前往下一個安全CP";
job.projections.navigation.result.required_actions=["補充 Planned DEM 資料"];
const rawBefore=JSON.stringify(job.projections);
const subject={project_id:project,subject_kind:"planned_gpx",subject_id:saved.manifest.version_id,selected_plan_version_id:saved.manifest.version_id,planned_bundle_sha256:saved.manifest.manifest_sha256,analysis_revision:"a".repeat(64),geometry_fingerprint:job.binding.geometry_sha256,timing_fingerprint:job.binding.itinerary_sha256,planned_analysis:job,dependencies:Object.fromEntries(roles.map(role=>[role,{status:role==="navigation"?"partial_planned_analysis":"current_planned_analysis"}]))};
for(const role of roles){
 win.document.getElementById("root").innerHTML=ui.renderSubject(subject,"outdoor-"+role.replaceAll("_","-"));ui.bind(host);
 const panel=el(`[data-planned-force-projection="${role}"]`);
 assert.equal(panel.dataset.plannedForceRun,job.run_id);assert.equal(panel.dataset.plannedForceCurrent,"true");
 assert.ok(panel.textContent.includes(`${role} 真實評估摘要`));assert.ok(panel.textContent.includes(`/${role}.json`));
 assert.ok(panel.textContent.includes("評估結果"));assert.ok(!panel.textContent.includes("現場摘要"));
 assert.ok(!panel.textContent.includes(job.projections[role].result.field_answer));
 assert.ok(!panel.textContent.includes("lazy evidence"));
 const details=panel.querySelector('[data-planned-result-details]');details.open=true;details.dispatchEvent(new win.Event("toggle"));
 assert.ok(details.textContent.includes("lazy evidence"));
 assert.ok(details.textContent.includes(job.projections[role].result.field_answer));
 if(role==="navigation"){assert.ok(el('[data-planned-force-limitations]').textContent.includes("新支線缺少 DEM"));assert.ok(panel.textContent.includes("準備／待補項目"));assert.ok(!panel.textContent.includes("需要的動作"));}
 if(role==="architecture")assert.ok(el('[data-planned-force-cp-graph]').textContent.includes("planned.new.cp"));
}
for(const key of ["project_id","version_id","manifest_sha256","geometry_sha256","itinerary_sha256","run_id"]){
 const wrong=JSON.parse(JSON.stringify(subject));wrong.planned_analysis.projections.navigation.input_binding[key]="wrong";
 const markup=ui.renderSubject(wrong,"outdoor-navigation");assert.ok(!markup.includes('data-planned-force-projection="navigation"'));assert.ok(markup.includes('data-planned-force-binding-error'));
}
for(const mutation of [value=>value.planned_analysis.status="stale",value=>value.planned_analysis.projections.navigation.runtime_safety_truth=true,value=>value.planned_analysis.candidate_only=false]){
 const wrong=JSON.parse(JSON.stringify(subject));mutation(wrong);assert.ok(!ui.renderSubject(wrong,"outdoor-navigation").includes('data-planned-force-projection="navigation"'));
}
assert.equal(JSON.stringify(job.projections),rawBefore);
return {six_real_projections:6,full_binding_required:true,stale_hidden:true,lazy_summary:true,limitations_visible:true,field_in_details_only:true};
''')
    assert result == {"six_real_projections": 6, "full_binding_required": True, "stale_hidden": True, "lazy_summary": True, "limitations_visible": True, "field_in_details_only": True}


def test_planned_light_tables_and_missing_reasons_are_readable_on_dark_page():
    result = _probe(r'''
win.document.body.style.color="#edf3f5";win.document.body.style.backgroundColor="#0c1512";
win.document.getElementById("root").innerHTML=`<section class="planned-subject">
 <table class="planned-table"><thead><tr><th>評估欄位</th></tr></thead><tbody><tr><td data-test-main-body>保留深底白字</td></tr></tbody></table>
 <div class="planned-issues"><p data-test-missing>新支線缺少資料</p><section data-planned-table="contrast" data-planned-total-rows="1"><div class="planned-map-tools"><span data-test-pagination>完整 1 筆</span></div>
 <table class="planned-table"><thead><tr><th>原因</th></tr></thead><tbody><tr><td data-test-reason>缺少 safety buffer</td></tr></tbody></table></section></div>
 <div class="planned-map"><div class="planned-map-tools"><span data-test-map>原有 map 工具</span></div></div>
 </section>`;
ui.bind(host);
const color=(selector,key="color")=>win.getComputedStyle(el(selector))[key];
const luminance=css=>css.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
const contrast=(fg,bg)=>{const a=luminance(fg),b=luminance(bg);return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);};
const ratios=[contrast(color('.planned-table th'),color('.planned-table th','backgroundColor')),
 contrast(color('[data-test-missing]'),color('.planned-issues','backgroundColor')),
 contrast(color('[data-test-reason]'),color('.planned-issues','backgroundColor')),
 contrast(color('[data-test-pagination]'),color('[data-planned-table] > .planned-map-tools','backgroundColor'))];
assert.ok(ratios.every(value=>value>=4.5),JSON.stringify(ratios));
assert.equal(color('[data-test-main-body]'),"rgb(237, 243, 245)");
assert.equal(color('[data-test-map]'),"rgb(237, 243, 245)");
assert.ok(contrast(color('[data-test-main-body]'),color('body','backgroundColor'))>=4.5);
return {light_surfaces_readable:true,main_body_preserved:true,map_style_preserved:true,minimum_contrast:Math.min(...ratios)};
''')
    assert result["light_surfaces_readable"] is True
    assert result["main_body_preserved"] is True
    assert result["map_style_preserved"] is True
    assert result["minimum_contrast"] >= 4.5


def test_large_catalog_and_timeline_keep_complete_geometry_and_page_to_last_record():
    result = _probe(r'''
const goldenPoints=Array.from({length:9290},(_,index)=>({lat:24+index/1000000,lon:121+index/1000000,ele:1000}));
const sources=Array.from({length:25},(_,index)=>({source_id:index?`ref.${index}`:"golden",label:`GPX ${index}`,kind:index?"reference_gpx":"golden",parts:[index?Array.from({length:5500},(_,p)=>({lat:24+p/1000000,lon:121+index/100+p/1000000})):goldenPoints]}));
const largeAnchors=Array.from({length:2034},(_,index)=>({anchor_id:`anchor.${index}`,label:`CP ${index}`,source_id:index%25?`ref.${index%25}`:"golden",part_index:0,point_index:index%5000,lat:24.001,lon:121.001}));
Object.assign(catalog,{sources,anchors:largeAnchors});click("refresh");await flush();
assert.equal(el('[data-planned-editor="at"]').options.length,83);
fill('[data-planned-anchor-scope]',"all");
assert.equal(el('[data-planned-editor="at"]').options.length,101);
click("anchor-next");assert.ok(el('[data-planned-anchor-count]').textContent.includes("101–200"));
fill('[data-planned-anchor-search]',"CP 2033");click("filter-anchors");
assert.equal(el('[data-planned-editor="at"]').options.length,2);
const timeline=goldenPoints.slice(1).map((_,index)=>({kind:"move",from_point_index:index,point_index:index+1,duration_minutes:index<8790?0.1:null,method:index<8790?"source_elapsed":"unknown",departure_at:index<8790?new Date(1790812800000+index*6000).toISOString():null,arrival_at:index<8790?new Date(1790812800000+(index+1)*6000).toISOString():null}));
timeline.splice(4000,0,{kind:"fixed_stop",point_index:4000,label:"40 min stay",duration_minutes:40,start_at:"2026-10-01T06:00:00+08:00",end_at:"2026-10-01T06:40:00+08:00"});
const features=[goldenPoints.slice(0,5000),goldenPoints.slice(5000)].map(part=>({type:"Feature",properties:{source_id:"golden"},geometry:{type:"LineString",coordinates:part.map(point=>[point.lon,point.lat])}}));
let largePreview;
const basePost=host.postJson;
host.postJson=async(path,body)=>{if(!path.endsWith("/preview"))return basePost(path,body);largePreview={...preview(body),route_geojson:{type:"FeatureCollection",features},golden_geojson:{type:"FeatureCollection",features},checkpoints:[{candidate_id:"new.cp",label:"planned CP",lat:24,lon:121}],itinerary:{...preview(body).itinerary,timeline}};return largePreview;};
const before=JSON.stringify(timeline);const started=Date.now();click("preview");await flush();const elapsed=Date.now()-started;
assert.equal(JSON.stringify(timeline),before);
assert.equal(win.document.querySelectorAll('[data-planned-map-anchor]').length,1);
assert.equal(win.document.querySelectorAll('[data-planned-map-layer="planned"]').length,2);
let vertexCount=0;for(const path of win.document.querySelectorAll('[data-planned-map-layer="planned"]'))vertexCount+=(path.getAttribute("d").match(/[ML]/g)||[]).length;
assert.equal(vertexCount,9290);
const tables=[...win.document.querySelectorAll('[data-planned-table]')];
const raw=tables.find(table=>table.dataset.plannedTable.endsWith(":raw"));
assert.equal(Number(raw.dataset.plannedTotalRows),9290);
assert.equal(raw.querySelectorAll("tbody tr").length,100);
assert.ok(win.document.querySelectorAll("tr").length<250);
el('[data-planned-raw-timeline]').open=true;
raw.querySelector('[data-planned-table-action="last"]').click();
const last=[...win.document.querySelectorAll('[data-planned-table]')].find(table=>table.dataset.plannedTable.endsWith(":raw"));
assert.equal(last.dataset.plannedTablePage,"92");
assert.ok(last.textContent.includes("p9288 → p9289"));
assert.equal(JSON.stringify(largePreview.itinerary.timeline),before);
return {catalog_points:sources.reduce((sum,source)=>sum+source.parts.reduce((count,part)=>count+part.length,0),0),timeline_records:timeline.length,full_planned_vertices:vertexCount,initial_render_ms:elapsed,last_page:92,raw_unchanged:true};
''')
    assert result["catalog_points"] == 141_290
    assert result["timeline_records"] == result["full_planned_vertices"] == 9_290
    assert result["last_page"] == 92
    assert result["raw_unchanged"] is True


def test_large_issue_review_remains_complete_and_requires_explicit_acknowledgment():
    result = _probe(r'''
const issues=Array.from({length:3136},(_,index)=>({issue_id:`source.issue.${index}`,code:"unlocated_waypoint",message:`Source issue ${index}`}));
catalog.issues=issues;click("refresh");await flush();
const initialPreview=preview;
preview=request=>({...initialPreview(request),issues,review_requirements:{required_issue_ids:issues.map(issue=>issue.issue_id)}});
click("preview");await flush();click("save");await flush();
assert.equal(win.document.querySelectorAll('[data-planned-review-issue]').length,100);
assert.equal(el('[data-planned-action="review"]').disabled,true);
for(const name of ["sources","geometry","timing","uncertainty"])check(`[data-planned-review-check="${name}"]`);
assert.equal(el('[data-planned-action="review"]').disabled,true);
check('[data-planned-review-all-issues]');
assert.equal(calls.filter(call=>call.method==="POST"&&call.path.endsWith("/review")).length,0);
assert.equal(el('[data-planned-action="review"]').disabled,false);
const reviewTable=[...win.document.querySelectorAll('[data-planned-table]')].find(table=>table.dataset.plannedTable.startsWith("review:"));
reviewTable.parentElement.open=true;reviewTable.querySelector('[data-planned-table-action="last"]').click();
assert.equal(el('[data-planned-review-issue="source.issue.3135"]').checked,true);
const last=el('[data-planned-review-issue="source.issue.3135"]');last.checked=false;last.dispatchEvent(new win.Event("change",{bubbles:true}));
assert.equal(el('[data-planned-action="review"]').disabled,true);
assert.equal(el('[data-planned-review-all-issues]').checked,false);
check('[data-planned-review-issue="source.issue.3135"]');click("review");await flush();
const request=calls.find(call=>call.method==="POST"&&call.path.endsWith("/review")).body;
assert.equal(request.acknowledged_issue_ids.length,3136);
assert.ok(request.acknowledged_issue_ids.includes("source.issue.3135"));
assert.equal(request.expected_manifest_sha256,"m".repeat(64));
return {issue_count:3136,visible_review_rows:36,explicit_version_review:true};
''')
    assert result == {"issue_count": 3_136, "visible_review_rows": 36, "explicit_version_review": True}


def test_exports_fetch_validate_and_preserve_original_bytes_for_all_formats():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
const exported="plan."+"a".repeat(16);
const specifications={gpx:{mime:"application/gpx+xml",suffix:".planned.gpx",bytes:Uint8Array.from([60,103,112,120,62,13,10,0,255])},manifest:{mime:"application/json",suffix:".manifest.json",bytes:Uint8Array.from([123,34,97,34,58,49,125,10])},bundle:{mime:"application/zip",suffix:".planned-bundle.zip",bytes:Uint8Array.from([80,75,3,4,0,255,1,2])}};
const fetched=[],blobs=[],downloads=[];
win.fetch=async(url,options)=>{const kind=url.split("/").at(-1),spec=specifications[kind];fetched.push({url,options});return {ok:true,status:200,headers:new Headers({"Content-Disposition":`attachment; filename="${exported}${spec.suffix}"`,"Content-Type":spec.mime,"X-Scout-Track-Role":"planned-candidate","X-Scout-Runtime-Safety-Truth":"false"}),arrayBuffer:async()=>spec.bytes.buffer};};
win.Blob=class {constructor(parts,options){this.parts=parts;this.type=options.type;}};
win.URL.createObjectURL=blob=>{blobs.push(blob);return `blob:http://localhost/export-${blobs.length}`;};win.URL.revokeObjectURL=()=>{};
win.HTMLAnchorElement.prototype.click=function(){downloads.push({filename:this.download,url:this.href});};
for(const kind of Object.keys(specifications)){
 el(`[data-planned-export="${kind}"]`).click();await flush();
 const state=el(`[data-planned-export-result="${kind}"]`);
 assert.equal(state.dataset.plannedExportStatus,"ready");assert.equal(Number(state.dataset.plannedExportBytes),specifications[kind].bytes.byteLength);
 assert.ok(state.textContent.includes("匯出產物已準備"));assert.ok(state.textContent.includes("尚未確認寫入使用者磁碟"));
 assert.deepEqual([...new Uint8Array(blobs.at(-1).parts[0])],[...specifications[kind].bytes]);
 assert.equal(downloads.at(-1).filename,exported+specifications[kind].suffix);
 assert.equal(fetched.at(-1).url,`/admin/pretrip/projects/project-a/planned-route/export/${exported}/${kind}`);
 assert.equal(fetched.at(-1).options.cache,"no-store");assert.equal(fetched.at(-1).options.redirect,"error");
}
assert.equal(fetched.length,3);assert.equal(downloads.length,3);
return {formats:3,original_bytes_preserved:true,native_file_claim:false};
''')
    assert result == {"formats": 3, "original_bytes_preserved": True, "native_file_claim": False}


def test_export_conflicts_and_unbound_headers_are_visible_without_download():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
let downloads=0,readBytes=0;
win.URL.createObjectURL=()=>{downloads++;return "blob:http://localhost/should-not-happen";};
win.fetch=async()=>({ok:false,status:409,json:async()=>({detail:{code:"planned_sources_stale",message:"Planning sources changed"}})});
el('[data-planned-export="gpx"]').click();await flush();
assert.equal(el('[data-planned-export-result="gpx"]').dataset.plannedExportStatus,"failed");
assert.ok(el('[data-planned-export-result="gpx"]').textContent.includes("HTTP 409 planned_sources_stale"));
for(const invalid of ["filename","role","runtime","type"]){
 win.fetch=async()=>({ok:true,status:200,headers:new Headers({"Content-Disposition":`attachment; filename="${invalid==="filename"?"another": "plan."+"a".repeat(16)+".planned.gpx"}"`,"Content-Type":invalid==="type"?"text/html":"application/gpx+xml","X-Scout-Track-Role":invalid==="role"?"recorded":"planned-candidate","X-Scout-Runtime-Safety-Truth":invalid==="runtime"?"true":"false"}),arrayBuffer:async()=>{readBytes++;return new ArrayBuffer(4);}});
 el('[data-planned-export="gpx"]').click();await flush();
 assert.equal(el('[data-planned-export-result="gpx"]').dataset.plannedExportStatus,"failed");
}
assert.equal(downloads,0);assert.equal(readBytes,0);
return {conflict_visible:true,invalid_header_cases:4,downloads:0};
''')
    assert result == {"conflict_visible": True, "invalid_header_cases": 4, "downloads": 0}


def test_late_export_response_cannot_download_after_project_switch():
    result = _probe(r'''
click("preview");await flush();click("save");await flush();
let finish,downloaded=0;win.fetch=()=>new Promise(resolve=>{finish=resolve;});
win.URL.createObjectURL=()=>{downloaded++;return "blob:http://localhost/stale";};
el('[data-planned-export="gpx"]').click();await tick();
project="project-b";host.render();await flush();
finish({ok:true,status:200,headers:new Headers({"Content-Disposition":'attachment; filename="plan.'+"a".repeat(16)+'.planned.gpx"',"Content-Type":"application/gpx+xml","X-Scout-Track-Role":"planned-candidate","X-Scout-Runtime-Safety-Truth":"false"}),arrayBuffer:async()=>new ArrayBuffer(4)});await flush();
assert.equal(downloaded,0);assert.equal(win.document.querySelector('[data-planned-export-result]'),null);
return {stale_project_ignored:true,downloads:0};
''')
    assert result == {"stale_project_ignored": True, "downloads": 0}
