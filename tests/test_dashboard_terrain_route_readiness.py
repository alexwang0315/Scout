from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _run(functions: tuple[str, ...], probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for Dashboard readiness tests")
    html = PAGE.read_text(encoding="utf-8")
    source = []
    for name in functions:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", html)
        assert match, f"Missing Dashboard function: {name}"
        source.append(match.group())
    result = subprocess.run(
        [node], input="\n".join((HARNESS, *source, "(async () => {", probe,
                                "})().catch(error => { console.error(error); process.exitCode = 1; });")),
        text=True, capture_output=True, check=False, cwd=ROOT, timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


HARNESS = r"""
const assert = require('node:assert/strict');
const nodes = new Map();
const document = {
  querySelector: selector => nodes.get(selector) || null,
  querySelectorAll: selector => selector.split(',').flatMap(part => nodes.has(part.trim()) ? [nodes.get(part.trim())] : []),
};
for (const suffix of ['builder','status','worker-chip','generate','check-worker','check-label','start-worker','start-label','select','reset','use-selected-hypothesis']) {
  nodes.set(`[data-qgis-terrain-route-${suffix}]`, {
    dataset:{}, disabled:false, textContent:'', attributes:{},
    setAttribute(name,value) { this.attributes[name] = value; },
    querySelector: document.querySelector, querySelectorAll: document.querySelectorAll,
  });
}
nodes.set('[data-terrain-guidance-generate-r4]', {disabled:false});
const QGIS_TERRAIN_ROUTE_WORKFLOW_ID = 'terrain_route_hypothesis.v1';
const QGIS_NAVIGATION_PRIMARY_WORKFLOW_ID = 'terrain_feature_stack.v1';
const QGIS_SPATIAL_FETCH_TIMEOUT_MS = 45000;
const QGIS_SPATIAL_WORKFLOW_TIMEOUT_MS = 180000;
const NAVIGATION_TERRAIN_FETCH_TIMEOUT_MS = 45000;
const asArray = value => Array.isArray(value) ? value : [];
const healthy = {availability:'available', enabled:true, configured:true, reachable:true,
  qgis_application_available:true, plugin_bridge_available:true, capabilities_discoverable:true, fixture_mode:false};
const capabilities = {workflow_allowlist:[QGIS_TERRAIN_ROUTE_WORKFLOW_ID]};
const runtime = {can_start:true,code:'IDLE',status:'idle',authority:'candidate_only'};
const state = {qgisSpatialStatus:{...healthy, availability:'unavailable', reachable:false},
  qgisSpatialCapabilities:capabilities, qgisSpatialBusy:false, qgisSpatialStatusRefreshing:false,
  qgisRuntimeControl:runtime, qgisRuntimeStarting:false, qgisRuntimeMessage:'',
  qgisSpatialWorkflow:null, qgisSpatialMessage:'', qgisTerrainRouteSelectionTarget:'',
  qgisTerrainRouteEndpoints:{start:{x:121,y:24},destination:{x:121.01,y:24.01}},
  qgisTerrainRouteCorridorM:1000, terrainRouteGuidance:{guided_execution_ready:false,review:null},
  terrainRouteGuidanceManualAnchors:{G1:{x:121,y:24}}, terrainRouteGuidanceSelectedFeatures:{G2:['f1']},
  route:'outdoor-navigation'};
let readyEndpoints = true;
const qgisTerrainRouteEndpointsReady = () => readyEndpoints;
const qgisTerrainRouteSelectionTarget = () => state.qgisTerrainRouteSelectionTarget;
const qgisTerrainRouteWorkflowActive = (workflow = state.qgisSpatialWorkflow) =>
  workflow?.workflow_id === QGIS_TERRAIN_ROUTE_WORKFLOW_ID && ['queued','running'].includes(workflow?.state);
const qgisTerrainRouteWorkflowProgress = () => ({completed:1,total:11});
const qgisTerrainRouteWorkflowStatusText = () => 'TRH 分析中';
const selectedTerrainRouteHypothesisEndpoints = () => null;
let currentProject = 'project-a';
let currentApi = '';
const projectId = () => currentProject;
const apiBase = () => currentApi;
const qgisSpatialBasePath = id => '/admin/pretrip/projects/' + (id || projectId()) + '/spatial/qgis';
let qgisTerrainRouteBackendRequest = null;
let qgisRuntimeStartRequest = null;
const calls = [];
let responses = {status:healthy,capabilities,runtime};
let beforeResponse = async () => {};
const fetchJson = async (path, options) => {
  calls.push({path,options});
  await beforeResponse();
  const value = responses[path.split('/').at(-1)];
  if (value instanceof Error) throw value;
  return value;
};
const generate = document.querySelector('[data-qgis-terrain-route-generate]');
const check = document.querySelector('[data-qgis-terrain-route-check-worker]');
const start = document.querySelector('[data-qgis-terrain-route-start-worker]');
const r4 = document.querySelector('[data-terrain-guidance-generate-r4]');
const escapeHtml = value => String(value ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
const qgisTerrainRouteEndpointText = point => point ? `${point.y}, ${point.x}` : '尚未選取';
"""

BACKEND_FUNCTIONS = (
    "qgisRuntimeControlText",
    "qgisTerrainRouteBackendReady",
    "qgisTerrainRouteBackendIssue",
    "qgisTerrainRouteBuilderStatusText",
    "updateQgisTerrainRouteBuilderWorkflowState",
)


@pytest.mark.parametrize("status", ["queued", "running", "failed", "cancelled", "completed"])
def test_trh_attempt_never_replaces_reference_gpx(status: str) -> None:
    payload = _run(("loadQgisSpatialAnalysisRoute",), f"""
const reference = {{type:'FeatureCollection',features:[{{geometry:{{type:'LineString',coordinates:[[121,24],[121.01,24.01]]}}}}]}};
state.qgisSpatialAnalysisRoute = reference;
await loadQgisSpatialAnalysisRoute({{workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:{json.dumps(status)},
  workflow_run_id:'ab-run',artifacts:[{{artifact_type:'route_geometry',artifact_id:'ab-line'}}]}});
assert.equal(state.qgisSpatialAnalysisRoute, reference);
assert.equal(calls.length, 0);
console.log(JSON.stringify({{retained:true}}));
""")
    assert payload["retained"] is True


def test_terrain_vectors_survive_failed_trh_and_reload() -> None:
    payload = _run(("loadQgisSpatialTerrainEvidence", "qgisSpatialTerrainEvidenceWorkflow",
                    "qgisSpatialBuildNormalizedWorkflowFeatures"), """
const baseline = {project_id:currentProject,workflow_id:QGIS_NAVIGATION_PRIMARY_WORKFLOW_ID,
  workflow_run_id:'terrain-run',state:'completed',maplibre_geojson:{features:[
    {type:'Feature',geometry:{type:'LineString',coordinates:[[121,24],[121.01,24.01]]},
      properties:{kind:'qgis_candidate_ridge_line',candidate_only:true,runtime_safety_truth:false}},
  ]}};
responses['latest?workflow_id=terrain_feature_stack.v1'] = baseline;
let loadedRoute = null;
globalThis.loadQgisSpatialAnalysisRoute = async run => { loadedRoute = run.workflow_run_id; };
state.qgisSpatialWorkflow = {workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:'failed',maplibre_geojson:{features:[]}};
await loadQgisSpatialTerrainEvidence();
assert.equal(loadedRoute, 'terrain-run');
assert.equal(state.qgisSpatialWorkflow.state, 'failed');
assert.equal(qgisSpatialBuildNormalizedWorkflowFeatures().length, 1);
assert.equal(qgisSpatialBuildNormalizedWorkflowFeatures()[0].properties.kind, 'qgis_candidate_ridge_line');
currentProject = 'different-project';
assert.equal(qgisSpatialBuildNormalizedWorkflowFeatures().length, 0);
console.log(JSON.stringify({retained:true}));
""")
    assert payload["retained"] is True


def test_reloaded_failure_receipt_stays_visible_with_previous_candidate() -> None:
    payload = _run(("loadQgisSpatialWorkflow", "qgisSpatialWorkflowFailureText"), """
const failed = {workflow_run_id:'failed-run',workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:'failed',
  error:{code:'NODATA_PRESENT',message:'DEM NoData'},steps:[{step_id:'dem_loaded',label:'DEM / NoData',status:'failed'}]};
responses['failed-run'] = failed;
globalThis.rememberQgisSpatialWorkflow = () => {};
globalThis.loadQgisSpatialAnalysisRoute = async () => {};
globalThis.refreshNavigationTerrainAfterCompletedRouteHypothesis = async () => {};
globalThis.navigationTerrainRouteHypothesis = () => ({id:'previous-candidate'});
await loadQgisSpatialWorkflow('failed-run');
assert.match(state.qgisSpatialMessage, /NODATA_PRESENT/);
assert.match(state.qgisSpatialMessage, /上一個/);
assert.match(state.qgisSpatialMessage, /不是本次/);
assert.equal(calls[0].options.timeoutMs, QGIS_SPATIAL_WORKFLOW_TIMEOUT_MS);
console.log(JSON.stringify({visible:true}));
""")
    assert payload["visible"] is True


@pytest.mark.parametrize("response", ["preparing", "transport_error", "source_unavailable", "project_switched"])
def test_navigation_refresh_keeps_previous_map_only_for_transient_failure(response: str) -> None:
    payload = _run(("loadNavigationTerrainData",), f"""
const previous = {{project_id:currentProject,projection_state:'ready',status:'ready',terrain_route_hypothesis:{{id:'old'}}}};
state.navigationTerrainData = previous;
globalThis.scheduleNavigationTerrainPolling = () => {{}};
globalThis.stopNavigationTerrainPolling = () => {{}};
globalThis.navigationTerrainPressureSamples = () => [];
globalThis.loadTerrainRouteGuidanceMapScope = () => {{}};
const mode = {json.dumps(response)};
responses['navigation-terrain-intelligence'] = mode === 'transport_error' ? new Error('timeout')
  : {{project_id:currentProject,status:mode === 'source_unavailable' ? 'failed' : 'preparing',retry_after_ms:1000}};
if (mode === 'project_switched') beforeResponse = async () => {{
  currentProject = 'another-project'; state.navigationTerrainData = null;
}};
try {{ await loadNavigationTerrainData(); }} catch (error) {{ assert.equal(error.message, 'timeout'); }}
if (['preparing','transport_error'].includes(mode)) {{
  assert.equal(state.navigationTerrainData, previous);
  assert.match(state.navigationTerrainRefreshMessage, /上次/);
}} else if (mode === 'source_unavailable') {{
  assert.equal(state.navigationTerrainData.status, 'failed');
}} else {{ assert.equal(state.navigationTerrainData, null); }}
console.log(JSON.stringify({{verified:true}}));
""")
    assert payload["verified"] is True


@pytest.mark.parametrize("patch", (
    {"availability": "unavailable"}, {"availability": "connecting"},
    {"availability": "degraded", "plugin_bridge_available": False},
    {"qgis_application_available": False}, {"reachable": False}, {"capabilities_discoverable": False},
    {"enabled": False}, {"configured": False}, {"fixture_mode": True},
))
def test_trh_stays_disabled_without_live_worker_and_bridge(patch: dict) -> None:
    payload = _run(BACKEND_FUNCTIONS, f"""
state.qgisSpatialStatus = {{...healthy, ...{json.dumps(patch)}}};
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, true);
assert.equal(r4.disabled, true);
assert.ok(document.querySelector('[data-qgis-terrain-route-status]').textContent.length > 30);
assert.equal(check.disabled, false);
console.log(JSON.stringify({{blocked:true}}));
""")
    assert payload["blocked"] is True


def test_trh_in_place_update_uses_same_readiness_and_human_review_gates() -> None:
    payload = _run(BACKEND_FUNCTIONS, """
state.qgisSpatialStatus = healthy;
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, false);
assert.equal(r4.disabled, true);
state.terrainRouteGuidance = {guided_execution_ready:true};
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(r4.disabled, false);
readyEndpoints = false;
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, true);
assert.equal(r4.disabled, true);
readyEndpoints = true;
state.qgisSpatialCapabilities = {workflow_allowlist:[]};
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, true);
state.qgisSpatialCapabilities = capabilities;
state.qgisSpatialWorkflow = {workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:'running'};
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, true);
assert.equal(check.disabled, true);
assert.equal(document.querySelector('[data-qgis-terrain-route-select]').disabled, true);
console.log(JSON.stringify({gates:true}));
""")
    assert payload["gates"] is True


def test_recheck_recovers_button_without_changing_ab_review_or_rendering_map() -> None:
    payload = _run((*BACKEND_FUNCTIONS, "refreshQgisTerrainRouteBackend"), """
const preserved = JSON.stringify([state.qgisTerrainRouteEndpoints,state.qgisTerrainRouteCorridorM,
  state.terrainRouteGuidance,state.terrainRouteGuidanceManualAnchors,state.terrainRouteGuidanceSelectedFeatures]);
const first = refreshQgisTerrainRouteBackend();
const second = refreshQgisTerrainRouteBackend();
assert.equal(state.qgisSpatialStatusRefreshing, true);
assert.equal(generate.disabled, true);
await Promise.all([first, second]);
assert.equal(calls.length, 3);
assert.ok(calls.every(call => !call.options.method || call.options.method === 'GET'));
assert.equal(generate.disabled, false);
assert.equal(state.qgisSpatialStatusRefreshing, false);
assert.equal(check.disabled, false);
assert.equal(preserved, JSON.stringify([state.qgisTerrainRouteEndpoints,state.qgisTerrainRouteCorridorM,
  state.terrainRouteGuidance,state.terrainRouteGuidanceManualAnchors,state.terrainRouteGuidanceSelectedFeatures]));
console.log(JSON.stringify({preserved:true}));
""")
    assert payload["preserved"] is True


@pytest.mark.parametrize("failure", ("status", "capabilities"))
def test_recheck_failure_does_not_reuse_stale_readiness_and_can_retry(failure: str) -> None:
    payload = _run((*BACKEND_FUNCTIONS, "refreshQgisTerrainRouteBackend"), f"""
state.qgisSpatialStatus = healthy;
responses = {{status:healthy,capabilities, {failure}:new Error('timeout')}};
await refreshQgisTerrainRouteBackend();
assert.equal(generate.disabled, true);
assert.equal(state.qgisSpatialStatusRefreshing, false);
assert.equal(check.disabled, false);
responses = {{status:healthy,capabilities}};
await refreshQgisTerrainRouteBackend();
assert.equal(generate.disabled, false);
console.log(JSON.stringify({{retry:true}}));
""")
    assert payload["retry"] is True


@pytest.mark.parametrize("change", ("currentProject = 'project-b'", "currentApi = 'http://new-host'"))
def test_recheck_ignores_reply_from_previous_workspace_or_server(change: str) -> None:
    payload = _run((*BACKEND_FUNCTIONS, "refreshQgisTerrainRouteBackend"), f"""
let release;
const pending = new Promise(resolve => {{ release = resolve; }});
beforeResponse = () => pending;
const oldStatus = state.qgisSpatialStatus;
const promise = refreshQgisTerrainRouteBackend();
{change};
release();
await promise;
assert.equal(state.qgisSpatialStatus, oldStatus);
assert.equal(qgisTerrainRouteBackendReady(), false);
console.log(JSON.stringify({{staleRejected:true}}));
""")
    assert payload["staleRejected"] is True


def test_recheck_does_not_probe_or_unlock_an_active_workflow() -> None:
    payload = _run((*BACKEND_FUNCTIONS, "refreshQgisTerrainRouteBackend"), """
state.qgisSpatialWorkflow = {workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:'running'};
await refreshQgisTerrainRouteBackend();
assert.equal(calls.length, 0);
updateQgisTerrainRouteBuilderWorkflowState();
assert.equal(generate.disabled, true);
console.log(JSON.stringify({runningPreserved:true}));
""")
    assert payload["runningPreserved"] is True


def test_initial_render_and_in_place_update_share_the_same_gate() -> None:
    payload = _run((*BACKEND_FUNCTIONS, "renderQgisTerrainRouteBuilder"), r"""
for (const scenario of ['unavailable','healthy','checking','starting','other_workflow','empty_ab']) {
  state.qgisSpatialStatus = scenario === 'unavailable' ? {...healthy,reachable:false} : healthy;
  state.qgisSpatialStatusRefreshing = scenario === 'checking';
  state.qgisRuntimeStarting = scenario === 'starting';
  state.qgisSpatialWorkflow = scenario === 'other_workflow' ? {workflow_id:'terrain_feature_stack.v1',state:'running'} : null;
  readyEndpoints = scenario !== 'empty_ab';
  const html = renderQgisTerrainRouteBuilder();
  const button = html.match(/<button[^>]*data-qgis-terrain-route-generate[^>]*>/)[0];
  updateQgisTerrainRouteBuilderWorkflowState();
  assert.equal(/\bdisabled\b/.test(button), scenario !== 'healthy', scenario);
  assert.equal(generate.disabled, scenario !== 'healthy', scenario);
  assert.ok(html.includes('data-qgis-terrain-route-check-worker="true"'));
  assert.ok(html.includes('data-qgis-terrain-route-start-worker="true"'));
  assert.ok(html.includes('candidate_only=true'));
  assert.ok(html.includes('runtime_safety_truth=false'));
}
console.log(JSON.stringify({sameGate:true}));
""")
    assert payload["sameGate"] is True


def test_direct_trh_submission_cannot_bypass_unavailable_worker_guard() -> None:
    payload = _run((*BACKEND_FUNCTIONS, "startQgisSpatialWorkflow"), """
let submitted = 0;
globalThis.postJson = async () => { submitted++; throw new Error('must not submit'); };
const result = await startQgisSpatialWorkflow(QGIS_TERRAIN_ROUTE_WORKFLOW_ID);
assert.equal(result, null);
assert.equal(submitted, 0);
assert.equal(state.qgisSpatialBusy, false);
assert.equal(generate.disabled, true);
console.log(JSON.stringify({noSubmission:true}));
""")
    assert payload["noSubmission"] is True


def test_completed_trh_submission_names_the_loaded_candidate_result() -> None:
    payload = _run((*BACKEND_FUNCTIONS, "startQgisSpatialWorkflow"), """
state.qgisSpatialStatus = healthy;
const run = {workflow_id:QGIS_TERRAIN_ROUTE_WORKFLOW_ID,state:'completed',artifacts:[]};
let submitOptions = null;
globalThis.postJson = async (_path, _payload, options) => { submitOptions = options; return run; };
globalThis.rememberQgisSpatialWorkflow = () => {};
globalThis.loadQgisSpatialAnalysisRoute = async () => {};
globalThis.refreshNavigationTerrainAfterCompletedRouteHypothesis = async () => true;
globalThis.scheduleQgisSpatialPolling = () => {};
globalThis.refreshCurrentDataView = () => {};
assert.equal(await startQgisSpatialWorkflow(QGIS_TERRAIN_ROUTE_WORKFLOW_ID), run);
assert.equal(state.qgisSpatialMessage, 'TRH 候選已就緒 · 地圖已載入對應 A/B 結果');
assert.equal(state.qgisSpatialBusy, false);
assert.equal(submitOptions.timeoutMs, QGIS_SPATIAL_WORKFLOW_TIMEOUT_MS);
console.log(JSON.stringify({completedCandidate:true}));
""")
    assert payload["completedCandidate"] is True


def test_endpoint_selection_and_worker_button_use_read_only_recheck() -> None:
    html = PAGE.read_text(encoding="utf-8")
    assert 'document.querySelector("[data-qgis-terrain-route-check-worker]")?.addEventListener("click"' in html
    selector = html.split("function setQgisTerrainRouteEndpointFromMap", 1)[1].split(
        "function resetQgisTerrainRouteDraft", 1,
    )[0]
    assert "qgisTerrainRouteEndpointsReady() && !qgisTerrainRouteBackendReady()" in selector
    assert "void refreshQgisTerrainRouteBackend();" in selector
    assert selector.index("rememberQgisTerrainRouteDraft();") < selector.index("refreshQgisTerrainRouteBackend();")


RUNTIME_FUNCTIONS = (*BACKEND_FUNCTIONS, "startQgisRuntime", "refreshQgisTerrainRouteBackend")


def test_explicit_start_is_coalesced_preserves_inputs_and_rechecks_real_health() -> None:
    payload = _run(RUNTIME_FUNCTIONS, """
const preserved = JSON.stringify([state.qgisTerrainRouteEndpoints,state.terrainRouteGuidance,
  state.terrainRouteGuidanceManualAnchors,state.terrainRouteGuidanceSelectedFeatures]);
let release;
const pending = new Promise(resolve => { release = resolve; });
const posts = [];
globalThis.postJson = async (path,body,options) => {
  posts.push({path,body,options}); await pending;
  return {...runtime,status:'ready',code:'READY'};
};
const first = startQgisRuntime();
const second = startQgisRuntime();
assert.equal(first, second);
assert.equal(state.qgisRuntimeStarting, true);
assert.equal(generate.disabled, true);
assert.equal(r4.disabled, true);
assert.equal(start.disabled, true);
assert.equal(check.disabled, true);
assert.equal(document.querySelector('[data-qgis-terrain-route-select]').disabled, false);
await refreshQgisTerrainRouteBackend();
assert.equal(calls.length, 0);
release();
await first;
assert.equal(posts.length, 1);
assert.ok(posts[0].path.endsWith('/runtime/ensure-ready'));
assert.deepEqual(posts[0].body, {action:'ensure_ready'});
assert.equal(calls.length, 3);
assert.equal(generate.disabled, false);
assert.equal(r4.disabled, true);
assert.equal(state.qgisRuntimeStarting, false);
assert.equal(start.disabled, true);
assert.match(state.qgisRuntimeMessage, /尚未提交 TRH/);
assert.equal(preserved, JSON.stringify([state.qgisTerrainRouteEndpoints,state.terrainRouteGuidance,
  state.terrainRouteGuidanceManualAnchors,state.terrainRouteGuidanceSelectedFeatures]));
responses.status = {...healthy,reachable:false};
await refreshQgisTerrainRouteBackend();
assert.equal(generate.disabled, true);
assert.equal(start.disabled, false);
assert.equal(document.querySelector('[data-qgis-terrain-route-worker-chip]').textContent, 'WORKER UNAVAILABLE');
assert.ok(!state.qgisRuntimeMessage.includes('Worker 已就緒'));
console.log(JSON.stringify({explicitOnly:true}));
""")
    assert payload["explicitOnly"] is True


@pytest.mark.parametrize("outcome", ("claimed_ready", "unavailable", "network_error"))
def test_startup_receipt_or_network_failure_cannot_unlock_without_handshake(outcome: str) -> None:
    payload = _run(RUNTIME_FUNCTIONS, f"""
responses = {{runtime,capabilities,status:{{...healthy,reachable:false}}}};
globalThis.postJson = async () => {{
  if ('{outcome}' === 'network_error') throw new Error('timeout');
  return {{...runtime,status:'{outcome}' === 'claimed_ready' ? 'ready' : 'unavailable',
    code:'{outcome}' === 'claimed_ready' ? 'READY' : 'START_TIMEOUT'}};
}};
await startQgisRuntime();
assert.equal(generate.disabled, true);
assert.equal(r4.disabled, true);
assert.equal(state.qgisRuntimeStarting, false);
assert.equal(check.disabled, false);
assert.equal(start.disabled, false);
assert.ok(state.qgisRuntimeMessage);
console.log(JSON.stringify({{failClosed:true}}));
""")
    assert payload["failClosed"] is True


@pytest.mark.parametrize("patch", (
    "state.qgisRuntimeControl = null", "state.qgisRuntimeControl = {can_start:false}",
    "state.qgisSpatialStatus = healthy", "state.qgisSpatialStatusRefreshing = true",
    "state.qgisSpatialWorkflow = {state:'running'}",
))
def test_start_never_runs_implicitly_or_bypasses_unmanaged_busy_gate(patch: str) -> None:
    payload = _run(RUNTIME_FUNCTIONS, f"""
let posted = 0;
globalThis.postJson = async () => {{ posted++; throw new Error('forbidden'); }};
{patch};
await startQgisRuntime();
assert.equal(posted, 0);
console.log(JSON.stringify({{guarded:true}}));
""")
    assert payload["guarded"] is True


@pytest.mark.parametrize("change", ("currentProject = 'project-b'", "currentApi = 'http://new-host'"))
def test_start_ignores_late_receipt_after_workspace_or_server_change(change: str) -> None:
    payload = _run(RUNTIME_FUNCTIONS, f"""
let release;
globalThis.postJson = () => new Promise(resolve => {{release = resolve;}});
const promise = startQgisRuntime();
{change};
responses = {{runtime,capabilities,status:{{...healthy,reachable:false}}}};
release({{...runtime,status:'ready',code:'READY'}});
await promise;
assert.equal(state.qgisRuntimeControl.code, 'IDLE');
assert.equal(state.qgisRuntimeMessage, '');
assert.equal(generate.disabled, true);
assert.equal(state.qgisRuntimeStarting, false);
console.log(JSON.stringify({{staleRejected:true}}));
""")
    assert payload["staleRejected"] is True
