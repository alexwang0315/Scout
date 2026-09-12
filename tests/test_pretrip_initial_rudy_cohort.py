"""The real initial renderMap path must observe every native image before readiness."""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase4-pretrip-planning.html"


def _functions(*names: str) -> str:
    source = PAGE.read_text()
    extracted = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source)
        assert match, name
        extracted.append(match.group())
    return "\n".join(extracted)


def _replay(probe: str) -> None:
    program = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><div id="mapRendererShell"><svg id="map"></svg></div><div id="mapRendererStatus"></div></body>');
const window=dom.window,document=window.document,svg=document.getElementById('map');
const timers=new Map();let timerSequence=0;
window.setTimeout=fn=>{const id=++timerSequence;timers.set(id,fn);return id;};
window.clearTimeout=id=>timers.delete(id);
const MAP_WIDTH=800,MAP_HEIGHT=600,RASTER_MAX_TILES=200,RASTER_TILE_SWAP_TIMEOUT_MS=15000;
const RASTER_OVERLAY_LAYER_DEFINITIONS=[{layerId:'rudy-twmap'}],RASTER_SOURCE_LAYER_BY_ID={};
const el=(tag,attrs={})=>{const element=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([key,value])=>element.setAttribute(key,value));return element;};
const view={route:{},map_candidates:{get corridor_candidates(){throw new Error('stop-after-initial-raster');}}};
const state={view,zoom:1,panX:0,panY:0,mapRenderer:{active:'svg'},rasterRemoteRefreshEnabled:true};
const boundsFor=()=>({west:120,east:121,south:23,north:24}),visibleBoundsFor=boundsFor;
const layerInputChecked=layer=>layer==='rudy-twmap';
const rasterLayerFor=()=>({source_id:'happyman_rudy_twmap',source_kind:'native_xyz'});
const rasterZoomRangeFor=()=>({min:5,max:20});
let requestedZoom=12;
const rasterTileUrl=(_view,_layer,z,x,y)=>`/native/${z}/${x}/${y}.png?native=1&exact=1`;
const rasterTileCoverage=()=>[0,1,2].map(x=>({z:requestedZoom,x,y:3,href:rasterTileUrl(view,'rudy-twmap',requestedZoom,x,3)}));
const positionTileImage=(image,_bounds,tile)=>{image.setAttribute('width','256');image.setAttribute('height','256');};
const parentTileFor=tile=>({...tile,z:tile.z-1,x:Math.floor(tile.x/2),y:Math.floor(tile.y/2)});
const chooseRasterZoom=()=>requestedZoom,updateMapZoomIndicator=()=>{},enforceMapRenderPolicy=()=>{};
const renderOsmBasemap=()=>{},syncPretripMapLibreEvidence=()=>{throw new Error('wrong renderer');};
''' + _functions("renderRasterLayer", "attachTileFallback", "rasterLayerTileGenerationKey", "mapViewStateSnapshot",
                    "rememberRudyMapView", "retainRudyMapViewAfterTileFailure", "updateRudyTileStatus",
                    "markRasterLayerGenerationActive", "discardPendingRasterLayerGeneration", "replaceRasterLayerWhenReady", "renderMap") + r'''
try {renderMap(view);} catch(error) {if(error.message!=='stop-after-initial-raster')throw error;}
const group=svg.querySelector('[data-layer-group="rudy-twmap"]');
const images=()=>[...group.querySelectorAll('image')];
const load=image=>image.dispatchEvent(new window.Event('load'));
const error=image=>image.dispatchEvent(new window.Event('error'));
const replace=()=>replaceRasterLayerWhenReady(group,candidate=>renderRasterLayer(candidate,view,boundsFor(),MAP_WIDTH,MAP_HEIGHT,'rudy-twmap'),
 ({reason})=>retainRudyMapViewAfterTileFailure(group,reason));
''' + probe
    result = subprocess.run(["node"], input=program, capture_output=True, text=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def test_initial_render_tracks_partial_and_complete_load_without_early_ready() -> None:
    _replay(r'''
assert.equal(group.dataset.tileGenerationState,'loading');assert.equal(images().length,3);
assert.equal(group.dataset.activeTileGenerationKey,undefined);
assert.equal(images().filter(image=>image.dataset.tileGenerationLoaded==='true').length,0);
load(images()[0]);load(images()[1]);
assert.equal(group.dataset.tileGenerationState,'loading');assert.equal(group.dataset.activeTileGenerationKey,undefined);
assert.equal(images().filter(image=>image.dataset.tileGenerationLoaded==='true').length,2);
load(images()[2]);assert.equal(group.dataset.tileGenerationState,'ready');
assert.equal(images().filter(image=>image.dataset.tileGenerationLoaded==='true').length,3);
assert.equal(group.querySelector('[data-tile-generation="active"]').getAttribute('aria-hidden'),null);
assert.equal(document.getElementById('mapRendererShell').dataset.mapRasterState,'available');
assert.equal(group.dataset.activeMapZoom,'1');assert.equal(timers.size,0);
assert.equal(replace(),false);assert.equal(images().filter(image=>image.dataset.tileGenerationLoaded==='true').length,3);
''')


def test_initial_error_is_not_parent_fallback_or_native_success_and_recovers() -> None:
    _replay(r'''
const failed=images()[1],requestedTile=failed.dataset.rasterTile;
load(images()[0]);error(failed);
assert.equal(failed.dataset.rasterTile,requestedTile,'native Rudy cannot switch to a parent tile');
assert.equal(failed.getAttribute('href'),null);assert.equal(images().length,0);
assert.equal(group.dataset.tileGenerationState,'retained-previous');assert.equal(group.dataset.activeTileGenerationKey,undefined);
assert.equal(document.getElementById('mapRendererShell').dataset.mapRasterState,'degraded');
assert.equal(group.dataset.nativeTileFailure,'load-error');assert.equal(timers.size,0);
assert.equal(replace(),true);images().forEach(load);assert.equal(group.dataset.tileGenerationState,'ready');
assert.equal(images().filter(image=>image.dataset.tileGenerationLoaded==='true').length,3);
assert.equal(group.dataset.nativeTileFailure,undefined);
''')


def test_failed_replacement_preserves_only_previously_complete_initial_cohort() -> None:
    _replay(r'''
images().forEach(load);const initial=[...images()],active=group.dataset.activeTileGenerationKey;
requestedZoom=13;state.zoom=2;replace();
const candidate=group.querySelector('[data-tile-generation="pending"]');
load(candidate.querySelectorAll('image')[0]);error(candidate.querySelectorAll('image')[1]);
assert.equal(group.dataset.activeTileGenerationKey,active);assert.deepEqual(images(),initial);
assert.equal(group.dataset.tileGenerationState,'retained-previous');assert.equal(state.zoom,2);
assert(images().every(image=>image.dataset.tileGenerationLoaded==='true'));
assert.equal(document.getElementById('mapRendererShell').dataset.mapRasterState,'degraded');
replace();[...group.querySelectorAll('[data-tile-generation="pending"] image')].forEach(load);
assert.equal(group.dataset.tileGenerationState,'ready');assert(images().every(image=>image.dataset.rasterTile.startsWith('13/')));
assert.equal(timers.size,0);
''')
