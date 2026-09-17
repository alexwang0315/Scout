"""Real Response/ReadableStream cleanup replays; no browser/network qualification."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_dashboard_rudy_live_diagnostic import BASE, MODULE, ROOT
from test_dashboard_rudy_request_lifecycle import CLOCK

REPLAY = ROOT / "tests/fixtures/rudy_response_body_replay.cjs"


def run(program, label):
    result = subprocess.run([shutil.which("node"), "-", str(MODULE)], input=program,
                            capture_output=True, text=True, cwd=ROOT, timeout=30)
    save(result, label)
    assert result.returncode == 0, result.stderr


def save(result, label):
    evidence = os.environ.get("SCOUT_BODY_LIFECYCLE_EVIDENCE")
    if evidence:
        folder = Path(evidence)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{label}.json").write_text(result.stdout)
        (folder / f"{label}.stderr.txt").write_text(result.stderr)


@pytest.mark.parametrize("scenario", ["200", "404", "503", "provenance"])
def test_real_unused_body_is_cancelled_and_awaited_before_terminal_receipt(scenario):
    result = subprocess.run([shutil.which("node"), str(REPLAY), str(MODULE), scenario],
                            capture_output=True, text=True, cwd=ROOT, timeout=30)
    save(result, f"held-{scenario}")
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["held"]["pending"] is True
    assert receipt["held"]["bodyOwned"] is True
    assert receipt["held"]["cancelCalled"] == 1
    assert receipt["held"]["lastReceipt"]["outcome"] == "pending"
    assert receipt["held"]["lastReceipt"]["bodySettlement"]["status"] == "cancelling"
    assert receipt["manualCleanup"] is False
    assert receipt["final"]["bodyOwned"] is False
    assert receipt["final"]["lastReceipt"]["bodySettlement"]["status"] == "cancelled"
    assert receipt["final"]["lastReceipt"]["outcome"] == (
        "verified" if scenario == "200" else "missing" if scenario == "404" else "failed"
    )


@pytest.mark.parametrize("status", [200, 404])
def test_original_deadline_aborts_but_does_not_abandon_held_body_cleanup(status):
    run(BASE + CLOCK + r"""
let release,signal,pending=true,error;const seen=[];
const body=new ReadableStream({start(c){c.enqueue(new Uint8Array([1]))},
 cancel(){return new Promise(resolve=>{release=resolve})}});
global.fetch=async(url,options)=>{signal=options.signal;return new Response(body,{status:STATUS,headers:headers()})};
(async()=>{
 const task=api.readTile(href(),descriptor,project,{decode:false,allowMissing:true,onReceipt:r=>seen.push(r)})
  .then(()=>assert.fail('Deadline must not pass'),reason=>{error=reason;pending=false});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(pending,true);assert.equal(typeof release,'function');
 assert.equal(deadlines.size,1);time=15000;[...deadlines][0].callback();
 await new Promise(resolve=>setImmediate(resolve));assert.equal(signal.aborted,true);assert.equal(pending,true);
 assert.equal(seen.at(-1).outcome,'pending');assert.equal(seen.at(-1).bodySettlement.status,'cancelling');
 release();await task;const receipt=error.requestReceipt;
 assert.equal(receipt.deadlineMs,15000);assert.equal(receipt.deadlineTriggered,true);assert.equal(receipt.elapsedMs,15000);
 assert.equal(receipt.abort.trigger,'diagnostic-readTile-deadline');assert.equal(receipt.outcome,'failed');
 assert.equal(receipt.bodySettlement.status,'cancelled');assert.equal(deadlines.size,0);
 console.log(JSON.stringify({scope:'controlled stream/deadline replay',receipt,observations:seen}));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("STATUS", str(status)), f"deadline-{status}")


@pytest.mark.parametrize("status", [200, 503])
def test_cancel_failure_is_visible_and_does_not_replace_an_earlier_http_failure(status):
    run(BASE + CLOCK + r"""
const body=new ReadableStream({cancel(){return Promise.reject(new TypeError('fixture cancel failure'))}});
global.fetch=async()=>new Response(body,{status:STATUS,headers:headers()});
(async()=>{
 await assert.rejects(api.readTile(href(),descriptor,project,{decode:false}),error=>{
  const r=error.requestReceipt;assert.equal(r.outcome,'failed');assert.equal(r.bodySettlement.status,'cancel-failed');
  assert.equal(r.bodySettlement.error.name,'TypeError');assert.match(r.bodySettlement.error.message,/fixture cancel failure/);
  assert.match(error.message,/response body cancellation failed/i);
  if(STATUS===503){assert.match(error.message,/HTTP 503/);assert.match(error.cause.message,/HTTP 503/);
   assert.match(r.error.message,/HTTP 503/);assert.match(r.bodyCleanupError.message,/body cancellation failed/i)}
  console.log(JSON.stringify({scope:'controlled cleanup failure replay',message:error.message,receipt:r}));return true;
 });assert.equal(deadlines.size,0);
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""".replace("STATUS", str(status)), f"cancel-failure-{status}")


def test_first_http_failure_aborts_siblings_before_awaiting_its_held_body_cleanup():
    run(BASE + CLOCK + r"""
let release,siblingSignal,settled=false;const receipts=[];
const body=new ReadableStream({start(c){c.enqueue(new Uint8Array([1]))},
 cancel(){return new Promise(resolve=>{release=resolve})}});
global.fetch=async(url,{signal})=>{
 if(new URL(url).pathname.includes('/850000/'))return new Response(body,{status:503,headers:headers()});
 siblingSignal=signal;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(aborted()),{once:true}));
};
(async()=>{
 const task=api.readTileCohort([href(20,850000),href(20,850001)],descriptor,project,{decode:false,onReceipt:r=>receipts.push(r)})
 .then(()=>assert.fail('503 cannot pass'),error=>{settled=true;return error});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(siblingSignal.aborted,true,'First503 must cancel its sibling while its own body cancel is held');
 assert.equal(typeof release,'function');assert.equal(settled,false);
 assert.equal(receipts.filter(r=>r.x===850000).at(-1).outcome,'pending');
 release();const error=await task;assert.match(error.message,/HTTP 503/);
 assert.equal(error.requestReceipt.httpStatus,503);assert.equal(error.requestReceipt.outcome,'failed');
 assert.equal(error.requestReceipt.bodySettlement.status,'cancelled');
 assert.equal(error.cohortReceipt.firstFailure.requestId,error.requestReceipt.requestId);
 assert.equal(error.cohortReceipt.firstFailure.inFlightCount,1);assert.equal(error.cohortReceipt.inFlightCount,0);
 assert.deepEqual(error.cohortReceipt.requests.map(r=>r.outcome),['failed','cancelled']);
 assert.equal(deadlines.size,0);
 console.log(JSON.stringify({scope:'real Response with controlled body cancellation and pending sibling',
  error:error.message,cohort:error.cohortReceipt,observations:receipts}));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""", "cohort-early-failure")


def test_successful_header_only_cohort_waits_for_every_body_cancel():
    run(BASE + CLOCK + r"""
const release=new Map(),closed=[];let settled=false;
global.fetch=async url=>{
 const x=Number(new URL(url).pathname.split('/').at(-2));
 return new Response(new ReadableStream({cancel(){return new Promise(resolve=>release.set(x,()=>{closed.push(x);resolve()}))}}),
  {status:x===850000?200:404,headers:headers()});
};
(async()=>{
 const task=api.readTileCohort([href(20,850000),href(20,850001)],descriptor,project,{decode:false,allowMissing:true})
  .then(value=>{settled=true;return value});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(release.size,2);assert.equal(settled,false);
 release.get(850000)();await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false);
 release.get(850001)();const results=await task;assert.equal(closed.length,2);
 assert.deepEqual(results.map(r=>r.status),[200,404]);assert.ok(results.every(r=>r.requestReceipt.bodySettlement.status==='cancelled'));
 assert.equal(deadlines.size,0);console.log(JSON.stringify({scope:'controlled unused-body cohort',results}));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""", "cohort-success")


def test_decode_path_consumes_actual_response_body_without_cancelling_it():
    run(BASE + CLOCK + r"""
let cancelled=0,decoded=0,closed=0;
const streamResponse=new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1,2,3]));c.close()},cancel(){cancelled++}}),{headers:headers()});
global.fetch=async()=>streamResponse;
global.createImageBitmap=async blob=>{assert.equal(blob.size,3);decoded++;return {width:256,height:256,close(){closed++}}};
(async()=>{
 const result=await api.readTile(href(),descriptor,project);
 assert.equal(streamResponse.bodyUsed,true);assert.equal(cancelled,0);assert.equal(decoded,1);assert.equal(closed,1);
 assert.equal(result.requestReceipt.bodySettlement.status,'consumed');assert.equal(result.requestReceipt.decoded,true);
 assert.equal(result.requestReceipt.blobBytes,3);assert.equal(deadlines.size,0);
 console.log(JSON.stringify({scope:'real body consumption with controlled bitmap decode',result}));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""", "decode-consumes")


def test_next_cache_probe_waits_for_previous_response_body_release():
    run(BASE + CLOCK + r"""
const releases=[],receipts=[];let calls=0,owned=0,maxOwned=0;
const template=href().replace('/20/850000/450000.png','/{z}/{x}/{y}.png');
const camera={...descriptor,tileView:()=>({tiles:[{z:20,x:850000,y:450000}],tileTemplate:template})};
global.fetch=async()=>{
 const index=calls++;owned++;maxOwned=Math.max(maxOwned,owned);
 return new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([index]))},
  cancel(){return new Promise(resolve=>releases.push(()=>{owned--;resolve()}))}}),
 {status:index===0?200:404,headers:headers()});
};
(async()=>{
 const task=api.findCacheMiss(camera,{matrix:20},project,{onReceipt:r=>receipts.push(r)});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,1);assert.equal(owned,1);
 releases[0]();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,2);assert.equal(owned,1);
 releases[1]();const result=await task;assert.equal(result.status,404);assert.equal(owned,0);assert.equal(maxOwned,1);
 assert.equal(result.requestReceipt.bodySettlement.status,'cancelled');assert.equal(deadlines.size,0);
 console.log(JSON.stringify({scope:'cache search body ownership, controlled Response streams',calls,maxOwned,result,receipts}));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{replayFinished=true});
""", "search-serial-body")
