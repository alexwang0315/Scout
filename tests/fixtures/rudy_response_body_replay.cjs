const assert=require('node:assert/strict'),api=require(process.argv[2]);
const scenario=process.argv[3],project='diagnostic_trip',url='http://fixture.invalid/admin/tiles/imagery/diagnostic_trip/imagery/20/850000/450000.png?source_id=happyman_rudy_twmap&exact=1&cache_only=1';
let cancelCalled=0,bodyOwned=true,releaseCancel,pending=true,result,error;
const events=[],receipts=[];
const body=new ReadableStream({start(controller){controller.enqueue(new Uint8Array([1,2,3]));events.push({event:'body-open'})},
 cancel(reason){cancelCalled++;events.push({event:'cancel-start',reason:String(reason)});return new Promise(resolve=>{releaseCancel=()=>{bodyOwned=false;events.push({event:'cancel-settled'});resolve()}})}});
const response=new Response(body,{status:scenario==='404'?404:scenario==='503'?503:200,headers:{
 'X-Scout-Tile-Exact':'true','X-Scout-Tile-Zoom':'20','X-Scout-Imagery-Source-Id':'happyman_rudy_twmap',
 'X-Scout-Tile-Source':scenario==='provenance'?'parent_cache_fallback':'local_source_cache'}});
global.fetch=async()=>response;
(async()=>{
 const task=api.readTile(url,{doc:{location:{href:url}}},project,{decode:false,allowMissing:true,onReceipt:r=>receipts.push(r)})
  .then(value=>{result=value;pending=false},reason=>{error=reason;pending=false});
 await new Promise(resolve=>setImmediate(resolve));
 const held={pending,bodyOwned,cancelCalled,bodyUsed:response.bodyUsed,
  lastReceipt:receipts.at(-1),resultStatus:result?.status,error:error?.message};
 const manualCleanup=cancelCalled===0;
 const cleanup=manualCleanup?response.body.cancel('harness cleanup after observation'):null;
 assert.equal(typeof releaseCancel,'function');releaseCancel();if(cleanup)await cleanup;await task;
 console.log(JSON.stringify({scope:'Real Response/ReadableStream resource-ownership replay; no HTTP/network/Chrome qualification',
  scenario,held,manualCleanup,final:{pending,bodyOwned,cancelCalled,resultStatus:result?.status,error:error?.message,
   lastReceipt:receipts.at(-1)},events}));
})().catch(error=>{console.error(error.stack);process.exitCode=1});
