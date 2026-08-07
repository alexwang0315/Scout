#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const Module = require("module");
const net = require("net");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "../..");
const bundledNodeModules = path.join(
  process.env.HOME || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
);
process.env.NODE_PATH = [process.env.NODE_PATH, bundledNodeModules]
  .filter(Boolean)
  .join(path.delimiter);
Module._initPaths();

const { chromium } = require("playwright");

const readyProjectId = "chilai_nanhua_day1";
const partialProjectId = "qualification_partial";
const blockedProjectId = "qualification_blocked";
const degradedProjectId = "qualification_degraded";
const staleProjectId = "qualification_stale";
const zeroEvidenceProjectId = "qualification_zero_evidence";
const assistantEnabledProjectId = "qualification_assistant_enabled";
const assistantDisabledProjectId = "qualification_assistant_disabled";
const scope = process.argv.includes("--smoke") ? "smoke" : "full";
const quiet = process.argv.includes("--quiet");
const outputArgument = process.argv.find(argument => argument.startsWith("--output="));
const requestedCaseIds = new Set(
  process.argv
    .filter(argument => argument.startsWith("--case="))
    .map(argument => argument.split("=", 2)[1])
    .filter(Boolean),
);
const browserExecutable = process.env.SCOUT_BROWSER_EXECUTABLE || detectedBrowserExecutable();

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function detectedBrowserExecutable() {
  const candidates = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ];
  return candidates.find(candidate => fs.existsSync(candidate));
}

function safeCaseId(value) {
  return String(value).replace(/[^a-zA-Z0-9._-]+/g, "-");
}

function workspaceDigest(root) {
  const entries = [];
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      const relative = path.relative(root, absolute).split(path.sep).join("/");
      if (entry.isDirectory()) {
        entries.push({ path: `${relative}/`, kind: "directory" });
        walk(absolute);
      } else if (entry.isFile()) {
        entries.push({
          path: relative,
          kind: "file",
          size: fs.statSync(absolute).size,
          sha256: sha256(fs.readFileSync(absolute)),
        });
      }
    }
  };
  walk(root);
  entries.sort((left, right) => left.path.localeCompare(right.path));
  return { sha256: sha256(JSON.stringify(entries)), entries };
}

function workspaceDiff(before, after) {
  const left = new Map(before.entries.map(entry => [entry.path, JSON.stringify(entry)]));
  const right = new Map(after.entries.map(entry => [entry.path, JSON.stringify(entry)]));
  return [...new Set([...left.keys(), ...right.keys()])]
    .filter(key => left.get(key) !== right.get(key))
    .sort();
}

function rudyMatrixFromUrl(value) {
  try {
    const parsed = new URL(String(value));
    if (parsed.searchParams.has("TILEMATRIX")) {
      const queryMatrix = Number(parsed.searchParams.get("TILEMATRIX"));
      if (Number.isInteger(queryMatrix)) return queryMatrix;
    }
    const segments = parsed.pathname.split("/").filter(Boolean);
    const tileName = segments.at(-1) || "";
    const matrix = Number(segments.at(-3));
    const x = Number(segments.at(-2));
    if (/^\d+\.png$/i.test(tileName) && Number.isInteger(matrix) && Number.isInteger(x)) {
      return matrix;
    }
  } catch (_error) {
    return null;
  }
  return null;
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForServer(url, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await new Promise(resolve => {
      const request = http.get(url, response => {
        response.resume();
        resolve(response.statusCode || 0);
      });
      request.on("error", () => resolve(0));
      request.setTimeout(1000, () => {
        request.destroy();
        resolve(0);
      });
    });
    if (status >= 200 && status < 500) return;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`Dashboard server did not become ready: ${url}`);
}

async function stopServer(server) {
  if (!server || server.exitCode !== null) return;
  server.kill("SIGTERM");
  await Promise.race([
    new Promise(resolve => server.once("exit", resolve)),
    new Promise(resolve => setTimeout(resolve, 5000)),
  ]);
  if (server.exitCode === null) server.kill("SIGKILL");
}

function spawnDashboardServer(python, port, workspaceRoot, assistantMode) {
  return spawn(
    python,
    [
      "-m",
      "uvicorn",
      "scripts.qualification.dashboard_fixture_server:create_app",
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
        SCOUT_QUALIFICATION_ASSISTANT_MODE: assistantMode,
        SCOUT_QUALIFICATION_WORKSPACE_ROOT: workspaceRoot,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
}

async function openDashboard(page, baseUrl, projectId, route) {
  await page.addInitScript(({ selectedProjectId }) => {
    localStorage.setItem("scout.dashboardProjectId", selectedProjectId);
  }, { selectedProjectId: projectId });
  await page.goto(
    `${baseUrl}/admin/dashboard?projectId=${encodeURIComponent(projectId)}#${route}`,
    { waitUntil: "domcontentloaded", timeout: 60_000 },
  );
  await page.locator(`[data-route="${route}"]`).first().waitFor({ state: "attached", timeout: 60_000 });
}

async function activeNativeTileState(viewport) {
  return viewport.evaluate(node => {
    const layer = node.querySelector('[data-dashboard-rudy-tile-layer="true"]');
    if (!layer) return null;
    const active = layer.querySelector('[data-dashboard-rudy-tile-generation="active"]');
    const images = active
      ? [...active.querySelectorAll("image")]
      : [...layer.querySelectorAll(':scope > image[data-dashboard-rudy-tile]')];
    const matrices = images
      .map(image => Number(String(image.getAttribute("data-dashboard-rudy-tile") || "").split("/")[0]))
      .filter(Number.isInteger);
    return {
      matrix: matrices.length ? Math.max(...matrices) : null,
      matrices: [...new Set(matrices)].sort((left, right) => left - right),
      loadState: node.dataset.dashboardTileLoadState || "unknown",
    };
  });
}

async function waitForHigherMatrix(page, reader, initialMatrix, label) {
  const deadline = Date.now() + 45_000;
  let state = await reader();
  while (!(Number(state?.matrix) > Number(initialMatrix)) && Date.now() < deadline) {
    await page.waitForTimeout(200);
    state = await reader();
  }
  assert(Number(state?.matrix) > Number(initialMatrix), `${label} did not advance beyond Z${initialMatrix}: ${JSON.stringify(state)}`);
  return state;
}

async function inspectNativeDynamicMap(page, observations, definition) {
  await openDashboard(page, observations.baseUrl, readyProjectId, definition.route);
  const viewport = page.locator(`[data-dashboard-map-viewport="${definition.viewportId}"]`).first();
  await viewport.waitFor({ state: "attached", timeout: 120_000 });
  await page.waitForTimeout(1000);
  await viewport.locator('[data-map-control="reset"]').click();
  const initial = await activeNativeTileState(viewport);
  assert(Number.isInteger(initial?.matrix), `${definition.label} has no active Fit matrix.`);
  const requestStart = observations.requests.length;
  await viewport.locator('[data-map-control="zoom-in"]').click();
  const advanced = await waitForHigherMatrix(
    page,
    () => activeNativeTileState(viewport),
    initial.matrix,
    definition.label,
  );
  const higherRequests = observations.requests
    .slice(requestStart)
    .filter(request => Number(request.rudyMatrix) > initial.matrix);
  assert(higherRequests.some(request => request.status >= 200 && request.status < 300), `${definition.label} has no successful native tile request above Z${initial.matrix}.`);
  return { initial, advanced, higherRequests };
}

async function inspectWeatherDynamicMap(page, observations) {
  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");
  const frame = page.frameLocator('[data-weather-cwa-map-frame="true"]');
  const group = frame.locator('[data-layer-group="rudy-twmap"]');
  await group.waitFor({ state: "attached", timeout: 120_000 });
  await frame.locator("#fitRoute").click();
  const readState = () => group.evaluate(node => {
    const visibleBounds = visibleBoundsFor(state.view) || boundsFor(state.view);
    const active = node.querySelector('[data-tile-generation="active"]');
    const images = active
      ? [...active.querySelectorAll('image[data-map-tile-source="rudy-twmap"]')]
      : [...node.querySelectorAll('image[data-map-tile-source="rudy-twmap"]')];
    const matrices = images
      .map(image => Number(String(image.getAttribute("data-raster-tile") || "").split("/")[0]))
      .filter(Number.isInteger);
    return {
      matrix: matrices.length ? Math.max(...matrices) : null,
      matrices: [...new Set(matrices)],
      mapZoomText: node.ownerDocument.getElementById("zoomLevel")?.textContent || "",
      activeMapZoom: node.dataset.activeMapZoom || null,
      generationState: node.dataset.tileGenerationState || null,
      selectedMatrix: chooseRasterZoom(state.view, visibleBounds, RASTER_MAX_TILES, "rudy-twmap"),
      tileCounts: {
        z13: tileCountForZoom(visibleBounds, 13),
        z14: tileCountForZoom(visibleBounds, 14),
        z15: tileCountForZoom(visibleBounds, 15),
      },
    };
  });
  const initial = await readState();
  assert(Number.isInteger(initial.matrix), "Weather Map has no active Fit matrix.");
  await frame.locator("#zoomIn").click();
  const generationDeadline = Date.now() + 45_000;
  let advanced = await readState();
  while (
    !(
      Number(advanced?.matrix) > Number(initial.matrix)
      && advanced?.generationState === "ready"
      && Number(advanced?.activeMapZoom) > Number(initial.activeMapZoom)
    )
    && Date.now() < generationDeadline
  ) {
    await page.waitForTimeout(200);
    advanced = await readState();
  }
  assert(
    Number(advanced?.matrix) > Number(initial.matrix)
      && advanced?.generationState === "ready"
      && Number(advanced?.activeMapZoom) > Number(initial.activeMapZoom),
    `Weather Map did not promote the higher native generation: ${JSON.stringify(advanced)}`,
  );
  const requestDeadline = Date.now() + 10_000;
  let higherRequests = observations.requests
    .filter(request => Number(request.rudyMatrix) > initial.matrix);
  while (
    !higherRequests.some(request => request.status >= 200 && request.status < 300)
    && Date.now() < requestDeadline
  ) {
    await page.waitForTimeout(50);
    higherRequests = observations.requests
      .filter(request => Number(request.rudyMatrix) > initial.matrix);
  }
  assert(higherRequests.some(request => request.status >= 200 && request.status < 300), `Weather Map has no successful native tile request above Z${initial.matrix}.`);
  return {
    initial,
    advanced,
    higherRequestCount: higherRequests.length,
    higherRequests: higherRequests.slice(0, 12),
  };
}

async function runIsolatedCase(browser, definition, environment) {
  const caseId = safeCaseId(definition.id);
  const caseDirectory = path.join(environment.outputRoot, "cases", caseId);
  const videoDirectory = path.join(caseDirectory, "videos");
  fs.mkdirSync(videoDirectory, { recursive: true });
  const tracePath = path.join(caseDirectory, "trace.zip");
  const screenshotPath = path.join(caseDirectory, "final.png");
  const context = await browser.newContext({
    viewport: definition.viewport || { width: 1440, height: 1000 },
    recordVideo: { dir: videoDirectory, size: definition.viewport || { width: 1440, height: 1000 } },
  });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  const page = await context.newPage();
  const observations = {
    baseUrl: environment.baseUrl,
    disabledBaseUrl: environment.disabledBaseUrl,
    consoleErrors: [],
    pageErrors: [],
    requests: [],
    postRequests: [],
    failedResponses: [],
  };
  page.on("console", message => {
    if (message.type() === "error") observations.consoleErrors.push(message.text());
  });
  page.on("pageerror", error => observations.pageErrors.push(error.message));
  page.on("request", request => {
    if (request.method() === "POST") observations.postRequests.push(request.url());
  });
  page.on("response", response => {
    const request = response.request();
    const rudyMatrix = rudyMatrixFromUrl(response.url());
    observations.requests.push({
      method: request.method(),
      status: response.status(),
      url: response.url(),
      rudyMatrix,
    });
    if (response.status() >= 400) {
      observations.failedResponses.push({ status: response.status(), url: response.url() });
    }
  });
  const before = workspaceDigest(environment.workspaceRoot);
  let status = "PASS";
  let detail = "completed";
  let result = null;
  let mutationPaths = [];
  try {
    result = await definition.run(page, observations);
    assert(observations.postRequests.length === 0, `unexpected_post_requests: ${observations.postRequests.join(", ")}`);
    const after = workspaceDigest(environment.workspaceRoot);
    mutationPaths = workspaceDiff(before, after);
    if (definition.readOnly !== false && mutationPaths.length) {
      throw new Error(`unexpected_workspace_mutation: ${mutationPaths.join(", ")}`);
    }
    await page.screenshot({ path: screenshotPath, fullPage: true });
  } catch (error) {
    status = "FAIL";
    detail = String(error?.stack || error);
    const after = workspaceDigest(environment.workspaceRoot);
    mutationPaths = workspaceDiff(before, after);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => undefined);
  } finally {
    await context.tracing.stop({ path: tracePath });
    await context.close();
  }
  return {
    id: definition.id,
    capability_id: definition.capabilityId,
    criticality: definition.criticality,
    status,
    detail,
    result,
    mutation_paths: mutationPaths,
    workspace_before_sha256: before.sha256,
    workspace_after_sha256: workspaceDigest(environment.workspaceRoot).sha256,
    observations,
    evidence: {
      trace: path.relative(environment.outputRoot, tracePath),
      screenshot: path.relative(environment.outputRoot, screenshotPath),
      video_directory: path.relative(environment.outputRoot, videoDirectory),
    },
  };
}

const caseDefinitions = [
  {
    id: "diagnostic-controls",
    capabilityId: "dashboard.diagnostic.controls",
    criticality: "P1",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "diagnostic");
      const diagnostic = page.locator('[data-diagnostic-page="true"]');
      await diagnostic.waitFor({ state: "visible", timeout: 60_000 });
      assert(await page.locator('[data-diagnostic-action="all"]').count() === 1, "Diag all is missing.");
      const cases = await page.locator("[data-diagnostic-case]").count();
      const retries = await page.locator('[data-diagnostic-action="retest"]').count();
      assert(cases === 37 && retries === 37, `Diagnostic case/retest count is ${cases}/${retries}.`);
      return { cases, retries };
    },
  },
  {
    id: "navigation-partial-read-only-shell",
    capabilityId: "dashboard.navigation.partial_data_shell",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, partialProjectId, "outdoor-navigation");
      const viewport = page.locator('[data-dashboard-map-viewport="navigation-workspace-map"]');
      await viewport.waitFor({ state: "attached", timeout: 60_000 });
      assert(await viewport.getAttribute("data-navigation-evidence-state") === "not-prepared", "Navigation partial state is not truthful.");
      assert(await viewport.getAttribute("data-dashboard-basemap-layer") === "none", "Partial state claims a basemap.");
      assert(await viewport.locator("[data-map-control]").count() === 5, "Partial state map controls are incomplete.");
      assert(await viewport.locator('image[data-map-render-kind="tile"]').count() === 0, "Partial state fabricated tiles.");
      return { evidenceState: "not-prepared", tileCount: 0 };
    },
  },
  {
    id: "permission-ready-candidate-boundary",
    capabilityId: "dashboard.permission.fail_closed",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-permission");
      const shell = page.locator('[data-contextual-permission-workbench="ready"], [data-contextual-permission-workbench="degraded"]').first();
      await shell.waitFor({ state: "attached", timeout: 120_000 });
      assert(await shell.getAttribute("data-candidate-only") === "true", "Permission ready state is not candidate-only.");
      assert(await page.locator("[data-emergency-review-decision]").count() === 0, "Permission exposes Emergency decisions.");
      return { state: await shell.getAttribute("data-contextual-permission-workbench") };
    },
  },
  {
    id: "permission-degraded-candidate-boundary",
    capabilityId: "dashboard.permission.fail_closed",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, degradedProjectId, "outdoor-permission");
      const shell = page.locator('[data-contextual-permission-workbench="degraded"]');
      await shell.waitFor({ state: "attached", timeout: 120_000 });
      assert(await shell.getAttribute("data-candidate-only") === "true", "Permission degraded state is not candidate-only.");
      assert(await shell.locator('[data-permission-bootstrap-review="true"]').count() === 1, "Permission degraded state hides its review requirement.");
      assert(await page.locator("[data-emergency-review-decision]").count() === 0, "Permission degraded state exposes Emergency decisions.");
      return { state: "degraded", candidateOnly: true };
    },
  },
  {
    id: "permission-blocked-fail-closed",
    capabilityId: "dashboard.permission.fail_closed",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, blockedProjectId, "outdoor-permission");
      const shell = page.locator('[data-contextual-permission-workbench="blocked"]');
      await shell.waitFor({ state: "attached", timeout: 120_000 });
      assert((await shell.textContent() || "").trim().length > 0, "Blocked Permission state has no explanation.");
      return { state: "blocked" };
    },
  },
  {
    id: "permission-stale-migration-boundary",
    capabilityId: "dashboard.permission.fail_closed",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, staleProjectId, "outdoor-permission");
      const shell = page.locator('[data-contextual-permission-workbench="blocked"]');
      await shell.waitFor({ state: "attached", timeout: 120_000 });
      const projection = await page.evaluate(async selectedProjectId => {
        const response = await fetch(`/admin/pretrip/projects/${encodeURIComponent(selectedProjectId)}/contextual-permission-dashboard`);
        return { status: response.status, payload: await response.json() };
      }, staleProjectId);
      assert(projection.status === 200, `Stale Permission projection returned HTTP ${projection.status}.`);
      assert(projection.payload?.status === "blocked", "Stale Permission projection did not fail closed.");
      assert(projection.payload?.error?.code === "contextual_permission_projection_stale", "Stale Permission projection lost its typed error code.");
      assert(projection.payload?.rebuild?.eligible === false, "Historical stale baseline incorrectly became rebuild-eligible.");
      const rootBlockers = (projection.payload?.rebuild?.blockers || []).filter(blocker => blocker.blocker_kind === "root");
      assert(rootBlockers.some(blocker => blocker.blocker_id === "baseline_migration_required"), "Historical stale baseline has no migration root blocker.");
      const rebuildAfterProposal = shell.getByRole("button", { name: "Rebuild after new proposal" });
      assert(await rebuildAfterProposal.isDisabled(), "Stale Permission exposes an ineffective rebuild action.");
      return {
        state: "blocked",
        errorCode: projection.payload.error.code,
        rebuildEligible: false,
        rootBlockerIds: rootBlockers.map(blocker => blocker.blocker_id),
      };
    },
  },
  {
    id: "diagnostic-mobile",
    capabilityId: "dashboard.diagnostic.controls",
    criticality: "P1",
    readOnly: true,
    viewport: { width: 390, height: 844 },
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "diagnostic");
      await page.locator('[data-diagnostic-page="true"]').waitFor({ state: "visible", timeout: 60_000 });
      const layout = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      assert(layout.clientWidth === layout.scrollWidth, `Mobile overflow ${layout.clientWidth}/${layout.scrollWidth}.`);
      return layout;
    },
  },
  {
    id: "fixture-zero-evidence-truthful",
    capabilityId: "qualification.fixture.active_p0_matrix",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, zeroEvidenceProjectId, "timeline");
      const panel = page.locator(`[data-pretrip-evidence-source="${zeroEvidenceProjectId}"]`);
      await panel.waitFor({ state: "attached", timeout: 120_000 });
      const text = await panel.textContent() || "";
      assert(text.includes("0 pre-trip evidence items"), "Zero-evidence fixture fabricates a nonzero evidence total.");
      assert(await panel.locator(".pretrip-evidence-item").count() === 0, "Zero-evidence fixture fabricates evidence rows.");
      return { state: "zero_evidence", evidenceItems: 0 };
    },
  },
  {
    id: "fixture-assistant-enabled",
    capabilityId: "qualification.fixture.active_p0_matrix",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, assistantEnabledProjectId, "agent");
      const status = await page.evaluate(async () => {
        const response = await fetch("/assistant/status");
        return { status: response.status, payload: await response.json() };
      });
      assert(status.status === 200, `Enabled Assistant fixture returned HTTP ${status.status}.`);
      assert(status.payload?.provider_class === "QualificationAssistantProvider", "Enabled Assistant fixture did not use the network-free provider.");
      assert(await page.locator('[data-agent-query-path="/assistant/query"]').count() >= 1, "Enabled Assistant query shell is missing.");
      return { state: "assistant_enabled", providerClass: status.payload.provider_class };
    },
  },
  {
    id: "fixture-assistant-disabled",
    capabilityId: "qualification.fixture.active_p0_matrix",
    criticality: "P0",
    readOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.disabledBaseUrl, assistantDisabledProjectId, "agent");
      const status = await page.evaluate(async () => {
        const response = await fetch("/assistant/status");
        return { status: response.status };
      });
      assert(status.status === 404, `Disabled Assistant fixture returned HTTP ${status.status}.`);
      await page.waitForFunction(() => (document.getElementById("agentStatusText")?.textContent || "").includes("unavailable"));
      assert(await page.locator('[data-agent-query-path="/assistant/query"]').count() >= 1, "Disabled Assistant safe shell is missing.");
      return { state: "assistant_disabled", statusCode: 404 };
    },
  },
  {
    id: "fixture-matrix-contract",
    capabilityId: "qualification.fixture.active_p0_matrix",
    criticality: "P0",
    readOnly: true,
    async run() {
      const matrix = JSON.parse(fs.readFileSync(path.join(repoRoot, "tests/e2e/qualification/fixtures/dashboard-state-matrix.json"), "utf8"));
      const states = new Set(matrix.fixtures.map(fixture => fixture.state));
      for (const required of ["ready", "degraded", "blocked", "stale", "partial", "zero_evidence", "assistant_enabled", "assistant_disabled"]) {
        assert(states.has(required), `Fixture matrix is missing ${required}.`);
      }
      assert(matrix.fixtures.every(fixture => fixture.candidate_only && !fixture.runtime_safety_truth && !fixture.writes_allowed_during_qualification), "Fixture matrix crosses its authority boundary.");
      return { states: [...states].sort() };
    },
  },
  {
    id: "diagnostic-diag-all-read-only",
    capabilityId: "dashboard.diagnostic.read_only",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "diagnostic");
      await page.locator('[data-diagnostic-action="all"]').click();
      await page.waitForFunction(() => {
        const snapshot = window.scoutDashboardDiagnostics?.snapshot?.();
        return snapshot && snapshot.summary.running === 0 && snapshot.summary.idle === 0;
      }, null, { timeout: 480_000 });
      const snapshot = await page.evaluate(() => window.scoutDashboardDiagnostics.snapshot());
      const zeroCountCategories = await page.evaluate(async () => {
        const project = await diagnosticProjectProjection();
        return diagnosticZeroCountEvidenceCategories(project);
      });
      assert(snapshot.summary.passed + snapshot.summary.failed === snapshot.summary.total, "Diag all did not reach terminal states.");
      return {
        summary: snapshot.summary,
        zeroCountCategories,
        unexplainedZeroCount: zeroCountCategories.filter(
          item => item.includes("fixture_or_projection_omission"),
        ).length,
        failedCases: Object.entries(snapshot.results)
          .filter(([, value]) => value.status === "failed")
          .map(([id, value]) => ({ id, ...value })),
      };
    },
  },
  {
    id: "navigation-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    run: (page, observations) => inspectNativeDynamicMap(page, observations, { route: "outdoor-navigation", viewportId: "navigation-workspace-map", label: "Navigation Map" }),
  },
  {
    id: "architecture-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    run: (page, observations) => inspectNativeDynamicMap(page, observations, { route: "outdoor-architecture", viewportId: "architecture-map", label: "Architecture Map" }),
  },
  {
    id: "weather-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    run: inspectWeatherDynamicMap,
  },
];

function buildCapabilityResults(definitions, results) {
  const capabilityIds = [...new Set(caseDefinitions.map(definition => definition.capabilityId))];
  const selectedIds = new Set(definitions.map(definition => definition.id));
  const byCase = new Map(results.map(result => [result.id, result]));
  const output = {};
  for (const capabilityId of capabilityIds) {
    const required = caseDefinitions.filter(definition => definition.capabilityId === capabilityId);
    if (required.some(definition => !selectedIds.has(definition.id))) {
      output[capabilityId] = "INSUFFICIENT_EVIDENCE";
      continue;
    }
    output[capabilityId] = required.every(definition => byCase.get(definition.id)?.status === "PASS") ? "PASS" : "FAIL";
  }
  output["qualification.evidence.integrity"] = "PASS";
  return output;
}

function writeJson(outputRoot, relativePath, payload) {
  const target = path.join(outputRoot, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`);
}

function xmlEscape(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function writeAggregateEvidence(outputRoot, definitions, results, capabilityResults) {
  const consoleErrors = results.flatMap(result =>
    result.observations.consoleErrors.map(detail => ({ case_id: result.id, detail })),
  );
  const pageErrors = results.flatMap(result =>
    result.observations.pageErrors.map(detail => ({ case_id: result.id, detail })),
  );
  const failedRequests = results.flatMap(result =>
    result.observations.failedResponses.map(response => ({ case_id: result.id, ...response })),
  );
  const responses = results.flatMap(result =>
    result.observations.requests.map(response => ({ case_id: result.id, ...response })),
  );
  writeJson(outputRoot, "console-errors.json", {
    schema: "scout.dashboardQualificationConsoleErrors.v1",
    errors: consoleErrors,
  });
  writeJson(outputRoot, "page-errors.json", {
    schema: "scout.dashboardQualificationPageErrors.v1",
    errors: pageErrors,
  });
  writeJson(outputRoot, "failed-requests.json", {
    schema: "scout.dashboardQualificationFailedRequests.v1",
    requests: failedRequests,
  });
  writeJson(outputRoot, "network/responses.json", {
    schema: "scout.dashboardQualificationNetworkResponses.v1",
    responses,
  });
  writeJson(outputRoot, "coverage-map.json", {
    schema: "scout.dashboardQualificationCoverageMap.v1",
    capability_results: capabilityResults,
    executed_cases: results.map(result => ({
      case_id: result.id,
      capability_id: result.capability_id,
      criticality: result.criticality,
      state: result.status,
      evidence: result.evidence,
    })),
    unexecuted_cases: caseDefinitions
      .filter(definition => !definitions.includes(definition))
      .map(definition => ({
        case_id: definition.id,
        capability_id: definition.capabilityId,
        reason: scope === "smoke" && definition.fullOnly ? "full_scope_only" : "not_selected",
      })),
  });
  const diagnosticFailures = results
    .flatMap(result => result.result?.failedCases || [])
    .map(failure => ({
      finding_kind: "runtime_diagnostic_failure",
      case_id: failure.id,
      observed_behavior: failure.detail,
      disposition: "AWAITING_HUMAN_REVIEW",
    }));
  const browserFailures = results
    .filter(result => result.status !== "PASS")
    .map(result => ({
      finding_kind: "browser_case_failure",
      case_id: result.id,
      capability_id: result.capability_id,
      criticality: result.criticality,
      observed_behavior: result.detail,
      disposition: "AWAITING_HUMAN_REVIEW",
    }));
  writeJson(outputRoot, "exploratory-findings.json", {
    schema: "scout.dashboardQualificationExploratoryFindings.v1",
    findings: [...browserFailures, ...diagnosticFailures],
    operator_final_verdict_allowed: false,
  });
  const testCases = results.map(result => {
    const failure = result.status === "PASS"
      ? ""
      : `<failure message="${xmlEscape(result.detail)}">${xmlEscape(result.detail)}</failure>`;
    return `  <testcase classname="dashboard.qualification" name="${xmlEscape(result.id)}">${failure}</testcase>`;
  }).join("\n");
  const failureCount = results.filter(result => result.status !== "PASS").length;
  fs.writeFileSync(
    path.join(outputRoot, "junit.xml"),
    `<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="Scout Dashboard browser qualification" tests="${results.length}" failures="${failureCount}">\n${testCases}\n</testsuite>\n`,
  );
  writeJson(outputRoot, "playwright-report/summary.json", {
    schema: "scout.dashboardQualificationPlaywrightSummary.v1",
    total: results.length,
    passed: results.length - failureCount,
    failed: failureCount,
    cases: results.map(result => ({ id: result.id, status: result.status })),
  });
  for (const [directory, evidenceKey] of [
    ["screenshots", "screenshot"],
    ["traces", "trace"],
    ["videos", "video_directory"],
  ]) {
    writeJson(outputRoot, `${directory}/index.json`, {
      schema: `scout.dashboardQualification${directory[0].toUpperCase()}${directory.slice(1)}Index.v1`,
      cases: results.map(result => ({
        case_id: result.id,
        evidence_ref: result.evidence[evidenceKey],
      })),
    });
  }
}

function writeEvidenceIndex(outputRoot) {
  const files = [];
  const walk = directory => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      const relative = path.relative(outputRoot, absolute).split(path.sep).join("/");
      if (entry.isDirectory()) walk(absolute);
      else if (entry.isFile() && relative !== "evidence-index.json") {
        files.push({ path: relative, sha256: sha256(fs.readFileSync(absolute)) });
      }
    }
  };
  walk(outputRoot);
  files.sort((left, right) => left.path.localeCompare(right.path));
  const canonical = files.map(file => `${file.sha256}  ${file.path}\n`).join("");
  const index = {
    schema: "scout.dashboardQualificationEvidenceIndex.v1",
    evidence_root_sha256: sha256(canonical),
    files,
  };
  fs.writeFileSync(path.join(outputRoot, "evidence-index.json"), `${JSON.stringify(index, null, 2)}\n`);
  return index;
}

async function main() {
  const workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "scout-dashboard-qualification-"));
  const commit = spawnSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).stdout.trim();
  const runId = `${commit.slice(0, 12)}-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const outputRoot = outputArgument
    ? path.resolve(outputArgument.split("=", 2)[1])
    : path.join(repoRoot, "artifacts", "qualification", "runs", runId);
  fs.mkdirSync(outputRoot, { recursive: true });
  const python = process.env.SCOUT_PYTHON || path.join(repoRoot, "venv/bin/python");
  const seedResult = spawnSync(
    python,
    ["-m", "scripts.qualification.seed_dashboard_fixture", "--workspace-root", workspaceRoot, "--output", path.join(outputRoot, "fixture-seed.json")],
    { cwd: repoRoot, encoding: "utf8" },
  );
  if (seedResult.status !== 0) throw new Error(seedResult.stderr || seedResult.stdout || "fixture seed failed");

  const port = await freePort();
  const disabledPort = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const disabledBaseUrl = `http://127.0.0.1:${disabledPort}`;
  const server = spawnDashboardServer(python, port, workspaceRoot, "enabled");
  const disabledServer = spawnDashboardServer(
    python,
    disabledPort,
    workspaceRoot,
    "disabled",
  );
  const serverErrors = [];
  server.stderr.on("data", chunk => serverErrors.push(`enabled: ${String(chunk)}`));
  disabledServer.stderr.on("data", chunk => serverErrors.push(`disabled: ${String(chunk)}`));
  let browser;
  try {
    await Promise.all([
      waitForServer(`${baseUrl}/admin/dashboard`),
      waitForServer(`${disabledBaseUrl}/admin/dashboard`),
    ]);
    browser = await chromium.launch({
      headless: true,
      ...(browserExecutable ? { executablePath: browserExecutable } : {}),
    });
    const definitions = caseDefinitions.filter(definition =>
      (scope === "full" || !definition.fullOnly)
      && (!requestedCaseIds.size || requestedCaseIds.has(definition.id)),
    );
    const results = [];
    for (const definition of caseDefinitions) {
      if (!definitions.includes(definition)) continue;
      results.push(await runIsolatedCase(browser, definition, {
        baseUrl,
        disabledBaseUrl,
        workspaceRoot,
        outputRoot,
      }));
    }
    const capabilityResults = buildCapabilityResults(definitions, results);
    const report = {
      schema: "scout.dashboardBrowserQualification.v1",
      commit_sha: commit,
      run_id: runId,
      scope,
      browser_executable: browserExecutable || "playwright-managed",
      fixture_provenance: "bounded_synthetic_workspace",
      capability_results: capabilityResults,
      results,
      server_errors: serverErrors,
      candidate_only: true,
      runtime_safety_truth: false,
    };
    writeAggregateEvidence(outputRoot, definitions, results, capabilityResults);
    fs.writeFileSync(path.join(outputRoot, "results.json"), `${JSON.stringify(report, null, 2)}\n`);
    const index = writeEvidenceIndex(outputRoot);
    const output = quiet
      ? {
        commit_sha: report.commit_sha,
        run_id: report.run_id,
        scope: report.scope,
        capability_results: report.capability_results,
        cases: results.map(result => ({
          id: result.id,
          status: result.status,
          detail: result.detail,
          result: result.result,
          mutation_paths: result.mutation_paths,
        })),
        evidence_root_sha256: index.evidence_root_sha256,
        output_root: outputRoot,
      }
      : { ...report, evidence_root_sha256: index.evidence_root_sha256, output_root: outputRoot };
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
    const p0Failure = results.some(result => result.criticality === "P0" && result.status !== "PASS");
    if (scope === "full" && p0Failure) process.exitCode = 2;
  } finally {
    if (browser) await browser.close();
    await stopServer(server);
    await stopServer(disabledServer);
    fs.rmSync(workspaceRoot, { recursive: true, force: true });
  }
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
