import * as maplibregl from "/benchmark-maplibre/maplibre-gl.mjs";
import {ELEVATION_COLOR_STOPS} from "../terrain.mjs";

export async function createAdapter(host,common,onRender,onFailure) {
  const {dem,model,mesh,config}=common;
  const bounds=dem.bounds_wgs84,css=getComputedStyle(document.documentElement),color=token=>css.getPropertyValue(`--${token}`).trim();
  maplibregl.addProtocol("scoutbench",async request=>{
    const key=request.url.replace("scoutbench://","").split("?")[0];
    const body=common.tiles.get(key);
    if(!body)throw Error(`Requested tile outside benchmark manifest: ${key}`);
    return {data:body.slice(0)};
  });
  const features=[...model.segments.map((segment,index)=>({type:"Feature",properties:{kind:"route",segment:index},geometry:{type:"LineString",coordinates:segment.points.map(p=>[p.lon,p.lat])}})),
    ...model.nodes.map(node=>({type:"Feature",properties:{kind:node.kind,id:node.id},geometry:{type:"Point",coordinates:[node.lon,node.lat]}}))];
  const ramp=["interpolate",["linear"],["elevation"],...ELEVATION_COLOR_STOPS.flatMap(s=>[mesh.minimum_elevation_m+s.fraction*(mesh.maximum_elevation_m-mesh.minimum_elevation_m),color(s.token)])];
  const demSource={type:"raster-dem",tiles:["scoutbench://{z}/{x}/{y}"],tileSize:dem.tile_size,minzoom:dem.minzoom,maxzoom:dem.maxzoom,bounds:[bounds.west,bounds.south,bounds.east,bounds.north],encoding:"mapbox"};
  const map=new maplibregl.Map({container:host,pixelRatio:config.pixelRatio,canvasContextAttributes:{antialias:true,preserveDrawingBuffer:true},
    center:config.center,zoom:config.zoom,pitch:config.pitch,bearing:0,maxPitch:80,renderWorldCopies:false,attributionControl:false,interactive:false,
    style:{version:8,transition:{duration:0,delay:0},sources:{dem:{...demSource},"dem-colors":{...demSource},
      features:{type:"geojson",data:{type:"FeatureCollection",features},tolerance:0}},
    terrain:{source:"dem",exaggeration:1},layers:[
      {id:"background",type:"background",paint:{"background-color":color("bg")}},
      {id:"dem-height-colors",type:"color-relief",source:"dem-colors",paint:{"color-relief-color":ramp}},
      {id:"gpx-segments",type:"line",source:"features",filter:["==",["get","kind"],"route"],paint:{"line-color":color("accent"),"line-width":3},layout:{"line-cap":"round","line-join":"round"}},
      {id:"source-nodes",type:"circle",source:"features",filter:["!=",["get","kind"],"route"],paint:{"circle-radius":5,"circle-color":["match",["get","kind"],"start",color("ok"),"end",color("warn"),color("accent")],"circle-stroke-color":color("bg"),"circle-stroke-width":1}}
    ]}});
  map.on("error",event=>onFailure(event.error?.message||"MapLibre error"));
  let validateDetail=false;
  const observedTerrainTileZooms=new Set();
  map.on("render",()=>{
    onRender();
    if(validateDetail)for(const tile of map.terrain.tileManager.getRenderableTiles()) {
      const zoom=tile.tileID.canonical.z;observedTerrainTileZooms.add(zoom);
      if(2**(zoom-dem.minzoom)*map.terrain.meshSize!==dem.tile_size)onFailure("Native terrain mesh spacing changed during rotation");
    }
  });
  map.once("load",()=>{
    map.setVerticalFieldOfView(config.fov);
    // One terrain LOD across this bounded viewport; retain native tile culling.
    map.setSourceTileLodParams(1,16,"dem");
    map.setSourceTileLodParams(1,16,"dem-colors");
  });
  await new Promise((resolve,reject)=>{map.once("idle",resolve);map.once("error",event=>reject(event.error));});
  if(!Number.isFinite(map.queryTerrainElevation(config.center)))throw Error("Native DEM not decoded");
  map.painter.context.gl.finish();
  validateDetail=true;
  return {engine:"maplibre",version:maplibregl.getVersion(),pose:bearing=>map.jumpTo({center:config.center,zoom:config.zoom,pitch:config.pitch,bearing}),
    sample:point=>map.queryTerrainElevation(point),project:point=>{const p=map.project(point);return [p.x,p.y];},
    diagnostics:()=>({meshSize:map.terrain.meshSize,terrainTileZooms:map.terrain.tileManager.getRenderableTiles().map(t=>t.tileID.canonical.z),observedTerrainTileZooms:[...observedTerrainTileZooms],
      zoom:map.getZoom(),pitch:map.getPitch(),fov:map.getVerticalFieldOfView(),elevation:map.getCenterElevation(),layers:map.getStyle().layers.map(l=>l.id)}),
    dispose:()=>{map.remove();maplibregl.removeProtocol("scoutbench");}};
}
