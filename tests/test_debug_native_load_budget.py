"""Native image budget starts after synchronous DOM work; no browser qualification."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase-3-5-runtime-debug.html"
SCRIPT = r"""const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const filename=process.argv[1],html=fs.readFileSync(filename,'utf8');
function fn(name){const m=html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }','m'));return m?.[0];}
const isCandidate=process.argv[2]!=='restore-early-budget';
const src=fn('stageDebugRudyTiles')+'\n'+(isCandidate?fn('withDebugMapDomUpdate'):'function withDebugMapDomUpdate(update){return update();}');
function fixture(){
 let now=0,nextTimer=1,status=null;
 const timers=new Map(),trace=[],state={mapLibreDisposed:false},tiles=[{z:12,x:3423,y:1771,href:'native-exact/12/3423/1771'},{z:12,x:3423,y:1772,href:'native-exact/12/3423/1772'}];
 class Element{
  constructor(tag,attrs={}){this.tag=tag;this.attrs={...attrs};this.dataset={};this.children=[];this.parentNode=null;this.events={};}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='href')trace.push({event:'href-start',time:now,href:String(v)});}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  appendChild(n){n.remove();this.children.push(n);n.parentNode=this;return n;}
  replaceChildren(...ns){for(const c of [...this.children])c.remove();for(const n of ns)this.appendChild(n);}
  remove(){if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}}
  contains(n){return n===this||this.children.some(c=>c.contains(n));}
  querySelectorAll(sel){return this.children.flatMap(c=>[...(c.tag===sel?[c]:[]),...c.querySelectorAll(sel)]);}
  fire(name){this.events[name]?.();}
 }
 const root=new Element('svg'),group=new Element('g');root.appendChild(group);
 const context={debugPageState:state,runtimeMap:root,Map,RUDY_TILE_SWAP_TIMEOUT_MS:12000,svgEl:(t,a)=>new Element(t,a),
  positionTileImage(){},rasterLayerFor:()=>({}),debugRudyViewportBounds:()=>({west:120,east:122,south:23,north:24}),
  rasterTileCoverage:()=>tiles,chooseRasterZoom:()=>12,updateDebugRudyTileStatus:s=>{status=s;trace.push({event:'status',time:now,state:s.state,reason:s.reason});},
  setTimeout:(fn,ms)=>{const id=nextTimer++;timers.set(id,{fn,at:now+ms});trace.push({event:'timer-start',time:now,budgetMs:ms,deadline:now+ms});return id;},
  clearTimeout:id=>timers.delete(id)
 };
 vm.createContext(context);vm.runInContext(src,context);
 return{context,state,root,group,trace,timers,now:()=>now,status:()=>status,advance:ms=>{now+=ms;},
  drain:()=>{for(const[id,t]of[...timers])if(t.at<=now){timers.delete(id);t.fn();}},
  stage:()=>context.stageDebugRudyTiles(group,{},{}),
  images:()=>group.children.find(c=>c.attrs['data-tile-generation']==='pending')?.children||[],
  update:fn=>context.withDebugMapDomUpdate(fn)};
}
if(!isCandidate){
 const f=fixture();let queuedImages;
 f.update(()=>{f.stage();queuedImages=[...f.images()];f.advance(13000);});
 f.drain();for(const image of queuedImages)image.fire('load');
 assert.equal(f.status().reason,'native_tiles_timeout');
 assert.equal(f.status().success_count,0);
 assert.equal(f.images().length,0);
 console.log(JSON.stringify({status:'OLD_DOM_WORK_CONSUMES_NATIVE_LOAD_BUDGET_REPRODUCED',source:filename,trace:f.trace,final:f.status(),scope:'controlled 13s DOM work then due timer task before queued image load callbacks; not a claim that Chrome used this exact task ordering'},null,2));
 process.exit(0);
}
const results=[];
const f=fixture();
f.update(()=>{f.stage();f.advance(13000);}); // Controlled synchronous vector/label work, not a profile-derived CPU claim.
assert.equal(f.trace.find(e=>e.event==='href-start')?.time,13000,'Native requests started before synchronous vector DOM work completed');
assert.equal(f.trace.find(e=>e.event==='timer-start')?.budgetMs,12000,'Original native tile load budget must remain 12s');
f.drain();assert.equal(f.status().state,'loading','Completed DOM work must not consume image load budget');
f.advance(11999);for(const image of f.images())image.fire('load');assert.equal(f.status().state,'available');
results.push({name:'controlled-13s-DOM-then-native-load',trace:f.trace});
const timeout=fixture();timeout.update(()=>{timeout.stage();timeout.advance(13000);});timeout.advance(12000);timeout.drain();
assert.equal(timeout.status().reason,'native_tiles_timeout');assert.equal(timeout.images().length,0);
results.push({name:'12s-native-failure-still-rejected',trace:timeout.trace});
const nested=fixture();nested.update(()=>{nested.stage();nested.update(()=>nested.stage());assert.equal(nested.timers.size,0);});
assert.equal(nested.trace.filter(e=>e.event==='timer-start').length,1);assert.equal(nested.timers.size,1);
const failed=fixture();assert.throws(()=>failed.update(()=>{failed.stage();throw new Error('DOM submission failed');}),/DOM submission failed/);
assert.equal(failed.timers.size,0);assert.equal(failed.trace.some(e=>e.event==='href-start'),false);assert.equal(failed.state.deferredRudyStages,null);
const removed=fixture();removed.update(()=>{removed.stage();removed.group.remove();});assert.equal(removed.timers.size,0);
const recover=fixture();
recover.update(()=>{recover.stage();try{recover.update(()=>{recover.stage();throw new Error('nested DOM failure');});}catch(e){assert.match(e.message,/nested DOM failure/);}});
assert.equal(recover.timers.size,0);assert.equal(recover.state.deferredRudyStages,null);assert.equal(recover.state.mapDomUpdateDepth,0);
recover.update(()=>recover.stage());assert.equal(recover.timers.size,1);
for(const image of recover.images())image.fire('load');assert.equal(recover.status().state,'available');

const disposed=fixture();disposed.update(()=>{disposed.stage();disposed.state.mapLibreDisposed=true;});assert.equal(disposed.timers.size,0);
const direct=fixture();direct.stage();assert.equal(direct.trace.find(e=>e.event==='href-start').time,0);
console.log(JSON.stringify({status:'CONTROLLED_NATIVE_DEADLINE_REPLAY_PASS',source:filename,isCandidate,cases:9,results,scope:'actual stage and DOM-batch helper; controlled two-tile event-order fixture, not live network/decode evidence'},null,2));

"""

@pytest.mark.parametrize("restore_early_budget", [False, True])
def test_debug_native_budget_excludes_dom_submission_and_preserves_real_timeout(restore_early_budget):
    node = shutil.which("node")
    assert node, "Node is required for actual Debug native-cohort source replay"
    args = [node, "-e", SCRIPT, str(PAGE)]
    if restore_early_budget:
        args.append("restore-early-budget")
    result = subprocess.run(args, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    expected = "OLD_DOM_WORK_CONSUMES_NATIVE_LOAD_BUDGET_REPRODUCED" if restore_early_budget else "CONTROLLED_NATIVE_DEADLINE_REPLAY_PASS"
    assert receipt["status"] == expected
    if not restore_early_budget:
        assert receipt["cases"] == 9
