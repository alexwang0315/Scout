#!/usr/bin/env node
// Analysis of retained Mac evidence; never launches a browser or changes a capture.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createHash} from "node:crypto";
import {summarizeIntervals} from "../docs/admin/experiments/gpx-3d/benchmark/common.mjs";

export const CASES=["base","hillshade","rudy","full","split_static","split_sync"];
const assert=(condition,message)=>{if(!condition)throw Error(message);};
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const unique=values=>[...new Set(values)].sort((a,b)=>a-b);
const intervals=times=>times.slice(1).map((t,i)=>t-times[i]);
const stats=values=>{
  assert(values.length&&values.every(Number.isFinite),"Missing finite metric");
  const sorted=[...values].sort((a,b)=>a-b),i=Math.floor(sorted.length/2);
  return {median:sorted.length%2?sorted[i]:(sorted[i-1]+sorted[i])/2,min:sorted[0],max:sorted.at(-1)};
};
const primary=row=>row.scene.diagnostics.find(d=>d.mode==="3d");

export function validateCapture(report){
  assert(report.status==="PASS"&&report.machine.platform==="darwin"&&!report.proofOnly&&!report.preflight,"Require completed actual Mac measurements");
  assert(report.runs?.length===18,"Require three balanced blocks of six cases");
  const authority=report.provenance?.authority;
  assert(authority?.candidate_only===true&&authority.visualization_only===true&&authority.runtime_safety_truth===false,"Missing display-only authority");
  assert(report.provenance.dem_fingerprint&&Object.keys(report.provenance.source_hashes||{}).length,"Missing source evidence");
  const reference=report.runs[0],referenceMap=primary(reference);
  for(let block=0;block<3;block++)assert(same(report.runs.slice(block*6,block*6+6).map(r=>r.caseId).sort(),[...CASES].sort()),"Unbalanced case order");
  for(const row of report.runs){
    assert(row.status==="PASS"&&!row.errors?.length&&!row.memoryError,`Failed capture: ${row.caseId}`);
    assert(row.finalTilesLoaded===true&&row.failedRequests?.length===row.cancelledTileRequests?.length,"Unresolved network failures or incomplete tiles");
    assert(row.gpu?.renderer&&!/swiftshader|llvmpipe|software/i.test(row.gpu.renderer),"Hardware GPU not verified");
    assert(row.gpu.renderer===reference.gpu.renderer,"GPU changed");
    assert(row.scene.payloadSha256===reference.scene.payloadSha256&&same(row.scene.camera,reference.scene.camera),"Data or camera mismatch");
    assert(row.scene.preparedRoutePointCount>0&&row.scene.preparedRoutePointCount===reference.scene.preparedRoutePointCount,"Route samples mismatch");
    const map=primary(row),split=row.caseId.startsWith("split_");
    assert(same(map.canvas,[960,640])&&map.camera.zoom===14&&map.camera.pitch===45,"Primary viewport/camera mismatch");
    assert(map.meshSize===referenceMap.meshSize&&map.meshSize===128&&same(map.terrain,referenceMap.terrain),"Terrain geometry mismatch");
    assert(same(map.rasterSources["scout-terrain-dem"],referenceMap.rasterSources["scout-terrain-dem"]),"Terrain source configuration mismatch");
    assert(same(unique(map.terrainZooms),unique(referenceMap.terrainZooms)),"Initial terrain LOD mismatch");
    assert(Number.isFinite(map.centerElevation)&&Math.abs(map.centerElevation-referenceMap.centerElevation)<.01,"Decoded elevation mismatch");
    const final=row.finalDiagnostics.find(d=>d.mode==="3d"),finalRef=reference.finalDiagnostics.find(d=>d.mode==="3d");
    assert(final.observedTerrainZooms.length&&same(unique(final.observedTerrainZooms),unique(finalRef.observedTerrainZooms)),"Observed terrain LOD mismatch");
    assert(row.scene.diagnostics.length===(split?2:1),"Unexpected map count");
    if(split)assert(same(row.scene.diagnostics.find(d=>d.mode==="2d").canvas,[320,640]),"Secondary viewport mismatch");
    if(map.rasterSources["scout-rudy-tw"])assert(map.rasterSources["scout-rudy-tw"].maxzoom===report.provenance.rudy_maxzoom,"Rudy zoom cap mismatch");
    const earlier=report.runs.find(r=>r.caseId===row.caseId);
    assert(same(map.layers,primary(earlier).layers)&&same(map.features,primary(earlier).features),"Layer/feature count changed within a case");
    for(const kind of ["rotation","pan"]){
      const phase=row.measurement?.[kind];
      assert(phase?.elapsedMs>=12000&&phase.elapsedMs<30000&&phase.primaryFrameTimes?.length>100,"Incomplete motion evidence");
      summarizeIntervals(intervals(phase.primaryFrameTimes),row.measurement.refreshMs);
      const jumps=phase.callbacks["2d.jumpTo"]?.calls||0;
      assert(row.caseId==="split_sync"?jumps>100:jumps===0,"Synchronization ablation did not execute as configured");
      assert((phase.callbacks["3d.moveend"]?.calls||0)<=6,"Driver generated artificial per-frame moveend work");
      if(row.caseId==="split_sync"&&kind==="pan")assert(phase.secondaryFrameTimes.length>100,"Panning peer did not render");
    }
  }
  const maps=Object.fromEntries(CASES.map(c=>[c,primary(report.runs.find(r=>r.caseId===c))]));
  const layers=id=>maps[id].layers.map(l=>l.id);
  assert(!layers("base").includes("scout-terrain-hillshade")&&layers("hillshade").includes("scout-terrain-hillshade"),"Hillshade ablation missing");
  assert(!layers("hillshade").includes("scout-rudy-tw")&&layers("rudy").includes("scout-rudy-tw"),"Rudy ablation missing");
  assert(maps.full.features["scout-terrain-candidates"].count>maps.rudy.features["scout-terrain-candidates"].count,"No nonempty candidate overlay difference");
  assert(same(maps.full.layers,maps.split_static.layers)&&same(maps.full.layers,maps.split_sync.layers),"Split case changed primary layers");
  assert(same(maps.full.features,maps.split_static.features)&&same(maps.full.features,maps.split_sync.features),"Split case changed primary features");
  return {status:"PASS",trials:18,blocks:3,meshSize:128,initialTerrainZooms:unique(referenceMap.terrainZooms),observedTerrainZooms:unique(reference.finalDiagnostics.find(d=>d.mode==="3d").observedTerrainZooms),preparedRoutePointCount:reference.scene.preparedRoutePointCount};
}

export function analyze(report){
  const parity=validateCapture(report),rows=report.runs.map(row=>{
    const metrics={firstReadySeconds:row.scene.phases.firstReadyMs/1000,dashboardDomMs:row.scene.phases.dashboardDomMs,
      peakRssMiB:row.peakRssBytes/2**20,readyRssMiB:row.readyMemory.rssBytes/2**20,readyHeapMiB:row.readyHeap.usedSize/2**20,
      setupQgisFilterMs:row.scene.setupCallbacks.qgisFeatureFilter?.totalMs||0,setupCandidateCollectionMs:row.scene.setupCallbacks.candidateCollection?.totalMs||0};
    for(const kind of ["rotation","pan"]){
      const phase=row.measurement[kind],cadence=summarizeIntervals(intervals(phase.primaryFrameTimes),row.measurement.refreshMs);
      metrics[`${kind}Fps`]=cadence.meanFps;metrics[`${kind}P95Ms`]=cadence.p95FrameMs;
      metrics[`${kind}DeficitPercent`]=cadence.estimatedMissedVsyncPercent;
      metrics[`${kind}SecondaryFrames`]=phase.secondaryFrameTimes.length;
      metrics[`${kind}SyncMs`]=phase.callbacks.syncDispatch?.totalMs||0;
      metrics[`${kind}PeerJumps`]=phase.callbacks["2d.jumpTo"]?.calls||0;
    }
    return {index:row.index,block:Math.floor((row.index-1)/6),caseId:row.caseId,metrics};
  });
  const summary=Object.fromEntries(CASES.map(caseId=>{
    const selected=rows.filter(r=>r.caseId===caseId),raw=report.runs.filter(r=>r.caseId===caseId),map=primary(raw[0]);
    const metrics=Object.fromEntries(Object.keys(selected[0].metrics).map(key=>[key,stats(selected.map(r=>r.metrics[key]))]));
    const callbacks={};
    for(const phase of ["rotation","pan"]){
      const names=[...new Set(raw.flatMap(r=>Object.keys(r.measurement[phase].callbacks)))];
      callbacks[phase]=Object.fromEntries(names.map(name=>[name,Object.fromEntries(["calls","totalMs","maxMs"].map(key=>[key,stats(raw.map(r=>r.measurement[phase].callbacks[name]?.[key]||0))]))]));
    }
    return [caseId,{trials:selected.length,mapCount:raw[0].scene.diagnostics.length,primaryLayerCount:map.layers.length,features:map.features,metrics,callbacks}];
  }));
  const contrasts=[["hillshade","base"],["rudy","hillshade"],["full","rudy"],["split_static","full"],["split_sync","split_static"]].map(([added,baseline])=>{
    const deltas=Object.fromEntries(Object.keys(rows[0].metrics).map(key=>[key,stats([0,1,2].map(block=>rows.find(r=>r.block===block&&r.caseId===added).metrics[key]-rows.find(r=>r.block===block&&r.caseId===baseline).metrics[key]))]));
    return {added,baseline,pairedBlockDeltas:deltas};
  });
  return {schemaVersion:"scout.dashboard_3d_cost_analysis.v1",status:"PASS",parity,machine:report.machine,browserVersion:report.browser.version,gpu:report.runs[0].gpu,
    capturedFrom:report.startedAt,capturedTo:report.finishedAt,summary,contrasts,rows,
    interpretation:{status:"DIRECTIONAL_ONLY",reason:"System load was not controlled and CPU/thermal state was not sampled per trial; capture parity PASS does not prove isolated causal timing costs"},
    limitations:[...report.limitations,"Rudy uses existing prepared Z14 cache; native higher-zoom tiles were missing", "Three trials per case; ranges and paired block differences are descriptive, not confidence intervals", "All cases retain full Dashboard DOM and candidate preparation; layer ablations isolate submitted map content", "Inactive/empty layers do not represent a populated workload; current structure lens contains 43 QGIS points", "Native Dashboard terrain LOD is retained, not forced to full source-pixel density"]};
}

if(process.argv[1]&&fileURLToPath(import.meta.url)===path.resolve(process.argv[1])){
  const [input,output,systemStateRef]=process.argv.slice(2);
  assert(input&&output&&path.resolve(input)!==path.resolve(output),"Supply capture and a different output file");
  const bytes=fs.readFileSync(input),result=analyze(JSON.parse(bytes));
  result.captureSha256=createHash("sha256").update(bytes).digest("hex");
  if(systemStateRef){
    const state=fs.readFileSync(systemStateRef);
    result.systemStateObservation={scope:"single late-capture system snapshot, not per-trial telemetry",text:state.toString(),sha256:createHash("sha256").update(state).digest("hex")};
  }
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(result,null,2)+"\n");
  console.log(JSON.stringify({status:result.status,parity:result.parity,captureSha256:result.captureSha256}));
}
