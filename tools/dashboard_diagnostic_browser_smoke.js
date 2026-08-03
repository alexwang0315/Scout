#!/usr/bin/env node
"use strict";

const path = require("path");
const Module = require("module");

const bundledNodeModules = path.join(
  process.env.HOME || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
);
process.env.NODE_PATH = [process.env.NODE_PATH, bundledNodeModules]
  .filter(Boolean)
  .join(path.delimiter);
Module._initPaths();

const { chromium } = require("playwright");

const baseUrl = process.env.SCOUT_DASHBOARD_DIAGNOSTIC_URL
  || "http://127.0.0.1:9099/admin/dashboard?projectId=chilai_nanhua_day1_scoutAI#diagnostic";
const expectedDiagnosticCount = 36;
const dataDependentDiagnosticIds = new Set([
  "DASH-009",
  "DASH-018",
  "DASH-019",
  "DASH-030",
  "DASH-032",
  "DASH-033",
  "DASH-035",
]);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function openDashboardRoute(page, route) {
  const navigation = page.locator(`[data-route="${route}"]`).first();
  await navigation.evaluate(node => {
    const details = node.closest("details");
    if (details) details.open = true;
  });
  await navigation.click();
}

async function inspectNativeDashboardMap(page, surface) {
  await openDashboardRoute(page, surface.route);
  await page.waitForTimeout(1500);
  const viewport = page.locator(`[data-dashboard-map-viewport="${surface.viewportId}"]`).first();
  await viewport.waitFor({ state: "attached", timeout: 120000 });
  await page.waitForTimeout(300);
  await viewport.evaluate(node => {
    const details = node.closest("details");
    if (details) details.open = true;
  });
  const controlNames = await viewport.locator("[data-map-control]").evaluateAll(nodes => (
    nodes.map(node => node.getAttribute("data-map-control"))
  ));
  for (const control of ["zoom-in", "zoom-out", "reset", "pan", "box-zoom"]) {
    assert(controlNames.includes(control), `${surface.label} is missing ${control}.`);
  }
  const policyStatus = await viewport.getAttribute("data-map-render-policy-status");
  assert(policyStatus === "verified", `${surface.label} render policy is ${policyStatus || "missing"}.`);
  assert(
    await viewport.getAttribute("data-map-wheel-zoom") === "false",
    `${surface.label} mouse-wheel zoom is not disabled.`,
  );
  assert(
    await viewport.getAttribute("data-dashboard-basemap-policy") === "rudy-twmap-only",
    `${surface.label} is not using the Rudy+TW-only basemap policy.`,
  );
  const tileSources = await viewport.locator('svg image[data-map-render-kind="tile"]').evaluateAll(nodes => (
    [...new Set(nodes.map(node => node.getAttribute("data-map-tile-source")).filter(Boolean))]
  ));
  assert(tileSources.length === 1 && tileSources[0] === "rudy-twmap", `${surface.label} tile sources are ${tileSources.join(", ") || "missing"}.`);
  const hintTarget = viewport.locator('[data-dashboard-map-hint-title][tabindex="0"]').first();
  assert(await hintTarget.count() === 1, `${surface.label} has no focusable evidence hint target.`);
  await hintTarget.focus();
  await page.waitForFunction(() => !document.getElementById("dashboardMapHoverHint")?.hidden, null, {timeout: 5000});
  const hintTitle = await page.locator("#dashboardMapHoverHint strong").textContent();
  assert(Boolean(hintTitle?.trim()), `${surface.label} hint has no title.`);
  await viewport.locator('[data-map-control="zoom-in"]').click();
  const zoomAfterClick = Number(await viewport.getAttribute("data-map-zoom"));
  assert(zoomAfterClick > 1, `${surface.label} Zoom in did not change scale.`);
  await viewport.dispatchEvent("wheel", {deltaY: -120});
  assert(
    Number(await viewport.getAttribute("data-map-zoom")) === zoomAfterClick,
    `${surface.label} mouse wheel changed map zoom.`,
  );
  await viewport.locator('[data-map-control="zoom-out"]').click();
  const zoomAfterOut = Number(await viewport.getAttribute("data-map-zoom"));
  assert(zoomAfterOut < zoomAfterClick, `${surface.label} Zoom out did not reduce scale.`);
  await viewport.locator('[data-map-control="zoom-in"]').click();
  const panStateBefore = await viewport.evaluate(node => node.dashboardMapController?.getState?.());
  assert(panStateBefore, `${surface.label} map controller is unavailable.`);
  await viewport.focus();
  await viewport.press("ArrowRight");
  const panStateAfter = await viewport.evaluate(node => node.dashboardMapController?.getState?.());
  assert(
    panStateAfter?.x !== panStateBefore.x,
    `${surface.label} keyboard pan did not change translation: ${JSON.stringify({before: panStateBefore, after: panStateAfter})}`,
  );
  await viewport.locator('[data-map-control="reset"]').click();
  assert(Number(await viewport.getAttribute("data-map-zoom")) === 1, `${surface.label} Fit did not reset scale.`);
  await viewport.locator('[data-map-control="box-zoom"]').click();
  assert(
    await viewport.locator('[data-map-control="box-zoom"]').getAttribute("aria-pressed") === "true",
    `${surface.label} Box mode did not activate.`,
  );
  const viewportBox = await viewport.boundingBox();
  assert(viewportBox, `${surface.label} viewport has no browser bounds.`);
  await page.mouse.move(viewportBox.x + viewportBox.width * 0.22, viewportBox.y + viewportBox.height * 0.48);
  await page.mouse.down();
  await page.mouse.move(viewportBox.x + viewportBox.width * 0.72, viewportBox.y + viewportBox.height * 0.82, {steps: 6});
  await page.mouse.up();
  const boxZoomState = await viewport.evaluate(node => node.dashboardMapController?.getState?.());
  assert(boxZoomState?.zoom > 1, `${surface.label} rectangle zoom did not change scale.`);
  await viewport.locator('[data-map-control="reset"]').click();
  await viewport.locator('[data-map-control="pan"]').click();
  return {
    id: surface.id,
    route: surface.route,
    controls: controlNames,
    hintTitle: hintTitle.trim(),
    zoomAfterClick,
    zoomAfterOut,
    rectangleZoom: boxZoomState.zoom,
    keyboardPanChanged: panStateAfter.x !== panStateBefore.x,
    renderPolicyStatus: policyStatus,
    tileSources,
    wheelZoomDisabled: true,
  };
}

async function inspectEmbeddedDashboardMap(page, surface) {
  await openDashboardRoute(page, surface.route);
  const iframe = page.locator(surface.frameSelector).first();
  await iframe.waitFor({ state: "attached", timeout: 120000 });
  const frame = iframe.contentFrame();
  const map = frame.locator("#map");
  await map.waitFor({ state: "attached", timeout: 120000 });
  for (const selector of ["#zoomIn", "#zoomOut", "#fitRoute", "#panMode", "#boxZoomMode"]) {
    assert(await frame.locator(selector).count() === 1, `${surface.label} is missing ${selector}.`);
  }
  const hintTarget = frame.locator('[data-evidence-type][tabindex="0"]:visible').first();
  await hintTarget.waitFor({state: "visible", timeout: 120000});
  await hintTarget.focus();
  await frame.locator("#hoverHint:not(.is-hidden)").waitFor({ state: "attached", timeout: 5000 });
  const hintTitle = await frame.locator("#hoverHint strong").textContent();
  assert(Boolean(hintTitle?.trim()), `${surface.label} hint has no title.`);
  const zoomBefore = await frame.locator("#zoomLevel").textContent();
  const viewBoxBeforeWheel = await map.getAttribute("viewBox");
  await map.dispatchEvent("wheel", {deltaY: -120});
  assert(
    await map.getAttribute("viewBox") === viewBoxBeforeWheel,
    `${surface.label} mouse wheel changed map zoom.`,
  );
  if (surface.basemapPolicy === "rudy-twmap-only") {
    const checkedBasemaps = await frame.locator(
      '[data-layer="imagery"]:checked, [data-layer="rudy"]:checked, [data-layer="rudy-twmap"]:checked, [data-layer="relief"]:checked, [data-layer="geology"]:checked, [data-layer="topo-5k"]:checked, [data-layer="forest"]:checked, [data-layer="osm"]:checked',
    ).evaluateAll(nodes => nodes.map(node => node.getAttribute("data-layer")));
    assert(
      checkedBasemaps.length === 1 && checkedBasemaps[0] === "rudy-twmap",
      `${surface.label} checked basemaps are ${checkedBasemaps.join(", ") || "missing"}.`,
    );
  }
  await frame.locator("#zoomIn").click();
  const zoomAfter = await frame.locator("#zoomLevel").textContent();
  assert(zoomAfter !== zoomBefore, `${surface.label} Zoom in did not change scale.`);
  await frame.locator("#zoomOut").click();
  const zoomAfterOut = await frame.locator("#zoomLevel").textContent();
  assert(zoomAfterOut !== zoomAfter, `${surface.label} Zoom out did not reduce scale.`);
  await frame.locator("#zoomIn").click();
  const viewBoxBeforePan = await map.getAttribute("viewBox");
  await map.focus();
  await map.press("ArrowRight");
  const viewBoxAfterPan = await map.getAttribute("viewBox");
  assert(viewBoxAfterPan !== viewBoxBeforePan, `${surface.label} keyboard pan did not change viewBox.`);
  await frame.locator("#fitRoute").click();
  assert(await frame.locator("#zoomLevel").textContent() === zoomBefore, `${surface.label} Fit did not reset scale.`);
  await frame.locator("#boxZoomMode").click();
  assert(
    await frame.locator("#boxZoomMode").getAttribute("aria-pressed") === "true",
    `${surface.label} Box mode did not activate.`,
  );
  const mapBox = await map.boundingBox();
  assert(mapBox, `${surface.label} embedded map has no browser bounds.`);
  const zoomBeforeBox = await frame.locator("#zoomLevel").textContent();
  await page.mouse.move(mapBox.x + mapBox.width * 0.24, mapBox.y + mapBox.height * 0.24);
  await page.mouse.down();
  await page.mouse.move(mapBox.x + mapBox.width * 0.68, mapBox.y + mapBox.height * 0.68, {steps: 6});
  await page.mouse.up();
  const zoomAfterBox = await frame.locator("#zoomLevel").textContent();
  assert(zoomAfterBox !== zoomBeforeBox, `${surface.label} rectangle zoom did not change scale.`);
  await frame.locator("#fitRoute").click();
  await frame.locator("#panMode").click();
  return {
    id: surface.id,
    route: surface.route,
    controls: ["zoom-in", "zoom-out", "reset", "pan", "box-zoom"],
    hintTitle: hintTitle.trim(),
    zoomBefore,
    zoomAfter,
    zoomAfterOut,
    rectangleZoom: zoomAfterBox,
    keyboardPanChanged: viewBoxAfterPan !== viewBoxBeforePan,
    renderPolicyStatus: await map.getAttribute("data-map-render-policy-status"),
    basemapPolicy: surface.basemapPolicy,
    wheelZoomDisabled: true,
  };
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const consoleErrors = [];
  const failedResponses = [];
  const postRequests = [];
  let workspaceRouteMode = "normal";

  page.on("console", message => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", error => consoleErrors.push(error.message));
  page.on("response", response => {
    if (response.status() >= 400) {
      failedResponses.push({ status: response.status(), url: response.url() });
    }
  });
  page.on("request", request => {
    if (request.method() === "POST") postRequests.push(request.url());
  });
  await page.route("**/admin/dashboard/workspaces", async route => {
    if (workspaceRouteMode === "fail") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "synthetic diagnostic failure" }),
      });
      return;
    }
    if (workspaceRouteMode === "delay") {
      await new Promise(resolve => setTimeout(resolve, 450));
    }
    await route.continue();
  });

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.locator('[data-diagnostic-page="true"]').waitFor({ state: "visible", timeout: 60000 });

    const settingsNav = page.locator('[data-route="settings"]');
    const diagnosticNav = page.locator('[data-route="diagnostic"]');
    assert(await settingsNav.count() === 1, "Settings navigation is missing.");
    assert(await diagnosticNav.count() === 1, "Diagnostic navigation is missing.");
    const diagnosticAfterSettings = await page.evaluate(() => {
      const settings = document.querySelector('[data-route="settings"]');
      return settings?.nextElementSibling?.getAttribute("data-route") === "diagnostic";
    });
    assert(diagnosticAfterSettings, "Diagnostic is not immediately after Settings.");
    assert(
      await page.locator("[data-diagnostic-case]").count() === expectedDiagnosticCount,
      `Expected ${expectedDiagnosticCount} diagnostic cases.`,
    );
    assert(
      await page.locator('[data-diagnostic-action="retest"]').count() === expectedDiagnosticCount,
      `Expected ${expectedDiagnosticCount} retest buttons.`,
    );
    assert(await page.locator('[data-diagnostic-action="all"]').count() === 1, "Diag all button is missing.");
    const dashboardMapSurfaces = await page.evaluate(() => (
      window.scoutDashboardDiagnostics?.mapSurfaces || []
    ));
    const expectedMapSurfaceIds = [
      "overview-map",
      "lbs-map",
      "permission-map",
      "emergency-review-map",
      "map",
      "weather-map",
      "navigation-map",
      "architecture-map",
      "pace-fit-map",
    ];
    assert(dashboardMapSurfaces.length === expectedMapSurfaceIds.length, "Dashboard map registry does not contain all expected maps.");
    for (const surfaceId of expectedMapSurfaceIds) {
      assert(dashboardMapSurfaces.some(surface => surface.id === surfaceId), `Dashboard map registry is missing ${surfaceId}.`);
    }
    assert(
      dashboardMapSurfaces.filter(surface => surface.basemapPolicy === "full-canonical").length === 1,
      "Dashboard map registry must have exactly one full-canonical map.",
    );
    assert(
      dashboardMapSurfaces.filter(surface => surface.basemapPolicy === "rudy-twmap-only").length === 8,
      "Dashboard map registry must have eight Rudy+TW-only maps.",
    );

    const dash001 = page.locator('[data-diagnostic-case="DASH-001"]');
    workspaceRouteMode = "delay";
    await dash001.locator('[data-diagnostic-action="retest"]').click();
    await page.waitForFunction(() => (
      document.querySelector('[data-diagnostic-case="DASH-001"]')?.dataset.diagnosticStatus === "running"
    ), null, { timeout: 5000 });
    assert(await dash001.locator("[data-diagnostic-status-label]").textContent() === "測試中", "Running label is incorrect.");
    await page.waitForFunction(() => (
      document.querySelector('[data-diagnostic-case="DASH-001"]')?.dataset.diagnosticStatus === "passed"
    ), null, { timeout: 240000 });
    assert(await dash001.locator("[data-diagnostic-status-label]").textContent() === "測試通過", "Passed label is incorrect.");

    workspaceRouteMode = "fail";
    await dash001.locator('[data-diagnostic-action="retest"]').click();
    await page.waitForFunction(() => (
      document.querySelector('[data-diagnostic-case="DASH-001"]')?.dataset.diagnosticStatus === "failed"
    ), null, { timeout: 30000 });
    assert(await dash001.locator("[data-diagnostic-status-label]").textContent() === "測試失敗", "Failed label is incorrect.");
    workspaceRouteMode = "normal";

    failedResponses.length = 0;
    await page.locator('[data-diagnostic-action="all"]').click();
    await page.waitForFunction(expectedCount => {
      const snapshot = window.scoutDashboardDiagnostics?.snapshot();
      return snapshot
        && snapshot.summary.running === 0
        && snapshot.summary.idle === 0
        && snapshot.summary.passed + snapshot.summary.failed === expectedCount;
    }, expectedDiagnosticCount, { timeout: 480000 });

    const snapshot = await page.evaluate(() => window.scoutDashboardDiagnostics.snapshot());
    assert(snapshot.summary.total === expectedDiagnosticCount, `Diag all summary total is not ${expectedDiagnosticCount}.`);
    assert(snapshot.summary.running === 0, "Diag all left a running case.");
    assert(snapshot.summary.idle === 0, "Diag all left an untested case.");
    assert(
      snapshot.summary.passed + snapshot.summary.failed === expectedDiagnosticCount,
      "Diag all did not finish all cases.",
    );
    for (let index = 1; index <= expectedDiagnosticCount; index += 1) {
      const caseId = `DASH-${String(index).padStart(3, "0")}`;
      const result = snapshot.results[caseId];
      assert(result && ["passed", "failed"].includes(result.status), `${caseId} has no terminal result.`);
      assert(Boolean(result.detail?.trim()), `${caseId} has no diagnostic evidence detail.`);
      assert(!/\bis not defined\b|ReferenceError|TypeError:/i.test(result.detail), `${caseId} failed inside its checker: ${result.detail}`);
      if (!dataDependentDiagnosticIds.has(caseId)) {
        assert(result.status === "passed", `${caseId} implementation check failed: ${result.detail}`);
      }
    }
    for (const caseId of ["DASH-026", "DASH-027", "DASH-028", "DASH-029"]) {
      assert(snapshot.results[caseId]?.status === "passed", `${caseId} did not pass for every Dashboard map.`);
      assert(snapshot.results[caseId]?.detail.includes("9 Dashboard maps"), `${caseId} did not report the nine-map scope.`);
    }
    assert(postRequests.length === 0, `Diagnostic issued unexpected POST requests: ${postRequests.join(", ")}`);

    await page.screenshot({
      path: "/tmp/scout-dashboard-diagnostic-desktop.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileLayout = await page.evaluate(() => {
      const firstCase = document.querySelector("[data-diagnostic-case]");
      const retest = firstCase?.querySelector('[data-diagnostic-action="retest"]');
      const caseRect = firstCase?.getBoundingClientRect();
      const buttonRect = retest?.getBoundingClientRect();
      return {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        caseWidth: caseRect?.width || 0,
        buttonWidth: buttonRect?.width || 0,
      };
    });
    assert(mobileLayout.scrollWidth === mobileLayout.clientWidth, "Diagnostic has mobile page-level horizontal overflow.");
    assert(mobileLayout.caseWidth <= mobileLayout.clientWidth, "Diagnostic case exceeds the mobile viewport.");
    assert(mobileLayout.buttonWidth > 0, "Diagnostic retest button is not measurable on mobile.");

    await page.screenshot({
      path: "/tmp/scout-dashboard-diagnostic-mobile.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    const browserMapChecks = [];
    for (const surface of [
      {id: "overview-map", route: "home", label: "Overview Map preview", viewportId: "overview-map"},
      {id: "lbs-map", route: "features-lbs", label: "LBS Map", viewportId: "lbs-map"},
      {id: "permission-map", route: "outdoor-permission", label: "Permission Map", viewportId: "permission-map"},
      {id: "emergency-review-map", route: "emergency", label: "Emergency Review Map", viewportId: "emergency-review-map"},
      {id: "navigation-map", route: "outdoor-navigation", label: "Navigation Map", viewportId: "navigation-workspace-map"},
      {id: "architecture-map", route: "outdoor-architecture", label: "Architecture Map", viewportId: "architecture-map"},
      {id: "pace-fit-map", route: "outdoor-pace-fit", label: "Pace Fit Map", viewportId: "pace-fit-map"},
    ]) {
      browserMapChecks.push(await inspectNativeDashboardMap(page, surface));
    }
    for (const surface of [
      {id: "map", route: "map", label: "Map", frameSelector: "#pretripMapFrame", basemapPolicy: "full-canonical"},
      {id: "weather-map", route: "outdoor-weather", label: "Weather Map", frameSelector: '[data-weather-cwa-map-frame="true"]', basemapPolicy: "rudy-twmap-only"},
    ]) {
      browserMapChecks.push(await inspectEmbeddedDashboardMap(page, surface));
    }
    assert(browserMapChecks.length === expectedMapSurfaceIds.length, "Not every Dashboard map was exercised in Chromium.");

    process.stdout.write(JSON.stringify({
      ok: true,
      url: baseUrl,
      summary: snapshot.summary,
      failedCaseIds: Object.entries(snapshot.results)
        .filter(([, result]) => result.status === "failed")
        .map(([id]) => id),
      failedCases: Object.fromEntries(
        Object.entries(snapshot.results)
          .filter(([, result]) => result.status === "failed")
          .map(([id, result]) => [id, result.detail]),
      ),
      mapParityCases: Object.fromEntries(
        ["DASH-026", "DASH-027", "DASH-028", "DASH-029"]
          .map(id => [id, snapshot.results[id]]),
      ),
      dashboardMapSurfaces,
      browserMapChecks,
      zeroCountEvidenceCase: snapshot.results["DASH-030"],
      dataDependentDiagnosticIds: [...dataDependentDiagnosticIds],
      postRequestCount: postRequests.length,
      mobileLayout,
      consoleErrors,
      failedResponses,
      screenshots: [
        "/tmp/scout-dashboard-diagnostic-desktop.png",
        "/tmp/scout-dashboard-diagnostic-mobile.png",
      ],
    }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
