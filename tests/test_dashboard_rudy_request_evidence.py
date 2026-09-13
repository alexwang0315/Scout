"""D037 request/init receipts only; these controlled replays do not qualify Chrome."""
import json

import pytest

from test_dashboard_rudy_live_diagnostic import BASE, function, node, workflow


@pytest.mark.parametrize("scenario,phase", [
    ("fetch-deadline", "fetch"), ("blob-deadline", "blob"),
    ("external-abort-message", "fetch"), ("http", "headers"),
    ("provenance", "provenance"), ("decode", "decode"), ("dimensions", "dimensions"),
])
def test_failed_request_keeps_exact_phase_provenance_abort_trigger_and_original_cause(scenario, phase):
    node(BASE + r"""
const scenario=SCENARIO,expectedPhase=PHASE,descriptor={doc:{location:{href:base}}};
let time=100,timer=null,cleared=0,signal=null,closed=0;const receipts=[];
Date.now=()=>time;
global.setTimeout=(callback,ms)=>{assert.equal(ms,15000);timer=callback;return 1};
global.clearTimeout=id=>{assert.equal(id,1);cleared++};
const aborted=()=>new DOMException('The user aborted a request.','AbortError');
const deadline=()=>new Promise((resolve,reject)=>{
 signal.addEventListener('abort',()=>reject(aborted()),{once:true});time+=15000;timer();
});
const cause=Object.assign(new Error('fixture decoder rejected bytes'),{code:'DECODE_FIXTURE'});
const original=new TypeError('fixture decode failure',{cause});
global.fetch=async(url,options)=>{
 assert.equal(new URL(url).searchParams.get('cache_only'),'1');
 assert.equal(new URL(url).searchParams.has('native'),false);
 signal=options.signal;
 if(scenario==='fetch-deadline')return deadline();
 if(scenario==='external-abort-message')throw aborted();
 time+=7;
 return {ok:scenario!=='http',status:scenario==='http'?503:200,
  headers:headers(scenario==='provenance'?{'X-Scout-Tile-Source':'parent_cache_fallback'}:{}),
  blob:async()=>{if(scenario==='blob-deadline')return deadline();time+=11;return new Blob(['fixture-bytes'])}};
};
global.createImageBitmap=async()=>{
 time+=13;if(scenario==='decode')throw original;
 return {width:scenario==='dimensions'?1:256,height:256,close(){closed++}};
};
(async()=>{
await assert.rejects(api.readTile(href(),descriptor,project,{onReceipt:receipt=>receipts.push(receipt)}),error=>{
 const receipt=error.requestReceipt;
 assert.equal(receipt.key,'20/850000/450000');assert.equal(receipt.mode,'cache');
 assert.equal(receipt.purpose,'diagnostic-tile-verification');assert.equal(receipt.fetchCache,'no-store');
 assert.equal(receipt.phase,expectedPhase);assert.equal(receipt.outcome,'failed');
 assert.equal(receipt.deadlineMs,15000);assert.equal(receipt.elapsedMs,time-100);
 assert.equal(receipt.httpStatus,['fetch-deadline','external-abort-message'].includes(scenario)?null:scenario==='http'?503:200);
 assert.equal(receipt.deadlineTriggered,scenario.endsWith('-deadline'));
 assert.equal(receipt.abort.aborted,scenario.endsWith('-deadline'));
 assert.equal(receipt.abort.trigger,scenario.endsWith('-deadline')?'diagnostic-readTile-deadline':null);
 assert.ok(receipt.events.some(event=>event.event==='start'));
 assert.equal(receipt.events.at(-1).event,'error');
 assert.equal(receipt.error.name,error.cause.name,'Keep the original error, including DOMException name');
 if(receipt.httpStatus)assert.equal(receipt.headers['X-Scout-Tile-Zoom'],'20');
 if(scenario==='provenance')assert.equal(receipt.headers['X-Scout-Tile-Source'],'parent_cache_fallback');
 if(scenario==='decode'){
  assert.equal(error.cause,original);assert.equal(receipt.error.cause.message,cause.message);
  assert.equal(receipt.error.cause.code,'DECODE_FIXTURE');assert.equal(receipt.blobBytes,13);
 }
 if(scenario==='dimensions'){assert.equal(receipt.bitmapWidth,1);assert.equal(receipt.bitmapHeight,256);assert.equal(closed,1);}
 if(scenario==='external-abort-message')assert.equal(receipt.abort.reason,null,'Browser wording is not proof of a manual or diagnostic abort');
 assert.doesNotThrow(()=>JSON.stringify(receipt));
 return true;
});
assert.equal(cleared,1);assert.equal(receipts[0].outcome,'pending');assert.equal(receipts[0].headers,null);
assert.equal(receipts.at(-1).outcome,'failed','Earlier receipts are immutable snapshots');
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace("SCENARIO", json.dumps(scenario)).replace("PHASE", json.dumps(phase)))


@pytest.mark.parametrize("mode", ["cache", "native"])
def test_successful_request_retains_url_mode_timings_headers_and_bitmap_receipt(mode):
    node(BASE + r"""
const mode=MODE,descriptor={doc:{location:{href:base}}};let time=0,closed=0;
Date.now=()=>time;
global.fetch=async(url,options)=>{
 const search=new URL(url).searchParams;
 assert.equal(search.get(mode==='cache'?'cache_only':'native'),'1');
 assert.equal(search.has(mode==='cache'?'native':'cache_only'),false);assert.equal(search.has('refresh'),false);
 assert.equal(options.cache,'no-store');time+=3;
 return {ok:true,status:200,headers:headers({'X-Scout-Tile-Source':mode==='cache'?'local_source_cache':'native_upstream'}),
  blob:async()=>{time+=5;return new Blob(['png'])}};
};
global.createImageBitmap=async()=>{time+=7;return {width:256,height:256,close(){closed++}}};
(async()=>{
 const result=await api.readTile(href(),descriptor,project,{mode});
 const receipt=result.requestReceipt;
 assert.equal(receipt.mode,mode);assert.equal(result.decoded,true);assert.equal(receipt.decoded,true);
 assert.equal(receipt.outcome,'verified');assert.equal(receipt.phase,'complete');
 assert.equal(receipt.httpStatus,200);assert.equal(receipt.elapsedMs,15);assert.equal(receipt.blobBytes,3);
 assert.equal(receipt.bitmapWidth,256);assert.equal(receipt.bitmapHeight,256);assert.equal(closed,1);
 assert.deepEqual(receipt.events.map(event=>event.phase),['fetch','headers','provenance','blob','decode','dimensions','complete']);
 assert.equal(receipt.abort.aborted,false);assert.equal(receipt.deadlineTriggered,false);
 global.fetch=async()=>({ok:false,status:404});
 const missing=await api.readTile(href(),descriptor,project,{allowMissing:true,decode:false});
 assert.equal(missing.status,404);assert.equal(missing.requestReceipt.outcome,'missing');
 assert.equal(missing.requestReceipt.decoded,false);assert.equal(missing.requestReceipt.httpStatus,404);
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace("MODE", json.dumps(mode)))


def test_real_stage_flow_keeps_cache_verification_separate_from_native_map_urls():
    workflow("normal", r"""
assert.equal(summary.passed,10);assert.equal(summary.status,'passed');
for(const stage of result.stages){
 assert.ok(stage.requestEvidence.requests.length>0);assert.equal(stage.requestEvidence.inFlightCount,0);
 for(const receipt of stage.requestEvidence.requests){
  const url=new URL(receipt.href);
  assert.equal(receipt.mode,'cache');assert.equal(url.searchParams.get('cache_only'),'1');
  assert.equal(url.searchParams.has('native'),false);assert.equal(url.searchParams.has('refresh'),false);
  assert.equal(receipt.deadlineMs,15000);assert.ok(['verified','missing'].includes(receipt.outcome));
 }
}
const missing=result.stages.find(stage=>stage.stage==='cache-miss').requestEvidence.requests;
assert.ok(missing.some(receipt=>receipt.httpStatus===404&&receipt.decodeRequested===false));
assert.ok(result.stages[0].snapshot.tiles.every(tile=>new URL(tile.href).searchParams.get('native')==='1'));
""")


def test_svg_failure_retains_the_failed_tile_and_honest_unsettled_siblings_in_dom_export():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="mount"></main>',{url:base});
const document=dom.window.document,projectId=()=>project,asArray=value=>Array.isArray(value)?value:[];
const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
let time=0,failResponse,lateResponse,closed=0;const timerIds=new Set();
const realTimeout=global.setTimeout;Date.now=()=>time;
global.setTimeout=(callback,ms)=>{
 if(ms===15000){const id={callback};timerIds.add(id);return id;}
 time+=ms;return realTimeout(callback,0);
};
global.clearTimeout=id=>{timerIds.delete(id)};
const response=status=>({ok:status===200,status,headers:headers(),blob:async()=>new Blob(['tile'])});
global.fetch=async url=>{
 const x=Number(new URL(url).pathname.split('/').at(-2));
 if(x===850001)return new Promise(resolve=>{failResponse=resolve});
 if(x===850002)return new Promise(resolve=>{lateResponse=resolve});
 return response(200);
};
global.createImageBitmap=async()=>({width:256,height:256,close(){failResponse?.(response(503))}});
const snapshot={activeRenderer:'svg',rendererReady:true,matrix:20,verified:20,required:3,success:3,pending:0,
 errors:0,unverified:0,status:'ready',view:'fixed',generation:'20-active',scrollTop:0,scrollLeft:0,
 tiles:[0,1,2].map(offset=>({key:`20/${850000+offset}/450000`,href:href(20,850000+offset)}))};
const descriptor={renderer:'svg',doc:{location:{href:base}},projectId:()=>project,snapshot:()=>snapshot};
""" + function("renderDiagnosticRudyResults") + r"""
(async()=>{
 const result=await api.runCase({key:'map/svg/default',renderer:'svg'},{projectId:project,
  open:async()=>({descriptor,close:async()=>{closed++;return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}}})});
 const failure=result.stages[0];
 assert.equal(failure.status,'warning');assert.equal(api.nativeComplete(failure.snapshot),true);
 assert.match(failure.detail,/20\/850001\/450000: HTTP 503.*Actual Z20/);
 assert.equal(failure.requestReceipt.httpStatus,503);assert.equal(failure.requestReceipt.phase,'headers');
 assert.equal(failure.error.cause.cause.message,'20/850001/450000: HTTP 503.');
 assert.equal(failure.requestEvidence.requests.length,3);assert.equal(failure.requestEvidence.inFlightCount,1);
 assert.deepEqual(failure.requestEvidence.requests.map(item=>item.outcome),['verified','failed','pending']);
 assert.equal(result.stages.filter(item=>item.status==='passed').length,0);
 assert.equal(result.stages.filter(item=>item.status==='not_checked').length,9);assert.equal(closed,1);
 const report={projectId:project,status:'warning',plannedCases:1,plannedStages:10,stageNames:api.STAGES,cases:[result]};
 document.querySelector('#mount').innerHTML=renderDiagnosticRudyResults(report);
 const exported=JSON.parse(document.querySelector('[data-diagnostic-rudy-json]').textContent);
 assert.deepEqual(exported.cases[0].stages[0].requestEvidence,failure.requestEvidence);
 assert.equal(exported.cases[0].stages[0].error.cause.cause.message,'20/850001/450000: HTTP 503.');
 lateResponse(response(200));await new Promise(resolve=>setImmediate(resolve));
 assert.equal(failure.requestEvidence.inFlightCount,1,'Receipt is a snapshot at failure, not an assertion that later siblings settled');
 assert.equal(failure.requestEvidence.requests.at(-1).outcome,'pending');
 assert.equal(timerIds.size,0);dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_pending_maplibre_records_dom_initialization_transitions_without_extending_native_deadline():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="mapRendererShell" data-map-project-load-state="loading" data-map-renderer-active="pending" data-map-renderer-state="loading"><div id="mapLibreEvidenceMap"></div></div>',{url:base});
const doc=dom.window.document,shell=doc.querySelector('#mapRendererShell'),root=doc.querySelector('#mapLibreEvidenceMap');
dom.window.ScoutMapLibreEvidence={};dom.window.scoutPretripMapRendererBridge={getSnapshot(){throw Error('Do not scan renderer features for initialization evidence')}};
let time=0;const realTimeout=global.setTimeout,observed=[];
Date.now=()=>time;
global.setTimeout=(callback,ms)=>{assert.equal(ms,150);time+=ms;return realTimeout(callback,0)};
const descriptor=api.descriptorFor({kind:'pretrip',renderer:'maplibre',root,doc,projectId:()=>project});
const snapshot=descriptor.snapshot;
descriptor.snapshot=()=>{
 if(time>=300)shell.dataset.mapProjectLoadState='base_ready';
 if(time>=600)Object.assign(shell.dataset,{mapRendererActive:'maplibre',mapRendererReason:'maplibre_selected',mapProjectLoadState:'enhanced_ready'});
 return snapshot();
};
(async()=>{
 const result=await api.runCase({key:'map/maplibre/default',renderer:'maplibre'},{projectId:project,
  open:async()=>({descriptor,close:async()=>({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]})}),
  onProgress:item=>{if(item.liveSnapshot)observed.push(structuredClone(item.liveSnapshot))}});
 const failure=result.stages[0];assert.equal(failure.status,'warning');assert.match(failure.detail,/deadline/);
 assert.equal(time,60000,'Initialization-only changes do not reset the native-success idle deadline');
 assert.equal(failure.waitEvidence.timeoutMs,60000);assert.equal(failure.waitEvidence.pollIntervalMs,150);
 assert.equal(failure.waitEvidence.scheduler,'setTimeout');assert.equal(failure.waitEvidence.deadlineResetCount,1);
 assert.equal(failure.waitEvidence.readCount,400);assert.equal(failure.waitEvidence.elapsedMs,60000);
 assert.ok(observed.some(item=>item.activeRenderer==='pending'));
 assert.ok(observed.some(item=>item.rendererReason==='maplibre_selected'),'Initialization must publish even when tile counters stay null');
 const evidence=failure.initializationEvidence;
 assert.equal(evidence.latestReceipt,null);
 assert.deepEqual([...new Set(evidence.observations.map(item=>item.projectLoadState))],['loading','base_ready','enhanced_ready']);
 const selected=evidence.observations.at(-1);
 assert.equal(selected.rendererReason,'maplibre_selected');assert.equal(selected.initializationReceiptPresent,false);
 assert.equal(selected.projectLoadState,'enhanced_ready');
 assert.equal(selected.initializationPhase,null,'Selected renderer is not proof a module or map constructor completed');
 assert.equal(selected.adapterAvailable,true);assert.equal(selected.bridgeAvailable,true);
 assert.equal(selected.documentUrl,base);assert.equal(selected.rootConnected,true);
 assert.equal(failure.snapshot.matrix,null);assert.equal(failure.requestEvidence.requests.length,0);
 assert.equal(result.stages.filter(item=>item.status==='passed').length,0);
 dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")
