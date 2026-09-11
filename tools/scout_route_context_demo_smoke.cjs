/* Real-entrypoint smoke. Test state access is injected only in this browser. */
const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

const base = process.argv[2] || "http://127.0.0.1:19130";
const output = path.resolve(process.argv[3] || "/tmp/scout-route-context-smoke");

async function mapPixels(page) {
  return page.evaluate(() => [...document.querySelectorAll(".maplibregl-canvas")].map(canvas => {
    const gl = canvas.getContext("webgl2"), pixels = new Uint8Array(canvas.width * canvas.height * 4);
    assertContext(gl);
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let painted = 0; const colors = new Set();
    for (let i = 0; i < pixels.length; i += 256) {
      if (pixels[i + 3]) painted++;
      colors.add(`${pixels[i]},${pixels[i + 1]},${pixels[i + 2]}`);
    }
    return {width: canvas.width, height: canvas.height, colors: colors.size, painted};
    function assertContext(context) { if (!context) throw new Error("No WebGL2 context"); }
  }));
}

async function waitMap(page) {
  await page.waitForFunction(() => window.__routeContextTestState?.ready, null, {timeout: 60000});
  await page.waitForFunction(() => {
    const state = window.__routeContextTestState;
    return !state.modern.isMoving() && state.modern.areTilesLoaded() && state.historic.areTilesLoaded();
  }, null, {timeout: 60000});
  await page.waitForTimeout(250);
}

async function cameraCheck(page) {
  const bounds = await page.evaluate(() => {
    const s = window.__routeContextTestState, m = s.modern, p = s.data.route.profile;
    return {width: m.getCanvas().clientWidth, height: m.getCanvas().clientHeight,
      ends: [m.project([p[0][2], p[0][3]]), m.project([p.at(-1)[2], p.at(-1)[3]])]};
  });
  for (const p of bounds.ends) {
    assert(p.x >= 20 && p.x <= bounds.width - 20, "GPX endpoint clipped horizontally");
    assert(p.y >= 30 && p.y <= bounds.height - 30, "GPX endpoint clipped vertically");
  }
  return bounds;
}

async function layoutCheck(page) {
  const overflow = await page.evaluate(() => {
    const visible = node => node.getClientRects().length && getComputedStyle(node).visibility !== "hidden";
    const controls = [...document.querySelectorAll("button, select, textarea")].filter(visible);
    return {
      page: document.documentElement.scrollWidth > innerWidth + 1,
      desktopHeight: innerWidth > 1100 && document.documentElement.scrollHeight > innerHeight + 160,
      controls: controls.filter(node => node.scrollWidth > node.clientWidth + 2).map(node => node.id || node.textContent),
    };
  });
  assert.equal(overflow.page, false, "Horizontal page overflow"); assert.equal(overflow.desktopHeight, false, "Desktop context escaped its scroll panel");
  assert.deepEqual(overflow.controls, [], "Text overflows a control");
}

async function main() {
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]});
  const results = {url: base, checked_at: new Date().toISOString(), desktop: {}, mobile: {}, errors: [], cached_tile_responses: 0, external_requests: []};
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, reducedMotion: "reduce", acceptDownloads: true});
    const page = await context.newPage();
    page.on("pageerror", error => results.errors.push(error.message));
    page.on("request", request => { if (!request.url().startsWith(base) && !request.url().startsWith("data:")) results.external_requests.push(request.url()); });
    page.on("response", response => { if (response.url().includes("/tiles/") && response.headers()["x-scout-tile-coverage"] === "cached") results.cached_tile_responses++; });
    await page.route("**/assets/app.mjs", async route => {
      const response = await route.fetch();
      await route.fulfill({response, body: await response.text() + "\nwindow.__routeContextTestState = state;"});
    });
    await page.goto(base); await waitMap(page); await layoutCheck(page);
    results.desktop.camera = await cameraCheck(page); results.desktop.pixels = await mapPixels(page);
    assert(results.desktop.pixels.every(p => p.colors > 100 && p.painted > 1000), "Blank raster canvas");
    await page.screenshot({path: path.join(output, "desktop-history.png"), fullPage: true});
    const data = await page.evaluate(() => window.__routeContextTestState.data);
    const restricted = data.points.filter(p => !p.position_allowed);
    assert.equal(restricted.length, 6);
    assert(restricted.every(p => !("coordinates" in p) && !("distance_m" in p)));
    assert.equal(data.research.raw_feature_count, 0); assert.equal(data.research.trained_model, null);
    assert.equal(data.boundary.workspace_writes, false);
    const before = await page.locator("#map-frame").screenshot();
    await page.getByLabel("歷史圖幅年代", {exact: true}).selectOption("historical-tm50k-1956"); await waitMap(page);
    assert.match(await page.locator("#historic-caption").innerText(), /1956/);
    const after = await page.locator("#map-frame").screenshot(); assert(!before.equals(after), "Historical edition did not change visually");
    results.desktop.editions = [];
    for (const layer of data.layers.filter(layer => layer.year)) {
      await page.getByLabel("歷史圖幅年代", {exact: true}).selectOption(layer.id); await waitMap(page);
      assert((await page.locator("#historic-caption").innerText()).includes(layer.year));
      const pixels = await mapPixels(page); results.desktop.editions.push({year: layer.year, historical_canvas_colors: pixels[1].colors});
    }
    await page.getByLabel("歷史圖幅年代", {exact: true}).selectOption("historical-tm50k-1956"); await waitMap(page);
    await page.getByRole("button", {name: "圖資證據", exact: false}).click();
    assert.match(await page.locator("#evidence-title").innerText(), /1956/);
    assert.match(await page.locator("#evidence-body").innerText(), /SHA-256/);
    await page.getByRole("button", {name: "關閉來源證據", exact: true}).click();
    await page.getByRole("tab", {name: "路線故事", exact: true}).click();
    await page.getByLabel("主題", {exact: true}).selectOption("cultural");
    assert.equal(await page.locator("#story-list .story").count(), 2);
    await page.getByRole("tab", {name: "文化地點", exact: true}).click();
    assert.equal(await page.locator("#place-list .place-row").count(), 7);
    await page.getByRole("button", {name: "定位 大水窟山屋", exact: true}).click(); await waitMap(page);
    assert.match(await page.locator("#selection-caption").innerText(), /大水窟/);
    await page.screenshot({path: path.join(output, "desktop-cultural-place.png"), fullPage: true});
    await page.getByRole("tab", {name: "影像研究", exact: true}).click();
    assert.equal(await page.locator("#comparison").inputValue(), "0");
    assert.match(await page.locator("#panel-research").innerText(), /未評估/);
    await page.getByRole("button", {name: "建立影像觀察", exact: true}).click();
    await page.getByLabel("地表類別", {exact: true}).selectOption("uncertain");
    await page.getByLabel("觀察記錄", {exact: true}).fill("瀏覽器驗證樣本：此處僅記錄待判讀影像，不判定通行或文化遺址。 <script>not executed</script>");
    await page.getByRole("button", {name: "儲存本機草稿", exact: true}).click();
    assert.equal(await page.locator("#note-count").innerText(), "1");
    assert.equal(await page.locator("#note-list script").count(), 0);
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("button", {name: "下載觀察 JSON", exact: true}).click();
    const download = await downloadEvent; const exportPath = path.join(output, "observation-export.json"); await download.saveAs(exportPath);
    const exported = JSON.parse(await fs.readFile(exportPath, "utf8"));
    assert.equal(exported.independent_ground_truth, false); assert.equal(exported.evaluation_eligible, false);
    assert.equal(exported.observations.length, 1); assert.equal(exported.observations[0].image_acquired_at, null);
    await page.screenshot({path: path.join(output, "desktop-observation.png"), fullPage: true});
    await page.reload(); await waitMap(page); assert.equal(await page.locator("#note-count").innerText(), "1");
    await page.getByRole("tab", {name: /^觀察簿/}).click();
    await page.getByRole("button", {name: "刪除此觀察", exact: true}).click();
    assert.equal(await page.locator("#note-count").innerText(), "0");
    await page.reload(); await waitMap(page); assert.equal(await page.locator("#note-count").innerText(), "0");
    await page.getByLabel("GPX", {exact: true}).uncheck();
    assert.equal(await page.evaluate(() => window.__routeContextTestState.modern.getLayoutProperty("route-line", "visibility")), "none");
    await page.getByLabel("GPX", {exact: true}).check();
    await page.locator("#route-position").fill("500");
    assert.match(await page.locator("#profile-position").innerText(), /44\.9/);
    results.desktop.interactions = "history, source, topic filter, cultural point, research, save, escaped text, export, reload, delete, route toggle, profile";
    await page.setViewportSize({width: 390, height: 844}); await page.reload(); await waitMap(page); await layoutCheck(page);
    results.mobile.camera = await cameraCheck(page); results.mobile.pixels = await mapPixels(page);
    assert(results.mobile.pixels.every(p => p.colors > 100 && p.painted > 500), "Blank mobile canvas");
    await page.screenshot({path: path.join(output, "mobile-history.png"), fullPage: true});
    await page.getByRole("tab", {name: "影像研究", exact: true}).click();
    await page.getByRole("button", {name: "建立影像觀察", exact: true}).click();
    await page.getByLabel("觀察記錄", {exact: true}).fill("手機版驗證樣本");
    await page.getByRole("button", {name: "儲存本機草稿", exact: true}).click();
    assert.equal(await page.locator("#note-count").innerText(), "1"); await layoutCheck(page);
    await page.screenshot({path: path.join(output, "mobile-observation.png"), fullPage: true});
    await page.getByRole("button", {name: "刪除此觀察", exact: true}).click();
    await page.setViewportSize({width: 320, height: 700}); await page.reload(); await waitMap(page); await layoutCheck(page);
    results.mobile.smallest_width = 320;
    await page.setViewportSize({width: 1920, height: 1080}); await page.reload(); await waitMap(page); await layoutCheck(page); await cameraCheck(page);
    results.desktop.widest_width = 1920;
    assert.deepEqual(results.errors, []); assert.deepEqual(results.external_requests, []); assert(results.cached_tile_responses > 20);
    results.status = "PASS";
  } catch (error) {
    results.status = "FAIL"; results.failure = error.stack; throw error;
  } finally {
    await fs.writeFile(path.join(output, "smoke-result.json"), JSON.stringify(results, null, 2));
    await browser.close(); console.log(JSON.stringify(results, null, 2));
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
