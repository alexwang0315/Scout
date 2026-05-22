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
        const checks = await collectChecks(surface, page);
        const screenshotPath = screenshotsDir
          ? path.join(screenshotsDir, `${surface.id}-${viewport.id}.png`)
          : "";
        if (screenshotPath) await page.screenshot({ path: screenshotPath, fullPage: false });
        results.push({
          surface: surface.id,
          viewport: viewport.id,
          url,
          title: await page.title(),
          screenshot: screenshotPath || undefined,
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

async function waitForSurface(surface, page) {
  for (const selector of surface.selectors) {
    await page.waitForSelector(selector, { state: "attached", timeout: 10_000 });
  }
  for (const ready of surface.ready || []) {
    await page.waitForFunction(
      ({ selector, missingText }) => {
        const node = document.querySelector(selector);
        return Boolean(node) && !node.textContent.includes(missingText);
      },
      ready,
      { timeout: 10_000 },
    );
  }
}

async function collectChecks(surface, page) {
  return page.evaluate(({ surfaceId, expectedTitle, selectors }) => {
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
      if (surfaceId === "after-action") {
        return compareCenteredMapColumns(".tree-pane", ".map-pane", ".json-pane");
      }
      if (surfaceId === "debug") {
        return compareCenteredMapColumns(".timeline-panel", ".map-panel", ".details-panel");
      }
      return { ok: true, skipped: true };
    }
    const doc = document.documentElement;
    const bodyText = document.body.innerText.trim();
    const selectorResults = selectors.map((selector) => ({
      selector,
      count: document.querySelectorAll(selector).length,
    }));
    const missingSelectors = selectorResults
      .filter((result) => result.count === 0)
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
    const titleMatches = document.title === expectedTitle;
    const nonBlank = bodyText.length > 80 && visibleTextBlocks >= 6;
    const noHorizontalOverflow = horizontalOverflowPx <= 24;
    const mapLayout = centeredMapLayout();
    if (
      missingSelectors.length
      || !titleMatches
      || !nonBlank
      || !noHorizontalOverflow
      || tinyTargets.length
      || !mapLayout.ok
    ) {
      throw new Error(JSON.stringify({
        missingSelectors,
        titleMatches,
        nonBlank,
        noHorizontalOverflow,
        horizontalOverflowPx,
        tinyTargets,
        mapLayout,
      }));
    }
    return {
      titleMatches,
      selectorResults,
      nonBlank,
      visibleTextBlocks,
      noHorizontalOverflow,
      horizontalOverflowPx,
      tinyTargets,
      mapLayout,
    };
  }, { surfaceId: surface.id, expectedTitle: surface.title, selectors: surface.selectors });
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
