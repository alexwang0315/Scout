"""Exercise shipped W1-W4 editors and Recorded guards in DOM; browser proof is separate."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def probe(script):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Scout Node runtime is required for DOM tests")
    setup = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const crypto = require("node:crypto");
const {JSDOM} = require("jsdom");
const dom = new JSDOM("<!doctype html><html><head></head><body><main id='root'></main></body></html>", {url:"http://localhost/",runScripts:"outside-only"});
const win = dom.window;
Object.defineProperty(win,"crypto",{value:crypto.webcrypto});
win.eval(fs.readFileSync(process.argv[1],"utf8"));
win.eval(fs.readFileSync(process.argv[2],"utf8"));
const ui=win.ScoutPlannedRoute, ext=win.ScoutPlannedReviewUI;
const versionId="plan."+"1".repeat(24), manifestSha="2".repeat(64), geometrySha="3".repeat(64), itinerarySha="4".repeat(64), catalogSha="5".repeat(64);
let project="project-a", context=null, badContext=false, failContextOnce=false, refreshes=0, runNumber=0;
const calls=[], runs=[];
const points=[{lat:24,lon:121,ele:100},{lat:24.001,lon:121.001,ele:200},{lat:24.002,lon:121.002,ele:300}];
const catalog={source_snapshot_sha256:catalogSha,golden_source_id:"golden",anchors:points.map((p,i)=>({anchor_id:`golden.p0.i${i}`,label:`CP ${i}`,source_id:"golden",part_index:0,point_index:i,...p})),sources:[{source_id:"golden",label:"Golden",kind:"golden",parts:[points]}]};
const binding=()=>({project_id:project,version_id:versionId,manifest_sha256:manifestSha,geometry_sha256:geometrySha,itinerary_sha256:itinerarySha});
const route={type:"FeatureCollection",features:[{type:"Feature",properties:{source_id:"golden"},geometry:{type:"LineString",coordinates:points.map(p=>[p.lon,p.lat])}}]};
const originalRequest={human_text:"第三天在營地 A 紮營；隔天六點出發",departure_at:"2026-10-01T06:00:00+08:00",operations:[],route_selections:[],pace_mode:"source_preferred",source_snapshot_sha256:catalogSha};
function preview(request){return {status:"needs_review",preview_sha256:"6".repeat(64),geometry_sha256:geometrySha,itinerary_sha256:itinerarySha,request,route_geojson:route,checkpoints:points.map((p,i)=>({candidate_id:`cp.${i}`,point_index:i,label:`CP ${i}`,...p})),itinerary:{days:[{day_id:"D1",departure_at:request.departure_at,arrival_at:"2026-10-01T08:00:00+08:00",moving_minutes:120,rest_minutes:0}],timeline:[]},issues:[],review_required_issue_ids:[]};}
let saved={manifest:{...binding(),request:originalRequest},preview:preview(originalRequest),review:{status:"reviewed_planning_candidate",review_sha256:"7".repeat(64)},source_status:{status:"current"}};
function recordedContext(declaration,body){const sha=crypto.createHash("sha256").update(JSON.stringify(declaration)).digest("hex");return {project_id:project,version_id:versionId,revision_id:"context."+sha.slice(0,24),parent_revision_id:context?.revision_id||null,context_sha256:sha,context_ref:"reviews/context.json",subject_binding:binding(),declaration,source_hashes:{},is_current:true,candidate_only:true,runtime_safety_truth:false,writes_performed:true};}
function job(status="completed_with_gaps", withReport=false){
 const b={...binding(),review_context_sha256:context?.context_sha256||null,run_id:"analysis."+(++runNumber).toString(16).padStart(32,"0")};
 const value={...b,binding:b,status,attempt:1,stage:"analysis",execution_location:"scout",candidate_only:true,runtime_safety_truth:false,projections:{},preparation:{status:"completed"}};
 if(withReport){
  const report={project_id:project,status:"partial",decision:"DELAY",input_binding:b,candidate_only:true,runtime_safety_truth:false,
   required_outputs:{pretrip_decision:"DELAY",top_risk_sources:[{reason:"尚缺隊伍能力",source_ref:"pace.json"}],required_conditions:["補齊能力"],cp_graph:{nodes:[{point_index:0}],edges:[]},latest_turnaround:{status:"unknown"},suggested_stop_points:[],not_recommended_stop_points:[{point_index:1,reason:"待查"}],alternatives_or_short_routes:[{action:"重新檢視日程"}],pretrip_checklist:[{item:"equipment",status:"missing"}],residual_risk:["候選評估仍有缺資料"]},planned_timetable:{status:"unknown"},return_constraint:{status:"unknown"},camp_candidates:[],missing_inputs:[]};
  const raw=JSON.stringify(report),sha=crypto.createHash("sha256").update(raw).digest("hex");
  value.pretrip_report={status:"partial",decision:"DELAY",artifact_ref:"reports/pretrip.json",artifact_sha256:sha,input_binding:b,report,candidate_only:true,runtime_safety_truth:false};
  value.rawReport=raw;
 }
 return value;
}
function intentResult(body){
 let offset=0;const clauses=body.human_text.split("；").map((text,i)=>{const start=offset;offset+=Array.from(text).length+1;return {clause_id:`clause.${i+1}`,source_text:text,source_span:{start,end:start+Array.from(text).length},operation_indices:[i],route_intent_indices:[],status:text.includes("隔天")?"needs_clarification":"resolved"};});
 return {schema_version:"plannedItineraryIntent.v1",status:"needs_clarification",mode:body.use_configured_model?"configured_model":"deterministic",input_sha256:crypto.createHash("sha256").update(body.human_text).digest("hex"),source_snapshot_sha256:catalogSha,trip_start_at:body.departure_at,clauses,operations:[{kind:"camp",day_index:3},{kind:"depart",day_index:4}],route_intents:[],issues:[{code:"camp_departure_day_ambiguous",clause_id:clauses.at(-1).clause_id,message:"請指定離營日",choices:["D4","D5"]}],unresolved_clause_ids:[clauses.at(-1).clause_id],derived_constraints:[],validated_draft:body.use_configured_model?{actions:[{kind:"camp",day_index:3,source_text:clauses[0].source_text}]}:null};
}
const host={projectId:()=>project,apiBase:()=>"",refreshAnalysis:async()=>{refreshes++;},
 fetchJson:async path=>{calls.push({method:"GET",path});
  if(path.endsWith("/catalog"))return {...catalog,project_id:project};
  if(path.endsWith("/versions"))return {versions:[saved.manifest],head_version_id:versionId};
  if(path.endsWith("/analysis-selection"))return {subject_kind:"planned_gpx",version_id:versionId};
  if(path.endsWith("/review-context"))return {context:badContext?{...(context||recordedContext({declared_by:"existing",declared_at:"2026-10-01T06:00:00+08:00"})),subject_binding:{...binding(),version_id:"plan.other"}}:context};
  if(path.includes("/versions/"))return saved;
  if(/\/analysis-runs(?:\?|$)/.test(path))return {project_id:project,runs};
  if(path.includes("/analysis-runs/"))return runs.find(value=>path.endsWith(value.run_id));
  throw Error(path);},
 postJson:async(path,body)=>{calls.push({method:"POST",path,body:JSON.parse(JSON.stringify(body))});
  if(path.endsWith("/review-context")){if(failContextOnce){failContextOnce=false;throw Error("response timeout");}context=recordedContext(body.declaration,body);return context;}
  if(path.endsWith("/preview"))return preview(body);
  if(path.endsWith("/intent"))return intentResult(body);
  if(path.endsWith("/resume")){const previous=runs.find(value=>path.includes(value.run_id));Object.assign(previous,{status:"queued",attempt:previous.attempt+1});return previous;}
  if(path.endsWith("/analysis-runs")){const created=job("queued");runs.unshift(created);return created;}
  if(path.endsWith("/versions")){saved={...saved,preview:preview(body.request),manifest:{...saved.manifest,request:body.request}};return saved.manifest;}
  throw Error(path);},
 render:()=>{win.document.querySelector("#root").innerHTML=ui.render({projectId:project});ui.bind(host);}};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function flush(){for(let i=0;i<12;i++)await tick();}
function el(selector){const value=win.document.querySelector(selector);assert.ok(value,selector);return value;}
function fill(selector,value){const input=el(selector);input.value=value;input.dispatchEvent(new win.Event(input.tagName==="SELECT"?"change":"input",{bubbles:true}));}
function check(selector,value=true){const input=el(selector);input.checked=value;input.dispatchEvent(new win.Event("change",{bubbles:true}));}
function click(selector){el(selector).click();}
async function restore(){fill("[data-planned-version]",versionId);click('[data-planned-action="restore"]');await flush();}
function declare(){fill('[data-planned-context-field="declaredBy"]',"operator-test");fill('[data-planned-context-field="declaredAt"]',"2026-10-01T06:00:00+08:00");fill('[data-planned-context-field="teamSize"]',"2");}
host.render();
'''
    code = setup + "\n(async()=>{await flush();\n" + script + r'''
})().then(value=>{process.stdout.write(JSON.stringify(value));dom.window.close();},error=>{console.error(error);dom.window.close();process.exitCode=1;});
'''
    result = subprocess.run([node, "-e", code, str(ROOT / "docs/admin/scout-planned-review-ui.js"), str(ROOT / "docs/admin/scout-planned-route.js")], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def test_restore_only_reads_context_and_navigation_defaults_to_unknown():
    result = probe(r'''
await restore();
assert.equal(calls.filter(c=>c.method==="POST").length,0);
assert.equal(win.document.querySelectorAll("[data-planned-context-navigation]").length,8);
for(const input of win.document.querySelectorAll("[data-planned-context-navigation]"))assert.equal(input.value,"unknown");
assert.equal(el('[data-planned-context-field="declaredBy"]').value,"");
assert.equal(el('[data-planned-context-field="declaredAt"]').value,"");
assert.equal(el('[data-planned-context-action="save"]').disabled,true);
return {getCount:calls.filter(c=>c.path.endsWith("/review-context")).length};
''')
    assert result["getCount"] == 1


def test_save_complete_declaration_preserves_false_unknown_and_updates_analysis_binding():
    result = probe(r'''
runs.push(job("completed_with_gaps",true));await restore();click('[data-planned-run-action="list"]');await flush();
assert.ok(win.document.querySelector("[data-planned-pretrip-report]"));
declare();fill('[data-planned-context-navigation="offline_map_downloaded"]',"false");
fill('[data-planned-context-json="members"]',JSON.stringify([{member_id:"one",planned_pace_kmh:2},{member_id:"two"}]));
fill('[data-planned-context-json="equipment"]',JSON.stringify([{item:"headlamp",state:"unknown"}]));
check("[data-planned-context-confirm]");click('[data-planned-context-action="save"]');await flush();
const posted=calls.find(c=>c.method==="POST"&&c.path.endsWith("/review-context")).body;
assert.equal(posted.declaration.navigation.offline_map_downloaded,false);
assert.equal(posted.declaration.navigation.gpx_loaded_on_device,null);
assert.equal(posted.declaration.narrative.review.status,"pending");
assert.equal(posted.declaration.declared_by,"operator-test");
assert.equal(posted.expected_geometry_sha256,geometrySha);assert.equal(posted.expected_itinerary_sha256,itinerarySha);
assert.equal(posted.explicit_confirmation,true);assert.equal(posted.expected_parent_revision_id,null);
assert.equal(win.document.querySelector("[data-planned-pretrip-report]"),null);
assert.ok(el("[data-planned-analysis-run-status]").textContent.includes("已失效"));
click('[data-planned-run-action="start"]');await flush();
const start=calls.find(c=>c.method==="POST"&&c.path.endsWith("/analysis-runs")).body;
assert.equal(start.expected_review_context_sha256,context.context_sha256);
return {refreshes,context:context.context_sha256,posted,start};
''')
    assert result["refreshes"] >= 1
    from scout_planned_review_context import PlannedReviewContextRequest
    assert PlannedReviewContextRequest.model_validate(result["posted"]).declaration.navigation.offline_map_downloaded is False
    assert len(result["context"]) == 64
    from scout_planned_analysis import PlannedAnalysisRunRequest
    assert PlannedAnalysisRunRequest.model_validate(result["start"]).expected_review_context_sha256 == result["context"]


def test_edit_after_confirmation_revokes_it_and_uncertain_save_retry_reuses_key():
    result = probe(r'''
await restore();declare();check("[data-planned-context-confirm]");
fill('[data-planned-context-field="goals"]',"觀察路況");
assert.equal(el("[data-planned-context-confirm]").checked,false);assert.equal(el('[data-planned-context-action="save"]').disabled,true);
check("[data-planned-context-confirm]");failContextOnce=true;click('[data-planned-context-action="save"]');await flush();
assert.ok(el("[data-planned-context-status]").textContent.includes("timeout"));
click('[data-planned-context-action="save"]');await flush();
const posts=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/review-context"));
assert.equal(posts.length,2);assert.equal(posts[0].body.idempotency_key,posts[1].body.idempotency_key);
return {keys:posts.map(c=>c.body.idempotency_key)};
''')
    assert result["keys"][0] == result["keys"][1]


def test_foreign_context_response_fails_binding_and_does_not_spin_get_retries():
    result = probe(r'''
badContext=true;await restore();await flush();
assert.ok(el("[data-planned-context-status]").textContent.includes("未通過"));
assert.equal(el('[data-planned-run-action="start"]').disabled,true);
return {gets:calls.filter(c=>c.path.endsWith("/review-context")).length,posts:calls.filter(c=>c.method==="POST").length};
''')
    assert result == {"gets": 1, "posts": 0}


def test_terrain_fields_and_candidate_metadata_reach_the_real_preview_request():
    result = probe(r'''
await restore();check("[data-planned-timing-enabled]");
fill('[data-planned-timing-field="assumed_flat_speed_kmh"]',"2");
fill('[data-planned-timing-field="assumed_ascent_m_per_hour"]',"300");
fill('[data-planned-timing-field="assumed_descent_m_per_hour"]',"600");
fill('[data-planned-timing-field="max_daily_moving_minutes"]',"360");
fill('[data-planned-timing-next-departure]',"06:00");check('[data-planned-timing-flag="auto_schedule_camps"]');
fill('[data-planned-timing-advanced]',JSON.stringify({team_members:[],campsite_candidates:[{candidate_id:"camp-a",point_index:1,water_available:null,legal_use:null}],daylight_windows:[],source_refs:[]}));
click('[data-planned-action="preview"]');await flush();
const request=calls.find(c=>c.method==="POST"&&c.path.endsWith("/preview")).body;
assert.equal(request.terrain_timing.assumed_ascent_m_per_hour,300);
assert.equal(request.terrain_timing.auto_schedule_camps,true);assert.equal(request.terrain_timing.next_day_departure_time,"06:00");
assert.equal(request.terrain_timing.campsite_candidates[0].legal_use,null);
assert.equal(request.terrain_timing.use_assumptions_for_missing_members,false);
return {timing:request.terrain_timing};
''')
    assert result["timing"]["assumed_flat_speed_kmh"] == 2
    from scout_planned_timing import TerrainTimingOptions
    assert TerrainTimingOptions.model_validate(result["timing"]).assumed_flat_speed_kmh == 2


def test_invalid_advanced_timing_json_prevents_preview_post():
    result = probe(r'''
await restore();check("[data-planned-timing-enabled]");fill('[data-planned-timing-advanced]',"{broken");
click('[data-planned-action="preview"]');await flush();
assert.ok(el("[data-planned-status]").textContent.includes("有效 JSON"));
return {posts:calls.filter(c=>c.method==="POST"&&c.path.endsWith("/preview")).length};
''')
    assert result["posts"] == 0


def test_original_text_parse_shows_clause_choices_and_unicode_span_replacement():
    result = probe(r'''
await restore();fill("[data-planned-human-text]","🏕第三天在營地 A 紮營；隔天六點出發");
click('[data-planned-intent-action="parse"]');await flush();
assert.equal(win.document.querySelectorAll("[data-planned-intent-clause]").length,2);
assert.ok(el("[data-planned-intent-result]").textContent.includes("D4"));
fill('[data-planned-intent-clause-edit="clause.2"]',"第四天六點出發");
click('[data-planned-intent-action="replace-clause"][data-planned-clause-id="clause.2"]');await flush();
const requests=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/intent"));
assert.equal(requests.length,2);assert.equal(requests[1].body.human_text,"🏕第三天在營地 A 紮營；第四天六點出發");
assert.equal(requests[1].body.use_configured_model,false);
return {text:el("[data-planned-human-text]").value};
''')
    assert "🏕第三天" in result["text"]


def test_model_draft_is_explicitly_adopted_and_invalidated_when_original_changes():
    result = probe(r'''
await restore();check("[data-planned-intent-model]");click('[data-planned-intent-action="parse"]');await flush();
click('[data-planned-intent-action="apply-draft"]');click('[data-planned-action="preview"]');await flush();
let request=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/preview")).at(-1).body;
assert.ok(request.intent_draft.actions.length);assert.equal(request.intent_input_sha256.length,64);assert.equal(request.source_snapshot_sha256,catalogSha);
fill('[data-planned-field="departure"]',"2026-10-02T06:00");
assert.equal(win.document.querySelector("[data-planned-intent-result]"),null);
click('[data-planned-action="preview"]');await flush();
request=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/preview")).at(-1).body;
assert.equal(Object.hasOwn(request,"intent_draft"),false);assert.equal(Object.hasOwn(request,"intent_input_sha256"),false);
return {parsed:calls.filter(c=>c.method==="POST"&&c.path.endsWith("/intent")).length};
''')
    assert result["parsed"] == 1


def test_report_displays_all_required_outputs_and_download_checks_actual_bytes():
    result = probe(r'''
const prior=job("completed_with_gaps",true);runs.push(prior);await restore();click('[data-planned-run-action="list"]');await flush();
assert.ok(el("[data-planned-pretrip-report]").textContent.includes("前三大風險來源"));
assert.ok(el("[data-planned-pretrip-report]").textContent.includes("pace.json"));
for(const key of ["cp_graph","latest_turnaround","suggested_stop_points","not_recommended_stop_points","pretrip_checklist"])assert.ok(win.document.querySelector(`[data-planned-report-output="${key}"]`));
const downloads=[];win.URL.createObjectURL=()=>"blob:verified-report";win.URL.revokeObjectURL=()=>{};
win.HTMLAnchorElement.prototype.click=function(){downloads.push({name:this.download,href:this.href});};
win.fetch=async url=>{calls.push({method:"GET_BYTES",path:url});const bytes=Buffer.from(prior.rawReport);return {ok:true,status:200,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};};
click("[data-planned-report-download]");await flush();
assert.equal(downloads.length,1);assert.ok(downloads[0].name.endsWith("pretrip-report.json"));
assert.ok(el("[data-planned-report-download-status]").textContent.includes("SHA-256 核對通過"));
return {url:calls.find(c=>c.method==="GET_BYTES").path};
''')
    assert "artifact?ref=reports%2Fpretrip.json" in result["url"]


def test_report_download_rejects_tampered_response_and_cross_context_report():
    result = probe(r'''
const prior=job("completed_with_gaps",true);runs.push(prior);await restore();click('[data-planned-run-action="list"]');await flush();
let downloads=0;win.URL.createObjectURL=()=>{downloads++;return "blob:bad";};
win.fetch=async()=>({ok:true,status:200,arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer});
click("[data-planned-report-download]");await flush();
assert.equal(downloads,0);assert.ok(el("[data-planned-report-download-status]").textContent.includes("已變更"));
assert.equal(ext.reportMatches(prior,binding(),"9".repeat(64)),false);
return {blocked:true};
''')
    assert result["blocked"]


def test_recorded_six_force_projection_uses_exact_recorded_binding_and_historical_labels():
    result = probe(r'''
const b={...binding(),version_id:"recorded."+"a".repeat(24),subject_kind:"recorded_gpx",kind:"recorded_gpx"};
const roles=["permission","pace_fit","architecture","navigation","weather","route_context"];
const projection=role=>({status:"partial",summary:"本次實錄評估",input_binding:b,artifact_ref:`${role}.json`,artifact_sha256:"b".repeat(64),candidate_only:true,runtime_safety_truth:false,result:{},missing_inputs:[]});
const observed={...b,binding:b,run_id:"analysis."+"c".repeat(32),status:"completed_with_gaps",candidate_only:true,runtime_safety_truth:false,projections:Object.fromEntries(roles.map(role=>[role,projection(role)]))};
const subject={project_id:project,subject_kind:"recorded_gpx",subject_id:b.version_id,analysis_revision:"rev",recorded_version_id:b.version_id,recorded_bundle_sha256:manifestSha,geometry_fingerprint:geometrySha,timing_fingerprint:itinerarySha,recorded_route_geojson:route,itinerary:saved.preview.itinerary,recorded_analysis:observed,dependencies:Object.fromEntries(roles.map(role=>[role,{status:"partial_recorded_analysis"}]))};
for(const role of roles){const html=ui.renderSubject(subject,"outdoor-"+role.replaceAll("_","-"));assert.ok(html.includes('data-planned-force-current="true"'));assert.ok(html.includes("共同分析主體：Recorded GPX"));assert.ok(html.includes('data-recorded-analysis-subject="true"'));}
for(const field of ["project_id","version_id","manifest_sha256","geometry_sha256","itinerary_sha256"]){const copy=JSON.parse(JSON.stringify(subject));copy.recorded_analysis.projections.navigation.input_binding[field]="different";const html=ui.renderSubject(copy,"outdoor-navigation");assert.ok(html.includes('data-planned-force-pending="navigation"'));assert.equal(html.includes('data-planned-force-current="true"'),false);}
const historical=ui.wrapHistorical("<h1>Weather</h1><div>old</div>","<h1>Weather</h1>","outdoor-weather",subject);
assert.ok(historical.includes("重算為 Recorded"));assert.ok(historical.includes('data-planned-legacy-golden="outdoor-weather"'));
return {roles:roles.length};
''')
    assert result["roles"] == 6



def test_no_golden_comparison_preserves_null_and_does_not_reuse_catalog_geometry():
    result = probe(r"""
catalog.golden_geojson=route;
saved.preview.golden_geojson=null;
saved.preview.comparison={status:"unavailable",golden_available:false,golden_length_m:null,planned_length_m:200,added_distance_m:null,geometry_changed:null};
await restore();
assert.equal(win.document.querySelector('[data-planned-map-layer="golden"]'),null);
assert.ok(el('[data-planned-golden-unavailable]').textContent.includes("無 Golden"));
const comparison=el('[data-planned-comparison]');
assert.ok(comparison.textContent.includes("無法進行基準差異比較"));
assert.ok(comparison.textContent.includes('"added_distance_m": null'));
assert.ok(win.document.querySelector('[data-planned-map-layer="planned"]'));
return {kept_unknown:true};
""")
    assert result["kept_unknown"]


def test_terrain_timeline_preserves_day_boundary_interval_and_partial_eta():
    result = probe(r"""
saved.preview.itinerary={time_role:"planned_estimate",complete_route_eta:false,unknowns:[{code:"segment_time_unknown"}],
 assumptions:{uncertainty_kind:"declared_scenario_envelope_not_statistical_confidence"},
 days:[{day_id:"D3",departure_at:"2026-10-03T06:00:00+08:00",arrival_at:null,conditional_on_prior_unknown:true,
   conditional_arrival_at:"2026-10-03T12:00:00+08:00",moving_minutes:30,moving_minutes_lower:24,moving_minutes_upper:36,
   moving_minutes_is_known_subtotal:true,rest_minutes:35,fixed_rest_minutes:20,estimated_rest_minutes:15}],
 timeline:[{kind:"move",day_id:"D3",from_point_index:0,point_index:1,duration_minutes:10,lower_minutes:8,upper_minutes:12,method:"terrain"},
   {kind:"move",day_id:"D3",from_point_index:1,point_index:2,duration_minutes:20,lower_minutes:16,upper_minutes:24,method:"terrain"},
   {kind:"move",day_id:"D4",from_point_index:2,point_index:3,duration_minutes:40,lower_minutes:32,upper_minutes:48,method:"terrain"}]};
await restore();
const timeline=el('[data-planned-table$=":summary"]');
assert.equal(timeline.dataset.plannedTotalRows,"2");
assert.ok(timeline.textContent.includes("情境區間 24.0–36.0 分"));
assert.ok(timeline.textContent.includes("D3"));assert.ok(timeline.textContent.includes("D4"));
const table=el('[data-planned-itinerary]');
assert.ok(table.textContent.includes("已知小計"));assert.ok(table.textContent.includes("前段含未知"));
assert.ok(table.textContent.includes("固定 20.0 分 · 估計 15.0 分"));
const basis=table.querySelector('[data-planned-result-details]');basis.open=true;basis.dispatchEvent(new win.Event("toggle"));
assert.ok(basis.textContent.includes("segment_time_unknown"));
return {day_boundaries:2};
""")
    assert result["day_boundaries"] == 2


def test_resume_uses_existing_job_context_and_new_context_requires_new_run():
    result = probe(r"""
context=recordedContext({declared_by:"existing",declared_at:"2026-10-01T06:00:00+08:00"});
const paused=job("failed");paused.can_resume=true;runs.push(paused);
await restore();click('[data-planned-run-action="list"]');await flush();
assert.equal(el('[data-planned-run-action="resume"]').disabled,false);
click('[data-planned-run-action="resume"]');await flush();
const resumed=calls.find(c=>c.method==="POST"&&c.path.endsWith("/resume"));
assert.equal(resumed.body.expected_review_context_sha256,paused.binding.review_context_sha256);
assert.ok(resumed.path.includes(paused.run_id));
paused.status="failed";context=recordedContext({declared_by:"updated",declared_at:"2026-10-01T07:00:00+08:00"});
click('[data-planned-context-action="load"]');await flush();click('[data-planned-run-action="list"]');await flush();
assert.equal(el('[data-planned-run-action="resume"]').disabled,true);
assert.equal(el('[data-planned-run-action="start"]').disabled,false);
return {bound:true,payload:resumed.body};
""")
    assert result["bound"]
    from scout_planned_analysis import PlannedAnalysisResumeRequest
    assert PlannedAnalysisResumeRequest.model_validate(result["payload"]).expected_review_context_sha256



def test_projection_cannot_reuse_another_review_context_even_with_same_geometry():
    result = probe(r"""
context=recordedContext({declared_by:"existing",declared_at:"2026-10-01T06:00:00+08:00"});
await restore();
const current=job("completed");
current.projections.navigation={status:"ready",input_binding:{...current.binding,review_context_sha256:"old-context"},
 artifact_ref:"nav.json",artifact_sha256:"a".repeat(64),candidate_only:true,runtime_safety_truth:false,result:{}};
const subject={project_id:project,subject_kind:"planned_gpx",selected_plan_version_id:versionId,planned_bundle_sha256:manifestSha,
 geometry_fingerprint:geometrySha,timing_fingerprint:itinerarySha,planned_analysis:current,dependencies:{navigation:{status:"current_planned_analysis"}}};
assert.ok(ui.renderSubject(subject,"outdoor-navigation").includes('data-planned-force-pending="navigation"'));
current.projections.navigation.input_binding.review_context_sha256=context.context_sha256;
assert.ok(ui.renderSubject(subject,"outdoor-navigation").includes('data-planned-force-current="true"'));
return {bound:true};
""")
    assert result["bound"]
