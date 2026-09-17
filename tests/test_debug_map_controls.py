"""Replay Debug evidence keyboard controls and the wheelZoom=0 contract."""
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase-3-5-runtime-debug.html"


def functions(*names):
    source = PAGE.read_text()
    extracted = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source)
        assert match, name
        extracted.append(match.group())
    return "\n".join(extracted)


def node(source):
    result = subprocess.run(["node"], input=source, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def controls_replay():
    return r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><div id="runtimeMapRendererShell"><svg id="runtimeMap"></svg><div id="runtimeMapLibre"><canvas></canvas></div></div></body>');
const window=dom.window,document=window.document;
const runtimeMap=document.querySelector('svg'),runtimeMapLibre=document.getElementById('runtimeMapLibre');
for(const id of ['debugClearButton','mobileIngressResetButton','zoomIn','zoomOut','fitRoute','refreshMapTiles','panMode','boxZoomMode','panUp','panDown','panLeft','panRight']) {
 const button=document.createElement('button');button.id=id;document.body.appendChild(button);
}
const zooms=[],pans=[],selected=[];let mapLibre=false,MAP_WHEEL_ZOOM_ENABLED=false;
const debugPageState={zoomSelection:null,hoveredMapTarget:null,mapKeyboardActive:false,mapInteractionMode:'pan'};
const debugMapLibreActive=()=>mapLibre;
const mapFeatureTitle=item=>item.display_label || item.identity_key || 'evidence';
const mapFeatureSummary=item=>item.evidence_type || 'evidence source';
const bindLayerMenuDismiss=()=>{},clearDebugProjection=()=>{},resetMobileWearableIngressProjection=()=>{};
const updateLayers=()=>{},applyLayerPreset=()=>{},toggleDebugRudyRefresh=()=>{},syncDebugRudyRefreshButton=()=>{};
const zoomMap=n=>zooms.push(n),panMap=(x,y)=>pans.push([x,y]),resetMapView=()=>{};
const setMapInteractionMode=mode=>{debugPageState.mapInteractionMode=mode;};
const beginMapRectangleZoom=()=>{},updateMapRectangleZoom=()=>{},finishMapRectangleZoom=()=>{},cancelMapRectangleZoom=()=>{};
const beginMapPointerPan=()=>{},updateMapPointerPan=()=>{},finishMapPointerPan=()=>{},cancelMapPointerPan=()=>{};
const selectTimelineForMapTarget=target=>selected.push(target.dataset.mapRef);
const selectDebugMapLibreFeature=feature=>selected.push(feature.id);
''' + functions(
        "text", "mapFeatureKind", "mapFeatureAriaLabel", "attachMapEvidence",
        "mapHoverTooltip", "positionMapHoverTooltip", "showMapHoverTooltip", "hideMapHoverTooltip",
        "handleMapHoverPointerMove", "handleMapEvidenceFocus", "handleMapEvidenceKeyboard",
        "mapKeyboardPanDelta", "isEditableKeyboardTarget", "handleMapKeyboardPan",
        "activateMapKeyboardPan", "deactivateMapKeyboardPanOutside", "handleMapWheelZoom", "bindDebugControls",
        "disposeDebugMapEvidenceControls", "configureDebugMapLibreControls", "syncDebugMapLibreKeyboardEvidence",
    ) + r'''
bindDebugControls();
const hintVisible=()=>Boolean(document.querySelector('.map-hover-tooltip.is-visible'));
function evidence(id='cp-1') {
 const point=document.createElementNS(runtimeMap.namespaceURI,'circle');point.setAttribute('r','5');
 attachMapEvidence(point,{source_id:id,display_label:`Checkpoint ${id}`,evidence_type:'checkpoint'},id);
 runtimeMap.appendChild(point);return point;
}
function key(target,value) {const event=new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true});target.dispatchEvent(event);return event;}
'''


def test_svg_evidence_focus_pointer_activation_escape_and_blur_use_real_bindings():
    node(controls_replay() + r'''
const point=evidence();
assert.equal(point.tabIndex,0);assert.equal(point.getAttribute('role'),'button');
point.dispatchEvent(new window.MouseEvent('pointermove',{bubbles:true,clientX:20,clientY:30}));
assert(hintVisible());assert.match(document.querySelector('.map-hover-tooltip strong').textContent,/Checkpoint cp-1/);
assert.match(document.querySelector('.map-hover-tooltip span').textContent,/checkpoint/);
runtimeMap.dispatchEvent(new window.MouseEvent('pointerleave'));assert(!hintVisible());
point.focus();assert.equal(document.activeElement,point);assert(hintVisible());
assert(!document.querySelector('.map-hover-tooltip').style.left.includes('NaN'));
assert(key(point,'Enter').defaultPrevented);assert.deepEqual(selected,['cp-1']);
assert(key(point,' ').defaultPrevented);assert.deepEqual(selected,['cp-1','cp-1']);
assert(key(point,'Escape').defaultPrevented);assert(!hintVisible());
point.blur();point.focus();assert(hintVisible());point.blur();assert(!hintVisible());
''')


def test_disabled_wheel_leaves_page_scroll_and_camera_untouched():
    node(controls_replay() + r'''
const wheel=new window.WheelEvent('wheel',{deltaY:-120,bubbles:true,cancelable:true});
runtimeMap.dispatchEvent(wheel);assert.equal(wheel.defaultPrevented,false);assert.deepEqual(zooms,[]);
const direct=new window.WheelEvent('wheel',{deltaY:-120,cancelable:true});
handleMapWheelZoom(direct);assert.equal(direct.defaultPrevented,false);assert.deepEqual(zooms,[]);
MAP_WHEEL_ZOOM_ENABLED=true;
const enabled=new window.WheelEvent('wheel',{deltaY:-120,cancelable:true});
handleMapWheelZoom(enabled);assert.equal(enabled.defaultPrevented,true);assert.deepEqual(zooms,[1]);
const browserZoom=new window.WheelEvent('wheel',{deltaY:-120,ctrlKey:true,cancelable:true});
handleMapWheelZoom(browserZoom);assert.equal(browserZoom.defaultPrevented,false);assert.deepEqual(zooms,[1]);
''')


MAPLIBRE_REPLAY = r'''
const features=new Map([
 ['visible-1',{id:'visible-1',geometry:{type:'Point'},properties:{identity_key:'visible-1',source_id:'source-1',display_label:'Live checkpoint',evidence_type:'checkpoint'}}],
 ['visible-2',{id:'visible-2',geometry:{type:'LineString'},properties:{identity_key:'visible-2',source_id:'source-2',display_label:'Live route',evidence_type:'route'}}],
 ['hidden-only',{id:'hidden-only',geometry:{type:'Point'},properties:{identity_key:'hidden-only',display_label:'Offscreen evidence'}}],
]);
let rendered=[{id:'visible-1'},{id:'visible-1'},{id:'visible-2'},{id:'not-evidence'}];
const focused=[],bindings=[],unbound=[],scroll=[],nativeKeyboard=[];
const camera={zoom:15,center:[121,23.5]},cameraBefore=JSON.stringify(camera);
const map={queryRenderedFeatures:()=>rendered,getCanvas:()=>runtimeMapLibre.querySelector('canvas'),
 on:(event,handler)=>bindings.push([event,handler]),off:(event,handler)=>unbound.push([event,handler]),
 scrollZoom:{enable:()=>scroll.push('enable'),disable:()=>scroll.push('disable')},
 keyboard:{disable:()=>nativeKeyboard.push('disable')}};
const renderer={map,index:{feature:id=>features.get(String(id))},focus:(id,options)=>focused.push({id,options})};
debugPageState.mapLibreRenderer=renderer;mapLibre=true;runtimeMap.hidden=true;
configureDebugMapLibreControls(renderer);
'''


def test_maplibre_keyboard_target_comes_from_rendered_canvas_evidence_and_highlights_it():
    node(controls_replay() + MAPLIBRE_REPLAY + r'''
const target=runtimeMapLibre.querySelector('#debugMapLibreEvidenceTarget');
assert(target);assert.equal(target.tabIndex,0);assert.equal(target.dataset.featureId,'visible-1');
assert.equal(target.dataset.sourceId,'source-1');assert.equal(target.dataset.mapRendererEvidence,'maplibre');
assert.equal(runtimeMapLibre.dataset.debugKeyboardEvidenceCount,'2','duplicate and non-rendered features must not appear');
assert.equal(runtimeMapLibre.querySelectorAll('option').length,2);
target.dispatchEvent(new window.MouseEvent('pointermove',{bubbles:true,clientX:20,clientY:30}));assert(hintVisible());
runtimeMapLibre.dispatchEvent(new window.MouseEvent('pointerleave'));assert(!hintVisible());
target.focus();assert(hintVisible());assert.deepEqual(focused.at(-1),{id:'visible-1',options:{fit:false}});
assert.match(document.querySelector('.map-hover-tooltip strong').textContent,/Live checkpoint/);
key(target,'Enter');assert.deepEqual(selected,['visible-1']);
key(target,'Escape');assert(!hintVisible());
const select=runtimeMapLibre.querySelector('select');select.focus();select.value='visible-2';
select.dispatchEvent(new window.Event('change',{bubbles:true}));target.focus();
assert.equal(target.dataset.featureId,'visible-2');assert.equal(target.dataset.sourceId,'source-2');
assert.deepEqual(focused.at(-1),{id:'visible-2',options:{fit:false}});
assert.match(document.querySelector('.map-hover-tooltip strong').textContent,/Live route/);
target.blur();assert(!hintVisible());assert.equal(JSON.stringify(camera),cameraBefore);
hideMapHoverTooltip();const hidden=evidence('hidden-svg');
hidden.dispatchEvent(new window.FocusEvent('focusin',{bubbles:true}));assert(!hintVisible(),'hidden SVG cannot satisfy MapLibre evidence focus');
''')


def test_maplibre_disabled_wheel_uses_native_handler_disable_and_cleanup_removes_keyboard_targets():
    node(controls_replay() + MAPLIBRE_REPLAY + r'''
assert.deepEqual(scroll,['disable']);assert.deepEqual(nativeKeyboard,['disable']);
assert.equal(map.getCanvas().getAttribute('tabindex'),'0');
assert.deepEqual(bindings.map(([event])=>event),['idle','moveend']);
const wheel=new window.WheelEvent('wheel',{deltaY:-120,bubbles:true,cancelable:true});
map.getCanvas().dispatchEvent(wheel);assert.equal(wheel.defaultPrevented,false);assert.deepEqual(zooms,[]);
disposeDebugMapEvidenceControls();assert.equal(runtimeMapLibre.querySelector('.debug-map-evidence-picker'),null);
assert.equal(runtimeMapLibre.dataset.debugKeyboardEvidenceCount,'0');assert.equal(unbound.length,2);
assert.equal(debugPageState.mapEvidenceControlsCleanup,null);
''')


def test_maplibre_empty_or_unready_view_cannot_keep_a_focusable_stale_feature():
    node(controls_replay() + MAPLIBRE_REPLAY + r'''
const target=runtimeMapLibre.querySelector('#debugMapLibreEvidenceTarget');target.focus();assert(hintVisible());
rendered=[];syncDebugMapLibreKeyboardEvidence(renderer);
assert.equal(runtimeMapLibre.dataset.debugKeyboardEvidenceCount,'0');assert.equal(target.disabled,true);
assert.equal(target.closest('.debug-map-evidence-picker').hidden,true);assert.equal(target.debugMapLibreFeature,null);
assert(!hintVisible());target.dispatchEvent(new window.FocusEvent('focusin',{bubbles:true}));assert(!hintVisible());
rendered=[{id:'visible-2'}];syncDebugMapLibreKeyboardEvidence(renderer);
assert.equal(target.disabled,false);assert.equal(target.closest('.debug-map-evidence-picker').hidden,false);
assert.equal(target.dataset.featureId,'visible-2');
map.queryRenderedFeatures=()=>{throw new Error('style not loaded');};syncDebugMapLibreKeyboardEvidence(renderer);
assert.equal(runtimeMapLibre.dataset.debugKeyboardEvidenceCount,'0');assert.equal(target.disabled,true);
''')


def test_map_keyboard_controls_work_without_stealing_dropdown_keys_or_focus():
    node(controls_replay() + MAPLIBRE_REPLAY + r'''
const canvas=map.getCanvas();canvas.focus();
for(const value of ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'])assert(key(canvas,value).defaultPrevented);
assert.deepEqual(pans,[[0,-70],[0,70],[-70,0],[70,0]]);
key(canvas,'b');assert.equal(debugPageState.mapInteractionMode,'box');
key(canvas,'p');assert.equal(debugPageState.mapInteractionMode,'pan');
key(canvas,'+');key(canvas,'-');assert.deepEqual(zooms,[1,-1]);
const select=runtimeMapLibre.querySelector('select');select.focus();
select.dispatchEvent(new window.MouseEvent('pointerdown',{bubbles:true}));
assert.equal(document.activeElement,select,'map activation cannot steal accessible picker focus');
const arrow=key(select,'ArrowDown');assert.equal(arrow.defaultPrevented,false);assert.equal(pans.length,4);
const outside=document.getElementById('fitRoute');outside.focus();
assert.equal(key(outside,'ArrowRight').defaultPrevented,false);assert.equal(pans.length,4);
assert.equal(key(outside,'+').defaultPrevented,false);assert.deepEqual(zooms,[1,-1]);
mapLibre=false;runtimeMap.hidden=false;runtimeMap.focus();activateMapKeyboardPan();
key(runtimeMap,'ArrowRight');assert.equal(pans.length,5);
outside.focus();assert.equal(key(outside,'ArrowRight').defaultPrevented,false);assert.equal(pans.length,5);
''')
