#!/usr/bin/env node
"use strict";

// Runs an isolated browser on the machine being measured. No real browser
// profile, Workspace writes, production runtime, or third-party endpoints.
const fs=require("node:fs"),path=require("node:path"),os=require("node:os");
const {execFile}=require("node:child_process"),{promisify}=require("node:util");
const exec=promisify(execFile);
const {validateParity,summarizeRuns}=require("./scout_gpx_3d_benchmark_metrics.cjs");
const arg=(name,fallback)=>{const i=process.argv.indexOf(name);return i<0?fallback:process.argv[i+1];};
const {chromium}=require(arg("--playwright", "playwright"));
const base=arg("--url","http://127.0.0.1:19128"),source=arg("--gpx","839bf9fac6f2fd73995a71ed");
const output=path.resolve(arg("--output","outputs/evals/scout-gpx-3d/benchmark"));
const preflight=process.argv.includes("--preflight"),proofOnly=process.argv.includes("--allow-non-mac-proof");
const target=new URL(base);
if(!["localhost","127.0.0.1"].includes(target.hostname)||["8000","8080","9099",""] .includes(target.port))throw Error("Use a separate loopback benchmark endpoint");
if(os.platform()!=="darwin"&&!proofOnly)throw Error("Mac results require running this tool on macOS");
fs.mkdirSync(output,{recursive:true});
const report={schemaVersion:"scout.renderer_benchmark.v1",status:"running",startedAt:new Date().toISOString(),phase:preflight?"parity_preflight":"measurement",
  machine:{platform:os.platform(),architecture:os.arch(),osRelease:os.release(),memoryBytes:os.totalmem(),cpu:os.cpus()[0]?.model},
  browser:{},runs:[],parity:null,limitations:["Isolated native renderers, not full Dashboard UI overhead", "Frame submission / rAF intervals estimate missed vsyncs; not physical display presentation counts", "Process-tree RSS includes shared pages and is not dedicated GPU VRAM", "Fresh browser profiles; OS, disk and server caches are not flushed"]};
const save=()=>fs.writeFileSync(path.join(output,"report.json"),JSON.stringify(report,null,2));

async function processMemory(root) {
  const {stdout}=await exec("ps",["-axo","pid=,ppid=,rss="]);
  const rows=stdout.trim().split("\n").map(line=>line.trim().split(/\s+/).map(Number));
  const owned=new Set([root]);let changed=true;
  while(changed){changed=false;for(const [pid,ppid]of rows)if(owned.has(ppid)&&!owned.has(pid)){owned.add(pid);changed=true;}}
  const selected=rows.filter(([pid])=>owned.has(pid));
  return {rssBytes:selected.reduce((sum,row)=>sum+row[2]*1024,0),processCount:selected.length};
}

async function run(engine,index) {
  const errors=[],warnings=[],requests=[],samples=[];
  const browser=await chromium.launch({headless:proofOnly,executablePath:proofOnly?undefined:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    args:proofOnly?["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"]:[]});
  let interval;
  const row={index,engine,status:"running",startedAt:new Date().toISOString(),loadAverage:os.loadavg(),errors,warnings,requests};
  report.runs.push(row);save();
  try {
    const browserCdp=await browser.newBrowserCDPSession();
    const processes=await browserCdp.send("SystemInfo.getProcessInfo");
    const root=processes.processInfo.find(p=>p.type==="browser")?.id;
    if(!root)throw Error("Cannot identify owned Chrome process tree");
    report.browser={version:browser.version(),...(await browserCdp.send("SystemInfo.getInfo"))};
    const context=await browser.newContext({viewport:{width:1280,height:800},deviceScaleFactor:1});
    await context.route("**/*",route=>{
      const request=route.request();
      if(new URL(request.url()).origin!==target.origin||!["GET","HEAD"].includes(request.method())){errors.push({kind:"blocked_request",url:request.url(),method:request.method()});return route.abort();}
      requests.push(request.url());return route.continue();
    });
    const page=await context.newPage();
    await page.bringToFront();
    const pageCdp=await context.newCDPSession(page);
    await pageCdp.send("Network.enable");await pageCdp.send("Network.setCacheDisabled",{cacheDisabled:true});
    page.on("pageerror",error=>errors.push({kind:"pageerror",message:error.message}));
    page.on("console",message=>{if(message.type()==="error")errors.push({kind:"console",message:message.text()});else if(message.type()==="warning")warnings.push(message.text());});
    page.on("requestfailed",request=>errors.push({kind:"network",url:request.url(),message:request.failure()?.errorText}));
    page.on("response",response=>{if(response.status()>=400)errors.push({kind:"http",url:response.url(),status:response.status()});});
    row.blankMemory=await processMemory(root);
    let polling=false;
    interval=setInterval(async()=>{if(polling)return;polling=true;try{samples.push({time:Date.now(),...await processMemory(root)});}catch(error){row.memorySamplingError=error.message;}finally{polling=false;}},500);
    await page.goto(`${base}/benchmark?engine=${engine}&gpx=${source}`,{waitUntil:"domcontentloaded",timeout:180000});
    await page.waitForFunction(()=>["ready","failed"].includes(window.scoutBenchmark?.snapshot().status),null,{timeout:300000});
    row.scene=await page.evaluate(()=>window.scoutBenchmark.snapshot());
    if(row.scene.status!=="ready")throw Error(JSON.stringify(row.scene.errors));
    console.log(`READY ${index} ${engine}: ${row.scene.phases.firstComplete3dMs.toFixed(0)}ms`);save();
    row.viewport=await page.evaluate(()=>{const canvas=document.querySelector("#bench-map canvas");return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,canvasWidth:canvas.width,canvasHeight:canvas.height,visibility:document.visibilityState};});
    if(JSON.stringify(row.viewport)!==JSON.stringify({width:1280,height:800,dpr:1,canvasWidth:1280,canvasHeight:720,visibility:"visible"}))throw Error("Unexpected actual viewport or drawing buffer");
    row.readyMemory=await processMemory(root);row.readyHeap=await pageCdp.send("Runtime.getHeapUsage");
    row.gpu=await page.evaluate(()=>{
      const gl=document.querySelector("#bench-map canvas").getContext("webgl2"),ext=gl?.getExtension("WEBGL_debug_renderer_info");
      return ext?{vendor:gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),renderer:gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)}:null;
    });
    if(!row.gpu)throw Error("Cannot verify actual GPU renderer");
    if(!proofOnly&&/swiftshader|llvmpipe|software/i.test(row.gpu.renderer))throw Error("Mac benchmark is using software rendering");
    row.probes=[];
    for(const angle of [0,90]) {
      await page.evaluate(angle=>window.scoutBenchmark.pose(angle),angle);
      await page.waitForTimeout(250);
      row.probes.push({angle,points:await page.evaluate(()=>window.scoutBenchmark.probes())});
    }
    await page.screenshot({path:path.join(output,`${index}-${engine}-ready.png`)});
    if(!preflight)row.measurement=await page.evaluate(()=>window.scoutBenchmark.measure());
    row.finalMemory=await processMemory(root);row.finalHeap=await pageCdp.send("Runtime.getHeapUsage");
    row.peakRssBytes=Math.max(row.blankMemory.rssBytes,row.readyMemory.rssBytes,row.finalMemory.rssBytes,...samples.map(s=>s.rssBytes));
    row.memorySamples=samples;row.peakRssAboveBlankBytes=row.peakRssBytes-row.blankMemory.rssBytes;
    if(errors.length)throw Error(JSON.stringify(errors));
    row.status="PASS";console.log(`PASS ${index} ${engine}: ready=${row.scene.phases.firstComplete3dMs.toFixed(0)}ms RSS peak=${Math.round(row.peakRssBytes/1048576)}MiB`);
  }catch(error){row.status="FAIL";row.error=error.stack;throw error;}
  finally{clearInterval(interval);await browser.close();row.finishedAt=new Date().toISOString();save();}
}

function parity() {
  report.parity=validateParity(report.runs);
  if(report.parity.status!=="PASS")throw Error(`Parity gate failed: ${JSON.stringify(report.parity)}`);
}

(async()=>{
  const order=preflight?["three","maplibre"]:["three","maplibre","maplibre","three","three","maplibre"];
  for(let i=0;i<order.length;i++){console.log(`START ${i+1}/${order.length} ${order[i]}`);await run(order[i],i+1);if(i===1)parity();}
  parity();
  if(!preflight)report.summary=summarizeRuns(report.runs);
  report.status=proofOnly?"NON_MAC_PROOF_ONLY":"PASS";
})().catch(error=>{report.status="FAIL";report.error=error.stack;process.exitCode=1;console.error(error);}).finally(()=>{report.finishedAt=new Date().toISOString();save();});
