"""Exercise actual Debug split/sort/toggle functions with mixed geometry."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_split_preserves_identity_labels_toggle_and_background_detection():
    page = (ROOT / 'docs/admin/phase-3-5-runtime-debug.html').read_text()
    names = ['mapLayerRank', 'splitEnvironmentBackgrounds', 'orderMapLayerGroups', 'updateLayers', 'layerInputChecked']
    functions = '\n'.join(re.search(rf'(?ms)^    function {name}\(.*?^    }}', page).group() for name in names)
    source = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><svg id="runtimeMap"></svg></body>');
global.window=dom.window;global.document=dom.window.document;
require('./docs/admin/scout-maplibre-evidence.js');
const runtimeMap=document.querySelector('svg');
const ids=['soil-moisture','antecedent-rain','cwa-qpf','cwa-weather'];
const MAP_LAYER_RANKS={terrain:20,route:44,segments:50,...Object.fromEntries(ids.map((id,i)=>[id,57+i]))};
const svgEl=(tag,attrs)=>{const n=document.createElementNS(runtimeMap.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;};
const selectorValue=x=>x;
const debugMapLibreActive=()=>false;
const syncRasterBasemapLayers=()=>{},syncMapMarkerScale=()=>{},updatePointLabels=()=>{},highlightMapForEvent=()=>{},selectedMapEvent=()=>null,syncLayerPresetButtons=()=>{};
const RASTER_BASEMAP_LAYER_IDS=new Set();
runtimeMap.innerHTML='<g data-layer-group="route"><path class="route-line" d="M0 0 L10 10"/></g><g data-layer-group="segments"><path class="segment-overlay" d="M0 0 L10 10"/></g>';
for(const id of ids){
 document.body.insertAdjacentHTML('beforeend',`<input type="checkbox" data-layer="${id}">`);
 runtimeMap.insertAdjacentHTML('beforeend',`<g data-layer-group="${id}"><rect class="environment-extent ${id}" width="10" height="10"/><circle class="${id}-point" r="5"/><text>evidence label</text>${id==='cwa-weather'?'<image href="tile.png" width="10" height="10"/>':''}</g>`);
}
const points=ids.map(id=>runtimeMap.querySelector(`[data-layer-group="${id}"] circle`));
'''+functions+r'''
orderMapLayerGroups();orderMapLayerGroups();
assert.equal(runtimeMap.querySelectorAll('[data-layer-background]').length,4);
for(const [i,id] of ids.entries()){
 const group=runtimeMap.querySelector(`[data-layer-group="${id}"]`),bg=runtimeMap.querySelector(`[data-layer-background="${id}"]`);
 assert.equal(runtimeMap.querySelectorAll(`[data-layer-group="${id}"]`).length,1);
 assert.equal(group.querySelector('circle'),points[i]);assert(group.querySelector('text'));
 assert.equal(group.querySelectorAll('image,rect').length,0);
 assert.equal(bg.querySelectorAll('rect').length,1);
 assert([...runtimeMap.children].indexOf(bg)<[...runtimeMap.children].indexOf(runtimeMap.querySelector('[data-layer-group="route"]')));
 const input=document.querySelector(`[data-layer="${id}"]`);
 for(const checked of [true,false,true]){input.checked=checked;updateLayers();assert.equal(group.dataset.layerHidden,String(!checked));assert.equal(bg.dataset.layerHidden,String(!checked));}
}
let result=window.ScoutMapLibreEvidence.inspectSvgLayerOrder(runtimeMap);
assert.equal(result.violations.length,0,JSON.stringify(result));
runtimeMap.appendChild(runtimeMap.querySelector('[data-layer-background="cwa-weather"]'));
result=window.ScoutMapLibreEvidence.inspectSvgLayerOrder(runtimeMap);
assert(result.violations.some(v=>v.code==='background_over_route'));
console.log('split, identity, idempotence, toggle, order and negative regression passed');
'''
    result = subprocess.run(['node', '-e', source], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
