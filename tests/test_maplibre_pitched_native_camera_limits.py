"""Pinned vendor geometry replay for the D037 five-lens pitched maximum failure.

This is computation evidence, not a live browser verdict. The test-only export
exposes the bundled transform without replacing MapLibre's covering algorithm.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("SCOUT_NATIVE_CAP_SOURCE", ROOT / "docs/admin/scout-maplibre-evidence.js"))
VENDOR = ROOT / "docs/admin/vendor/maplibre-gl/6.2.0"
DIAGNOSTIC = ROOT / "docs/admin/scout-rudy-live-diagnostic.js"


def geometry(probe: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for the actual vendor geometry replay"
    program = r"""
const fs=require('node:fs'), {pathToFileURL}=require('node:url');
global.window=globalThis;global.location={origin:'http://scout.test'};
global.fetch=()=>{throw Error('No network in geometry replay');};
require(process.argv[1]);const scout=ScoutMapLibreEvidence;
const diagnostic=require(process.argv[3]);
(async()=>{
const vendor=process.argv[2];
let source=fs.readFileSync(`${vendor}/maplibre-gl.mjs`,'utf8');
source=source.replace('./maplibre-gl-shared.mjs',pathToFileURL(`${vendor}/maplibre-gl-shared.mjs`).href);
source+='\nexport {Ts as TestMercatorTransform, tp as TestCamera};\n';
const lib=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const layer=scout.normalizeRasterLayer({layer_id:'rudy-twmap',source_id:'happyman_rudy_twmap',
 tiles:['/tiles/{z}/{x}/{y}.png?native=1&exact=1'],minzoom:5,maxzoom:20,tile_size:256});
function makeMap({pitch=58,bearing=-28,width=1062,height=700,elevation=0,terrain=true,center=[121.24676003873537,23.349075258976697]}={}) {
 const transform=new lib.TestMercatorTransform({minZoom:0,maxZoom:24,minPitch:0,maxPitch:80,renderWorldCopies:false});
 transform.resize(width,height);transform.setCenter(new lib.LngLat(...center));transform.setElevation(elevation);
 transform.setPitch(pitch);transform.setBearing(bearing);transform.setZoom(19);
 const source={tileSize:256,minzoom:5,maxzoom:20,roundZoom:true,hasTile:()=>true};
 return {_camera:{transform},getSource:()=>source,getZoom:()=>transform.zoom,getPitch:()=>transform.pitch,
  getMaxZoom:()=>transform.maxZoom,getMinZoom:()=>transform.minZoom,getCenter:()=>transform.center,
  setMaxZoom:zoom=>transform.setMaxZoom(zoom),coveringTiles:lib.Map.prototype.coveringTiles,
  terrain:terrain?{getMinMaxElevation:()=>({minElevation:elevation,maxElevation:elevation})}:null};
}
function snapshot(map,policy) {
 const camera=scout.rasterNativeCameraReceipt(map,layer,policy);
 return {activeRenderer:'maplibre',rendererReady:true,matrix:20,verified:20,required:77,success:77,pending:0,
 errors:0,unverified:0,status:'available',failure:'',viewLimits:{viewZoom:map.getZoom(),maxViewZoom:map.getMaxZoom(),
 nativePixelRatio:camera.worldPixelsPerProviderPixel,nativeCamera:camera}};
}
function cameraState(map) {const t=map._camera.transform;return JSON.stringify({zoom:t.zoom,maxZoom:t.maxZoom,
 center:t.center,pitch:t.pitch,bearing:t.bearing,roll:t.roll,elevation:t.elevation,width:t.width,height:t.height});}
"""
    program += probe + "\n})().catch(e=>{console.error(e.stack);process.exit(1)});"
    result = subprocess.run([node, "-e", program, str(SCRIPT), str(VENDOR), str(DIAGNOSTIC),
                             str(ROOT / "docs/admin/scout-dashboard-v0.1.html")],
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("center", [
    [121.24676003873537, 23.349075258976697],
    [121.24676003874242, 23.349075258973883],
    [121.24676003873992, 23.349075258975546],
    [121.24676003874231, 23.349075258973116],
    [121.24676003873446, 23.349075258972107],
])
def test_five_recorded_camera_centers_reject_old_cap_and_accept_projected_cap(center: list[float]) -> None:
    result = geometry("""
const map=makeMap({center:CENTER});
const oldPolicy=scout.rasterNativeCameraPolicy([layer],20);map.setMaxZoom(oldPolicy.maxCameraZoom);
const old=snapshot(map,oldPolicy),before=cameraState(map);
const policy=scout.rasterNativeCameraPolicy([layer],20,{map,maplibregl:lib});
const computationMovedCamera=before!==cameraState(map);
map.setMaxZoom(policy.maxCameraZoom);const current=snapshot(map,policy);
console.log(JSON.stringify({old,policy,current,computationMovedCamera,
 oldMaximumComplete:diagnostic.maximumComplete(old),currentMaximumComplete:diagnostic.maximumComplete(current)}));
""".replace("CENTER", json.dumps(center)))
    assert result["old"]["viewLimits"]["nativeCamera"]["requestedAboveNativeMax"] is True
    assert 21 in result["old"]["viewLimits"]["nativeCamera"]["requestedNativeZooms"]
    assert result["oldMaximumComplete"] is False
    assert result["currentMaximumComplete"] is True, "The actual maximum must satisfy the unchanged D037 predicate"
    assert result["policy"]["nativeDemandCap"]["status"] == "verified"
    assert 18 < result["policy"]["maxCameraZoom"] < 19
    assert result["computationMovedCamera"] is False
    assert max(result["current"]["viewLimits"]["nativeCamera"]["requestedNativeZooms"]) == 20


@pytest.mark.parametrize("options", [
    {"pitch": 0}, {"pitch": 25}, {"pitch": 58}, {"pitch": 70}, {"pitch": 80},
    {"pitch": 58, "terrain": False},
    {"pitch": 80, "terrain": False},
    {"pitch": 58, "bearing": 95, "width": 430, "height": 800},
    {"pitch": 58, "bearing": 0, "width": 1920, "height": 1080},
    {"pitch": 58, "elevation": 1500},
    {"pitch": 58, "elevation": 3000, "center": [121.11, 23.45]},
])
def test_pitched_cap_uses_actual_viewport_terrain_and_keeps_native_twenty(options: dict) -> None:
    result = geometry("""
const map=makeMap(OPTIONS),before=cameraState(map);
const policy=scout.rasterNativeCameraPolicy([layer],20,{map,maplibregl:lib});
const unchanged=before===cameraState(map);map.setMaxZoom(policy.maxCameraZoom);
const current=snapshot(map,policy);
const repeated=scout.rasterNativeCameraPolicy([layer],20,{map,maplibregl:lib});
console.log(JSON.stringify({policy,current,repeated,unchanged,maximumComplete:diagnostic.maximumComplete(current)}));
""".replace("OPTIONS", json.dumps(options)))
    assert result["unchanged"] is True
    assert result["policy"]["maxCameraZoom"] == result["repeated"]["maxCameraZoom"], "Cap must not oscillate after clamping"
    assert result["maximumComplete"] is True
    if options["pitch"] == 0:
        assert result["policy"]["maxCameraZoom"] == 19
        assert "nativeDemandCap" not in result["policy"]
    else:
        assert result["policy"]["nativeDemandCap"]["status"] == "verified"


@pytest.mark.parametrize("fault,reason", [
    ("version", "vendor_unverified"), ("method", "vendor_unverified"),
    ("missing-clone", "clone_unavailable"), ("same-clone", "clone_unavailable"),
    ("empty-cohort", "cohort_unavailable"), ("zero-viewport", "clone_unavailable"),
])
def test_projection_fault_is_explicitly_unverified_and_does_not_hide_actual_overzoom(fault: str, reason: str) -> None:
    result = geometry("""
const map=makeMap();let module=lib;const fault=FAULT;
if(fault==='version')module={...lib,getVersion:()=> '6.3.0'};
if(fault==='method')module={...lib,Map:{prototype:{coveringTiles:()=>[]}}};
if(fault==='missing-clone')map._camera.transform.clone=null;
if(fault==='same-clone')map._camera.transform.clone=()=>map._camera.transform;
if(fault==='empty-cohort')map.getSource().hasTile=()=>false;
if(fault==='zero-viewport')map._camera.transform.resize(0,0);
const before=cameraState(map),policy=scout.rasterNativeCameraPolicy([layer],20,{map,maplibregl:module});
const unchanged=before===cameraState(map);map.setMaxZoom(policy.maxCameraZoom);
const current=snapshot(map,policy);
console.log(JSON.stringify({policy,unchanged,current,maximumComplete:diagnostic.maximumComplete(current)}));
""".replace("FAULT", json.dumps(fault)))
    assert result["policy"]["nativeDemandCap"]["status"] == "unverified"
    assert reason in result["policy"]["nativeDemandCap"]["reason"]
    assert result["unchanged"] is True
    assert result["maximumComplete"] is False


def test_return_to_two_dimensions_and_hidden_rudy_restore_existing_cap() -> None:
    result = geometry("""
const map=makeMap(),context={map,maplibregl:lib};
const pitched=scout.rasterNativeCameraPolicy([layer],22,context);map.setMaxZoom(pitched.maxCameraZoom);
map._camera.transform.setPitch(0);
const flat=scout.rasterNativeCameraPolicy([layer],22,context);
map._camera.transform.setPitch(58);
const hidden=scout.rasterNativeCameraPolicy([{...layer,visible:false}],22,context);
console.log(JSON.stringify({pitched,flat,hidden}));
""")
    assert result["pitched"]["maxCameraZoom"] < 19
    assert result["flat"]["maxCameraZoom"] == 19
    assert result["hidden"]["maxCameraZoom"] == 22
    assert result["hidden"]["active"] is False


@pytest.mark.parametrize("vendor_matches", [True, False])
def test_dashboard_caller_with_real_vendor_camera_and_synchronous_move_reentry(vendor_matches: bool) -> None:
    result = geometry(r"""
const html=fs.readFileSync(process.argv[4],'utf8');
const match=html.match(/entry\.updateNativeCameraLimit = ([\s\S]+?);\n\s+entry\.updateNativeCameraLimit\(\);/);
if(!match)throw Error('Missing production Navigation cap caller');
const body=match[1];
const map=makeMap(),camera=new lib.TestCamera({minZoom:0,maxZoom:24,maxPitch:80});
camera.transform=map._camera.transform;camera.terrain=map.terrain;
camera.terrain.getElevationForLngLatZoom=()=>0;map._camera=camera;
let setCalls=0,depth=0,maxDepth=0,updates=0;const events=[];
map._update=()=>{};
map.fire=function(event){events.push(event.type);if(['move','moveend'].includes(event.type))update();return this;};
map.setMaxZoom=function(value){setCalls++;return lib.Map.prototype.setMaxZoom.call(this,value);};
const label={textContent:''},host={dataset:{},parentElement:{querySelector:()=>label}},entry={rudyLayer:layer};
const module=VENDOR_MATCHES?lib:{...lib,getVersion:()=> '6.3.0'};
const original=new Function('entry','map','maplibregl','host',`return (${body})`)(entry,map,module,host);
function update(){depth++;maxDepth=Math.max(depth,maxDepth);updates++;if(depth>8)throw Error('Synchronous cap recursion');
 try{return original();}finally{depth--;}}
const before={center:map.getCenter().toArray(),pitch:map.getPitch()};
const began=performance.now();update();
for(let i=0;i<20;i++)map.fire({type:'move'});
const elapsedMs=performance.now()-began;
console.log(JSON.stringify({setCalls,maxDepth,updates,events,elapsedMs,before,
 after:{center:map.getCenter().toArray(),pitch:map.getPitch()},receipt:entry.nativeCameraReceipt,label:label.textContent,
 current:snapshot(map,entry.nativeCameraReceipt),maximumComplete:diagnostic.maximumComplete(snapshot(map,entry.nativeCameraReceipt))}));
""".replace("VENDOR_MATCHES", json.dumps(vendor_matches)))
    assert result["setCalls"] == 1
    assert result["maxDepth"] <= 2
    assert result["before"] == result["after"]
    if vendor_matches:
        assert result["receipt"]["nativeDemandCap"]["status"] == "verified"
        assert result["maximumComplete"] is True
        assert "未驗證" not in result["label"]
        assert "zoomstart" in result["events"] and "moveend" in result["events"]
    else:
        assert result["receipt"]["nativeDemandCap"]["status"] == "unverified"
        assert "未驗證" in result["label"]
        assert result["receipt"]["requestedAboveNativeMax"] is True
        assert result["maximumComplete"] is False
