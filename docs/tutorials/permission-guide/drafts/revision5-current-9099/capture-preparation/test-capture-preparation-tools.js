// Offline planning-tool regression only. No browser launch, network, or UI captures.
const fs=require("fs"),vm=require("vm"),assert=require("assert"),path=require("path");
const {JSDOM}=require("jsdom");
const root=__dirname, guide=path.resolve(root,"../../..");
const official=process.env.SCOUT_GUIDE_BASELINE_ROOT;
assert(official&&path.isAbsolute(official),"Set SCOUT_GUIDE_BASELINE_ROOT to the preserved historical guide metadata fixture; it is never a new capture.");
const inspector=fs.readFileSync(path.join(root,"inspect-capture-worklist.js"),"utf8");
const worklist=JSON.parse(fs.readFileSync(path.join(root,"capture-worklist.json"),"utf8"));
const collector=fs.readFileSync(path.join(guide,"drafts/revision5-current-9099/collect-target-rects.js"),"utf8");
const oldCollector=fs.readFileSync(path.join(official,"drafts/revision5-current-9099/collect-target-rects.js"),"utf8");
const source=fs.readFileSync(path.join(guide,"verify-browser.js"),"utf8");
const original=fs.readFileSync(path.join(official,"verify-browser.js"),"utf8");
const draft=JSON.parse(fs.readFileSync(path.join(guide,"drafts/revision5-current-9099/slides.draft.json"),"utf8"));
const historical=JSON.parse(fs.readFileSync(path.join(official,"slides.json"),"utf8"));
const rows=[];
function test(name,fn){try{const evidence=fn();rows.push({name,status:"PASS",evidence});}catch(e){rows.push({name,status:"FAIL",error:String(e),stack:e.stack});}}
function metadata(code,data){
 const end=code.indexOf("fs.mkdirSync(out");
 assert(end>0);
 const context={
  require(name){if(name==="fs")return {readFileSync(){return JSON.stringify(data);}};if(name==="assert")return assert;if(name==="vm")return vm;if(name==="playwright")return {chromium:{launch(){throw Error("Browser launch forbidden in metadata test");}}};throw Error(name);},
  __dirname:"/isolated-static-guide-fixture",process:{argv:["node","verify-browser.js","isolated-out"]}
 };
 vm.runInNewContext(code.slice(0,end)+"\nglobalThis.result={plannedPage,reviewIndex};",context);
 return JSON.parse(JSON.stringify(context.result));
}
test("old verifier rejects actual renamed 38-page draft",()=>{
 assert.throws(()=>metadata(original,draft),/AssertionError/);
 return {observed:"EXPECTED_OLD_FAILURE",deck_pages:draft.slides.length};
});
test("stable IDs resolve actual renamed draft",()=>{const r=metadata(source,draft);assert.deepEqual(r,{plannedPage:8,reviewIndex:16});return r;});
test("stable IDs retain historical guide chapter targets",()=>{assert.deepEqual(metadata(source,historical),metadata(original,historical));});
test("changing display titles does not change chapter targets",()=>{
 const d=structuredClone(draft);d.slides.forEach(s=>s.title="Local title "+s.id);assert.deepEqual(metadata(source,d),{plannedPage:8,reviewIndex:16});
});
test("missing planned-input rejected",()=>{const d=structuredClone(draft);d.slides=d.slides.filter(s=>s.id!=="planned-input");assert.throws(()=>metadata(source,d),/Expected exactly one teaching chapter/);});
test("duplicate planned-input rejected",()=>{const d=structuredClone(draft);d.slides.push(structuredClone(d.slides[7]));assert.throws(()=>metadata(source,d),/Expected exactly one teaching chapter/);});
test("missing planned-review rejected",()=>{const d=structuredClone(draft);d.slides=d.slides.filter(s=>s.id!=="planned-review");assert.throws(()=>metadata(source,d),/Expected exactly one teaching chapter/);});
test("duplicate planned-review rejected",()=>{const d=structuredClone(draft);d.slides.push(structuredClone(d.slides[16]));assert.throws(()=>metadata(source,d),/Expected exactly one teaching chapter/);});
function makeDom(body,url){
 const dom=new JSDOM("<!doctype html><style>*{opacity:1}</style>"+body,{url:url||worklist.pages[0].entry.url,runScripts:"outside-only"});
 const win=dom.window,calls=[];
 for(const key of ["fetch","scroll","scrollTo","scrollBy"]){win[key]=()=>{calls.push(key);throw Error("Mutation/network forbidden");};}
 for(const key of ["click","scrollIntoView"]){win.HTMLElement.prototype[key]=()=>{calls.push(key);throw Error("UI mutation forbidden");};}
 return {dom,win,calls};
}
function box(el,x=10,y=10,width=100,height=25){
 Object.defineProperty(el,"getBoundingClientRect",{configurable:true,value:()=>({x,y,width,height,left:x,top:y,right:x+width,bottom:y+height})});
}
function smallWorklist(){
 return {origin:worklist.origin,workspace:worklist.workspace,pages:[
 {page:1,id:"one",entry:worklist.pages[0].entry,targets:[{step:1,locator:"#a"}]},
 {page:2,id:"two",entry:worklist.pages[0].entry,targets:[{step:1,locator:"#b"}]}
 ],capture_groups:[{id:"same",pages:[1,2]}],supplements:[]};
}
function inspect(fixture,w,options){
 const before=fixture.win.document.documentElement.outerHTML;
 fixture.win.eval(inspector);
 const r=fixture.win.inspectGuideCaptureWorklist(w,options);
 assert.equal(fixture.win.document.documentElement.outerHTML,before);
 assert.deepEqual(fixture.calls,[]);
 assert.equal(r.captured_at,null);assert.equal(r.image_sha256,null);
 return r;
}
test("read-only ready group remains screenshot pending",()=>{
 const f=makeDom('<button id="a">A</button><button id="b">B</button>');try{
 box(f.win.document.querySelector("#a"));box(f.win.document.querySelector("#b"),20,70);
 const r=inspect(f,smallWorklist(),{pages:[1,2]});
 assert.equal(r.status,"DOM_READY_SCREENSHOT_AND_VISUAL_CHECK_PENDING");
 assert.equal(r.shared_image_confirmed,false);assert.equal(r.targets.length,2);assert.equal(r.collector_pages.length,2);
 return {status:r.status,targets:r.targets.length,side_effects:f.calls.length};
 }finally{f.dom.window.close();}
});
test("wrong workspace blocks target inspection",()=>{
 const f=makeDom('<button id="a">A</button>',worklist.pages[0].entry.url.replace(worklist.workspace,"different-project"));
 try{assert.equal(inspect(f,smallWorklist(),{pages:[1]}).status,"NAVIGATION_REQUIRED");}finally{f.dom.window.close();}
});
test("wrong service pathname blocks target inspection",()=>{
 const f=makeDom('<button id="a">A</button>',worklist.pages[0].entry.url.replace("/admin/dashboard","/report"));
 try{assert.equal(inspect(f,smallWorklist(),{pages:[1]}).status,"NAVIGATION_REQUIRED");}finally{f.dom.window.close();}
});
test("closed details gives explicit open step without opening",()=>{
 const f=makeDom('<details><summary>Recorded</summary><button id="a">A</button></details>');
 try{box(f.win.document.querySelector("#a"));const r=inspect(f,smallWorklist(),{pages:[1]});assert(r.pending.some(x=>x.status==="CLOSED_DETAILS"));assert.equal(f.win.document.querySelector("details").open,false);assert.equal(r.open_summaries[0].summary_text,"Recorded");}finally{f.dom.window.close();}
});
test("duplicate target is blocked",()=>{
 const f=makeDom('<button id="a">A</button><button id="a">B</button>');
 try{assert(inspect(f,smallWorklist(),{pages:[1]}).pending.some(x=>x.status==="AMBIGUOUS_TARGET"));}finally{f.dom.window.close();}
});
test("absent conditional target is pending, never skipped",()=>{
 const f=makeDom(""),w=smallWorklist();w.pages[0].targets[0].condition="shown only when real review issue exists";
 try{const r=inspect(f,w,{pages:[1]});assert(r.pending.some(x=>x.status==="TARGET_MISSING"&&x.condition===w.pages[0].targets[0].condition));}finally{f.dom.window.close();}
});
test("completed recovery requires actual recording binding",()=>{
 const f=makeDom('<button id="a">A</button>'),w=smallWorklist();w.pages[0].targets[0].locator_template='[data-record="{{completed_recording_id}}"]';
 try{const r=inspect(f,w,{pages:[1]});assert(r.pending.some(x=>x.status==="REAL_BINDING_REQUIRED"));}finally{f.dom.window.close();}
});
test("completed recording binding handles quoted IDs literally",()=>{
 const f=makeDom('<button id="a">A</button>'),w=smallWorklist();w.pages[0].targets[0].locator_template='[data-record="{{completed_recording_id}}"]';
 try{const id='record"quote\\slash',el=f.win.document.querySelector("#a");el.setAttribute("data-record",id);box(el);
 const r=inspect(f,w,{pages:[1],bindings:{completed_recording_id:id}});assert.equal(r.status,"DOM_READY_SCREENSHOT_AND_VISUAL_CHECK_PENDING");assert.equal(r.targets.length,1);}finally{f.dom.window.close();}
});
test("main and weather cannot share capture",()=>{
 const f=makeDom("");try{assert.equal(inspect(f,worklist,{pages:[35,37]}).status,"SEPARATE_CAPTURES_REQUIRED");}finally{f.dom.window.close();}
});
function withFrame(project){
 const f=makeDom('<iframe id="frame"></iframe>');
 const child=makeDom('<button id="a">A</button>',worklist.origin+"/admin/pretrip?projectId="+project);
 const frame=f.win.document.querySelector("#frame");
 Object.defineProperty(frame,"contentDocument",{value:child.win.document});
 Object.defineProperty(frame,"clientLeft",{value:2});Object.defineProperty(frame,"clientTop",{value:3});
 box(frame,30,50,300,200);box(child.win.document.querySelector("#a"),10,20,80,25);
 const w=smallWorklist();w.pages[0].entry={...w.pages[0].entry,frame_selector:"#frame"};w.pages[0].frame_selector="#frame";
 return {f,child,w};
}
test("mismatched iframe project cannot produce ready receipt",()=>{
 const {f,child,w}=withFrame("different-project");try{assert.equal(inspect(f,w,{pages:[1]}).status,"FRAME_WORKSPACE_OR_ORIGIN_MISMATCH");}finally{child.dom.window.close();f.dom.window.close();}
});
test("original collector omits iframe border in top coordinates",()=>{
 const {f,child,w}=withFrame(worklist.workspace);try{
 f.win.eval(oldCollector);const r=f.win.collectGuideTargetRects(w.pages[0]);
 assert.equal(r.targets[0].top_rect_css.x,40);assert.equal(r.targets[0].top_rect_css.y,70);
 assert.notEqual(r.targets[0].top_rect_css.x,42);
 return {observed:"EXPECTED_OLD_OFFSET_ERROR",old:r.targets[0].top_rect_css,expected_x:42,expected_y:73};
 }finally{child.dom.window.close();f.dom.window.close();}
});
test("collector and inspector include iframe borders without writes",()=>{
 const {f,child,w}=withFrame(worklist.workspace);try{
 f.win.eval(collector);const r=f.win.collectGuideTargetRects(w.pages[0]),i=inspect(f,w,{pages:[1]});
 assert.equal(r.targets[0].top_rect_css.x,42);assert.equal(r.targets[0].top_rect_css.y,73);
 assert.deepEqual(JSON.parse(JSON.stringify(r.targets[0].top_rect_css)),JSON.parse(JSON.stringify(i.targets[0].top_rect_css)));
 assert.deepEqual(f.calls,[]);assert.deepEqual(child.calls,[]);
 return {top_rect_css:r.targets[0].top_rect_css,side_effects:0};
 }finally{child.dom.window.close();f.dom.window.close();}
});
test("offscreen targets never become capture ready",()=>{
 const f=makeDom('<button id="a">A</button>');try{
 box(f.win.document.querySelector("#a"),10,1500);const r=inspect(f,smallWorklist(),{pages:[1]});
 assert(r.pending.some(x=>x.status==="SCROLL_OR_SEPARATE_VIEW_REQUIRED"));
 }finally{f.dom.window.close();}
});
test("all worklist target and preparation selector syntax parses",()=>{
 const f=makeDom("");let checked=0;try{
 for(const page of [...worklist.pages,...worklist.supplements]){
  for(const item of [...page.targets,...page.prepare_actions]){
   for(const locator of [item.locator,...(item.locators||[])].filter(Boolean)){
    f.win.document.querySelectorAll(locator);checked++;
   }
  }
 }return {selectors_parsed:checked,scope:"syntax only; no live target availability"};}finally{f.dom.window.close();}
});
const summary={scope:"isolated offline planning tools; no live browser, no UI captures, no PDF/layout qualification",counts:{tests:rows.length,pass:rows.filter(r=>r.status==="PASS").length,fail:rows.filter(r=>r.status==="FAIL").length},network_requests:0,browser_launches:0,rows};
if(process.env.SCOUT_GUIDE_TOOL_TEST_REPORT)fs.writeFileSync(process.env.SCOUT_GUIDE_TOOL_TEST_REPORT,JSON.stringify(summary,null,2)+"\n");
console.log(JSON.stringify(summary,null,2));if(summary.counts.fail)process.exitCode=1;
