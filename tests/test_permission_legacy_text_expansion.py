"""Exercise Legacy authoring disclosure using shipped render/bind/preview code.

JSDOM supplies native details events; only the outer page replacement and API
transport are isolated. These checks do not replace the actual Chrome replay.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _source_receipt(record_testsuite_property) -> None:
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _run(body: str, *, old_render: bool = False, unguarded_toggle: bool = False) -> dict:
    setup = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('docs/admin/scout-dashboard-v0.1.html', 'utf8');
const dom = new JSDOM('<body><main id="workspace"></main></body>', {
  url:'http://localhost/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport',
  runScripts:'outside-only',
});
const {window} = dom;
window.fetch = () => {throw Error('Unexpected network access')};
function source(name) {
  const match = html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }', 'm'));
  assert.ok(match, 'Missing shipped function '+name);
  return match[0];
}
const names = ['renderPermissionBaselineAuthoring', 'renderPermissionBaselineProposal',
  'renderPermissionBaselineQuickReview', 'bindPermissionControls',
  'previewPermissionBaseline', 'resetPermissionBaselineReviewChecks', 'permissionHasReferenceReplay'];
let functions = names.map(source).join('\n');
if (OLD_RENDER) functions = functions.replace(
  '${state.permissionLegacyTextAuthoringExpanded ? "open" : ""}', '');
if (UNGUARDED_TOGGLE) functions = functions.replace('if (!legacyTextAuthoring.isConnected) return;', '');
const initialExpanded = html.match(/^      permissionLegacyTextAuthoringExpanded: (false),$/m);
assert.ok(initialExpanded, 'Production state must initially close Legacy authoring');
window.eval(functions + '\n' + String.raw`
const state = {
  route:'outdoor-permission', permissionBaselineMode:'human_text',
  permissionLegacyTextAuthoringExpanded: INITIAL_EXPANDED,
  permissionBaselineText:'D1：起點 - 營地C1', permissionBaselineDraft:null,
  permissionBaselineSavedCandidate:null, permissionBaselineCandidates:[],
  permissionBaselineCandidateRef:'', permissionBaselineCatalogStatus:'ready',
  permissionBaselineBusy:false, permissionBaselineStatus:'',
  permissionBaselinePatchText:'', permissionBaselinePatchPreview:null,
  permissionBaselineMapContext:null, permissionBaselineMapStatus:'idle',
  permissionBaselinePendingAction:null,
  permissionBaselineReviewChecks:{candidateSha256:'',dayEnds:false,timingUncertainty:false,safetyHandoff:false},
  analysisSubject:{kind:'golden',source_sha256:'a'.repeat(64)},
  selectedGeometry:{source:'unchanged',points:[[121,23],[121.1,23.1]]},
  terrainGuidanceReview:{R4:'pending'}, runtime_safety_truth:false,
};
const asArray = value => Array.isArray(value) ? value : [];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const resolvedPretripProjectId = () => 'dongqing_batongguan_historic_trail_newImport';
const bindPermissionDayMaps = () => {};
// The restored workflow host references this dependency. This isolated Legacy
// replay must never invoke it or mutate the shared six-force analysis selection.
const refreshSixAxisAfterBaselineChange = () => {throw Error('Unexpected six-force analysis refresh')};
const calls = [];
let completeRequest, rejectRequest;
const postJson = (path,payload) => {
  calls.push({path,payload});
  return new Promise((resolve,reject) => {completeRequest=resolve;rejectRequest=reject;});
};
const loadPermissionBaselineMapContext = () => {throw Error('Unexpected reference map load')};
const snapshots = [];
function panel() {return document.querySelector('[data-permission-legacy-text-authoring="true"]')}
function render() {
  document.getElementById('workspace').innerHTML = renderPermissionBaselineAuthoring();
  bindPermissionControls();
  snapshots.push({open:panel()?.open ?? null,status:state.permissionBaselineStatus});
}
function immutableState() {
  const {permissionLegacyTextAuthoringExpanded, ...data} = state;
  return JSON.stringify(data);
}
const tick = () => new Promise(resolve => window.setTimeout(resolve,5));
async function togglePanel() {panel().querySelector('summary').click();await tick()}
const preview = {source_mode:'human_text',proposal_profile:'legacy_sparse',validation_state:'needs_review',
  source_text:state.permissionBaselineText,days:[{mission_day_id:'D1'}],unresolved_gaps:['D1:alias:C1'],
  candidate_only:true,runtime_safety_truth:false,writes_performed:false};
window.probe = {state,calls,snapshots,panel,render,tick,togglePanel,immutableState,
  finish:()=>completeRequest(preview),fail:()=>rejectRequest(Error('preview unavailable'))};
render();
`.replace('INITIAL_EXPANDED', initialExpanded[1]));
const {document} = window;
const api = window.probe;
"""
    program = (
        f"const OLD_RENDER={json.dumps(old_render)}, UNGUARDED_TOGGLE={json.dumps(unguarded_toggle)};\n"
        + setup
        + "\n(async()=>{try{"
        + body
        + "}finally{window.close()}})().then(value=>process.stdout.write(JSON.stringify(value)))"
        + ".catch(error=>{process.stderr.write(String(error.stack||error));process.exitCode=1});"
    )
    completed = subprocess.run(
        ["node"], input=program, text=True, capture_output=True, cwd=ROOT, timeout=20,
        env={key:value for key,value in os.environ.items() if key != "NODE_OPTIONS"},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_initial_closed_and_native_toggle_only_change_presentation_state() -> None:
    result = _run("""
assert.equal(api.panel().open,false);
const before = api.immutableState();
await api.togglePanel();
assert.equal(api.state.permissionLegacyTextAuthoringExpanded,true);
api.render();await api.tick();
assert.equal(api.panel().open,true);
assert.equal(api.immutableState(),before);
assert.equal(api.calls.length,0);
return {snapshots:api.snapshots};
""")
    assert [row["open"] for row in result["snapshots"]] == [False, True]


@pytest.mark.parametrize("action", ["preview", "generate"])
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_preview_keeps_open_through_pending_and_settled_render(action: str, outcome: str) -> None:
    result = _run(f"""
await api.togglePanel();
document.querySelector('[data-permission-baseline-{action}]').click();
assert.equal(api.panel().open,true,'pending render must retain expansion');
assert.match(api.state.permissionBaselineStatus,/no-write/);
assert.equal(api.calls.length,1);
assert.ok(api.calls[0].path.endsWith('/mission-baseline/{'preview' if action == 'preview' else 'generate-draft'}'));
assert.equal(api.calls[0].payload.mode,'human_text');
api.{'finish' if outcome == 'success' else 'fail'}();await api.tick();
assert.equal(api.panel().open,true,'settled render must retain expansion');
assert.equal(api.state.permissionLegacyTextAuthoringExpanded,true);
assert.equal(api.state.permissionBaselineSavedCandidate,null);
assert.equal(api.state.permissionBaselinePendingAction,null);
return {{snapshots:api.snapshots,status:api.state.permissionBaselineStatus,markup:api.panel().textContent}};
""")
    assert [row["open"] for row in result["snapshots"]] == [False, True, True]
    if outcome == "success":
        assert "1 mission days" in result["status"]
        assert "1 mission day row" in result["markup"]
    else:
        assert "Draft failed closed" in result["status"]
        assert "preview unavailable" in result["markup"]


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_manual_close_during_request_remains_closed_after_response(outcome: str) -> None:
    result = _run(f"""
await api.togglePanel();
document.querySelector('[data-permission-baseline-preview]').click();
await api.togglePanel();
assert.equal(api.state.permissionLegacyTextAuthoringExpanded,false);
api.{'finish' if outcome == 'success' else 'fail'}();await api.tick();
assert.equal(api.panel().open,false);
api.render();await api.tick();
assert.equal(api.panel().open,false);
return {{snapshots:api.snapshots}};
""")
    assert [row["open"] for row in result["snapshots"]] == [False, True, False, False]


STALE_TOGGLE_PROBE = """
await api.togglePanel();
const detached = api.panel();
api.render();
assert.equal(detached.isConnected,false);
detached.open=false;
detached.dispatchEvent(new window.Event('toggle'));
await api.tick();
assert.equal(api.state.permissionLegacyTextAuthoringExpanded,true,'detached toggle must not overwrite live choice');
api.render();await api.tick();
assert.equal(api.panel().open,true);
return {open:api.panel().open};
"""


def test_detached_queued_toggle_cannot_override_current_disclosure() -> None:
    assert _run(STALE_TOGGLE_PROBE)["open"] is True


def test_expansion_survives_mode_roundtrip_without_restoring_candidate_data() -> None:
    result = _run("""
await api.togglePanel();
api.state.permissionBaselineDraft={source_mode:'human_text',days:[],unresolved_gaps:[]};
api.state.permissionBaselineSavedCandidate={version_ref:'candidate/old',review_ready:false};
const retained=JSON.stringify([api.state.analysisSubject,api.state.selectedGeometry,api.state.terrainGuidanceReview]);
document.querySelector('[data-permission-baseline-mode="reference_gpx"]').click();
await api.tick();
assert.equal(api.panel(),null);
assert.equal(api.state.permissionBaselineDraft,null);
assert.equal(api.state.permissionBaselineSavedCandidate,null);
document.querySelector('[data-permission-baseline-mode="human_text"]').click();
await api.tick();
assert.equal(api.panel().open,true);
assert.equal(api.state.permissionBaselineDraft,null);
assert.equal(api.state.permissionBaselineSavedCandidate,null);
assert.equal(JSON.stringify([api.state.analysisSubject,api.state.selectedGeometry,api.state.terrainGuidanceReview]),retained);
assert.equal(api.state.runtime_safety_truth,false);
assert.equal(api.calls.length,0);
return {snapshots:api.snapshots};
""")
    assert [row["open"] for row in result["snapshots"]] == [False, None, True]


def test_checks_detect_old_unconditional_closed_render() -> None:
    with pytest.raises(AssertionError, match="pending render lost expansion"):
        _run("""
await api.togglePanel();
document.querySelector('[data-permission-baseline-preview]').click();
assert.equal(api.panel().open,true,'pending render lost expansion');
return {};
""", old_render=True)


def test_checks_detect_missing_detached_event_guard() -> None:
    with pytest.raises(AssertionError, match="detached toggle must not overwrite live choice"):
        _run(STALE_TOGGLE_PROBE, unguarded_toggle=True)
