"""Run the shipped Recorded control handlers in a DOM; this is not browser GIS proof."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/admin/scout-recorded-workflow.js"


def _probe(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for Recorded DOM checks")
    setup = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {createHash} = require("node:crypto");
const {JSDOM} = require("jsdom");
const dom = new JSDOM("<!doctype html><html><body><main id='root'></main></body></html>", {url:"http://localhost/",runScripts:"outside-only"});
const win=dom.window, container=win.document.getElementById("root");
let uuid=0;
Object.defineProperty(win.crypto,"randomUUID",{value:()=>`00000000-0000-4000-a000-${String(++uuid).padStart(12,"0")}`});
win.eval(fs.readFileSync(process.argv[1],"utf8"));
const ui=win.ScoutRecordedWorkflow;
let project="project-a", refreshes=0, failStartOnce=false, failSaveOnce=false;
const calls=[], versions=[], jobs=[], bundles=new Map(), runKeys=new Map();
let selection={subject_kind:"golden_gpx",selection_sha256:null};
const A="recorded."+"a".repeat(24), B="recorded."+"b".repeat(24), PLAN="plan."+"c".repeat(24);
const sha=value=>createHash("sha256").update(value).digest("hex");
function bundle(version=A, request={label:"explicit replay",recordings:[]}) {
 const value={manifest:{version_id:version,manifest_sha256:sha(version),kind:"recorded_gpx",source_times_role:"fixture_replay_time",observation_kind:"fixture_replay",actual_user_recorded_activity:false},
  preview:{request,metrics:{moving_seconds:600,unobserved_seconds:43200},route_axis:[{lat:24,lon:121}],comparison:{golden:{matched_point_count:1,deviation_point_count:0},planned:{turnback_detected:true}},itinerary:{unknowns:[{code:"recording_gap"}]}}};
 bundles.set(version,value);
 if(!versions.some(row=>row.manifest.version_id===version))versions.push({manifest:value.manifest,label:request.label});
 return value;
}
function job(version, status="queued") {
 const m=bundles.get(version).manifest;
 return {run_id:"analysis."+String(jobs.length+1).padStart(32,"0"),version_id:version,manifest_sha256:m.manifest_sha256,
  status,attempt:1,can_resume:status==="interrupted",projections:{},binding:{kind:"recorded_gpx",source_times_role:"fixture_replay_time"}};
}
function el(selector){const result=win.document.querySelector(selector);assert.ok(result,selector);return result;}
function field(name,value){const input=el(`[data-recorded-field="${name}"]`);input.value=value;input.dispatchEvent(new win.Event("input",{bubbles:true}));}
function row(index,name,value){const input=el(`[data-recorded-row="${index}"][data-recorded-prop="${name}"]`);input.value=value;input.dispatchEvent(new win.Event("input",{bubbles:true}));}
function click(action){el(`[data-recorded-action="${action}"]`).click();}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function flush(){for(let n=0;n<8;n++)await tick();}
function choose(files){Object.defineProperty(el("[data-recorded-files]"),"files",{value:files.map(([name,raw])=>({name,text:async()=>raw})),configurable:true});}
const host={
 refresh:()=>{container.innerHTML=ui.render({projectId:project});ui.bind(container,host);},
 refreshAnalysis:async()=>{refreshes++;},
 apiGet:async path=>{
  calls.push({method:"GET",path});
  if(path.endsWith("/planned-route/analysis-selection"))return {...selection};
  if(path.endsWith("/planned-route/versions"))return {versions:[{version_id:PLAN}]};
  if(path.endsWith("/recorded-analysis/versions"))return {versions,analysis_selection:selection};
  if(path.includes("/versions/")){const result=bundles.get(decodeURIComponent(path.split("/versions/")[1]));assert.ok(result,path);return result;}
  if(path.includes("/analysis-runs?")){const id=new URL(path,"http://localhost").searchParams.get("version_id");return {runs:jobs.filter(item=>item.version_id===id)};}
  if(path.includes("/analysis-runs/")){const result=jobs.find(item=>path.endsWith(item.run_id));assert.ok(result,path);return {...result};}
  throw Error(path);
 },
 apiPost:async(path,body)=>{
  calls.push({method:"POST",path,body:JSON.parse(JSON.stringify(body))});
  if(path.endsWith("/sources")){const h=sha(body.content);return {source_ref:`post_analysis/completed_trips/recorded/imports/${h}/${body.file_name}`,sha256:h,file_name:body.file_name,point_count:2,source_bytes_preserved:true};}
  if(path.endsWith("/versions")){if(failSaveOnce){failSaveOnce=false;throw Error("save response unavailable");}return bundle(versions.length?B:A,body);}
  if(path.endsWith("/selection")){selection={...body,selection_sha256:sha(body.idempotency_key)};return selection;}
  if(path.endsWith("/analysis-runs")){
   const existing=runKeys.get(body.idempotency_key);
   if(existing){assert.equal(existing.version_id,body.version_id,"a run key was reused for another Recorded version");return {...existing};}
   const next=job(body.version_id);jobs.push(next);runKeys.set(body.idempotency_key,next);
   if(failStartOnce){failStartOnce=false;throw Error("start response unavailable");}
   return {...next};
  }
  if(path.endsWith("/resume")){const item=jobs.find(v=>path.includes(v.run_id));assert.ok(item,path);assert.equal(item.manifest_sha256,body.expected_manifest_sha256);Object.assign(item,{status:"queued",attempt:item.attempt+1,can_resume:false});return {...item};}
  throw Error(path);
 }
};
host.refresh();
'''
    script = setup + "\n(async()=>{\n" + probe + r'''
})().then(value=>{process.stdout.write(JSON.stringify(value));dom.window.close();},error=>{console.error(error);dom.window.close();process.exitCode=1;});
'''
    result = subprocess.run([node, "-e", script, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_actual_controls_upload_multifile_provenance_save_retry_and_select():
    result = _probe(r'''
assert.equal(el('[data-recorded-action="save"]').disabled,true);
field("member","alice");field("device","phone");field("origin","fixture_replay");
const files=[["day1.gpx","<gpx>第一天 fixture\r\n</gpx>"],["day2.gpx","<gpx>第二天 fixture\n</gpx>"],["backup.gpx","<gpx>backup fixture</gpx>"],["bob.gpx","<gpx>member fixture</gpx>"]];
choose(files);click("upload");await flush();
const uploads=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/sources"));
assert.deepEqual(uploads.map(v=>[v.body.file_name,v.body.content]),files);
assert.equal(win.document.querySelectorAll('[data-recorded-prop="member_id"]').length,4);
row(2,"device_id","watch");row(2,"role","backup");
row(3,"member_id","bob");row(3,"device_id","bob-phone");row(3,"role","member_context");
click("reload");await flush();field("plan",PLAN);
failSaveOnce=true;click("save");await flush();
assert.ok(el('[data-recorded-status]').textContent.includes("save response unavailable"));
click("save");await flush();
const saves=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/versions"));
assert.equal(saves.length,2);assert.equal(saves[0].body.idempotency_key,saves[1].body.idempotency_key);
const body=saves[1].body;
assert.equal(body.project_id,"project-a");assert.equal(body.primary_member_id,"alice");assert.equal(body.planned_version_id,PLAN);
assert.deepEqual(body.recordings.map(r=>[r.member_id,r.device_id,r.role,r.observation_kind]),[["alice","phone","primary","fixture_replay"],["alice","phone","primary","fixture_replay"],["alice","watch","backup","fixture_replay"],["bob","bob-phone","member_context","fixture_replay"]]);
assert.deepEqual(body.recordings.map(r=>r.expected_sha256),files.map(f=>sha(f[1])));
assert.equal(el('[data-recorded-version]').dataset.recordedVersion,A);
assert.ok(el('[data-recorded-version]').textContent.includes("fixture_replay_time"));
assert.ok(el('[data-recorded-version] a[download]').href.includes(`/export/${A}/gpx`));
click("select");await flush();
const selectionCall=calls.find(c=>c.method==="POST"&&c.path.endsWith("/selection"));
assert.equal(selectionCall.body.subject_kind,"recorded_gpx");assert.equal(selectionCall.body.version_id,A);
assert.equal(selectionCall.body.expected_manifest_sha256,sha(A));assert.equal(selectionCall.body.explicit_confirmation,true);
assert.equal(refreshes,1);
return {uploaded_originals:4,provenance_preserved:true,save_retry_identity:true,canonical_selection:true};
''')
    assert result == {"uploaded_originals": 4, "provenance_preserved": True, "save_retry_identity": True, "canonical_selection": True}


def test_existing_recorded_version_can_be_restored_from_fresh_page():
    result = _probe(r'''
bundle(A);click("reload");await flush();
assert.equal(el('[data-recorded-action="restore"]').disabled,true);
field("selected",A);
assert.equal(el('[data-recorded-action="restore"]').disabled,false,"choosing an existing version must enable its Restore action");
click("restore");await flush();
assert.equal(el('[data-recorded-version]').dataset.recordedVersion,A);
assert.equal(calls.filter(c=>c.method==="POST").length,0);
assert.ok(calls.some(c=>c.path.endsWith(`/analysis-runs?version_id=${A}`)));
return {fresh_page_restore:true,read_only:true};
''')
    assert result == {"fresh_page_restore": True, "read_only": True}


def test_restore_new_version_changes_run_and_resume_identity_but_uncertain_retry_keeps_it():
    result = _probe(r'''
field("member","alice");field("device","phone");field("origin","fixture_replay");
choose([["day1.gpx","<gpx>fixture</gpx>"]]);click("upload");await flush();click("save");await flush();
failStartOnce=true;click("analyse");await flush();
assert.ok(el('[data-recorded-status]').textContent.includes("start response unavailable"));
click("analyse");await flush();
const firstStarts=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/analysis-runs"));
assert.equal(firstStarts.length,2);assert.equal(firstStarts[0].body.idempotency_key,firstStarts[1].body.idempotency_key);
assert.equal(jobs.length,1);
Object.assign(jobs[0],{status:"interrupted",can_resume:true});click("run-refresh");await flush();
click("resume");await flush();
assert.equal(jobs[0].attempt,2);
bundle(B);click("reload");await flush();field("selected",B);click("restore");await flush();
assert.equal(el('[data-recorded-version]').dataset.recordedVersion,B);
assert.equal(win.document.querySelector('[data-recorded-run]'),null);
click("analyse");await flush();
const starts=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/analysis-runs"));
assert.equal(starts.length,3);assert.equal(starts[2].body.version_id,B);
assert.notEqual(starts[2].body.idempotency_key,starts[1].body.idempotency_key);
assert.equal(jobs.length,2);
Object.assign(jobs[1],{status:"interrupted",can_resume:true});click("run-refresh");await flush();click("resume");await flush();
const resumes=calls.filter(c=>c.method==="POST"&&c.path.endsWith("/resume"));
assert.equal(resumes.length,2);assert.notEqual(resumes[0].body.idempotency_key,resumes[1].body.idempotency_key);
assert.equal(resumes[1].body.expected_manifest_sha256,sha(B));
assert.ok(resumes[1].path.includes(jobs[1].run_id));
return {uncertain_retry_same_key:true,restored_version_new_key:true,resume_bound_to_version:true};
''')
    assert result == {"uncertain_retry_same_key": True, "restored_version_new_key": True, "resume_bound_to_version": True}


def test_async_old_project_result_cannot_replace_visible_project():
    result = _probe(r'''
field("member","alice");field("device","phone");field("origin","fixture_replay");
let release;const originalPost=host.apiPost;
host.apiPost=(path,body)=>path.endsWith("/sources")?new Promise(resolve=>{release=()=>originalPost(path,body).then(resolve);}):originalPost(path,body);
choose([["old-project.gpx","<gpx>fixture</gpx>"]]);click("upload");await tick();
project="project-b";host.refresh();release();await flush();
assert.equal(el('[data-recorded-workflow]').dataset.recordedWorkflow,"project-b");
assert.equal(win.document.querySelector('[data-recorded-prop="member_id"]'),null);
assert.equal(el('[data-recorded-action="save"]').disabled,true);
assert.equal(el('[data-recorded-field="member"]').value,"");
return {late_project_response_isolated:true};
''')
    assert result == {"late_project_response_isolated": True}


def test_pending_selection_disables_next_action_until_analysis_refresh_finishes():
    result = _probe(r'''
bundle(A);click("reload");await flush();field("selected",A);click("restore");await flush();
let release;host.refreshAnalysis=()=>new Promise(resolve=>{release=resolve;});
click("select");await flush();
assert.equal(el('[data-recorded-action="analyse"]').disabled,true);
click("analyse");assert.equal(jobs.length,0);
release();await flush();
assert.equal(el('[data-recorded-action="analyse"]').disabled,false);
click("analyse");await flush();assert.equal(jobs.length,1);
return {pending_action_disabled:true,next_action_available_after_refresh:true};
''')
    assert result == {"pending_action_disabled": True, "next_action_available_after_refresh": True}
