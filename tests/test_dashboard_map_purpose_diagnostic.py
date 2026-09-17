"""D049 actual production render/bind replay with saved-source fixtures.

JSDOM has no layout or browser navigation: the fixed SVG rectangle below is a
declared layout seam, and Legacy uses the real server desktop transformation.
These tests prove Diagnostic decisions/handlers, never live workspace readiness.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"
MODULE = ROOT / "docs/admin/scout-map-purpose-diagnostic.js"
PLANNED = ROOT / "docs/admin/scout-planned-route.js"
LEGACY = ROOT / "docs/emergency/scout-emergency-mobile-approval-v0.html"


@pytest.fixture(scope="module")
def desktop_page(tmp_path_factory):
    # Execute the shipped server transform without importing server startup or
    # loading .env. Its only input is the checked-in Legacy page.
    tree = ast.parse((ROOT / "admin_api.py").read_text())
    function = next(item for item in tree.body if isinstance(item, ast.FunctionDef)
                    and item.name == "_dashboard_emergency_desktop_approval_html")
    namespace = {"DEFAULT_EMERGENCY_MOBILE_APPROVAL_PAGE": LEGACY, "HTTPException": RuntimeError}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "admin_api.py", "exec"), namespace)
    page = tmp_path_factory.mktemp("map-purpose") / "legacy-desktop.html"
    page.write_text(namespace[function.name]())
    return page


BASE = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM,VirtualConsole}=require('jsdom');
const html=fs.readFileSync(process.argv[4],'utf8'),moduleSource=fs.readFileSync(process.argv[2],'utf8'),
 plannedSource=fs.readFileSync(process.argv[3],'utf8'),legacyHtml=fs.readFileSync(process.argv[5],'utf8');
const api=require(process.argv[2]);
const project='purpose_replay', origin='http://localhost', prefix='/admin/pretrip/projects/'+project;
const sha=letter=>letter.repeat(64),windows=[],calls=[];
const clone=value=>structuredClone(value);
const geometry={type:'FeatureCollection',features:[
 {type:'Feature',properties:{source_id:'reference-a',direction:'forward'},geometry:{type:'LineString',coordinates:[[121,24],[121.001,24.002],[121.003,24.001]]}},
 {type:'Feature',properties:{source_id:'reference-b',direction:'reverse'},geometry:{type:'LineString',coordinates:[[121.007,24.006],[121.006,24.005]]}},
]};
const golden={type:'FeatureCollection',features:[{type:'Feature',properties:{source_id:'golden'},geometry:{type:'LineString',coordinates:[[121,24],[121.002,24.002],[121.005,24.004]]}}]};
const checkpoints=[{checkpoint_id:'cp.start',lon:121,lat:24},{checkpoint_id:'cp.turn',lon:121.003,lat:24.001},{checkpoint_id:'cp.finish',lon:121.006,lat:24.005}];
const catalog={project_id:project,source_snapshot_sha256:sha('f'),source_hashes:{'source.gpx':sha('d')},golden_source_id:'golden',
 anchors:[{anchor_id:'golden.anchor',source_id:'golden',part_index:0,point_index:0,lon:121,lat:24,label:'catalog anchor'}],
 sources:[{source_id:'golden',kind:'golden',parts:[[{lon:121,lat:24},{lon:121.002,lat:24.002}]]}]};
function saved(version='plan.aaaaaaaaaaaaaaaa',mark='a'){
 const manifest={project_id:project,version_id:version,manifest_sha256:sha(mark==='a'?'c':'f'),preview_sha256:sha(mark),geometry_sha256:sha('b'),
 files:{'preview.json':{sha256:sha('d')}},candidate_only:true,runtime_safety_truth:false,
 request:{human_text:'沿既有路徑',operations:[],name_resolutions:{},departure_at:'2026-09-13T06:00:00+08:00'}};
 return {manifest,preview:{project_id:project,preview_sha256:manifest.preview_sha256,geometry_sha256:manifest.geometry_sha256,
 request:manifest.request,route_geojson:clone(geometry),golden_geojson:clone(golden),checkpoints:clone(checkpoints),candidate_only:true,runtime_safety_truth:false},
 source_status:{status:'current'},candidate_only:true,runtime_safety_truth:false};
}
const selected=saved(),comparison=saved('plan.bbbbbbbbbbbbbbbb','e');
const selection={project_id:project,subject_kind:'planned_gpx',version_id:selected.manifest.version_id,manifest_sha256:selected.manifest.manifest_sha256,selection_sha256:sha('f')};
const subject={project_id:project,subject_kind:'planned_gpx',subject_id:selected.manifest.version_id,selected_plan_version_id:selected.manifest.version_id,
 planned_bundle_sha256:selected.manifest.manifest_sha256,geometry_fingerprint:sha('b'),analysis_revision:sha('e'),timing_fingerprint:sha('f'),
 sources:{planned_comparison_preview:{status:'available',sha256:sha('d'),ref:'reviews/planned_routes/versions/'+selected.manifest.version_id+'/preview.json'}},
 checkpoints:clone(checkpoints),segments:[],planned_route_geojson:clone(geometry),golden_route_geojson:clone(golden),
 candidate_only:true,runtime_safety_truth:false,departure_approval_granted:false,dependencies:{},issues:[],schedule_status:'planned_reviewed'};
const versions={project_id:project,versions:[comparison.manifest,selected.manifest],head_version_id:comparison.manifest.version_id};
const data=new Map([
 [prefix+'/planned-route/versions',versions],[prefix+'/planned-route/analysis-selection',selection],[prefix+'/analysis-subject',subject],
 [prefix+'/planned-route/catalog',catalog],[prefix+'/planned-route/versions/'+selected.manifest.version_id,selected],
 [prefix+'/planned-route/versions/'+comparison.manifest.version_id,comparison],
]);
async function read(path){calls.push({method:'GET',path});if(data.has(path))return clone(data.get(path));
 if(path.includes('/planned-route/analysis-runs'))return {project_id:project,runs:[]};
 if(path.includes('contextual-permission'))return {project_id:project,status:'degraded',candidate_only:true,remaining_plan:[],missing_inputs:[]};
 throw Error('Unexpected GET '+path);
}
function domPage(page,url){
 const errors=[],console=new VirtualConsole();console.on('jsdomError',error=>errors.push(error.message));
 const win=new JSDOM(page,{url,runScripts:'outside-only',virtualConsole:console,pretendToBeVisual:true}).window;
 windows.push(win);win.__errors=errors;win.structuredClone=clone;win.fetch=async(path,options={})=>{
  assert.ok(!options.method||options.method==='GET','Unexpected write');const value=await read(String(path));return {ok:true,json:async()=>value};};
 return win;
}
function dashboard(options={}){
 const win=domPage(html,origin+'/admin/dashboard?projectId='+project+'&diagnosticMapProbe=1');
 win.eval(plannedSource);win.eval(moduleSource);
  // The only data-loader seam prevents unrelated Golden page reads; production
  // renderOutdoorPage + its force renderer + the map binding all execute below.
 win.eval([...win.document.querySelectorAll('script:not([src])')].map(script=>script.textContent).join('\n')
  +'\nwindow.__purposeReplayState=state;'
  +(options.productionLoaders ? '' : `loadDataScope=async function(scope){if(scope==='project')state.project={project_id:'${project}'};};`));
 win.SVGElement.prototype.getBoundingClientRect=function(){return {left:0,top:0,width:900,height:420,right:900,bottom:420};};
 return win;
}
function legacy(){
 const win=domPage(legacyHtml,origin+'/admin/dashboard/emergency-approval-desktop-v0?projectId='+project+'&diagnosticMapProbe=1');
 for(const script of win.document.querySelectorAll('script:not([src])'))win.eval(script.textContent);
 return {win,descriptor:{root:win.document.querySelector('[data-map-surface="desktop"]'),doc:win.document,
  boundary:()=>win.scoutLegacyMapPurposeBridge.snapshot(),sourceBasis:'production-desktop-entry-transform'}};
}
async function context(){return api.readContext({projectId:project,read});}
async function open(testCase,ctx){
 if(testCase.purpose==='illustrative-only'){
  const {win,descriptor}=legacy();return {descriptor,close:async()=>{const receipt=win.scoutLegacyMapPurposeBridge.dispose();win.close();return receipt;}};
 }
 const win=dashboard();
 const descriptor=await win.scoutDashboardMapPurposeProbe.prepare(testCase,ctx);
 return {descriptor,close:async()=>{const receipt=await win.scoutDashboardMapPurposeProbe.dispose();win.close();return receipt;}};
}
"""


def node(body, desktop_page, *, project_override=None):
    executable = shutil.which("node")
    assert executable, "Node is required for the D049 production DOM replay"
    setup = BASE if project_override is None else BASE.replace("const project='purpose_replay'", f"const project={json.dumps(project_override)}")
    program = setup + "\n(async()=>{\n" + body + r"""
})().then(()=>{for(const win of windows)win.close();},error=>{
 console.error(error);for(const win of windows)win.close();process.exitCode=1;
});
"""
    result = subprocess.run([executable, "-", str(MODULE), str(PLANNED), str(PAGE), str(desktop_page)],
                            input=program, text=True, capture_output=True, cwd=ROOT, timeout=70)
    assert result.returncode == 0, result.stderr


def test_all_ten_rows_use_production_render_binding_and_complete_cleanup(desktop_page):
    node(r"""
const updates=[];
const report=await api.run({projectId:project,currentProjectId:()=>project,read,open,onProgress:value=>updates.push(clone(value))});
if(process.env.SCOUT_PURPOSE_REPLAY_REPORT)fs.writeFileSync(process.env.SCOUT_PURPOSE_REPLAY_REPORT,JSON.stringify({basis:'JSDOM source-fixture production render/bind; not Chrome or workspace qualification',report},null,2));
assert.equal(report.status,'passed',JSON.stringify(report.rows.filter(row=>row.status!=='passed'),null,2));
assert.equal(report.rows.length,10);assert.equal(report.rows.filter(row=>row.purpose==='vector-comparison').length,9);
assert.equal(report.rows.reduce((sum,row)=>sum+row.stages.length,0),67);
assert.ok(report.rows.every(row=>row.cleanup.length===2&&row.cleanup.every(clean=>clean.status==='passed')));
assert.ok(updates.some(update=>update.activeResult?.activeStage==='controls'));
assert.ok(calls.every(call=>call.method==='GET'));
assert.ok(windows.every(win=>!win.__errors.length),JSON.stringify(windows.flatMap(win=>win.__errors)));
""", desktop_page)


def test_missing_selected_planned_keeps_nine_failures_and_runs_legacy(desktop_page):
    node(r"""
data.set(prefix+'/planned-route/analysis-selection',{project_id:project,subject_kind:'golden_gpx'});
data.set(prefix+'/planned-route/versions',{project_id:project,versions:[]});
let opened=[];
const report=await api.run({projectId:project,currentProjectId:()=>project,read,open:async(testCase,ctx)=>{opened.push(testCase.key);return open(testCase,ctx);}});
assert.equal(report.status,'failed');assert.equal(report.rows.length,10);assert.equal(report.passedRows,1);
assert.deepEqual(opened,['legacy-emergency','legacy-emergency']);
assert.ok(report.rows.slice(0,9).every(row=>row.status==='failed'&&row.stages[0].detail.includes('no selected Planned')));
assert.equal(report.rows.at(-1).status,'passed');assert.ok(calls.every(call=>call.method==='GET'));
""", desktop_page)


@pytest.mark.parametrize("mutation, message", [
    ("selection.project_id='another_workspace'", "no selected"),
    ("subject.selected_plan_version_id=comparison.manifest.version_id", "does not match"),
    ("subject.sources.planned_comparison_preview.sha256='0'.repeat(64)", "source/hash"),
    ("subject.golden_route_geojson=null", "geometry differs"),
    ("selected.preview.golden_geojson=null", "missing Golden"),
    ("selected.source_status.status='stale'", "source binding changed"),
    ("subject.runtime_safety_truth=true", "authority"),
])
def test_source_version_hash_geometry_and_authority_mismatches_fail(mutation, message, desktop_page):
    node(mutation + f"; const ctx=await context(); assert.ok(ctx.plannedError?.includes({json.dumps(message)}),ctx.plannedError);", desktop_page)


def test_geometry_key_order_is_semantic_but_all_coordinates_must_match(desktop_page):
    node(r"""
subject.golden_route_geojson={features:subject.golden_route_geojson.features,type:'FeatureCollection'};
assert.equal((await context()).plannedError,undefined);
subject.golden_route_geojson.features[0].geometry.coordinates[1][0]+=.1;
assert.match((await context()).plannedError,/geometry differs/);
""", desktop_page)


def test_geometry_regression_detects_joined_gap_reversal_and_invented_point(desktop_page):
    node(r"""
const ctx=await context(),testCase=api.CASES.find(row=>row.key==='analysis-navigation');
for(const mutation of ['join','reverse','shift']){
 const probe=await open(testCase,ctx),root=probe.descriptor.root;
 const paths=[...root.querySelectorAll('[data-planned-map-layer="planned"]')];
 if(mutation==='join'){paths[0].setAttribute('d',paths[0].getAttribute('d')+' '+paths[1].getAttribute('d').replace('M','L'));paths[1].remove();}
 if(mutation==='reverse'){const commands=paths[1].getAttribute('d').match(/[ML][^ML]+/g).reverse();paths[1].setAttribute('d',commands.map((text,i)=>(i?'L':'M')+text.slice(1)).join(' '));}
 if(mutation==='shift')paths[1].setAttribute('d',paths[1].getAttribute('d').replace(/M[^ ]+/,'M22,22'));
 assert.throws(()=>api.geometryEvidence(probe.descriptor,geometry,golden),/missing|changed|projection/);
 await probe.close();
}
""", desktop_page)


def test_noop_disabled_controls_and_capture_cancellation_are_observed(desktop_page):
    node(r"""
const ctx=await context(),testCase=api.CASES.find(row=>row.key==='analysis-weather');
let probe=await open(testCase,ctx),root=probe.descriptor.root;
root.querySelector('svg').setPointerCapture=()=>{throw Object.assign(Error(),{name:'NotFoundError'});};
await api.controlEvidence(probe.descriptor);
root.querySelector('[data-planned-action="map-in"]').disabled=true;
await assert.rejects(()=>api.controlEvidence(probe.descriptor),/unavailable/);await probe.close();
probe=await open(testCase,ctx);root=probe.descriptor.root;
const button=root.querySelector('[data-planned-action="map-in"]');button.replaceWith(button.cloneNode(true));
await assert.rejects(()=>api.controlEvidence(probe.descriptor),/did not change/);await probe.close();
""", desktop_page)


def test_legacy_real_toggles_do_not_change_authority_and_wrong_purpose_fails(desktop_page):
    node(r"""
const {win,descriptor}=legacy(),before=api.authorityEvidence(descriptor,true);
const rows=api.layerEvidence(descriptor,true);assert.equal(rows.length,7);
assert.equal(rows.find(row=>row.layer==='checkpoints').groups,2);
assert.deepEqual(api.authorityEvidence(descriptor,true),before);
descriptor.root.dataset.workspaceRouteEvidence='true';assert.throws(()=>api.illustrationEvidence(descriptor),/authority boundary/);
await assert.rejects(()=>win.eval("postLivingAction('/living/approvals', {})"),/read-only/);
assert.equal(calls.length,0);
assert.equal(win.scoutLegacyMapPurposeBridge.dispose().pendingRefresh,false);
""", desktop_page)


def test_saved_restore_catalog_anchors_and_analysis_role_are_bound(desktop_page):
    node(r"""
selected.manifest.request.name_resolutions={junction:'golden.anchor'};
const ctx=await context(),testCase=api.CASES.find(row=>row.key==='permission-preview');
const probe=await open(testCase,ctx);
assert.equal(probe.descriptor.sourceAnchors.length,4);
assert.equal(api.anchorEvidence(probe.descriptor,probe.descriptor.sourceAnchors).renderedAnchors,4);
probe.descriptor.root.querySelector('[data-planned-map-anchor]').dataset.plannedMapAnchor='wrong-source';
assert.throws(()=>api.anchorEvidence(probe.descriptor,probe.descriptor.sourceAnchors),/identity/);await probe.close();
const analysisCase=api.CASES.find(row=>row.key==='analysis-navigation'),analysisProbe=await open(analysisCase,ctx);
analysisProbe.descriptor.root.dataset.plannedMapAnalysisRole='weather';
assert.throws(()=>api.inspectBinding(analysisProbe.descriptor,analysisCase,ctx),/another force/);await analysisProbe.close();
""", desktop_page)


def test_saved_missing_golden_cannot_borrow_the_current_catalog_geometry(desktop_page):
    node(r"""
const ctx=await context();selected.preview.golden_geojson=null;catalog.golden_geojson=clone(golden);
// Exercise only the production Saved-version renderer. A fresh D049 read must
// reject this incomplete comparison before it can contribute a passing row.
const probe=await open(api.CASES.find(row=>row.key==='permission-preview'),ctx);
assert.equal(probe.descriptor.root.querySelectorAll('[data-planned-map-layer="golden"]').length,0);
assert.equal(probe.descriptor.root.querySelector('[data-planned-map-toggle="golden"]').disabled,true);
assert.match(probe.descriptor.root.textContent,/來源幾何未提供/);await probe.close();
assert.match((await context()).plannedError,/missing Golden/);
""", desktop_page)


def test_legacy_factory_uses_actual_emergency_entry_and_replay_scope(desktop_page):
    node(r"""
const win=dashboard(),state=win.__purposeReplayState;
state.permissionDataStatus='ready';state.permissionProjection={project_id:project,movement_groups:[]};
state.permissionReviewSession={project_id:project,mission_day_instance_id:'day.fixture',alternatives:[],receipts:[]};
let permissionReads=0;
win.loadDataScope=async(scope)=>{assert.equal(scope,'permission');assert.equal(state.route,'emergency');permissionReads++;};
const loading=win.scoutDashboardMapPurposeProbe.prepare(api.CASES.at(-1),{projectId:project});
await new Promise(resolve=>setImmediate(resolve));
const frame=win.document.querySelector('#workspace iframe');assert.ok(frame);
assert.equal(new URL(frame.src).pathname,'/admin/dashboard/emergency-approval-desktop-v0');
assert.equal(new URL(frame.src).searchParams.get('diagnosticMapProbe'),'1');
assert.equal(new URL(frame.src).searchParams.has('living'),false);
// Browser navigation seam: actual transformed HTML/script loads in the final
// same-origin document; frame readiness/identity and production bridge execute.
const child=legacy();assert.equal(child.win.location.href,frame.src);
Object.defineProperty(frame,'contentDocument',{value:child.win.document,configurable:true});
Object.defineProperty(frame,'contentWindow',{value:child.win,configurable:true});
const descriptor=await loading;assert.equal(permissionReads,1);
assert.equal(api.illustrationEvidence(descriptor).workspaceRouteEvidence,false);
assert.equal(api.layerEvidence(descriptor,true).length,7);
const cleanup=await win.scoutDashboardMapPurposeProbe.dispose();assert.equal(cleanup.disposed,true,JSON.stringify(cleanup));
assert.equal(win.document.querySelectorAll('#workspace iframe').length,0);
""", desktop_page)


@pytest.mark.parametrize("status", ["blocked", "loading", "ready"])
def test_legacy_entry_remains_illustrative_in_all_daily_review_states(status, desktop_page):
    node("const status=" + json.dumps(status) + r""";
const win=dashboard(),state=win.__purposeReplayState;
state.permissionDataStatus=status;state.permissionProjection={project_id:project,status,
 error:{code:'contextual_permission_projection_stale',message:'A newer reviewed baseline is selected; rebuild Contextual Permission artifacts explicitly.'}};
state.permissionReviewSession=status==='ready'?{mission_day_instance_id:'recorded.fixture',alternatives:[],receipts:[]}:null;
const before=JSON.stringify(state.permissionProjection),root=new win.DOMParser().parseFromString(win.renderEmergencyPage(),'text/html');
const expected=status==='blocked'?'unavailable':status;
assert.equal(root.querySelector('[data-daily-emergency-review]').dataset.dailyEmergencyReview,expected);
assert.equal(root.querySelectorAll('[data-emergency-legacy-illustration]').length,1);
const entry=root.querySelector('[data-emergency-approval-frame="desktop"]');
assert.equal(new URL(entry.getAttribute('src'),origin).searchParams.get('projectId'),project);
assert.match(root.querySelector('[data-emergency-legacy-illustration]').textContent,/固定 SVG.*不代表/);
assert.equal(state.permissionDataStatus,status);assert.equal(JSON.stringify(state.permissionProjection),before);
if(status==='blocked'){
 assert.match(root.body.textContent,/Daily Emergency Review unavailable/);
 assert.match(root.body.textContent,/A newer reviewed baseline is selected/);
 assert.match(root.body.textContent,/Phase 1 mutation remain closed/);
}
if(status!=='ready')assert.equal(root.querySelectorAll('[data-emergency-decision],[data-emergency-confirm-submit]').length,0);
assert.equal(calls.length,0);
""", desktop_page)


def test_recorded_9099_blocked_response_preserves_state_and_completes_legacy(desktop_page):
    # The default is a redacted recording of the 9099 failure shape. The explicit
    # HTTP replay run uses the unmodified response bodies and source hashes kept
    # on Scout, including ancillary GETs required by the production loader.
    capture_dir = os.environ.get("SCOUT_PURPOSE_HTTP_REPLAY_DIR")
    if capture_dir:
        capture = Path(capture_dir)
        receipt = json.loads((capture / "receipt.json").read_text())
        selected_project = receipt["project_id"]
        imports = r"""
const capture=process.env.SCOUT_PURPOSE_HTTP_REPLAY_DIR,path=require('node:path'),crypto=require('node:crypto');
const receipt=JSON.parse(fs.readFileSync(path.join(capture,'receipt.json'),'utf8'));
const responses=new Map();
for(const [name,entry]of Object.entries(receipt.responses)){
 const content=fs.readFileSync(path.join(capture,name+(name==='legacy-desktop'?'.html':'.json')),'utf8');
 assert.equal(crypto.createHash('sha256').update(content).digest('hex'),entry.body_sha256);
 assert.equal(entry.status,200);assert.equal(new URL(entry.url).origin,'http://127.0.0.1:9099');
 responses.set(new URL(entry.url).pathname+new URL(entry.url).search,{...entry,body:content});
}
const projection=JSON.parse(responses.get(prefix+'/contextual-permission-dashboard?lens=replay').body);
const childHtml=responses.get('/admin/dashboard/emergency-approval-desktop-v0?projectId='+project+'&diagnosticMapProbe=1').body;
const evidenceBasis='actual-9099-GET-response-replay';
"""
    else:
        selected_project = "purpose_replay"
        imports = r"""
const projection={artifact_kind:'contextual_permission_dashboard_projection',schema_version:'contextualPermissionDashboard.v1',
 project_id:project,status:'blocked',error:{code:'contextual_permission_projection_stale',
 message:'A newer reviewed baseline is selected; rebuild Contextual Permission artifacts explicitly.'},
 missing_inputs:['contextual_permission_projection_stale'],candidate_only:true,runtime_safety_truth:false};
const responses=new Map([
 [prefix+'/contextual-permission-dashboard?lens=replay',{body:JSON.stringify(projection)}],
 [prefix+'/mission-baseline/map-context',{body:JSON.stringify({project_id:project})}],
 [prefix+'/mission-baseline/candidates',{body:JSON.stringify({project_id:project,candidates:[]})}],
]);
const childHtml=legacyHtml,evidenceBasis='redacted-recorded-blocked-shape-with-isolated-ancillary-read-seams';
"""
    node(imports + r"""
assert.equal(projection.project_id,project);assert.equal(projection.status,'blocked');
assert.equal(projection.error.code,'contextual_permission_projection_stale');assert.equal(projection.daily_review,undefined);
const getReceipts=[],opened=[];
const row=await api.runCase(api.CASES.at(-1),{projectId:project},{open:async(testCase,ctx)=>{
 const win=dashboard({productionLoaders:true}),state=win.__purposeReplayState;
 win.fetch=async(url,options={})=>{
  assert.ok(!options.method||options.method==='GET','No writes/rebuilds');
  const key=new URL(String(url),origin).pathname+new URL(String(url),origin).search;
  const response=responses.get(key);assert.ok(response,'Unexpected GET '+key);getReceipts.push({method:'GET',path:key});
  return {ok:true,json:async()=>JSON.parse(response.body)};
 };
 const preparation=win.scoutDashboardMapPurposeProbe.prepare(testCase,ctx);
 await new Promise(resolve=>setImmediate(resolve));
 const frame=win.document.querySelector('#workspace iframe');assert.ok(frame,'Blocked state lost the actual Legacy entry');
 const child=domPage(childHtml,frame.src);
 for(const script of child.document.querySelectorAll('script:not([src])'))child.eval(script.textContent);
 Object.defineProperty(frame,'contentDocument',{value:child.document,configurable:true});
 Object.defineProperty(frame,'contentWindow',{value:child,configurable:true});
 const descriptor=await preparation;
 assert.equal(state.permissionDataStatus,'blocked');assert.equal(state.permissionReviewSession,null);
 assert.deepEqual(JSON.parse(JSON.stringify(state.permissionProjection)),projection);
 assert.equal(descriptor.dailyReviewContext.state,'unavailable');assert.equal(descriptor.dailyReviewContext.projectionStatus,'blocked');
 assert.equal(descriptor.dailyReviewContext.projectionErrorCode,'contextual_permission_projection_stale');
 opened.push({dailyReviewContext:descriptor.dailyReviewContext,entry:frame.src});
 return {descriptor,close:async()=>{const result=await win.scoutDashboardMapPurposeProbe.dispose();child.close();win.close();return result;}};
}});
assert.equal(row.status,'passed',JSON.stringify(row));assert.equal(row.stages.length,4);
assert.equal(row.stages.find(stage=>stage.stage==='layer-toggles').evidence.length,7);
assert.equal(row.cleanup.length,2);assert.ok(row.cleanup.every(cleanup=>cleanup.status==='passed'));
assert.equal(getReceipts.length,6);assert.ok(getReceipts.every(read=>read.method==='GET'));
if(process.env.SCOUT_PURPOSE_HTTP_REPLAY_REPORT)fs.writeFileSync(process.env.SCOUT_PURPOSE_HTTP_REPLAY_REPORT,
 JSON.stringify({basis:evidenceBasis,projectId:project,opened,reads:getReceipts,row},null,2));
""", desktop_page, project_override=selected_project)


def test_missing_second_saved_version_does_not_compare_to_itself(desktop_page):
    node(r"""
versions.versions=[selected.manifest];const ctx=await context();assert.match(ctx.compareError,/No second saved/);
const row=await api.runCase(api.CASES.find(row=>row.mapId==='compare'),ctx,{open:()=>{throw Error('Should not open');}});
assert.equal(row.status,'failed');assert.match(row.stages[0].detail,/No second saved/);
""", desktop_page)


def test_read_boundary_and_missing_or_duplicate_entry_fail_without_effects(desktop_page):
    node(r"""
const win=dashboard(),before=calls.length;
for(const path of ['https://other.test'+prefix+'/analysis-subject','/admin/pretrip/projects/another/analysis-subject',prefix+'/analysis-subject?refresh=1'])
 await assert.rejects(()=>win.diagnosticMapPurposeRead(path),/escaped/);
assert.equal(calls.length,before);
const ctx=await context(),testCase=api.CASES.find(row=>row.key==='analysis-weather');
const original=win.renderOutdoorPage;
win.renderOutdoorPage=route=>original(route)+original(route);
await assert.rejects(()=>win.scoutDashboardMapPurposeProbe.prepare(testCase,ctx),/duplicates/);
win.renderOutdoorPage=()=>'<p>Missing actual production map</p>';
await assert.rejects(()=>win.scoutDashboardMapPurposeProbe.prepare(testCase,ctx),/missing/);
await win.scoutDashboardMapPurposeProbe.dispose();
""", desktop_page)


def test_workspace_change_stops_new_entries_and_keeps_complete_failed_report(desktop_page):
    node(r"""
let current='another_workspace',opened=0;
const report=await api.run({projectId:project,currentProjectId:()=>current,read,open:()=>{opened++;throw Error('Should not open');}});
assert.equal(opened,0);assert.equal(report.status,'failed');assert.equal(report.rows.length,10);
assert.match(report.scopeError,/Workspace changed/);assert.ok(report.rows.every(row=>row.status==='failed'));
""", desktop_page)


def test_report_dom_preserves_full_json_rows_and_escapes_source_text(desktop_page):
    node(r"""
const win=dashboard(),report={projectId:project,status:'failed',rows:[{key:'permission-preview',status:'failed',
 stages:[{stage:'source-geometry',status:'failed',detail:'<img src=x onerror=bad()> missing Golden'}]}]};
const rendered=win.renderDiagnosticMapPurposeResults(report),root=win.document.createElement('div');
root.innerHTML=rendered;win.document.body.appendChild(root);
assert.equal(root.querySelectorAll('img').length,0);assert.equal(root.querySelectorAll('[data-diagnostic-map-purpose-row]').length,1);
assert.deepEqual(JSON.parse(root.querySelector('[data-diagnostic-map-purpose-json]').textContent),report);
root.querySelector('details').open=true;assert.match(win.renderDiagnosticMapPurposeResults(report),/data-diagnostic-map-purpose-evidence open/);
""", desktop_page)


def test_selected_analysis_revision_invalidates_previous_d049_result(desktop_page):
    node(r"""
const win=dashboard(),state=win.__purposeReplayState;
state.analysisSubject=clone(subject);const scopeKey=win.diagnosticCaseScopeKey('DASH-049');
state.diagnosticResults={'DASH-049':{scopeKey,status:'passed',detail:'previous evidence'}};
assert.equal(win.diagnosticResult('DASH-049').status,'passed');
state.analysisSubject.analysis_revision='1'.repeat(64);
assert.notEqual(win.diagnosticCaseScopeKey('DASH-049'),scopeKey);
assert.equal(win.diagnosticResult('DASH-049').status,'idle');
""", desktop_page)


def test_missing_duplicate_rows_and_cleanup_failure_cannot_pass(desktop_page):
    node(r"""
const rows=api.CASES.map(row=>({...row,status:'passed'}));assert.equal(api.summarize(rows).status,'passed');
assert.equal(api.summarize(rows.slice(1)).status,'failed');
assert.equal(api.summarize([...rows.slice(1),rows[1]]).status,'failed');
const ctx=await context(),testCase=api.CASES.at(-1);
const row=await api.runCase(testCase,ctx,{open:async(c,context)=>{const probe=await open(c,context);return {...probe,close:async()=>{await probe.close();throw Error('cleanup failure');}};}});
assert.equal(row.status,'failed');assert.equal(row.cleanup[0].status,'failed');
const next=await api.runCase(testCase,ctx,{open});assert.equal(next.status,'passed');
""", desktop_page)


def test_only_actual_dashboard_registry_runs_d049_and_keeps_json_visible():
    source = PAGE.read_text()
    assert len(re.findall(r'id: "DASH-049"', source)) == 1
    assert 'run: diagnosticCheck049' in source
    assert 'await import("/admin/scout-map-purpose-diagnostic.js")' in source
    assert '<script src="/admin/scout-map-purpose-diagnostic.js"' not in source
    assert 'renderDiagnosticMapPurposeResults(result.mapPurposeReport)' in source
    assert 'data-diagnostic-map-purpose-json' in source
    assert 'data-diagnostic-map-purpose-row=' in source
    # Source inventory is tied to reachable route declarations, not merely a
    # hand-maintained denominator. The runtime also rejects missing map roots.
    six_forces = source[source.index('const SIX_FORCES ='):source.index('const SIX_FORCES =') + 3000]
    declared = set(re.findall(r'route: "(outdoor-[^"]+)"', six_forces))
    assert declared == {f"outdoor-{role}" for role in ("route-context", "permission", "weather", "navigation", "architecture", "pace-fit")}
