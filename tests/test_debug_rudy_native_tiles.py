"""Executable replay of Debug's native Rudy tile transport and SVG swap boundary."""
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase-3-5-runtime-debug.html"


def functions(*names):
    source = PAGE.read_text()
    result = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source)
        assert match, name
        result.append(match.group())
    return "\n".join(result)


def node(source):
    result = subprocess.run(
        ["node"], input="const assert=require('node:assert/strict');\n" + source,
        text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_debug_inline_scripts_parse():
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", PAGE.read_text(), re.S)
    node("const vm=require('node:vm');\n" + "\n".join(
        f"new vm.Script({json.dumps(script)});" for script in scripts if script.strip()
    ))


def test_both_renderers_use_project_native_exact_proxy_and_bounded_probe_retry():
    rudy = re.search(r'^      (\{layerId: "rudy-twmap".*\}),$', PAGE.read_text(), re.M).group(1)
    node(functions("debugRudyTileTemplate", "rasterTileTemplate", "wmtsTileUrl",
                   "replaceTilePlaceholders", "debugMapLibreRasterLayers") + r'''
let DIAGNOSTIC_MAP_PROBE=false;
const location={origin:'http://127.0.0.1:9099',protocol:'http:'};
const apiBase=()=> 'http://old-remote:19111';
const PRETRIP_PROJECT_ID='dongqing_batongguan_historic_trail_newImport';
const debugPageState={rudyRemoteRefreshEnabled:true,rudyForceRefresh:false,rudyRefreshNonce:0};
const OSM_MIN_ZOOM=8, OSM_MAX_ZOOM=20, OSM_ATTRIBUTION='OSM';
const definition=''' + rudy + r''';
const rasterSourceDefinitionFor=()=>definition;
const rasterLayerFor=()=>({raster_tile_max_zoom:14,raster_tile_url_template:'https://old-wmts/{z}/{x}/{y}'});
const layerInputChecked=()=>true, debugMapLibreNetworkScope=()=> 'same_origin';
const debugMapLibreTerrainImageLayers=()=>[];
const template=rasterTileTemplate({},'rudy-twmap');
assert.equal(debugMapLibreRasterLayers({})[0].tiles[0],template);
assert.equal(debugMapLibreRasterLayers({})[0].maxzoom,20);
const url=new URL(wmtsTileUrl(definition,20,876543,432100));
assert.equal(url.origin,location.origin);
assert.equal(url.pathname,`/admin/tiles/imagery/${PRETRIP_PROJECT_ID}/rudy-twmap/20/876543/432100.png`);
assert.equal(url.searchParams.get('source_id'),'happyman_rudy_twmap');
assert.equal(url.searchParams.get('native'),'1');
assert.equal(url.searchParams.get('exact'),'1');
assert.equal(url.searchParams.has('refresh'),false);
debugPageState.rudyRemoteRefreshEnabled=false;
let query=new URL(debugRudyTileTemplate()).searchParams;
assert.equal(query.get('cache_only'),'1');
assert.equal(query.has('native'),false);
debugPageState.rudyRemoteRefreshEnabled=true;
debugPageState.rudyForceRefresh=true;
debugPageState.rudyRefreshNonce=2;
query=new URL(debugRudyTileTemplate()).searchParams;
assert.equal(query.get('refresh'),'1');
DIAGNOSTIC_MAP_PROBE=true;
query=new URL(debugRudyTileTemplate()).searchParams;
assert.equal(query.has('refresh'),false,'Diagnostic may fill missing native tiles but must not force-refresh cache');
assert.equal(query.get('native'),'1');
assert.equal(query.get('exact'),'1');
''')


def test_provider_zoom_ignores_preparation_ceiling_and_first_zoom_requests_detail():
    node(functions("parseZoomRange", "rasterZoomRangeFor", "boundsForProjection",
                   "debugRudyWorldPixelScale", "debugMapInteractionMaxZoom", "chooseRasterZoom",
                   "debugRudyViewportBounds", "mapViewportBox", "tileRangeForZoom", "tileCountForZoom",
                   "lonToTileX", "latToTileY") + r'''
const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
const MAP_WIDTH=1000, MAP_HEIGHT=720, MAP_VISUAL_PADDING=56, MAP_MAX_ZOOM=12000;
const OSM_MIN_ZOOM=8, OSM_MAX_ZOOM=20, OSM_TARGET_ZOOM=17;
const RASTER_MAX_TILES=64,RUDY_TWMAP_MAX_TILES=160;
const layerInputChecked=()=>true;
const rasterLayerFor=()=>({raster_tile_min_zoom:10,raster_tile_max_zoom:14});
const rasterSourceDefinitionFor=id=>({sourceId:id==='rudy-twmap'?'happyman_rudy_twmap':'other',minZoom:5,maxZoom:20});
const runtimeMap={getBoundingClientRect:()=>({width:1000,height:720})};
const projection={route:{bounds:{min_lat:23.3,max_lat:23.6,min_lon:120.8,max_lon:121.2}}};
const debugPageState={projection,zoom:1,panX:0,panY:0};
assert.deepEqual(rasterZoomRangeFor(projection,'rudy-twmap'),{min:5,max:20});
assert.deepEqual(rasterZoomRangeFor(projection,'imagery'),{min:10,max:14});
const fit=chooseRasterZoom(projection,debugRudyViewportBounds(projection),'rudy-twmap');
debugPageState.zoom=1.25;
const after=chooseRasterZoom(projection,debugRudyViewportBounds(projection),'rudy-twmap');
assert.equal(after,fit+1,'the first + must change native tile zoom');
debugPageState.zoom=debugMapInteractionMaxZoom();
const at20=debugRudyViewportBounds(projection);
assert.equal(chooseRasterZoom(projection,at20,'rudy-twmap'),20);
const first=tileRangeForZoom(at20,20);
debugPageState.panX+=100/debugPageState.zoom;
const panned=tileRangeForZoom(debugRudyViewportBounds(projection),20);
assert.notDeepEqual(panned,first,'pan must request different native tile coverage');
''')


DOM_REPLAY = r'''
const debugPageState={mapLibreDisposed:false};
class Element {
  constructor(tag,attrs={}) {this.tag=tag;this.attrs={...attrs};this.dataset={};this.children=[];this.parentNode=null;this.events={};}
  setAttribute(k,v){this.attrs[k]=String(v);}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  appendChild(node){node.remove();this.children.push(node);node.parentNode=this;return node;}
  replaceChildren(...nodes){for(const child of [...this.children])child.remove();for(const node of nodes)this.appendChild(node);}
  remove(){if(this.parentNode){const p=this.parentNode;p.children=p.children.filter(n=>n!==this);this.parentNode=null;}}
  contains(node){return node===this || this.children.some(child=>child.contains(node));}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(child.tag===selector?[child]:[]),...child.querySelectorAll(selector)]);}
  fire(event){this.events[event]?.();}
}
const runtimeMap=new Element('svg');
const group=new Element('g');runtimeMap.appendChild(group);
const svgEl=(tag,attrs)=>new Element(tag,attrs);
const timers=new Map();let nextTimer=1;
const setTimeout=fn=>{const id=nextTimer++;timers.set(id,fn);return id;};
const clearTimeout=id=>timers.delete(id);
const RUDY_TILE_SWAP_TIMEOUT_MS=12000;
const positionTileImage=()=>{},rasterLayerFor=()=>({});
const debugRudyViewportBounds=()=>({west:120,east:121,south:23,north:24});
let requestedZoom=14;
let tiles=[{z:14,x:1,y:1,href:'native-exact/14/1/1'}, {z:14,x:2,y:1,href:'native-exact/14/2/1'}];
const rasterTileCoverage=()=>tiles,chooseRasterZoom=()=>requestedZoom;
const view={zoom:1.25,panX:10,panY:20};
const viewBefore=JSON.stringify(view);
let status=null;
const updateDebugRudyTileStatus=value=>{status=value;};
const stage=()=>stageDebugRudyTiles(group,{},{});
const images=()=>group.children.find(child=>child.attrs['data-tile-generation']==='pending')?.children || [];
function advance(z){requestedZoom=z;tiles=tiles.map(tile=>({...tile,z,href:`native-exact/${z}/${tile.x}/${tile.y}`}));stage();}
'''


DEBUG_DISPOSE_REPLAY = r'''
const window={}, runtimeMapLibre={dataset:{}};
const disposeDebugMapEvidenceControls=()=>{};
runtimeMap.querySelectorAll=selector=>selector==='[data-layer-group="rudy-twmap"]'?[group]:[];
group.querySelector=selector=>selector==='[data-tile-generation="pending"]'
  ?group.children.find(child=>child.attrs['data-tile-generation']==='pending')||null:null;
'''


def test_debug_dispose_cancels_svg_cohort_and_blocks_late_staging():
    node(functions("stageDebugRudyTiles", "disposeDebugMapRenderer") + DOM_REPLAY + DEBUG_DISPOSE_REPLAY + r'''
(async()=>{
stage();const pendingImages=images();assert.equal(timers.size,1);
const receipt=await disposeDebugMapRenderer();
assert.equal(receipt.disposed,true);assert.equal(timers.size,0);assert.equal(group.debugRudyPending,null);
for(const image of pendingImages){assert.equal(image.attrs.href,undefined);image.fire('load');}
assert.equal(group.querySelector('[data-tile-generation="pending"]'),null);
stage();assert.equal(timers.size,0);assert.equal(group.debugRudyPending,null);
assert.deepEqual(await disposeDebugMapRenderer(),receipt);
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_debug_dispose_reports_missing_svg_cancel_hook_instead_of_success():
    node(functions("stageDebugRudyTiles", "disposeDebugMapRenderer") + DOM_REPLAY + DEBUG_DISPOSE_REPLAY + r'''
(async()=>{
stage();const cancel=group.debugRudyCancel;delete group.debugRudyCancel;
const receipt=await disposeDebugMapRenderer();
assert.equal(receipt.disposed,false);assert.equal(receipt.pendingInitializations,null);
assert.ok(receipt.errors.some(error=>error.errorName==='MissingCancellationHook'));
assert.deepEqual(await disposeDebugMapRenderer(),receipt);cancel();
})().catch(error=>{console.error(error);process.exitCode=1});
''')


def test_svg_promotes_only_complete_generation_and_retains_view_on_failure_then_retry():
    node(functions("stageDebugRudyTiles") + DOM_REPLAY + r'''
stage();
let pending=images();
pending[0].fire('load');
assert.equal(status.state,'loading');assert.equal(status.success_count,1);
assert.equal(group.debugRudyActive,undefined);
pending[1].fire('load');
assert.equal(status.state,'available');assert.equal(status.success_count,2);
const original=group.children[0];assert.equal(original.attrs['data-tile-generation'],'active');
advance(15);pending=images();
pending[0].fire('load');pending[1].fire('error');
assert.equal(status.state,'degraded');assert.equal(status.error_count,1);
assert.equal(status.retained_native_zoom,14);
assert.equal(group.children.length,1);assert.equal(group.children[0],original);
assert.equal(pending[1].attrs.href,undefined,'failed images must not retry lower zoom parents');
assert.equal(JSON.stringify(view),viewBefore);
stage();pending=images();pending.forEach(image=>image.fire('load'));
assert.equal(status.state,'available');assert.equal(status.native_zoom,15);
assert.notEqual(group.children[0],original);assert.equal(timers.size,0);
assert.equal(JSON.stringify(view),viewBefore);
''')


def test_svg_timeout_cancel_and_superseded_callbacks_cannot_claim_native_success():
    node(functions("stageDebugRudyTiles") + DOM_REPLAY + r'''
stage();images().forEach(image=>image.fire('load'));const original=group.children[0];
advance(15);const outdated=images();
advance(16);outdated.forEach(image=>image.fire('load'));
assert.equal(status.state,'loading');assert.equal(status.native_zoom,16);
assert.equal(group.children[0],original);
const timeout=[...timers.values()][0];timeout();
assert.equal(status.state,'degraded');assert.equal(status.reason,'native_tiles_timeout');
assert.equal(status.unverified_count,2);assert.equal(status.retained_native_zoom,14);
assert.equal(group.children[0],original);
stage();const stopped=images();group.debugRudyCancel();
const atStop=status;stopped.forEach(image=>image.fire('load'));
assert.equal(status,atStop);assert.equal(group.children.length,1);
assert.equal(timers.size,0);assert.equal(JSON.stringify(view),viewBefore);
''')


def test_native_status_requires_full_coverage_and_does_not_hide_errors_behind_renderer_ready():
    node(functions("updateDebugRudyTileStatus") + r'''
const debugPageState={};const runtimeMapRendererShell={dataset:{mapRendererState:'ready'}};
const output={};const document={getElementById:()=>output};const updateMapZoomIndicator=()=>{};
updateDebugRudyTileStatus({state:'available',visible:true,native_zoom:20,required_count:4,success_count:3,unverified_count:1});
assert.equal(runtimeMapRendererShell.dataset.debugRudyState,'degraded');
assert.equal(runtimeMapRendererShell.dataset.debugRudyVerifiedZoom,'');
assert.match(output.textContent,/細節未完整載入/);
updateDebugRudyTileStatus({state:'available',visible:true,native_zoom:20,required_count:4,success_count:4});
assert.equal(runtimeMapRendererShell.dataset.debugRudyVerifiedZoom,'20');
assert.equal(runtimeMapRendererShell.dataset.debugRudyPendingCount,'0');
assert.equal(runtimeMapRendererShell.dataset.debugRudyUnverifiedCount,'0');
updateDebugRudyTileStatus({state:'degraded',visible:true,native_zoom:20,required_count:4,success_count:2,error_count:1,unverified_count:1,retained_native_zoom:19});
assert.equal(runtimeMapRendererShell.dataset.debugRudyVerifiedZoom,'');
assert.equal(runtimeMapRendererShell.dataset.debugRudyRetainedZoom,'19');
assert.match(output.textContent,/保留先前 Z19/);
assert.equal(runtimeMapRendererShell.dataset.mapRendererState,'ready');
updateDebugRudyTileStatus({state:'hidden',visible:false});assert.equal(output.hidden,true);
''')


def test_refresh_reconfigures_transport_without_moving_camera_and_cancels_remote_mode():
    node(functions("toggleDebugRudyRefresh") + r'''
const camera={zoom:19,center:[121,23.5]};const original=JSON.stringify(camera);
const debugPageState={projection:{},rudyRemoteRefreshEnabled:true,rudyForceRefresh:false,rudyRefreshNonce:0,
  mapLibreRenderer:{setRasterLayers:layers=>calls.push(layers)}};
const calls=[];let mapLibre=true,svgCalls=0;
const debugMapLibreActive=()=>mapLibre, syncDebugRudyRefreshButton=()=>{};
const debugMapLibreRasterLayers=()=>({native:debugPageState.rudyRemoteRefreshEnabled,revision:debugPageState.rudyRefreshNonce});
const syncRasterBasemapLayers=()=>{svgCalls+=1;};
toggleDebugRudyRefresh();assert.equal(debugPageState.rudyRemoteRefreshEnabled,false);
assert.deepEqual(calls[0],{native:false,revision:1});
toggleDebugRudyRefresh();assert.equal(debugPageState.rudyForceRefresh,true);
assert.deepEqual(calls[1],{native:true,revision:2});
mapLibre=false;toggleDebugRudyRefresh();assert.equal(svgCalls,1);
assert.equal(JSON.stringify(camera),original);
''')
