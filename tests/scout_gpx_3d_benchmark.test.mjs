import assert from "node:assert/strict";
import test from "node:test";
import {summarizeIntervals} from "../docs/admin/experiments/gpx-3d/benchmark/common.mjs";
import {validateParity} from "../tools/scout_gpx_3d_benchmark_metrics.cjs";

test("frame estimates use the measured refresh interval, including 120 Hz",()=>{
  for(const refresh of [1000/60,1000/120]) {
    const result=summarizeIntervals([refresh,refresh,refresh*2,refresh*4],refresh);
    assert.equal(result.estimatedMissedVsyncs,4);
    assert.equal(result.estimatedMissedVsyncPercent,50);
    assert.equal(result.longFrames,2);
    assert.equal(result.p95FrameMs,refresh*4);
    assert.equal(summarizeIntervals([refresh,refresh],refresh).estimatedMissedVsyncs,0);
  }
});

test("missing or non-finite timings cannot become successful measurements",()=>{
  for(const intervals of [[],[NaN],[0],[-1],[Infinity]])assert.throws(()=>summarizeIntervals(intervals,16.67));
  assert.throws(()=>summarizeIntervals([16.67],Infinity));
});

test("sustained 50 FPS on a 60 Hz cadence includes cumulative missed updates",()=>{
  const result=summarizeIntervals(Array(600).fill(20),1000/60);
  assert.equal(result.estimatedMissedVsyncs,120);
  assert.ok(Math.abs(result.estimatedMissedVsyncPercent-100/6)<1e-9);
});

function trial(engine) {
  return {engine,status:"PASS",errors:[],scene:{inputSha256:"same",config:{zoom:14,pixelRatio:1},input:{meshVertices:4,demTileZoom:13,tileSize:256},
    diagnostics:engine==="three"?{meshVertices:4}:{meshSize:128,terrainTileZooms:[14]}},probes:[{angle:0,points:[{point:[121,23],height:1234,screen:[640,360]}]}]};
}

test("all trials must retain the same inputs and camera, not only the first pair",()=>{
  const rows=[trial("three"),trial("maplibre"),trial("maplibre")];
  assert.equal(validateParity(rows).status,"PASS");
  rows[2].scene.inputSha256="changed";
  assert.throws(()=>validateParity(rows),/fingerprints/);
  rows[2]=trial("maplibre");rows[2].scene.config.zoom=13;
  assert.throws(()=>validateParity(rows),/configuration/);
});

test("height/projection mismatches or renderer errors prevent a fair-comparison claim",()=>{
  const a=trial("three"),b=trial("maplibre");
  b.probes[0].points[0].height+=2;
  assert.equal(validateParity([a,b]).status,"FAIL");
  b.probes[0].points[0].height=1234;b.probes[0].points[0].screen[0]+=6;
  assert.equal(validateParity([a,b]).status,"FAIL");
  b.probes[0].points[0].screen[0]=NaN;
  assert.throws(()=>validateParity([a,b]),/projection/);
  b.errors.push("terrain failed");
  assert.throws(()=>validateParity([a,b]),/without errors/);
});

test("identical DEM bytes do not excuse a coarser mesh or lower LOD",()=>{
  const a=trial("three"),b=trial("maplibre");
  b.scene.diagnostics.terrainTileZooms=[13,14];
  assert.throws(()=>validateParity([a,b]),/mesh spacing/);
  b.scene.diagnostics.terrainTileZooms=[14];a.scene.diagnostics.meshVertices=3;
  assert.throws(()=>validateParity([a,b]),/simplified/);
});
