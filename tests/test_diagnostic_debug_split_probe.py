"""DASH044 runs actual Debug handlers on isolated DOM and retains negative evidence."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_debug_split_diagnostic_operates_handlers_and_keeps_failures():
    dashboard = (ROOT / 'docs/admin/scout-dashboard-v0.1.html').read_text()
    debug = (ROOT / 'docs/admin/phase-3-5-runtime-debug.html').read_text()
    names = [
        'mapLayerRank', 'splitEnvironmentBackgrounds', 'orderMapLayerGroups',
        'withDebugMapDomUpdate', 'updateLayers', 'updateLayersDom', 'layerInputChecked',
    ]
    functions = '\n'.join(re.search(rf'(?ms)^    function {name}\(.*?^    }}', debug).group() for name in names)
    probe = re.search(r'(?ms)^    async function diagnosticProbeDebugSplitControls\(.*?^    }', dashboard).group()
    script = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><svg id="runtimeMap"></svg></body>');
global.window=dom.window;global.document=dom.window.document;
const runtimeMap=document.querySelector('svg');
const debugPageState={};
const ids=['soil-moisture','antecedent-rain','cwa-qpf','cwa-weather'];
const MAP_LAYER_RANKS={route:44,segments:50,...Object.fromEntries(ids.map((id,i)=>[id,57+i]))};
const svgEl=(tag,attrs)=>{const n=document.createElementNS(runtimeMap.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;};
const selectorValue=x=>x,debugMapLibreActive=()=>false;
const syncRasterBasemapLayers=()=>{},syncMapMarkerScale=()=>{},updatePointLabels=()=>{},highlightMapForEvent=()=>{},selectedMapEvent=()=>null,syncLayerPresetButtons=()=>{};
const RASTER_BASEMAP_LAYER_IDS=new Set();
const diagnosticMapOrderGap=(surface,variant,detail)=>({...surface,variant,status:'warning',violations:[],gaps:[detail]});
runtimeMap.innerHTML='<g data-layer-group="route"><path/></g><g data-layer-group="segments"><path/></g>';
for(const id of ids){
 document.body.insertAdjacentHTML('beforeend',`<input type="checkbox" checked data-layer="${id}">`);
 runtimeMap.insertAdjacentHTML('beforeend',`<g data-layer-group="${id}"><rect class="environment-extent"/><circle/><text>Label</text>${id==='cwa-weather'?'<image href="tile.png"/>':''}</g>`);
}
''' + functions + '\n' + probe + r'''
(async()=>{
orderMapLayerGroups();updateLayers();
for(const input of document.querySelectorAll('input'))input.addEventListener('change',updateLayers);
const frame={contentDocument:document,contentWindow:window}, surface={id:'debug-map',label:'Debug'};
const collect=variant=>({variant,status:'passed',violations:[],gaps:[]});
const run=()=>diagnosticProbeDebugSplitControls(frame,surface,collect);
let result=await run();
assert.equal(result.length,8);assert.equal(result.filter(r=>r.status==='passed').length,6);
assert.equal(result.filter(r=>r.status==='failed').length,0);
assert(result[7].gaps.some(x=>x.includes('影格更新')));
assert([...document.querySelectorAll('input')].every(x=>x.checked));
// Broken linkage must fail, not downgrade to a data gap.
const input=document.querySelector('input[data-layer="soil-moisture"]');
const broken=()=>runtimeMap.querySelector('[data-layer-background="soil-moisture"]').dataset.layerHidden='false';
input.addEventListener('change',broken);
result=await run();assert(result[0].violations.some(v=>v.code==='split_visibility_mismatch'));
input.removeEventListener('change',broken);
// Known background above route fails even in the off state.
runtimeMap.appendChild(runtimeMap.querySelector('[data-layer-background="cwa-qpf"]'));
result=await run();assert(result[4].violations.some(v=>v.code==='split_background_over_route'));
orderMapLayerGroups();
// Missing loaded imagery cannot silently count as verified raster linkage.
runtimeMap.querySelector('image').remove();
result=await run();assert.equal(result[7].status,'warning');assert(result[7].gaps.some(x=>x.includes('無 CWA raster')));
// Lost point/label evidence during an actual toggle remains a red failure.
input.addEventListener('change',()=>runtimeMap.querySelector('[data-layer-group="soil-moisture"] circle')?.remove(),{once:true});
result=await run();assert(result[0].violations.some(v=>v.code==='split_evidence_lost'));
console.log('8 real handler toggle states, restoration, negative linkage/order/loss and raster gaps verified');
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
