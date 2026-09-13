"""D028 uses actual Navigation state markup; ready cannot borrow loading's gate."""

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run(options):
    program = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const {window}=new JSDOM('<body/>',{url:'http://localhost/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport&diagnosticMapProbe=1',runScripts:'outside-only'});
window.matchMedia=()=>({matches:false});window.fetch=()=>{throw Error('Unexpected network request')};
const source=[...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)].map(item=>item[1]).find(script=>script.includes('const DIAGNOSTIC_MAP_PROBE'));
window.eval(source+String.raw`
window.inspectLoadingPolicy=options=>{
  const original={...state},host=document.createElement('div');
  const domain=options.domain||'observed',ready=options.ready===true;
  const bounds={west:121.04,east:121.07,south:23.46,north:23.48};
  const points=options.withData?[{lat:23.463,lon:121.044,distance_m:0},{lat:23.474,lon:121.063,distance_m:1500}]:[];
  const mesh={status:'visualization_mesh',minimum_elevation_m:100,maximum_elevation_m:140,
    vertices:[{u:0,v:0,elevation_m:100,supported:true},{u:1,v:0,elevation_m:120,supported:true},{u:0,v:1,elevation_m:140,supported:true}],
    triangles:options.withData?[[0,1,2]]:[]};
  const snapshot={status:options.status||(ready?'ready':'loading'),orientation_basemap:{status:'ready',bounds_wgs84:bounds},
    terrain_surface:{bbox_wgs84:bounds,cell_resolution_m:20},route_samples:{points},terrain_mesh:mesh};
  document.body.append(host);
  try {
    state.navigationTerrainEvidenceDomain=domain;state.navigationTerrainLens='structure';
    state.dataScopeErrors=options.failure==='scope-error'?{navigation_terrain:'Projection unavailable'}:{};
    host.innerHTML=ready?renderNavigationWorkspaceMap(snapshot,null,null,null,null):renderNavigationWorkspaceLoading(snapshot);
    diagnosticSetMapInteractionCacheOnly(host);
    const viewport=host.querySelector('[data-dashboard-map-viewport]');
    const layer=viewport.querySelector('[data-dashboard-rudy-tile-layer]');
    // Generate the same cache-only tile URLs as the production controller.
    // Network decoding/native completeness is intentionally outside D028.
    if(layer)layer.innerHTML=navigationRudyTileImages(bounds,bounds,navigationRudyBaseZoom(bounds),1000,392,'navigation-map',{cacheOnly:true});
    const failure=options.failure;
    if(failure==='hidden-status')viewport.querySelector('.navigation-workspace-map-status').hidden=true;
    if(failure==='missing-state')viewport.removeAttribute('data-navigation-evidence-state');
    if(failure==='wrong-title')viewport.querySelector('.navigation-workspace-map-status strong').textContent='READY';
    if(failure==='missing-claim')viewport.querySelector('.navigation-workspace-scale').remove();
    if(failure==='fake-ready'){
      viewport.dataset.navigationEvidenceState='ready';viewport.dataset.navigationWorkspaceMap='ready';
      viewport.querySelector('.navigation-workspace-map-status strong').textContent='READY';
    }
    if(failure==='placeholder-vectors')viewport.querySelector('svg').insertAdjacentHTML('beforeend',
      '<defs><path d="M0 0 L5 5"/></defs><path d="M0 0 H1000"/><g style="display:none" data-dashboard-map-hint-source="fixture"><circle r="4"/></g><path data-navigation-route-path="true" d="M0 0"/>');
    if(failure==='missing-tiles')viewport.querySelectorAll('image').forEach(image=>image.remove());
    if(failure==='native-url'||failure==='wrong-workspace'){
      const image=viewport.querySelector('image'),url=new URL(image.getAttribute('href'),location.href);
      if(failure==='native-url'){url.searchParams.delete('cache_only');url.searchParams.set('native','1')}
      else url.pathname=url.pathname.replace(encodeURIComponent(projectId()),'another-workspace');
      image.setAttribute('href',url.href);
    }
    const adapter=diagnosticSharedMapInteractionAdapter(viewport),policy=adapter.policy();
    const variant=domain+':'+(ready?'fallback':'loading')+':structure';
    const surface=diagnosticMapInteractionSurfaceCases().find(item=>item.id==='navigation-map'&&item.renderer==='svg'&&item.variant===variant);
    try {return {status:'passed',evidence:diagnosticMapInteractionRenderPolicy(surface,adapter),vectorCount:policy.vectorCount}}
    catch(error){return {status:error.diagnosticStatus==='warning'?'warning':'failed',detail:error.message,evidence:error.diagnosticEvidence,vectorCount:policy.vectorCount}}
  } finally {host.remove();for(const key of Object.keys(state))if(!(key in original))delete state[key];Object.assign(state,original)}
};
window.inspectCanonicalPolicy=options=>{
  const host=document.createElement('div'),debug=options.canonical==='debug-map';
  const id=debug?'runtimeMap':'map';
  host.innerHTML='<svg id="'+id+'"><defs><path d="M0 0 L5 5"/></defs><g style="display:none"><circle r="4"/></g>'
    +(options.withData?'<path d="M0 0 L5 5"/>':'<path d=""/>')
    +'<g data-layer-group="rudy-twmap"><image data-raster-tile="12/1/1" href="/admin/tiles/imagery/'+encodeURIComponent(projectId())+'/rudy-twmap/12/1/1.png?source_id=happyman_rudy_twmap&amp;exact=1&amp;cache_only=1"/></g></svg>';
  document.body.append(host);
  try {
    const frame={contentDocument:document};
    const adapter=debug?diagnosticDebugMapInteractionAdapter(frame,{},'svg'):diagnosticPretripMapInteractionAdapter(frame,{},'svg');
    const surface={id:options.canonical,renderer:'svg',variant:'default'};
    try{return {status:'passed',evidence:diagnosticMapInteractionRenderPolicy(surface,adapter)}}
    catch(error){return {status:error.diagnosticStatus==='warning'?'warning':'failed',detail:error.message,evidence:error.diagnosticEvidence}}
  } finally {host.remove()}
};
`);
const options=OPTIONS;
try {console.log(JSON.stringify(options.canonical?window.inspectCanonicalPolicy(options):window.inspectLoadingPolicy(options)))} finally {window.close()}
'''.replace("OPTIONS", json.dumps(options))
    result = subprocess.run(["node", "-e", program], cwd=ROOT, text=True, capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("domain", ["observed", "terrain", "prior"])
@pytest.mark.parametrize("status", ["loading", "preparing"])
def test_actual_loading_shell_with_zero_vectors_verifies_state_without_claiming_ready(domain, status):
    result = _run({"domain": domain, "status": status})
    assert result["status"] == "passed", result
    assert result["vectorCount"] == 0
    evidence = result["evidence"]
    assert evidence["mapState"] == status
    assert evidence["vectorEvidenceRequired"] is False
    assert evidence["readyVectorEvidenceVerified"] is False
    assert evidence["navigationState"]["statusVisible"] is True
    assert evidence["navigationState"]["noVectorsClaim"] is True
    assert evidence["inspectedRudyTileUrls"] > 0


@pytest.mark.parametrize("domain", ["observed", "terrain", "prior"])
def test_actual_ready_svg_requires_prepared_vectors_and_ignores_grid_and_definitions(domain):
    good = _run({"domain": domain, "ready": True, "withData": True})
    assert good["status"] == "passed", good
    assert good["evidence"]["readyVectorEvidenceVerified"] is True
    assert good["vectorCount"] > 0
    empty = _run({"domain": domain, "ready": True, "failure": "placeholder-vectors"})
    assert empty["status"] == "failed", empty
    assert empty["vectorCount"] == 0
    assert "vector evidence is absent" in empty["detail"]
    assert empty["evidence"]["mapState"] == "ready"
    assert empty["evidence"]["vectorEvidenceRequired"] is True
    assert empty["evidence"]["readyVectorEvidenceVerified"] is False


@pytest.mark.parametrize("failure", ["hidden-status", "missing-state", "wrong-title", "missing-claim", "fake-ready", "scope-error"])
def test_loading_variant_name_cannot_substitute_missing_or_contradictory_ui_state(failure):
    result = _run({"failure": failure})
    assert result["status"] == "failed", result
    assert "does not truthfully expose" in result["detail"]
    assert result["evidence"]["readyVectorEvidenceVerified"] is False


@pytest.mark.parametrize("status", ["failed", "not_prepared", "stale"])
def test_loading_case_retains_failed_and_unprepared_states_as_non_pass(status):
    result = _run({"status": status})
    assert result["status"] == "failed", result
    assert result["evidence"]["mapState"] == ("failed" if status == "failed" else "not-prepared")


@pytest.mark.parametrize(("failure", "status"), [("missing-tiles", "warning"), ("native-url", "failed"), ("wrong-workspace", "failed")])
def test_loading_vector_exception_preserves_tile_availability_and_source_boundaries(failure, status):
    result = _run({"failure": failure})
    assert result["status"] == status, result
    assert result["evidence"]["mapState"] == "loading"
    assert result["evidence"]["readyVectorEvidenceVerified"] is False


@pytest.mark.parametrize("canonical", ["map", "debug-map"])
def test_canonical_svg_policy_cannot_count_hidden_or_definition_shapes_as_data(canonical):
    present = _run({"canonical": canonical, "withData": True})
    assert present["status"] == "passed", present
    assert present["evidence"]["vectorCount"] == 1
    empty = _run({"canonical": canonical})
    assert empty["status"] == "failed", empty
    assert "vector evidence is absent" in empty["detail"]
    assert empty["evidence"]["vectorCount"] == 0
