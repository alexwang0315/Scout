#!/usr/bin/env node
"use strict";

const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { spawn, spawnSync } = require("child_process");
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

const surfacePaths = {
  admin: "/admin",
  debug: "/admin/debug",
  pretrip: "/admin/pretrip?tileSource=local",
};

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const python = args.python || process.env.SCOUT_PYTHON || path.join(repoRoot, "venv/bin/python");
  const prompts = loadPromptCorpus(python);
  const baseUrl = args.baseUrl || await startLocalServer(args, python);

  let server = null;
  if (!args.baseUrl) {
    server = baseUrl.server;
  }
  const targetBaseUrl = typeof baseUrl === "string" ? baseUrl : baseUrl.url;

  try {
    await waitFor(`${targetBaseUrl}/admin`, 20_000);
    const report = await runBrowserSmoke({
      baseUrl: targetBaseUrl,
      prompts,
      screenshotsDir: args.screenshotsDir,
      timeoutMs: args.timeoutMs,
    });
    process.stdout.write(`${JSON.stringify(report, null, args.pretty ? 2 : 0)}\n`);
    if (!report.ok) process.exitCode = 1;
  } finally {
    if (server) await stopServer(server);
  }
}

function parseArgs(argv) {
  const args = {
    baseUrl: "",
    port: 0,
    pretty: false,
    python: "",
    screenshotsDir: "",
    timeoutMs: 20_000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--base-url") args.baseUrl = argv[++index];
    else if (arg === "--port") args.port = Number(argv[++index]);
    else if (arg === "--python") args.python = argv[++index];
    else if (arg === "--screenshots-dir") args.screenshotsDir = argv[++index];
    else if (arg === "--timeout-ms") args.timeoutMs = Number(argv[++index]);
    else if (arg === "--pretty") args.pretty = true;
    else if (arg === "--help") {
      process.stdout.write([
        "Usage: node tools/scout_ui_operation_browser_smoke.js [--base-url URL] [--port PORT] [--python PYTHON] [--screenshots-dir DIR] [--pretty]",
        "",
        "Starts a fixture-backed Scout admin server unless --base-url is provided.",
        "Runs the 20 Scout UI operation prompts in Chromium against admin/debug/pretrip.",
        "",
      ].join("\n"));
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function loadPromptCorpus(python) {
  const script = [
    "import json",
    "from scout.ui_action_plan import list_scout_ui_action_prompts",
    "print(json.dumps(list_scout_ui_action_prompts(), ensure_ascii=False))",
  ].join("\n");
  const completed = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONPATH: [path.join(repoRoot, "src"), repoRoot, process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
    encoding: "utf8",
  });
  if (completed.status !== 0) {
    throw new Error(`Failed to load UI prompt corpus: ${completed.stderr || completed.stdout}`);
  }
  const corpus = JSON.parse(completed.stdout);
  if (!Array.isArray(corpus.prompts) || corpus.prompt_count !== 20) {
    throw new Error(`Unexpected UI prompt corpus shape: ${completed.stdout}`);
  }
  return corpus.prompts;
}

async function startLocalServer(args, python) {
  const port = args.port || await freePort();
  const serverPath = path.join(repoRoot, "tools/admin_ui_smoke_app.py");
  const child = spawn(python, [serverPath, "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });
  child.on("exit", (code, signal) => {
    if (code && !child.killed) {
      process.stderr.write(`Scout UI operation smoke server exited with ${code || signal}\n${stderr}\n`);
    }
  });
  return { server: child, url: `http://127.0.0.1:${port}` };
}

async function runBrowserSmoke({ baseUrl, prompts, screenshotsDir, timeoutMs }) {
  if (screenshotsDir) fs.mkdirSync(screenshotsDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const results = [];
  const consoleErrors = [];
  try {
    for (const surface of ["admin", "debug", "pretrip"]) {
      const surfacePrompts = prompts.filter((prompt) => prompt.surface === surface);
      for (const prompt of surfacePrompts) {
        const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
        page.on("console", (message) => {
          if (message.type() === "error") consoleErrors.push(`${surface}:${prompt.id}:${message.text()}`);
        });
        page.on("pageerror", (error) => consoleErrors.push(`${surface}:${prompt.id}:${error.message}`));
        await page.goto(`${baseUrl}${surfacePaths[surface]}`, {
          waitUntil: "domcontentloaded",
          timeout: timeoutMs,
        });
        await waitForSurfaceReady(page, surface, timeoutMs);
        await preparePromptContext(page, prompt, timeoutMs);
        const result = await runPrompt(page, prompt, timeoutMs);
        results.push(result);
        if (screenshotsDir) {
          await page.screenshot({
            path: path.join(screenshotsDir, `ui-operation-${prompt.id}-${surface}.png`),
            fullPage: false,
          });
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }

  const failures = results
    .filter((result) => !result.ok)
    .map((result) => ({
      id: result.id,
      surface: result.surface,
      expected_action_kind: result.expected_action_kind,
      plan_status: result.plan_status,
      application_status: result.application_status,
      result_statuses: result.result_statuses,
      reason: result.reason,
    }));
  return {
    ok: failures.length === 0 && consoleErrors.length === 0,
    check: "scout_ui_operation_browser_smoke",
    base_url: baseUrl,
    promptCount: prompts.length,
    resultCount: results.length,
    failures,
    consoleErrors,
    results,
  };
}

async function waitForSurfaceReady(page, surface, timeoutMs) {
  await page.waitForFunction(
    () => Boolean(window.ScoutAssistantUI?.applyUiActionPlan),
    null,
    { timeout: timeoutMs },
  );
  const selectorBySurface = {
    admin: "#map",
    debug: "#runtimeMap",
    pretrip: "#map",
  };
  await page.waitForSelector(selectorBySurface[surface], { state: "attached", timeout: timeoutMs });
  const readyChecks = {
    admin: [
      { selector: "#narrativePanel", missingText: "Loading" },
      { selector: "#evidenceTree", missingText: "Loading" },
    ],
    debug: [
      { selector: ".timeline-node.is-selected", missingText: "Loading" },
    ],
    pretrip: [
      { selector: "#readinessStripStatus", missingText: "Loading" },
      { selector: "#routeMeta", missingText: "Loading" },
      { selector: "#detailTitle", missingText: "No selection" },
    ],
  };
  for (const check of readyChecks[surface] || []) {
    await page.waitForFunction(
      ({ selector, missingText }) => {
        const node = document.querySelector(selector);
        return Boolean(node) && !node.textContent.includes(missingText);
      },
      check,
      { timeout: timeoutMs },
    );
  }
  await page.waitForTimeout(1000);
}

async function preparePromptContext(page, prompt, timeoutMs) {
  const expectsSelectedAdminEvidence = (
    prompt.surface === "admin"
    && prompt.expected_action_kind === "focus_map_target"
    && prompt.expected_target_kind === "selected_evidence"
  );
  const expectsDebugTimelineEvent = (
    prompt.surface === "debug"
    && prompt.expected_action_kind === "focus_map_target"
    && prompt.expected_target_kind === "timeline_event"
  );
  if (expectsDebugTimelineEvent) {
    await prepareDebugTimelineEventContext(page, timeoutMs);
    return;
  }
  if (!expectsSelectedAdminEvidence) return;

  const selector = "#evidenceTree button[data-tree-source-id]";
  await page.waitForSelector(selector, { state: "attached", timeout: timeoutMs });
  await page.evaluate((selector) => {
    document.querySelectorAll("#evidenceTree details").forEach((details) => {
      details.open = true;
    });
    document.querySelector(selector)?.click();
  }, selector);
  await page.waitForFunction(
    () => {
      const title = document.getElementById("detailTitle")?.textContent || "";
      const source = document.getElementById("detailSource")?.textContent || "";
      return Boolean(title.trim()) && !source.includes("no source path");
    },
    null,
    { timeout: timeoutMs },
  ).catch(() => {});
}

async function prepareDebugTimelineEventContext(page, timeoutMs) {
  await page.waitForSelector(".timeline-node", { state: "attached", timeout: timeoutMs });
  await page.waitForSelector("#runtimeMap [data-map-ref]", { state: "attached", timeout: timeoutMs });
  await page.evaluate(() => {
    const nodes = Array.from(document.querySelectorAll(".timeline-node"));
    const target = nodes.find((node) => (
      node.textContent.includes("#2")
      || node.textContent.includes("cp.003")
      || node.textContent.includes("CP 003")
    ));
    target?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await page.waitForFunction(
    () => {
      const target = document.getElementById("selectedMapTarget")?.textContent || "";
      const summary = document.getElementById("selectedEventSummary")?.textContent || "";
      return (
        target.includes("route-progress")
        || target.includes("cp.003")
        || summary.includes("safety_event_emitted")
      );
    },
    null,
    { timeout: timeoutMs },
  ).catch(() => {});
}

async function runPrompt(page, prompt, timeoutMs) {
  const evaluation = await page.evaluate(async (prompt) => {
    const response = await fetch("/admin/ui-action-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        surface: prompt.surface,
        request_text: prompt.prompt_zh,
      }),
    });
    const plan = await response.json();
    const application = window.ScoutAssistantUI.applyUiActionPlan(plan, { confirmed: false });
    const layerStates = Array.from(document.querySelectorAll("[data-layer]")).map((input) => ({
      layer: input.getAttribute("data-layer"),
      checked: Boolean(input.checked),
    }));
    const assistantAnswer = document.getElementById("assistantAnswerText")?.textContent || "";
    const reviewSeverity = document.getElementById("reviewSeverityFilter")?.value || "";
    return { plan, application, layerStates, assistantAnswer, reviewSeverity };
  }, prompt);

  if (prompt.expected_action_kind === "workspace_search") {
    await page.waitForFunction(
      () => (document.getElementById("assistantAnswerText")?.textContent || "").includes("Workspace search returned"),
      null,
      { timeout: timeoutMs },
    ).catch(() => {});
    evaluation.assistantAnswer = await page.evaluate(
      () => document.getElementById("assistantAnswerText")?.textContent || "",
    );
  }

  return evaluatePromptResult(prompt, evaluation);
}

function evaluatePromptResult(prompt, evaluation) {
  const plan = evaluation.plan || {};
  const application = evaluation.application || {};
  const actions = Array.isArray(plan.actions) ? plan.actions : [];
  const results = Array.isArray(application.results) ? application.results : [];
  const firstAction = actions[0] || {};
  const resultStatuses = results.map((result) => result.status);
  const requiresConfirmation = Boolean(prompt.requires_confirmation);
  const expectedStatus = requiresConfirmation ? "partial" : "applied";
  const expectedResultStatus = requiresConfirmation ? "blocked" : null;
  const isWorkspaceSearch = prompt.expected_action_kind === "workspace_search";
  const okChecks = [];
  const reasons = [];

  check(okChecks, reasons, plan.artifact_version === "scout_ui_action_plan.v0", "wrong artifact version");
  check(okChecks, reasons, plan.status === "planned", "plan was not planned");
  check(okChecks, reasons, firstAction.action_kind === prompt.expected_action_kind, "wrong action kind");
  check(
    okChecks,
    reasons,
    application.status === expectedStatus || (isWorkspaceSearch && application.status === "partial"),
    `application status was not ${expectedStatus}`,
  );
  if (expectedResultStatus) {
    check(okChecks, reasons, resultStatuses.includes(expectedResultStatus), "confirmation action was not blocked");
    check(
      okChecks,
      reasons,
      results.some((result) => result.block_reason === "confirmation_required"),
      "missing confirmation_required block",
    );
  } else if (!isWorkspaceSearch) {
    check(
      okChecks,
      reasons,
      results.every((result) => result.status === "applied" || result.status === "dispatched"),
      "non-confirmation action did not apply or dispatch",
    );
  } else {
    check(
      okChecks,
      reasons,
      results.every((result) => result.status === "pending" || result.status === "dispatched"),
      "workspace search was not dispatched",
    );
  }
  if (prompt.expected_preset === "risk_only") {
    const riskLayers = new Set(firstAction.visible_layers || []);
    check(okChecks, reasons, riskLayers.has("risk-score"), "risk-score layer missing from preset");
    check(okChecks, reasons, layerChecked(evaluation.layerStates, "risk-score"), "risk-score checkbox not enabled");
    check(okChecks, reasons, !layerChecked(evaluation.layerStates, "imagery"), "imagery checkbox still enabled");
  }
  if (isWorkspaceSearch) {
    check(
      okChecks,
      reasons,
      evaluation.assistantAnswer.includes("Workspace search returned"),
      "workspace search did not render local evidence result",
    );
  }
  if (prompt.expected_action_kind === "set_review_filter") {
    check(okChecks, reasons, evaluation.reviewSeverity === "blocker", "review severity was not blocker");
  }

  return {
    id: prompt.id,
    surface: prompt.surface,
    prompt_zh: prompt.prompt_zh,
    expected_action_kind: prompt.expected_action_kind,
    plan_status: plan.status,
    action_kind: firstAction.action_kind || "",
    application_status: application.status,
    result_statuses: resultStatuses,
    ok: reasons.length === 0,
    reason: reasons.join("; "),
  };
}

function check(_checks, reasons, passed, reason) {
  if (!passed) reasons.push(reason);
}

function layerChecked(layerStates, layer) {
  const match = (layerStates || []).find((item) => item.layer === layer);
  return Boolean(match && match.checked);
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

function stopServer(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
      resolve();
    }, 3000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
