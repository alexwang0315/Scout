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
const expectedDiagnosticCount = 29;

function assert(condition, message) {
  if (!condition) throw new Error(message);
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
