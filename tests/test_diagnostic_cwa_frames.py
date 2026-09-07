"""Prepared imagery diagnostics reject external and cross-workspace assets."""
from test_dashboard_diagnostic_alignment import function, node


def test_cached_frames_are_project_bound_and_respect_prepared_window():
    node(function('diagnosticWeatherCachedFrames') + r'''
const assert=require('node:assert/strict');
const diagnosticRequire=(ok,message)=>{if(!ok)throw Error(message)};
const base='http://localhost/admin/pretrip?projectId=one';
const good={frameId:'radar.1',productId:'radar-a',bboxWgs84:{north:24},assetUrl:'/admin/pretrip/projects/one/weather-imagery/radar.1'};
const manifest=f=>({childOverlays:{radar:{frames:[f]}}});
assert.equal(diagnosticWeatherCachedFrames(manifest(good),base,'one')[0].assetHref,'http://localhost/admin/pretrip/projects/one/weather-imagery/radar.1');
for(const assetUrl of ['https://external.invalid/file.png','/admin/pretrip/projects/two/weather-imagery/radar.1','/admin/pretrip/projects/one/weather-imagery/radar.1?refresh=1']){
 assert.throws(()=>diagnosticWeatherCachedFrames(manifest({...good,assetUrl}),base,'one'));
}
assert.equal(diagnosticWeatherCachedFrames(manifest({...good,mapOverlaySupported:false}),base,'one').length,0);
assert.equal(diagnosticWeatherCachedFrames({childOverlays:{radar:{frames:[good],windows:{'12h':[]}}}},base,'one').length,0);
''')


def test_unavailable_cached_manifest_never_creates_frame_or_reports_pass():
    node(function('diagnosticWeatherLiveFrames') + r'''
const assert=require('node:assert/strict');
const projectId=()=> 'one',surfaceSrc=()=>'/admin/pretrip?projectId=one',location={href:'http://localhost/admin/dashboard',origin:'http://localhost'};
const diagnosticCoverageRead=async()=>({available:false});
const diagnosticWarning=(detail,dataStatus)=>({status:'warning',detail,dataStatus});
const document={createElement:()=>{throw Error('must not start frame')}};
(async()=>{const result=await diagnosticWeatherLiveFrames();assert.equal(result.status,'warning');assert.equal(result.dataStatus,'unavailable')})();
''')


def test_real_control_events_validate_frames_opacity_and_restore_state():
    node(function('diagnosticWeatherCachedFrames') + function('diagnosticWeatherLiveFrames') + r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM(`<input data-layer="cwa-weather" type="checkbox" checked><select data-cwa-imagery-product><option value="a">a</option><option value="b">b</option></select><select data-cwa-imagery-window><option value="12h">12h</option></select><input data-cwa-imagery-timeline max="1" value="0"><input data-cwa-imagery-opacity="radar" value="62"><svg><image data-cwa-imagery-family="radar"/></svg>`);
const doc=dom.window.document, frame={contentDocument:doc,contentWindow:dom.window};
const projectId=()=> 'one',surfaceSrc=()=>'/admin/pretrip?projectId=one',location={href:'http://localhost/admin/dashboard',origin:'http://localhost'};
const diagnosticRequire=(ok,message)=>{if(!ok)throw Error(message)};
const diagnosticWarning=(detail,dataStatus)=>({status:'warning',detail,dataStatus}),diagnosticAvailability=(dataStatus,detail)=>({status:'passed',dataStatus,detail});
const frames=['a','b'].flatMap(productId=>[0,1].map(index=>({productId,frameId:productId+index,bboxWgs84:{north:24},assetUrl:'/admin/pretrip/projects/one/weather-imagery/'+productId+index})));
const diagnosticCoverageRead=async()=>({available:true,data:{childOverlays:{radar:{frames}}}});
const diagnosticWaitForMapOrder=async f=>{const result=f();if(!result)throw Error('not ready');return result;};
let corrupt=false,renders=0;
const state=()=>({products:[{id:'a'},{id:'b'}],productId:doc.querySelector('select').value,windowId:'12h',frameIndex:Number(doc.querySelector('[data-cwa-imagery-timeline]').value),current:{frameId:doc.querySelector('select').value+doc.querySelector('[data-cwa-imagery-timeline]').value},radarOpacityPercent:Number(doc.querySelector('[data-cwa-imagery-opacity]').value),layerEnabled:true,boundary:{cacheOnly:true,candidateOnly:true}});
frame.contentWindow.scoutCwaImageryController={getState:state};
const render=()=>{const s=state(),image=doc.querySelector('image');image.setAttribute('data-cwa-imagery-frame',corrupt?'wrong':s.current.frameId);image.setAttribute('href','/admin/pretrip/projects/one/weather-imagery/'+s.current.frameId);image.setAttribute('opacity',String(s.radarOpacityPercent/100));};
for(const input of doc.querySelectorAll('select,input'))for(const event of ['change','input'])input.addEventListener(event,render);
const fetch=async url=>{assert.match(url,/^http:\/\/localhost\/admin\/pretrip\/projects\/one\/weather-imagery\//);return {ok:true,blob:async()=>({})}};
const createImageBitmap=async()=>({width:1,height:1,close(){}});
(async()=>{
const result=await diagnosticWeatherLiveFrames(frame,()=>renders++);
assert.equal(result.status,'passed');assert.equal(renders,4);assert.equal(state().productId,'a');assert.equal(state().radarOpacityPercent,62);
corrupt=true;await assert.rejects(diagnosticWeatherLiveFrames(frame),/DOM frame/);
assert.equal(state().productId,'a');assert.equal(state().radarOpacityPercent,62);
})();
''')
