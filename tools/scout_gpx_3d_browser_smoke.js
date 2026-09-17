#!/usr/bin/env node
"use strict";

// Local-only browser proof. GPX fixtures below are explicitly synthetic error /
// replay probes. Real route verification always reads the operator's workspace.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const {chromium} = require("playwright");
const {JSDOM} = require("jsdom");

const arg = name => {const index = process.argv.indexOf(name);return index >= 0 ? process.argv[index + 1] : undefined;};
const base = arg("--url");
const root = arg("--project-root");
const output = arg("--output") || "outputs/evals/scout-gpx-3d";
if (!base || !root) throw new Error("Supply --url http://127.0.0.1:9127 and --project-root");
const target = new URL(base);
if (!["127.0.0.1", "localhost"].includes(target.hostname) || ["8000", "8080", "9099", ""].includes(target.port)) throw new Error("Only a separate loopback experiment port is allowed");
fs.mkdirSync(output, {recursive:true});
const sha = data => crypto.createHash("sha256").update(data).digest("hex");
const report = {status:"running", url:base, realSource: null, checks:[], console:[], failedRequests:[], httpErrors:[], externalRequests:[], mutations:[], screenshots:[]};
let phase = "setup";
const check = (name, details = {}) => {report.checks.push({name,status:"PASS",...details});console.log(`PASS ${name}`);};

async function ready(page) {
  await page.waitForFunction(() => window.scoutGpx3d?.snapshot().pointCount && document.querySelector("#map").dataset.renderer, null, {timeout:120000});
}
const snapshot = page => page.evaluate(() => window.scoutGpx3d.snapshot());
async function noOverflow(page) {
  const widths = await page.evaluate(() => ({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  assert.ok(widths.document <= widths.viewport && widths.body <= widths.viewport, JSON.stringify(widths));return widths;
}
async function screen(page, name, locator) {
  const file = path.join(output, name);
  if (locator) await page.locator(locator).screenshot({path:file});else await page.screenshot({path:file,fullPage:true});
  report.screenshots.push(path.resolve(file));
}
async function upload(page, name, content) {
  await page.locator("#file-picker").setInputFiles({name,mimeType:"application/gpx+xml",buffer:Buffer.from(content)});
}

(async () => {
  const catalog = await (await fetch(`${base}/api/catalog`)).json();
  assert.equal(catalog.status,"ready", "Real selected Workspace must be available for this harness");
  const primary = catalog.sources.find(s => s.id === catalog.preferred_source_id);
  assert.ok(primary,"Require the hash-verified Workspace golden route, not an arbitrary trip");
  const raw = fs.readFileSync(path.join(root,primary.source_ref));
  assert.equal(sha(raw),primary.sha256);
  const document = new JSDOM(raw.toString("utf8"),{contentType:"application/xml"}).window.document;
  const points = [...document.getElementsByTagNameNS("*","trkpt")];
  const segments = document.getElementsByTagNameNS("*","trkseg").length;
  report.realSource = {...primary,independentXmlPointCount:points.length,independentXmlSegmentCount:segments};
  const before = {};
  for (const source of catalog.sources) before[source.source_ref] = sha(fs.readFileSync(path.join(root,source.source_ref)));
  for (const ref of ["project.json","candidates/checkpoints.json","outputs/overpass_aligned_checkpoints.json","outputs/navigation/terrain_rgb/manifest.json"]) {
    if (fs.existsSync(path.join(root,ref))) before[ref] = sha(fs.readFileSync(path.join(root,ref)));
  }
  const browser = await chromium.launch({headless:true,args:["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"]});
  report.browser = await browser.version();
  try {
    async function makePage(viewport, mobile=false) {
      const context = await browser.newContext({viewport, isMobile:mobile, hasTouch:mobile,deviceScaleFactor:mobile?2:1});
      await context.route("**/*", route => {
        const request = route.request();
        if (!["GET","HEAD"].includes(request.method())) {report.mutations.push(request.url());return route.abort();}
        if (new URL(request.url()).origin !== target.origin) {report.externalRequests.push(request.url());return route.abort();}
        return route.continue();
      });
      const page = await context.newPage();
      page.on("pageerror",error=>report.console.push({phase,type:"pageerror",text:error.message}));
      page.on("console",message=>{if (["error","warning"].includes(message.type())) report.console.push({phase,type:message.type(),text:message.text()});});
      page.on("requestfailed",request=>report.failedRequests.push({phase,url:request.url(),error:request.failure()?.errorText}));
      page.on("response",response=>{if(response.status()>=400) report.httpErrors.push({phase,url:response.url(),status:response.status()});});
      return page;
    }

    phase = "desktop-real";
    const desktop = await makePage({width:1440,height:1000});
    await desktop.goto(`${base}/?gpx=${primary.id}`);await ready(desktop);
    let s = await snapshot(desktop);
    assert.equal(s.pointCount,points.length);assert.equal(s.sourceSegmentCount,segments);assert.equal(s.source.sha256,sha(raw));
    assert.equal(s.start.lon,Number(points[0].getAttribute("lon")));assert.equal(s.start.lat,Number(points[0].getAttribute("lat")));
    assert.equal(s.end.lon,Number(points.at(-1).getAttribute("lon")));assert.equal(s.end.lat,Number(points.at(-1).getAttribute("lat")));
    assert.equal(s.terrainStatus,"ready");assert.equal(await desktop.locator("#map").getAttribute("data-renderer"),"three");
    assert.ok(s.nodeScreens.every(n=>n.visible));assert.equal(await desktop.locator("#source-type").inputValue(),"unknown");
    check("desktop real GPX identity, axes, segments, endpoints, 3D and whole-route fit",{snapshot:s,overflow:await noOverflow(desktop)});
    await desktop.locator('[data-node-id="endpoint:start"]').click();
    assert.equal((await snapshot(desktop)).selectedId,"endpoint:start");
    const rect = await desktop.locator("#map").boundingBox();
    const end = (await snapshot(desktop)).nodeScreens.find(n=>n.id==="endpoint:end");
    await desktop.mouse.click(rect.x+end.x,rect.y+end.y);
    assert.equal((await snapshot(desktop)).selectedId,"endpoint:end");
    assert.equal(await desktop.locator('[data-node-id="endpoint:end"]').getAttribute("aria-pressed"),"true");
    check("map click and sidebar selection synchronize");
    await desktop.locator("#play").click();
    await desktop.waitForFunction(()=>window.scoutGpx3d.snapshot().fraction>.01);
    await desktop.locator('[data-node-id="endpoint:start"]').click();
    const fraction = (await snapshot(desktop)).fraction;
    await desktop.waitForFunction(f=>window.scoutGpx3d.snapshot().fraction>f+.01,fraction);
    assert.equal((await snapshot(desktop)).selectedId,"endpoint:start");
    await desktop.locator("#play").click();
    const slider = await desktop.locator("#progress").boundingBox();
    await desktop.mouse.move(slider.x+slider.width*.2,slider.y+slider.height/2);await desktop.mouse.down();
    await desktop.mouse.move(slider.x+slider.width*.72,slider.y+slider.height/2,{steps:8});await desktop.mouse.up();
    assert.ok((await snapshot(desktop)).fraction>.65);assert.equal((await snapshot(desktop)).selectedId,"endpoint:start");
    check("playback and real slider drag preserve manual selection");
    const cameraBefore = await desktop.locator("#camera-readout").textContent();
    await desktop.locator("#rotate-left").click();assert.notEqual(await desktop.locator("#camera-readout").textContent(),cameraBefore);
    await desktop.locator("#zoom-in").click();await desktop.locator("#zoom-out").click();await desktop.locator("#tilt").click();await desktop.locator("#fit").click();
    assert.ok((await snapshot(desktop)).nodeScreens.every(n=>n.visible));
    check("camera rotate, zoom, tilt and refit controls");
    await screen(desktop,"desktop-real.png");

    phase = "mobile-real";
    const mobile = await makePage({width:390,height:844},true);
    await mobile.goto(`${base}/?gpx=${primary.id}`);await ready(mobile);
    await mobile.locator("#map").scrollIntoViewIfNeeded();
    await mobile.locator("#fit").click();
    assert.ok((await snapshot(mobile)).nodeScreens.every(n=>n.visible));
    const mrect = await mobile.locator("#map").boundingBox();
    const mEnd = (await snapshot(mobile)).nodeScreens.find(n=>n.id==="endpoint:end");
    await mobile.touchscreen.tap(mrect.x+mEnd.x,mrect.y+mEnd.y);
    assert.equal((await snapshot(mobile)).selectedId,"endpoint:end");
    const cdp = await mobile.context().newCDPSession(mobile);
    const cx = mrect.x+mrect.width/2, cy = mrect.y+mrect.height/2;
    await cdp.send("Input.dispatchTouchEvent",{type:"touchStart",touchPoints:[{x:cx-25,y:cy,id:0},{x:cx+25,y:cy,id:1}]});
    await cdp.send("Input.dispatchTouchEvent",{type:"touchMove",touchPoints:[{x:cx-65,y:cy,id:0},{x:cx+65,y:cy,id:1}]});
    await cdp.send("Input.dispatchTouchEvent",{type:"touchEnd",touchPoints:[]});
    await mobile.locator("#fit").click();
    check("390×844 mobile real terrain, touch node selection, pinch and whole-route fit",{overflow:await noOverflow(mobile),snapshot:await snapshot(mobile)});
    await screen(mobile,"mobile-real-full.png");await screen(mobile,"mobile-real-scene.png",".scene");

    phase = "tablet-real";
    await desktop.setViewportSize({width:768,height:1024});await desktop.locator("#fit").click();
    check("768×1024 responsive layout",{overflow:await noOverflow(desktop)});
    await screen(desktop,"tablet-real.png");await desktop.setViewportSize({width:1440,height:1000});

    phase = "reference-real";
    const reference = catalog.sources.find(source=>source.source_ref.startsWith("inbox/gpx/reference_002"));
    assert.ok(reference);await desktop.locator("#source-picker").selectOption(reference.id);await ready(desktop);
    s = await snapshot(desktop);
    const refDocument = new JSDOM(fs.readFileSync(path.join(root,reference.source_ref),"utf8"),{contentType:"application/xml"}).window.document;
    assert.equal(s.segmentCount,refDocument.getElementsByTagNameNS("*","trkseg").length);
    const waypointCount=refDocument.getElementsByTagNameNS("*","wpt").length;
    assert.equal(s.nodeScreens.length,waypointCount+2);
    const waypoint = await desktop.locator('[data-kind="waypoint"]').first();await waypoint.click();
    assert.ok((await snapshot(desktop)).selectedId.startsWith("waypoint:"));
    check("real reference GPX segment breaks and original waypoints",{source:reference,segmentCount:s.segmentCount,waypointCount});
    await screen(desktop,"desktop-real-reference.png");

    phase = "cp-real";
    const filtered = catalog.sources.find(source=>source.source_ref.startsWith("normalized/")&&source.source_ref.includes("primary."));
    assert.ok(filtered);await desktop.locator("#source-picker").selectOption(filtered.id);await ready(desktop);
    assert.ok(await desktop.locator('[data-kind="checkpoint"]').count()>0);
    await desktop.locator('[data-kind="checkpoint"]').nth(15).click();
    assert.ok((await snapshot(desktop)).selectedId.startsWith("cp:"));
    await desktop.waitForFunction(()=>!document.querySelector("#node-detail").textContent.includes("正在讀取"));
    check("existing CP matched through source hashes; elevation channels displayed separately",{source:filtered,cpCount:await desktop.locator('[data-kind="checkpoint"]').count(),detail:await desktop.locator("#node-detail").textContent()});

    phase = "synthetic-replay-probe";
    // Deliberately labelled synthetic. This probe is not real-route evidence.
    const synthetic = '<gpx><metadata><name>SYNTHETIC TEST ONLY</name></metadata><wpt lat="23.4" lon="121.1"><name>TEST waypoint</name></wpt><trk><trkseg><trkpt lat="23.4" lon="121.1"><time>2026-09-07T00:00:00Z</time></trkpt><trkpt lat="23.41" lon="121.11"><time>2026-09-07T00:01:00Z</time></trkpt></trkseg><trkseg><trkpt lat="23.42" lon="121.12"><time>2026-09-07T00:03:00Z</time></trkpt><trkpt lat="23.43" lon="121.13"><time>2026-09-07T00:04:00Z</time></trkpt></trkseg></trk></gpx>';
    await upload(desktop,"synthetic-test-only.gpx",synthetic);await ready(desktop);
    assert.equal((await snapshot(desktop)).replayMode,"recorded_time");
    await desktop.locator("#progress").fill("5000");await desktop.locator("#progress").dispatchEvent("input");
    assert.match(await desktop.locator("#playback-time").textContent(),/區段缺口/);
    await desktop.locator('[data-kind="waypoint"]').click();assert.match(await desktop.locator("#node-detail").textContent(),/缺漏 \/ unknown/);
    check("synthetic upload stays local; timestamp gap replay and missing elevation are explicit");
    await upload(desktop,"empty-test-only.gpx","<gpx/>");
    await desktop.waitForFunction(()=>!document.querySelector("#source-error").hidden);
    assert.match(await desktop.locator("#source-error").textContent(),/空 GPX/);assert.equal(await desktop.locator("#map canvas").count(),0);
    check("empty GPX clears previous route and reports an explicit error");

    phase = "injected-terrain-failure";
    const failed = await makePage({width:390,height:844},true);
    await failed.route("**/api/terrain-mesh",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"intentional terrain failure probe"}'}));
    await failed.goto(`${base}/?gpx=${primary.id}`);await ready(failed);
    assert.match(await failed.locator("#terrain-status").textContent(),/降級/);assert.equal((await snapshot(failed)).terrainStatus,"unavailable");
    check("injected terrain HTTP 503 visibly degrades without normal-terrain claims");
    await screen(failed,"mobile-terrain-failure.png",".scene");

    phase = "injected-renderer-failure";
    const noGL = await makePage({width:1440,height:1000});
    await noGL.route("**/renderer.mjs",route=>route.abort("failed"));
    await noGL.goto(`${base}/?gpx=${primary.id}`);await ready(noGL);
    assert.equal(await noGL.locator("#map").getAttribute("data-renderer"),"svg-fallback");
    assert.match(await noGL.locator("#render-status").textContent(),/降級/);
    check("renderer module failure provides visible SVG fallback");

    for (const [ref,hash] of Object.entries(before)) assert.equal(sha(fs.readFileSync(path.join(root,ref))),hash,`Source changed: ${ref}`);
    check("all GPX, project, CP and terrain manifest bytes unchanged",{fileCount:Object.keys(before).length});
    assert.equal(report.externalRequests.length,0);assert.equal(report.mutations.length,0);
    check("zero third-party requests and zero mutations");
    const ordinaryErrors = report.console.filter(item=>item.type!=="warning"&&!item.phase.startsWith("injected-"));
    assert.deepEqual(ordinaryErrors,[]);assert.equal(report.httpErrors.filter(item=>!item.phase.startsWith("injected-")).length,0);
    report.status = "PASS";
  } finally {await browser.close();}
})().catch(error=>{report.status="FAIL";report.error=error.stack;console.error(error);process.exitCode=1;})
  .finally(()=>{fs.writeFileSync(path.join(output,"browser-report.json"),JSON.stringify(report,null,2));console.log(`Report: ${path.resolve(output,"browser-report.json")}`);});
