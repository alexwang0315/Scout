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
];

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const port = args.port || await freePort();
  const server = startServer(port, args.python);
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    await waitFor(`${baseUrl}/admin`, 20_000);
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
      const consoleErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error") consoleErrors.push(message.text());
      });
      page.on("pageerror", (error) => consoleErrors.push(error.message));

      for (const surface of surfaces) {
        const url = `${baseUrl}${surface.path}`;
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20_000 });
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
  return page.evaluate(async () => {
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
    const ok = hiddenWhileAway && visibleAfterReturn && sameSrc && loadCount === 0;
    if (!ok) {
      throw new Error(JSON.stringify({
        hiddenWhileAway,
        visibleAfterReturn,
        sameSrc,
        loadCount,
        initialSrc,
        currentSrc: frame.src,
      }));
    }
    return { ok, hiddenWhileAway, visibleAfterReturn, sameSrc, loadCount };
  });
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
