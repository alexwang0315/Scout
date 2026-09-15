"""Regression of actual Debug startup functions; fixtures do not qualify live maps."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase-3-5-runtime-debug.html"
SCRIPT = r"""const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const file=process.argv[1];
let html=fs.readFileSync(file,'utf8');
/* MUTATION_POINT */
function fn(name){const m=html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }','m'));assert.ok(m,name);return m[0];}
const functions=['loadOsmPbfVectorLayer','loadCwaWeatherImagery','loadDebugSurface','initializeDebugMapRenderer','activateDebugSvgFallback'].map(fn).join('\n');
const match=html.match(/    if \(DIAGNOSTIC_MAP_PROBE\) \{\n      \(async \(\) => \{([\s\S]*?)\n      \}\)\(\);/);assert.ok(match);
const source=functions+'\nasync function runDiagnosticStartup(){'+match[1]+'\n}';
const projection={project_id:'contract-fixture',map_layers:[{layer_id:'osm',local_osm_render_geojson_ref:'fixture.geojson'}]};
const osm={type:'FeatureCollection',features:[{type:'Feature',properties:{source:'opaque-osm-fixture'},geometry:null}]};
const imagery={status:'fixture-available',sourceFrameIds:['opaque-cwa-fixture']};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject};}
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(renderer){
 const gates=Object.fromEntries(['projection','cwa','osm','palette'].map(k=>[k,deferred()]));
 const renders=[],activations=[],requests=[],state={projection:null,mapLibreDisposed:false,osmPbfVectorStatus:'not_loaded',mapLibreRenderer:null};
 const context={Promise,PRETRIP_PROJECT_ID:projection.project_id,PRETRIP_DEBUG_PROJECTION_PATH:'/debug-projection',DEBUG_MAP_RENDERER_PREFERENCE:renderer,debugPageState:state,cwaImageryUi:{manifest:null},runtimeMapRendererShell:{},runtimeMapLibre:{hidden:true},runtimeMap:{hidden:false},
  document:{getElementById:()=>({innerHTML:''}),querySelectorAll:()=>[]},
  apiBase:()=>'',localOsmPbfVectorUrl:p=>p?.map_layers.some(l=>l.layer_id==='osm'&&l.local_osm_render_geojson_ref)?'/osm-pbf-vector.geojson':'',
  fetchJson:async()=>gates.projection.promise,
  fetch:async url=>{const k=String(url).includes('weather-imagery')?'cwa':'osm';requests.push(k);const data=await gates[k].promise;return{ok:true,json:async()=>data};},
  syncCwaImageryControls(){},loadOsmCartoPalette:()=>gates.palette.promise,
  loadProjectedDebugEventPayload:async()=>({projection:await gates.projection.promise,payload:{events:[]}}),
  loadRuntimeDebugStatePayload:async()=>({}),loadRuntimeDebugMessagesPayload:async()=>({messages:[]}),
  loadHardwareReadinessContext:async()=>({}),loadMobileWearableIngressContext:async()=>({}),loadMonitoringCenter:async()=>({}),
  stateWithProjectedEvents:x=>x,renderEndpointPayloads(){},renderState(){},renderEvents(){},setText(){},escapeHtml:x=>x,renderLevels(){},
  debugMapLibreActive:()=>state.mapRenderer?.active==='maplibre',
  syncDebugMapLibreProjection:()=>{renders.push({kind:'maplibre-sync',osm:state.osmPbfVector,imagery:context.cwaImageryUi.manifest});},
  renderDebugEvidenceMap:()=>renders.push({kind:'svg',osm:state.osmPbfVector,imagery:context.cwaImageryUi.manifest}),
  disposeDebugMapEvidenceControls(){},
  setDebugMapRendererState:s=>{state.mapRenderer=s;return s;},
  activateDebugMapLibreRenderer:async()=>{activations.push({osm:state.osmPbfVector,imagery:context.cwaImageryUi.manifest});state.mapRenderer={active:'maplibre',state:'ready'};return state.mapRenderer;},
  debugMapLibreEnabled:()=>true,
  window:{ScoutMapLibreEvidence:{resolveRenderer:()=>({active:renderer,reason:renderer==='svg'?'forced_svg':'webgl_available'}),webglAvailable:()=>true,loadRenderer:async()=>({active:'maplibre',maplibregl:{}})}}
 };
 vm.createContext(context);vm.runInContext(source,context);return{context,gates,renders,activations,requests,state};
}
function perms(a){return a.length?a.flatMap((x,i)=>perms(a.filter((_,j)=>j!==i)).map(p=>[x,...p])):[[]];}
const results=[];
(async()=>{
 for(const entry of ['diagnostic','normal'])for(const renderer of ['svg','maplibre']){
  for(const order of perms(entry==='normal'?['cwa','osm','palette']:['cwa','osm'])){
   const f=fixture(renderer);let done=false;
   const pending=(entry==='normal'?f.context.loadDebugSurface():f.context.runDiagnosticStartup()).then(()=>{done=true;});
   await tick();assert.equal(f.renders.length,0);f.gates.projection.resolve(projection);await tick();
   for(let i=0;i<order.length;i++){
    f.gates[order[i]].resolve(order[i]==='cwa'?imagery:order[i]==='osm'?osm:{});
    await tick();
    if(i<order.length-1){assert.equal(done,false,entry+' initialized before complete dependencies');assert.equal(f.renders.length,0,entry+' redrew partial map');assert.equal(f.activations.length,0);}
   }
   await pending;assert.equal(done,true);
   assert.deepEqual(f.requests.sort(),['cwa','osm'],'Both real dependency paths must be awaited');
   assert.equal(f.renders.length,renderer==='svg'?1:0,entry+' must not build and discard intermediate SVG generations');
   assert.equal(f.activations.length,renderer==='maplibre'?1:0);
   const receipt=renderer==='svg'?f.renders[0]:f.activations[0];
   assert.equal(receipt.osm,osm,'Complete actual OSM body must reach render');
   assert.equal(receipt.imagery,imagery,'Complete actual CWA body must reach render');
   results.push({entry,renderer,order});
  }
 }
 // Default interactive OSM load must preserve an immediate redraw.
 const f=fixture('svg');f.state.projection=projection;
 const interactive=f.context.loadOsmPbfVectorLayer();f.gates.osm.resolve(osm);await interactive;
 assert.equal(f.renders.length,1);assert.equal(f.renders[0].osm,osm);
 // Rejected OSM and CWA keep existing unavailable states; they cannot be pending forever after rejection.
 for(const failed of ['osm','cwa']){
  const f=fixture('svg');const p=f.context.runDiagnosticStartup();f.gates.projection.resolve(projection);await tick();
  f.gates[failed].reject(new Error('recorded dependency rejection'));
  f.gates[failed==='osm'?'cwa':'osm'].resolve(failed==='osm'?imagery:osm);await p;
  assert.equal(f.renders.length,1);
  if(failed==='osm'){assert.match(f.state.osmPbfVectorStatus,/^failed:/);assert.equal(f.state.osmPbfVector,null);}
  else assert.equal(f.context.cwaImageryUi.manifest,null);
 }
 console.log(JSON.stringify({status:'SOURCE_BOUNDARY_REPLAY_PASS',source:file,responseOrders:results,interactiveRedraws:1,rejectedDependencies:2,scope:'actual loader/initializer functions with opaque unit fixtures; renderer activation/DOM stubbed; not real workspace or Diagnostic PASS'},null,2));
})().catch(e=>{console.error(e.stack);process.exitCode=1});

"""

@pytest.mark.parametrize("restore_duplicate_redraw", [False, True])
def test_debug_startup_keeps_complete_dependency_barrier_and_single_svg_commit(restore_duplicate_redraw):
    node = shutil.which("node")
    assert node, "Node is required for the actual-source Debug startup replay"
    script = SCRIPT
    if restore_duplicate_redraw:
        mutation = """
html = html.replaceAll('loadOsmPbfVectorLayer({redraw: false})', 'loadOsmPbfVectorLayer({redraw: true})')
  .replace('          await initializeDebugMapRenderer(debugPageState.projection);',
    '          renderDebugEvidenceMap(debugPageState.projection);\\n          await initializeDebugMapRenderer(debugPageState.projection);');
"""
        script = script.replace("/* MUTATION_POINT */", mutation)
    result = subprocess.run([node, "-e", script, str(PAGE)], text=True, capture_output=True, cwd=ROOT, timeout=30)
    if restore_duplicate_redraw:
        assert result.returncode != 0
        assert "must not build and discard intermediate SVG generations" in result.stderr
        assert "3 !== 1" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert len(receipt["responseOrders"]) == 16
        assert receipt["interactiveRedraws"] == 1 and receipt["rejectedDependencies"] == 2
