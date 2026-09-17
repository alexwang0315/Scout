/* Experimental instrumentation over unmodified Dashboard function bodies. */
(async () => {
  "use strict";
  const cases = {
    base: {label:"3D · DEM + prepared route",hillshade:false,rudy:false,overlays:false,split:false,sync:false},
    hillshade: {label:"3D + hillshade",hillshade:true,rudy:false,overlays:false,split:false,sync:false},
    rudy: {label:"3D + hillshade + cached Rudy",hillshade:true,rudy:true,overlays:false,split:false,sync:false},
    full: {label:"3D + all Dashboard candidate layers",hillshade:true,rudy:true,overlays:true,split:false,sync:false},
    split_static: {label:"Full 3D + stationary 2D",hillshade:true,rudy:true,overlays:true,split:true,sync:false},
    split_sync: {label:"Full 3D + original Dashboard 2D synchronization",hillshade:true,rudy:true,overlays:true,split:true,sync:true},
  };
  const caseId = new URLSearchParams(location.search).get("case") || "full", config = cases[caseId];
  const result = {status:"loading",caseId,config,errors:[],phases:{},authority:{visualization_only:true,candidate_only:true,runtime_safety_truth:false}};
  let counters={},frames=null,phase=null,primary,secondary,payload,renderMs=0;
  const tick=()=>new Promise(resolve=>requestAnimationFrame(resolve));
  const panel=document.createElement("section");panel.id="cost-panel";
  panel.innerHTML='<header id="cost-header"><strong>Dashboard 3D 成本量測</strong><small>既有 Workspace 投影回放 · candidate_only · 不代表目前導航狀態</small></header><div id="cost-maps"><div id="cost-primary"></div><div id="cost-secondary"></div></div><footer id="cost-footer"><button id="cost-measure" disabled>量測旋轉／平移</button><span id="cost-status" role="status">載入本機證據…</span></footer>';
  document.body.append(panel);
  const status=text=>document.querySelector("#cost-status").textContent=text;
  const fail=error=>{result.status="failed";result.errors.push(String(error?.message||error));status(result.errors.at(-1));};
  window.addEventListener("error",event=>fail(event.error||event.message));
  window.addEventListener("unhandledrejection",event=>fail(event.reason));
  const timed=(name,fn)=>function(...args){
    const started=performance.now();
    try{return fn.apply(this,args);}finally{
      const c=counters[name]||(counters[name]={calls:0,totalMs:0,maxMs:0});
      const duration=performance.now()-started;c.calls++;c.totalMs+=duration;c.maxMs=Math.max(c.maxMs,duration);
    }
  };
  const mapDiagnostics=entry=>{
    const map=entry.map,style=map.getStyle(),canvas=map.getCanvas();
    return {mode:entry.mode,canvas:[canvas.width,canvas.height],camera:navigationTerrainMapLibreCameraSnapshot(map),
      terrain:style.terrain||null,
      rasterSources:Object.fromEntries(Object.entries(style.sources).filter(([,s])=>s.type==="raster"||s.type==="raster-dem").map(([id,s])=>[id,{type:s.type,minzoom:s.minzoom,maxzoom:s.maxzoom,tileSize:s.tileSize,encoding:s.encoding,bounds:s.bounds}])),
      layers:style.layers.map(layer=>({id:layer.id,type:layer.type})),
      features:Object.fromEntries(Object.entries(style.sources).filter(([,s])=>s.type==="geojson").map(([id,s])=>[id,{count:s.data.features.length,kinds:s.data.features.reduce((r,f)=>{const k=f.properties.kind||f.properties.feature_class||"unknown";r[k]=(r[k]||0)+1;return r;},{})}])),
      meshSize:map.terrain?.meshSize||null,terrainZooms:map.terrain?.tileManager.getRenderableTiles().map(t=>t.tileID.canonical.z)||[],
      observedTerrainZooms:[...(map.costZooms||[])],centerElevation:entry.mode==="3d"?map.queryTerrainElevation(map.getCenter()):null};
  };
  const mount=()=>{
    for(const mode of ["3d","2d"]){
      const host=document.querySelector(`[data-navigation-terrain-pane="${mode}"]`);
      const target=document.querySelector(mode==="3d"?"#cost-primary":"#cost-secondary");
      target.replaceChildren();if(host)target.append(host);
    }
  };
  const originalRender=render;
  render=function(...args){const start=performance.now();const value=originalRender(...args);mount();renderMs+=performance.now()-start;return value;};
  const originalSync=synchronizeNavigationTerrainMapLibre;
  synchronizeNavigationTerrainMapLibre=timed("syncDispatch",entry=>config.sync?originalSync(entry):undefined);
  rememberNavigationTerrainMapLibreCamera=timed("rememberCamera",rememberNavigationTerrainMapLibreCamera);
  navigationTerrainMapLibreFeatureCollection=timed("candidateCollection",navigationTerrainMapLibreFeatureCollection);
  qgisSpatialWorkflowFeatures=timed("qgisFeatureFilter",qgisSpatialWorkflowFeatures);
  const originalStyle=navigationTerrainMapLibreStyle;
  navigationTerrainMapLibreStyle=timed("styleGeneration",(snapshot,mode)=>{
    const style=originalStyle(snapshot,mode);
    if(style.sources["scout-rudy-tw"])style.sources["scout-rudy-tw"].maxzoom=payload.provenance.rudy_maxzoom;
    if(!config.overlays){
      const keep=new Set(["scout-terrain-background","scout-route-halo","scout-route"]);
      if(config.hillshade)keep.add("scout-terrain-hillshade");if(config.rudy)keep.add("scout-rudy-tw");
      style.layers=style.layers.filter(l=>keep.has(l.id));
      style.sources["scout-terrain-candidates"].data.features=style.sources["scout-terrain-candidates"].data.features.filter(f=>f.properties.kind==="observed_route");
    }
    const used=new Set([style.terrain?.source,...style.layers.map(l=>l.source)].filter(Boolean));
    style.sources=Object.fromEntries(Object.entries(style.sources).filter(([id])=>used.has(id)));
    return style;
  });
  const waitReady=async()=>{
    const deadline=performance.now()+120000;
    while(performance.now()<deadline){
      if(result.errors.length)throw Error(result.errors.join("; "));
      const entries=navigationTerrainMapLibreRuntime.maps;
      if(entries.length===(config.split?2:1)&&entries.every(e=>e.host.dataset.navigationMaplibreStatus==="ready"&&e.map.areTilesLoaded())){
        await tick();await tick();return;
      }
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    throw Error("Dashboard maps did not become ready");
  };
  const animate=options=>new Promise((resolve,reject)=>{
    const map=primary.map;
    const timer=setTimeout(()=>reject(Error("Camera motion timed out")),options.duration+10000);
    map.once("moveend",()=>{clearTimeout(timer);resolve();});
    map.easeTo({...options,easing:t=>t,essential:true});
  });
  const motion=async(kind,seconds)=>{
    const origin=result.camera.center;
    primary.map.jumpTo(result.camera);
    await tick();await tick();
    if(kind==="rotation"){
      for(const bearing of [90,180,270,360])await animate({bearing,duration:seconds*250});
    }else{
      for(const [dx,dy]of [[.008,0],[.008,.006],[0,.006],[0,0]])await animate({center:[origin[0]+dx,origin[1]+dy],duration:seconds*250});
    }
  };
  const measure=async()=>{
    if(result.status!=="ready"&&result.status!=="complete")throw Error("Not ready to measure");
    const {summarizeIntervals}=await import("/assets/benchmark/common.mjs");
    const refresh=[];for(let i=0;i<90;i++)refresh.push(await tick());
    const delta=times=>times.slice(1).map((t,i)=>t-times[i]).filter(ms=>ms>0);
    const refreshSorted=delta(refresh).sort((a,b)=>a-b),refreshMs=refreshSorted[Math.floor(refreshSorted.length/2)];
    const measurements={refreshMs};
    for(const kind of ["rotation","pan"]){
      status(`${config.label} · ${kind} 暖機`);await motion(kind,4);await waitReady();
      if(document.visibilityState!=="visible")throw Error("Benchmark must remain foreground");
      result.status="measuring";phase=kind;counters={};frames={"3d":[],"2d":[]};const raf=[];
      let watching=true,hidden=false;
      const watch=t=>{if(!watching)return;raf.push(t);hidden ||= document.visibilityState!=="visible";requestAnimationFrame(watch);};requestAnimationFrame(watch);
      status(`${config.label} · ${kind} 量測中`);
      const started=performance.now();await motion(kind,12);const elapsed=performance.now()-started;
      watching=false;const saved=frames;frames=null;phase=null;
      if(hidden||innerWidth!==1280||innerHeight!==800)throw Error("Foreground or viewport changed");
      if(result.errors.length)throw Error(result.errors.join("; "));
      measurements[kind]={elapsedMs:elapsed,primary:summarizeIntervals(delta(saved["3d"]),refreshMs),
        secondary:saved["2d"].length>2?summarizeIntervals(delta(saved["2d"]),refreshMs):null,
        primaryFrameTimes:saved["3d"],secondaryFrameTimes:saved["2d"],rafIntervals:delta(raf),callbacks:structuredClone(counters)};
      await waitReady();
    }
    result.measurement=measurements;result.status="complete";
    result.diagnostics=navigationTerrainMapLibreRuntime.maps.map(mapDiagnostics);
    status("量測完成 · 完整資料由 Mac 工具保存");return measurements;
  };
  window.scoutDashboardCost={snapshot:()=>structuredClone(result),measure,diagnostics:()=>navigationTerrainMapLibreRuntime.maps.map(mapDiagnostics)};
  try{
    if(!config)throw Error("Unknown ablation case");
    const response=await fetch("/cost-data");if(!response.ok)throw Error(`Replay HTTP ${response.status}`);
    const bytes=await response.arrayBuffer();
    const sha=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(b=>b.toString(16).padStart(2,"0")).join("");
    if(sha!==response.headers.get("X-Source-Sha256"))throw Error("Replay hash mismatch");
    payload=JSON.parse(new TextDecoder().decode(bytes));result.payloadSha256=sha;result.provenance=payload.provenance;
    document.querySelector("#cost-header small").textContent=`既有 Workspace 投影回放 · Rudy 快取上限 Z${payload.provenance.rudy_maxzoom} · candidate_only · 非目前導航狀態`;
    result.phases.replayFetchMs=performance.now();
    const module=await import(NAVIGATION_MAPLIBRE_MODULE_URL);
    class InstrumentedMap extends module.Map{
      constructor(options){
        super({...options,pixelRatio:1});
        const mode=options.container.dataset.navigationMaplibreMap;
        this.costZooms=new Set();
        const originalOn=this.on;
        this.on=function(type,...args){
          if(type==="moveend"&&args.length===1&&String(args[0]).includes("rememberNavigationTerrainMapLibreCamera"))args[0]=timed(`${mode}.moveend`,args[0]);
          return originalOn.call(this,type,...args);
        };
        this.jumpTo=timed(`${mode}.jumpTo`,this.jumpTo);
        this.queryTerrainElevation=timed(`${mode}.queryTerrainElevation`,this.queryTerrainElevation);
        this.on("error",event=>fail(event.error||"MapLibre failure"));
        this.on("render",()=>{
          if(frames)frames[mode].push(performance.now());
          if(phase&&mode==="3d")for(const tile of this.terrain.tileManager.getRenderableTiles())this.costZooms.add(tile.tileID.canonical.z);
        });
      }
    }
    navigationTerrainMapLibreRuntime.modulePromise=Promise.resolve({...module,Map:InstrumentedMap});
    state.route="outdoor-navigation";state.project=payload.project;
    state.navigationTerrainData=payload.snapshot;state.navigationTerrainViewMode=config.split?"split":"terrain";
    state.navigationTerrainEvidenceDomain="observed";state.navigationTerrainLens="structure";state.navigationTerrainCandidateScope="route";
    if(payload.qgis){
      const q=payload.qgis;
      state.qgisSpatialWorkflow={workflow_run_id:q.workflow_run_id,workflow_id:q.workflow_id,state:q.state,maplibre_geojson:q.maplibre_geojson,candidate_only:true,runtime_safety_truth:false};
    }
    const points=payload.snapshot.route_samples.points,middle=points[Math.floor(points.length/2)];
    result.preparedRoutePointCount=points.length;
    result.camera={center:[Number(middle.lon??middle.longitude),Number(middle.lat??middle.latitude)],zoom:Number(payload.snapshot.terrain_raster_dem.minzoom)+1,pitch:45,bearing:0};
    if(!result.camera.center.every(Number.isFinite))throw Error("Recorded route midpoint missing");
    const scopeKey=navigationTerrainMapLibreCameraScope(payload.snapshot);
    navigationTerrainMapLibreRuntime.cameraByMode={"3d":{scopeKey,...result.camera},"2d":{scopeKey,center:result.camera.center,zoom:12,pitch:0,bearing:0}};
    document.querySelector("#cost-header strong").textContent=config.label;
    render();result.phases.dashboardDomMs=renderMs;
    await waitReady();primary=navigationTerrainMapLibreRuntime.maps.find(e=>e.mode==="3d");secondary=navigationTerrainMapLibreRuntime.maps.find(e=>e.mode==="2d");
    primary.map.painter.context.gl.finish();
    result.phases.firstReadyMs=performance.now();result.setupCallbacks=structuredClone(counters);
    result.diagnostics=navigationTerrainMapLibreRuntime.maps.map(mapDiagnostics);
    result.status="ready";status("就緒 · DEM / cached Rudy / recorded candidates · 不連線至外部服務");
    const button=document.querySelector("#cost-measure");button.disabled=false;button.onclick=()=>measure().catch(fail);
  }catch(error){fail(error);}
})();
