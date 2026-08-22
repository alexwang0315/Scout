#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

async function gotoWhenReady(page, url) {
  let lastError;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 5_000 });
      return;
    } catch (error) {
      lastError = error;
      if (!String(error).includes("ERR_CONNECTION_REFUSED")) throw error;
      await page.waitForTimeout(250);
    }
  }
  throw lastError;
}

async function main() {
  const baseUrl = process.argv[2] || "http://127.0.0.1:9099";
  const projectId = process.argv[3] || "chilai_nanhua_day1_scoutAI";
  const outputDir = path.resolve(process.argv[4] || "/tmp/scout-qgis-browser-qualification");
  fs.mkdirSync(outputDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const consoleErrors = [];
  const failedResponses = [];
  const failedRequests = [];
  const startupConnectionRefusals = [];
  const httpOrigins = new Set();
  const timings = {};
  const startedAt = Date.now();
  let workflowRunId = "";
  let readinessComplete = false;

  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400) {
        failedResponses.push({ status: response.status(), url: response.url() });
      }
      if (/^https?:/.test(response.url())) {
        httpOrigins.add(new URL(response.url()).origin);
      }
    });
    page.on("requestfailed", (request) => {
      const errorText = request.failure()?.errorText || "unknown";
      if (!readinessComplete && errorText.includes("ERR_CONNECTION_REFUSED")) {
        startupConnectionRefusals.push({ errorText, url: request.url() });
        return;
      }
      if (!errorText.includes("ERR_ABORTED")) {
        failedRequests.push({ errorText, url: request.url() });
      }
    });

    const dashboardUrl = `${baseUrl}/admin/dashboard?projectId=${encodeURIComponent(projectId)}#outdoor-navigation`;
    await gotoWhenReady(page, dashboardUrl);
    readinessComplete = true;
    await page.evaluate((key) => localStorage.removeItem(key), `scout.qgisSpatialWorkflowRunId.${projectId}`);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(
      () => document.querySelector("[data-qgis-spatial-panel]")?.dataset.qgisAvailability === "available",
      null,
      { timeout: 45_000 },
    );
    timings.dashboardReadyMs = Date.now() - startedAt;

    await page.locator("[data-qgis-terrain-preview]").click();
    await page.waitForFunction(
      () => {
        const panel = document.querySelector("[data-qgis-spatial-panel]")?.innerText || "";
        const map = document.querySelector('[data-scout-maplibre-evidence="qgis"]');
        const image = document.querySelector("[data-qgis-visual-review] img");
        return panel.includes("WORKFLOW · COMPLETED")
          && panel.includes("review pending")
          && map?.dataset.navigationMaplibreStatus === "ready"
          && image?.complete
          && image?.naturalWidth > 0;
      },
      null,
      { timeout: 45_000 },
    );
    timings.fixtureReadyMs = Date.now() - startedAt;
    workflowRunId = await page.evaluate(
      (key) => localStorage.getItem(key) || "",
      `scout.qgisSpatialWorkflowRunId.${projectId}`,
    );
    const runPath = `/admin/pretrip/projects/${encodeURIComponent(projectId)}/spatial/qgis/workflows/${encodeURIComponent(workflowRunId)}`;
    const pendingRun = await page.evaluate(async (url) => {
      const response = await fetch(url, { cache: "no-store" });
      return response.json();
    }, runPath);
    await page.locator("[data-qgis-spatial-panel]").screenshot({
      path: path.join(outputDir, "01-fixture-review-pending.png"),
    });

    await page.locator('[data-qgis-layer-toggle="slope"]').click();
    await page.waitForFunction(
      () => document.querySelector('[data-qgis-layer-toggle="slope"]')?.getAttribute("aria-pressed") === "false",
    );
    const slopeToggleOff = await page.locator('[data-qgis-layer-toggle="slope"]').getAttribute("aria-pressed");
    await page.locator('[data-qgis-layer-toggle="slope"]').click();
    await page.waitForFunction(
      () => document.querySelector('[data-qgis-layer-toggle="slope"]')?.getAttribute("aria-pressed") === "true",
    );
    await page.locator("[data-qgis-maplibre-fit]").click();

    await page.locator("[data-qgis-review-evidence]").click();
    await page.waitForFunction(
      () => {
        const panel = document.querySelector("[data-qgis-spatial-panel]")?.innerText || "";
        const metadata = document.querySelector("[data-qgis-artifact-metadata]")?.innerText || "";
        return panel.includes("review completed")
          && panel.includes("candidate authority unchanged")
          && metadata.includes("REVIEWED_EVIDENCE");
      },
      null,
      { timeout: 20_000 },
    );
    timings.reviewedMs = Date.now() - startedAt;
    const reviewedRun = await page.evaluate(async (url) => {
      const response = await fetch(url, { cache: "no-store" });
      return response.json();
    }, runPath);
    await page.locator('[data-scout-maplibre-evidence="qgis"]').screenshot({
      path: path.join(outputDir, "02-maplibre-candidate-reviewed.png"),
    });
    await page.locator("[data-qgis-visual-review]").screenshot({
      path: path.join(outputDir, "03-qgis-visual-review.png"),
    });
    await page.locator("[data-qgis-artifact-metadata]").screenshot({
      path: path.join(outputDir, "04-artifact-metadata-reviewed.png"),
    });

    await page.reload({ waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.waitForFunction(
      (expectedRunId) => {
        const stored = localStorage.getItem(`scout.qgisSpatialWorkflowRunId.${new URL(location.href).searchParams.get("projectId")}`);
        const panel = document.querySelector("[data-qgis-spatial-panel]")?.innerText || "";
        const map = document.querySelector('[data-scout-maplibre-evidence="qgis"]');
        return stored === expectedRunId
          && panel.includes("review completed")
          && map?.dataset.navigationMaplibreStatus === "ready";
      },
      workflowRunId,
      { timeout: 45_000 },
    );
    timings.reloadRestoredMs = Date.now() - startedAt;
    const desktop = await page.evaluate(() => ({
      overflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      mapStatus: document.querySelector('[data-scout-maplibre-evidence="qgis"]')?.dataset.navigationMaplibreStatus || "missing",
      renderNaturalWidth: document.querySelector("[data-qgis-visual-review] img")?.naturalWidth || 0,
    }));

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    const mobile = await page.evaluate(() => {
      const panel = document.querySelector("[data-qgis-spatial-panel]");
      const map = document.querySelector('[data-scout-maplibre-evidence="qgis"]');
      const image = document.querySelector("[data-qgis-visual-review] img");
      return {
        overflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        panelWidth: Math.round(panel?.getBoundingClientRect().width || 0),
        mapWidth: Math.round(map?.getBoundingClientRect().width || 0),
        mapStatus: map?.dataset.navigationMaplibreStatus || "missing",
        renderWidth: Math.round(image?.getBoundingClientRect().width || 0),
      };
    });
    await page.locator("[data-qgis-spatial-panel]").screenshot({
      path: path.join(outputDir, "05-mobile-gis-analysis.png"),
    });

    const authorityPreserved = (run) => run.candidate_only === true
      && run.runtime_safety_truth === false
      && run.operational === false
      && [...(run.artifacts || []), ...(run.render_artifacts || [])].every(
        (artifact) => artifact.candidate_only === true
          && artifact.runtime_safety_truth === false
          && artifact.operational === false,
      );
    const expectedOrigin = new URL(baseUrl).origin;
    const externalOrigins = [...httpOrigins].filter((origin) => origin !== expectedOrigin);
    const checks = {
      fixtureCompleted: pendingRun.state === "completed" && pendingRun.processing_status === "completed",
      processingAndReviewSeparated: pendingRun.render_status === "completed" && pendingRun.human_review_status === "pending",
      fixtureExplicit: [...(pendingRun.artifacts || []), ...(pendingRun.render_artifacts || [])].every(
        (artifact) => artifact.fixture === true && artifact.synthetic === true,
      ),
      pendingAuthorityPreserved: authorityPreserved(pendingRun),
      mapLibreReady: desktop.mapStatus === "ready" && desktop.renderNaturalWidth > 0,
      layerToggleWorks: slopeToggleOff === "false",
      reviewRecorded: reviewedRun.human_review_status === "completed"
        && reviewedRun.visual_review_status === "completed"
        && [...(reviewedRun.artifacts || []), ...(reviewedRun.render_artifacts || [])].every(
          (artifact) => artifact.status === "reviewed_evidence",
        ),
      reviewedAuthorityPreserved: authorityPreserved(reviewedRun),
      reloadRestoredSameRun: reviewedRun.workflow_run_id === workflowRunId,
      desktopNoHorizontalOverflow: desktop.overflowPx === 0,
      mobileNoHorizontalOverflow: mobile.overflowPx === 0,
      mobileMapReady: mobile.mapStatus === "ready" && mobile.mapWidth > 0 && mobile.renderWidth > 0,
      noBrowserToMcpOrWorker: externalOrigins.length === 0,
      noFailedResponses: failedResponses.length === 0,
      noUnexpectedFailedRequests: failedRequests.length === 0,
      noConsoleErrors: consoleErrors.length === 0,
    };
    const report = {
      schema_version: "scout_qgis_dashboard_browser_qualification.v0_1",
      status: Object.values(checks).every(Boolean) ? "passed" : "failed",
      fixture: true,
      synthetic: true,
      non_runtime: true,
      baseUrl,
      projectId,
      workflowRunId,
      checks,
      timings,
      desktop,
      mobile,
      externalOrigins,
      failedResponses,
      failedRequests,
      startupConnectionRefusals,
      consoleErrors,
      screenshotPaths: [
        "01-fixture-review-pending.png",
        "02-maplibre-candidate-reviewed.png",
        "03-qgis-visual-review.png",
        "04-artifact-metadata-reviewed.png",
        "05-mobile-gis-analysis.png",
      ].map((name) => path.join(outputDir, name)),
      authority: {
        candidate_only: true,
        runtime_safety_truth: false,
        operational: false,
      },
    };
    const reportPath = path.join(outputDir, "qualification-report.json");
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`${JSON.stringify({ ...report, reportPath }, null, 2)}\n`);
    if (report.status !== "passed") process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
