/* Operate the Architecture controls on an existing local Dashboard. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
}

async function main() {
  const base = option("--base-url", "http://127.0.0.1:9099");
  const project = option("--project-id", "dongqing_batongguan_historic_trail_newImport");
  const output = path.resolve(option("--output-dir", "/tmp/scout-architecture-controls"));
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: option("--browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")});
  const report = {base, project, startedAt: new Date().toISOString(), actions: [], pageErrors: [], tileResponses: []};
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}, hasTouch: true});
    page.setDefaultTimeout(20000);
    page.on("pageerror", error => report.pageErrors.push(error.message));
    page.on("response", response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith("/admin/tiles/imagery/")) {
        report.tileResponses.push({path: url.pathname, status: response.status()});
      }
    });
    await page.route("**/*", route => ["GET", "HEAD", "OPTIONS"].includes(route.request().method())
      ? route.continue() : route.abort());
    const url = `${base}/admin/dashboard?projectId=${encodeURIComponent(project)}#outdoor-architecture`;
    await page.goto(url, {waitUntil: "domcontentloaded"});
    await page.waitForFunction(() => architectureSnapshot().historical_time_windows?.days?.length > 0, null, {timeout: 60000});
    const shell = page.locator(".route-architecture-shell");
    const fingerprint = page.locator('[data-route-fingerprint="ready"]');
    const map = page.locator('[data-dashboard-map-viewport="architecture-map"]');
    const mapFrame = page.locator(".architecture-map-frame");
    const controls = id => map.locator(`[data-map-control="${id}"]`);
    const viewState = () => map.evaluate(element => ({...element.dashboardMapController.getState(),
      tileZoom: Number(element.dataset.dashboardTileZoom), tileState: element.dataset.dashboardTileLoadState,
      renderPolicy: element.dataset.mapRenderPolicyStatus, blockedImages: element.dataset.mapRenderPolicyBlockedImageCount}));
    const stateSnapshot = () => page.evaluate(() => ({
      mode: state.architectureMode, lens: state.architectureLens, mobile: state.architectureMobileView,
      selectedBin: state.architectureSelectedBinId, selectedNode: state.architectureSelectedPassageNodeId,
      supporting: {...state.architectureSupportingExpanded}, map: {...state.mapViewportById["architecture-map"]},
    }));
    async function waitForMapTiles() {
      if (!await map.isVisible()) return;
      await page.waitForFunction(() => {
        const element = document.querySelector('[data-dashboard-map-viewport="architecture-map"]');
        return element?.dataset.dashboardTileLoadState === "ready"
          && element.dataset.mapRenderPolicyStatus === "verified";
      }, null, {timeout: 60000});
    }
    async function check(name, surface, action) {
      const before = await stateSnapshot();
      const prefix = `${String(report.actions.length + 1).padStart(2, "0")}-${name}`;
      try {
        await waitForMapTiles();
        await surface.screenshot({path: path.join(output, `${prefix}-before.png`)});
        const details = await action();
        await waitForMapTiles();
        await surface.screenshot({path: path.join(output, `${prefix}-after.png`)});
        report.actions.push({name, status: "pass", before, after: await stateSnapshot(), details});
        console.log(`PASS ${name}`);
      } catch (error) {
        report.actions.push({name, status: "fail", error: error.message, before, after: await stateSnapshot()});
        await page.screenshot({path: path.join(output, `${prefix}-failure.png`)});
        console.log(`FAIL ${name}: ${error.message}`);
      }
    }
    async function drag(startX, startY, endX, endY) {
      await map.scrollIntoViewIfNeeded();
      const box = await map.boundingBox();
      await page.mouse.move(box.x + box.width * startX, box.y + box.height * startY);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * endX, box.y + box.height * endY, {steps: 12});
      await page.mouse.up();
    }

    const modes = await shell.locator("button[data-architecture-mode]").evaluateAll(nodes => nodes.map(node => node.dataset.architectureMode));
    const lenses = await shell.locator("button[data-architecture-lens]").evaluateAll(nodes => nodes.map(node => node.dataset.architectureLens));
    report.controlInventory = {modes, lenses, map: ["reset", "zoom-in", "zoom-out", "pan", "box-zoom"],
      supporting: ["retreat", "evidence"], mobile: ["spine", "map", "segment"]};
    let previousOpacity;
    for (const mode of modes) {
      await check(`mode-${mode}`, fingerprint, async () => {
        const button = shell.locator(`button[data-architecture-mode="${mode}"]`);
        await button.click();
        assert.equal(await button.getAttribute("aria-selected"), "true");
        const values = await fingerprint.locator("[opacity]").evaluateAll(nodes => nodes.map(node => node.getAttribute("opacity")));
        assert(values.length > 0 && values.every(value => Number.isFinite(Number(value))));
        assert(values.some(value => Number(value) > 0) && values.some(value => Number(value) < 1));
        if (previousOpacity) assert.notDeepEqual(values, previousOpacity);
        previousOpacity = values;
        return {opacityCount: values.length};
      });
    }
    for (const lens of lenses) {
      await check(`lens-${lens}`, mapFrame, async () => {
        const button = shell.locator(`button[data-architecture-lens="${lens}"]`);
        await button.click();
        assert.equal(await button.getAttribute("aria-selected"), "true");
        assert.equal(await shell.locator("[data-architecture-legend]").getAttribute("data-architecture-legend"), lens);
        const colors = await map.locator('[data-architecture-selection-surface="map-bin"]').evaluateAll(nodes => [...new Set(nodes.map(node => node.getAttribute("stroke")))]);
        assert(lens === "structure" ? colors.length === 1 : colors.length > 1);
        return {colors};
      });
    }
    await check("map-fit", mapFrame, async () => {
      await controls("reset").click();
      const state = await viewState();
      assert.equal(state.zoom, 1);
      assert.equal(state.x, 0);
      assert.equal(state.y, 0);
      return state;
    });
    await check("map-zoom-in-native-tiles", mapFrame, async () => {
      const before = await viewState();
      await controls("zoom-in").click();
      await page.waitForFunction(previous => {
        const element = document.querySelector('[data-dashboard-map-viewport="architecture-map"]');
        return Number(element.dataset.dashboardTileZoom) > previous && element.dataset.dashboardTileLoadState === "ready";
      }, before.tileZoom, {timeout: 30000});
      const after = await viewState();
      assert(after.zoom > before.zoom);
      assert.equal(after.renderPolicy, "verified");
      assert.equal(after.blockedImages, "0");
      assert(report.tileResponses.some(response => response.status === 200
        && response.path.includes(`/imagery/${after.tileZoom}/`)));
      return {before, after};
    });
    await check("map-zoom-out", mapFrame, async () => {
      const before = await viewState();
      await controls("zoom-out").click();
      assert((await viewState()).zoom < before.zoom);
    });
    await check("map-mouse-pan", mapFrame, async () => {
      await controls("zoom-in").click();
      await controls("pan").click();
      const before = await viewState();
      await drag(.3, .55, .48, .68);
      const after = await viewState();
      assert(before.x !== after.x || before.y !== after.y);
      assert.equal(after.mode, "pan");
    });
    await check("map-keyboard-pan", mapFrame, async () => {
      const before = await viewState();
      await map.focus();
      await map.press(before.x === 0 ? "ArrowRight" : "ArrowLeft");
      const after = await viewState();
      assert(before.x !== after.x || before.y !== after.y);
    });
    await check("map-rectangle-zoom", mapFrame, async () => {
      await controls("reset").click();
      await controls("box-zoom").click();
      await drag(.2, .3, .65, .75);
      const after = await viewState();
      assert(after.zoom > 1 && after.zoom <= 4);
      assert.equal(after.mode, "box");
      assert.equal(await map.getAttribute("data-map-last-gesture"), "rectangle-zoom-in");
    });
    await check("map-point-zoom-and-pan-mode", mapFrame, async () => {
      const before = await viewState();
      await map.click({position: {x: 80, y: 130}});
      assert((await viewState()).zoom > before.zoom);
      await controls("pan").click();
      assert.equal((await viewState()).mode, "pan");
    });
    await check("map-wheel-does-not-zoom", mapFrame, async () => {
      const before = await viewState();
      await map.hover();
      await page.mouse.wheel(0, -200);
      assert.equal((await viewState()).zoom, before.zoom);
    });
    await controls("reset").click();

    for (const kind of ["retreat", "evidence"]) {
      const details = shell.locator(`[data-architecture-supporting="${kind}"]`);
      await check(`supporting-${kind}-toggle-persistence`, details, async () => {
        assert.equal(await details.getAttribute("open"), null);
        await details.locator("summary").click();
        await page.waitForFunction(key => state.architectureSupportingExpanded[key] === true, kind);
        await shell.locator('[data-architecture-mode="structure"]').click();
        assert.notEqual(await details.getAttribute("open"), null);
        assert((await details.innerText()).length > 180);
        await details.locator("summary").click();
        await page.waitForFunction(key => state.architectureSupportingExpanded[key] === false, kind);
      });
    }
    await check("fingerprint-horizontal-scroll", fingerprint, async () => {
      const scroll = shell.locator("[data-architecture-fingerprint-scroll]");
      await scroll.hover();
      await page.mouse.wheel(600, 0);
      await page.waitForFunction(() => document.querySelector("[data-architecture-fingerprint-scroll]").scrollLeft > 100);
      const before = await scroll.evaluate(element => element.scrollLeft);
      await shell.locator('[data-architecture-mode="demand"]').click();
      assert(Math.abs(await scroll.evaluate(element => element.scrollLeft) - before) < 2);
    });
    for (const surface of ["fingerprint-bin", "fingerprint-structure", "fingerprint-passage", "fingerprint-next-cp"]) {
      await check(`select-${surface}`, fingerprint, async () => {
        const target = shell.locator(`[data-architecture-selection-surface="${surface}"]`).nth(2);
        const binId = await target.getAttribute("data-architecture-bin-id");
        const nodeId = await target.getAttribute("data-architecture-passage-node-id");
        await target.click();
        await page.waitForFunction(({binId,nodeId}) => nodeId
          ? state.architectureSelectedPassageNodeId === nodeId
          : state.architectureSelectedBinId === binId, {binId,nodeId});
        assert(await shell.locator(".architecture-inspector-body").isVisible());
        return {binId,nodeId};
      });
    }
    await controls("reset").click();
    await check("select-map-checkpoint", mapFrame, async () => {
      const target = map.locator('[data-architecture-selection-surface="map-evidence"]').nth(2);
      const nodeId = await target.getAttribute("data-architecture-passage-node-id");
      await target.click();
      assert.equal((await stateSnapshot()).selectedNode, nodeId);
    });
    await check("select-map-route-segment", mapFrame, async () => {
      await map.scrollIntoViewIfNeeded();
      const target = await map.evaluate(element => {
        for (const path of element.querySelectorAll('[data-architecture-selection-surface="map-bin"]')) {
          const point = path.getPointAtLength(path.getTotalLength() / 2).matrixTransform(path.getScreenCTM());
          const hit = document.elementFromPoint(point.x, point.y)?.closest('[data-architecture-selection-surface="map-bin"]');
          if (hit && element.contains(hit) && hit.dataset.architectureBinId) {
            return {x: point.x, y: point.y, binId: hit.dataset.architectureBinId};
          }
        }
        return null;
      });
      assert(target, "A painted route segment must be clickable");
      await page.mouse.click(target.x, target.y);
      assert.equal((await stateSnapshot()).selectedBin, target.binId);
      assert.equal((await stateSnapshot()).selectedNode, "");
      return target;
    });

    for (const width of [390, 320]) {
      await page.setViewportSize({width,height:844});
      for (const view of ["spine", "map", "segment"]) {
        await check(`mobile-${width}-${view}`, shell, async () => {
          await shell.locator(`[data-architecture-mobile-view="${view}"]`).click();
          assert(await shell.locator(`[data-architecture-mobile-panel="${view}"]`).isVisible());
          assert.equal((await stateSnapshot()).mobile, view);
          assert(await shell.evaluate(element => element.scrollWidth - element.clientWidth <= 1));
        });
        if (width === 390 && view === "map") {
          await check("mobile-touch-map-checkpoint", mapFrame, async () => {
            await controls("reset").tap();
            const target = map.locator('[data-architecture-selection-surface="map-evidence"]').nth(2);
            const nodeId = await target.getAttribute("data-architecture-passage-node-id");
            await target.tap();
            assert.equal((await stateSnapshot()).selectedNode, nodeId);
            return {nodeId};
          });
        }
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await check("reload-workspace-data", shell, async () => {
      await page.reload({waitUntil:"domcontentloaded"});
      await page.waitForFunction(() => architectureSnapshot().historical_time_windows?.days?.length > 0, null, {timeout:60000});
      assert.equal(await page.evaluate(() => architectureSnapshot().project_id), project);
      assert.equal(await shell.locator("[data-architecture-supporting][open]").count(), 0);
    });
    report.ok = report.actions.every(action => action.status === "pass") && report.pageErrors.length === 0;
    report.finishedAt = new Date().toISOString();
    fs.writeFileSync(path.join(output,"controls-verification.json"), JSON.stringify(report,null,2) + "\n");
    console.log(JSON.stringify({ok:report.ok,passed:report.actions.filter(action=>action.status==="pass").length,
      failed:report.actions.filter(action=>action.status==="fail"),pageErrors:report.pageErrors,output},null,2));
    if (!report.ok) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
