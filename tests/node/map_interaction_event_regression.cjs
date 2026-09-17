// The exported vendored handlers are unchanged. Camera projection is a bounded
// seam; no WebGL, tiles, workspace writes or browser qualification is claimed.
const fs=require('node:fs'),assert=require('node:assert/strict'),{pathToFileURL}=require('node:url'),{JSDOM}=require('jsdom');
(async()=>{
const dom=new JSDOM('<body><main id="host"><div id="surface"><canvas tabindex="0"></canvas></div></main><button id="pan">Pan</button><button id="box">Box</button></body>',{pretendToBeVisual:true,url:'http://localhost'});
const {window}=dom,document=window.document;
global.window=global.self=window;global.document=document;global.navigator=window.navigator;
const win=window,host=document.getElementById('host'),viewport=host.querySelector('canvas'),canvas=viewport;
const element=document.getElementById('surface'),pan=document.getElementById('pan'),box=document.getElementById('box');
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:800,height:500,right:800,bottom:500});
for(const node of [canvas,element,host]){Object.defineProperty(node,'offsetWidth',{value:800});Object.defineProperty(node,'offsetHeight',{value:500});}
window.fetch=()=>{throw Error('No network in event replay')};
class PointerContract extends window.MouseEvent {
 constructor(type,options={}){super(type,options);Object.defineProperty(this,'pointerId',{value:options.pointerId??0});Object.defineProperty(this,'isPrimary',{value:options.isPrimary??false});}
}
window.PointerEvent=PointerContract;
const {QaHandlerManager,QaMousePanHandler}=await import(pathToFileURL(__MODULE__));
const map={getCanvas:()=>canvas,getCanvasContainer:()=>element,getContainer:()=>host,fire(){},
 getZoom:()=>camera.zoom,getMaxZoom:()=>20,getBearing:()=>0,getPitch:()=>0,
 unproject:([x,y])=>({lng:121+x*.0001,lat:23.5+y*.0001}),easeTo(options){camera.zoom=options.zoom;},
 boxZoom:{disable(){}},dragPan:{enable(){manager._handlersById.mousePan.enable();},disable(){manager._handlersById.mousePan.disable();}}};
const camera={zoom:12};
QaHandlerManager.prototype._addDefaultHandlers=function(){this._add('mousePan',QaMousePanHandler({enable:true,clickTolerance:1}));};
QaHandlerManager.prototype._triggerRenderFrame=function(){};
const manager=new QaHandlerManager(map,{stop(){}},{bearingSnap:7});
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const extract=name=>html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }','m'))[0];
const configure=eval('('+extract('configureNavigationTerrainBoxInteraction')+')');
const controls=configure({host,map},pan,box);
const adapter={gestureTarget:kind=>kind==='box'?host.querySelector('.scout-maplibre-box-capture'):canvas};
const surface={id:'navigation-map',renderer:'maplibre'},settle=async()=>{},diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
const source=extract('diagnosticExerciseMapInteractionDom');
const declarations=['dispatchPointer','gesture'].map(name=>{
 const matches=[...source.matchAll(new RegExp('^      const '+name+' = [\\s\\S]*?^      };','gm'))];
 assert.equal(matches.length,1,'Production '+name+' declaration must remain uniquely inspectable');
 return matches[0][0];
});
const exercise=new Function('win','doc','viewport','adapter','surface','settle','diagnosticRequire','key',declarations.join('\n')+'\nreturn gesture;');
const key=async value=>canvas.dispatchEvent(new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
const gesture=exercise(win,document,canvas,adapter,surface,settle,diagnosticRequire,key);
const kind=__KIND__;
try {
 if(kind==='pan') {
  await gesture('pan');
  const deltas=manager._changes.map(row=>row[0].panDelta).filter(Boolean);
  assert.ok(deltas.length>0,'The actual vendored owner-document listener never received mousemove');
  assert.ok(deltas.some(value=>Math.abs(value.x)>0&&Math.abs(value.y)>0));
 } else {
  box.click();const before=camera.zoom;
  await gesture('box',kind==='box-reverse');
  assert.ok(camera.zoom>before,'The actual Navigation primary-pointer guard rejected the probe');
  assert.equal(host.dataset.navigationBoxZoomResult,'zoom-in');
  assert.equal(host.dataset.mapInteractionMode,'box');
  assert.equal(host.querySelector('.scout-maplibre-box-selection').hidden,true);
 }
} finally {controls.dispose();manager.destroy();window.close();}
})().catch(error=>{console.error(error);process.exitCode=1});

