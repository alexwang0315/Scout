#!/usr/bin/env node
"use strict";
const fs=require("node:fs"),path=require("node:path"),os=require("node:os");
const {execFile}=require("node:child_process"),{promisify}=require("node:util");
const exec=promisify(execFile);
const arg=(name,fallback)=>{const i=process.argv.indexOf(name);return i<0?fallback:process.argv[i+1];};
const {chromium}=require(arg("--playwright","playwright"));
const base=arg("--url","http://127.0.0.1:19129"),target=new URL(base);
const output=path.resolve(arg("--output","outputs/evals/dashboard-3d-cost/mac"));
const preflight=process.argv.includes("--preflight"),proof=process.argv.includes("--allow-non-mac-proof");
const selected=arg("--cases","").split(",").filter(Boolean);
const projectId="dongqing_batongguan_historic_trail_newImport";
if(!["localhost","127.0.0.1"].includes(target.hostname)||["8000","8080","9099","9127",""].includes(target.port))throw Error("Use a separate loopback experiment server");
if(os.platform()!=="darwin"&&!proof)throw Error("Performance measurement must run on the user's Mac");
fs.mkdirSync(output,{recursive:true});
const report={schemaVersion:"scout.dashboard_3d_cost.v1",status:"running",startedAt:new Date().toISOString(),
  machine:{platform:os.platform(),architecture:os.arch(),release:os.release(),memoryBytes:os.totalmem(),cpu:os.cpus()[0]?.model},
  preflight,proofOnly:proof,runs:[],limitations:["Recorded Workspace projection; current read-only interface reports not_prepared", "Fixed map sizes; unrelated Dashboard API bootstrap disabled", "Render event cadence, not compositor-confirmed display frames", "RSS includes shared pages; not dedicated GPU VRAM", "Fresh Chrome per trial; OS and server caches are not flushed", "Callback timings are inclusive and must not be summed across nested wrappers"]};
const save=()=>fs.writeFileSync(path.join(output,"report.json"),JSON.stringify(report,null,2));
async function memory(root){
  const {stdout}=await exec("ps",["-axo","pid=,ppid=,rss="]);
  const rows=stdout.trim().split("\n").map(l=>l.trim().split(/\s+/).map(Number)),owned=new Set([root]);let changed=true;
  while(changed){changed=false;for(const [pid,ppid]of rows)if(owned.has(ppid)&&!owned.has(pid)){owned.add(pid);changed=true;}}
  const selected=rows.filter(([pid])=>owned.has(pid));return {rssBytes:selected.reduce((sum,r)=>sum+r[2]*1024,0),processCount:selected.length};
}
async function run(caseId,index){
  const row={caseId,index,status:"running",startedAt:new Date().toISOString(),errors:[],warnings:[],requests:[],failedRequests:[],loadingFailures:[],cancelledTileRequests:[],memorySamples:[]};report.runs.push(row);save();
  const browser=await chromium.launch({headless:proof,executablePath:proof?undefined:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",args:proof?["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"]:[]});
  let interval,pending=null;
  try{
    const bcdp=await browser.newBrowserCDPSession(),info=await bcdp.send("SystemInfo.getProcessInfo");
    const root=info.processInfo.find(p=>p.type==="browser")?.id;if(!root)throw Error("Missing owned browser PID");
    report.browser={version:browser.version(),...(await bcdp.send("SystemInfo.getInfo"))};
    const context=await browser.newContext({viewport:{width:1280,height:800},deviceScaleFactor:1});
    await context.route("**/*",route=>{
      const r=route.request();
      if(new URL(r.url()).origin!==target.origin||!["GET","HEAD"].includes(r.method())){row.errors.push({kind:"blocked",method:r.method(),url:r.url()});return route.abort();}
      row.requests.push({url:r.url(),type:r.resourceType()});return route.continue();
    });
    const page=await context.newPage();await page.bringToFront();const cdp=await context.newCDPSession(page);
    await cdp.send("Network.enable");await cdp.send("Network.setCacheDisabled",{cacheDisabled:true});
    const networkRequests=new Map();
    cdp.on("Network.requestWillBeSent",event=>networkRequests.set(event.requestId,{url:event.request.url,method:event.request.method}));
    cdp.on("Network.loadingFailed",event=>row.loadingFailures.push({...networkRequests.get(event.requestId),cancelled:event.canceled===true,errorText:event.errorText}));
    page.on("pageerror",e=>row.errors.push({kind:"pageerror",message:e.message}));
    page.on("console",e=>{if(e.type()==="error")row.errors.push({kind:"console",message:e.text()});else if(e.type()==="warning")row.warnings.push(e.text());});
    page.on("response",r=>{if(r.status()>=400)row.errors.push({kind:"http",status:r.status(),url:r.url()});});
    page.on("requestfailed",r=>row.failedRequests.push({kind:"requestfailed",message:r.failure()?.errorText,url:r.url(),method:r.method()}));
    row.blankMemory=await memory(root);
    interval=setInterval(()=>{if(pending)return;pending=memory(root).then(m=>row.memorySamples.push({time:Date.now(),...m})).catch(e=>{row.memoryError=e.message;}).finally(()=>{pending=null;});},500);
    await page.goto(`${base}/dashboard-cost?case=${caseId}&projectId=${projectId}`,{waitUntil:"domcontentloaded",timeout:120000});
    await page.waitForFunction(()=>["ready","failed"].includes(window.scoutDashboardCost?.snapshot().status),null,{timeout:180000});
    row.scene=await page.evaluate(()=>window.scoutDashboardCost.snapshot());
    if(row.scene.status!=="ready")throw Error(JSON.stringify(row.scene.errors));
    report.provenance ||= row.scene.provenance;delete row.scene.provenance;
    row.gpu=await page.evaluate(()=>{
      const gl=document.querySelector('#cost-primary canvas').getContext('webgl2'),ext=gl?.getExtension('WEBGL_debug_renderer_info');
      return ext?{vendor:gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),renderer:gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)}:null;
    });
    if(!row.gpu||(!proof&&/swiftshader|llvmpipe|software/i.test(row.gpu.renderer)))throw Error("Hardware GPU renderer not verified");
    row.readyMemory=await memory(root);row.readyHeap=await cdp.send("Runtime.getHeapUsage");
    console.log(`READY ${index} ${caseId}: ${row.scene.phases.firstReadyMs.toFixed(0)} ms`);save();
    await page.screenshot({path:path.join(output,`${index}-${caseId}.png`)});
    if(!preflight)row.measurement=await page.evaluate(()=>window.scoutDashboardCost.measure());
    row.finalDiagnostics=await page.evaluate(()=>window.scoutDashboardCost.diagnostics());
    row.finalTilesLoaded=await page.evaluate(()=>navigationTerrainMapLibreRuntime.maps.every(e=>e.map.areTilesLoaded()&&e.host.dataset.navigationMaplibreStatus==="ready"));
    row.finalMemory=await memory(root);row.finalHeap=await cdp.send("Runtime.getHeapUsage");
    clearInterval(interval);if(pending)await pending;
    row.peakRssBytes=Math.max(row.blankMemory.rssBytes,row.readyMemory.rssBytes,row.finalMemory.rssBytes,...row.memorySamples.map(s=>s.rssBytes));
    row.resourceSummary=await page.evaluate(()=>{
      const rows=performance.getEntriesByType('resource');return {count:rows.length,transferBytes:rows.reduce((sum,r)=>sum+r.transferSize,0),decodedBytes:rows.reduce((sum,r)=>sum+r.decodedBodySize,0)};
    });
    for(const failure of row.failedRequests){
      const tile=/^\/(?:cost-dem\/\d+\/\d+\/\d+\.png|admin\/tiles\/imagery\/[^/]+\/imagery\/\d+\/\d+\/\d+\.png)$/.test(new URL(failure.url).pathname);
      const cancelled=row.loadingFailures.some(f=>f.url===failure.url&&f.cancelled&&f.errorText==="net::ERR_ABORTED");
      if(tile&&failure.method==="GET"&&failure.message==="net::ERR_ABORTED"&&cancelled&&row.finalTilesLoaded)row.cancelledTileRequests.push(failure);
      else row.errors.push(failure);
    }
    if(row.errors.length||!row.finalTilesLoaded)throw Error(JSON.stringify({errors:row.errors,finalTilesLoaded:row.finalTilesLoaded}));
    const primary=row.scene.diagnostics.find(d=>d.mode==="3d");
    if(JSON.stringify(primary.canvas)!==JSON.stringify([960,640])||primary.camera.zoom!==14||primary.camera.pitch!==45||!Number.isFinite(primary.centerElevation))throw Error("Unexpected 3D geometry or missing DEM");
    row.status="PASS";console.log(`PASS ${index} ${caseId}${row.measurement?`: rotation ${row.measurement.rotation.primary.meanFps.toFixed(2)} FPS / pan ${row.measurement.pan.primary.meanFps.toFixed(2)} FPS`:''}`);
  }catch(error){row.status="FAIL";row.error=error.stack;throw error;}
  finally{clearInterval(interval);if(pending)await pending;await browser.close();row.finishedAt=new Date().toISOString();save();}
}
(async()=>{
  const normal=["base","hillshade","rudy","full","split_static","split_sync"];
  const cases=selected.length?selected:normal;
  if(cases.some(c=>!normal.includes(c)))throw Error("Unknown case");
  const order=preflight?cases:selected.length?[...cases,...cases.toReversed(),...cases]:[...normal,...normal.toReversed(),"rudy","split_sync","base","full","hillshade","split_static"];
  for(let i=0;i<order.length;i++){console.log(`START ${i+1}/${order.length} ${order[i]}`);await run(order[i],i+1);}
  const first=report.runs[0].scene;
  for(const r of report.runs){
    if(r.scene.payloadSha256!==first.payloadSha256||JSON.stringify(r.scene.camera)!==JSON.stringify(first.camera))throw Error("Recorded data or primary camera changed between trials");
  }
  report.status=proof?"NON_MAC_PROOF_ONLY":"PASS";
})().catch(e=>{report.status="FAIL";report.error=e.stack;console.error(e);process.exitCode=1;}).finally(()=>{report.finishedAt=new Date().toISOString();save();});
