"""Actual DOM bindings expose only active MapLibre evidence, without moving its view."""

from pathlib import Path
import json
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PRETRIP = ROOT / "docs/admin/phase4-pretrip-planning.html"
NAVIGATION = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _functions(page: Path, *names: str) -> str:
    source = page.read_text()
    result = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source)
        assert match, name
        result.append(match.group())
    return "\n".join(result)


def _node(source: str) -> None:
    result = subprocess.run(["node"], input=source, capture_output=True, text=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def _pretrip() -> str:
    return r'''
const assert = require('node:assert/strict'), {JSDOM} = require('jsdom');
const dom = new JSDOM('<body><svg id="map" hidden></svg><div id="mapLibreEvidenceMap"><canvas tabindex="0"></canvas></div><div id="hoverHint" class="is-hidden"></div></body>');
const window = dom.window, document = window.document;
window.ScoutMapLibreEvidence = {sourceId:'scout-evidence'};
const host = document.getElementById('mapLibreEvidenceMap'), hoverHint = document.getElementById('hoverHint');
const features = new Map([
 ['visible-1',{id:'visible-1',geometry:{type:'Point',coordinates:[121,23]},properties:{identity_key:'visible-1',source_id:'checkpoint-1',display_label:'Live checkpoint',evidence_type:'checkpoint'}}],
 ['visible-2',{id:'visible-2',geometry:{type:'LineString',coordinates:[[121,23],[121.1,23.1]]},properties:{identity_key:'visible-2',source_id:'route-1',display_label:'Live route',evidence_type:'route'}}],
 ['hidden-only',{id:'hidden-only',geometry:{type:'Point'},properties:{identity_key:'hidden-only',display_label:'Hidden evidence'}}],
]);
let rendered = ['visible-1','visible-1','visible-2'].map(id=>({id,source:'scout-evidence'}));
const focused=[], selected=[], bindings=[], unbound=[];
const map={queryRenderedFeatures:()=>rendered,on:(event,fn)=>bindings.push([event,fn]),off:(event,fn)=>unbound.push([event,fn])};
const renderer={map,index:{feature:id=>features.get(String(id))},focus:(id,options)=>focused.push({id,options})};
const state={mapRenderer:{active:'maplibre'},mapLibreRenderer:renderer};
const pretripEvidenceForMapLibreFeature=()=>null, selectPretripMapLibreFeature=feature=>selected.push(feature.id);
const hintTitle=item=>item.display_label || 'evidence', hintSummary=item=>item.evidence_type || 'candidate evidence';
const moveHint=()=>{}, hideHint=()=>hoverHint.classList.add('is-hidden');
const visible=()=>!hoverHint.classList.contains('is-hidden');
const key=(node,value)=>{const event=new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true});node.dispatchEvent(event);return event;};
''' + _functions(PRETRIP, "disposePretripMapEvidenceControls", "configurePretripMapEvidenceControls", "syncPretripMapKeyboardEvidence") + r'''
configurePretripMapEvidenceControls(renderer);
'''


def test_pretrip_actual_picker_pointer_focus_selection_escape_and_blur() -> None:
    _node(_pretrip() + r'''
const picker=host.querySelector('.pretrip-map-evidence-picker'), target=picker.querySelector('button'), select=picker.querySelector('select');
assert.equal(target.tabIndex,0);assert.equal(target.dataset.mapRef,'checkpoint-1');
assert.equal(host.dataset.mapKeyboardEvidenceCount,'2');assert.equal(select.options.length,2);
assert(![...select.options].some(option=>option.value==='hidden-only'));
target.dispatchEvent(new window.MouseEvent('mouseenter',{clientX:20,clientY:20}));assert(visible());
assert.equal(hoverHint.querySelector('strong').textContent,'Live checkpoint');
assert.equal(hoverHint.querySelector('span').textContent,'checkpoint');
target.dispatchEvent(new window.MouseEvent('mouseleave'));assert(!visible());
target.focus();assert.equal(document.activeElement,target);assert(visible());
assert.deepEqual(focused.at(-1),{id:'visible-1',options:{fit:false}});
target.click();assert.deepEqual(selected,['visible-1']);
assert(key(target,'Escape').defaultPrevented);assert(!visible());
target.blur();target.focus();assert(visible());target.blur();assert(!visible());
select.value='visible-2';select.dispatchEvent(new window.Event('change'));target.focus();
assert.equal(target.dataset.mapFeatureKind,'linestring');assert.equal(target.dataset.mapRef,'route-1');
assert.deepEqual(focused.at(-1),{id:'visible-2',options:{fit:false}});
assert.equal(hoverHint.querySelector('strong').textContent,'Live route');
features.get('visible-2').properties.display_label='<img src=x onerror=alert(1)> source label';
target.blur();target.focus();assert.equal(hoverHint.querySelector('img'),null);
assert.match(hoverHint.querySelector('strong').textContent,/<img/);
''')


def test_pretrip_empty_failed_wrong_source_or_disposed_view_cannot_keep_stale_target() -> None:
    _node(_pretrip() + r'''
const target=host.querySelector('button');target.focus();assert(visible());
rendered=[{id:'hidden-only',source:'unrelated-source'}];syncPretripMapKeyboardEvidence(renderer);
assert.equal(host.dataset.mapKeyboardEvidenceCount,'0');assert(target.disabled);assert(target.closest('div').hidden);
assert.equal(target.pretripMapLibreFeature,null);assert(!visible());
target.dispatchEvent(new window.FocusEvent('focus'));assert(!visible());target.click();assert.deepEqual(selected,[]);
rendered=[{id:'visible-2',source:'scout-evidence'}];syncPretripMapKeyboardEvidence(renderer);assert(!target.disabled);
map.queryRenderedFeatures=()=>{throw new Error('style unavailable');};syncPretripMapKeyboardEvidence(renderer);assert(target.disabled);
disposePretripMapEvidenceControls();assert.equal(host.querySelector('button'),null);assert.equal(unbound.length,2);
assert.equal(state.mapEvidenceControlsCleanup,null);assert.equal(host.dataset.mapKeyboardEvidenceCount,'0');
''')


def test_pretrip_svg_existing_evidence_closes_hint_on_escape() -> None:
    _node(r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const {window}=new JSDOM('<body><svg><circle r="5"></circle></svg></body>');
const document=window.document,node=document.querySelector('circle');
let visible=false;
const evidenceSourceId=item=>item.source_id,showHint=()=>{visible=true;},hideHint=()=>{visible=false;};
const moveHint=()=>{},selectEvidence=()=>{},focusMapFor=()=>{};
''' + _functions(PRETRIP, "attachEvidence") + r'''
attachEvidence(node,{source_id:'actual-svg-source',evidence_type:'checkpoint'});
node.focus();assert(visible);assert.equal(node.tabIndex,0);
const event=new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});node.dispatchEvent(event);
assert(event.defaultPrevented);assert(!visible);node.blur();node.focus();assert(visible);node.blur();assert(!visible);
''')


def _navigation(mode: str = "2d", lens: str = "events") -> str:
    return r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><div id="map"><canvas tabindex="0"></canvas></div><div id="dashboardMapHoverHint" hidden><strong></strong><span></span></div></body>');
const window=dom.window,document=window.document,host=document.getElementById('map');
const hints=document.getElementById('dashboardMapHoverHint');
const features=[{id:'visible-1',source:'terrain-'+LENS,layer:{id:'scout-terrain-events'},
 geometry:{type:'Point',coordinates:[121,23]},properties:{id:'visible-1',event_id:'event-1',label:'Rendered '+LENS,feature_class:'terrain_event_location'}},
 {id:'visible-route',source:'golden-route',layer:{id:'scout-golden-route'},
 geometry:{type:'LineString',coordinates:[[121,23],[121.1,23.1]]},properties:{id:'visible-route',label:'Golden GPX'}}];
let rendered=[features[0],features[0],features[1]];
const bindings=[],unbound=[],sources=new Map(),layers=[],selected=[];
let panEnabled=false;
const camera={zoom:MODE==='3d'?16:13,pitch:MODE==='3d'?58:0,center:[121,23]},before=JSON.stringify(camera);
const map={queryRenderedFeatures:()=>rendered,getCanvas:()=>host.querySelector('canvas'),
 getSource:id=>sources.get(id),addSource:(id,definition)=>sources.set(id,{...definition,setData(data){this.data=data;}}),
 addLayer:layer=>layers.push(layer),on:(event,fn)=>bindings.push([event,fn]),off:(event,fn)=>unbound.push([event,fn]),
 dragPan:{enable:()=>{panEnabled=true;}}};
const entry={host,map,mode:MODE,selectEvidenceFeature:feature=>selected.push(feature.id)};
const key=(node,value)=>{const event=new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true});node.dispatchEvent(event);return event;};
''' .replace("LENS", json.dumps(lens)).replace("MODE", json.dumps(mode)) + _functions(
        NAVIGATION, "dashboardMapHintNode", "positionDashboardMapHint", "showDashboardMapHint", "hideDashboardMapHint",
        "navigationTerrainRenderedKeyboardFeatures", "highlightNavigationTerrainKeyboardFeature",
        "syncNavigationTerrainKeyboardEvidence", "configureNavigationTerrainEvidenceControls",
    ) + r'''
configureNavigationTerrainEvidenceControls(entry);
'''


@pytest.mark.parametrize("mode", ["2d", "3d"])
@pytest.mark.parametrize("lens", ["events", "structure", "pressure", "risk", "hierarchy"])
def test_navigation_pan_and_visible_canvas_evidence_dom_for_every_lens(mode: str, lens: str) -> None:
    _node(_navigation(mode, lens) + r'''
const pan=host.querySelector('[data-navigation-map-control="pan"]'),canvas=map.getCanvas();
assert(panEnabled);assert.equal(host.dataset.mapInteractionMode,'pan');
panEnabled=false;pan.click();assert(panEnabled);assert.equal(document.activeElement,canvas);
panEnabled=false;assert(key(canvas,'p').defaultPrevented);assert(panEnabled);
const picker=host.querySelector('.navigation-map-evidence-picker'),select=picker.querySelector('select'),target=picker.querySelector('button');
assert.equal(host.dataset.mapKeyboardEvidenceCount,'2');assert.equal(select.options.length,2);
select.value=[...select.options].find(option=>option.textContent.startsWith('Rendered')).value;select.dispatchEvent(new window.Event('change'));
assert.equal(target.tabIndex,0);assert.equal(target.dataset.mapRendererEvidence,'maplibre');
target.dispatchEvent(new window.MouseEvent('pointermove',{clientX:20,clientY:20}));assert(!hints.hidden);
assert.match(hints.querySelector('strong').textContent,/Rendered/);assert(hints.querySelector('span').textContent.includes('候選'));
host.dispatchEvent(new window.MouseEvent('pointerleave'));assert(hints.hidden);
target.focus();assert(!hints.hidden);assert.equal(document.activeElement,target);
assert.deepEqual(sources.get('scout-keyboard-evidence-focus').data.features[0].geometry,features[0].geometry);
assert.equal(sources.get('scout-keyboard-evidence-focus').data.features[0].properties.runtime_safety_truth,false);
target.click();assert.deepEqual(selected,['visible-1']);
assert(key(target,'Escape').defaultPrevented);assert(hints.hidden);assert.equal(sources.get('scout-keyboard-evidence-focus').data.features.length,0);
target.blur();target.focus();assert(!hints.hidden);target.blur();assert(hints.hidden);
panEnabled=false;select.focus();assert(!key(select,'p').defaultPrevented);assert(!panEnabled);
assert.equal(JSON.stringify(camera),before,'evidence focus cannot move the view or pitch');
''')


def test_navigation_empty_failed_offscreen_and_highlight_sources_do_not_claim_evidence() -> None:
    _node(_navigation() + r'''
const picker=host.querySelector('.navigation-map-evidence-picker'),target=picker.querySelector('button');
target.focus();assert(!hints.hidden);
rendered=[{...features[0],source:'scout-keyboard-evidence-focus'}];syncNavigationTerrainKeyboardEvidence(entry);
assert.equal(host.dataset.mapKeyboardEvidenceCount,'0');assert(picker.hidden);assert(target.disabled);
assert.equal(target.navigationMapLibreFeature,null);assert.equal(target.dataset.dashboardMapHintTitle,undefined);assert(hints.hidden);
target.dispatchEvent(new window.FocusEvent('focus'));assert(hints.hidden);target.click();assert.deepEqual(selected,[]);
rendered=[features[0]];syncNavigationTerrainKeyboardEvidence(entry);assert(!picker.hidden);assert(!target.disabled);
map.queryRenderedFeatures=()=>{throw new Error('style pending');};syncNavigationTerrainKeyboardEvidence(entry);assert(picker.hidden);
entry.evidenceControlsCleanup();assert.equal(host.querySelector('button'),null);assert.equal(unbound.length,2);
assert.equal(entry.disposed,true);assert(hints.hidden);
''')
