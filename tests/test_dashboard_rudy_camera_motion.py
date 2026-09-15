"""D037 camera stop replays with public API receipts; no live qualification."""
import json

import pytest

from test_dashboard_rudy_live_diagnostic import BASE, node
from test_dashboard_rudy_request_lifecycle import CLOCK


@pytest.mark.parametrize("direction", ["left", "right", "up", "down"])
def test_vendored_keyboard_with_modeled_camera_finishes_before_action_returns(direction):
    node(BASE + CLOCK + r"""
(async()=>{
const {JSDOM}=require('jsdom'),{pathToFileURL}=require('node:url'),path=require('node:path');
const {KeyboardHandler}=await import(pathToFileURL(path.join(path.dirname(process.argv[2]),'vendor/maplibre-gl/6.2.0/maplibre-gl.mjs')));
const dom=new JSDOM('<section data-navigation-maplibre-shell="2d"><div id="host"><canvas tabindex="0"></canvas></div></section>',{url:base});
const handler=new KeyboardHandler(null,{zoom:19,bearing:0,pitch:0,center:[121,23]});
let animation;
const map={easeTo(options){animation={...options,startedAt:time}},isMoving(){return time<animation.startedAt+animation.duration},
 isEasing(){return this.isMoving()},offset(){return animation.offset.map(value=>value*animation.easing(Math.min(1,(time-animation.startedAt)/animation.duration)))}};
dom.window.document.querySelector('canvas').addEventListener('keydown',event=>handler.keydown(event).cameraAnimation(map));
const cameraDescriptor=api.descriptorFor({kind:'navigation',renderer:'maplibre',root:dom.window.document.querySelector('#host'),doc:dom.window.document,map,projectId:()=>project});
const evidence=await api.act(cameraDescriptor,DIRECTION);
assert.equal(animation.duration,300);assert.equal(evidence.status,'stopped');
assert.equal(evidence.observations[0].observedAt,240);assert.equal(evidence.observations[0].moving,true);
assert.equal(evidence.observations.at(-1).moving,false);assert.equal(evidence.observations.at(-1).easing,false);
assert.ok(evidence.completedAt>=300);assert.equal(evidence.observations.length,2);
const unavailable={view:JSON.stringify(map.offset())};time+=100;
assert.equal(JSON.stringify(map.offset()),unavailable.view,'The exact camera predicate must not compare two animation instants');
assert.ok(evidence.observations.every(row=>row.basis==='maplibre-public-api'&&row.available));
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("DIRECTION", json.dumps(direction)))


@pytest.mark.parametrize("duration", [0, 900, 1800])
def test_motion_wait_uses_actual_state_and_not_a_larger_fixed_sleep(duration):
    node(BASE + CLOCK + r"""
const duration=DURATION;let stopAt=0;
const cameraDescriptor={renderer:'maplibre',act(){stopAt=time+duration},cameraMotion(){return {
 observedAt:time,basis:'maplibre-public-api',available:true,moving:time<stopAt,easing:time<stopAt}}};
(async()=>{
 const evidence=await api.act(cameraDescriptor,'right');
 assert.equal(evidence.status,'stopped');assert.ok(time>=duration);assert.ok(time<Math.max(240,duration)+150);
 assert.equal(time,duration===0?240:duration===900?990:1890);
 assert.equal(evidence.observations.at(-1).moving,false);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("DURATION", str(duration)))


@pytest.mark.parametrize("kind", ["pretrip", "debug"])
def test_canonical_descriptor_reads_current_bridge_receipts_without_cached_fallback(kind):
    node(BASE + CLOCK + r"""
const {JSDOM}=require('jsdom'),kind=KIND;
const dom=new JSDOM('<div id="mapRendererShell"><div id="map"></div></div><div id="runtimeMapRendererShell"></div>',{url:base});
let available=true,moving=true;
const cameraDescriptor=api.descriptorFor({kind,renderer:'maplibre',root:dom.window.document.querySelector('#map'),doc:dom.window.document,
 cameraMotion:()=>({observedAt:time,basis:'maplibre-public-api',available,moving:available?moving:null,easing:available?moving:null})});
assert.equal(cameraDescriptor.cameraMotion().moving,true);moving=false;
assert.equal(cameraDescriptor.cameraMotion().moving,false);available=false;
assert.equal(cameraDescriptor.cameraMotion().available,false);assert.equal(cameraDescriptor.cameraMotion().moving,null);
dom.window.close();replayFinished=true;
""".replace("KIND", json.dumps(kind)))


@pytest.mark.parametrize("scenario", ["missing", "missing-method", "non-boolean", "throw", "invalid-bridge", "unavailable-bridge"])
def test_unknown_motion_is_recorded_and_cannot_pass(scenario):
    node(BASE + CLOCK + r"""
const {JSDOM}=require('jsdom'),scenario=SCENARIO;
const dom=new JSDOM('<section data-navigation-maplibre-shell><div id="host"></div></section>',{url:base});
const config={kind:'navigation',renderer:'maplibre',root:dom.window.document.querySelector('#host'),doc:dom.window.document};
if(scenario==='missing-method')config.map={isEasing:()=>false};
if(scenario==='non-boolean')config.map={isMoving:()=>undefined,isEasing:()=>false};
if(scenario==='throw')config.map={isMoving(){throw new TypeError('fixture detached map')},isEasing:()=>false};
if(scenario==='invalid-bridge')config.cameraMotion=()=>({basis:'maplibre-public-api',available:true,moving:'false',easing:false});
if(scenario==='unavailable-bridge')config.cameraMotion=()=>({basis:'maplibre-public-api',available:false,moving:false,easing:false});
const cameraDescriptor=api.descriptorFor(config);cameraDescriptor.act=()=>{};
(async()=>{
 await assert.rejects(api.act(cameraDescriptor,'right'),error=>{
  assert.match(error.message,/motion is unverified/);assert.equal(error.cameraMotionEvidence.status,'warning');
  const observed=error.cameraMotionEvidence.observations[0];assert.equal(observed.available,false);
  assert.equal(observed.moving,null);assert.equal(observed.easing,null);assert.equal(error.waitEvidence.timeoutMs,60000);return true;
 });
 dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("SCENARIO", json.dumps(scenario)))


def test_easing_or_moving_remains_blocking_and_preserves_original_wait_deadline():
    node(BASE + CLOCK + r"""
const cameraDescriptor={renderer:'maplibre',act(){},cameraMotion:()=>({observedAt:time,basis:'maplibre-public-api',
 available:true,moving:false,easing:true})};
(async()=>{
 await assert.rejects(api.act(cameraDescriptor,'right'),error=>{
  assert.equal(error.waitEvidence.timeoutMs,60000);assert.equal(error.waitEvidence.elapsedMs,60000);
  assert.equal(error.cameraMotionEvidence.status,'warning');assert.equal(error.cameraMotionEvidence.observations.length,400);
  assert.ok(error.cameraMotionEvidence.observations.every(row=>row.easing===true));return true;
 });
 assert.equal(time,60240);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")


def test_case_keeps_action_motion_receipt_with_unchanged_native_acceptance():
    node(BASE + CLOCK + r"""
let movingUntil=0;
const cameraDescriptor={...descriptor,renderer:'maplibre',snapshot:()=>({...descriptor.snapshot(),activeRenderer:'maplibre'}),
 cameraMotion:()=>({observedAt:time,basis:'maplibre-public-api',available:true,moving:time<movingUntil,easing:time<movingUntil}),
 act(action){if(action==='plus')throw Error('fixture stops after fit motion receipt');movingUntil=time+300}};
(async()=>{
 const result=await api.runCase({key:'map/maplibre/default',renderer:'maplibre'},{projectId:project,
  open:async()=>({descriptor:cameraDescriptor,close:async()=>({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]})})});
 assert.deepEqual(result.stages.slice(0,3).map(stage=>stage.status),['passed','passed','passed']);
 assert.equal(result.stages[3].status,'warning');assert.match(result.stages[3].detail,/fixture stops/);
 assert.equal(result.actionEvidence.length,1);const action=result.actionEvidence[0];
 assert.equal(action.stage,'fit');assert.equal(action.action,'fit');assert.equal(action.status,'stopped');
 assert.equal(action.observations[0].moving,true);assert.equal(action.observations.at(-1).moving,false);
 assert.equal(api.STAGES.length,10);assert.equal(result.stages.length,10);assert.equal(result.cleanupStatus,'passed');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")
