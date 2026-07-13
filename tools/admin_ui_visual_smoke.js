#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { spawn } = require("child_process");
const Module = require("module");

const repoRoot = path.resolve(__dirname, "..");
const bundledNodeModules = path.join(
  process.env.HOME || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
);
process.env.NODE_PATH = [process.env.NODE_PATH, bundledNodeModules].filter(Boolean).join(path.delimiter);
Module._initPaths();

const { chromium } = require("playwright");
const SCOUT_ADMIN_UI_STARTUP_TIMEOUT_MS = Math.max(
  5_000,
  Number(process.env.SCOUT_ADMIN_UI_STARTUP_TIMEOUT_MS || 20_000),
);

const scoutLayerIds = [
  "imagery",
  "rudy",
  "rudy-twmap",
  "relief",
  "geology",
  "topo-5k",
  "forest",
  "osm",
  "terrain",
  "corridors",
  "overpass",
  "route",
  "completed-track",
  "reference-tracks",
  "retreat",
  "segments",
  "risk-ribbon",
  "risk-heatmap",
  "risk-delta",
  "soil-moisture",
  "antecedent-rain",
  "cwa-qpf",
  "risk-score",
  "checkpoints",
  "pois",
  "hazards",
  "route-notes",
  "cwa-weather",
  "mcp",
  "boss-points",
  "events",
  "weather-api",
];

const expectedLayerIdsBySurface = {
  debug: scoutLayerIds.filter((layerId) => layerId !== "completed-track"),
  "after-action": scoutLayerIds,
  pretrip: scoutLayerIds.filter((layerId) => layerId !== "completed-track"),
  dashboard: scoutLayerIds.filter((layerId) => layerId !== "completed-track"),
};

const surfaces = [
  {
    id: "debug",
    path: "/admin/debug?tab=panel-state&event=debug_event.admin_ui_smoke.000003",
    title: "Scout Phase 3.5 Runtime Debug",
    selectors: ["#timeline", "#runtimeMap", '[role="tablist"]', ".timeline-node.is-selected"],
    ready: [
      { selector: "#runtimeMap", missingText: "Loading" },
      { selector: ".timeline-node.is-selected", missingText: "Loading" },
    ],
  },
  {
    id: "after-action",
    path: "/admin",
    title: "Scout Phase 1 Admin",
    selectors: ["#map", "#evidenceTree", "#narrativePanel", "#rawJsonDetails"],
    ready: [
      { selector: "#narrativePanel", missingText: "Loading" },
      { selector: "#evidenceTree", missingText: "Loading" },
    ],
  },
  {
    id: "pretrip",
    path: "/admin/pretrip",
    title: "Scout Phase 4 Pre-Trip Planning",
    selectors: ["#readinessStrip", "#map", "#evidenceTree", "#jsonPane"],
    ready: [
      { selector: "#readinessStripStatus", missingText: "Loading" },
      { selector: "#routeMeta", missingText: "Loading" },
      { selector: "#detailTitle", missingText: "No selection" },
    ],
  },
  {
    id: "hardware-readiness",
    path: "/admin/hardware-readiness",
    title: "Scout Hardware Readiness",
    selectors: ["#providerGrid .provider-card", "#evidenceList", "#assistantPanel", "#assistantProviderStatus"],
    ready: [
      { selector: "#providerCount", missingText: "0" },
      { selector: "#assistantProviderStatus", missingText: "Loading" },
    ],
  },
  {
    id: "dashboard",
    path: "/admin/dashboard?projectId=chilai_nanhua_day1#map",
    title: "Scout Dashboard v0.1",
    selectors: ["#dashboardShell", "#dashboardMap", "#dashboardMapStatus", "#dashboardMapEvidence", "#dashboardEvidence", "#pretripMapFrame"],
    ready: [
      { selector: "#dashboardRouteStatus", missingText: "Loading" },
      { selector: "#dashboardMapStatus", missingText: "fallback geometry" },
    ],
    frameSelector: "#pretripMapFrame",
    frameSurfaceId: "dashboard-map-only",
    frameTitle: "Scout Phase 4 Pre-Trip Planning",
    frameSelectors: ["#map", ".map-pane", ".toolbar", 'input[data-layer="route"]'],
    frameVisibleSelectors: ["#map", ".map-pane", ".toolbar"],
    frameHiddenSelectors: [
      "#readinessStrip",
      ".toolbar-title",
      ".tool-disclosure",
      ".route-pane",
      ".detail-pane",
      "#evidenceTree",
      "#jsonPane",
    ],
    frameReady: [],
    frameMustFitViewport: true,
  },
];

const viewports = [
  { id: "desktop", width: 1440, height: 1000 },
  { id: "mobile", width: 390, height: 844 },
  { id: "compact", width: 320, height: 720 },
];

function cwaImageryFixtureManifest() {
  const frame = (family, index, imageType, opacity) => ({
    frameId: `${family}.fixture.${index}`,
    productId: `${family}.${imageType}.taiwan`,
    sourceTimestamp: `2026-07-13T0${index}:20:00+08:00`,
    fetchedAt: `2026-07-13T0${index}:27:00+08:00`,
    imageType,
    extent: "taiwan",
    expectedDelayMinutes: family === "radar" ? 12 : 20,
    dataDelayMinutes: 7,
    bboxWgs84: { west: 120.5, south: 23.5, east: 121.5, north: 24.5 },
    mediaType: "image/svg+xml",
    mapOverlaySupported: true,
    assetUrl: `/admin/pretrip/projects/chilai_nanhua_day1/weather-imagery/${family}.fixture.${index}`,
    fixtureOpacity: opacity,
  });
  const radarFrames = [frame("radar", 1, "echo_no_terrain", 0.62), frame("radar", 2, "echo_no_terrain", 0.62)];
  const satelliteFrames = [frame("satellite", 1, "enhanced_color", 0.48), frame("satellite", 2, "enhanced_color", 0.48)];
  const windows = {
    "3h": [radarFrames[0].frameId, radarFrames[1].frameId],
    "6h": [radarFrames[0].frameId, radarFrames[1].frameId],
    "9h": [radarFrames[0].frameId, radarFrames[1].frameId],
    "12h": [radarFrames[0].frameId, radarFrames[1].frameId],
  };
  const satelliteWindows = Object.fromEntries(Object.entries(windows).map(([key]) => [key, satelliteFrames.map(item => item.frameId)]));
  return {
    artifactKind: "weatherImageryTimelineManifest",
    schemaVersion: "weatherImageryTimelineManifest.v1",
    projectId: "chilai_nanhua_day1",
    layerId: "cwa-weather",
    animationWindowsHours: [3, 6, 9, 12],
    childOverlays: {
      radar: { latestFrameId: radarFrames[1].frameId, frames: radarFrames, windows },
      satellite: { latestFrameId: satelliteFrames[1].frameId, frames: satelliteFrames, windows: satelliteWindows },
    },
    processingBoundary: {
      adminReadIsCacheOnly: true,
      upstreamFetchOnRead: false,
      candidateOnly: true,
      runtimeSafetyTruth: false,
    },
  };
}

async function installCwaImageryFixture(page) {
  await page.route(/\/admin\/pretrip\/projects\/[^/]+\/weather-imagery(?:\/[^/?]+)?(?:\?.*)?$/, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/weather-imagery")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(cwaImageryFixtureManifest()),
      });
      return;
    }
    const radar = pathname.includes("/radar.fixture.");
    const fill = radar ? "rgba(44,160,210,.65)" : "rgba(245,182,47,.42)";
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="${fill}"/></svg>`,
    });
  });
  await page.route(/\/admin\/pretrip\/projects\/chilai_nanhua_day1\/rainfall-(?:grids|grid-overlay)(?:\?.*)?$/, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const projectId = "chilai_nanhua_day1";
    const overlay = pathname.endsWith("/rainfall-grid-overlay");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(overlay ? {
        projectId,
        status: "no_coverage",
        gridCells: [],
        cachePolicy: {adminReadIsCacheOnly: true, upstreamFetchOnRead: false},
        boundary: {candidateOnly: true, runtimeSafetyTruth: false},
      } : {
        projectId,
        status: "unavailable",
        products: [],
        processingBoundary: {adminReadIsCacheOnly: true, upstreamFetchOnRead: false, candidateOnly: true},
      }),
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const port = args.port || await freePort();
  const server = startServer(port, args.python);
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    await waitFor(`${baseUrl}/admin`, SCOUT_ADMIN_UI_STARTUP_TIMEOUT_MS);
    const report = await runBrowserChecks(baseUrl, args.screenshotsDir);
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await stopServer(server);
  }
}

function parseArgs(args) {
  const parsed = { port: 0, screenshotsDir: "" };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--port") parsed.port = Number(args[++index]);
    else if (arg === "--python") parsed.python = args[++index];
    else if (arg === "--screenshots-dir") parsed.screenshotsDir = args[++index];
    else if (arg === "--help") {
      process.stdout.write([
        "Usage: node tools/admin_ui_visual_smoke.js [--port PORT] [--python PYTHON] [--screenshots-dir DIR]",
        "",
        "Starts a fixture-backed Scout admin smoke app and checks /admin/debug, /admin, and /admin/pretrip",
        "in desktop and mobile Chromium viewports.",
        "",
      ].join("\n"));
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return parsed;
}

function startServer(port, pythonOverride) {
  const python = pythonOverride || process.env.SCOUT_PYTHON || path.join(repoRoot, "venv/bin/python");
  const serverPath = path.join(repoRoot, "tools/admin_ui_smoke_app.py");
  const child = spawn(python, [serverPath, "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
  child.on("exit", (code, signal) => {
    if (code && !child.killed) {
      process.stderr.write(`admin UI smoke server exited with ${code || signal}\n${stderr}\n`);
    }
  });
  return child;
}

function stopServer(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
      resolve();
    }, 3_000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

async function runBrowserChecks(baseUrl, screenshotsDir) {
  if (screenshotsDir) fs.mkdirSync(screenshotsDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
      await installCwaImageryFixture(page);
      const consoleErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") {
          const location = message.location();
          consoleErrors.push(`${message.text()}${location.url ? ` @ ${location.url}` : ""}`);
        }
      });
      page.on("pageerror", (error) => consoleErrors.push(error.message));

      for (const surface of surfaces) {
        const url = `${baseUrl}${surface.path}`;
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: SCOUT_ADMIN_UI_STARTUP_TIMEOUT_MS });
        await page.waitForTimeout(250);
        await waitForSurface(surface, page);
        const frameShellChecks = surface.frameMustFitViewport
          ? await collectFrameShellChecks(surface, page)
          : undefined;
        const checkTarget = await checkTargetForSurface(surface, page);
        const expectedLayerIds = expectedLayerIdsBySurface[surface.id] || [];
        await waitForLayerGroups(checkTarget.context, expectedLayerIds);
        const checks = await collectChecks(
          checkTarget.surface,
          checkTarget.context,
          expectedLayerIds,
        );
        const screenshotPath = screenshotsDir
          ? path.join(screenshotsDir, `${surface.id}-${viewport.id}.png`)
          : "";
        if (screenshotPath) await page.screenshot({ path: screenshotPath, fullPage: false });
        const frameReuseChecks = surface.id === "dashboard"
          ? await collectDashboardFrameReuseChecks(page)
          : undefined;
        results.push({
          surface: surface.id,
          viewport: viewport.id,
          url,
          title: await page.title(),
          checkedTitle: await checkTarget.context.title(),
          screenshot: screenshotPath || undefined,
          frameShellChecks,
          frameReuseChecks,
          checks,
        });
      }

      await page.close();
      if (consoleErrors.length) {
        throw new Error(`Console errors in ${viewport.id}: ${consoleErrors.join(" | ")}`);
      }
    }
  } finally {
    await browser.close();
  }
  return { ok: true, surfaces: results };
}

async function checkTargetForSurface(surface, page) {
  if (!surface.frameSelector) return { context: page, surface };
  const frameElement = await page.waitForSelector(surface.frameSelector, {
    state: "attached",
    timeout: 10_000,
  });
  const frame = await frameElement.contentFrame();
  if (!frame) throw new Error(`Frame not available for ${surface.id}: ${surface.frameSelector}`);
  const framedSurface = {
    ...surface,
    id: surface.frameSurfaceId || surface.id,
    title: surface.frameTitle || surface.title,
    selectors: surface.frameSelectors || [],
    visibleSelectors: surface.frameVisibleSelectors || [],
    hiddenSelectors: surface.frameHiddenSelectors || [],
    ready: surface.frameReady || [],
    readyTimeoutMs: surface.frameReadyTimeoutMs || surface.readyTimeoutMs,
  };
  await waitForSurface(framedSurface, frame);
  return { context: frame, surface: framedSurface };
}

async function collectFrameShellChecks(surface, page) {
  return page.evaluate(({ frameSelector }) => {
    const frame = document.querySelector(frameSelector);
    if (!frame) throw new Error(`Frame shell missing: ${frameSelector}`);
    const rect = frame.getBoundingClientRect();
    const verticalOverflowPx = Math.max(
      0,
      document.documentElement.scrollHeight - window.innerHeight,
      document.body.scrollHeight - window.innerHeight,
    );
    const frameBottomOverflowPx = Math.max(0, Math.round(rect.bottom - window.innerHeight));
    const frameTop = Math.round(rect.top);
    const ok = verticalOverflowPx <= 1 && frameBottomOverflowPx <= 1 && frameTop >= 0;
    if (!ok) {
      throw new Error(JSON.stringify({
        frameSelector,
        verticalOverflowPx,
        frameBottomOverflowPx,
        frameTop,
        frameBottom: Math.round(rect.bottom),
        viewportHeight: window.innerHeight,
      }));
    }
    return {
      ok,
      verticalOverflowPx,
      frameBottomOverflowPx,
      frameTop,
      frameBottom: Math.round(rect.bottom),
      viewportHeight: window.innerHeight,
    };
  }, { frameSelector: surface.frameSelector });
}

async function collectDashboardFrameReuseChecks(page) {
  const result = await page.evaluate(async () => {
    const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
    const frame = document.querySelector("#pretripMapFrame");
    if (!frame) throw new Error("Dashboard map frame missing");
    const initialSrc = frame.src;
    frame.dataset.smokeLoadCount = "0";
    if (frame.dataset.smokeLoadBound !== "true") {
      frame.dataset.smokeLoadBound = "true";
      frame.addEventListener("load", () => {
        frame.dataset.smokeLoadCount = String(Number(frame.dataset.smokeLoadCount || "0") + 1);
      });
    }
    window.location.hash = "#timeline";
    await delay(100);
    const hiddenWhileAway = document.querySelector("#dashboardMap")?.hidden === true;
    window.location.hash = "#map";
    await delay(350);
    const loadCount = Number(frame.dataset.smokeLoadCount || "0");
    const sameSrc = frame.src === initialSrc;
    const visibleAfterReturn = document.querySelector("#dashboardMap")?.hidden === false;
    for (let attempt = 0; attempt < 20 && !document.querySelector("#dashboardCwaImagery"); attempt += 1) {
      await delay(100);
    }
    const cwaPanel = document.querySelector("#dashboardCwaImagery");
    const sheetToggle = cwaPanel?.querySelector("[data-dashboard-cwa-panel-toggle]");
    if (cwaPanel?.dataset.dashboardCwaSheetState === "peek") {
      sheetToggle?.click();
      await delay(50);
    }
    const cwaSelectors = [
      "[data-dashboard-cwa-imagery-layer]",
      "[data-dashboard-cwa-rainfall-layer]",
      "[data-dashboard-cwa-rainfall-product]",
      "[data-dashboard-cwa-rainfall-opacity]",
      "[data-dashboard-cwa-imagery-product]",
      "[data-dashboard-cwa-imagery-window]",
      "[data-dashboard-cwa-imagery-timeline]",
      '[data-dashboard-cwa-imagery-opacity="radar"]',
      '[data-dashboard-cwa-imagery-opacity="satellite"]',
      "[data-dashboard-cwa-imagery-play]",
      "[data-dashboard-cwa-imagery-status]",
    ];
    const cwaControls = cwaSelectors.map((selector) => cwaPanel?.querySelector(selector));
    const panelRect = cwaPanel?.getBoundingClientRect();
    const railRect = document.querySelector("#dashboardMapEvidence")?.getBoundingClientRect();
    const mapRect = document.querySelector("#dashboardMap")?.getBoundingClientRect();
    const minTouchTargetPx = 44;
    const cwaSheetFitsViewport = Boolean(panelRect
      && panelRect.top >= 0
      && panelRect.bottom <= window.innerHeight + 1
      && (window.innerWidth > 620 || panelRect.height <= window.innerHeight * 0.7 + 1));
    const cwaMapVisibleHeight = window.innerWidth <= 620 && railRect && mapRect
      ? Math.max(0, Math.round(railRect.top - mapRect.top))
      : Math.round(window.innerHeight);
    const cwaControlsInViewport = Boolean(panelRect
      && panelRect.width > 0
      && panelRect.height > 0
      && panelRect.left >= 0
      && panelRect.right <= window.innerWidth + 1
      && cwaControls.every((control, index) => {
        const rect = control?.getBoundingClientRect();
        const minimum = index === cwaControls.length - 1 ? 24 : minTouchTargetPx;
        return rect && rect.width >= minimum && rect.height >= minimum;
      }));
    const controller = frame.contentWindow?.scoutCwaImageryController;
    let cwaControlsInteractive = false;
    let cwaOverlayDomUpdated = false;
    if (controller && cwaControls.every(Boolean)) {
      const layer = cwaPanel.querySelector("[data-dashboard-cwa-imagery-layer]");
      const rainfallLayer = cwaPanel.querySelector("[data-dashboard-cwa-rainfall-layer]");
      const rainfallProduct = cwaPanel.querySelector("[data-dashboard-cwa-rainfall-product]");
      const rainfallOpacity = cwaPanel.querySelector("[data-dashboard-cwa-rainfall-opacity]");
      const windowControl = cwaPanel.querySelector("[data-dashboard-cwa-imagery-window]");
      const radarOpacity = cwaPanel.querySelector('[data-dashboard-cwa-imagery-opacity="radar"]');
      const timeline = cwaPanel.querySelector("[data-dashboard-cwa-imagery-timeline]");
      const play = cwaPanel.querySelector("[data-dashboard-cwa-imagery-play]");
      layer.checked = true;
      layer.dispatchEvent(new Event("change", {bubbles: true}));
      rainfallLayer.checked = true;
      rainfallLayer.dispatchEvent(new Event("change", {bubbles: true}));
      rainfallProduct.value = "qpe_past_1h";
      rainfallProduct.dispatchEvent(new Event("change", {bubbles: true}));
      rainfallOpacity.value = "41";
      rainfallOpacity.dispatchEvent(new Event("input", {bubbles: true}));
      windowControl.value = "3h";
      windowControl.dispatchEvent(new Event("change", {bubbles: true}));
      radarOpacity.value = "37";
      radarOpacity.dispatchEvent(new Event("input", {bubbles: true}));
      timeline.value = "1";
      timeline.dispatchEvent(new Event("input", {bubbles: true}));
      play.click();
      await delay(50);
      const active = controller.getState();
      play.click();
      await delay(50);
      const stopped = controller.getState();
      const radarImage = frame.contentDocument?.querySelector('image[data-cwa-imagery-family="radar"]');
      const satelliteImage = frame.contentDocument?.querySelector('image[data-cwa-imagery-family="satellite"]');
      cwaOverlayDomUpdated = radarImage?.getAttribute("data-cwa-imagery-frame") === "radar.fixture.2"
        && !satelliteImage
        && Math.abs(Number(radarImage?.getAttribute("opacity")) - 0.37) < 0.001;
      cwaControlsInteractive = active.layerEnabled === true
        && active.rainfallLayerEnabled === true
        && active.rainfallProduct === "qpe_past_1h"
        && active.rainfallOpacityPercent === 41
        && active.windowId === "3h"
        && active.frameIndex === 1
        && active.radarOpacityPercent === 37
        && active.playing === true
        && stopped.playing === false;
      controller.setLayerEnabled(false);
      controller.setRainfallLayerEnabled(false);
      controller.setRainfallProduct("qpf_next_1h");
      controller.setRainfallOpacity(56);
      controller.setProduct("radar");
      controller.setWindow("12h");
      controller.setOpacity("radar", 62);
    }
    const cwaOverlayImages = frame.contentDocument?.querySelectorAll("image[data-cwa-imagery-family]").length || 0;
    const ok = hiddenWhileAway
      && visibleAfterReturn
      && sameSrc
      && loadCount === 0
      && cwaControlsInViewport
      && cwaSheetFitsViewport
      && cwaMapVisibleHeight >= (window.innerWidth <= 620 ? Math.round(window.innerHeight * 0.25) : 1)
      && cwaControlsInteractive
      && cwaOverlayImages === 1
      && cwaOverlayDomUpdated;
    if (!ok) {
      throw new Error(JSON.stringify({
        hiddenWhileAway,
        visibleAfterReturn,
        sameSrc,
        loadCount,
        initialSrc,
        currentSrc: frame.src,
        cwaControlsInViewport,
        cwaSheetFitsViewport,
        cwaMapVisibleHeight,
        minTouchTargetPx: 44,
        cwaPanelRect: panelRect ? {
          top: Math.round(panelRect.top),
          bottom: Math.round(panelRect.bottom),
          height: Math.round(panelRect.height),
        } : null,
        cwaRailRect: railRect ? {
          top: Math.round(railRect.top),
          bottom: Math.round(railRect.bottom),
          height: Math.round(railRect.height),
        } : null,
        viewport: {width: window.innerWidth, height: window.innerHeight},
        cwaControlsInteractive,
        cwaOverlayImages,
        cwaOverlayDomUpdated,
      }));
    }
    return {
      ok,
      hiddenWhileAway,
      visibleAfterReturn,
      sameSrc,
      loadCount,
      cwaControlsInViewport,
      cwaSheetFitsViewport,
      cwaMapVisibleHeight,
      minTouchTargetPx: 44,
      cwaControlsInteractive,
      cwaOverlayImages,
      cwaOverlayDomUpdated,
    };
  });
  const focusOrder = [
    "[data-dashboard-cwa-imagery-layer]",
    "[data-dashboard-cwa-rainfall-layer]",
    "[data-dashboard-cwa-rainfall-product]",
    "[data-dashboard-cwa-rainfall-opacity]",
    "[data-dashboard-cwa-imagery-product]",
    "[data-dashboard-cwa-imagery-window]",
    "[data-dashboard-cwa-imagery-timeline]",
    '[data-dashboard-cwa-imagery-opacity="radar"]',
    '[data-dashboard-cwa-imagery-opacity="satellite"]',
    "[data-dashboard-cwa-imagery-play]",
  ];
  await page.locator(focusOrder[0]).focus();
  await page.keyboard.press("Space");
  const keyboardFocusResults = [{ selector: focusOrder[0], focused: true }];
  for (const selector of focusOrder.slice(1)) {
    await page.keyboard.press("Tab");
    keyboardFocusResults.push({
      selector,
      focused: await page.evaluate((candidate) => document.activeElement?.matches(candidate) === true, selector),
    });
  }
  const focusVisible = await page.evaluate(() => {
    const node = document.activeElement;
    if (!node) return false;
    const style = getComputedStyle(node);
    return style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth || "0") >= 2;
  });
  await page.keyboard.press("Space");
  await page.waitForTimeout(50);
  const playingFromKeyboard = await page.evaluate(() => (
    document.querySelector("#pretripMapFrame")?.contentWindow?.scoutCwaImageryController?.getState?.().playing === true
  ));
  await page.keyboard.press("Space");
  await page.waitForTimeout(50);
  await page.locator("[data-dashboard-cwa-imagery-timeline]").focus();
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(50);
  const rangeChangedFromKeyboard = await page.evaluate(() => (
    document.querySelector("#pretripMapFrame")?.contentWindow?.scoutCwaImageryController?.getState?.().frameIndex === 1
  ));
  await page.evaluate(() => {
    const controller = document.querySelector("#pretripMapFrame")?.contentWindow?.scoutCwaImageryController;
    controller?.setLayerEnabled(false);
    controller?.setRainfallLayerEnabled(false);
    controller?.setRainfallProduct("qpf_next_1h");
    controller?.setRainfallOpacity(56);
    controller?.setProduct("radar");
    controller?.setFrameIndex(0);
    controller?.setPlaying(false);
  });
  const cwaKeyboardAccessible = keyboardFocusResults.every(item => item.focused)
    && focusVisible
    && playingFromKeyboard
    && rangeChangedFromKeyboard;
  if (!cwaKeyboardAccessible) {
    throw new Error(JSON.stringify({
      cwaKeyboardAccessible,
      keyboardFocusResults,
      focusVisible,
      playingFromKeyboard,
      rangeChangedFromKeyboard,
    }));
  }
  return {
    ...result,
    cwaKeyboardAccessible,
    keyboardFocusResults,
    focusVisible,
    playingFromKeyboard,
    rangeChangedFromKeyboard,
  };
}

async function waitForSurface(surface, page) {
  for (const selector of surface.selectors) {
    await page.waitForSelector(selector, { state: "attached", timeout: 10_000 });
  }
  for (const selector of surface.visibleSelectors || []) {
    await page.waitForSelector(selector, { state: "visible", timeout: 10_000 });
  }
  for (const selector of surface.hiddenSelectors || []) {
    await page.waitForFunction(
      (candidate) => {
        const node = document.querySelector(candidate);
        if (!node) return false;
        const rect = node.getBoundingClientRect();
        return getComputedStyle(node).display === "none" || rect.width === 0 || rect.height === 0;
      },
      selector,
      { timeout: 10_000 },
    );
  }
  for (const ready of surface.ready || []) {
    try {
      await page.waitForFunction(
        ({ selector, missingText }) => {
          const node = document.querySelector(selector);
          return Boolean(node) && !node.textContent.includes(missingText);
        },
        ready,
        { timeout: surface.readyTimeoutMs || 10_000 },
      );
    } catch (error) {
      const observed = await page.evaluate((selector) => (
        document.querySelector(selector)?.textContent || ""
      ), ready.selector).catch(() => "");
      throw new Error(
        `Ready check timed out for ${surface.id} selector ${ready.selector} `
        + `while waiting to remove ${JSON.stringify(ready.missingText)}; observed=${JSON.stringify(observed.slice(0, 160))}`,
      );
    }
  }
}

async function waitForLayerGroups(page, expectedLayerIds) {
  if (!expectedLayerIds.length) return;
  await page.waitForFunction(
    (layerIds) => {
      function selectorValue(value) {
        if (window.CSS?.escape) return CSS.escape(value);
        return String(value).replace(/["\\]/g, "\\$&");
      }
      return layerIds.every((layerId) => (
        Boolean(document.querySelector(`[data-layer-group="${selectorValue(layerId)}"]`))
      ));
    },
    expectedLayerIds,
    { timeout: 60_000 },
  );
}

async function collectChecks(surface, page, expectedLayerIds) {
  return page.evaluate(({ surfaceId, expectedTitle, selectors, visibleSelectors, hiddenSelectors, expectedLayerIds }) => {
    function compareCenteredMapColumns(leftSelector, mapSelector, rightSelector) {
      const left = document.querySelector(leftSelector)?.getBoundingClientRect();
      const map = document.querySelector(mapSelector)?.getBoundingClientRect();
      const right = document.querySelector(rightSelector)?.getBoundingClientRect();
      if (!left || !map || !right) {
        return { ok: false, reason: "missing layout columns" };
      }
      const visible = [left, map, right].every((rect) => rect.width > 0 && rect.height > 0);
      const desktop = document.documentElement.clientWidth >= 1100;
      const centered = !desktop || (left.left < map.left && map.right < right.right);
      const mapIsLargest = !desktop || (map.width > left.width && map.width > right.width);
      return {
        ok: visible && centered && mapIsLargest,
        centered,
        mapIsLargest,
        widths: {
          left: Math.round(left.width),
          map: Math.round(map.width),
          right: Math.round(right.width),
        },
      };
    }
    function centeredMapLayout() {
      if (surfaceId === "pretrip") {
        return compareCenteredMapColumns(".route-pane", ".map-pane", ".detail-pane");
      }
      if (surfaceId === "dashboard-map-only") {
        const mapPane = document.querySelector(".map-pane")?.getBoundingClientRect();
        const map = document.querySelector("#map")?.getBoundingClientRect();
        const toolbar = document.querySelector(".toolbar")?.getBoundingClientRect();
        if (!mapPane || !map || !toolbar) {
          return { ok: false, reason: "missing dashboard map-only layout" };
        }
        return {
          ok: mapPane.width > 0
            && mapPane.height > 0
            && map.width > 0
            && map.height > 0
            && toolbar.width > 0
            && toolbar.height > 0
            && mapPane.width >= document.documentElement.clientWidth - 4,
          mapOnly: true,
          widths: {
            mapPane: Math.round(mapPane.width),
            map: Math.round(map.width),
            viewport: Math.round(document.documentElement.clientWidth),
          },
        };
      }
      if (surfaceId === "after-action") {
        return compareCenteredMapColumns(".tree-pane", ".map-pane", ".json-pane");
      }
      if (surfaceId === "debug") {
        return compareCenteredMapColumns(".timeline-panel", ".map-panel", ".details-panel");
      }
      return { ok: true, skipped: true };
    }
    function selectorValue(value) {
      if (window.CSS?.escape) return CSS.escape(value);
      return String(value).replace(/["\\]/g, "\\$&");
    }
    function layerControlChecks() {
      if (!expectedLayerIds.length) return { ok: true, skipped: true };
      function isGroupHidden(group) {
        return group.getAttribute("data-layer-hidden") === "true"
          || group.style.display === "none"
          || getComputedStyle(group).display === "none";
      }
      const controls = Array.from(document.querySelectorAll("input[data-layer]"))
        .map((input) => input.dataset.layer)
        .filter(Boolean);
      const unexpectedControls = controls.filter((layerId) => !expectedLayerIds.includes(layerId));
      const missingControls = expectedLayerIds.filter((layerId) => !controls.includes(layerId));
      const toggleResults = [];
      for (const layerId of expectedLayerIds) {
        const input = document.querySelector(`input[data-layer="${selectorValue(layerId)}"]`);
        const group = document.querySelector(`[data-layer-group="${selectorValue(layerId)}"]`);
        if (!input || !group) {
          toggleResults.push({
            layerId,
            ok: false,
            controlPresent: Boolean(input),
            groupPresent: Boolean(group),
          });
          continue;
        }
        const originalChecked = input.checked;
        input.checked = false;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        const hidden = isGroupHidden(group);
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        const shown = !isGroupHidden(group);
        input.checked = originalChecked;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        toggleResults.push({
          layerId,
          ok: hidden && shown,
          controlPresent: true,
          groupPresent: true,
          hidden,
          shown,
        });
      }
      const failedToggles = toggleResults.filter((result) => !result.ok);
      return {
        ok: missingControls.length === 0
          && unexpectedControls.length === 0
          && failedToggles.length === 0,
        expectedCount: expectedLayerIds.length,
        controlCount: controls.length,
        missingControls,
        unexpectedControls,
        failedToggles,
        toggleResults,
      };
    }
    const doc = document.documentElement;
    const bodyText = document.body.innerText.trim();
    const selectorResults = selectors.map((selector) => ({
      selector,
      count: document.querySelectorAll(selector).length,
    }));
    const visibleSelectorResults = (visibleSelectors || []).map((selector) => {
      const node = document.querySelector(selector);
      const rect = node?.getBoundingClientRect();
      return {
        selector,
        visible: Boolean(rect && rect.width > 0 && rect.height > 0 && getComputedStyle(node).display !== "none"),
      };
    });
    const hiddenSelectorResults = (hiddenSelectors || []).map((selector) => {
      const node = document.querySelector(selector);
      const rect = node?.getBoundingClientRect();
      return {
        selector,
        hidden: Boolean(node && (getComputedStyle(node).display === "none" || rect.width === 0 || rect.height === 0)),
      };
    });
    const missingSelectors = selectorResults
      .filter((result) => result.count === 0)
      .map((result) => result.selector);
    const failedVisibleSelectors = visibleSelectorResults
      .filter((result) => !result.visible)
      .map((result) => result.selector);
    const failedHiddenSelectors = hiddenSelectorResults
      .filter((result) => !result.hidden)
      .map((result) => result.selector);
    const horizontalOverflowPx = Math.max(0, doc.scrollWidth - doc.clientWidth);
    const visibleTextBlocks = Array.from(document.querySelectorAll("h1,h2,h3,p,button,summary,strong,small"))
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
      })
      .length;
    const tinyTargets = Array.from(document.querySelectorAll("button,[role='button'],[role='tab'],summary"))
      .filter((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24);
      })
      .map((node) => node.id || node.textContent.trim().slice(0, 32));
    const titleMatches = document.title === expectedTitle || document.title.startsWith(`${expectedTitle} | `);
    const nonBlank = surfaceId === "dashboard-map-only"
      ? bodyText.length > 40 && visibleTextBlocks >= 3
      : bodyText.length > 80 && visibleTextBlocks >= 6;
    const noHorizontalOverflow = horizontalOverflowPx <= 24;
    const mapLayout = centeredMapLayout();
    const layerControls = layerControlChecks();
    if (
      missingSelectors.length
      || failedVisibleSelectors.length
      || failedHiddenSelectors.length
      || !titleMatches
      || !nonBlank
      || !noHorizontalOverflow
      || tinyTargets.length
      || !mapLayout.ok
      || !layerControls.ok
    ) {
      throw new Error(JSON.stringify({
        missingSelectors,
        failedVisibleSelectors,
        failedHiddenSelectors,
        titleMatches,
        nonBlank,
        noHorizontalOverflow,
        horizontalOverflowPx,
        tinyTargets,
        mapLayout,
        layerControls,
      }));
    }
    return {
      titleMatches,
      selectorResults,
      visibleSelectorResults,
      hiddenSelectorResults,
      nonBlank,
      visibleTextBlocks,
      noHorizontalOverflow,
      horizontalOverflowPx,
      tinyTargets,
      mapLayout,
      layerControls,
    };
  }, {
    surfaceId: surface.id,
    expectedTitle: surface.title,
    selectors: surface.selectors,
    visibleSelectors: surface.visibleSelectors || [],
    hiddenSelectors: surface.hiddenSelectors || [],
    expectedLayerIds,
  });
}

function waitFor(url, timeoutMs) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      http.get(url, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      }).on("error", retry);
    };
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(attempt, 250);
    };
    attempt();
  });
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
