#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const Module = require("module");

const repoRoot = path.resolve(__dirname, "..");
const bundledNodeModules = path.join(
  process.env.HOME || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
);
process.env.NODE_PATH = [process.env.NODE_PATH, bundledNodeModules]
  .filter(Boolean)
  .join(path.delimiter);
Module._initPaths();

const { chromium } = require("playwright");

const projectId = "chilai_nanhua_day1";
const importProjectId = "browser_import_scoutAI";

async function main() {
  const pretty = process.argv.includes("--pretty");
  const python = process.env.SCOUT_PYTHON || path.join(repoRoot, "venv/bin/python");
  const workspaceRoot = fs.mkdtempSync(
    path.join(os.tmpdir(), "scout-dashboard-workspace-smoke-"),
  );
  fs.cpSync(
    path.join(repoRoot, "tests/fixtures/pretrip/projects", projectId),
    path.join(workspaceRoot, projectId),
    { recursive: true },
  );

  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const server = spawn(
    python,
    [
      "-m",
      "uvicorn",
      "admin_api:create_dashboard_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--log-level",
      "warning",
    ],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: "1",
        SCOUT_AI_ASSISTANT_ENABLED: "0",
        SCOUT_PRETRIP_WORKSPACE_ROOT: workspaceRoot,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  try {
    await waitFor(`${baseUrl}/admin/dashboard`, 30_000);
    const report = await runSmoke({ baseUrl, workspaceRoot });
    process.stdout.write(`${JSON.stringify(report, null, pretty ? 2 : 0)}\n`);
    if (!report.ok) process.exitCode = 1;
  } finally {
    await stopServer(server);
    fs.rmSync(workspaceRoot, { recursive: true, force: true });
  }
}

async function runSmoke({ baseUrl, workspaceRoot }) {
  const browser = await chromium.launch({ headless: true });
  const connectedPreparationPosts = [];
  const consoleErrors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("console", (message) => {
      if (
        message.type() === "error"
        && !message.text().includes("Failed to load resource: the server responded with a status of 404")
      ) {
        consoleErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));
    await page.addInitScript((activeProjectId) => {
      localStorage.setItem("scout.dashboardProjectId", activeProjectId);
    }, projectId);
    await page.route(/\/admin\/pretrip\/projects\/[^/]+\/connected-preparation$/, async (route) => {
      if (route.request().method() === "POST") {
        connectedPreparationPosts.push(JSON.parse(route.request().postData() || "{}"));
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            schemaVersion: "dashboardConnectedPreparation.v1",
            projectId,
            status: "queued",
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schemaVersion: "dashboardConnectedPreparation.v1",
          projectId,
          status: "idle",
        }),
      });
    });

    await page.goto(
      `${baseUrl}/admin/dashboard?projectId=${projectId}#features-workspace`,
      { waitUntil: "domcontentloaded", timeout: 30_000 },
    );
    await page.waitForSelector("#workspaceRedirectProjectInput", { timeout: 30_000 });
    await page.waitForFunction(
      () => {
        const value = document.querySelector(
          '[data-workspace-structure="true"] > .panel:first-child .metric-row:first-child span:last-child',
        )?.textContent || "";
        return value && !value.includes("unavailable");
      },
      null,
      { timeout: 30_000 },
    );

    const initialPostCount = connectedPreparationPosts.length;
    const resolvedRoot = await page.locator(
      '[data-workspace-structure="true"] > .panel:first-child .metric-row:first-child span:last-child',
    ).textContent();

    await page.evaluate(() => {
      const select = document.getElementById("workspaceRedirectProjectInput");
      const option = document.createElement("option");
      option.value = "missing_workspace";
      option.textContent = "Missing workspace";
      select.append(option);
      select.value = option.value;
    });
    await page.locator("#workspaceSwitchProject").click();
    await page.waitForFunction(
      () => document.getElementById("workspaceOperationStatus")?.textContent.includes("switch cancelled"),
      null,
      { timeout: 10_000 },
    );
    const retainedProject = await page.evaluate(
      () => localStorage.getItem("scout.dashboardProjectId"),
    );

    await page.locator('[data-workspace-action="clone"]').click();
    await page.waitForFunction(
      () => document.getElementById("workspaceOperationStatus")?.textContent.includes("appended"),
      null,
      { timeout: 10_000 },
    );
    const requestLog = path.join(
      workspaceRoot,
      projectId,
      "reviews/workspace_operation_requests.jsonl",
    );
    const operationRecord = JSON.parse(
      fs.readFileSync(requestLog, "utf8").trim().split("\n").at(-1),
    );

    await page.locator("#workspaceRefreshExternalEvidence").click();
    await page.waitForFunction(
      () => document.getElementById("workspaceOperationStatus")?.textContent.includes("separate from workspace switching"),
      null,
      { timeout: 10_000 },
    );

    await page.evaluate(() => {
      window.location.hash = "#features-import-new-trip";
    });
    await page.waitForSelector("#importGoldenRouteGpxPath", { timeout: 10_000 });
    await page.locator("#importTripIdInput").fill("browser_import");
    await page.locator("#importGoldenRouteGpxPath").fill(
      path.join(repoRoot, "tests/fixtures/routes/normal_climb.gpx"),
    );
    await page.locator('[data-import-trip-action="validate"]').click();
    await waitForStatus(page, "GPX parsed and validated");
    await page.locator('[data-import-trip-action="preview"]').click();
    await waitForStatus(page, "Import preview ready");
    await page.locator('[data-import-trip-action="create"]').click();
    await waitForStatus(page, `Workspace ${importProjectId} created`, 30_000);

    const importedProjectPath = path.join(workspaceRoot, importProjectId, "project.json");
    const expectedResolvedRoot = fs.realpathSync(path.join(workspaceRoot, projectId));
    const checks = {
      catalogResolvedProjectRoot: resolvedRoot?.trim() === expectedResolvedRoot,
      noAutomaticConnectedPreparationPost: initialPostCount === 0,
      invalidSwitchPreservesWorkspace: retainedProject === projectId,
      operationRequestPersisted: operationRecord.operation === "clone",
      operationWasNotExecuted: operationRecord.execution_performed === false,
      explicitRefreshPostsOnce: connectedPreparationPosts.length === 1,
      explicitRefreshReason:
        connectedPreparationPosts[0]?.reason === "workspace-operator-refresh",
      importWorkspaceCreated: fs.existsSync(importedProjectPath),
      importOpenEnabled:
        !(await page.locator('[data-import-trip-action="open"]').isDisabled()),
      noConsoleErrors: consoleErrors.length === 0,
    };
    return {
      ok: Object.values(checks).every(Boolean),
      check: "dashboard_workspace_browser_smoke",
      checks,
      observed: {
        resolvedRoot: resolvedRoot?.trim(),
        expectedResolvedRoot,
      },
      consoleErrors,
    };
  } finally {
    await browser.close();
  }
}

async function waitForStatus(page, text, timeout = 15_000) {
  await page.waitForFunction(
    (expected) => document.getElementById("importTripStatus")?.textContent.includes(expected),
    text,
    { timeout },
  );
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function waitFor(url, timeoutMs) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(url, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
          return;
        }
        retry();
      });
      request.on("error", retry);
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error(`Timed out waiting for ${url}`));
        return;
      }
      setTimeout(attempt, 150);
    };
    attempt();
  });
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

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
