import {parseGpx} from "../gpx.mjs";
import {meshElevation} from "../terrain.mjs";

export const CIRCUMFERENCE = 2 * Math.PI * 6378137;
export const CONFIG = Object.freeze({width:1280,height:800,mapHeight:720,pixelRatio:1,pitch:45,fov:36.86989764584402,zoom:14,bearing:0,rotationSeconds:12,warmupSeconds:4});
export const sha256 = async bytes => [...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(b=>b.toString(16).padStart(2,"0")).join("");
export async function fetchBytes(url) {
  const response=await fetch(url,{cache:"no-store"});
  if(!response.ok)throw Error(`${url}: HTTP ${response.status}`);
  return response.arrayBuffer();
}
const fetchJson=async url=>JSON.parse(new TextDecoder().decode(await fetchBytes(url)));

export async function loadCommon(sourceId) {
  if(!sourceId)throw Error("Explicit GPX source id required");
  const catalog=await fetchJson("/api/catalog");
  const source=catalog.sources.find(s=>s.id===sourceId);
  if(!source)throw Error("Selected GPX is not in this Workspace");
  const [raw,dem,cpBytes]=await Promise.all([fetchBytes(`/api/gpx/${sourceId}`),fetchJson("/api/terrain"),fetchBytes(`/api/checkpoints/${sourceId}`)]);
  const cp=JSON.parse(new TextDecoder().decode(cpBytes));
  if(await sha256(raw)!==source.sha256)throw Error("GPX hash changed");
  if(dem.status!=="ready")throw Error("Prepared terrain unavailable; benchmark cannot use fallback");
  const model=parseGpx(new TextDecoder("utf-8",{fatal:true}).decode(raw),source.source_ref);
  model.nodes.push(...cp.nodes);
  const block=dem.tile_block,size=dem.tile_size;
  const width=(block.x_max-block.x_min+1)*size,height=(block.y_max-block.y_min+1)*size;
  const elevations=new Float32Array(width*height).fill(NaN),tiles=new Map();
  const bytes=await Promise.all(dem.tiles.map(async tile=>{
    const body=await fetchBytes(`/api/terrain/${tile.z}/${tile.x}/${tile.y}.png`);
    if(await sha256(body)!==tile.sha256)throw Error("DEM tile hash mismatch");
    return {tile,body};
  }));
  let minimum=Infinity,maximum=-Infinity;
  for(const {tile,body} of bytes) {
    tiles.set(`${tile.z}/${tile.x}/${tile.y}`,body);
    const bitmap=await createImageBitmap(new Blob([body],{type:"image/png"}),{colorSpaceConversion:"none",premultiplyAlpha:"none"});
    if(bitmap.width!==size||bitmap.height!==size)throw Error("Tile dimensions changed");
    const canvas=document.createElement("canvas");canvas.width=canvas.height=size;
    const context=canvas.getContext("2d",{willReadFrequently:true});context.drawImage(bitmap,0,0);bitmap.close();
    const pixels=context.getImageData(0,0,size,size).data;
    const x0=(tile.x-block.x_min)*size,y0=(tile.y-block.y_min)*size;
    for(let row=0;row<size;row++)for(let column=0;column<size;column++) {
      const i=(row*size+column)*4;
      if(pixels[i+3]!==255)throw Error("Missing DEM support; refusing zero terrain");
      const h=-10000+(pixels[i]*65536+pixels[i+1]*256+pixels[i+2])*.1;
      elevations[(y0+row)*width+x0+column]=h;
      minimum=Math.min(minimum,h);maximum=Math.max(maximum,h);
    }
  }
  if(elevations.some(h=>!Number.isFinite(h)))throw Error("Incomplete DEM block");
  const pixel=CIRCUMFERENCE/(2**dem.minzoom*size);
  // Match the pinned MapLibre DEMData pixel-coordinate convention. This is a
  // benchmark adapter, not a georeferencing correction to Workspace artifacts.
  const mesh={status:"ready",source:dem,width,height,elevations,step_m:pixel,
    x0:block.x_min*size*pixel-CIRCUMFERENCE/2,y0:CIRCUMFERENCE/2-block.y_min*size*pixel,
    minimum_elevation_m:minimum,maximum_elevation_m:maximum,vertical_datum:dem.vertical_datum};
  const middle=model.points[Math.floor(model.points.length/2)];
  const center=[middle.lon,middle.lat];
  if(meshElevation(mesh,...center)===null)throw Error("Route midpoint outside common DEM");
  const input={sourceId,sourceSha256:source.sha256,cpSha256:await sha256(cpBytes),demFingerprint:dem.source_fingerprint,
    tileHashes:dem.tiles.map(t=>t.sha256),tileCount:tiles.size,demTileZoom:dem.minzoom,tileSize:size,pointCount:model.points.length,
    segments:model.segments.map(s=>s.points.length),nodeCount:model.nodes.length,
    pixelSpacingGroundM:pixel*Math.cos(center[1]*Math.PI/180),meshVertices:width*height,
    layers:["dem-height-colors","gpx-segments","source-nodes"],center};
  return {model,mesh,dem,tiles,input,inputSha256:await sha256(new TextEncoder().encode(JSON.stringify(input))),config:{...CONFIG,zoom:dem.minzoom+1,center}};
}

export function summarizeIntervals(intervals,refreshMs) {
  if(!intervals.length||!Number.isFinite(refreshMs)||refreshMs<=0||intervals.some(ms=>!Number.isFinite(ms)||ms<=0))throw Error("No valid frames");
  const sorted=[...intervals].sort((a,b)=>a-b),quantile=q=>sorted[Math.ceil(q*sorted.length)-1];
  const duration=intervals.reduce((a,b)=>a+b,0);
  // Round across the complete observation window. Per-interval rounding would
  // wrongly report zero misses for sustained 50 FPS on a 60 Hz display.
  const expected=Math.max(intervals.length,Math.round(duration/refreshMs));
  const missed=expected-intervals.length;
  return {frameCount:intervals.length,medianFrameMs:quantile(.5),p95FrameMs:quantile(.95),p99FrameMs:quantile(.99),maxFrameMs:sorted.at(-1),
    meanFps:1000/(duration/intervals.length),observedDurationMs:duration,expectedFrameIntervals:expected,longFrames:intervals.filter(ms=>ms>refreshMs*1.5).length,
    estimatedMissedVsyncs:missed,estimatedMissedVsyncPercent:100*missed/(intervals.length+missed),refreshMs,
    semantics:"render-update deficit against measured refresh cadence; not compositor presentation counts"};
}
