"use strict";

function validateParity(runs) {
  const reference=runs.find(row=>row.engine==="three");
  if(!reference||!runs.some(row=>row.engine==="maplibre"))throw Error("Both renderers must complete");
  let heightDelta=0,screenDelta=0;
  for(const row of runs) {
    if(row.status!=="PASS"||row.errors?.length)throw Error("Every trial must complete without errors");
    if(row.scene.inputSha256!==reference.scene.inputSha256)throw Error("Input fingerprints differ");
    if(JSON.stringify(row.scene.config)!==JSON.stringify(reference.scene.config))throw Error("Camera or viewport configuration differs");
    for(const diagnostic of [row.scene.diagnostics,...(row.measurement?[row.measurement.diagnostics]:[])]) {
      if(row.engine==="three") {
        if(diagnostic.meshVertices!==row.scene.input.meshVertices)throw Error("Three.js mesh was simplified");
      } else {
        const zooms=diagnostic.terrainTileZooms;
        if(!zooms?.length||[...zooms,...(diagnostic.observedTerrainTileZooms||[])].some(z=>2**(z-row.scene.input.demTileZoom)*diagnostic.meshSize!==row.scene.input.tileSize))throw Error("Native terrain mesh spacing differs from source pixels");
      }
    }
    if(row.probes.length!==reference.probes.length||!row.probes.length)throw Error("Missing camera probes");
    for(let turn=0;turn<reference.probes.length;turn++) {
      const left=reference.probes[turn],right=row.probes[turn];
      if(left.angle!==right.angle||left.points.length!==right.points.length||!left.points.length)throw Error("Mismatched camera probes");
      for(let i=0;i<left.points.length;i++) {
        const x=left.points[i],y=right.points[i];
        if(JSON.stringify(x.point)!==JSON.stringify(y.point))throw Error("Probe coordinates differ");
        if(!Number.isFinite(x.height)||!Number.isFinite(y.height))throw Error("Missing parity elevation");
        if(x.screen.length!==2||y.screen.length!==2||![...x.screen,...y.screen].every(Number.isFinite))throw Error("Invalid screen projection");
        heightDelta=Math.max(heightDelta,Math.abs(x.height-y.height));
        screenDelta=Math.max(screenDelta,Math.hypot(x.screen[0]-y.screen[0],x.screen[1]-y.screen[1]));
      }
    }
  }
  const result={inputSha256:reference.scene.inputSha256,trialsChecked:runs.length,maxHeightDeltaM:heightDelta,maxScreenDeltaPx:screenDelta,heightToleranceM:1,screenTolerancePx:5};
  result.status=heightDelta<=1&&screenDelta<=5?"PASS":"FAIL";
  return result;
}

function summarizeRuns(runs) {
  const median=values=>[...values].sort((a,b)=>a-b)[Math.floor(values.length/2)];
  return Object.fromEntries(["three","maplibre"].map(engine=>{
    const rows=runs.filter(row=>row.engine===engine);
    if(rows.length!==3||rows.some(row=>row.status!=="PASS"||!row.measurement))throw Error("Three completed measured trials per engine are required");
    return [engine,{runs:rows.length,medianFirstComplete3dMs:median(rows.map(r=>r.scene.phases.firstComplete3dMs)),
      medianEngineSetupMs:median(rows.map(r=>r.scene.phases.engineSetupMs)),medianMeanFps:median(rows.map(r=>r.measurement.rotation.meanFps)),
      medianFrameP95Ms:median(rows.map(r=>r.measurement.rotation.p95FrameMs)),
      medianEstimatedMissedVsyncPercent:median(rows.map(r=>r.measurement.rotation.estimatedMissedVsyncPercent)),
      medianPeakRssBytes:median(rows.map(r=>r.peakRssBytes)),medianReadyJsHeapBytes:median(rows.map(r=>r.readyHeap.usedSize))}];
  }));
}

module.exports={validateParity,summarizeRuns};
