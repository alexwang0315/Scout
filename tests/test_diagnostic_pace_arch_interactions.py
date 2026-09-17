"""Replay production Pace/Architecture controls and renderers without live DOM effects."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_production_controls_synchronize_and_restore_state():
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const dom=new JSDOM('<body><div id="live-sentinel">unchanged</div></body>',{url:'http://localhost/admin/dashboard?diagnosticMapProbe=1',runScripts:'outside-only'});
dom.window.matchMedia=()=>({matches:false});dom.window.structuredClone=structuredClone;
dom.window.fetch=()=>{throw Error('Unexpected network effect')};
const source=[...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('const DIAGNOSTIC_MAP_PROBE'));
dom.window.eval(source+`\nwindow.exercise=(project)=>{
 const before=JSON.stringify(state);
 const force=SIX_FORCES.find(f=>f.route==='outdoor-pace-fit');
 const pace=diagnosticPaceInteractions(project,force);
 const architecture=diagnosticArchitectureInteractions(project);
 if(JSON.stringify(state)!==before)throw Error('Diagnostic leaked live state');
 return {pace,architecture};
};
window.exerciseBrokenPace=(project)=>{
 const before=JSON.stringify(state),original=bindPaceFitControls;
 try {bindPaceFitControls=()=>{};diagnosticPaceInteractions(project,SIX_FORCES.find(f=>f.route==='outdoor-pace-fit'));}
 finally {bindPaceFitControls=original;if(JSON.stringify(state)!==before)throw Error('Failed diagnostic leaked state');}
};`);
const fixture={route:{distance_m:2000,display_geometry:{coordinates:[{lon:121,lat:24},{lon:121.01,lat:24.01}]}},project_id:'fixture',checkpoints:[{candidate_id:'a',lat:24,lon:121,label:'A'},{candidate_id:'b',lat:24.01,lon:121.01,label:'B'}],route_architecture_intelligence:{status:'available',architecture_summary:{route_distance_m:2000},historical_time_windows:{checkpoints:[{node_id:'win1',label:'Window',route_distance_m:0,remaining_minutes:60,remaining_ratio:0.5}]},segment_demand_vectors:[{route_bin_id:'bin1',start_distance_m:0,end_distance_m:2000}],boundary:{runtime_safety_truth:false}}};
const result=dom.window.exercise(fixture);
assert.equal(result.pace.complete,true,result.pace.detail);
assert.equal(result.architecture.complete,true,result.architecture.detail);
assert.throws(()=>dom.window.exerciseBrokenPace(fixture),/selection handler did not update/);
const missing=dom.window.exercise({project_id:'empty',route_architecture_intelligence:{segment_demand_vectors:[]}});
assert.equal(missing.pace.complete,false);
assert.equal(missing.architecture.complete,false);
assert.equal(dom.window.document.body.textContent,'unchanged');
dom.window.close();
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=240)
    assert result.returncode == 0, result.stderr
