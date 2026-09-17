"""Formal Diagnostic runner preserves map sub-results into readable DOM JSON."""

import json
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _run(body):
    text = PAGE.read_text()
    names = ("runDashboardDiagnostic", "diagnosticResult", "diagnosticSetResult", "diagnosticCaseScopeKey",
             "diagnosticRequire", "diagnosticSafeDetail", "renderDiagnosticCase", "diagnosticStatusLabel")
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", text)
        assert match, name
        functions.append(match.group())
    script = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const {window}=new JSDOM('<body/>');const document=window.document;
let project='workspace-a';const projectId=()=>project,resolvedPretripProjectId=()=>project,apiBase=()=>'';
const NAVIGATION_DIAGNOSTIC_CASE_IDS=[],diagnosticResourceCache=new Map();
const diagnosticExecutionBusy=()=>false,updateDiagnosticDom=()=>{};
const state={diagnosticResults:{}};
const escapeHtml=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const renderDiagnosticEvidenceStatus=()=>'',renderDiagnosticMapOrderResults=()=>'';
const renderDiagnosticRudyResults=report=>report?'<pre data-diagnostic-rudy-json>'+escapeHtml(JSON.stringify(report))+'</pre>':'';
const item={id:'DASH-027',title:'Map controls',description:'Actual diagnostic evidence'};
const DASHBOARD_DIAGNOSTIC_CASES=[item];
const badCleanup={disposed:false,activeMaps:1,pendingInitializations:1,errors:[{phase:'renderer_destroy',errorName:'Error'}]};
const evidence={mapInteractions:{rows:[{id:'navigation-map',renderer:'maplibre',variant:'2d:structure',check:'DASH-027',status:'failed',detail:'missing control'}]},
  nativeTiles:{cases:[{key:'map:svg',status:'warning'}]},cameraHelper:{status:'passed'},
  cameraPage:{status:'failed',phases:[{id:'layer-toggle',status:'failed'}]},
  cleanup:badCleanup,cleanupStatus:'warning',mapLayerOrder:{surfaces:[{id:'map',status:'failed',violations:[{code:'wrong-order'}]}]}};
const exported=()=>{
  const host=document.createElement('div');host.innerHTML=renderDiagnosticCase(item);
  const node=host.querySelector('[data-diagnostic-map-evidence-json]');
  return {host,data:node?JSON.parse(node.textContent):null};
};
''' + "\n".join(functions) + "\n(async()=>{\n" + body + r'''
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>window.close());
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("status", ["passed", "warning", "failed"])
def test_formal_outcomes_retain_map_child_failures_and_cleanup_in_dom(status):
    result = _run("""
item.run=async()=>({status:%s,detail:'map evidence retained',...evidence});
const result=await runDashboardDiagnostic(item.id),{data}=exported();
assert.equal(result.status,%s);assert.deepEqual(result.mapInteractions,evidence.mapInteractions);
assert.deepEqual(result.nativeTiles,evidence.nativeTiles);assert.deepEqual(data.cameraPage,evidence.cameraPage);
assert.equal(data.mapInteractions.rows[0].status,'failed');assert.equal(data.cleanup.disposed,false);
assert.equal(data.cleanupStatus,'warning');assert.equal(data.projectId,'workspace-a');
console.log(JSON.stringify({status:result.status,exported:true}));
""" % (json.dumps(status), json.dumps("warning" if status == "passed" else status)))
    assert result == {"status": "warning" if status == "passed" else status, "exported": True}


def test_successful_cleanup_and_evidence_are_retained_without_downgrading_pass():
    result = _run(r'''
const clean={disposed:true,activeMaps:0,pendingInitializations:0,errors:[]};
const mapInteractions={rows:[{id:'map',renderer:'svg',check:'DASH-027',status:'passed'}]};
item.run=async()=>({status:'passed',detail:'all controls passed',mapInteractions,cleanup:clean});
const result=await runDashboardDiagnostic(item.id),{data}=exported();
assert.equal(result.status,'passed');assert.equal(result.cleanupStatus,'passed');
assert.deepEqual(data.mapInteractions,mapInteractions);assert.deepEqual(data.cleanup,clean);
console.log(JSON.stringify({passed:true}));
''')
    assert result["passed"]


def test_throw_path_keeps_cleanup_receipt_and_original_failure_in_readable_json():
    result = _run(r'''
item.run=async()=>{const value={...evidence};delete value.cleanup;throw Object.assign(Error('original map failure'),value,{cleanupReceipt:badCleanup})};
const result=await runDashboardDiagnostic(item.id),{data}=exported();
assert.equal(result.status,'failed');assert.equal(result.detail,'original map failure');
assert.equal(data.cleanup.disposed,false);assert.equal(data.mapInteractions.rows[0].detail,'missing control');
console.log(JSON.stringify({retained:true}));
''')
    assert result["retained"]


def test_running_state_clears_prior_map_evidence_before_the_next_result_arrives():
    result = _run(r'''
item.run=async()=>({status:'failed',detail:'first',...evidence});await runDashboardDiagnostic(item.id);
let finish;item.run=()=>new Promise(resolve=>{finish=resolve});const pending=runDashboardDiagnostic(item.id);
const running=diagnosticResult(item.id);assert.equal(running.status,'running');
for(const key of ['mapInteractions','nativeTiles','cameraHelper','cameraPage','cleanup','cleanupStatus','mapLayerOrder','rudyNativeReport'])assert.equal(running[key],null,key);
assert.equal(exported().data,null);finish({status:'passed',detail:'next result'});await pending;
console.log(JSON.stringify({cleared:true}));
''')
    assert result["cleared"]


@pytest.mark.parametrize("failure", [False, True])
def test_scope_change_cannot_publish_or_export_previous_workspace_evidence(failure):
    result = _run("""
item.run=async()=>{project='workspace-b';%s};
await runDashboardDiagnostic(item.id);const stored=state.diagnosticResults[item.id];
assert.equal(diagnosticResult(item.id).status,'idle');assert.equal(exported().data,null);
for(const key of ['mapInteractions','nativeTiles','cameraPage','cleanup','mapLayerOrder'])assert.equal(stored[key],null,key);
console.log(JSON.stringify({isolated:true}));
""" % ("throw Object.assign(Error('old failure'),evidence)" if failure else "return {status:'failed',detail:'old result',...evidence}"))
    assert result["isolated"]


def test_d038_uses_same_dom_export_and_d037_keeps_only_existing_large_report():
    result = _run(r'''
item.id='DASH-038';item.run=async()=>({status:'failed',detail:'page failed',cameraHelper:evidence.cameraHelper,cameraPage:evidence.cameraPage});
await runDashboardDiagnostic(item.id);assert.equal(exported().data.cameraPage.phases[0].status,'failed');
item.id='DASH-037';item.run=async()=>{diagnosticSetResult(item.id,{rudyNativeReport:evidence.nativeTiles});return {status:'warning',detail:'native incomplete',nativeTiles:evidence.nativeTiles}};
await runDashboardDiagnostic(item.id);const {host,data}=exported();assert.equal(data,null);assert.equal(host.querySelectorAll('[data-diagnostic-rudy-json]').length,1);
assert.deepEqual(diagnosticResult(item.id).nativeTiles,evidence.nativeTiles);
console.log(JSON.stringify({cameraExported:true,nativeNotDuplicated:true}));
''')
    assert result == {"cameraExported": True, "nativeNotDuplicated": True}
