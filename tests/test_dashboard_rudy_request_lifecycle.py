"""Controlled D037 request lifecycle replays; never live Dashboard qualification."""
import pytest

from test_dashboard_rudy_live_diagnostic import BASE, node


CLOCK = r"""
let time=0;const realTimeout=global.setTimeout,realClearTimeout=global.clearTimeout;
const deadlines=new Set();Date.now=()=>time;
let replayFinished=false;process.once('beforeExit',()=>assert.equal(replayFinished,true,'Async replay must reach its assertions'));
global.setTimeout=(callback,ms)=>{
 if(ms===15000){const id={callback};deadlines.add(id);return id;}
 time+=ms;return realTimeout(callback,0);
};
global.clearTimeout=id=>{if(deadlines.has(id))deadlines.delete(id);else realClearTimeout(id)};
const response=status=>({ok:status===200,status,headers:headers(),blob:async()=>new Blob(['tile'])});
const aborted=()=>new DOMException('Cohort fixture observed cancellation.','AbortError');
const descriptor={renderer:'svg',doc:{location:{href:base}},projectId:()=>project,
 snapshot:()=>({activeRenderer:'svg',rendererReady:true,matrix:20,verified:20,required:3,success:3,pending:0,
  errors:0,unverified:0,status:'ready',view:'fixed',generation:'20-active',scrollTop:0,scrollLeft:0,
  tiles:[0,1,2].map(offset=>({key:`20/${850000+offset}/450000`,href:href(20,850000+offset)}))})};
"""


def test_case_waits_for_cancelled_siblings_before_cleanup_and_keeps_first_failure():
    node(BASE + CLOCK + r"""
let failResponse,active=0,closed=0,activeAtClose=null,signalForPending;
global.fetch=async(url,{signal})=>{
 const x=Number(new URL(url).pathname.split('/').at(-2));
 if(x===850001)return new Promise(resolve=>{failResponse=resolve});
 if(x===850002){
  active++;signalForPending=signal;
  return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{
   realTimeout(()=>{active--;reject(aborted())},0);
  },{once:true}));
 }
 return response(200);
};
global.createImageBitmap=async()=>({width:256,height:256,close(){failResponse(response(503))}});
(async()=>{
 const result=await api.runCase({key:'map/svg/default',renderer:'svg'},{projectId:project,
  open:async()=>({descriptor,close:async()=>{closed++;activeAtClose=active;
   return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}}})});
 const failure=result.stages[0];
 assert.equal(activeAtClose,0,'The parent-realm verification cohort must settle before map disposal');
 assert.equal(signalForPending.aborted,true);assert.equal(closed,1);
 assert.match(failure.detail,/20\/850001\/450000: HTTP 503.*Actual Z20/);
 assert.equal(failure.requestReceipt.httpStatus,503,'Sibling cancellation cannot replace the original failure');
 assert.equal(failure.requestEvidence.inFlightCount,0);
 assert.deepEqual(failure.requestEvidence.requests.map(r=>r.outcome),['verified','failed','cancelled']);
 const cancelled=failure.requestEvidence.requests.at(-1);
 assert.equal(cancelled.abort.trigger,'diagnostic-cohort-cancelled');assert.equal(cancelled.deadlineTriggered,false);
 assert.equal(failure.cohortReceipt.firstFailure.inFlightCount,1);
 assert.equal(failure.cohortReceipt.firstFailure.requestId,failure.requestReceipt.requestId);
 assert.equal(failure.cohortReceipt.settledCount,3);assert.equal(failure.cohortReceipt.inFlightCount,0);
 assert.deepEqual(failure.cohortReceipt.requests,failure.requestEvidence.requests);
 assert.equal(result.stages.filter(s=>s.status==='not_checked').length,9);assert.equal(result.cleanupStatus,'passed');
 const sealed=JSON.stringify(result);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(JSON.stringify(result),sealed,'Final receipts cannot change after cleanup');assert.equal(deadlines.size,0);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")


@pytest.mark.parametrize("pending_phase", ["fetch", "blob", "decode"])
def test_cohort_cancels_fetch_or_blob_and_awaits_non_abortable_bitmap_cleanup(pending_phase):
    node(BASE + CLOCK + r"""
const pendingPhase='PENDING_PHASE';let failResponse,finishDecode,decodeClosed=0,settled=false;
const seen=new Map();
global.fetch=async(url,{signal})=>{
 const x=Number(new URL(url).pathname.split('/').at(-2));
 if(x===850001)return new Promise(resolve=>{failResponse=resolve});
 const pending=()=>new Promise((resolve,reject)=>{
  signal.addEventListener('abort',()=>realTimeout(()=>reject(aborted()),0),{once:true});
  failResponse(response(503));
 });
 if(pendingPhase==='fetch')return pending();
 return {ok:true,status:200,headers:headers(),blob:async()=>pendingPhase==='blob'?pending():new Blob(['decode'])};
};
global.createImageBitmap=()=>new Promise(resolve=>{
 finishDecode=()=>resolve({width:256,height:256,close(){decodeClosed++}});failResponse(response(503));
});
(async()=>{
 const result=api.readTileCohort([href(20,850001),href(20,850002)],descriptor,project,
  {onReceipt:receipt=>seen.set(receipt.requestId,receipt)}).then(()=>assert.fail('Failure must not pass'),error=>{settled=true;return error});
 await new Promise(resolve=>setImmediate(resolve));
 if(pendingPhase==='decode'){
  assert.equal(settled,false,'createImageBitmap cannot be abandoned when the cohort aborts');finishDecode();
 }
 const error=await result;
 assert.match(error.message,/HTTP 503/);assert.equal(error.requestReceipt.httpStatus,503);
 assert.equal(error.cohortReceipt.inFlightCount,0);assert.equal(error.cohortReceipt.settledCount,2);
 const sibling=[...seen.values()].find(r=>r.x===850002);
 assert.equal(sibling.phase,pendingPhase);assert.equal(sibling.outcome,'cancelled');
 assert.equal(sibling.abort.trigger,'diagnostic-cohort-cancelled');assert.equal(sibling.decoded,false);
 assert.equal(decodeClosed,pendingPhase==='decode'?1:0);assert.equal(deadlines.size,0);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("PENDING_PHASE", pending_phase))


def test_successful_cohort_keeps_every_request_and_original_timeout_policy():
    node(BASE + CLOCK + r"""
let closed=0;const receipts=[];
global.fetch=async()=>response(200);
global.createImageBitmap=async()=>({width:256,height:256,close(){closed++}});
(async()=>{
 const results=await api.readTileCohort([href(20,850001),href(20,850002)],descriptor,project,
  {onReceipt:receipt=>receipts.push(receipt)});
 assert.equal(results.length,2);assert.equal(closed,2);assert.equal(deadlines.size,0);
 for(const result of results){assert.equal(result.requestReceipt.outcome,'verified');
  assert.equal(result.requestReceipt.deadlineMs,15000);assert.equal(result.requestReceipt.abort.aborted,false);}
 assert.ok(receipts.length>=14,'Every request phase remains available, not just a truncated summary');
 assert.equal(results[0].requestReceipt.cohortId,results[1].requestReceipt.cohortId);
 const standalone=await api.readTile(href(),descriptor,project);
 assert.equal(standalone.requestReceipt.cohortId,null);assert.equal(standalone.requestReceipt.deadlineMs,15000);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")


def test_own_deadline_remains_first_error_and_cancels_siblings_without_relabeling_it():
    node(BASE + CLOCK + r"""
const signals=[];
global.fetch=(url,{signal})=>{signals.push(signal);return new Promise((resolve,reject)=>{
 signal.addEventListener('abort',()=>reject(aborted()),{once:true});
})};
(async()=>{
 const result=api.readTileCohort([href(20,850001),href(20,850002)],descriptor,project).catch(error=>error);
 assert.equal(deadlines.size,2);time+=15000;[...deadlines][0].callback();
 const error=await result;
 assert.equal(error.requestReceipt.deadlineMs,15000);assert.equal(error.requestReceipt.deadlineTriggered,true);
 assert.equal(error.requestReceipt.abort.trigger,'diagnostic-readTile-deadline');
 assert.equal(error.cohortReceipt.requests[1].abort.trigger,'diagnostic-cohort-cancelled');
 assert.equal(error.cohortReceipt.inFlightCount,0);assert.ok(signals.every(signal=>signal.aborted));
 assert.equal(deadlines.size,0);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")


def test_progress_throttle_accounts_for_time_spent_inside_synchronous_observer():
    node(BASE + CLOCK + r"""
let reads=0;const progress=[];
const loading={renderer:'maplibre',projectId:()=>project,snapshot:()=>({activeRenderer:'maplibre',rendererReady:false,
 matrix:++reads,verified:null,required:0,success:null,pending:0,errors:0,unverified:0,status:'loading',scrollTop:0,scrollLeft:0})};
(async()=>{
 const result=await api.runCase({key:'map/maplibre/default',renderer:'maplibre'},{projectId:project,
  open:async()=>({descriptor:loading,close:async()=>({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]})}),
  onProgress:item=>{if(item.liveSnapshot&&!item.stages.length){progress.push(time);time+=700}}});
 assert.ok(progress.length>1);
 for(let i=1;i<progress.length;i++)assert.ok(progress[i]-progress[i-1]>=1200,
  'A slow observer must not turn the 500 ms throttle into publishing every phase');
 assert.equal(result.stages[0].waitEvidence.timeoutMs,60000);assert.equal(result.stages[0].status,'warning');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""")
