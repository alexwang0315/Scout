/* Read-only browser proof for historical return costs and daily time windows. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : process.argv[index + 1];
}

async function main() {
  const base = option("--base-url", "http://127.0.0.1:9187");
  const project = option("--project-id", "dongqing_batongguan_historic_trail_newImport");
  const output = path.resolve(option("--output-dir", "/tmp/scout-architecture-return-smoke"));
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({
    headless: true,
    executablePath: option("--browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
  });
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const request = route.request();
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) return route.abort();
      return route.continue();
    });
    await page.goto(`${base}/admin/dashboard?projectId=${encodeURIComponent(project)}#outdoor-architecture`, {waitUntil: "domcontentloaded"});
    await page.waitForFunction(() => architectureSnapshot().historical_time_windows?.days?.length > 0, null, {timeout: 60000});
    const summary = await page.evaluate(() => {
      const snapshot = architectureSnapshot();
      const result = snapshot.historical_return_cost;
      const resets = result.checkpoints.filter(node => node.decision_boundary);
      const crossing = result.checkpoints.find(node => node.entry_decision_boundary);
      return {
        project: snapshot.project_id,
        stats: result.stats,
        counts: result.directional_counts,
        dailyBudget: result.daily_budget,
        crossing: crossing ? {id: crossing.node_id, km: crossing.route_distance_m / 1000} : null,
        reset: resets.find(node => node.return_target_kind === "camp"),
        costStatus: result.status,
      };
    });
    assert.equal(summary.project, project);
    assert(summary.stats.available_return_count > 0);
    assert(summary.crossing, "Missing entry decision point");
    assert(summary.reset, "Missing historical camp reset");
    await page.locator('[data-architecture-mode="reversibility"]').click();
    const returnMarks = page.locator('[data-architecture-selection-surface="fingerprint-return"]');
    assert.equal(await returnMarks.count(), summary.stats.checkpoint_count);
    assert(await returnMarks.evaluateAll(nodes => new Set(nodes.map(node => node.getAttribute("fill"))).size > 5));
    assert.equal(await page.locator('[data-architecture-supporting][open]').count(), 0);
    const resetSelector = `[data-architecture-selection-surface="fingerprint-return"][data-architecture-passage-node-id="${summary.reset.node_id}"]`;
    await page.locator(resetSelector).click();
    await page.waitForFunction(id => state.architectureSelectedPassageNodeId === id, summary.reset.node_id);
    await page.locator('[data-route-fingerprint="ready"]').screenshot({path: path.join(output, "return-desktop.png")});
    await page.locator(resetSelector).press("ArrowRight");
    await page.waitForFunction(id => state.architectureSelectedPassageNodeId !== id, summary.reset.node_id);
    assert(await page.locator('[data-architecture-return-node]').innerText().then(text => text.includes("推估")));

    await page.locator('[data-architecture-lens="reversibility"]').click();
    assert(await page.locator('[data-architecture-selection-surface="map-bin"]').evaluateAll(nodes => new Set(nodes.map(node => node.getAttribute("stroke"))).size > 2));
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('[data-architecture-mode="reversibility"]').click();
    await page.locator('[data-architecture-mobile-view="spine"]').click();
    const mobileReset = page.locator(`[data-architecture-selection-surface="mobile-return"][data-architecture-passage-node-id="${summary.reset.node_id}"]`);
    await mobileReset.scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(output, "return-mobile-spine.png")});
    await mobileReset.click();
    await page.waitForFunction(() => state.architectureMobileView === "segment");
    const inspector = page.locator('[data-architecture-return-node]');
    await inspector.scrollIntoViewIfNeeded();
    assert.equal(await inspector.getAttribute("data-architecture-return-node"), summary.reset.node_id);
    assert(await inspector.innerText().then(text => text.includes(summary.reset.return_target_label)));
    await page.screenshot({path: path.join(output, "return-mobile-inspector.png")});
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      const overflow = await page.locator(".route-architecture-shell").evaluate(element => element.scrollWidth - element.clientWidth);
      assert(overflow <= 1, `Architecture overflow at ${width}: ${overflow}`);
    }

    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator('[data-architecture-mode="time_window"]').click();
    const windows = await page.evaluate(() => {
      const result = architectureSnapshot().historical_time_windows;
      const reset = result.checkpoints.find(node => node.day_reset && node.day_index === 2);
      const available = result.checkpoints.filter(node => node.remaining_minutes !== null);
      return {
        status: result.status, stats: result.stats,
        days: result.days.map(day => ({
          day: day.day_index, departure: architectureClockMinutes(day.departure_minute_of_day),
          initialMinutes: day.initial_window_minutes,
        })),
        reset,
        formulaValid: available.every(node => Math.abs(node.initial_window_minutes - node.consumed_minutes - node.remaining_minutes) < 1e-8),
        marginsValid: available.filter(node => node.arrival_margin_minutes !== null)
          .every(node => Math.abs(node.remaining_minutes - node.forward_to_safe_minutes - node.arrival_margin_minutes) < 1e-8),
        countdownValid: result.days.every(day => {
          const rows = available.filter(node => node.day_id === day.day_id);
          return rows.every((node, index) => index === 0 || node.remaining_minutes <= rows[index - 1].remaining_minutes);
        }),
        minimumRemainingMinutes: Math.min(...available.map(node => node.remaining_minutes)),
        maximumRemainingMinutes: Math.max(...available.map(node => node.remaining_minutes)),
      };
    });
    assert(windows.days.length > 1, "Missing historical daily departure schedule");
    assert(windows.formulaValid && windows.marginsValid && windows.countdownValid);
    assert(windows.reset?.day_reset);
    assert.equal(windows.reset.consumed_minutes, 0);
    const windowMarks = page.locator('[data-architecture-selection-surface="fingerprint-window"]');
    assert.equal(await windowMarks.count(), windows.stats.checkpoint_count);
    assert(await windowMarks.evaluateAll(nodes => new Set(nodes.map(node => node.dataset.architectureWindowColor)).size > 5));
    const windowResetSelector = `[data-architecture-selection-surface="fingerprint-window"][data-architecture-passage-node-id="${windows.reset.node_id}"]`;
    await page.locator(windowResetSelector).click();
    await page.waitForFunction(id => state.architectureSelectedPassageNodeId === id, windows.reset.node_id);
    await page.locator('[data-route-fingerprint="ready"]').screenshot({path: path.join(output, "time-window-desktop.png")});
    await page.locator(windowResetSelector).press("ArrowRight");
    await page.waitForFunction(id => state.architectureSelectedPassageNodeId !== id, windows.reset.node_id);
    assert(await page.locator('[data-architecture-window-node]').innerText().then(text => text.includes("剩餘時間資本") && text.includes("18:00")));
    await page.locator('[data-architecture-lens="time_window"]').click();
    assert(await page.locator('[data-architecture-selection-surface="map-bin"]').evaluateAll(nodes => new Set(nodes.map(node => node.getAttribute("stroke"))).size > 2));
    await page.locator('.architecture-map-frame').screenshot({path: path.join(output, "time-window-map.png")});

    await page.setViewportSize({width: 390, height: 844});
    await page.locator('[data-architecture-mobile-view="spine"]').click();
    const mobileWindow = page.locator(`[data-architecture-selection-surface="mobile-window"][data-architecture-passage-node-id="${windows.reset.node_id}"]`);
    await mobileWindow.scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(output, "time-window-mobile-spine.png")});
    await mobileWindow.click();
    await page.waitForFunction(() => state.architectureMobileView === "segment");
    const windowInspector = page.locator('[data-architecture-window-node]');
    assert.equal(await windowInspector.getAttribute("data-architecture-window-node"), windows.reset.node_id);
    await windowInspector.scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(output, "time-window-mobile-inspector.png")});
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      const overflow = await page.locator('.route-architecture-shell').evaluate(element => element.scrollWidth - element.clientWidth);
      assert(overflow <= 1, `Time Window overflow at ${width}: ${overflow}`);
      const clipped = await windowInspector.locator('strong, h4').evaluateAll(elements => elements.filter(element => element.scrollWidth > element.clientWidth + 1).map(element => element.textContent));
      assert.deepEqual(clipped, [], `Time Window clipped text at ${width}`);
    }
    assert.deepEqual(errors, []);
    const evidence = {...summary, reset: {
      id: summary.reset.node_id, label: summary.reset.return_target_label,
      km: summary.reset.route_distance_m / 1000,
    }, timeWindows: windows, browserErrors: errors, screenshots: output};
    fs.writeFileSync(path.join(output, "return-verification.json"), JSON.stringify(evidence, null, 2) + "\n");
    console.log(JSON.stringify(evidence, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
