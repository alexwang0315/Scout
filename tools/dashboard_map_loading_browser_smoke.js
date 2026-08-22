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

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:9099";
  const projectId = process.argv[3] || "chilai_nanhua_day1_scoutAI";
  const screenshotPath = process.argv[4] || "/tmp/scout-dashboard-map-loading-smoke.png";
  const browser = await chromium.launch({ headless: true });
  const startedAt = Date.now();
  const compactRequests = [];
  const failedResponses = [];
  const consoleErrors = [];

  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("request", (request) => {
      if (
        request.method() === "GET"
        && request.url().includes(`/admin/pretrip/projects/${encodeURIComponent(projectId)}?compact=1`)
      ) {
        compactRequests.push({ url: request.url(), startedMs: Date.now() - startedAt });
      }
    });
    page.on("response", (response) => {
      if (response.status() >= 400) {
        failedResponses.push({ status: response.status(), url: response.url() });
      }
    });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));

    await page.goto(
      `${baseUrl}/admin/dashboard?projectId=${encodeURIComponent(projectId)}#map`,
      { waitUntil: "domcontentloaded", timeout: 30_000 },
    );
    await page.locator("#dashboardMapLoading").waitFor({ state: "visible", timeout: 10_000 });
    const loadingObservedMs = Date.now() - startedAt;

    await page.waitForFunction(
      (expectedProjectId) => {
        const frame = document.getElementById("pretripMapFrame");
        const snapshot = frame?.contentWindow?.scoutPretripProjectBridge?.getSnapshot?.();
        return snapshot?.projectId === expectedProjectId
          && Boolean(snapshot.view)
          && ["base_ready", "enhanced_ready", "degraded"].includes(snapshot.status);
      },
      projectId,
      { timeout: 60_000 },
    );
    const bridgeReadyMs = Date.now() - startedAt;

    await page.waitForFunction(
      () => {
        const frame = document.getElementById("pretripMapFrame");
        return Boolean(frame?.contentDocument?.querySelector("#map[viewBox] [data-layer-group]"));
      },
      null,
      { timeout: 45_000 },
    );
    const mapReadyMs = Date.now() - startedAt;

    await page.waitForFunction(
      () => Boolean(
        document.querySelector(
          '#dashboardMapEvidence [data-evidence-group-toggle="true"]',
        ),
      ),
      null,
      { timeout: 45_000 },
    );
    const evidenceReadyMs = Date.now() - startedAt;
    await page.locator("#dashboardMapLoading").waitFor({ state: "hidden", timeout: 5_000 });
    await page.screenshot({ path: screenshotPath, fullPage: true });

    const bridgeStatus = await page.evaluate(() => {
      const frame = document.getElementById("pretripMapFrame");
      const snapshot = frame?.contentWindow?.scoutPretripProjectBridge?.getSnapshot?.();
      return snapshot?.status || "missing";
    });
    const checks = {
      loadingStateWasVisible: loadingObservedMs >= 0,
      oneCompactProjectionRequest: compactRequests.length === 1,
      mapRendered: mapReadyMs > 0,
      evidenceGroupsAdoptedFromBridge: evidenceReadyMs > 0,
      loadingStateCleared: await page.locator("#dashboardMapLoading").isHidden(),
      noFailedResponses: failedResponses.length === 0,
      noConsoleErrors: consoleErrors.length === 0,
    };
    process.stdout.write(`${JSON.stringify({
      ok: Object.values(checks).every(Boolean),
      check: "dashboard_map_loading_browser_smoke",
      checks,
      timingMs: {
        loadingObserved: loadingObservedMs,
        bridgeReady: bridgeReadyMs,
        mapReady: mapReadyMs,
        evidenceReady: evidenceReadyMs,
      },
      compactRequests,
      bridgeStatus,
      failedResponses,
      consoleErrors,
      screenshotPath,
    }, null, 2)}\n`);
    if (!Object.values(checks).every(Boolean)) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
