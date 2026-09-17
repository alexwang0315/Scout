"""Replay real loader functions with controlled response order, without network."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("replay_duplicate_redraw", [False, True])
def test_initial_enhancements_commit_one_complete_redraw(replay_duplicate_redraw: bool) -> None:
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('docs/admin/phase4-pretrip-planning.html', 'utf8');
const names = ['reloadProjectView', 'loadOsmPbfVectorLayer', 'loadCwaWeatherImageryIfEnabled'];
const source = names.map(name => {
  const m = html.match(new RegExp('^    async function '+name+'\\([\\s\\S]*?^    }', 'm'));
  assert.ok(m, name); return m[0];
}).join('\n');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((a,b) => {resolve=a; reject=b});
  return {promise, resolve, reject};
}
function fixture() {
  const pending = Object.fromEntries(['rain','imagery','palette','osm','weather'].map(k=>[k,deferred()]));
  const renders = [], phases = [], state = {}, selected = {checked:true};
  const context = {
    state, PROJECT_ID:'real-project', Promise, console,
    apiBase: () => '', localOsmPbfVectorUrl: () => '/osm',
    publishPretripProjectBridge: (phase,detail) => phases.push({phase,detail}),
    renderMap: view => renders.push({view:{...view},osm:state.osmPbfVector,
      weather:state.weatherOverlay,imagery:state.imagery,palette:state.palette}),
    renderProjectView: view => context.renderMap(view),
    cwaWeatherLayerInput: () => selected,
    clearCwaWeatherImagery: () => {state.imagery=null},
    renderCurrentCwaImagerySurface: () => context.renderMap(state.view),
    loadCwaWeatherImagery: async () => {state.imagery=await pending.imagery.promise; return state.imagery},
    loadCwaRainfallGridOverlay: async view => ({...view,rain:await pending.rain.promise}),
    loadOsmCartoPalette: async () => {state.palette=await pending.palette.promise},
    fetch: async url => {
      if (url.endsWith('?compact=1')) return {ok:true,json:async()=>({id:'real-project',base:true})};
      const key = url==='/osm' ? 'osm' : url.endsWith('/weather-overlay') ? 'weather' : null;
      assert.ok(key, 'Unexpected fetch '+url);
      const data=await pending[key].promise;
      return {ok:true,json:async()=>data};
    },
  };
  vm.createContext(context); vm.runInContext(source, context);
  return {context,pending,renders,phases,state,selected};
}
function permutations(a) {return a.length ? a.flatMap((x,i)=>permutations(a.filter((_,j)=>j!==i)).map(p=>[x,...p])) : [[]]}
(async () => {
  let checked=0;
  for (const order of permutations(['rain','imagery','palette','osm','weather'])) {
    const f=fixture(); let done=false;
    const load=f.context.reloadProjectView().then(()=>{done=true});
    await tick(); assert.equal(f.renders.length,1,'Base map must remain visible');
    for (let i=0;i<order.length;i++) {
      f.pending[order[i]].resolve({source:order[i]}); await tick();
      if (i<order.length-1) {
        assert.equal(done,false,'No early ready while an enhancement is pending');
        assert.equal(f.renders.length,1,'Intermediate response rebuilt the full map');
      }
    }
    await load;
    assert.equal(f.renders.length,2,'Exactly base plus complete enhancement render');
    const final=f.renders[1];
    for (const k of ['osm','weather','imagery','palette']) assert.equal(final[k].source,k);
    assert.equal(final.view.rain.source,'rain');
    assert.equal(f.phases.at(-1).phase,'enhanced_ready');
    checked++;
  }
  // A rejected endpoint still completes the barrier and preserves degradation.
  for (const failed of ['rain','imagery','palette','weather']) {
    const f=fixture(); const load=f.context.reloadProjectView(); await tick();
    for (const [key,d] of Object.entries(f.pending)) {
      if (key===failed) d.reject(new Error('Observed endpoint failure'));
      else d.resolve({source:key});
    }
    await load;
    assert.equal(f.renders.length,2);
    assert.equal(f.phases.at(-1).phase,'degraded');
  }
  // Standalone layer operations keep their original immediate redraw behavior.
  const f=fixture(); f.state.view={id:'real-project'};
  const osm=f.context.loadOsmPbfVectorLayer(f.state.view);
  f.pending.osm.resolve({source:'osm'}); await osm; assert.equal(f.renders.length,1);
  const imagery=f.context.loadCwaWeatherImageryIfEnabled('real-project');
  f.pending.imagery.resolve({source:'imagery'}); await imagery; assert.equal(f.renders.length,2);
  f.selected.checked=false;
  await f.context.loadCwaWeatherImageryIfEnabled('real-project');
  assert.equal(f.renders.length,3); assert.equal(f.state.imagery,null);
  await f.context.loadCwaWeatherImageryIfEnabled('real-project',{redraw:false});
  assert.equal(f.renders.length,3);
  console.log(JSON.stringify({responseOrders:checked,rejectedEndpoints:4,interactiveRedraws:3}));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    node = shutil.which("node")
    assert node, "Node is required for the shipped-loader replay"
    if replay_duplicate_redraw:
        script = script.replace("const source =", "let source =").replace(
            "const tick =",
            "source = source.replaceAll('{redraw: false}', '{redraw: true}');\nconst tick =",
        )
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if replay_duplicate_redraw:
        assert result.returncode != 0
        assert "Intermediate response rebuilt the full map" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert '"responseOrders":120' in result.stdout
