import test from "node:test";
import assert from "node:assert/strict";
import {analyze,validateCapture,CASES} from "../tools/dashboard_3d_cost_analyze.mjs";

// Artificial capture contract only; never presented as actual Mac evidence.
function capture(){
  const order=[...CASES,...CASES.toReversed(),"rudy","split_sync","base","full","hillshade","split_static"];
  return {status:"PASS",machine:{platform:"darwin"},browser:{version:"synthetic"},limitations:[],
    provenance:{authority:{candidate_only:true,visualization_only:true,runtime_safety_truth:false},dem_fingerprint:"fixture",source_hashes:{fixture:"fixture"},rudy_maxzoom:14},
    runs:order.map((caseId,i)=>{
      const c=CASES.indexOf(caseId),split=c>=4,terrain={source:"scout-terrain-dem",exaggeration:1};
      const layers=["background","route",...(c>0?["scout-terrain-hillshade"]:[]),...(c>1?["scout-rudy-tw"]:[]),...(c>2?["candidates"]:[])].map(id=>({id}));
      const diag={mode:"3d",canvas:[960,640],camera:{zoom:14,pitch:45},terrain,meshSize:128,terrainZooms:[12,13,14],observedTerrainZooms:[12,13,14],centerElevation:100,
        rasterSources:{"scout-terrain-dem":{minzoom:13,maxzoom:13},...(c>1?{"scout-rudy-tw":{maxzoom:14}}:{})},layers,features:{"scout-terrain-candidates":{count:c>2?44:1}}};
      const diagnostics=[diag,...(split?[{mode:"2d",canvas:[320,640]}]:[])];
      const times=Array.from({length:721-c*60},(_,n)=>n*12000/(720-c*60));
      const phase={elapsedMs:12020,primaryFrameTimes:times,secondaryFrameTimes:caseId==="split_sync"?times:[],primary:{meanFps:-999},
        callbacks:{"3d.moveend":{calls:5,totalMs:5,maxMs:1},syncDispatch:{calls:times.length,totalMs:10,maxMs:1},...(caseId==="split_sync"?{"2d.jumpTo":{calls:times.length,totalMs:10,maxMs:1}}:{})}};
      return {caseId,index:i+1,status:"PASS",errors:[],finalTilesLoaded:true,failedRequests:[],cancelledTileRequests:[],gpu:{renderer:"hardware fixture"},scene:{payloadSha256:"fixture",preparedRoutePointCount:3,camera:{zoom:14},diagnostics,
        phases:{firstReadyMs:1000+c*100+Math.floor(i/6)*50,dashboardDomMs:100},setupCallbacks:{}},finalDiagnostics:structuredClone(diagnostics),
        measurement:{refreshMs:1000/60,rotation:structuredClone(phase),pan:structuredClone(phase)},peakRssBytes:2**20,readyMemory:{rssBytes:2**20},readyHeap:{usedSize:1024}};
    })};
}

test("summaries use raw frame evidence and pair the same balanced block",()=>{
  const result=analyze(capture());
  assert.equal(result.parity.status,"PASS");
  assert.ok(Math.abs(result.summary.base.metrics.rotationFps.median-60)<1e-9);
  assert.ok(Math.abs(result.summary.hillshade.metrics.rotationFps.median-55)<1e-9);
  assert.ok(Math.abs(result.contrasts[0].pairedBlockDeltas.rotationFps.median+5)<1e-9);
  assert.ok(Math.abs(result.contrasts[0].pairedBlockDeltas.firstReadySeconds.median-.1)<1e-9);
});

test("incomplete, software, stale configuration and missing DEM evidence are rejected",()=>{
  for(const mutate of [
    p=>p.runs.pop(),p=>p.preflight=true,p=>p.machine.platform="linux",
    p=>p.runs[0].errors.push({kind:"http"}),p=>p.runs[0].gpu.renderer="SwiftShader",p=>p.runs[0].finalTilesLoaded=false,
    p=>p.runs[1].scene.payloadSha256="changed",p=>p.runs[1].scene.diagnostics[0].centerElevation=null,
    p=>p.runs[1].finalDiagnostics[0].observedTerrainZooms=[13],
    p=>p.runs[5].scene.diagnostics[0].rasterSources["scout-rudy-tw"].maxzoom=18,
    p=>p.runs[1].measurement.pan.primaryFrameTimes=[0,NaN],
  ]){const p=capture();mutate(p);assert.throws(()=>validateCapture(p));}
});

test("a disabled synchronization path or artificial moveend storm cannot pass",()=>{
  const stopped=capture();delete stopped.runs[5].measurement.pan.callbacks["2d.jumpTo"];
  assert.throws(()=>validateCapture(stopped),/Synchronization/);
  const storm=capture();storm.runs[0].measurement.rotation.callbacks["3d.moveend"].calls=720;
  assert.throws(()=>validateCapture(storm),/artificial/);
  const idle=capture();idle.runs[5].measurement.pan.secondaryFrameTimes=[];
  assert.throws(()=>validateCapture(idle),/peer/);
});
