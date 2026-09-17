/* Real pinned Map camera/HandlerManager replay. GPU painter only is stubbed.
 * No WebGL rendering or tile qualification; no network, Chrome or workspace writes. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {pathToFileURL}=require('node:url'),{JSDOM}=require('jsdom');
async function run(){
 const modulePath=path.resolve(process.argv[2]),surface=process.argv[3]||'navigation',action=process.argv[4]||'right';
 const api=require(modulePath),admin=path.dirname(modulePath);
 const dom=new JSDOM('<section data-navigation-maplibre-shell><div id="mapRendererShell"><div id="runtimeMapRendererShell"><button id="fitRoute" data-navigation-maplibre-fit>Fit</button><div id="host" style="width:600px;height:400px"></div></div></div></section>',{url:'http://fixture.invalid/'});
 for(const name of ['window','document','HTMLElement','HTMLCanvasElement','Node','MouseEvent','KeyboardEvent'])
  globalThis[name]=name==='window'?dom.window:name==='document'?dom.window.document:dom.window[name];
 globalThis.devicePixelRatio=1;globalThis.ResizeObserver=class{observe(){}disconnect(){}};
 let networkCalls=0;globalThis.fetch=()=>{networkCalls++;throw Error('Network forbidden in pure camera replay')};
 const vendorPath=path.join(admin,'vendor/maplibre-gl/6.2.0/maplibre-gl.mjs'),lib=await import(pathToFileURL(vendorPath));
 const setup=lib.Map.prototype._setupPainter,realTimeout=global.setTimeout,realNow=Date.now;
 let map,time=0,clockEnabled=false,finished=false;
 process.once('beforeExit',()=>assert.equal(finished,true,'Real Map replay must complete'));
 try {
  lib.Map.prototype._setupPainter=function(){this.painter={resize(){},overLimit(){return false},destroy(){},context:{gl:{getExtension(){return null}}}}};
  lib.setNow(0);
  try{map=new lib.Map({container:'host',interactive:true,attributionControl:false,trackResize:false,
   style:undefined,center:[121,23],zoom:19,reduceMotion:false})}finally{lib.Map.prototype._setupPainter=setup}
  assert.ok(map instanceof lib.Map);assert.ok(map._handlers);assert.ok(map._camera);
  assert.equal(Object.hasOwn(map,'isMoving'),false);assert.equal(map.isMoving,lib.Map.prototype.isMoving);
  const prototypes=[];for(let p=map;p;p=Object.getPrototypeOf(p))prototypes.push({name:p.constructor.name,ownIsMoving:Object.hasOwn(p,'isMoving'),ownIsEasing:Object.hasOwn(p,'isEasing')});
  const evidence={surface,action,realMapInstance:true,publicIsMoving:typeof map.isMoving,publicIsEasing:typeof map.isEasing,
   movingMethod:lib.Map.prototype.isMoving.toString(),prototypes,
   harness:{rendererStub:'Map._setupPainter GPU painter only',cameraAndHandlers:'actual vendor instances, methods unmodified',
    clock:'vendor setNow and actual _renderTaskQueue',network:'forbidden',
    actionDispatch:action==='fit'?'Fixture Fit button invokes controlled 300 ms Map.easeTo; not Dashboard Fit handler'
     :'Descriptor DOM keyboard event through actual vendor HandlerManager',
    scope:'Public Map API and stationary exact-view replay; not Dashboard UI or native tile qualification'},events:[],frames:[]};
  const view=()=>JSON.stringify({center:map.getCenter().toArray(),zoom:map.getZoom(),pitch:map.getPitch(),bearing:map.getBearing()});
  for(const type of ['movestart','move','moveend'])map.on(type,()=>evidence.events.push({type,time,moving:map.isMoving(),view:view()}));
  const advance=next=>{time=next;lib.setNow(time);map._renderTaskQueue.run(time);evidence.frames.push({time,moving:map.isMoving(),view:view()})};
  const root=dom.window.document.querySelector('#host'),config={kind:surface,renderer:'maplibre',root,doc:dom.window.document,projectId:()=> 'fixture'};
  if(surface==='navigation')config.map=map;
  else{
   const name=surface==='pretrip'?'pretripCameraMotion':'debugCameraMotion',stateName=surface==='pretrip'?'state':'debugPageState';
   const page=surface==='pretrip'?'phase4-pretrip-planning.html':'phase-3-5-runtime-debug.html';
   const source=fs.readFileSync(path.join(admin,page),'utf8'),helper=source.match(new RegExp('^    function '+name+'\\(.*?^    \\}', 'ms'))[0];
   config.cameraMotion=vm.runInNewContext(helper+';'+name,{[stateName]:{mapLibreRenderer:{map}},Date});
  }
  const descriptor=api.descriptorFor(config);
  evidence.initialMotion=descriptor.cameraMotion();evidence.initialMapMoving=map.isMoving();
  dom.window.document.querySelector('#fitRoute').addEventListener('click',()=>map.easeTo({center:[121.001,23],duration:300,essential:true}));
  Date.now=()=>time;
  global.setTimeout=(callback,ms)=>clockEnabled?realTimeout(()=>{advance(time+ms);callback()},0):realTimeout(callback,ms);
  clockEnabled=true;
  try{evidence.actionReceipt=await api.act(descriptor,action);evidence.actionStatus='stopped'}
  catch(error){evidence.actionStatus='warning';evidence.error=error.message;evidence.actionReceipt=error.cameraMotionEvidence;evidence.waitEvidence=error.waitEvidence}
  evidence.viewAtReturn=view();evidence.movingAtReturn=map.isMoving();
  advance(Math.max(time+150,450));evidence.viewAfterAnimation=view();evidence.movingAfterAnimation=map.isMoving();
  evidence.exactViewPreserved=evidence.viewAtReturn===evidence.viewAfterAnimation;evidence.networkCalls=networkCalls;
  assert.equal(networkCalls,0);console.log(JSON.stringify(evidence));
 }finally{
  clockEnabled=false;global.setTimeout=realTimeout;Date.now=realNow;
  lib.Map.prototype._setupPainter=setup;if(map)map.remove();lib.restoreNow();dom.window.close();finished=true;
 }
}
run().catch(error=>{console.error(error.stack);process.exitCode=1});
