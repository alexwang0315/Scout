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

let chromium = null;

function chromiumLauncher() {
  if (!chromium) chromium = require("playwright").chromium;
  return chromium;
}

const fixtureHarness = process.argv.includes("--fixture-harness");
const runtimeUrlArgument = process.argv.find(argument => argument.startsWith("--runtime-url="));
const projectIdArgument = process.argv.find(argument => argument.startsWith("--project-id="));
const configuredRuntimeUrl = (
  runtimeUrlArgument?.split("=", 2)[1]
  || process.env.SCOUT_QUALIFICATION_RUNTIME_URL
  || ""
).trim();
const configuredRuntimeProjectId = (
  projectIdArgument?.split("=", 2)[1]
  || process.env.SCOUT_QUALIFICATION_PROJECT_ID
  || ""
).trim();
const readyProjectId = fixtureHarness ? "chilai_nanhua_day1" : configuredRuntimeProjectId;
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
const browserActionContractPath = path.join(
  repoRoot,
  "qualification/dashboard-browser-action-contract.json",
);
const CONTROL_OPERATION_TIMEOUT_MS = 90_000;
const CONTROL_DISCOVERY_TIMEOUT_MS = 90_000;
const CONTROL_ROUTE_TIMEOUT_MS = 10 * 60_000;
const CASE_EXECUTION_TIMEOUT_MS = 30 * 60_000;
const CASE_FINALIZATION_TIMEOUT_MS = 90_000;
const ROUTE_TRACE_FINALIZATION_TIMEOUT_MS = 30_000;
const ROUTE_FRAME_VISIBILITY_TIMEOUT_MS = 5_000;
const CASE_FAILURE_SCREENSHOT_TIMEOUT_MS = 15_000;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function runCaseFinalizerWithTimeout(
  label,
  operation,
  timeoutMs = CASE_FINALIZATION_TIMEOUT_MS,
) {
  let timeoutHandle;
  const timeout = new Promise((_, reject) => {
    timeoutHandle = setTimeout(() => {
      const error = new Error(
        `${label} exceeded ${timeoutMs}ms while closing browser evidence.`,
      );
      error.code = "CASE_FINALIZATION_TIMEOUT";
      error.timeoutMs = timeoutMs;
      reject(error);
    }, timeoutMs);
  });
  try {
    return await Promise.race([Promise.resolve().then(operation), timeout]);
  } finally {
    clearTimeout(timeoutHandle);
  }
}

async function runCaseExecutionWithTimeout(definition, operation) {
  const caseId = String(definition?.id || "unknown-case");
  const configuredTimeout = Number(definition?.executionTimeoutMs);
  const timeoutMs = Number.isFinite(configuredTimeout) && configuredTimeout > 0
    ? configuredTimeout
    : CASE_EXECUTION_TIMEOUT_MS;
  let timeoutHandle;
  const timeout = new Promise((_, reject) => {
    timeoutHandle = setTimeout(() => {
      const error = new Error(
        `${caseId} exceeded ${timeoutMs}ms while executing its browser case body.`,
      );
      error.code = "CASE_EXECUTION_TIMEOUT";
      error.caseId = caseId;
      error.timeoutMs = timeoutMs;
      reject(error);
    }, timeoutMs);
  });
  try {
    return await Promise.race([Promise.resolve().then(operation), timeout]);
  } finally {
    clearTimeout(timeoutHandle);
  }
}

function appendCaseProgress(observations, event, detail = {}) {
  const record = {
    schema: "scout.dashboardQualificationCaseProgress.v1",
    observed_at: new Date().toISOString(),
    case_id: observations.caseId,
    event,
    ...detail,
  };
  fs.appendFileSync(
    path.join(observations.caseDirectory, "case-progress.jsonl"),
    `${JSON.stringify(record)}\n`,
  );
  return record;
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function loadBrowserActionContract() {
  const contract = JSON.parse(fs.readFileSync(browserActionContractPath, "utf8"));
  assert(
    contract?.schema === "scout.dashboardBrowserActionContract.v1",
    "Dashboard browser action contract is missing or has the wrong schema.",
  );
  assert(
    contract?.official_mode?.contract_tests_are_dashboard_evidence === false,
    "Qualification contract tests must never be treated as Dashboard evidence.",
  );
  assert(
    contract?.official_mode?.browser_operation_required === true,
    "Official qualification must require browser operation.",
  );
  assert(
    contract?.official_mode?.zero_unmapped_controls_required === true,
    "Official qualification must fail when a visible control is not mapped.",
  );
  return Object.freeze(contract);
}

const browserActionContract = loadBrowserActionContract();

function loadExpectedPretripLayerIds(python) {
  const result = spawnSync(
    python,
    [
      "-c",
      "import json; from scout_layer_contract import SCOUT_LAYER_IDS, SCOUT_SURFACE_LAYER_IDS; print(json.dumps({'all': list(SCOUT_LAYER_IDS), 'pretrip': list(SCOUT_SURFACE_LAYER_IDS['pretrip'])}))",
    ],
    {cwd: repoRoot, encoding: "utf8"},
  );
  assert(result.status === 0, result.stderr || result.stdout || "Scout layer contract could not be loaded.");
  const payload = JSON.parse(result.stdout);
  assert(Array.isArray(payload.pretrip) && payload.pretrip.length > 0, "Pre-trip layer contract is empty.");
  return payload;
}

function normalizeRuntimeBaseUrl(value) {
  assert(value, "SCOUT_QUALIFICATION_RUNTIME_URL or --runtime-url is required for official qualification.");
  const parsed = new URL(value);
  assert(["http:", "https:"].includes(parsed.protocol), "Runtime URL must use http or https.");
  assert(!parsed.username && !parsed.password, "Runtime URL must not contain credentials.");
  assert(!parsed.search && !parsed.hash, "Runtime URL must not contain query or fragment state.");
  assert(parsed.pathname === "/" || parsed.pathname === "", "Runtime URL must be an origin without a path.");
  return parsed.origin;
}

async function fetchPayload(url, { required = true } = {}) {
  let response;
  try {
    response = await fetch(url, { redirect: "manual", cache: "no-store" });
  } catch (error) {
    if (!required) return { status: 0, payload: null, text: "", error: String(error) };
    throw new Error(`Runtime request failed for ${url}: ${error}`);
  }
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      payload = null;
    }
  }
  if (required) assert(response.ok, `Runtime request returned HTTP ${response.status}: ${url}`);
  return { status: response.status, payload, text, error: null };
}

function localListenerPid(baseUrl) {
  const parsed = new URL(baseUrl);
  if (!["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) return null;
  const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
  const result = spawnSync(
    "lsof",
    ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"],
    { encoding: "utf8" },
  );
  if (result.status !== 0) return null;
  const pids = result.stdout.split(/\s+/).filter(Boolean).sort();
  return pids.length === 1 ? pids[0] : null;
}

async function attestLiveRuntime(baseUrl, projectId, phase) {
  assert(projectId && /^[A-Za-z0-9_.-]+$/.test(projectId), "A valid real runtime --project-id is required.");
  const dashboard = await fetchPayload(
    `${baseUrl}/admin/dashboard?projectId=${encodeURIComponent(projectId)}`,
  );
  assert(dashboard.text.includes("Scout Dashboard"), "Runtime response is not the Scout Dashboard.");
  const catalog = await fetchPayload(`${baseUrl}/admin/dashboard/workspaces`);
  assert(catalog.payload && Array.isArray(catalog.payload.projects), "Runtime workspace catalog is invalid.");
  const selected = catalog.payload.projects.find(item => item?.project_id === projectId);
  assert(selected, `Runtime project is not present in the workspace catalog: ${projectId}`);
  assert(selected.workspace_backed === true, `Runtime project is not workspace-backed: ${projectId}`);
  const project = await fetchPayload(
    `${baseUrl}/admin/pretrip/projects/${encodeURIComponent(projectId)}?compact=1`,
  );
  const assistant = await fetchPayload(`${baseUrl}/assistant/status`, { required: false });
  const workspaceRoot = String(selected.resolved_project_root || "");
  const fixtureSignals = [];
  if (assistant.payload?.provider_class === "QualificationAssistantProvider") fixtureSignals.push("qualification_assistant_provider");
  if (assistant.payload?.runtime_profile === "dashboard-qualification") fixtureSignals.push("qualification_runtime_profile");
  if (project.payload?.qualification_fixture_state) fixtureSignals.push("qualification_fixture_state");
  if (String(project.payload?.artifact_kind || "").includes("qualification_synthetic")) fixtureSignals.push("qualification_synthetic_artifact");
  if (workspaceRoot.includes("scout-dashboard-qualification-")) fixtureSignals.push("temporary_qualification_workspace");
  assert(fixtureSignals.length === 0, `Official qualification rejected fixture runtime: ${fixtureSignals.join(", ")}`);
  assert(workspaceRoot && fs.existsSync(workspaceRoot) && fs.statSync(workspaceRoot).isDirectory(), "Runtime workspace root is not locally readable for no-write verification.");
  const parsed = new URL(baseUrl);
  const localListenerPidRequired = ["127.0.0.1", "localhost", "::1"].includes(parsed.hostname);
  return {
    workspaceRoot,
    publicEvidence: {
      schema: "scout.dashboardRuntimeAttestation.v1",
      phase,
      observed_at: new Date().toISOString(),
      runtime_provenance: "live_operational_dashboard",
      runtime_base_url: baseUrl,
      runtime_port: Number(parsed.port || (parsed.protocol === "https:" ? 443 : 80)),
      project_id: projectId,
      dashboard_http_status: dashboard.status,
      dashboard_html_sha256: sha256(dashboard.text),
      workspace_catalog_http_status: catalog.status,
      workspace_catalog_project_count: catalog.payload.projects.length,
      selected_workspace_backed: true,
      workspace_root_path_sha256: sha256(workspaceRoot),
      assistant_http_status: assistant.status,
      assistant_provider_class: assistant.payload?.provider_class || null,
      runtime_profile: assistant.payload?.runtime_profile || null,
      local_listener_pid: localListenerPid(baseUrl),
      local_listener_pid_required: localListenerPidRequired,
      fixture_signals: fixtureSignals,
      runner_started_runtime: false,
      official_qualification_eligible: true,
      runtime_safety_truth: false,
    },
  };
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

function evidenceSafeUrl(value) {
  try {
    const parsed = new URL(String(value));
    parsed.username = "";
    parsed.password = "";
    for (const key of [...parsed.searchParams.keys()]) {
      if (/(?:token|secret|password|authorization|cookie|api[_-]?key)/i.test(key)) {
        parsed.searchParams.set(key, "<redacted>");
      }
    }
    parsed.hash = "";
    return parsed.toString();
  } catch (_error) {
    return "<invalid-url>";
  }
}

function recordBrowserAction(observations, action, target, outcome = "completed", evidence = {}) {
  observations.browserActions.push({
    observed_at: new Date().toISOString(),
    action,
    target,
    outcome,
    ...evidence,
  });
}

function visualEvidencePath(observations, group, slug) {
  const relative = path.join(
    "cases",
    safeCaseId(observations.caseId),
    "states",
    safeCaseId(group),
    `${safeCaseId(slug)}.png`,
  );
  const absolute = path.join(observations.outputRoot, relative);
  fs.mkdirSync(path.dirname(absolute), { recursive: true });
  return { absolute, relative: relative.split(path.sep).join("/") };
}

async function analyzeScreenshotPixels(page, imageBuffer) {
  const dataUrl = `data:image/png;base64,${imageBuffer.toString("base64")}`;
  return page.evaluate(async encoded => {
    const image = new Image();
    image.src = encoded;
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error("Screenshot could not be decoded for visual analysis."));
    });
    const maxDimension = 512;
    const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(image, 0, 0, width, height);
    const pixels = context.getImageData(0, 0, width, height).data;
    const luminance = new Float64Array(width * height);
    let sum = 0;
    let sumSquares = 0;
    for (let index = 0; index < luminance.length; index += 1) {
      const offset = index * 4;
      const value = .2126 * pixels[offset] + .7152 * pixels[offset + 1] + .0722 * pixels[offset + 2];
      luminance[index] = value;
      sum += value;
      sumSquares += value * value;
    }
    const mean = sum / luminance.length;
    const variance = Math.max(0, sumSquares / luminance.length - mean * mean);
    let edgeCount = 0;
    let laplacianCount = 0;
    let laplacianSum = 0;
    let laplacianSquares = 0;
    for (let y = 1; y < height - 1; y += 1) {
      for (let x = 1; x < width - 1; x += 1) {
        const index = y * width + x;
        const horizontal = Math.abs(luminance[index + 1] - luminance[index - 1]);
        const vertical = Math.abs(luminance[index + width] - luminance[index - width]);
        if (horizontal + vertical >= 28) edgeCount += 1;
        const laplacian = 4 * luminance[index]
          - luminance[index - 1]
          - luminance[index + 1]
          - luminance[index - width]
          - luminance[index + width];
        laplacianCount += 1;
        laplacianSum += laplacian;
        laplacianSquares += laplacian * laplacian;
      }
    }
    const laplacianMean = laplacianCount ? laplacianSum / laplacianCount : 0;
    const laplacianVariance = laplacianCount
      ? Math.max(0, laplacianSquares / laplacianCount - laplacianMean * laplacianMean)
      : 0;
    return {
      source_width: image.naturalWidth,
      source_height: image.naturalHeight,
      sampled_width: width,
      sampled_height: height,
      luminance_stddev: Math.sqrt(variance),
      edge_density: laplacianCount ? edgeCount / laplacianCount : 0,
      laplacian_variance: laplacianVariance,
    };
  }, dataUrl);
}

async function collectDomVisualMetrics(rootLocator) {
  const quality = browserActionContract.visual_quality;
  return rootLocator.evaluate((root, thresholds) => {
    const analysisStartedAt = performance.now();
    const visible = element => {
      if (element.closest("[hidden], [aria-hidden='true']")) return false;
      const closedDetails = element.closest("details:not([open])");
      if (closedDetails) {
        const summary = closedDetails.querySelector(":scope > summary");
        if (!summary || (element !== summary && !summary.contains(element))) return false;
      }
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && element.getClientRects().length > 0
        && rect.width > 0
        && rect.height > 0;
    };
    const centerInsideClippingAncestors = element => {
      const rect = element.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      let current = element.parentElement;
      while (current) {
        const style = getComputedStyle(current);
        const clipsX = ["auto", "scroll", "hidden", "clip"].includes(style.overflowX);
        const clipsY = ["auto", "scroll", "hidden", "clip"].includes(style.overflowY);
        if (clipsX || clipsY) {
          const ancestorRect = current.getBoundingClientRect();
          if (clipsX && (centerX < ancestorRect.left || centerX > ancestorRect.right)) return false;
          if (clipsY && (centerY < ancestorRect.top || centerY > ancestorRect.bottom)) return false;
        }
        if (current === root) break;
        current = current.parentElement;
      }
      return true;
    };
    const visibleInViewport = element => {
      if (!visible(element)) return false;
      const rect = element.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      return centerX >= 0
        && centerX <= innerWidth
        && centerY >= 0
        && centerY <= innerHeight
        && centerInsideClippingAncestors(element);
    };
    const describe = element => {
      const dataKey = Object.keys(element.dataset || {}).sort()[0];
      const dataValue = dataKey ? `${dataKey}=${element.dataset[dataKey]}` : "";
      const text = String(element.getAttribute("aria-label") || element.textContent || "")
        .trim()
        .replace(/\s+/g, " ")
        .slice(0, 100);
      return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${dataValue ? `[${dataValue}]` : ""}${text ? `:${text}` : ""}`;
    };
    const all = [...root.querySelectorAll("*")].filter(visibleInViewport);
    const textElements = all.filter(element => {
      if (element instanceof SVGElement && element.tagName.toLowerCase() !== "text") return false;
      return [...element.childNodes].some(child => (
        child.nodeType === Node.TEXT_NODE && String(child.textContent || "").trim()
      ));
    });
    const activeModal = [...root.querySelectorAll('[role="dialog"][aria-modal="true"]')].find(visibleInViewport);
    const interactionRoot = activeModal || root;
    const insideStickyLayer = element => {
      let current = element;
      while (current && current !== root.parentElement) {
        const position = getComputedStyle(current).position;
        if (["sticky", "fixed"].includes(position)) return current;
        current = current.parentElement;
      }
      return null;
    };
    const isMapInteractionSurface = element => element.matches(
      "svg#map, [data-dashboard-map-viewport], [data-dashboard-basemap-layer], .maplibregl-map, .maplibregl-canvas",
    );
    const interactive = [...interactionRoot.querySelectorAll(
      "button, a[href], input, select, textarea, summary, [role=button], [role=tab], [tabindex]:not([tabindex='-1'])",
    )].filter(element => visibleInViewport(element) && !element.disabled && element.getAttribute("aria-disabled") !== "true");
    const blurredElements = all
      .filter(element => {
        const style = getComputedStyle(element);
        return /blur\(\s*(?!0(?:px)?\s*\))[^)]+\)/i.test(style.filter || "");
      })
      .map(describe);
    const backdropBlurElements = all
      .filter(element => /blur\(\s*(?!0(?:px)?\s*\))[^)]+\)/i.test(getComputedStyle(element).backdropFilter || ""))
      .map(describe);
    const brokenImages = [...root.querySelectorAll("img")]
      .filter(element => visibleInViewport(element) && element.complete && element.naturalWidth === 0)
      .map(describe);
    const lowResolutionRasters = [...root.querySelectorAll("img, canvas")]
      .filter(visibleInViewport)
      .flatMap(element => {
        const rect = element.getBoundingClientRect();
        const sourceWidth = element instanceof HTMLCanvasElement ? element.width : element.naturalWidth;
        const sourceHeight = element instanceof HTMLCanvasElement ? element.height : element.naturalHeight;
        if (!sourceWidth || !sourceHeight) return [];
        const requiredWidth = rect.width * devicePixelRatio;
        const requiredHeight = rect.height * devicePixelRatio;
        const upscale = Math.max(requiredWidth / sourceWidth, requiredHeight / sourceHeight);
        return upscale > 1.5 ? [{element: describe(element), upscale_ratio: upscale}] : [];
      });
    const clippedText = textElements
      .filter(element => {
        if (!String(element.textContent || "").trim()) return false;
        if (element.classList.contains("sr-only")) return false;
        const style = getComputedStyle(element);
        const clipsX = ["hidden", "clip"].includes(style.overflowX);
        const clipsY = ["hidden", "clip"].includes(style.overflowY);
        return (clipsX && element.scrollWidth > element.clientWidth + 2)
          || (clipsY && element.scrollHeight > element.clientHeight + 2);
      })
      .map(describe);
    const lowReadabilityText = textElements
      .filter(element => {
        if (!String(element.textContent || "").trim()) return false;
        if (element.classList.contains("sr-only")) return false;
        if (element.closest("[disabled], [aria-disabled='true']")) return false;
        const style = getComputedStyle(element);
        const effectiveTextPixelSize = element instanceof SVGElement
          && element.tagName.toLowerCase() === "text"
          ? Math.max(Number.parseFloat(style.fontSize), element.getBoundingClientRect().height)
          : Number.parseFloat(style.fontSize);
        return effectiveTextPixelSize < Number(thresholds.minimum_readable_font_px)
          || Number(style.opacity || 1) < .55;
      })
      .map(describe);
    const viewportInteractive = interactive;
    const rectangularControls = viewportInteractive.filter(element => (
      !(element instanceof SVGElement)
      && !(element instanceof HTMLCanvasElement)
      && !isMapInteractionSurface(element)
    ));
    const occludedControls = rectangularControls.flatMap(element => {
      const rect = element.getBoundingClientRect();
      const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2));
      const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height / 2));
      if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) return [];
      const top = document.elementsFromPoint(x, y).find(candidate => getComputedStyle(candidate).pointerEvents !== "none");
      if (!top || top === element || element.contains(top) || top.contains(element)) return [];
      const coveringStickyLayer = insideStickyLayer(top);
      const controlStickyLayer = insideStickyLayer(element);
      if (coveringStickyLayer && coveringStickyLayer !== controlStickyLayer) return [];
      const coveringMapSurface = top.closest(
        "svg#map, [data-dashboard-map-viewport], [data-dashboard-basemap-layer], .maplibregl-map, .maplibregl-canvas",
      );
      if (
        coveringMapSurface
        && element.closest(".layer-menu-panel, .map-controls, .map-toolbar, .toolbar-row, .control-group")
      ) return [];
      return [{control: describe(element), covering_element: describe(top)}];
    });
    const overlappingControlPairs = [];
    const overlapGrid = new Map();
    const comparedPairs = new Set();
    const gridCellSize = 96;
    const controlEntries = rectangularControls.map((element, index) => ({
      element,
      index,
      rect: element.getBoundingClientRect(),
    }));
    for (const entry of controlEntries) {
      const minColumn = Math.floor(Math.max(0, entry.rect.left) / gridCellSize);
      const maxColumn = Math.floor(Math.max(0, Math.min(innerWidth - 1, entry.rect.right)) / gridCellSize);
      const minRow = Math.floor(Math.max(0, entry.rect.top) / gridCellSize);
      const maxRow = Math.floor(Math.max(0, Math.min(innerHeight - 1, entry.rect.bottom)) / gridCellSize);
      const nearbyIndexes = new Set();
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let column = minColumn; column <= maxColumn; column += 1) {
          const cellKey = `${column}:${row}`;
          for (const candidateIndex of overlapGrid.get(cellKey) || []) nearbyIndexes.add(candidateIndex);
        }
      }
      for (const candidateIndex of nearbyIndexes) {
        const pairKey = `${candidateIndex}:${entry.index}`;
        if (comparedPairs.has(pairKey)) continue;
        comparedPairs.add(pairKey);
        const candidate = controlEntries[candidateIndex];
        if (candidate.element.contains(entry.element) || entry.element.contains(candidate.element)) continue;
        const candidateStickyLayer = insideStickyLayer(candidate.element);
        const entryStickyLayer = insideStickyLayer(entry.element);
        if (Boolean(candidateStickyLayer) !== Boolean(entryStickyLayer)) continue;
        const width = Math.max(0, Math.min(candidate.rect.right, entry.rect.right) - Math.max(candidate.rect.left, entry.rect.left));
        const height = Math.max(0, Math.min(candidate.rect.bottom, entry.rect.bottom) - Math.max(candidate.rect.top, entry.rect.top));
        const area = width * height;
        const smaller = Math.max(1, Math.min(
          candidate.rect.width * candidate.rect.height,
          entry.rect.width * entry.rect.height,
        ));
        if (area > 4 && area / smaller > .08) {
          overlappingControlPairs.push([describe(candidate.element), describe(entry.element)]);
        }
      }
      for (let row = minRow; row <= maxRow; row += 1) {
        for (let column = minColumn; column <= maxColumn; column += 1) {
          const cellKey = `${column}:${row}`;
          const occupants = overlapGrid.get(cellKey) || [];
          overlapGrid.set(cellKey, [...occupants, entry.index]);
        }
      }
    }
    const documentElement = root.ownerDocument.documentElement;
    return {
      horizontal_overflow_px: Math.max(0, documentElement.scrollWidth - documentElement.clientWidth),
      blurred_elements: blurredElements,
      backdrop_blur_elements: backdropBlurElements,
      broken_images: brokenImages,
      low_resolution_rasters: lowResolutionRasters,
      clipped_text: clippedText,
      low_readability_text: lowReadabilityText,
      occluded_controls: occludedControls,
      overlapping_control_pairs: overlappingControlPairs,
      visible_interactive_count: interactive.length,
      viewport_interactive_count: viewportInteractive.length,
      overlap_candidate_pair_count: comparedPairs.size,
      analysis_duration_ms: performance.now() - analysisStartedAt,
      root_width: root.getBoundingClientRect().width,
      root_height: root.getBoundingClientRect().height,
    };
  }, quality);
}

function visualQualityIssues(checkpoint, label) {
  const quality = browserActionContract.visual_quality;
  const issues = [];
  const dom = checkpoint.dom;
  const pixels = checkpoint.pixels;
  if (dom.horizontal_overflow_px > quality.max_horizontal_overflow_px) {
    issues.push(`${label}: horizontal overflow ${dom.horizontal_overflow_px}px`);
  }
  for (const [key, maximum] of [
    ["occluded_controls", quality.max_occluded_controls],
    ["overlapping_control_pairs", quality.max_overlapping_control_pairs],
    ["blurred_elements", quality.max_blurred_elements],
    ["broken_images", quality.max_broken_images],
    ["low_resolution_rasters", quality.max_low_resolution_rasters],
    ["clipped_text", quality.max_unexplained_clipped_text],
  ]) {
    if ((dom[key] || []).length > maximum) {
      issues.push(`${label}: ${key}=${JSON.stringify(dom[key])}`);
    }
  }
  if ((dom.low_readability_text || []).length) {
    issues.push(`${label}: low_readability_text=${JSON.stringify(dom.low_readability_text)}`);
  }
  if (pixels.luminance_stddev < quality.minimum_screenshot_luminance_stddev) {
    issues.push(`${label}: screenshot luminance stddev ${pixels.luminance_stddev}`);
  }
  if (pixels.edge_density < quality.minimum_screenshot_edge_density) {
    issues.push(`${label}: screenshot edge density ${pixels.edge_density}`);
  }
  if (pixels.laplacian_variance < quality.minimum_screenshot_laplacian_variance) {
    issues.push(`${label}: screenshot sharpness ${pixels.laplacian_variance}`);
  }
  return issues;
}

function canonicalVisualIssueSignature(issue) {
  return String(issue || "")
    .replace(/^[^:]+:[^:]+:\s*/, "")
    .replace(/data-scout-qualification-[a-z-]+=[^\]:,}]+/gi, "data-scout-qualification=<dynamic>")
    .replace(/q-\d+-[a-f0-9]{8}/gi, "q-<dynamic>");
}

function visualIssueRootSignature(issue) {
  const canonical = canonicalVisualIssueSignature(issue);
  const separatorIndex = canonical.indexOf("=");
  if (separatorIndex < 0) {
    return canonical
      .replace(/-?\d+(?:\.\d+)?(?:px)?/gi, "<number>")
      .replace(/\s+/g, " ")
      .trim();
  }
  const kind = canonical.slice(0, separatorIndex).trim();
  const rawPayload = canonical.slice(separatorIndex + 1);
  let payload;
  try {
    payload = JSON.parse(rawPayload);
  } catch (_error) {
    return `${kind}=<unparsed>`;
  }
  const descriptors = [];
  const collect = value => {
    if (typeof value === "string") {
      descriptors.push(value);
      return;
    }
    if (Array.isArray(value)) {
      value.forEach(collect);
      return;
    }
    if (value && typeof value === "object") {
      Object.values(value).forEach(collect);
    }
  };
  collect(payload);
  const selectorFamilies = [...new Set(descriptors.map(descriptor => (
    String(descriptor)
      .split(":", 1)[0]
      .replace(/\[([^\]=]+)=[^\]]*\]/g, "[$1]")
      .replace(/\[scoutQualification[^\]]*\]/gi, "[scoutQualification]")
      .trim()
  )).filter(Boolean))].sort();
  const count = descriptors.length;
  const countBucket = count <= 1
    ? "1"
    : count <= 5
      ? "2-5"
      : count <= 20
        ? "6-20"
        : "21+";
  return `${kind}|selectors=${selectorFamilies.join(",")}|items=${countBucket}`;
}

function visualIssueDelta(beforeIssues, afterIssues) {
  const beforeSignatures = new Set((beforeIssues || []).map(canonicalVisualIssueSignature));
  const afterSignatures = new Set((afterIssues || []).map(canonicalVisualIssueSignature));
  return {
    baseline_visual_issues: [...(beforeIssues || [])],
    new_visual_issues: (afterIssues || []).filter(
      issue => !beforeSignatures.has(canonicalVisualIssueSignature(issue)),
    ),
    resolved_visual_issues: (beforeIssues || []).filter(
      issue => !afterSignatures.has(canonicalVisualIssueSignature(issue)),
    ),
  };
}

function assertVisualQuality(checkpoint, label) {
  const issues = visualQualityIssues(checkpoint, label);
  assert(issues.length === 0, `Visual quality failed: ${issues.join(" | ")}`);
  return checkpoint;
}

async function captureVisualCheckpoint(page, locator, observations, group, slug, options = {}) {
  const checkpointStartedAt = Date.now();
  appendCaseProgress(observations, "visual_checkpoint_started", {group, slug});
  const target = visualEvidencePath(observations, group, slug);
  const root = options.domRoot || locator || page.locator("body");
  await root.waitFor({ state: "visible", timeout: 60_000 });
  let buffer;
  if (locator) {
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        buffer = await locator.screenshot({
          path: target.absolute,
          type: "png",
          animations: "disabled",
          timeout: 60_000,
        });
        break;
      } catch (error) {
        if (attempt >= 3 || !isTransientControlLocatorError(error)) throw error;
        appendCaseProgress(observations, "visual_checkpoint_screenshot_retry", {
          group,
          slug,
          attempt,
          error: String(error?.message || error),
        });
        await page.waitForTimeout(250);
        await locator.waitFor({state: "visible", timeout: 60_000});
      }
    }
  } else {
    buffer = await page.screenshot({
      path: target.absolute,
      type: "png",
      fullPage: options.fullPage !== false,
      animations: "disabled",
      timeout: 60_000,
    });
  }
  assert(buffer, `Visual checkpoint ${group}/${slug} produced no screenshot buffer.`);
  appendCaseProgress(observations, "visual_checkpoint_screenshot_completed", {
    group,
    slug,
    screenshot: target.relative,
  });
  const pixels = await analyzeScreenshotPixels(page, buffer);
  appendCaseProgress(observations, "visual_checkpoint_pixels_completed", {group, slug});
  const dom = await collectDomVisualMetrics(root);
  appendCaseProgress(observations, "visual_checkpoint_dom_completed", {
    group,
    slug,
    analysis_duration_ms: dom.analysis_duration_ms,
    viewport_interactive_count: dom.viewport_interactive_count,
  });
  const checkpoint = {
    id: `${group}:${slug}`,
    screenshot: target.relative,
    screenshot_sha256: sha256(buffer),
    pixels,
    dom,
  };
  checkpoint.issues = visualQualityIssues(checkpoint, checkpoint.id);
  observations.visualCheckpoints.push(checkpoint);
  appendCaseProgress(observations, "visual_checkpoint_completed", {
    group,
    slug,
    duration_ms: Date.now() - checkpointStartedAt,
    issue_count: checkpoint.issues.length,
  });
  return checkpoint;
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
  const observations = page.__scoutQualificationObservations;
  if (observations) recordBrowserAction(observations, "navigate", `dashboard-route:${route}`);
}

function dashboardRouteRootSelector(route) {
  if (route === "map") return "#dashboardMap";
  if (route === "agent") return "#dashboardAgent";
  return "#workspace";
}

async function waitForRouteVisualReadiness(page, route, projectId) {
  if (route !== "map") return;
  const iframe = page.locator("#pretripMapFrame");
  await iframe.waitFor({state: "visible", timeout: 120_000});
  const deadline = Date.now() + 60_000;
  let frame = null;
  while (!frame && Date.now() < deadline) {
    const handle = await iframe.elementHandle();
    frame = await handle?.contentFrame() || null;
    await handle?.dispose().catch(() => undefined);
    if (!frame) await page.waitForTimeout(100);
  }
  assert(frame, "Map route iframe did not attach before visual qualification.");
  await waitForCanonicalEmbeddedMapReady(
    page,
    frame,
    projectId,
    "Dashboard Map visual readiness",
    {waitForDashboardOverlay: true},
  );
}

async function revealThroughClosedDetails(page, locator, observations, label) {
  if (!(await locator.count())) return;
  const keys = await locator.first().evaluate((node, targetLabel) => {
    const closed = [];
    let parent = node.parentElement;
    while (parent) {
      if (parent instanceof HTMLDetailsElement && !parent.open) closed.unshift(parent);
      parent = parent.parentElement;
    }
    return closed.map((details, index) => {
      const key = `${targetLabel}-${index}`.replace(/[^a-zA-Z0-9_-]/g, "-");
      details.dataset.scoutQualificationRevealKey = key;
      return key;
    });
  }, label);
  for (const key of keys) {
    const summary = page.locator(`details[data-scout-qualification-reveal-key="${key}"] > summary`).first();
    await summary.click();
    recordBrowserAction(observations, "click", `${label}:reveal-details`);
    await page.waitForTimeout(200);
  }
}

async function auditAllRouteVisualStates(page, observations, profileId) {
  const contractedRoutes = browserActionContract.routes.map(route => route.id);
  await openDashboard(page, observations.baseUrl, readyProjectId, "home");
  const renderedRoutes = await page.locator("button.nav-item[data-route]").evaluateAll(buttons => (
    [...new Set(buttons.map(button => button.dataset.route).filter(Boolean))].sort()
  ));
  assert(
    JSON.stringify(renderedRoutes) === JSON.stringify([...contractedRoutes].sort()),
    `Runtime navigation/action-contract mismatch: ${JSON.stringify({renderedRoutes, contractedRoutes})}`,
  );
  const visualAudits = [];
  const issues = [];
  for (const route of contractedRoutes) {
    const issueStart = issues.length;
    appendCaseProgress(observations, "route_started", {route, profile: profileId});
    try {
      await openDashboard(page, observations.baseUrl, readyProjectId, route);
      await page.waitForFunction(expectedRoute => (
        typeof state !== "undefined" && state.route === expectedRoute
      ), route, {timeout: 60_000});
      await waitForRouteVisualReadiness(page, route, readyProjectId);
      const workspace = page.locator(dashboardRouteRootSelector(route));
      await workspace.waitFor({ state: "visible", timeout: 120_000 });
      await page.waitForTimeout(500);
      const workspaceState = await workspace.evaluate(node => ({
        text_length: String(node.textContent || "").trim().length,
        width: node.getBoundingClientRect().width,
        height: node.getBoundingClientRect().height,
        workspace_scroll_height: node.scrollHeight,
        workspace_client_height: node.clientHeight,
        document_scroll_height: document.documentElement.scrollHeight,
        viewport_height: innerHeight,
      }));
      assert(workspaceState.text_length > 0, `${route} rendered an empty workspace.`);
      assert(workspaceState.width > 0 && workspaceState.height > 0, `${route} workspace has no rendered size.`);
      const useWorkspaceScroll = workspaceState.workspace_scroll_height > workspaceState.workspace_client_height + 1;
      const scrollViewportHeight = useWorkspaceScroll
        ? workspaceState.workspace_client_height
        : workspaceState.viewport_height;
      const maximumScroll = useWorkspaceScroll
        ? Math.max(0, workspaceState.workspace_scroll_height - workspaceState.workspace_client_height)
        : Math.max(0, workspaceState.document_scroll_height - workspaceState.viewport_height);
      const step = Math.max(240, Math.floor(scrollViewportHeight * .8));
      const positions = [];
      for (let position = 0; position < maximumScroll; position += step) positions.push(position);
      positions.push(maximumScroll);
      const uniquePositions = [...new Set(positions)];
      const checkpoints = [];
      for (let index = 0; index < uniquePositions.length; index += 1) {
        const position = uniquePositions[index];
        if (useWorkspaceScroll) {
          await workspace.evaluate((node, scrollTop) => node.scrollTo({top: scrollTop, behavior: "instant"}), position);
        } else {
          await page.evaluate(scrollTop => window.scrollTo({top: scrollTop, behavior: "instant"}), position);
        }
        await page.waitForTimeout(100);
        recordBrowserAction(
          observations,
          "scroll",
          `route:${route}`,
          "completed",
          {
            profile: profileId,
            scroll_target: useWorkspaceScroll ? "workspace" : "window",
            scroll_top: position,
          },
        );
        const checkpoint = await captureVisualCheckpoint(
          page,
          null,
          observations,
          `routes-${profileId}`,
          `${route}-scroll-${index}`,
          {fullPage: false, domRoot: workspace},
        );
        checkpoints.push(checkpoint);
        issues.push(...checkpoint.issues);
      }
      const frameAudits = [];
      for (const frame of page.frames().filter(candidate => candidate !== page.mainFrame())) {
        try {
          appendCaseProgress(observations, "route_frame_visibility_started", {
            route,
            profile: profileId,
            frame_index: frameAudits.length,
            frame_url: evidenceSafeUrl(frame.url()),
          });
          const frameHost = await runCaseFinalizerWithTimeout(
            "route-frame-visibility",
            () => frame.frameElement(),
            ROUTE_FRAME_VISIBILITY_TIMEOUT_MS,
          );
          const frameHostVisible = await runCaseFinalizerWithTimeout(
            "route-frame-visibility",
            () => frameHost.isVisible(),
            ROUTE_FRAME_VISIBILITY_TIMEOUT_MS,
          );
          await frameHost.dispose().catch(() => undefined);
          if (!frameHostVisible) continue;
          const frameBody = frame.locator("body");
          const frameBodyVisible = await runCaseFinalizerWithTimeout(
            "route-frame-visibility",
            () => frameBody.isVisible(),
            ROUTE_FRAME_VISIBILITY_TIMEOUT_MS,
          );
          if (!frameBodyVisible) continue;
          const checkpoint = await captureVisualCheckpoint(
            page,
            frameBody,
            observations,
            `routes-${profileId}`,
            `${route}-frame-${frameAudits.length}`,
          );
          frameAudits.push({url: evidenceSafeUrl(frame.url()), checkpoint});
          issues.push(...checkpoint.issues);
        } catch (error) {
          const detail = `${route}: embedded frame visual audit failed: ${String(error)}`;
          issues.push(detail);
          frameAudits.push({url: evidenceSafeUrl(frame.url()), error: detail});
        }
      }
      visualAudits.push({
        route,
        profile: profileId,
        workspace: workspaceState,
        scroll_target: useWorkspaceScroll ? "workspace" : "window",
        scroll_positions: uniquePositions,
        checkpoints,
        frames: frameAudits,
      });
      appendCaseProgress(observations, "route_completed", {
        route,
        profile: profileId,
        checkpoint_count: checkpoints.length,
        frame_count: frameAudits.length,
        issue_count: issues.length - issueStart,
      });
    } catch (error) {
      const detail = `${route}: ${String(error?.message || error)}`;
      issues.push(detail);
      visualAudits.push({route, profile: profileId, error: detail});
      appendCaseProgress(observations, "route_failed", {
        route,
        profile: profileId,
        error: detail,
      });
    }
  }
  observations.routeVisualAudits = visualAudits;
  observations.routeVisualIssues = issues;
  const visualIssueGroups = groupVisualQualityFindings(observations.visualCheckpoints);
  const failureSummary = summarizeRouteVisualAuditFailure(visualAudits, visualIssueGroups);
  observations.routeVisualIssueGroups = visualIssueGroups;
  observations.routeVisualFailureSummary = failureSummary;
  assert(
    failureSummary.operational_issue_count === 0 && visualIssueGroups.length === 0,
    `Route visual audit failures: ${JSON.stringify(failureSummary)}`,
  );
  return {
    profile: profileId,
    contractedRouteCount: contractedRoutes.length,
    auditedRouteCount: visualAudits.filter(audit => !audit.error).length,
    visualAudits,
    issues,
    visualIssueGroups,
  };
}

function controlIdentityIsEffectful(descriptor) {
  const value = [
    descriptor.id,
    descriptor.text,
    descriptor.aria_label,
    ...Object.entries(descriptor.data_attributes || {}).flat(),
  ]
    .join(" ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase();
  return /(?:^|[-_\s])(save|accept|submit|send|publish|delete|remove|import|upload|prepare|generate|regenerate|rebuild|authorize|approve|reject|execute|install|write|watch|transport|payment|purchase)(?:$|[-_\s])/i.test(value)
    || /(?:^|[-_\s])run(?:$|[-_\s])/i.test(value);
}

function controlCoverageGapRecord(control, cause, detail = "") {
  const definitions = {
    disabled_in_runtime_state: {
      terminalState: "DISABLED_IN_RUNTIME_STATE",
      detail: "This control was disabled in the selected live runtime state; an executable real state is required before the function can qualify.",
    },
    disappeared_before_operation: {
      terminalState: "DISAPPEARED_BEFORE_OPERATION",
      detail: "The control was visible during the route state walk but its stable identity was absent immediately before operation.",
    },
    nonvisible_after_discovery: {
      terminalState: "NONVISIBLE_AFTER_DISCOVERY",
      detail: "The control changed to a non-visible runtime state before operation.",
    },
    single_runtime_value: {
      terminalState: "SINGLE_RUNTIME_VALUE",
      detail: "This select exposed only one runtime value; an alternate real value is required before its behavior can qualify.",
    },
    route_aborted_after_operation_error: {
      terminalState: "ROUTE_ABORTED_AFTER_OPERATION_ERROR",
      detail: "The route audit stopped after an operation error; the remaining control requires a fresh live-runtime qualification.",
    },
  };
  const definition = definitions[cause];
  assert(definition, `Unknown control coverage gap cause: ${cause}`);
  return {
    ...control,
    terminal_state: definition.terminalState,
    legacy_terminal_state: "NOT_EXERCISED",
    coverage_gap_kind: cause,
    product_defect_claimed: false,
    detail: detail || definition.detail,
  };
}

function classifyPassiveControl(control) {
  if (control.discovery_error) {
    return {
      ...control,
      terminal_state: "UNMAPPED",
      detail: `Interactive controls could not be inventoried in ${control.context_id}: ${control.discovery_error}`,
    };
  }
  if (control.delegated_to) return {...control, terminal_state: "DELEGATED"};
  if (control.disabled) {
    return controlCoverageGapRecord(control, "disabled_in_runtime_state");
  }
  return {
    ...control,
    terminal_state: "EFFECT_AUTHORIZATION_REQUIRED",
    detail: "Persistent, outbound, hardware, preparation, or generation action was not executed by the read-only qualification role.",
  };
}

function controlOperationTerminalState(effectOracle) {
  if (!effectOracle.semantic_changed) return "NO_STATE_CHANGE";
  if (!effectOracle.visual_changed && effectOracle.popup_loaded !== true) {
    return "NO_VISUAL_CHANGE";
  }
  return "OPERATED";
}

function isTransientFrameDiscoveryError(error) {
  return /frame was detached/i.test(String(error?.message || error));
}

function isTransientControlLocatorError(error) {
  const detail = String(error?.message || error);
  return /element is not attached to the dom/i.test(detail)
    || (
      /timeout/i.test(detail)
      && /waiting for locator\(.+data-scout-qualification-control-key/i.test(detail)
    );
}

function isLoadedPopupUrl(value) {
  const raw = String(value?.href || value || "");
  try {
    const parsed = new URL(raw);
    return ["http:", "https:"].includes(parsed.protocol);
  } catch (_error) {
    return false;
  }
}

function summarizeControlCoverageFailure(blockingControls, visualIssueGroups) {
  const stateCounts = blockingControls.reduce((counts, control) => ({
    ...counts,
    [control.terminal_state]: (counts[control.terminal_state] || 0) + 1,
  }), {});
  const routeCounts = blockingControls.reduce((counts, control) => ({
    ...counts,
    [control.route || "unassigned"]: (counts[control.route || "unassigned"] || 0) + 1,
  }), {});
  const causeCounts = blockingControls.reduce((counts, control) => ({
    ...counts,
    [control.coverage_gap_kind || controlGapReason(control)]: (
      counts[control.coverage_gap_kind || controlGapReason(control)] || 0
    ) + 1,
  }), {});
  return {
    classification: "qualification_coverage_gap",
    product_defect_claimed: false,
    blocking_control_count: blockingControls.length,
    blocking_control_states: Object.fromEntries(Object.entries(stateCounts).sort()),
    blocking_control_routes: Object.fromEntries(Object.entries(routeCounts).sort()),
    blocking_control_causes: Object.fromEntries(Object.entries(causeCounts).sort()),
    blocking_control_samples: blockingControls.slice(0, 12).map(control => ({
      route: control.route,
      terminal_state: control.terminal_state,
      identity: String(control.identity || "").slice(0, 240),
      detail: String(control.detail || "").slice(0, 240),
    })),
    visual_issue_group_count: visualIssueGroups.length,
    visual_issue_groups: visualIssueGroups.slice(0, 12).map(group => ({
      observed_behavior: group.observed_behavior,
      occurrence_count: group.occurrence_count,
      evidence_refs: (group.evidence_refs || []).slice(0, 3),
    })),
  };
}

async function frameContextId(page, frame, ordinal) {
  if (frame === page.mainFrame()) return "main";
  let owner = {};
  try {
    const frameElement = await frame.frameElement();
    owner = await frameElement.evaluate(element => ({
      id: element.id || "",
      name: element.getAttribute("name") || "",
      title: element.getAttribute("title") || "",
      data: Object.fromEntries(Object.entries(element.dataset || {}).sort(([left], [right]) => left.localeCompare(right))),
    }));
  } catch (_error) {
    owner = {};
  }
  const stableOwner = owner.id
    || owner.name
    || Object.entries(owner.data || {}).map(([key, value]) => `${key}=${value}`).join(",")
    || owner.title
    || `ordinal-${ordinal}`;
  let framePath = "unresolved";
  try {
    const parsed = new URL(frame.url());
    framePath = parsed.pathname;
  } catch (_error) {
    framePath = frame.url() || "unresolved";
  }
  return `frame:${stableOwner}:${framePath}`;
}

function aggregateDelegatedMapEvidenceControls(controls) {
  const grouped = [];
  const groupIndexes = new Map();
  const aggregateTags = new Set(["path", "circle", "image"]);
  for (const control of controls) {
    const data = control.data_attributes || {};
    const evidenceType = data.evidenceType || "";
    const shouldAggregate = (
      control.delegated_to === "runtime-all-map-surface-interactions"
      && aggregateTags.has(control.tag)
      && Boolean(evidenceType)
    );
    if (!shouldAggregate) {
      grouped.push(control);
      continue;
    }
    const canonicalData = Object.fromEntries(
      ["evidenceType", "mapRenderKind", "singleImageTheme", "terrainOverlayMode"]
        .filter(key => data[key] !== undefined && data[key] !== "")
        .map(key => [key, data[key]]),
    );
    const groupPayload = {
      route: control.route,
      context_id: control.context_id,
      delegated_to: control.delegated_to,
      tag: control.tag,
      data_attributes: canonicalData,
    };
    const identity = JSON.stringify(groupPayload);
    const sourceId = data.sourceId || "";
    const existingIndex = groupIndexes.get(identity);
    if (existingIndex !== undefined) {
      const existing = grouped[existingIndex];
      const sourceSamples = sourceId && !existing.aggregate_source_samples.includes(sourceId)
        ? [...existing.aggregate_source_samples, sourceId].slice(0, 3)
        : existing.aggregate_source_samples;
      grouped[existingIndex] = {
        ...existing,
        aggregate_member_count: existing.aggregate_member_count + 1,
        aggregate_source_samples: sourceSamples,
        text: `${evidenceType} (${existing.aggregate_member_count + 1} visible targets)`,
      };
      continue;
    }
    groupIndexes.set(identity, grouped.length);
    grouped.push({
      ...control,
      identity,
      key: `q-map-evidence-group-${sha256(identity).slice(0, 12)}`,
      data_attributes: canonicalData,
      text: `${evidenceType} (1 visible target)`,
      aggregate_member_count: 1,
      aggregate_source_samples: sourceId ? [sourceId] : [],
    });
  }
  return grouped;
}

function sampleRepeatedSelectionControls(controls) {
  const families = new Map();
  controls.forEach((control, index) => {
    const data = control.data_attributes || {};
    const selectionSurface = Object.entries(data).find(([key, value]) => (
      /SelectionSurface$/.test(key) && value !== undefined && value !== ""
    ));
    if (!selectionSurface) return;
    const [selectionKey, selectionValue] = selectionSurface;
    const familyPayload = {
      route: control.route,
      context_id: control.context_id,
      tag: control.tag,
      role: control.role,
      delegated_to: control.delegated_to,
      disabled: control.disabled,
      selection_key: selectionKey,
      selection_value: selectionValue,
    };
    const familyIdentity = JSON.stringify(familyPayload);
    const member = {control, index, familyPayload, familyIdentity};
    families.set(familyIdentity, [...(families.get(familyIdentity) || []), member]);
  });
  const denseFamilyByMemberIndex = new Map();
  for (const members of families.values()) {
    if (members.length < 7) continue;
    for (const member of members) denseFamilyByMemberIndex.set(member.index, members);
  }
  const output = [];
  const emittedFamilies = new Set();
  controls.forEach((control, index) => {
    const members = denseFamilyByMemberIndex.get(index);
    if (!members) {
      output.push(control);
      return;
    }
    const familyIdentity = members[0].familyIdentity;
    if (emittedFamilies.has(familyIdentity)) return;
    emittedFamilies.add(familyIdentity);
    const middleIndex = Math.floor((members.length - 1) / 2);
    const representatives = [
      ["first", members[0]],
      ["middle", members[middleIndex]],
      ["last", members[members.length - 1]],
    ];
    const memberSamples = representatives.map(([_position, member]) => {
      const identifier = Object.entries(member.control.data_attributes || {})
        .find(([key, value]) => /Id$/.test(key) && value !== undefined && value !== "");
      return identifier ? String(identifier[1]) : member.control.aria_label || member.control.key;
    });
    for (const [position, member] of representatives) {
      const identity = JSON.stringify({
        ...member.familyPayload,
        representative_position: position,
      });
      output.push({
        ...member.control,
        identity,
        aggregate_member_count: members.length,
        aggregate_member_samples: memberSamples,
        aggregate_representative_position: position,
        aggregate_sampling_policy: "first-middle-last",
      });
    }
  });
  return output;
}

async function discoverVisibleControlsInFrame(frame, route, contextId) {
  const selector = browserActionContract.control_coverage.interactive_selector;
  const controls = await frame.evaluate(({interactiveSelector, currentRoute, currentContextId}) => {
    const nodes = [...document.querySelectorAll(interactiveSelector)];
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0;
    };
    const stableData = element => Object.fromEntries(
      Object.entries(element.dataset || {})
        .filter(([key]) => !/^scoutQualification/.test(key))
        .filter(([key]) => !/(?:state|status|selected|active|current|busy|loading|expanded)$/i.test(key))
        .sort(([left], [right]) => left.localeCompare(right)),
    );
    const hash = value => {
      let output = 2166136261;
      for (let index = 0; index < value.length; index += 1) {
        output ^= value.charCodeAt(index);
        output = Math.imul(output, 16777619);
      }
      return (output >>> 0).toString(16).padStart(8, "0");
    };
    return nodes.flatMap((element, ordinal) => {
      if (element.dataset.scoutQualificationCompleted === "true") return [];
      if (!visible(element)) return [];
      const dataAttributes = stableData(element);
      const text = String(element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 160);
      let delegatedTo = null;
      const isMapLibraryControl = Boolean(
        element.closest(".maplibregl-map, .maplibregl-control-container")
        || element.matches(".maplibregl-canvas, .maplibregl-ctrl, .maplibregl-ctrl-icon, .maplibregl-ctrl-attrib"),
      );
      if (element.matches("[data-route]")) delegatedTo = "runtime-route-navigation";
      if (isMapLibraryControl || element.matches("[data-map-control], [data-dashboard-map-viewport], [data-dashboard-map-hint-title], [data-evidence-type], [data-navigation-maplibre-fit], #map, #zoomIn, #zoomOut, #fitRoute, #panMode, #boxZoomMode, #panUp, #panDown, #panLeft, #panRight")) delegatedTo = "runtime-all-map-surface-interactions";
      if (element.matches("input[data-layer], [data-weather-layer-control], [data-layer-preset], [data-cwa-rainfall-product], [data-cwa-rainfall-opacity], [data-cwa-imagery-product], [data-cwa-imagery-window], [data-cwa-imagery-timeline], [data-cwa-imagery-opacity], [data-cwa-imagery-play]")) delegatedTo = "runtime-all-layer-toggle-integrity";
      if (element.matches("[data-diagnostic-action]")) delegatedTo = "diagnostic-controls";
      const hasStableIdentityAttributes = Boolean(
        element.id
        || element.getAttribute("name")
        || element.getAttribute("aria-label")
        || Object.keys(dataAttributes).length,
      );
      const stableIdentityText = hasStableIdentityAttributes ? "" : text;
      const identityPayload = {
        route: currentRoute,
        context_id: currentContextId,
        tag: element.tagName.toLowerCase(),
        id: element.id || "",
        name: element.getAttribute("name") || "",
        type: element.getAttribute("type") || "",
        role: element.getAttribute("role") || "",
        aria_label: element.getAttribute("aria-label") || "",
        data_attributes: dataAttributes,
        text: stableIdentityText,
      };
      const identity = JSON.stringify(identityPayload);
      const key = `q-${ordinal}-${hash(identity)}`;
      element.dataset.scoutQualificationControlKey = key;
      if (delegatedTo) element.dataset.scoutQualificationCompleted = "true";
      return [{
        ...identityPayload,
        text,
        identity,
        key,
        ordinal,
        delegated_to: delegatedTo,
        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
        aria_pressed: element.getAttribute("aria-pressed"),
        aria_selected: element.getAttribute("aria-selected"),
        aria_expanded: element.getAttribute("aria-expanded"),
        checked: "checked" in element ? Boolean(element.checked) : null,
        value: "value" in element ? String(element.value) : null,
        href: element instanceof HTMLAnchorElement ? element.href : null,
        target: element instanceof HTMLAnchorElement ? element.target : null,
      }];
    });
  }, {interactiveSelector: selector, currentRoute: route, currentContextId: contextId});
  return sampleRepeatedSelectionControls(
    aggregateDelegatedMapEvidenceControls(controls),
  );
}

async function discoverVisibleControls(page, route) {
  const controls = [];
  const frames = page.frames();
  for (let index = 0; index < frames.length; index += 1) {
    const frame = frames[index];
    const contextId = await frameContextId(page, frame, index);
    try {
      controls.push(...await discoverVisibleControlsInFrame(frame, route, contextId));
    } catch (error) {
      const detail = String(error?.message || error);
      if (isTransientFrameDiscoveryError(error)) continue;
      const identity = JSON.stringify({route, context_id: contextId, discovery_error: detail});
      controls.push({
        route,
        context_id: contextId,
        identity,
        key: `q-frame-error-${sha256(identity).slice(0, 12)}`,
        tag: "iframe",
        id: "",
        type: "",
        role: "",
        aria_label: "",
        data_attributes: {},
        text: "",
        delegated_to: null,
        disabled: false,
        discovery_error: detail,
      });
    }
  }
  return controls;
}

async function runVisibleControlDiscoveryWithTimeout(page, route, observations = null) {
  const startedAt = Date.now();
  let timeoutId = null;
  const discovery = discoverVisibleControls(page, route);
  discovery.catch(() => undefined);
  const timeout = new Promise((_resolve, reject) => {
    timeoutId = setTimeout(() => {
      const error = new Error(
        `Visible control discovery exceeded ${CONTROL_DISCOVERY_TIMEOUT_MS}ms`,
      );
      error.code = "CONTROL_DISCOVERY_TIMEOUT";
      reject(error);
    }, CONTROL_DISCOVERY_TIMEOUT_MS);
  });
  try {
    const controls = await Promise.race([discovery, timeout]);
    if (observations) {
      observations.controlStateTraces.push({
        kind: "control_discovery_timing",
        observed_at: new Date().toISOString(),
        route,
        duration_ms: Date.now() - startedAt,
        discovered_control_count: controls.length,
        context_count: new Set(controls.map(control => control.context_id)).size,
      });
    }
    return controls;
  } catch (error) {
    if (observations) {
      observations.controlStateTraces.push({
        kind: "control_discovery_timing",
        observed_at: new Date().toISOString(),
        route,
        duration_ms: Date.now() - startedAt,
        discovered_control_count: null,
        error_code: String(error?.code || "CONTROL_DISCOVERY_FAILURE"),
        error: String(error?.message || error),
      });
    }
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

async function locateControlContext(page, key) {
  for (const frame of page.frames()) {
    const locator = frame.locator(`[data-scout-qualification-control-key="${key}"]`).first();
    if (await locator.count()) return {frame, locator};
  }
  return null;
}

async function refreshControlDescriptor(page, route, descriptor) {
  const current = await locateControlContext(page, descriptor.key);
  if (current && await current.locator.isVisible()) {
    return {descriptor, ...current, refreshed: false};
  }
  const controls = await discoverVisibleControls(page, route);
  const refreshedDescriptor = controls.find(control => control.identity === descriptor.identity);
  if (!refreshedDescriptor) return null;
  const refreshed = await locateControlContext(page, refreshedDescriptor.key);
  if (!refreshed || !(await refreshed.locator.isVisible())) return null;
  return {
    descriptor: {...descriptor, ...refreshedDescriptor},
    ...refreshed,
    refreshed: true,
  };
}

async function classifyUncompletedControl(page, route, control, routeAbortedAfterOperationError) {
  if (routeAbortedAfterOperationError) {
    return controlCoverageGapRecord(control, "route_aborted_after_operation_error");
  }
  const refreshed = await refreshControlDescriptor(page, route, control);
  if (!refreshed) {
    return controlCoverageGapRecord(control, "disappeared_before_operation");
  }
  const availability = await refreshed.locator.evaluate(node => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return {
      visible: style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0,
      disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
    };
  });
  if (availability.disabled) {
    return controlCoverageGapRecord(
      {...control, ...refreshed.descriptor},
      "disabled_in_runtime_state",
    );
  }
  if (!availability.visible) {
    return controlCoverageGapRecord(
      {...control, ...refreshed.descriptor},
      "nonvisible_after_discovery",
    );
  }
  return {
    ...control,
    ...refreshed.descriptor,
    terminal_state: "UNMAPPED",
    coverage_gap_kind: "visible_unresolved_remainder",
    product_defect_claimed: false,
    detail: "A stable visible control remained after the state walk without an operation or an explicit delegation.",
  };
}

async function markControlCompleted(page, descriptor) {
  if (descriptor.aggregate_representative_position) return true;
  const located = await locateControlContext(page, descriptor.key);
  if (!located) return false;
  await located.locator.evaluate(node => {
    node.dataset.scoutQualificationCompleted = "true";
  }).catch(() => undefined);
  return true;
}

async function controlContextRoot(page, frame) {
  if (frame === page.mainFrame()) {
    const workspace = frame.locator("#workspace");
    if ((await workspace.count()) && (await workspace.isVisible())) return workspace;
  }
  return frame.locator("body");
}

async function controlSemanticState(page, frame, locator) {
  const element = await locator.evaluate(node => ({
    tag: node.tagName.toLowerCase(),
    id: node.id || "",
    type: node.getAttribute("type") || "",
    role: node.getAttribute("role") || "",
    aria_pressed: node.getAttribute("aria-pressed"),
    aria_selected: node.getAttribute("aria-selected"),
    aria_expanded: node.getAttribute("aria-expanded"),
    checked: "checked" in node ? Boolean(node.checked) : null,
    value: "value" in node ? String(node.value) : null,
    details_open: node.closest("details")?.open ?? null,
    text: String(node.textContent || "").trim().replace(/\s+/g, " ").slice(0, 160),
  }));
  const contextRoot = await controlContextRoot(page, frame);
  const workspaceSignature = await contextRoot.evaluate(node => {
    const value = node.outerHTML;
    let output = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
      output ^= value.charCodeAt(index);
      output = Math.imul(output, 16777619);
    }
    return `${(output >>> 0).toString(16)}:${value.length}`;
  });
  return {
    element,
    workspace_signature: workspaceSignature,
    url: page.url(),
    context_url: frame.url(),
  };
}

async function captureControlStateTrace(page, observations, route, phase, descriptor = {}) {
  if (!["outdoor-permission", "runtime-audit", "outdoor-weather", "emergency"].includes(route)) {
    return null;
  }
  let snapshot;
  try {
    snapshot = await page.evaluate(currentRoute => {
      const runtimeState = typeof state === "object" && state ? state : {};
      const visible = node => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== "none"
          && style.visibility !== "hidden"
          && Number(style.opacity || 1) > 0
          && rect.width > 0
          && rect.height > 0;
      };
      const safeFramePath = frame => {
        try {
          return new URL(frame.src, location.href).pathname;
        } catch (_error) {
          return "unresolved";
        }
      };
      const common = {
        visible_interactive_count: [...document.querySelectorAll("button, a[href], input, select, textarea, summary, [role=button], [role=tab]")].filter(visible).length,
      };
      if (currentRoute === "outdoor-permission") {
        return {
          ...common,
          permission_data_status: runtimeState.permissionDataStatus || null,
          selected_node_id: runtimeState.permissionSelectedNodeId || null,
          projection_status: runtimeState.permissionProjection?.status || null,
          visible_node_count: [...document.querySelectorAll("[data-permission-node]")].filter(visible).length,
          refresh_control_count: document.querySelectorAll("[data-permission-refresh]").length,
          loading_status_count: document.querySelectorAll('.permission-loading[role="status"]').length,
        };
      }
      if (currentRoute === "runtime-audit") {
        return {
          ...common,
          selected_date: runtimeState.runtimeAuditSelectedDate || null,
          selected_month: runtimeState.runtimeAuditSelectedMonth || null,
          payload_status: runtimeState.runtimeAuditStatus || runtimeState.runtimeAuditDataStatus || null,
          selected_day_control: document.querySelector('[data-runtime-audit-day][aria-pressed="true"]')?.dataset.runtimeAuditDay || null,
          selected_month_control: document.querySelector('[data-runtime-audit-month][aria-pressed="true"]')?.dataset.runtimeAuditMonth || null,
          rendered_event_count: document.querySelectorAll("[data-runtime-audit-event]").length,
          rendered_summary_count: document.querySelectorAll("[data-runtime-audit-summary]").length,
        };
      }
      if (currentRoute === "outdoor-weather") {
        const frames = [...document.querySelectorAll('iframe[data-weather-cwa-map-frame="true"]')];
        return {
          ...common,
          weather_frame_count: frames.length,
          weather_frames: frames.map(frame => ({
            connected: frame.isConnected,
            path: safeFramePath(frame),
            bridge_state: frame.dataset.weatherCwaFrameState || frame.parentElement?.querySelector("[data-weather-cwa-frame-state]")?.dataset.weatherCwaFrameState || null,
          })),
        };
      }
      const emergencyRoot = document.querySelector("[data-daily-emergency-review]");
      return {
        ...common,
        emergency_review_state: emergencyRoot?.dataset.dailyEmergencyReview || null,
        emergency_interactive_count: emergencyRoot
          ? [...emergencyRoot.querySelectorAll("button, a[href], input, select, textarea, summary, [role=button], [role=tab]")].filter(visible).length
          : 0,
      };
    }, route);
  } catch (error) {
    snapshot = {capture_error: String(error?.message || error)};
  }
  const record = {
    kind: "control_state",
    observed_at: new Date().toISOString(),
    route,
    phase,
    control_identity_sha256: descriptor.identity ? sha256(descriptor.identity) : null,
    control_key: descriptor.key || null,
    request_count: observations.requests.length,
    last_completed_request: observations.requests.at(-1) || null,
    snapshot,
  };
  observations.controlStateTraces.push(record);
  return record;
}

async function waitForIssue0063TerminalState(page, observations, route, phase) {
  const startedAt = Date.now();
  let terminalObserved = false;
  let waitError = null;
  try {
    await page.waitForFunction(currentRoute => {
      const runtimeState = typeof state === "object" && state ? state : {};
      if (currentRoute === "outdoor-permission") {
        return !["", "idle", "loading"].includes(String(runtimeState.permissionDataStatus || ""));
      }
      if (currentRoute === "runtime-audit") {
        return !["", "idle", "loading"].includes(String(runtimeState.runtimeAuditStatus || ""));
      }
      if (currentRoute === "outdoor-weather") {
        const frameState = document.querySelector("[data-weather-cwa-frame-state]")?.dataset.weatherCwaFrameState || "";
        return !["", "loading"].includes(frameState);
      }
      const emergencyState = document.querySelector("[data-daily-emergency-review]")?.dataset.dailyEmergencyReview || "";
      return !["", "loading"].includes(emergencyState);
    }, route, {timeout: 60_000});
    terminalObserved = true;
  } catch (error) {
    waitError = String(error?.message || error);
  }
  const record = {
    kind: "terminal_state_wait",
    observed_at: new Date().toISOString(),
    route,
    phase,
    terminal_observed: terminalObserved,
    duration_ms: Date.now() - startedAt,
    error: waitError,
  };
  observations.controlStateTraces.push(record);
  return record;
}

async function captureIssue0063RouteControlInventory(page, observations, route, phase) {
  const startedAt = Date.now();
  let inventory;
  try {
    inventory = await page.evaluate(currentRoute => {
      const visible = node => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== "none"
          && style.visibility !== "hidden"
          && Number(style.opacity || 1) > 0
          && rect.width > 0
          && rect.height > 0;
      };
      const routeSelectors = {
        "outdoor-permission": "[data-contextual-permission-workbench]",
        "runtime-audit": "[data-runtime-audit-page]",
        "outdoor-weather": "[data-weather-layer-control], [data-weather-cwa-map-frame], [data-weather-cwa-frame-state]",
        emergency: "[data-daily-emergency-review]",
      };
      const selector = routeSelectors[currentRoute];
      const roots = selector ? [...document.querySelectorAll(selector)] : [];
      const scopedRoots = roots.length ? roots : [document.body];
      const interactiveSelector = "button, a[href], input, select, textarea, summary, [role=button], [role=tab]";
      const controls = scopedRoots.flatMap(root => [
        ...(root.matches?.(interactiveSelector) ? [root] : []),
        ...root.querySelectorAll(interactiveSelector),
      ]);
      return {
        root_selector: selector || "body",
        root_count: roots.length,
        discovered_control_count: [...new Set(controls)].filter(visible).length,
        contextual_permission_node_count: document.querySelectorAll("[data-permission-node]").length,
        runtime_audit_day_count: document.querySelectorAll("[data-runtime-audit-day]").length,
        weather_layer_control_count: document.querySelectorAll("[data-weather-layer-control]").length,
        weather_frame_count: document.querySelectorAll("[data-weather-cwa-map-frame]").length,
        emergency_review_control_count: document.querySelectorAll("[data-daily-emergency-review] button, [data-daily-emergency-review] a[href], [data-daily-emergency-review] [role=tab]").length,
      };
    }, route);
  } catch (error) {
    inventory = {
      discovered_control_count: null,
      capture_error: String(error?.message || error),
    };
  }
  const record = {
    kind: "control_discovery_timing",
    observed_at: new Date().toISOString(),
    route,
    phase,
    discovery_strategy: "route_specific_main_document",
    duration_ms: Date.now() - startedAt,
    ...inventory,
  };
  observations.controlStateTraces.push(record);
  return record;
}

async function inspectIssue0063ControlStateEvidence(page, observations) {
  const routes = [
    "outdoor-permission",
    "runtime-audit",
    "outdoor-weather",
    "emergency",
  ];
  const routeEvidence = [];
  for (const route of routes) {
    const startedAt = Date.now();
    await openDashboard(page, observations.baseUrl, readyProjectId, route);
    const beforeReloadWait = await waitForIssue0063TerminalState(
      page,
      observations,
      route,
      "before_reload",
    );
    const beforeReload = await captureControlStateTrace(
      page,
      observations,
      route,
      "before_reload",
    );
    const controlsBeforeReload = await captureIssue0063RouteControlInventory(
      page,
      observations,
      route,
      "before_reload",
    );
    await captureControlStateTrace(
      page,
      observations,
      route,
      "after_discovery_before_reload",
    );
    await page.reload({waitUntil: "domcontentloaded", timeout: 60_000});
    recordBrowserAction(observations, "reload", `dashboard-route:${route}`);
    await page.locator(`[data-route="${route}"]`).first().waitFor({state: "attached", timeout: 60_000});
    const afterReloadWait = await waitForIssue0063TerminalState(
      page,
      observations,
      route,
      "after_reload",
    );
    const afterReload = await captureControlStateTrace(
      page,
      observations,
      route,
      "after_reload",
    );
    const controlsAfterReload = await captureIssue0063RouteControlInventory(
      page,
      observations,
      route,
      "after_reload",
    );
    routeEvidence.push({
      route,
      duration_ms: Date.now() - startedAt,
      before_reload_wait: beforeReloadWait,
      after_reload_wait: afterReloadWait,
      before_reload: beforeReload,
      after_reload: afterReload,
      discovered_before_reload: controlsBeforeReload.discovered_control_count,
      discovered_after_reload: controlsAfterReload.discovered_control_count,
    });
    recordBrowserAction(
      observations,
      "observe",
      `q0063-control-state:${route}`,
      "evidence_captured",
    );
  }
  assert(routeEvidence.length === routes.length, "Q0063 control-state evidence is incomplete.");
  return {
    evidence_only: true,
    product_behavior_changed: false,
    routes: routeEvidence,
  };
}

async function operateVisibleControl(page, observations, route, descriptor, operationIndex) {
  if (descriptor.discovery_error) {
    return {
      ...descriptor,
      terminal_state: "UNMAPPED",
      detail: `Interactive controls could not be inventoried in ${descriptor.context_id}: ${descriptor.discovery_error}`,
    };
  }
  if (descriptor.delegated_to) {
    return {...descriptor, terminal_state: "DELEGATED"};
  }
  let refreshedControl = await refreshControlDescriptor(page, route, descriptor);
  if (!refreshedControl) {
    await captureControlStateTrace(
      page,
      observations,
      route,
      "identity_missing_before_reload",
      descriptor,
    );
    appendCaseProgress(observations, "control_refresh_reload_started", {
      route,
      control_key: descriptor.key,
      control_identity: descriptor.identity,
    });
    await openDashboard(page, observations.baseUrl, readyProjectId, route);
    await page.waitForTimeout(500);
    await captureControlStateTrace(page, observations, route, "after_route_reload", descriptor);
    refreshedControl = await refreshControlDescriptor(page, route, descriptor);
  }
  if (!refreshedControl) {
    return {...descriptor, terminal_state: "MISSING_AFTER_RELOAD"};
  }
  descriptor = refreshedControl.descriptor;
  const {frame, locator} = refreshedControl;
  await locator.scrollIntoViewIfNeeded();
  const availability = await locator.evaluate(node => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return {
      visible: style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0,
      disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
      aria_pressed: node.getAttribute("aria-pressed"),
      aria_selected: node.getAttribute("aria-selected"),
    };
  });
  if (!availability.visible) {
    return controlCoverageGapRecord(descriptor, "nonvisible_after_discovery");
  }
  if (availability.disabled) {
    return controlCoverageGapRecord(descriptor, "disabled_in_runtime_state");
  }
  if (controlIdentityIsEffectful(descriptor)) {
    return {
      ...descriptor,
      terminal_state: "EFFECT_AUTHORIZATION_REQUIRED",
      detail: "Persistent, outbound, hardware, preparation, or generation action was not executed by the read-only qualification role.",
    };
  }
  if (
    (descriptor.role === "tab" && availability.aria_selected === "true")
    || availability.aria_pressed === "true"
  ) {
    return {
      ...descriptor,
      terminal_state: "GUARD_VERIFIED",
      detail: "The control was already in its active guarded state after sibling operations.",
    };
  }
  const contextRoot = await controlContextRoot(page, frame);
  const before = await controlSemanticState(page, frame, locator);
  await captureControlStateTrace(page, observations, route, "before_operation", descriptor);
  const beforeCheckpoint = await captureVisualCheckpoint(
    page,
    null,
    observations,
    `controls-${route}`,
    `${operationIndex}-before`,
    {fullPage: false, domRoot: contextRoot},
  );
  const requestCountBefore = observations.requests.length;
  let restore = null;
  let popupEffect = null;
  if (descriptor.tag === "input") {
    if (["checkbox", "radio"].includes(descriptor.type)) {
      await locator.click();
      restore = async () => locator.click().catch(() => undefined);
    } else if (descriptor.type === "range") {
      const key = await locator.evaluate(node => Number(node.value) < Number(node.max || node.value) ? "ArrowRight" : "ArrowLeft");
      await locator.press(key);
      restore = async () => locator.press(key === "ArrowRight" ? "ArrowLeft" : "ArrowRight").catch(() => undefined);
    } else if (descriptor.type === "file") {
      return {...descriptor, terminal_state: "EFFECT_AUTHORIZATION_REQUIRED", detail: "File input requires an explicitly approved real test artifact."};
    } else {
      const original = descriptor.value || "";
      const probe = descriptor.type === "number"
        ? await locator.evaluate(node => String(Math.min(Number(node.max || 999999), Math.max(Number(node.min || 0), Number(node.value || 0) + 1))))
        : `${original} qualification-probe`.trim();
      await locator.fill(probe);
      restore = async () => locator.fill(original).catch(() => undefined);
    }
  } else if (descriptor.tag === "textarea") {
    const original = descriptor.value || "";
    await locator.fill(`${original} qualification-probe`.trim());
    restore = async () => locator.fill(original).catch(() => undefined);
  } else if (descriptor.tag === "select") {
    const options = await locator.locator("option").evaluateAll(nodes => nodes.map(node => node.value));
    const alternate = options.find(value => value !== descriptor.value);
    if (alternate === undefined) {
      return controlCoverageGapRecord(descriptor, "single_runtime_value");
    }
    await locator.selectOption(alternate);
    restore = async () => locator.selectOption(descriptor.value).catch(() => undefined);
  } else if (descriptor.tag === "a") {
    if (!descriptor.href || /^(?:mailto|tel|javascript):/i.test(descriptor.href)) {
      return {...descriptor, terminal_state: "EFFECT_AUTHORIZATION_REQUIRED", detail: "Non-HTTP browser target requires explicit authorization."};
    }
    if (descriptor.target === "_blank") {
      const popupPromise = page.waitForEvent("popup", {timeout: 15_000}).catch(() => null);
      await locator.click();
      const popup = await popupPromise;
      if (popup) {
        await popup.waitForURL(url => isLoadedPopupUrl(url), {timeout: 60_000}).catch(() => undefined);
        await popup.waitForLoadState("domcontentloaded", {timeout: 60_000}).catch(() => undefined);
        const loadedPopup = isLoadedPopupUrl(popup.url());
        const popupUrl = (() => {
          try {
            const parsed = new URL(popup.url());
            return `${parsed.origin}${parsed.pathname}`;
          } catch (_error) {
            return "unresolved";
          }
        })();
        popupEffect = {
          popup_loaded: loadedPopup,
          popup_url: popupUrl,
        };
        await popup.close();
      } else {
        popupEffect = {popup_loaded: false, popup_url: null};
      }
    } else {
      const originalUrl = page.url();
      const originalContextUrl = frame.url();
      await locator.click();
      await page.waitForTimeout(500);
      if (page.url() !== originalUrl && frame === page.mainFrame()) {
        restore = async () => {
          await page.goBack({waitUntil: "domcontentloaded", timeout: 60_000}).catch(() => undefined);
        };
      } else if (frame.url() !== originalContextUrl) {
        restore = async () => {
          await openDashboard(page, observations.baseUrl, readyProjectId, route);
          await page.waitForTimeout(500);
        };
      }
    }
  } else if (
    descriptor.role === "button"
    && (
      descriptor.tag === "svg"
      || ["g", "circle", "path", "polygon", "polyline", "rect", "line"].includes(descriptor.tag)
    )
  ) {
    await locator.focus();
    await locator.press("Enter");
  } else {
    await locator.click({timeout: 30_000});
    if (descriptor.data_attributes?.route) {
      restore = async () => {
        await openDashboard(page, observations.baseUrl, readyProjectId, route);
        await page.waitForTimeout(500);
      };
    }
  }
  await page.waitForTimeout(500);
  const refreshed = await locateControlContext(page, descriptor.key);
  const afterRoot = refreshed
    ? await controlContextRoot(page, refreshed.frame)
    : page.locator("body");
  const after = refreshed
    ? await controlSemanticState(page, refreshed.frame, refreshed.locator)
    : {
        element: null,
        workspace_signature: await afterRoot.evaluate(node => `${node.innerHTML.length}:${node.textContent.length}`),
        url: page.url(),
      };
  await captureControlStateTrace(page, observations, route, "after_operation", descriptor);
  const afterCheckpoint = await captureVisualCheckpoint(
    page,
    null,
    observations,
    `controls-${route}`,
    `${operationIndex}-after`,
    {fullPage: false, domRoot: afterRoot},
  );
  const requestObserved = observations.requests.length > requestCountBefore;
  const semanticChanged = JSON.stringify(before) !== JSON.stringify(after)
    || requestObserved
    || popupEffect?.popup_loaded === true;
  const visualChanged = beforeCheckpoint.screenshot_sha256 !== afterCheckpoint.screenshot_sha256;
  const {
    baseline_visual_issues,
    new_visual_issues,
    resolved_visual_issues,
  } = visualIssueDelta(beforeCheckpoint.issues, afterCheckpoint.issues);
  const visualIssueEvidence = {
    baseline_visual_issues,
    new_visual_issues,
    resolved_visual_issues,
  };
  const effectOracle = {
    semantic_changed: semanticChanged,
    visual_changed: visualChanged,
    request_observed: requestObserved,
    popup_loaded: popupEffect?.popup_loaded ?? null,
    popup_url: popupEffect?.popup_url ?? null,
  };
  if (restore) await restore();
  const terminalState = controlOperationTerminalState(effectOracle);
  const visualQualityStatus = visualIssueEvidence.new_visual_issues.length
    ? "WARNING"
    : "PASS";
  recordBrowserAction(
    observations,
    "operate-control",
    `${route}:${descriptor.identity}`,
    terminalState,
    {
      before_screenshot: beforeCheckpoint.screenshot,
      after_screenshot: afterCheckpoint.screenshot,
      semantic_changed: semanticChanged,
      visual_changed: visualChanged,
      visual_quality_status: visualQualityStatus,
      effect_oracle: effectOracle,
    },
  );
  return {
    ...descriptor,
    terminal_state: terminalState,
    before,
    after,
    before_screenshot: beforeCheckpoint.screenshot,
    after_screenshot: afterCheckpoint.screenshot,
    semantic_changed: semanticChanged,
    visual_changed: visualChanged,
    visual_quality_status: visualQualityStatus,
    visual_issues: visualIssueEvidence.new_visual_issues,
    ...visualIssueEvidence,
    effect_oracle: effectOracle,
  };
}

async function runVisibleControlOperationWithTimeout(
  page,
  observations,
  route,
  descriptor,
  operationIndex,
) {
  let timeoutId = null;
  const operation = operateVisibleControl(
    page,
    observations,
    route,
    descriptor,
    operationIndex,
  );
  operation.catch(() => undefined);
  const timeout = new Promise((_resolve, reject) => {
    timeoutId = setTimeout(() => {
      const error = new Error(
        `Visible control operation exceeded ${CONTROL_OPERATION_TIMEOUT_MS}ms`,
      );
      error.code = "CONTROL_OPERATION_TIMEOUT";
      reject(error);
    }, CONTROL_OPERATION_TIMEOUT_MS);
  });
  try {
    return await Promise.race([operation, timeout]);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

async function auditAllVisibleControls(page, observations) {
  const inventory = [];
  observations.controlInventory = inventory;
  observations.segmentedTraces = [];
  const browserContext = page ? page.context() : observations._browserContext;
  assert(browserContext, "Visible-control audit requires a live browser context.");
  const routeTraceDirectory = path.join(observations.caseDirectory, "traces");
  fs.mkdirSync(routeTraceDirectory, {recursive: true});
  const blockingStates = new Set(
    browserActionContract.control_coverage.blocking_terminal_states,
  );
  const allowedStates = new Set(browserActionContract.control_coverage.allowed_terminal_states);
  const routes = browserActionContract.routes.map(item => item.id);
  let routeTracingAvailable = true;
  for (let routeIndex = 0; routeIndex < routes.length; routeIndex += 1) {
    const route = routes[routeIndex];
    const routeTracePath = path.join(routeTraceDirectory, `${safeCaseId(route)}.zip`);
    let routeTraceError = null;
    let routeTraceStarted = false;
    const routeInventoryStart = inventory.length;
    appendCaseProgress(observations, "route_started", {route, profile: "control-audit"});
    if (routeTracingAvailable) {
      try {
        await browserContext.tracing.start({screenshots: false, snapshots: false, sources: false});
        routeTraceStarted = true;
      } catch (error) {
        routeTraceError = error;
        routeTracingAvailable = false;
        appendCaseProgress(observations, "route_trace_start_failed", {
          route,
          error: String(error?.message || error),
        });
      }
    }
    try {
    const routePage = await browserContext.newPage();
    routePage.__scoutQualificationObservations = observations;
    attachQualificationPageObservers(routePage, observations);
    const completedIdentities = new Set();
    const discoveredIdentities = new Map();
    const deferredSelectedTabs = new Map();
    let operationIndex = 0;
    let routeAbortedAfterOperationError = false;
    const routeStartedAt = Date.now();
    try {
      await openDashboard(routePage, observations.baseUrl, readyProjectId, route);
      await routePage.waitForTimeout(500);
      while (true) {
        if (Date.now() - routeStartedAt > CONTROL_ROUTE_TIMEOUT_MS) {
          const error = new Error(
            `Visible control route audit exceeded ${CONTROL_ROUTE_TIMEOUT_MS}ms`,
          );
          error.code = "CONTROL_ROUTE_TIMEOUT";
          throw error;
        }
        const controls = await runVisibleControlDiscoveryWithTimeout(
          routePage,
          route,
          observations,
        );
        controls.forEach(control => discoveredIdentities.set(control.identity, control));
        const passiveControls = controls.filter(control => (
          !completedIdentities.has(control.identity)
          && (
            control.discovery_error
            || control.disabled
            || control.delegated_to
            || controlIdentityIsEffectful(control)
          )
        ));
        for (const control of passiveControls) {
          const result = classifyPassiveControl(control);
          inventory.push(result);
          completedIdentities.add(control.identity);
          await markControlCompleted(routePage, control);
        }
        if (passiveControls.length) observations.controlInventory = inventory;
        const candidate = controls.find(control => (
          !completedIdentities.has(control.identity)
          && !(control.role === "tab" && control.aria_selected === "true")
        ));
        if (!candidate) {
          for (const control of controls.filter(item => item.role === "tab" && item.aria_selected === "true")) {
            if (!completedIdentities.has(control.identity)) deferredSelectedTabs.set(control.identity, control);
          }
          break;
        }
        operationIndex += 1;
        let result;
        appendCaseProgress(observations, "control_operation_started", {
          route,
          operation_index: operationIndex,
          control_key: candidate.key,
          control_identity: candidate.identity,
        });
        try {
          result = await runVisibleControlOperationWithTimeout(
            routePage,
            observations,
            route,
            candidate,
            operationIndex,
          );
        } catch (error) {
          if (isTransientControlLocatorError(error)) {
            appendCaseProgress(observations, "control_operation_transient_retry", {
              route,
              operation_index: operationIndex,
              control_key: candidate.key,
              control_identity: candidate.identity,
              error: String(error?.message || error),
            });
            await openDashboard(routePage, observations.baseUrl, readyProjectId, route);
            await routePage.waitForTimeout(500);
            try {
              result = await runVisibleControlOperationWithTimeout(
                routePage,
                observations,
                route,
                candidate,
                operationIndex,
              );
            } catch (retryError) {
              error = retryError;
            }
          }
          if (result) {
            // A single fresh-route retry recovered an explicitly transient DOM race.
          } else {
          result = {
            ...candidate,
            terminal_state: "OPERATION_ERROR",
            detail: String(error?.message || error),
          };
          recordBrowserAction(
            observations,
            "operate-control",
            `${route}:${candidate.identity}`,
            "failed",
            {error: result.detail},
          );
          }
          if (
            error?.code === "CONTROL_OPERATION_TIMEOUT"
            || /(?:page|target|renderer).*(?:closed|crashed|unresponsive)/i.test(result.detail)
          ) {
            routeAbortedAfterOperationError = true;
          }
        }
        inventory.push(result);
        observations.controlInventory = inventory;
        completedIdentities.add(candidate.identity);
        appendCaseProgress(observations, "control_operation_completed", {
          route,
          operation_index: operationIndex,
          control_key: candidate.key,
          control_identity: candidate.identity,
          terminal_state: result.terminal_state,
        });
        await markControlCompleted(routePage, result);
        if (routeAbortedAfterOperationError) break;
        if (["MISSING_AFTER_RELOAD", "OPERATION_ERROR"].includes(result.terminal_state)) {
          try {
            await openDashboard(routePage, observations.baseUrl, readyProjectId, route);
            await routePage.waitForTimeout(500);
          } catch (error) {
            routeAbortedAfterOperationError = true;
            const identity = JSON.stringify({route, route_recovery_error: String(error)});
            inventory.push({
              route,
              context_id: "main",
              identity,
              key: `q-route-recovery-${sha256(identity).slice(0, 12)}`,
              terminal_state: "OPERATION_ERROR",
              detail: `route_aborted_after_operation_error: ${String(error?.message || error)}`,
            });
            observations.controlInventory = inventory;
            break;
          }
        }
      }
    } catch (error) {
      routeAbortedAfterOperationError = true;
      const identity = JSON.stringify({route, route_error: String(error)});
      inventory.push({
        route,
        context_id: "main",
        identity,
        key: `q-route-error-${sha256(identity).slice(0, 12)}`,
        terminal_state: "OPERATION_ERROR",
        detail: `route_aborted_after_operation_error: ${String(error?.message || error)}`,
      });
      observations.controlInventory = inventory;
    } finally {
      if (!routeAbortedAfterOperationError) {
        for (const control of deferredSelectedTabs.values()) {
          inventory.push({
            ...control,
            terminal_state: "GUARD_VERIFIED",
            detail: "The sole remaining selected tab state was visibly verified after sibling tab operations.",
          });
          observations.controlInventory = inventory;
          completedIdentities.add(control.identity);
        }
      }
      for (const [identity, control] of discoveredIdentities) {
        if (completedIdentities.has(identity)) continue;
        inventory.push(await classifyUncompletedControl(
          routePage,
          route,
          control,
          routeAbortedAfterOperationError,
        ));
        observations.controlInventory = inventory;
      }
      if (routeIndex === routes.length - 1) {
        await routePage.screenshot({
          path: path.join(observations.caseDirectory, "final.png"),
          type: "png",
          fullPage: true,
        }).catch(() => undefined);
      }
      await Promise.race([
        routePage.close({runBeforeUnload: false}).catch(() => undefined),
        new Promise(resolve => setTimeout(resolve, 10_000)),
      ]);
      appendCaseProgress(
        observations,
        routeAbortedAfterOperationError ? "route_failed" : "route_completed",
        {
          route,
          profile: "control-audit",
          control_count: inventory.length - routeInventoryStart,
        },
      );
    }
    } finally {
      if (routeTraceStarted) {
        appendCaseProgress(observations, "route_trace_stop_started", {route});
        try {
          await runCaseFinalizerWithTimeout(
            `route-trace-stop:${route}`,
            () => browserContext.tracing.stop({path: routeTracePath}),
            ROUTE_TRACE_FINALIZATION_TIMEOUT_MS,
          );
          observations.segmentedTraces.push(
            path.relative(observations.outputRoot, routeTracePath),
          );
          appendCaseProgress(observations, "route_trace_finalized", {route});
        } catch (error) {
          routeTraceError = error;
          routeTracingAvailable = false;
          appendCaseProgress(observations, "route_trace_finalization_failed", {
            route,
            error: String(error?.message || error),
          });
        }
      }
    }
    if (routeTraceError) {
      const identity = JSON.stringify({route, route_trace_error: String(routeTraceError)});
      inventory.push({
        route,
        context_id: "qualification-trace",
        identity,
        key: `q-route-trace-${sha256(identity).slice(0, 12)}`,
        terminal_state: "OPERATION_ERROR",
        detail: `route_trace_finalization_failed: ${String(routeTraceError?.message || routeTraceError)}`,
      });
      observations.controlInventory = inventory;
    }
  }
  const terminalStates = inventory.reduce((counts, item) => ({
    ...counts,
    [item.terminal_state]: (counts[item.terminal_state] || 0) + 1,
  }), {});
  const blocking = inventory.filter(item => (
    blockingStates.has(item.terminal_state)
    || (!allowedStates.has(item.terminal_state) && item.terminal_state !== "GUARD_VERIFIED")
  ));
  const visualIssueGroups = groupVisualQualityFindings(observations.visualCheckpoints);
  const coverageFailureSummary = summarizeControlCoverageFailure(
    blocking,
    visualIssueGroups,
  );
  observations.controlInventory = inventory;
  observations.controlCoverageBlocking = blocking;
  observations.controlVisualQualityFindings = visualIssueGroups;
  observations.controlCoverageFailureSummary = coverageFailureSummary;
  assert(
    blocking.length === 0 && visualIssueGroups.length === 0,
    `Visible control coverage is incomplete: ${JSON.stringify(coverageFailureSummary)}`,
  );
  return {
    routeCount: browserActionContract.routes.length,
    controlCount: inventory.length,
    terminalStates,
    blocking,
    visualIssueGroups,
    controlInventory: inventory,
  };
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

async function selectHoverableEvidenceCandidate(locator, label) {
  const candidateIndexes = await locator.evaluateAll(nodes => {
    const indexes = [];
    const visible = node => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0
        && rect.bottom > 0
        && rect.right > 0
        && rect.top < innerHeight
        && rect.left < innerWidth;
    };
    for (let index = nodes.length - 1; index >= 0 && indexes.length < 16; index -= 1) {
      const node = nodes[index];
      if (!visible(node)) continue;
      const rect = node.getBoundingClientRect();
      const points = [
        [.5, .5], [.25, .25], [.75, .75], [.25, .75], [.75, .25],
        [.5, .25], [.5, .75], [.25, .5], [.75, .5],
      ];
      const targetIsTopmost = points.some(([xRatio, yRatio]) => {
        const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width * xRatio));
        const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height * yRatio));
        const hit = document.elementFromPoint(x, y);
        const owner = hit?.closest?.("[data-dashboard-map-hint-title], [data-evidence-type]") || null;
        return owner === node || node.contains(owner);
      });
      if (targetIsTopmost) indexes.push(index);
    }
    return indexes;
  });
  assert(candidateIndexes.length > 0, `${label} has no topmost, target-specific hover candidate.`);
  return candidateIndexes.map(index => locator.nth(index));
}

async function hoverSelectedEvidence(page, locator, observations, label) {
  const candidates = await selectHoverableEvidenceCandidate(locator, label);
  const failures = [];
  for (const candidate of candidates) {
    try {
      const hover = await hoverRenderedEvidence(page, candidate, observations, label);
      return {locator: candidate, hover};
    } catch (error) {
      failures.push(String(error?.message || error));
    }
  }
  throw new Error(`${label} candidate hover attempts failed: ${failures.join(" | ")}`);
}

async function hoverRenderedEvidence(page, locator, observations, label) {
  const geometry = await locator.evaluate(node => {
    const source = typeof node.getTotalLength === "function"
      ? node
      : node.querySelector("path, polyline, polygon, circle, ellipse, line, rect");
    const rect = node.getBoundingClientRect();
    const candidates = [];
    if (source && typeof source.getTotalLength === "function" && source.getScreenCTM()) {
      const length = source.getTotalLength();
      for (const fraction of [.1, .25, .4, .5, .6, .75, .9]) {
        const point = source.getPointAtLength(length * fraction);
        const screen = new DOMPoint(point.x, point.y).matrixTransform(source.getScreenCTM());
        candidates.push({x: screen.x, y: screen.y});
      }
    }
    candidates.push(
      {x: rect.left + rect.width * .5, y: rect.top + rect.height * .5},
      {x: rect.left + rect.width * .25, y: rect.top + rect.height * .25},
      {x: rect.left + rect.width * .75, y: rect.top + rect.height * .75},
      {x: rect.left + rect.width * .25, y: rect.top + rect.height * .75},
      {x: rect.left + rect.width * .75, y: rect.top + rect.height * .25},
    );
    return {
      rect: {left: rect.left, top: rect.top},
      candidates,
    };
  });
  const box = await locator.boundingBox();
  assert(box, `${label} evidence has no browser bounding box.`);
  const interceptedBy = [];
  for (const candidate of geometry.candidates) {
    const pageX = box.x + candidate.x - geometry.rect.left;
    const pageY = box.y + candidate.y - geometry.rect.top;
    await page.mouse.move(pageX, pageY);
    await page.waitForTimeout(100);
    const hit = await locator.evaluate((node, point) => {
      const element = document.elementFromPoint(point.x, point.y);
      const owner = element?.closest?.("[data-dashboard-map-hint-title], [data-evidence-type]") || null;
      const targetHit = Boolean(owner && (owner === node || node.contains(owner)));
      const dashboardHintTarget = node.hasAttribute("data-dashboard-map-hint-title");
      return {
        evidence_hit: targetHit && (
          !dashboardHintTarget
          || node.getAttribute("aria-describedby") === "dashboardMapHoverHint"
        ),
        target_hit: targetHit,
        aria_describedby: node.getAttribute("aria-describedby"),
        evidence_owner: owner
          ? String(owner.getAttribute("data-dashboard-map-hint-title") || owner.getAttribute("data-evidence-type") || owner.tagName)
          : null,
        intercepted_by: element
          ? `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}${element.className?.baseVal ? `.${element.className.baseVal}` : ""}`
          : "none",
      };
    }, candidate);
    if (hit.evidence_hit) {
      recordBrowserAction(observations, "hover", label, "completed", {
        page_x: pageX,
        page_y: pageY,
        evidence_owner: hit.evidence_owner,
        aria_describedby: hit.aria_describedby,
      });
      return {page_x: pageX, page_y: pageY, evidence_owner: hit.evidence_owner};
    }
    interceptedBy.push(
      hit.target_hit && !hit.evidence_hit
        ? `${hit.intercepted_by}:missing-target-hint`
        : hit.intercepted_by,
    );
  }
  throw new Error(`${label} has no user-hoverable rendered geometry; intercepted by ${[...new Set(interceptedBy)].join(", ")}.`);
}

async function inspectNativeDynamicMap(page, observations, definition) {
  await openDashboard(page, observations.baseUrl, readyProjectId, definition.route);
  const viewport = page.locator(`[data-dashboard-map-viewport="${definition.viewportId}"]`).first();
  await viewport.waitFor({ state: "attached", timeout: 60_000 });
  await page.waitForTimeout(1000);
  await viewport.locator('[data-map-control="reset"]').click();
  recordBrowserAction(observations, "click", `${definition.label}:fit-reset`);
  const initial = await activeNativeTileState(viewport);
  assert(Number.isInteger(initial?.matrix), `${definition.label} has no active Fit matrix.`);
  const requestStart = observations.requests.length;
  await viewport.locator('[data-map-control="zoom-in"]').click();
  recordBrowserAction(observations, "click", `${definition.label}:zoom-in`);
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

async function inspectNavigationDynamicRudyTiles(page, observations) {
  const requestStart = observations.requests.length;
  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-navigation");
  const shell = page.locator('[data-navigation-maplibre-shell="2d"]:visible').first();
  await shell.waitFor({state: "visible", timeout: 120_000});
  const host = shell.locator('[data-navigation-maplibre-map="2d"]');
  await host.waitFor({state: "visible", timeout: 120_000});
  await page.waitForFunction(() => (
    document.querySelector('[data-navigation-maplibre-map="2d"]')
      ?.getAttribute("data-navigation-maplibre-status") === "ready"
  ), null, {timeout: 120_000});
  const fit = shell.locator('[data-navigation-maplibre-fit="2d"]');
  const zoomIn = shell.locator(".maplibregl-ctrl-zoom-in");
  assert(await fit.isVisible() && await zoomIn.isVisible(), "Navigation MapLibre Fit/zoom controls are incomplete.");
  await fit.click();
  recordBrowserAction(observations, "click", "Navigation Map:fit");
  await page.waitForTimeout(750);
  const initial = await navigationMapLibreState(host);
  assert(Number.isInteger(initial.tile_zoom), "Navigation MapLibre has no active Fit tile matrix.");
  await zoomIn.click();
  recordBrowserAction(observations, "click", "Navigation Map:zoom-in");
  const advanced = await waitForHigherMatrix(
    page,
    async () => {
      const state = await navigationMapLibreState(host);
      return {...state, matrix: state.tile_zoom};
    },
    initial.tile_zoom,
    "Navigation MapLibre",
  );
  const higherRequests = observations.requests
    .slice(requestStart)
    .filter(request => Number(request.rudyMatrix) > initial.tile_zoom);
  assert(
    higherRequests.some(request => request.status >= 200 && request.status < 300),
    `Navigation MapLibre has no successful native tile request above Z${initial.tile_zoom}.`,
  );
  return {
    initial: {...initial, matrix: initial.tile_zoom},
    advanced,
    higherRequests,
  };
}

async function inspectWeatherDynamicMap(page, observations) {
  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");
  const frame = page.frameLocator('[data-weather-cwa-map-frame="true"]');
  const group = frame.locator('[data-layer-group="rudy-twmap"]');
  await group.waitFor({ state: "attached", timeout: 120_000 });
  await frame.locator("#fitRoute").click();
  recordBrowserAction(observations, "click", "Weather Map:fit-route");
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
  recordBrowserAction(observations, "click", "Weather Map:zoom-in");
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

async function nativeMapState(viewport) {
  return viewport.evaluate(node => {
    const stage = node.querySelector("[data-dashboard-map-stage]");
    const policy = node.dataset.mapRenderPolicy || null;
    const tileImages = [...node.querySelectorAll('svg image[data-map-render-kind="tile"], [data-dashboard-rudy-tile]')]
      .filter(image => getComputedStyle(image).display !== "none");
    const approvedImages = [...node.querySelectorAll('svg image[data-map-render-kind="approved-single-image"]')]
      .filter(image => getComputedStyle(image).display !== "none");
    const vectors = [...node.querySelectorAll("svg path, svg polyline, svg polygon, svg circle, svg line")]
      .filter(element => getComputedStyle(element).display !== "none");
    const safeResourceUrl = value => {
      try {
        const parsed = new URL(value, location.href);
        return `${parsed.origin}${parsed.pathname}`;
      } catch (_error) {
        return "unresolved";
      }
    };
    const rawRasterSources = [...tileImages, ...approvedImages]
      .map(image => image.getAttribute("href") || image.getAttribute("xlink:href") || "")
      .filter(Boolean);
    const resourceEntries = performance.getEntriesByType("resource")
      .filter(entry => rawRasterSources.some(source => entry.name === source || entry.name.endsWith(source)))
      .slice(-24)
      .map(entry => ({
        name: safeResourceUrl(entry.name),
        duration_ms: entry.duration,
        transfer_size: entry.transferSize,
      }));
    return {
      selector_identity: node.getAttribute("data-dashboard-map-viewport") || node.id || null,
      zoom: Number(node.dataset.mapZoom),
      mode: node.dataset.mapMode || null,
      last_gesture: node.dataset.mapLastGesture || null,
      dragging: node.dataset.mapDragging || null,
      stage_transform: stage?.style.transform || null,
      render_policy: policy,
      render_policy_status: node.dataset.mapRenderPolicyStatus || null,
      blocked_image_count: Number(node.dataset.mapRenderPolicyBlockedImageCount || 0),
      tile_count: tileImages.length,
      approved_single_image_count: approvedImages.length,
      vector_count: vectors.length,
      raster_sources: rawRasterSources.map(safeResourceUrl),
      resource_entries: resourceEntries,
      tile_load_state: node.dataset.dashboardTileLoadState || null,
      width: node.getBoundingClientRect().width,
      height: node.getBoundingClientRect().height,
    };
  });
}

async function browserObservedRasterProvenance(
  page,
  observations,
  requestStart,
  states,
  label,
) {
  const successfulResponses = observations.requests
    .slice(requestStart)
    .filter(request => Number.isInteger(request.rudyMatrix))
    .filter(request => request.status >= 200 && request.status < 300);
  const resourceEntries = states
    .flatMap(state => state?.resource_entries || [])
    .filter(entry => entry?.name);
  const rasterSources = states
    .flatMap(state => state?.raster_sources || [])
    .filter(Boolean);
  const tileLoadStates = states
    .map(state => state?.tile_load_state)
    .filter(Boolean);
  const readyTilesRendered = states.some(state => (
    state?.tile_load_state === "ready"
    && Number(state?.tile_count || 0) > 0
  ));
  let cacheVerification = null;
  if (!successfulResponses.length && readyTilesRendered) {
    const source = resourceEntries[0]?.name || rasterSources[0] || null;
    if (source) {
      cacheVerification = await page.evaluate(async resourceUrl => {
        try {
          const response = await fetch(resourceUrl, {
            cache: "force-cache",
            credentials: "same-origin",
          });
          await response.arrayBuffer();
          return {
            ok: response.ok,
            status: response.status,
            url: response.url,
          };
        } catch (error) {
          return {
            ok: false,
            status: null,
            url: resourceUrl,
            error: String(error?.message || error),
          };
        }
      }, source);
      recordBrowserAction(
        observations,
        "verify-raster-provenance",
        label,
        cacheVerification.ok ? "completed" : "failed",
        {
          status: cacheVerification.status,
          cache_path: true,
        },
      );
    }
  }
  const browserObservedCount = successfulResponses.length + (cacheVerification?.ok ? 1 : 0);
  return {
    browser_observed_count: browserObservedCount,
    network_response_count: successfulResponses.length,
    resource_entries: resourceEntries,
    raster_sources: rasterSources,
    tile_load_states: tileLoadStates,
    cache_verification: cacheVerification,
  };
}

async function prepareMapSurfaceForBrowserOperation(page, observations, surface) {
  const operations = [];
  if (surface.id === "emergency-review-map") {
    const evidenceTab = page.locator('[data-emergency-review-view="evidence"]').first();
    await evidenceTab.waitFor({state: "visible", timeout: 120_000});
    if ((await evidenceTab.getAttribute("aria-selected")) !== "true") {
      await evidenceTab.click();
      recordBrowserAction(observations, "click", `${surface.id}:reveal-evidence-view`);
      operations.push("reveal-emergency-evidence-view");
    }
    await page.waitForFunction(() => (
      typeof state !== "undefined" && state.emergencyReviewView === "evidence"
    ), null, {timeout: 60_000});
  }
  return operations;
}

async function captureMapFailureCheckpoint(page, observations, surface, slug = "failure") {
  try {
    const captureRoot = page.locator("body");
    await captureRoot.waitFor({state: "visible", timeout: 30_000});
    return await captureVisualCheckpoint(
      page,
      null,
      observations,
      `maps-${surface.id}`,
      slug,
      {fullPage: false, domRoot: captureRoot},
    );
  } catch (error) {
    return {
      id: `maps-${surface.id}:${slug}`,
      capture_error: String(error?.message || error),
    };
  }
}

async function inspectNativeMapGestures(page, observations, surface) {
  const requestStart = observations.requests.length;
  await openDashboard(page, observations.baseUrl, readyProjectId, surface.route);
  const preparationOperations = await prepareMapSurfaceForBrowserOperation(page, observations, surface);
  const viewport = page.locator(`[data-dashboard-map-viewport="${surface.viewport_id}"]`).first();
  await viewport.waitFor({ state: "attached", timeout: 60_000 });
  await revealThroughClosedDetails(page, viewport, observations, `map-${surface.id}`);
  await viewport.waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForTimeout(1000);
  const controls = viewport.locator("[data-map-control]");
  const controlNames = await controls.evaluateAll(nodes => nodes.map(node => node.dataset.mapControl));
  assert(
    JSON.stringify(controlNames.sort()) === JSON.stringify(["box-zoom", "pan", "reset", "zoom-in", "zoom-out"].sort()),
    `${surface.id} map controls are incomplete: ${JSON.stringify(controlNames)}`,
  );
  const checkpoints = [];
  const initial = await nativeMapState(viewport);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "initial"));
  assert(initial.width > 0 && initial.height > 0, `${surface.id} is not visibly rendered.`);
  assert(initial.render_policy === browserActionContract.required_map_content.render_policy, `${surface.id} render policy is missing.`);
  assert(initial.render_policy_status === "verified", `${surface.id} render policy is ${initial.render_policy_status}.`);
  assert(initial.blocked_image_count === 0, `${surface.id} contains unapproved single-image map content.`);
  assert(initial.vector_count > 0, `${surface.id} contains no visible vector content.`);
  assert(initial.tile_count + initial.approved_single_image_count > 0, `${surface.id} contains neither tiles nor an approved single image.`);

  await viewport.locator('[data-map-control="zoom-in"]').click();
  recordBrowserAction(observations, "click", `${surface.id}:fit-setup-zoom-in`);
  await page.waitForTimeout(500);
  const fitBefore = await nativeMapState(viewport);
  assert(fitBefore.zoom > initial.zoom, `${surface.id} Fit setup did not leave the initial extent.`);
  const fitBeforeCheckpoint = await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "fit-before");
  checkpoints.push(fitBeforeCheckpoint);
  await viewport.locator('[data-map-control="reset"]').click();
  recordBrowserAction(observations, "click", `${surface.id}:fit`);
  await page.waitForTimeout(500);
  const fitted = await nativeMapState(viewport);
  assert(Math.abs(fitted.zoom - 1) < .001, `${surface.id} Fit did not reset zoom: ${fitted.zoom}`);
  const fitAfterCheckpoint = await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "fit-after");
  assert(fitBeforeCheckpoint.screenshot_sha256 !== fitAfterCheckpoint.screenshot_sha256, `${surface.id} Fit changed state without a visible map change.`);
  checkpoints.push(fitAfterCheckpoint);

  await viewport.locator('[data-map-control="zoom-in"]').click();
  recordBrowserAction(observations, "click", `${surface.id}:zoom-in`);
  await page.waitForTimeout(750);
  const zoomedIn = await nativeMapState(viewport);
  assert(zoomedIn.zoom > fitted.zoom, `${surface.id} zoom-in did not increase zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "zoom-in"));

  await viewport.locator('[data-map-control="zoom-out"]').click();
  recordBrowserAction(observations, "click", `${surface.id}:zoom-out`);
  await page.waitForTimeout(500);
  const zoomedOut = await nativeMapState(viewport);
  assert(zoomedOut.zoom < zoomedIn.zoom, `${surface.id} zoom-out did not decrease zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "zoom-out"));

  await viewport.locator('[data-map-control="zoom-in"]').click();
  await viewport.locator('[data-map-control="zoom-in"]').click();
  await viewport.locator('[data-map-control="pan"]').click();
  const panBefore = await nativeMapState(viewport);
  const panBox = await viewport.boundingBox();
  assert(panBox && panBox.width >= 160 && panBox.height >= 160, `${surface.id} is too small for mouse pan.`);
  await page.mouse.move(panBox.x + panBox.width * .5, panBox.y + panBox.height * .5);
  await page.mouse.down();
  await page.mouse.move(panBox.x + panBox.width * .65, panBox.y + panBox.height * .62, {steps: 8});
  await page.mouse.up();
  recordBrowserAction(observations, "mouse-drag", `${surface.id}:pan`);
  await page.waitForTimeout(300);
  const panned = await nativeMapState(viewport);
  assert(panned.mode === "pan", `${surface.id} mouse pan did not remain in pan mode.`);
  assert(panned.stage_transform !== panBefore.stage_transform, `${surface.id} mouse drag did not pan the map.`);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "mouse-pan"));

  await viewport.focus();
  const keyboardBefore = await nativeMapState(viewport);
  await viewport.press("ArrowRight");
  recordBrowserAction(observations, "keyboard", `${surface.id}:ArrowRight`);
  await page.waitForTimeout(250);
  const keyboardPanned = await nativeMapState(viewport);
  assert(keyboardPanned.stage_transform !== keyboardBefore.stage_transform, `${surface.id} keyboard pan did not move the map.`);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "keyboard-pan"));

  await viewport.locator('[data-map-control="reset"]').click();
  await viewport.locator('[data-map-control="box-zoom"]').click();
  const boxControlPressed = await viewport.locator('[data-map-control="box-zoom"]').getAttribute("aria-pressed");
  assert(boxControlPressed === "true", `${surface.id} rectangle zoom mode did not activate.`);
  const box = await viewport.boundingBox();
  assert(box && box.width >= 180 && box.height >= 180, `${surface.id} is too small for rectangle zoom.`);
  await page.mouse.move(box.x + box.width * .2, box.y + box.height * .2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .68, box.y + box.height * .72, {steps: 10});
  await page.mouse.up();
  recordBrowserAction(observations, "rectangle-drag", `${surface.id}:box-zoom`);
  await page.waitForTimeout(750);
  const rectangleZoomed = await nativeMapState(viewport);
  assert(rectangleZoomed.mode === "box", `${surface.id} rectangle zoom did not remain active.`);
  assert(rectangleZoomed.last_gesture === "rectangle-zoom-in", `${surface.id} did not record rectangle zoom.`);
  assert(rectangleZoomed.zoom > 1, `${surface.id} rectangle zoom did not increase zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "rectangle-zoom"));

  await viewport.locator('[data-map-control="reset"]').click();
  recordBrowserAction(observations, "click", `${surface.id}:evidence-hover-fit-reset`);
  await page.waitForTimeout(500);
  const evidenceTargets = viewport.locator("[data-dashboard-map-hint-title]");
  assert(await evidenceTargets.count(), `${surface.id} has no hoverable map evidence.`);
  await page.evaluate(() => {
    if (typeof hideDashboardMapHint === "function") hideDashboardMapHint();
  });
  const hint = page.locator("#dashboardMapHoverHint");
  assert(await hint.isHidden(), `${surface.id} inherited a visible hint before target hover.`);
  const hintBeforeCheckpoint = await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "evidence-hint-before");
  checkpoints.push(hintBeforeCheckpoint);
  const selectedEvidence = await hoverSelectedEvidence(
    page,
    evidenceTargets,
    observations,
    `${surface.id}:evidence-hint`,
  );
  const evidenceTarget = selectedEvidence.locator;
  const targetHintSource = await evidenceTarget.getAttribute("data-dashboard-map-hint-source") || "evidence";
  await page.waitForTimeout(200);
  const hintAfterCheckpoint = await captureVisualCheckpoint(page, viewport, observations, `maps-${surface.id}`, "evidence-hint-after");
  checkpoints.push(hintAfterCheckpoint);
  assert(await hint.isVisible(), `${surface.id} evidence hover hint is not visible.`);
  assert((await hint.textContent() || "").trim().length > 0, `${surface.id} evidence hover hint is empty.`);
  const target_hint_source = await hint.getAttribute("data-hint-source");
  assert(target_hint_source === targetHintSource, `${surface.id} displayed a hint from ${target_hint_source} instead of ${targetHintSource}.`);
  assert(await evidenceTarget.getAttribute("aria-describedby") === "dashboardMapHoverHint", `${surface.id} hint is not bound to the hovered evidence target.`);
  assert(hintBeforeCheckpoint.screenshot_sha256 !== hintAfterCheckpoint.screenshot_sha256, `${surface.id} hint became semantic-only without visible evidence.`);

  const rasterProvenance = await browserObservedRasterProvenance(
    page,
    observations,
    requestStart,
    [initial, fitBefore, fitted, zoomedIn, zoomedOut, panned, keyboardPanned, rectangleZoomed],
    `${surface.id}:rendered-raster`,
  );
  assert(
    rasterProvenance.browser_observed_count > 0,
    `${surface.id} displayed tiles without a successful browser-observed raster request.`,
  );
  const visualIssues = checkpoints.flatMap(checkpoint => checkpoint.issues);
  assert(visualIssues.length === 0, `${surface.id} visual quality failed: ${JSON.stringify(visualIssues)}`);
  const finalRenderState = await nativeMapState(viewport);
  return {
    surface_id: surface.id,
    route: surface.route,
    kind: surface.kind,
    preparation_operations: preparationOperations,
    gestures: browserActionContract.required_map_gestures,
    initial,
    fit_before: fitBefore,
    fitted,
    zoomed_in: zoomedIn,
    zoomed_out: zoomedOut,
    mouse_panned: panned,
    keyboard_panned: keyboardPanned,
    rectangle_zoomed: rectangleZoomed,
    hover_hint_visible: true,
    target_hint_source,
    successful_raster_request_count: rasterProvenance.network_response_count,
    browser_observed_raster_provenance_count: rasterProvenance.browser_observed_count,
    raster_resource_entries: rasterProvenance.resource_entries,
    raster_tile_load_states: rasterProvenance.tile_load_states,
    raster_cache_verification: rasterProvenance.cache_verification,
    final_render_state: finalRenderState,
    final_screenshot: hintAfterCheckpoint.screenshot,
    checkpoints,
  };
}

async function navigationMapLibreState(host) {
  return host.evaluate(node => {
    const canvas = node.querySelector("canvas.maplibregl-canvas");
    const rect = canvas?.getBoundingClientRect();
    return {
      selector_identity: node.getAttribute("data-navigation-maplibre-map"),
      status: node.dataset.navigationMaplibreStatus || null,
      zoom: Number(node.dataset.navigationMaplibreZoom),
      center: node.dataset.navigationMaplibreCenter || null,
      pitch: Number(node.dataset.navigationMaplibrePitch),
      bearing: Number(node.dataset.navigationMaplibreBearing),
      tile_zoom: Number(node.dataset.dashboardTileZoom),
      basemap_layer: node.dataset.dashboardBasemapLayer || null,
      basemap_policy: node.dataset.dashboardBasemapPolicy || null,
      canvas_present: Boolean(canvas),
      canvas_width: rect?.width || 0,
      canvas_height: rect?.height || 0,
    };
  });
}

async function inspectNavigationMapLibreGestures(page, observations, surface) {
  const requestStart = observations.requests.length;
  await openDashboard(page, observations.baseUrl, readyProjectId, surface.route);
  const shell = page.locator('[data-navigation-maplibre-shell="2d"]').first();
  await shell.waitFor({state: "visible", timeout: 120_000});
  const host = shell.locator('[data-navigation-maplibre-map="2d"]');
  await host.waitFor({state: "visible", timeout: 120_000});
  await page.waitForFunction(() => (
    document.querySelector('[data-navigation-maplibre-map="2d"]')
      ?.getAttribute("data-navigation-maplibre-status") === "ready"
  ), null, {timeout: 120_000});
  const canvas = host.locator("canvas.maplibregl-canvas");
  await canvas.waitFor({state: "visible", timeout: 60_000});
  const checkpoints = [];
  const initial = await navigationMapLibreState(host);
  assert(initial.canvas_present && initial.canvas_width >= 180 && initial.canvas_height >= 180, "navigation-map MapLibre canvas is not visibly rendered.");
  assert(initial.basemap_policy === "rudy-twmap-only", "navigation-map MapLibre basemap policy is not Rudy+TW-only.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "initial"));

  const zoomIn = shell.locator(".maplibregl-ctrl-zoom-in");
  const zoomOut = shell.locator(".maplibregl-ctrl-zoom-out");
  const fit = shell.locator('[data-navigation-maplibre-fit="2d"]');
  assert(await zoomIn.isVisible() && await zoomOut.isVisible() && await fit.isVisible(), "navigation-map MapLibre zoom/Fit controls are incomplete.");
  await zoomIn.click();
  await zoomIn.click();
  recordBrowserAction(observations, "click-sequence", "navigation-map:fit-setup-zoom-in");
  await page.waitForTimeout(750);
  const fitBefore = await navigationMapLibreState(host);
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "fit-before"));
  await fit.click();
  recordBrowserAction(observations, "click", "navigation-map:fit");
  await page.waitForTimeout(750);
  const fitted = await navigationMapLibreState(host);
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "fit-after"));
  assert(fitBefore.zoom > fitted.zoom, "navigation-map MapLibre Fit did not restore the fitted extent.");

  await zoomIn.click();
  recordBrowserAction(observations, "click", "navigation-map:zoom-in");
  await page.waitForTimeout(750);
  const zoomedIn = await navigationMapLibreState(host);
  assert(zoomedIn.zoom > fitted.zoom, "navigation-map MapLibre zoom-in did not increase zoom.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "zoom-in"));
  await zoomOut.click();
  recordBrowserAction(observations, "click", "navigation-map:zoom-out");
  await page.waitForTimeout(750);
  const zoomedOut = await navigationMapLibreState(host);
  assert(zoomedOut.zoom < zoomedIn.zoom, "navigation-map MapLibre zoom-out did not decrease zoom.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "zoom-out"));

  await zoomIn.click();
  const panBefore = await navigationMapLibreState(host);
  const canvasBox = await canvas.boundingBox();
  assert(canvasBox, "navigation-map MapLibre canvas has no browser bounding box.");
  await page.mouse.move(canvasBox.x + canvasBox.width * .5, canvasBox.y + canvasBox.height * .5);
  await page.mouse.down();
  await page.mouse.move(canvasBox.x + canvasBox.width * .65, canvasBox.y + canvasBox.height * .62, {steps: 8});
  await page.mouse.up();
  recordBrowserAction(observations, "mouse-drag", "navigation-map:pan");
  await page.waitForTimeout(750);
  const mousePanned = await navigationMapLibreState(host);
  assert(mousePanned.center !== panBefore.center, "navigation-map MapLibre mouse drag did not pan.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "mouse-pan"));

  await canvas.focus();
  const keyboardBefore = await navigationMapLibreState(host);
  await canvas.press("ArrowRight");
  recordBrowserAction(observations, "keyboard", "navigation-map:ArrowRight");
  await page.waitForTimeout(750);
  const keyboardPanned = await navigationMapLibreState(host);
  assert(keyboardPanned.center !== keyboardBefore.center, "navigation-map MapLibre keyboard pan did not move.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "keyboard-pan"));

  await fit.click();
  await page.waitForTimeout(500);
  const rectangleBefore = await navigationMapLibreState(host);
  await page.keyboard.down("Shift");
  try {
    await page.mouse.move(canvasBox.x + canvasBox.width * .2, canvasBox.y + canvasBox.height * .2);
    await page.mouse.down();
    await page.mouse.move(canvasBox.x + canvasBox.width * .68, canvasBox.y + canvasBox.height * .72, {steps: 10});
    await page.mouse.up();
  } finally {
    await page.keyboard.up("Shift");
  }
  recordBrowserAction(observations, "rectangle-drag", "navigation-map:box-zoom");
  await page.waitForTimeout(1000);
  const rectangleZoomed = await navigationMapLibreState(host);
  assert(rectangleZoomed.zoom > rectangleBefore.zoom, "navigation-map MapLibre Shift+drag rectangle zoom did not increase zoom.");
  checkpoints.push(await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "rectangle-zoom"));

  await fit.click();
  await page.waitForTimeout(500);
  const evidenceTargets = shell.locator("[data-dashboard-map-hint-title]");
  assert(await evidenceTargets.count(), "navigation-map MapLibre surface exposes no hoverable evidence hint target.");
  const hintBefore = await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "evidence-hint-before");
  checkpoints.push(hintBefore);
  const selectedEvidence = await hoverSelectedEvidence(
    page,
    evidenceTargets,
    observations,
    "navigation-map:evidence-hint",
  );
  await page.waitForTimeout(200);
  const hint = page.locator("#dashboardMapHoverHint");
  const hintAfter = await captureVisualCheckpoint(page, shell, observations, "maps-navigation-map", "evidence-hint-after");
  checkpoints.push(hintAfter);
  assert(await hint.isVisible(), "navigation-map MapLibre evidence hover hint is not visible.");
  assert(await selectedEvidence.locator.getAttribute("aria-describedby") === "dashboardMapHoverHint", "navigation-map MapLibre hint is not bound to its hovered target.");
  assert(hintBefore.screenshot_sha256 !== hintAfter.screenshot_sha256, "navigation-map MapLibre hint produced no visible change.");

  const visualIssues = checkpoints.flatMap(checkpoint => checkpoint.issues);
  assert(visualIssues.length === 0, `navigation-map MapLibre visual quality failed: ${JSON.stringify(visualIssues)}`);
  const successfulRequests = observations.requests.slice(requestStart).filter(request => (
    request.status >= 200 && request.status < 300
  ));
  return {
    surface_id: surface.id,
    route: surface.route,
    kind: "maplibre-native",
    gestures: browserActionContract.required_map_gestures,
    initial,
    fit_before: fitBefore,
    fitted,
    zoomed_in: zoomedIn,
    zoomed_out: zoomedOut,
    mouse_panned: mousePanned,
    keyboard_panned: keyboardPanned,
    rectangle_zoomed: rectangleZoomed,
    hover_hint_visible: true,
    successful_response_count: successfulRequests.length,
    final_render_state: await navigationMapLibreState(host),
    final_screenshot: hintAfter.screenshot,
    checkpoints,
  };
}

async function embeddedMapState(frame) {
  return frame.locator("#map").evaluate(node => {
    const rasterNodes = [...document.querySelectorAll(
      '#map image[data-map-tile-source], #map image[data-map-render-kind="tile"], #map image[data-map-render-kind="approved-single-image"]',
    )];
    const safeResourceUrl = value => {
      try {
        const parsed = new URL(value, location.href);
        return `${parsed.origin}${parsed.pathname}`;
      } catch (_error) {
        return "unresolved";
      }
    };
    const rawRasterSources = rasterNodes
      .map(image => image.getAttribute("href") || image.getAttribute("xlink:href") || "")
      .filter(Boolean);
    return {
      selector_identity: node.id || "map",
      zoom: Number(state.zoom),
      pan_x: Number(state.panX),
      pan_y: Number(state.panY),
      mode: state.mapInteractionMode,
      vector_count: document.querySelectorAll("#map path, #map polyline, #map polygon, #map circle, #map ellipse, #map line, #map rect, #map use").length,
      tile_count: document.querySelectorAll('#map image[data-map-tile-source], #map image[data-map-render-kind="tile"]').length,
      approved_single_image_count: document.querySelectorAll('#map image[data-map-render-kind="approved-single-image"]').length,
      visible_layer_count: [...document.querySelectorAll("#map [data-layer-group]")]
        .filter(layer => layer.dataset.layerHidden !== "true" && getComputedStyle(layer).display !== "none").length,
      raster_sources: rawRasterSources.map(safeResourceUrl),
      resource_entries: performance.getEntriesByType("resource")
        .filter(entry => rawRasterSources.some(source => entry.name === source || entry.name.endsWith(source)))
        .slice(-24)
        .map(entry => ({
          name: safeResourceUrl(entry.name),
          duration_ms: entry.duration,
          transfer_size: entry.transferSize,
        })),
    };
  });
}

async function inspectEmbeddedMapGestures(page, observations, surface) {
  const requestStart = observations.requests.length;
  await openDashboard(page, observations.baseUrl, readyProjectId, surface.route);
  const preparationOperations = await prepareMapSurfaceForBrowserOperation(page, observations, surface);
  const frameElement = page.locator(surface.frame_selector);
  await frameElement.waitFor({ state: "visible", timeout: 120_000 });
  const frame = page.frameLocator(surface.frame_selector);
  const map = frame.locator("#map");
  await map.waitFor({ state: "visible", timeout: 120_000 });
  await frame.locator('#map[data-map-render-policy-status="verified"]').waitFor({state: "visible", timeout: 120_000});
  await frame.locator("#zoomIn").click();
  recordBrowserAction(observations, "click", `${surface.id}:fit-setup-zoom-in`);
  await page.waitForTimeout(500);
  const fitBefore = await embeddedMapState(frame);
  const fitBeforeCheckpoint = await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "fit-before");
  await frame.locator("#fitRoute").click();
  recordBrowserAction(observations, "click", `${surface.id}:fit`);
  await page.waitForTimeout(500);
  const fitted = await embeddedMapState(frame);
  const fitAfterCheckpoint = await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "fit-after");
  const checkpoints = [fitBeforeCheckpoint, fitAfterCheckpoint];
  assert(fitBefore.zoom > fitted.zoom, `${surface.id} Fit setup did not leave the fitted extent.`);
  assert(Math.abs(fitted.zoom - 1) < .001, `${surface.id} Fit did not reset zoom.`);
  assert(fitBeforeCheckpoint.screenshot_sha256 !== fitAfterCheckpoint.screenshot_sha256, `${surface.id} Fit changed state without a visible map change.`);
  assert(fitted.vector_count > 0, `${surface.id} contains no vector content.`);
  assert(fitted.tile_count + fitted.approved_single_image_count > 0, `${surface.id} contains no tile or approved single image.`);

  await frame.locator("#zoomIn").click();
  recordBrowserAction(observations, "click", `${surface.id}:zoom-in`);
  await page.waitForTimeout(750);
  const zoomedIn = await embeddedMapState(frame);
  assert(zoomedIn.zoom > fitted.zoom, `${surface.id} zoom-in did not increase zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "zoom-in"));

  await frame.locator("#zoomOut").click();
  recordBrowserAction(observations, "click", `${surface.id}:zoom-out`);
  await page.waitForTimeout(500);
  const zoomedOut = await embeddedMapState(frame);
  assert(zoomedOut.zoom < zoomedIn.zoom, `${surface.id} zoom-out did not decrease zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "zoom-out"));

  await frame.locator("#zoomIn").click();
  await frame.locator("#zoomIn").click();
  await frame.locator("#panMode").click();
  const panBefore = await embeddedMapState(frame);
  const panBox = await map.boundingBox();
  assert(panBox && panBox.width >= 180 && panBox.height >= 180, `${surface.id} is too small for mouse pan.`);
  await page.mouse.move(panBox.x + panBox.width * .5, panBox.y + panBox.height * .5);
  await page.mouse.down();
  await page.mouse.move(panBox.x + panBox.width * .65, panBox.y + panBox.height * .62, {steps: 8});
  await page.mouse.up();
  recordBrowserAction(observations, "mouse-drag", `${surface.id}:pan`);
  await page.waitForTimeout(300);
  const mousePanned = await embeddedMapState(frame);
  assert(mousePanned.pan_x !== panBefore.pan_x || mousePanned.pan_y !== panBefore.pan_y, `${surface.id} mouse drag did not pan.`);
  checkpoints.push(await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "mouse-pan"));

  await map.focus();
  const keyboardBefore = await embeddedMapState(frame);
  await map.press("ArrowRight");
  recordBrowserAction(observations, "keyboard", `${surface.id}:ArrowRight`);
  await page.waitForTimeout(250);
  const keyboardPanned = await embeddedMapState(frame);
  assert(keyboardPanned.pan_x !== keyboardBefore.pan_x || keyboardPanned.pan_y !== keyboardBefore.pan_y, `${surface.id} keyboard pan did not move.`);
  checkpoints.push(await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "keyboard-pan"));

  await frame.locator("#fitRoute").click();
  await frame.locator("#zoomIn").click();
  await frame.locator("#zoomIn").click();
  recordBrowserAction(observations, "click-sequence", `${surface.id}:pan-button-centered-zoom-setup`);
  await page.waitForTimeout(750);
  const panButtonInteractions = [];
  for (const definition of [
    {id: "panUp", axis: "pan_y", direction: -1},
    {id: "panDown", axis: "pan_y", direction: 1},
    {id: "panLeft", axis: "pan_x", direction: -1},
    {id: "panRight", axis: "pan_x", direction: 1},
  ]) {
    const panControl = frame.locator(`#${definition.id}`);
    if (!(await panControl.isVisible())) continue;
    const beforeState = await embeddedMapState(frame);
    const beforeCheckpoint = await captureVisualCheckpoint(
      page,
      map,
      observations,
      `maps-${surface.id}`,
      `${definition.id}-before`,
    );
    await panControl.click();
    recordBrowserAction(observations, "click", `${surface.id}:${definition.id}`);
    await page.waitForTimeout(300);
    const afterState = await embeddedMapState(frame);
    const delta = afterState[definition.axis] - beforeState[definition.axis];
    assert(delta * definition.direction > 0, `${surface.id} ${definition.id} moved in the wrong direction or did not move.`);
    const afterCheckpoint = await captureVisualCheckpoint(
      page,
      map,
      observations,
      `maps-${surface.id}`,
      `${definition.id}-after`,
    );
    assert(
      beforeCheckpoint.screenshot_sha256 !== afterCheckpoint.screenshot_sha256,
      `${surface.id} ${definition.id} changed state without a visible map change.`,
    );
    panButtonInteractions.push({
      control_id: definition.id,
      before: beforeState,
      after: afterState,
      before_screenshot: beforeCheckpoint.screenshot,
      after_screenshot: afterCheckpoint.screenshot,
      terminal_state: "OPERATED",
    });
  }

  await frame.locator("#fitRoute").click();
  await frame.locator("#boxZoomMode").click();
  assert(await frame.locator("#boxZoomMode").getAttribute("aria-pressed") === "true", `${surface.id} rectangle zoom mode did not activate.`);
  const box = await map.boundingBox();
  assert(box && box.width >= 180 && box.height >= 180, `${surface.id} is too small for rectangle zoom.`);
  await page.mouse.move(box.x + box.width * .2, box.y + box.height * .2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .68, box.y + box.height * .72, {steps: 10});
  await page.mouse.up();
  recordBrowserAction(observations, "rectangle-drag", `${surface.id}:box-zoom`);
  await page.waitForTimeout(750);
  const rectangleZoomed = await embeddedMapState(frame);
  assert(rectangleZoomed.zoom > 1, `${surface.id} rectangle zoom did not increase zoom.`);
  checkpoints.push(await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "rectangle-zoom"));

  await frame.locator("#fitRoute").click();
  const evidenceTargets = map.locator("[data-evidence-type]");
  assert(await evidenceTargets.count(), `${surface.id} has no hoverable map evidence.`);
  const hint = frame.locator("#hoverHint");
  await map.hover({position: {x: 4, y: 4}}).catch(() => undefined);
  await page.waitForTimeout(150);
  assert((await hint.getAttribute("class") || "").includes("is-hidden"), `${surface.id} inherited a visible hint before target hover.`);
  const hintBeforeCheckpoint = await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "evidence-hint-before");
  checkpoints.push(hintBeforeCheckpoint);
  await hoverSelectedEvidence(page, evidenceTargets, observations, `${surface.id}:evidence-hint`);
  await page.waitForTimeout(200);
  const hintAfterCheckpoint = await captureVisualCheckpoint(page, map, observations, `maps-${surface.id}`, "evidence-hint-after");
  checkpoints.push(hintAfterCheckpoint);
  assert(!(await hint.getAttribute("class") || "").includes("is-hidden"), `${surface.id} evidence hover hint is hidden.`);
  assert((await hint.textContent() || "").trim().length > 0, `${surface.id} evidence hover hint is empty.`);
  assert(hintBeforeCheckpoint.screenshot_sha256 !== hintAfterCheckpoint.screenshot_sha256, `${surface.id} hint became semantic-only without visible evidence.`);

  const rasterRequests = observations.requests
    .slice(requestStart)
    .filter(request => Number.isInteger(request.rudyMatrix));
  assert(
    rasterRequests.some(request => request.status >= 200 && request.status < 300),
    `${surface.id} has no successful browser-observed raster response.`,
  );
  const visualIssues = checkpoints.flatMap(checkpoint => checkpoint.issues);
  assert(visualIssues.length === 0, `${surface.id} visual quality failed: ${JSON.stringify(visualIssues)}`);
  const finalRenderState = await embeddedMapState(frame);
  return {
    surface_id: surface.id,
    route: surface.route,
    kind: surface.kind,
    preparation_operations: preparationOperations,
    gestures: browserActionContract.required_map_gestures,
    fit_before: fitBefore,
    fitted,
    zoomed_in: zoomedIn,
    zoomed_out: zoomedOut,
    mouse_panned: mousePanned,
    keyboard_panned: keyboardPanned,
    pan_button_interactions: panButtonInteractions,
    rectangle_zoomed: rectangleZoomed,
    hover_hint_visible: true,
    successful_raster_request_count: rasterRequests.filter(request => request.status >= 200 && request.status < 300).length,
    final_render_state: finalRenderState,
    final_screenshot: hintAfterCheckpoint.screenshot,
    checkpoints,
  };
}

async function inspectAllDashboardMapSurfaces(page, observations) {
  const mapInteractions = [];
  const failures = [];
  for (const surface of browserActionContract.map_surfaces) {
    try {
      const result = surface.id === "navigation-map"
        ? await inspectNavigationMapLibreGestures(page, observations, surface)
        : surface.kind === "native"
          ? await inspectNativeMapGestures(page, observations, surface)
          : await inspectEmbeddedMapGestures(page, observations, surface);
      mapInteractions.push(result);
    } catch (error) {
      const detail = `${surface.id}: ${String(error?.message || error)}`;
      const failureCheckpoint = await captureMapFailureCheckpoint(
        page,
        observations,
        surface,
        "failure-state",
      );
      failures.push(detail);
      mapInteractions.push({
        surface_id: surface.id,
        route: surface.route,
        kind: surface.kind,
        error: detail,
        failure_checkpoint: failureCheckpoint,
      });
    }
  }
  observations.mapInteractions = mapInteractions;
  observations.mapInteractionFailures = failures;
  assert(failures.length === 0, `Dashboard map interaction failures: ${JSON.stringify(failures)}`);
  return {
    requiredSurfaceCount: browserActionContract.map_surfaces.length,
    completedSurfaceCount: mapInteractions.filter(result => !result.error).length,
    mapInteractions,
    failures,
  };
}

async function canonicalLayerRenderState(frame, layerId) {
  return frame.locator("#map").evaluate((node, selectedLayerId) => {
    const input = document.querySelector(`input[data-layer="${CSS.escape(selectedLayerId)}"]`);
    const controlLabel = input?.closest("label") || null;
    const group = node.querySelector(`[data-layer-group="${CSS.escape(selectedLayerId)}"]`);
    const style = group ? getComputedStyle(group) : null;
    const inputStyle = input ? getComputedStyle(input) : null;
    const inputRect = input?.getBoundingClientRect();
    const controlVisible = Boolean(
      input
      && inputStyle.display !== "none"
      && inputStyle.visibility !== "hidden"
      && Number(inputStyle.opacity || 1) > 0
      && inputRect.width > 0
      && inputRect.height > 0
    );
    const controlDisabled = Boolean(input?.disabled || input?.getAttribute("aria-disabled") === "true");
    const safeResourceUrl = value => {
      try {
        const parsed = new URL(value, location.href);
        return `${parsed.origin}${parsed.pathname}`;
      } catch (_error) {
        return "unresolved";
      }
    };
    const rawRasterSources = group
      ? [...group.querySelectorAll("image, img")]
        .map(image => image.getAttribute("href") || image.getAttribute("xlink:href") || image.currentSrc || image.src || "")
        .filter(Boolean)
      : [];
    const resourceEntries = performance.getEntriesByType("resource")
      .filter(entry => rawRasterSources.some(source => entry.name === source || entry.name.endsWith(source)))
      .slice(-24)
      .map(entry => ({
        name: safeResourceUrl(entry.name),
        duration_ms: entry.duration,
        transfer_size: entry.transferSize,
        encoded_body_size: entry.encodedBodySize,
        decoded_body_size: entry.decodedBodySize,
      }));
    const rasterCount = group?.querySelectorAll("image, img").length || 0;
    const vectorCount = group?.querySelectorAll("path, polyline, polygon, circle, line, rect").length || 0;
    const snapshot = window.scoutPretripProjectBridge?.getSnapshot?.() || null;
    const view = snapshot?.view || null;
    const projectionKey = {
      "antecedent-rain": "antecedent_rain",
      "cwa-qpf": "cwa_qpf",
      "cwa-weather": "cwa_weather",
      "soil-moisture": "soil_moisture",
    }[selectedLayerId] || null;
    const projection = projectionKey && view && typeof view === "object"
      ? view[projectionKey]
      : null;
    const projectedReason = projection && typeof projection === "object"
      ? (
        projection.availability_reason
        || projection.empty_reason
        || projection.reason
        || projection.detail_code
        || null
      )
      : null;
    return {
      control_present: Boolean(input),
      control_disabled: controlDisabled,
      control_visible: controlVisible,
      availability_reason: !input
        ? "control_missing"
        : controlDisabled
          ? "control_disabled_in_runtime_state"
          : !controlVisible
            ? "control_not_visible_in_runtime_state"
            : "available",
      checked: Boolean(input?.checked),
      group_present: Boolean(group),
      hidden_attribute: group?.dataset.layerHidden || null,
      visibly_rendered: Boolean(group && style.display !== "none" && style.visibility !== "hidden"),
      child_count: group?.childElementCount || 0,
      raster_count: rasterCount,
      vector_count: vectorCount,
      raster_sources: rawRasterSources.map(safeResourceUrl),
      resource_entries: resourceEntries,
      control_label: String(controlLabel?.textContent || "").trim().replace(/\s+/g, " "),
      control_title: controlLabel?.getAttribute("title") || null,
      dashboard_weather_layer_hidden: controlLabel?.dataset.dashboardWeatherLayerHidden || null,
      dashboard_weather_layer_required: controlLabel?.dataset.dashboardWeatherLayerRequired || null,
      dashboard_weather_layer_availability: controlLabel?.dataset.dashboardWeatherLayerAvailability || null,
      dashboard_weather_layer_availability_reason: controlLabel?.dataset.dashboardWeatherLayerAvailabilityReason || null,
      dashboard_weather_layer_state_text: String(
        controlLabel?.querySelector('[data-dashboard-weather-layer-state="true"]')?.textContent || "",
      ).trim() || null,
      projected_availability: {
        bridge_project_id: snapshot?.projectId || null,
        projection_key: projectionKey,
        projection_present: Boolean(projection),
        status: projection?.status || projection?.availability_status || null,
        typed_reason: projectedReason,
        typed_reason_present: Boolean(projectedReason),
        point_count: Array.isArray(projection?.points) ? projection.points.length : null,
        source_path_present: Boolean(projection?.source_path),
        bounds_present: Boolean(projection?.bounds || projection?.bbox || projection?.bbox_wgs84),
      },
      render_provenance: rasterCount && vectorCount
        ? "raster_and_vector"
        : rasterCount
          ? "raster"
          : vectorCount
            ? "vector"
            : "empty",
    };
  }, layerId);
}

async function inspectMainMapWeatherLayerAvailability(page, observations) {
  const layerIds = [
    "antecedent-rain",
    "cwa-qpf",
    "cwa-weather",
    "soil-moisture",
    "weather-api",
  ];
  const mainMapRecords = [];
  observations.layerInteractions = mainMapRecords;
  observations.layerInteractionFailures = [];
  await openDashboard(page, observations.baseUrl, readyProjectId, "map");
  const frameSelector = browserActionContract.map_surfaces.find(surface => surface.id === "map").frame_selector;
  const frameHost = page.locator(frameSelector);
  const frame = page.frameLocator(frameSelector);
  await frame.locator("#map").waitFor({state: "visible", timeout: 120_000});
  await frame.locator("input[data-layer]").first().waitFor({state: "attached", timeout: 120_000});
  await frame.locator('label[data-dashboard-weather-layer-required="true"]')
    .first()
    .waitFor({state: "visible", timeout: 120_000});
  await page.waitForTimeout(1000);
  const mapFrameBoundaryRaw = await frameHost.evaluate(node => ({
    id: node.id || null,
    title: node.getAttribute("title") || null,
    source: node.src || node.getAttribute("src") || "",
  }));
  const mapFrameBoundary = {
    ...mapFrameBoundaryRaw,
    source: evidenceSafeUrl(mapFrameBoundaryRaw.source),
  };
  for (const layerId of layerIds) {
    const initial = await canonicalLayerRenderState(frame, layerId);
    const mainMapAvailability = initial.dashboard_weather_layer_availability;
    assert(initial.control_visible, `Main Map required weather layer ${layerId} is not visible.`);
    assert(initial.dashboard_weather_layer_required === "true",
      `Main Map weather layer ${layerId} is not marked required.`,
    );
    assert(["AVAILABLE", "NA"].includes(mainMapAvailability),
      `Main Map weather layer ${layerId} has invalid availability ${mainMapAvailability}.`,
    );
    assert(
      initial.dashboard_weather_layer_state_text === mainMapAvailability,
      `Main Map weather layer ${layerId} state text does not match ${mainMapAvailability}.`,
    );
    if (mainMapAvailability === "NA") {
      assert(initial.control_disabled, `Main Map unavailable weather layer ${layerId} must be guarded.`);
    }
    mainMapRecords.push({
      surface_id: "map",
      layer_id: layerId,
      required_contract: "weather_hydrology_layer_required",
      initial,
      availability_reason: initial.availability_reason,
      normalized_unavailable_state: mainMapAvailability,
      map_frame_boundary: mapFrameBoundary,
      evidence_semantics: "weather_hydrology_required_unavailable_normalized_to_na",
      terminal_state: mainMapAvailability === "AVAILABLE" ? "REQUIRED_AVAILABLE" : "REQUIRED_NA",
    });
    recordBrowserAction(
      observations,
      "observe",
      `main-map-weather-layer-availability:${layerId}`,
      initial.availability_reason,
    );
  }
  await frame.locator("#map [data-layer-group]")
    .first()
    .waitFor({state: "attached", timeout: 15_000})
    .catch(() => undefined);
  await page.waitForTimeout(750);
  for (const record of mainMapRecords) {
    const settled = await canonicalLayerRenderState(frame, record.layer_id);
    const settledAvailability = settled.dashboard_weather_layer_availability;
    assert(settled.control_visible, `Main Map settled weather layer ${record.layer_id} is not visible.`);
    assert(settled.dashboard_weather_layer_required === "true",
      `Main Map settled weather layer ${record.layer_id} is not marked required.`,
    );
    assert(["AVAILABLE", "NA"].includes(settledAvailability),
      `Main Map settled weather layer ${record.layer_id} has invalid availability ${settledAvailability}.`,
    );
    assert(settled.dashboard_weather_layer_state_text === settledAvailability,
      `Main Map settled weather layer ${record.layer_id} state text does not match ${settledAvailability}.`,
    );
    if (settledAvailability === "AVAILABLE") {
      assert(!settled.control_disabled, `Main Map available weather layer ${record.layer_id} must be operable.`);
      assert(settled.child_count > 0, `Main Map available weather layer ${record.layer_id} has no render content.`);
    } else {
      assert(settled.control_disabled, `Main Map unavailable weather layer ${record.layer_id} must be guarded.`);
    }
    record.settled = settled;
    record.normalized_unavailable_state = settledAvailability;
    record.terminal_state = settledAvailability === "AVAILABLE" ? "REQUIRED_AVAILABLE" : "REQUIRED_NA";
    recordBrowserAction(
      observations,
      "observe",
      `main-map-weather-layer-settled:${record.layer_id}`,
      settledAvailability,
    );
  }
  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");
  await page.locator("[data-weather-layer-control]").first().waitFor({state: "attached", timeout: 60_000});
  const weatherFrameSelector = browserActionContract.map_surfaces.find(surface => surface.id === "weather-map").frame_selector;
  const weatherFrame = page.frameLocator(weatherFrameSelector);
  await weatherFrame.locator("#map").waitFor({state: "visible", timeout: 120_000});
  await weatherFrame.locator("input[data-layer]").first().waitFor({state: "attached", timeout: 120_000});
  await page.waitForTimeout(1500);
  const records = [];
  for (const mainMapRecord of mainMapRecords) {
    const layerId = mainMapRecord.layer_id;
    const weatherControl = page.locator(`[data-weather-layer-control="${layerId}"]`);
    const weatherSurfaceControl = await weatherControl.count()
      ? await weatherControl.first().evaluate(node => ({
          present: true,
          visible: Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length),
          disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
          aria_pressed: node.getAttribute("aria-pressed"),
          render_state: node.dataset.weatherLayerRenderState || null,
          rendered_count: node.dataset.weatherLayerRenderedCount || null,
          state_text: String(node.querySelector("[data-weather-layer-state]")?.textContent || "").trim() || null,
        }))
      : {present: false};
    const pairedWeatherEmbeddedState = await canonicalLayerRenderState(weatherFrame, layerId);
    records.push({
      ...mainMapRecord,
      paired_weather_surface_control: weatherSurfaceControl,
      paired_weather_embedded_state: pairedWeatherEmbeddedState,
      paired_weather_normalized_unavailable_state: pairedWeatherEmbeddedState.availability_reason === "available"
        ? "AVAILABLE"
        : "NA",
    });
    recordBrowserAction(
      observations,
      "observe",
      `weather-surface-layer-availability:${layerId}`,
      pairedWeatherEmbeddedState.availability_reason,
    );
  }
  observations.layerInteractions = records;
  assert(records.length === layerIds.length, "Main Map weather-layer availability evidence is incomplete.");
  assert(records.every(record => record.paired_weather_surface_control.present), "Weather surface controls are missing from paired availability evidence.");
  return {
    evidence_only: true,
    product_behavior_changed: true,
    required_contract: "weather_hydrology_layer_required",
    unavailable_semantics: "NA",
    record_count: records.length,
    records,
  };
}

async function waitForCanonicalEmbeddedMapReady(
  page,
  frame,
  expectedProjectId,
  label,
  {waitForDashboardOverlay = false} = {},
) {
  if (waitForDashboardOverlay) {
    const loading = page.locator("#dashboardMapLoading");
    if (await loading.count()) {
      await page.waitForFunction(() => {
        const node = document.querySelector("#dashboardMapLoading");
        return !node || node.hidden || node.dataset.status === "blocked";
      }, null, {timeout: 120_000});
      assert(await loading.isHidden(), `${label} remained blocked before layer interaction.`);
    }
  }
  const deadline = Date.now() + 120_000;
  let lastState = null;
  while (Date.now() < deadline) {
    try {
      const map = frame.locator("#map[viewBox]");
      await map.waitFor({state: "visible", timeout: 5_000});
      lastState = await frame.locator("body").evaluate((node, expected) => {
        const bridge = node.ownerDocument.defaultView?.scoutPretripProjectBridge;
        const snapshot = bridge?.getSnapshot?.() || null;
        return {
          expected_project_id: expected,
          bridge_project_id: snapshot?.projectId || null,
          bridge_view_ready: Boolean(snapshot?.view && typeof snapshot.view === "object"),
          render_group_count: node.ownerDocument.querySelectorAll("#map[viewBox] [data-layer-group]").length,
        };
      }, expectedProjectId);
      if (
        lastState.bridge_project_id === expectedProjectId
        && lastState.bridge_view_ready
        && lastState.render_group_count > 0
      ) return lastState;
    } catch (error) {
      lastState = {error: String(error?.message || error)};
    }
    await page.waitForTimeout(250);
  }
  throw new Error(`${label} did not reach canonical map readiness: ${JSON.stringify(lastState)}`);
}

async function inspectEmbeddedCwaControls(page, frame, map, observations) {
  const menu = frame.locator("details.layer-menu");
  const unavailable = (controlId, reason) => ({
    interactions: [{
      surface_id: "weather-map",
      control_kind: "cwa-control",
      control_id: controlId,
      terminal_state: "NOT_EXERCISED",
      availability_reason: reason,
      error: `cwa:${controlId}: ${reason}`,
    }],
    failures: [`cwa:${controlId}: ${reason}`],
  });
  if (!(await menu.count())) {
    return unavailable("layer-menu", "layer_menu_missing_in_runtime_state");
  }
  if (!(await menu.isVisible())) {
    const exposedOuterControls = await page.locator(
      ".weather-cwa-control-deck select, .weather-cwa-control-deck input, .weather-cwa-control-deck button",
    ).evaluateAll(nodes => nodes.filter(node => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      return style.display !== "none"
        && style.visibility !== "hidden"
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0;
    }).length);
    if (!exposedOuterControls) {
      return unavailable("layer-menu", "layer_menu_not_visible_in_runtime_state");
    }
    return {
      interactions: [{
        surface_id: "weather-map",
        control_kind: "cwa-control",
        control_id: "embedded-layer-menu",
        terminal_state: "NOT_EXPOSED",
        availability_reason: "embedded_duplicate_layer_menu_not_exposed",
        delegated_to: "runtime-all-visible-controls",
        exposed_outer_control_count: exposedOuterControls,
      }],
      failures: [],
    };
  }
  const menuSummary = menu.locator(":scope > summary");
  if ((await menu.getAttribute("open")) === null) {
    if (!(await menuSummary.isVisible())) return unavailable("layer-menu", "layer_menu_summary_not_actionable");
    await menuSummary.click({timeout: 5_000});
  }
  const advanced = frame.locator("details.layer-advanced");
  if (!(await advanced.count()) || !(await advanced.isVisible())) {
    return unavailable("advanced-layers", "advanced_layer_controls_not_visible_in_runtime_state");
  }
  const advancedSummary = advanced.locator(":scope > summary");
  if ((await advanced.getAttribute("open")) === null) {
    if (!(await advancedSummary.isVisible())) return unavailable("advanced-layers", "advanced_layer_summary_not_actionable");
    await advancedSummary.click({timeout: 5_000});
  }
  const selector = [
    "[data-cwa-rainfall-product]",
    "[data-cwa-rainfall-opacity]",
    "[data-cwa-imagery-product]",
    "[data-cwa-imagery-window]",
    "[data-cwa-imagery-timeline]",
    "[data-cwa-imagery-opacity]",
    "[data-cwa-imagery-play]",
  ].join(", ");
  const controls = frame.locator(selector);
  const count = await controls.count();
  assert(count >= 8, `Embedded CWA control inventory is incomplete: ${count}.`);
  const interactions = [];
  const failures = [];
  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    const descriptor = await control.evaluate(node => ({
      tag: node.tagName.toLowerCase(),
      type: node.getAttribute("type") || "",
      value: "value" in node ? String(node.value) : null,
      disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
      aria_pressed: node.getAttribute("aria-pressed"),
      data_attributes: Object.fromEntries(Object.entries(node.dataset || {}).sort(([left], [right]) => left.localeCompare(right))),
      options: node instanceof HTMLSelectElement ? [...node.options].map(option => option.value) : [],
    }));
    const controlId = Object.entries(descriptor.data_attributes)
      .map(([key, value]) => `${key}${value && value !== "true" ? `-${value}` : ""}`)
      .join("-") || `control-${index}`;
    let restore = null;
    try {
      if (!(await control.isVisible()) || descriptor.disabled) {
        const availabilityReason = descriptor.disabled
          ? "control_disabled_in_runtime_state"
          : "control_not_visible_after_opening_advanced_layers";
        const detail = `cwa:${controlId}: ${availabilityReason}`;
        failures.push(detail);
        interactions.push({
          surface_id: "weather-map",
          control_kind: "cwa-control",
          control_id: controlId,
          descriptor,
          terminal_state: "NOT_EXERCISED",
          availability_reason: availabilityReason,
          error: detail,
        });
        continue;
      }
      const beforeCheckpoint = await captureVisualCheckpoint(page, map, observations, "embedded-cwa-controls", `${controlId}-before`);
      if (descriptor.tag === "select") {
        const alternate = descriptor.options.find(value => value !== descriptor.value);
        assert(alternate !== undefined, `${controlId} exposes only one runtime value.`);
        await control.selectOption(alternate);
        restore = async () => control.selectOption(descriptor.value);
      } else if (descriptor.type === "range") {
        const key = await control.evaluate(node => Number(node.value) < Number(node.max || node.value) ? "ArrowRight" : "ArrowLeft");
        await control.press(key);
        restore = async () => control.press(key === "ArrowRight" ? "ArrowLeft" : "ArrowRight");
      } else {
        await control.click();
        restore = async () => {
          if (await control.getAttribute("aria-pressed") === "true") await control.click();
        };
      }
      recordBrowserAction(observations, "operate-control", `embedded-cwa:${controlId}`);
      await page.waitForTimeout(descriptor.data_attributes.cwaImageryPlay !== undefined ? 900 : 500);
      const after = await control.evaluate(node => ({
        value: "value" in node ? String(node.value) : null,
        aria_pressed: node.getAttribute("aria-pressed"),
      }));
      assert(
        after.value !== descriptor.value || after.aria_pressed !== descriptor.aria_pressed,
        `${controlId} did not change semantic state.`,
      );
      const afterCheckpoint = await captureVisualCheckpoint(page, map, observations, "embedded-cwa-controls", `${controlId}-after`);
      assert(beforeCheckpoint.screenshot_sha256 !== afterCheckpoint.screenshot_sha256, `${controlId} produced no visible map change.`);
      assert(afterCheckpoint.issues.length === 0, `${controlId} visual quality failed: ${JSON.stringify(afterCheckpoint.issues)}`);
      await restore();
      await page.waitForTimeout(300);
      interactions.push({
        surface_id: "weather-map",
        control_kind: "cwa-control",
        control_id: controlId,
        before: descriptor,
        after,
        before_screenshot: beforeCheckpoint.screenshot,
        after_screenshot: afterCheckpoint.screenshot,
        terminal_state: "OPERATED",
      });
    } catch (error) {
      if (restore) await restore().catch(() => undefined);
      const detail = `cwa:${controlId}: ${String(error?.message || error)}`;
      failures.push(detail);
      interactions.push({
        surface_id: "weather-map",
        control_kind: "cwa-control",
        control_id: controlId,
        terminal_state: "NOT_EXERCISED",
        error: detail,
      });
    }
  }
  return {interactions, failures};
}

async function inspectCanonicalLayerToggles(page, observations) {
  const layerInteractions = [];
  const failures = [];
  observations.layerInteractions = layerInteractions;
  observations.layerInteractionFailures = failures;
  await openDashboard(page, observations.baseUrl, readyProjectId, "map");
  const frameSelector = browserActionContract.map_surfaces.find(surface => surface.id === "map").frame_selector;
  let frame = page.frameLocator(frameSelector);
  let map = frame.locator("#map");
  await map.waitFor({state: "visible", timeout: 120_000});
  await waitForCanonicalEmbeddedMapReady(
    page,
    frame,
    readyProjectId,
    "canonical preset map",
    {waitForDashboardOverlay: true},
  );
  let menu = frame.locator("details.layer-menu");
  if ((await menu.getAttribute("open")) === null) await menu.locator(":scope > summary").click();
  const expected = [...observations.expectedLayerIds.pretrip].sort();
  const rendered = (await frame.locator("input[data-layer]").evaluateAll(inputs => inputs.map(input => input.dataset.layer))).sort();
  assert(JSON.stringify(rendered) === JSON.stringify(expected), `Canonical browser layer controls differ from scout_layer_contract.py: ${JSON.stringify({rendered, expected})}`);
  const presetIds = await frame.locator("[data-layer-preset]").evaluateAll(buttons => (
    buttons.filter(button => !button.disabled).map(button => button.dataset.layerPreset)
  ));
  const activePreset = frame.locator('[data-layer-preset][aria-pressed="true"]').first();
  const activePresetId = await activePreset.count()
    ? await activePreset.getAttribute("data-layer-preset")
    : null;
  const activePresetIndex = activePresetId ? presetIds.indexOf(activePresetId) : -1;
  const orderedPresetIds = activePresetIndex >= 0
    ? [...presetIds.slice(activePresetIndex + 1), ...presetIds.slice(0, activePresetIndex + 1)]
    : presetIds;
  for (const presetId of orderedPresetIds) {
    try {
      const beforeLayers = (await frame.locator('input[data-layer]:checked').evaluateAll(inputs => inputs.map(input => input.dataset.layer))).sort();
      const beforeCheckpoint = await captureVisualCheckpoint(page, map, observations, "canonical-layer-presets", `${presetId}-before`);
      const button = frame.locator(`[data-layer-preset="${presetId}"]`);
      await button.click();
      recordBrowserAction(observations, "click", `canonical-layer-preset:${presetId}`);
      await page.waitForTimeout(1000);
      const afterLayers = (await frame.locator('input[data-layer]:checked').evaluateAll(inputs => inputs.map(input => input.dataset.layer))).sort();
      assert(await button.getAttribute("aria-pressed") === "true", `${presetId} layer preset did not become active.`);
      assert(JSON.stringify(afterLayers) !== JSON.stringify(beforeLayers), `${presetId} layer preset did not change the rendered layer selection.`);
      const afterCheckpoint = await captureVisualCheckpoint(page, map, observations, "canonical-layer-presets", `${presetId}-after`);
      assert(beforeCheckpoint.screenshot_sha256 !== afterCheckpoint.screenshot_sha256, `${presetId} layer preset produced no visible map change.`);
      assert(afterCheckpoint.issues.length === 0, `${presetId} layer preset visual quality failed: ${JSON.stringify(afterCheckpoint.issues)}`);
      layerInteractions.push({
        surface_id: "map",
        control_kind: "layer-preset",
        preset_id: presetId,
        before_layers: beforeLayers,
        after_layers: afterLayers,
        before_screenshot: beforeCheckpoint.screenshot,
        after_screenshot: afterCheckpoint.screenshot,
        terminal_state: "OPERATED",
      });
    } catch (error) {
      const detail = `preset:${presetId}: ${String(error?.message || error)}`;
      failures.push(detail);
      layerInteractions.push({surface_id: "map", control_kind: "layer-preset", preset_id: presetId, terminal_state: "FAIL", error: detail});
    }
  }

  const presetPage = page;
  await Promise.race([
    presetPage.close({runBeforeUnload: false}).catch(() => undefined),
    new Promise(resolve => setTimeout(resolve, 10_000)),
  ]);
  const individualLayerPage = await observations._browserContext.newPage();
  individualLayerPage.__scoutQualificationObservations = observations;
  attachQualificationPageObservers(individualLayerPage, observations);
  await openDashboard(
    individualLayerPage,
    observations.baseUrl,
    readyProjectId,
    "map",
  );
  page = individualLayerPage;
  frame = page.frameLocator(frameSelector);
  map = frame.locator("#map");
  menu = frame.locator("details.layer-menu");
  await map.waitFor({state: "visible", timeout: 120_000});
  await waitForCanonicalEmbeddedMapReady(
    page,
    frame,
    readyProjectId,
    "canonical individual layer map",
    {waitForDashboardOverlay: true},
  );
  if ((await menu.getAttribute("open")) === null) await menu.locator(":scope > summary").click();
  for (const layerId of expected) {
    try {
      const input = frame.locator(`input[data-layer="${layerId}"]`);
      const initial = await canonicalLayerRenderState(frame, layerId);
      assert(initial.control_present, `${layerId} control is missing.`);
      if (initial.control_disabled || !initial.control_visible) {
        const detail = `${layerId}: ${initial.availability_reason}`;
        failures.push(detail);
        layerInteractions.push({
          surface_id: "map",
          layer_id: layerId,
          initial,
          terminal_state: "NOT_EXERCISED",
          availability_reason: initial.availability_reason,
          error: detail,
        });
        continue;
      }
      const requestStart = observations.requests.length;
      if (initial.checked) await input.click();
      else await input.click();
      recordBrowserAction(observations, "click", `canonical-layer:${layerId}:${initial.checked ? "off" : "on"}`);
      await page.waitForTimeout(750);
      let toggled = await canonicalLayerRenderState(frame, layerId);
      const offState = initial.checked ? toggled : null;
      const onState = initial.checked ? null : toggled;
      if (initial.checked) {
        assert(toggled.checked === false && toggled.hidden_attribute === "true", `${layerId} did not visibly turn off.`);
        await input.click();
        recordBrowserAction(observations, "click", `canonical-layer:${layerId}:on`);
        await page.waitForTimeout(1000);
        toggled = await canonicalLayerRenderState(frame, layerId);
      }
      const enabled = initial.checked ? toggled : onState;
      assert(enabled.checked === true, `${layerId} did not turn on.`);
      assert(enabled.group_present && enabled.hidden_attribute === "false" && enabled.visibly_rendered, `${layerId} enabled without a visible render group.`);
      assert(enabled.child_count > 0, `${layerId} enabled but rendered no tile, vector, point, line, polygon, or approved image.`);
      const onCheckpoint = await captureVisualCheckpoint(page, map, observations, "canonical-layers", `${layerId}-on`);
      if (!initial.checked) {
        await input.click();
        recordBrowserAction(observations, "click", `canonical-layer:${layerId}:off`);
        await page.waitForTimeout(500);
        const disabled = await canonicalLayerRenderState(frame, layerId);
        assert(disabled.checked === false && disabled.hidden_attribute === "true", `${layerId} did not visibly turn off.`);
      }
      const finalState = await canonicalLayerRenderState(frame, layerId);
      if (finalState.checked !== initial.checked) await input.click();
      const rasterResponses = observations.requests.slice(requestStart).filter(request => (
        request.status >= 200 && request.status < 300
      ));
      const renderProvenance = {
        render_kind: enabled.render_provenance,
        raster_sources: enabled.raster_sources,
        resource_entries: enabled.resource_entries,
        new_successful_response_count: rasterResponses.length,
        observation_kind: rasterResponses.length
          ? "network_response"
          : enabled.resource_entries.length
            ? "browser_resource_timing_or_cache"
            : "rendered_without_observed_resource",
      };
      if (enabled.raster_count > 0) {
        assert(
          rasterResponses.length > 0 || enabled.resource_entries.length > 0,
          `${layerId} raster appeared without successful browser network or resource-timing provenance.`,
        );
      }
      assert(onCheckpoint.issues.length === 0, `${layerId} visual quality failed: ${JSON.stringify(onCheckpoint.issues)}`);
      layerInteractions.push({
        surface_id: "map",
        layer_id: layerId,
        initial,
        enabled,
        off_state: offState,
        screenshot_on: onCheckpoint.screenshot,
        successful_response_count: rasterResponses.length,
        render_provenance: renderProvenance,
        resource_entries: enabled.resource_entries,
        terminal_state: "OPERATED",
      });
    } catch (error) {
      const detail = `${layerId}: ${String(error?.message || error)}`;
      failures.push(detail);
      layerInteractions.push({surface_id: "map", layer_id: layerId, terminal_state: "FAIL", error: detail});
    }
  }

  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");
  const weatherButtons = page.locator("[data-weather-layer-control]");
  const weatherLayerIds = await weatherButtons.evaluateAll(buttons => buttons.map(button => button.dataset.weatherLayerControl));
  const weatherFrameSelector = browserActionContract.map_surfaces.find(surface => surface.id === "weather-map").frame_selector;
  const weatherFrame = page.frameLocator(weatherFrameSelector);
  const weatherMap = weatherFrame.locator("#map");
  await weatherMap.waitFor({state: "visible", timeout: 120_000});
  await waitForCanonicalEmbeddedMapReady(
    page,
    weatherFrame,
    readyProjectId,
    "canonical Weather layer map",
  );
  for (const layerId of weatherLayerIds) {
    try {
      let button = page.locator(`[data-weather-layer-control="${layerId}"]`);
      const buttonAvailable = await button.isVisible();
      const buttonDisabled = await button.isDisabled();
      if (!buttonAvailable || buttonDisabled) {
        const availabilityReason = buttonDisabled
          ? "weather_layer_control_disabled_in_runtime_state"
          : "weather_layer_control_not_visible_in_runtime_state";
        const detail = `weather:${layerId}: ${availabilityReason}`;
        failures.push(detail);
        layerInteractions.push({
          surface_id: "weather-map",
          layer_id: layerId,
          terminal_state: "NOT_EXERCISED",
          availability_reason: availabilityReason,
          error: detail,
        });
        continue;
      }
      const initialPressed = await button.getAttribute("aria-pressed");
      let offCheckpoint = null;
      if (initialPressed === "true") {
        await button.click();
        recordBrowserAction(observations, "click", `weather-layer:${layerId}:off`);
        await page.waitForTimeout(750);
        const offState = await canonicalLayerRenderState(weatherFrame, layerId);
        assert(offState.checked === false && offState.hidden_attribute === "true", `${layerId} weather layer did not visibly turn off.`);
        offCheckpoint = await captureVisualCheckpoint(page, weatherMap, observations, "weather-layers", `${layerId}-off`);
        button = page.locator(`[data-weather-layer-control="${layerId}"]`);
      }
      await button.click();
      recordBrowserAction(observations, "click", `weather-layer:${layerId}:on`);
      await page.waitForTimeout(1500);
      button = page.locator(`[data-weather-layer-control="${layerId}"]`);
      const toggledPressed = await button.getAttribute("aria-pressed");
      const stateText = (await button.locator("[data-weather-layer-state]").textContent() || "").trim();
      assert(toggledPressed === "true", `${layerId} weather layer did not reach its enabled state.`);
      assert(stateText === "ON", `${layerId} weather layer state label is inconsistent.`);
      const enabled = await canonicalLayerRenderState(weatherFrame, layerId);
      assert(enabled.checked === true, `${layerId} embedded map control did not turn on.`);
      assert(enabled.group_present && enabled.hidden_attribute === "false" && enabled.visibly_rendered, `${layerId} enabled without a visible Weather render group.`);
      assert(enabled.child_count > 0, `${layerId} enabled but rendered no Weather tile, vector, point, line, polygon, or approved image.`);
      const onCheckpoint = await captureVisualCheckpoint(page, weatherMap, observations, "weather-layers", `${layerId}-on`);
      if (offCheckpoint) {
        assert(offCheckpoint.screenshot_sha256 !== onCheckpoint.screenshot_sha256, `${layerId} off/on map rendering is visually unchanged.`);
      }
      assert(onCheckpoint.issues.length === 0, `${layerId} weather layer visual quality failed: ${JSON.stringify(onCheckpoint.issues)}`);
      if (initialPressed !== "true") await button.click();
      layerInteractions.push({
        surface_id: "weather-map",
        layer_id: layerId,
        initial_aria_pressed: initialPressed,
        toggled_aria_pressed: toggledPressed,
        state_text: stateText,
        enabled,
        render_provenance: {
          render_kind: enabled.render_provenance,
          raster_sources: enabled.raster_sources,
          resource_entries: enabled.resource_entries,
        },
        resource_entries: enabled.resource_entries,
        screenshot_off: offCheckpoint?.screenshot || null,
        screenshot_on: onCheckpoint.screenshot,
        terminal_state: "OPERATED",
      });
    } catch (error) {
      const detail = `weather:${layerId}: ${String(error?.message || error)}`;
      failures.push(detail);
      layerInteractions.push({surface_id: "weather-map", layer_id: layerId, terminal_state: "FAIL", error: detail});
    }
  }
  const cwaSetupRestores = [];
  const cwaSetupFailures = [];
  for (const layerId of ["cwa-qpf", "cwa-weather"]) {
    const button = page.locator(`[data-weather-layer-control="${layerId}"]`);
    if (!(await button.isVisible()) || await button.isDisabled()) {
      cwaSetupFailures.push(`cwa:${layerId}: weather_layer_control_not_actionable_for_cwa_setup`);
      continue;
    }
    const initiallyEnabled = await button.getAttribute("aria-pressed") === "true";
    cwaSetupRestores.push({button, initiallyEnabled});
    if (!initiallyEnabled) {
      await button.click();
      recordBrowserAction(observations, "click", `weather-layer:${layerId}:cwa-control-setup-on`);
      await page.waitForTimeout(1000);
    }
  }
  const cwaControls = cwaSetupFailures.length
    ? {
        interactions: cwaSetupFailures.map((detail, index) => ({
          surface_id: "weather-map",
          control_kind: "cwa-control",
          control_id: `setup-${index + 1}`,
          terminal_state: "NOT_EXERCISED",
          availability_reason: "weather_layer_control_not_actionable_for_cwa_setup",
          error: detail,
        })),
        failures: cwaSetupFailures,
      }
    : await inspectEmbeddedCwaControls(page, weatherFrame, weatherMap, observations);
  for (const {button, initiallyEnabled} of cwaSetupRestores) {
    if (!initiallyEnabled && await button.getAttribute("aria-pressed") === "true") await button.click();
  }
  layerInteractions.push(...cwaControls.interactions);
  failures.push(...cwaControls.failures);
  observations.layerInteractions = layerInteractions;
  observations.layerInteractionFailures = failures;
  assert(layerInteractions.length > 0, "Dashboard layer interaction coverage produced no evidence records.");
  assert(failures.length === 0, `Dashboard layer interaction failures: ${JSON.stringify(failures)}`);
  return {
    canonicalLayerCount: expected.length,
    layerPresetCount: presetIds.length,
    weatherLayerCount: weatherLayerIds.length,
    cwaControlCount: cwaControls.interactions.length,
    layerInteractions,
    failures,
  };
}

async function inspectApprovedTargetedRepairEvidence(page, observations) {
  const result = {
    navigation: {},
    weather: {},
    readability: [],
    product_verdict_allowed: false,
  };
  const sampleReadability = async (selector, route, label) => {
    const locator = page.locator(`${selector}:visible`).first();
    await locator.waitFor({state: "visible", timeout: 60_000});
    const sample = await locator.evaluate(node => {
      const style = getComputedStyle(node);
      const overflowX = style.overflowX;
      const overflowY = style.overflowY;
      return {
        text: String(node.textContent || "").trim().replace(/\s+/g, " ").slice(0, 160),
        font_size_px: Number.parseFloat(style.fontSize || "0"),
        client_width: node.clientWidth,
        scroll_width: node.scrollWidth,
        client_height: node.clientHeight,
        scroll_height: node.scrollHeight,
        overflow_x: overflowX,
        overflow_y: overflowY,
        clipped: (
          (node.scrollWidth > node.clientWidth + 1 && overflowX === "hidden")
          || (node.scrollHeight > node.clientHeight + 1 && overflowY === "hidden")
        ),
      };
    });
    assert(sample.font_size_px >= 10, `${label} remains below 10px: ${JSON.stringify(sample)}`);
    assert(!sample.clipped, `${label} remains clipped: ${JSON.stringify(sample)}`);
    const record = {route, selector, label, ...sample};
    result.readability.push(record);
    recordBrowserAction(observations, "observe", `compact-readability:${label}`, "completed", record);
    return record;
  };

  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-navigation");
  const navigationShell = page.locator('[data-navigation-maplibre-shell="2d"]').first();
  const navigationMap = page.locator('[data-navigation-maplibre-map="2d"][data-dashboard-map-hint-title]').first();
  await navigationShell.waitFor({state: "visible", timeout: 120_000});
  await navigationMap.waitFor({state: "visible", timeout: 120_000});
  await hoverSelectedEvidence(page, navigationMap, observations, "approved-navigation-evidence-hint");
  const navigationHint = page.locator("#dashboardMapHoverHint");
  await navigationHint.waitFor({state: "visible", timeout: 10_000});
  result.navigation.hint = await navigationHint.evaluate(node => ({
    visible: !node.hidden,
    text: String(node.textContent || "").trim().replace(/\s+/g, " "),
    source: node.dataset.hintSource || null,
  }));
  assert(result.navigation.hint.visible && result.navigation.hint.text, "Navigation evidence hint did not visibly render.");
  const fitControl = page.locator('[data-navigation-maplibre-fit="2d"]').first();
  const mapLibreControls = navigationShell.locator(".maplibregl-ctrl-top-right").first();
  await fitControl.waitFor({state: "visible", timeout: 60_000});
  await mapLibreControls.waitFor({state: "visible", timeout: 60_000});
  const [fitBox, controlsBox] = await Promise.all([fitControl.boundingBox(), mapLibreControls.boundingBox()]);
  assert(fitBox && controlsBox, "Navigation fit/control geometry is unavailable.");
  const navigationFitControlNonOverlap = (
    fitBox.y + fitBox.height <= controlsBox.y
    || controlsBox.y + controlsBox.height <= fitBox.y
    || fitBox.x + fitBox.width <= controlsBox.x
    || controlsBox.x + controlsBox.width <= fitBox.x
  );
  result.navigation.navigation_fit_control_non_overlap = navigationFitControlNonOverlap;
  result.navigation.fit_box = fitBox;
  result.navigation.maplibre_controls_box = controlsBox;
  assert(navigationFitControlNonOverlap, `Navigation FIT overlaps MapLibre controls: ${JSON.stringify(result.navigation)}`);
  await sampleReadability(".navigation-terrain-maplibre-fit", "outdoor-navigation", "navigation-fit");
  await captureVisualCheckpoint(
    page,
    null,
    observations,
    "approved-targeted-repairs",
    "navigation-hint-and-fit",
    {fullPage: false, domRoot: page.locator("body")},
  );

  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");
  const weatherFrameSelector = browserActionContract.map_surfaces.find(surface => surface.id === "weather-map").frame_selector;
  const weatherFrame = page.frameLocator(weatherFrameSelector);
  await weatherFrame.locator("#map").waitFor({state: "visible", timeout: 120_000});
  const weatherEvidence = weatherFrame.locator('rect[data-evidence-type="cwa_weather_environment_evidence"]');
  await weatherEvidence.first().waitFor({state: "visible", timeout: 120_000});
  await page.waitForFunction(() => {
    const frame = document.querySelector('[data-weather-cwa-map-frame="true"]');
    return Boolean(frame?.contentDocument && frame.weatherCwaHintDocument === frame.contentDocument);
  }, null, {timeout: 60_000});
  const weatherHover = await hoverSelectedEvidence(page, weatherEvidence, observations, "approved-weather-evidence-hint");
  const weatherHint = weatherFrame.locator("#hoverHint");
  let weatherHintWaitError = null;
  try {
    await weatherHint.waitFor({state: "visible", timeout: 10_000});
  } catch (error) {
    weatherHintWaitError = String(error?.message || error);
  }
  result.weather.hint = await weatherHint.evaluate(node => ({
    visible: getComputedStyle(node).display !== "none",
    text: String(node.textContent || "").trim().replace(/\s+/g, " "),
  }));
  result.weather.evidence_owner = weatherHover.hover.evidence_owner;
  result.weather.headless_hint_observation = result.weather.hint.visible && result.weather.hint.text
    ? "VISIBLE"
    : "NOT_OBSERVED_AFTER_BOUND_LISTENER_AND_TARGETED_HOVER";
  result.weather.headless_hint_wait_error = weatherHintWaitError;
  recordBrowserAction(
    observations,
    "observe",
    "approved-weather-evidence-hint-visibility",
    result.weather.headless_hint_observation,
  );
  await sampleReadability(".weather-layer-control small", "outdoor-weather", "weather-layer-detail");
  await captureVisualCheckpoint(
    page,
    null,
    observations,
    "approved-targeted-repairs",
    "weather-evidence-hint",
    {fullPage: false, domRoot: page.locator("body")},
  );

  await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-permission");
  await page.waitForFunction(() => !["", "idle", "loading"].includes(String(state?.permissionDataStatus || "")), null, {timeout: 60_000});
  await sampleReadability(".permission-eyebrow", "outdoor-permission", "permission-eyebrow");
  await captureVisualCheckpoint(
    page,
    null,
    observations,
    "approved-targeted-repairs",
    "permission-readability",
    {fullPage: false, domRoot: page.locator("body")},
  );

  await openDashboard(page, observations.baseUrl, readyProjectId, "runtime-audit");
  await page.waitForFunction(() => !["", "idle", "loading"].includes(String(state?.runtimeAuditStatus || "")), null, {timeout: 60_000});
  await sampleReadability(".runtime-audit-health-card small", "runtime-audit", "runtime-audit-health");
  await captureVisualCheckpoint(
    page,
    null,
    observations,
    "approved-targeted-repairs",
    "runtime-audit-readability",
    {fullPage: false, domRoot: page.locator("body")},
  );
  return result;
}

function attachQualificationPageObservers(page, observations) {
  if (page.__scoutQualificationObserversAttached) return;
  page.__scoutQualificationObserversAttached = true;
  const requestStartedAt = new WeakMap();
  const dashboardRoute = () => {
    try {
      return new URL(page.url()).hash.replace(/^#/, "") || "home";
    } catch (_error) {
      return "unresolved";
    }
  };
  const recordFrameLifecycle = async (event, frame) => {
    const baseRecord = {
      kind: "frame_lifecycle",
      observed_at: new Date().toISOString(),
      route: dashboardRoute(),
      event,
      frame_name: frame.name?.() || null,
      frame_url: evidenceSafeUrl(frame.url?.() || ""),
      owner: null,
    };
    observations.controlStateTraces.push(baseRecord);
    try {
      const element = await frame.frameElement();
      const owner = await element.evaluate(node => ({
        id: node.id || null,
        title: node.getAttribute("title") || null,
        weather_cwa_map_frame: node.dataset.weatherCwaMapFrame || null,
        emergency_approval_frame: node.dataset.emergencyApprovalFrame || null,
      }));
      observations.controlStateTraces.push({
        ...baseRecord,
        kind: "frame_lifecycle_owner",
        owner,
      });
    } catch (_error) {
      // A detached frame cannot expose its former owner; the synchronous lifecycle record remains authoritative.
    }
  };
  page.on("frameattached", frame => { void recordFrameLifecycle("attached", frame); });
  page.on("framenavigated", frame => { void recordFrameLifecycle("navigated", frame); });
  page.on("framedetached", frame => { void recordFrameLifecycle("detached", frame); });
  page.on("console", message => {
    if (message.type() !== "error") return;
    const location = message.location();
    const source = location.url
      ? ` @ ${location.url}:${location.lineNumber || 0}:${location.columnNumber || 0}`
      : "";
    observations.consoleErrors.push(`${message.text()}${source}`);
  });
  page.on("pageerror", error => observations.pageErrors.push(error.message));
  page.on("request", request => {
    requestStartedAt.set(request, Date.now());
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      observations.postRequests.push(`${request.method()} ${evidenceSafeUrl(request.url())}`);
    }
  });
  page.on("response", response => {
    const request = response.request();
    const rudyMatrix = rudyMatrixFromUrl(response.url());
    const record = {
      observed_at: new Date().toISOString(),
      method: request.method(),
      status: response.status(),
      url: evidenceSafeUrl(response.url()),
      rudyMatrix,
      resource_type: request.resourceType(),
      duration_ms: requestStartedAt.has(request) ? Date.now() - requestStartedAt.get(request) : null,
    };
    observations.requests.push(record);
    const route = dashboardRoute();
    if (["outdoor-permission", "runtime-audit", "outdoor-weather", "emergency"].includes(route)) {
      observations.controlStateTraces.push({
        kind: "network_completion",
        route,
        ...record,
      });
    }
    if (response.status() >= 400) {
      observations.failedResponses.push({ status: response.status(), url: evidenceSafeUrl(response.url()) });
    }
  });
}

async function captureAvailableCaseScreenshot(context, primaryPage, options) {
  const candidates = [...new Set([
    primaryPage,
    ...context.pages().slice().reverse(),
  ])].filter(candidate => candidate && !candidate.isClosed());
  if (!candidates.length) return {captured: false, reason: "no_open_page"};
  await candidates[0].screenshot(options);
  return {
    captured: true,
    page_url: evidenceSafeUrl(candidates[0].url()),
  };
}

async function runIsolatedCase(browser, definition, environment) {
  const caseId = safeCaseId(definition.id);
  const caseDirectory = path.join(environment.outputRoot, "cases", caseId);
  fs.mkdirSync(caseDirectory, { recursive: true });
  const videoDirectory = path.join(caseDirectory, "videos");
  const tracePath = path.join(caseDirectory, "trace.zip");
  const screenshotPath = path.join(caseDirectory, "final.png");
  const segmentedTraceByRoute = definition.segmentedTraceByRoute === true;
  const contextOptions = {
    viewport: definition.viewport || { width: 1440, height: 1000 },
  };
  if (definition.recordVideo !== false) {
    fs.mkdirSync(videoDirectory, { recursive: true });
    contextOptions.recordVideo = {
      dir: videoDirectory,
      size: definition.viewport || { width: 1440, height: 1000 },
    };
  }
  const context = await browser.newContext(contextOptions);
  if (!segmentedTraceByRoute) {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  }
  const page = definition.selfManagedPages === true ? null : await context.newPage();
  const observations = {
    baseUrl: environment.baseUrl,
    disabledBaseUrl: environment.disabledBaseUrl,
    caseId,
    caseDirectory,
    outputRoot: environment.outputRoot,
    expectedLayerIds: environment.expectedLayerIds,
    consoleErrors: [],
    pageErrors: [],
    requests: [],
    postRequests: [],
    blockedMutationRequests: [],
    failedResponses: [],
    browserActions: [],
    controlStateTraces: [],
    visualCheckpoints: [],
  };
  Object.defineProperty(observations, "_browserContext", {
    value: context,
    enumerable: false,
  });
  if (page) page.__scoutQualificationObservations = observations;
  const configuredExecutionTimeout = Number(definition.executionTimeoutMs);
  appendCaseProgress(observations, "case_started", {
    execution_timeout_ms: (
      Number.isFinite(configuredExecutionTimeout) && configuredExecutionTimeout > 0
        ? configuredExecutionTimeout
        : CASE_EXECUTION_TIMEOUT_MS
    ),
  });
  await context.route("**/*", async route => {
    const method = route.request().method();
    if (["GET", "HEAD", "OPTIONS"].includes(method)) {
      await route.continue();
      return;
    }
    observations.blockedMutationRequests.push({
      method,
      url: evidenceSafeUrl(route.request().url()),
    });
    await route.abort("blockedbyclient");
  });
  if (page) attachQualificationPageObservers(page, observations);
  const before = workspaceDigest(environment.workspaceRoot);
  let status = "PASS";
  let detail = "completed";
  let result = null;
  let mutationPaths = [];
  const finalizationErrors = [];
  let executionTimedOut = false;
  try {
    appendCaseProgress(observations, "case_body_started");
    result = await runCaseExecutionWithTimeout(
      definition,
      () => definition.run(page, observations),
    );
    appendCaseProgress(observations, "case_body_completed");
    assert(observations.postRequests.length === 0, `unexpected_post_requests: ${observations.postRequests.join(", ")}`);
    const after = workspaceDigest(environment.workspaceRoot);
    mutationPaths = workspaceDiff(before, after);
    if (definition.readOnly !== false && mutationPaths.length) {
      throw new Error(`unexpected_workspace_mutation: ${mutationPaths.join(", ")}`);
    }
    await captureAvailableCaseScreenshot(context, page, {
      path: screenshotPath,
      type: "png",
      fullPage: true,
    });
  } catch (error) {
    detail = String(error?.stack || error);
    executionTimedOut = error?.code === "CASE_EXECUTION_TIMEOUT";
    status = executionTimedOut ? "BLOCKED" : "FAIL";
    appendCaseProgress(observations, "case_body_failed", {
      error_code: String(error?.code || "CASE_BODY_FAILURE"),
      error: String(error?.message || error),
      execution_timed_out: executionTimedOut,
    });
    const after = workspaceDigest(environment.workspaceRoot);
    mutationPaths = workspaceDiff(before, after);
    if (!executionTimedOut) {
      try {
        await runCaseFinalizerWithTimeout(
          "failure-screenshot",
          () => captureAvailableCaseScreenshot(context, page, {
            path: screenshotPath,
            type: "png",
            fullPage: true,
            timeout: CASE_FAILURE_SCREENSHOT_TIMEOUT_MS,
          }),
        );
      } catch (screenshotError) {
        finalizationErrors.push(String(screenshotError?.stack || screenshotError));
      }
    }
  } finally {
    appendCaseProgress(observations, "case_finalization_started");
    try {
      if (!segmentedTraceByRoute) {
        await runCaseFinalizerWithTimeout(
          "trace-stop",
          () => context.tracing.stop({ path: tracePath }),
        );
        appendCaseProgress(observations, "trace_finalized");
      }
    } catch (error) {
      finalizationErrors.push(String(error?.stack || error));
      appendCaseProgress(observations, "trace_finalization_failed", {
        error: String(error?.message || error),
      });
    } finally {
      try {
        await runCaseFinalizerWithTimeout("context-close", () => context.close());
        appendCaseProgress(observations, "context_closed");
      } catch (error) {
        finalizationErrors.push(String(error?.stack || error));
        appendCaseProgress(observations, "context_close_failed", {
          error: String(error?.message || error),
        });
      }
    }
  }
  if (finalizationErrors.length && status === "PASS") status = "FAIL";
  if (finalizationErrors.length) {
    const finalizationDetail = `Browser evidence finalization failed: ${finalizationErrors.join(" | ")}`;
    detail = detail === "completed" ? finalizationDetail : `${detail}\n${finalizationDetail}`;
    observations.caseFinalizationErrors = [...finalizationErrors];
  }
  appendCaseProgress(observations, "case_completed", {
    status,
    execution_timed_out: executionTimedOut,
    mutation_path_count: mutationPaths.length,
    finalization_error_count: finalizationErrors.length,
  });
  const traceReferences = segmentedTraceByRoute
    ? (observations.segmentedTraces || []).filter(reference => fs.existsSync(path.join(environment.outputRoot, reference)))
    : (fs.existsSync(tracePath) ? [path.relative(environment.outputRoot, tracePath)] : []);
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
      trace: segmentedTraceByRoute ? null : (traceReferences[0] || null),
      traces: traceReferences,
      screenshot: fs.existsSync(screenshotPath) ? path.relative(environment.outputRoot, screenshotPath) : null,
      video_directory: path.relative(environment.outputRoot, videoDirectory),
      progress_log: path.relative(
        environment.outputRoot,
        path.join(caseDirectory, "case-progress.jsonl"),
      ),
      visual_checkpoints: observations.visualCheckpoints.map(checkpoint => checkpoint.screenshot),
    },
  };
}

const caseDefinitions = [
  {
    id: "runtime-route-navigation",
    capabilityId: "dashboard.shell.runtime_route_navigation",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "home");
      const routeValues = await page.locator("button.nav-item[data-route]").evaluateAll(buttons => (
        [...new Set(buttons.map(button => button.dataset.route).filter(Boolean))]
      ));
      assert(routeValues.length > 0, "Dashboard navigation exposes no routes.");
      const visited = [];
      for (const route of routeValues) {
        const control = page.locator(`button.nav-item[data-route="${route}"]`).first();
        await revealThroughClosedDetails(page, control, observations, `navigation-route:${route}`);
        await control.scrollIntoViewIfNeeded();
        await control.click();
        recordBrowserAction(observations, "click", `navigation-route:${route}`);
        await page.waitForFunction(expectedRoute => typeof state !== "undefined" && state.route === expectedRoute, route, { timeout: 60_000 });
        visited.push({ route, hash: await page.evaluate(() => window.location.hash) });
      }
      assert(observations.pageErrors.length === 0, `Route navigation raised page errors: ${observations.pageErrors.join(" | ")}`);
      return { routeCount: routeValues.length, visited };
    },
  },
  {
    id: "runtime-all-route-visual-states-desktop",
    capabilityId: "dashboard.visual.complete_live_rendering",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 15 * 60_000,
    viewport: {width: 1440, height: 1000},
    recordVideo: false,
    run: (page, observations) => auditAllRouteVisualStates(page, observations, "desktop"),
  },
  {
    id: "runtime-all-route-visual-states-mobile",
    capabilityId: "dashboard.visual.complete_live_rendering",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 15 * 60_000,
    viewport: {width: 390, height: 844},
    recordVideo: false,
    run: (page, observations) => auditAllRouteVisualStates(page, observations, "large-mobile"),
  },
  {
    id: "runtime-approved-mobile-layouts",
    capabilityId: "dashboard.visual.complete_live_rendering",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 15 * 60_000,
    viewport: {width: 390, height: 844},
    recordVideo: false,
    async run(page, observations) {
      const result = {};

      await openDashboard(page, observations.baseUrl, readyProjectId, "home");
        await page.locator("#dashboardNavToggle").click();
      recordBrowserAction(observations, "click", "mobile-sidebar-open");
      const sidebar = page.locator(".dashboard-sidebar");
      const navigation = sidebar.locator(".nav");
      result.sidebar = await navigation.evaluate(node => ({
        client_height: node.clientHeight,
        scroll_height: node.scrollHeight,
        overflow_y: getComputedStyle(node).overflowY,
      }));
      assert(
        ["auto", "scroll"].includes(result.sidebar.overflow_y),
        `Mobile sidebar navigation is not scrollable: ${JSON.stringify(result.sidebar)}`,
      );
      const diagnosticRoute = sidebar.locator('[data-route="diagnostic"]').first();
      const systemSection = diagnosticRoute.locator("xpath=ancestor::details[1]");
      if ((await systemSection.getAttribute("open")) === null) {
        await systemSection.locator(":scope > summary").click();
        recordBrowserAction(observations, "click", "mobile-sidebar-system-open");
      }
      await diagnosticRoute.scrollIntoViewIfNeeded();
      result.sidebar = {
        ...result.sidebar,
        ...(await navigation.evaluate(node => ({scroll_top: node.scrollTop}))),
      };
      result.sidebar.diagnostic_visible = await diagnosticRoute.evaluate(node => {
        const rect = node.getBoundingClientRect();
        const navigationRect = node.closest(".nav").getBoundingClientRect();
        return rect.top >= navigationRect.top && rect.bottom <= navigationRect.bottom;
      });
      assert(result.sidebar.scroll_top > 0, `Mobile sidebar did not scroll: ${JSON.stringify(result.sidebar)}`);
      assert(result.sidebar.diagnostic_visible, "Diagnostic is not reachable in the mobile sidebar.");
      await captureVisualCheckpoint(
        page,
        sidebar,
        observations,
        "approved-mobile-layouts",
        "mobile-sidebar-diagnostic-visible",
      );
      await diagnosticRoute.click();
      recordBrowserAction(observations, "click", "mobile-sidebar-diagnostic-visible");
      await page.waitForFunction(() => typeof state !== "undefined" && state.route === "diagnostic");

      await openDashboard(page, observations.baseUrl, readyProjectId, "living");
      const livingHeader = page.locator('[data-living-surface="true"] > .panel-header').first();
      await livingHeader.waitFor({state: "visible", timeout: 60_000});
      result.living = await livingHeader.evaluate(node => {
        const children = [...node.children];
        const first = children[0]?.getBoundingClientRect();
        const second = children[1]?.getBoundingClientRect();
        return {
          flex_direction: getComputedStyle(node).flexDirection,
          first_width: first?.width || 0,
          header_width: node.getBoundingClientRect().width,
          overlap: Boolean(first && second && first.bottom > second.top + 1),
        };
      });
      assert(result.living.flex_direction === "column", `Living mobile header is not stacked: ${JSON.stringify(result.living)}`);
      assert(!result.living.overlap, `Living mobile header children overlap: ${JSON.stringify(result.living)}`);
      assert(
        result.living.first_width >= result.living.header_width * .8,
        `Living mobile heading remains compressed: ${JSON.stringify(result.living)}`,
      );
      await page.locator(".living-event").first().waitFor({state: "visible", timeout: 60_000});
      result.living_containment = await page.evaluate(() => {
        const events = [...document.querySelectorAll(".living-event")].map(node => ({
          client_width: node.clientWidth,
          scroll_width: node.scrollWidth,
          client_height: node.clientHeight,
          scroll_height: node.scrollHeight,
        }));
        return {
          body_client_width: document.body.clientWidth,
          body_scroll_width: document.body.scrollWidth,
          event_count: events.length,
          event_overflow_count: events.filter(item => item.scroll_width > item.client_width + 1).length,
          events,
        };
      });
      assert(
        result.living_containment.body_scroll_width <= result.living_containment.body_client_width + 1,
        `Living mobile page overflows horizontally: ${JSON.stringify(result.living_containment)}`,
      );
      assert(result.living_containment.event_count > 0, "Living mobile route exposes no event cards to verify.");
      assert(
        result.living_containment.event_overflow_count === 0,
        `Living mobile long tokens overflow event cards: ${JSON.stringify(result.living_containment)}`,
      );
      await captureVisualCheckpoint(
        page,
        page.locator('[data-living-surface="true"]').first(),
        observations,
        "approved-mobile-layouts",
        "living-mobile-header",
      );

      await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-architecture");
      await page.locator('[data-architecture-mobile-view="map"]').first().click();
      const architectureFrame = page.locator(".architecture-map-frame").first();
      const architectureLens = architectureFrame.locator(".architecture-lensbar").first();
      await architectureLens.waitFor({state: "visible", timeout: 60_000});
      await architectureLens.evaluate(node => {
        const rect = node.getBoundingClientRect();
        window.scrollBy(0, Math.max(180, rect.top + 100));
      });
      await page.waitForTimeout(250);
      result.architecture = await architectureLens.evaluate(node => {
        const rect = node.getBoundingClientRect();
        const frameRect = node.closest(".architecture-map-frame").getBoundingClientRect();
        return {
          top: rect.top,
          bottom: rect.bottom,
          frame_bottom: frameRect.bottom,
          position: getComputedStyle(node).position,
        };
      });
      assert(
        result.architecture.position === "sticky"
          && result.architecture.top >= -1
          && result.architecture.top <= 12
          && result.architecture.frame_bottom > result.architecture.bottom,
        `Architecture mobile lensbar did not remain visibly sticky: ${JSON.stringify(result.architecture)}`,
      );
      await captureVisualCheckpoint(
        page,
        null,
        observations,
        "approved-mobile-layouts",
        "architecture-mobile-sticky",
        {fullPage: false, domRoot: page.locator("body")},
      );

      await openDashboard(page, observations.baseUrl, readyProjectId, "debug");
      const debugTables = page.locator(".debug-table");
      await debugTables.first().waitFor({state: "attached", timeout: 60_000});
      result.debug_tables = await debugTables.evaluateAll(tables => tables.map(table => {
        const wrapper = table.closest(".debug-table-wrap");
        return {
          min_width: getComputedStyle(table).minWidth,
          table_width: table.getBoundingClientRect().width,
          wrapper_width: wrapper?.getBoundingClientRect().width || 0,
          wrapper_overflow_x: wrapper ? getComputedStyle(wrapper).overflowX : "missing",
        };
      }));
      assert(
        result.debug_tables.every(item => (
          item.table_width >= 639
          && item.wrapper_width < item.table_width
          && ["auto", "scroll"].includes(item.wrapper_overflow_x)
        )),
        `Debug mobile tables are compressed instead of horizontally scrollable: ${JSON.stringify(result.debug_tables)}`,
      );
      const debugPills = page.locator(".debug-pill:visible");
      result.debug_pills = await debugPills.evaluateAll(nodes => nodes.map(node => ({
        client_width: node.clientWidth,
        scroll_width: node.scrollWidth,
        client_height: node.clientHeight,
        scroll_height: node.scrollHeight,
      })));
      assert(result.debug_pills.length > 0, "Debug mobile route exposes no endpoint badges to verify.");
      assert(
        result.debug_pills.every(item => item.scroll_width <= item.client_width + 1 && item.scroll_height <= item.client_height + 1),
        `Debug mobile endpoint badges remain clipped: ${JSON.stringify(result.debug_pills)}`,
      );
      const debugTableWrap = page.locator(".debug-table-wrap").last();
      await debugTableWrap.scrollIntoViewIfNeeded();
      await captureVisualCheckpoint(
        page,
        debugTableWrap,
        observations,
        "approved-mobile-layouts",
        "debug-mobile-table",
      );
      result.debug_horizontal_scroll = await debugTableWrap.evaluate(node => {
        node.scrollLeft = node.scrollWidth - node.clientWidth;
        return {
          scroll_left: node.scrollLeft,
          max_scroll_left: node.scrollWidth - node.clientWidth,
        };
      });
      assert(
        result.debug_horizontal_scroll.scroll_left > 0
          && result.debug_horizontal_scroll.scroll_left === result.debug_horizontal_scroll.max_scroll_left,
        `Debug mobile table did not scroll horizontally: ${JSON.stringify(result.debug_horizontal_scroll)}`,
      );
      await captureVisualCheckpoint(
        page,
        debugTableWrap,
        observations,
        "approved-mobile-layouts",
        "debug-mobile-table-after-horizontal-scroll",
      );

      return result;
    },
  },
  {
    id: "runtime-approved-targeted-repair-evidence",
    capabilityId: "dashboard.visual.complete_live_rendering",
    criticality: "P1",
    readOnly: true,
    evidenceOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 15 * 60_000,
    recordVideo: false,
    run: inspectApprovedTargetedRepairEvidence,
  },
  {
    id: "debug-live-runtime-read-evidence",
    capabilityId: "dashboard.shell.runtime_route_navigation",
    criticality: "P1",
    readOnly: true,
    evidenceOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "home");
      const endpointPaths = [
        "/debug/events?limit=200",
        "/debug/state",
        "/debug/messages",
        "/debug/mobile-wearable/ingress",
        "/debug/monitoring",
      ];
      const endpoints = await page.evaluate(async paths => Promise.all(paths.map(async endpoint => {
        try {
          const response = await fetch(endpoint, {cache: "no-store"});
          const body = await response.arrayBuffer();
          return {
            endpoint,
            http_status: response.status,
            content_type: response.headers.get("content-type"),
            body_byte_count: body.byteLength,
            availability_state: response.ok ? "available" : "http_error",
          };
        } catch (error) {
          return {
            endpoint,
            http_status: null,
            content_type: null,
            body_byte_count: null,
            availability_state: "request_error",
            error_class: error?.name || "Error",
          };
        }
      })), endpointPaths);
      const stream = await page.evaluate(async () => {
        const endpoint = "/debug/stream";
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4_000);
        try {
          const response = await fetch(endpoint, {
            cache: "no-store",
            signal: controller.signal,
          });
          const reader = response.body?.getReader?.();
          let firstChunk = null;
          if (reader) {
            firstChunk = await Promise.race([
              reader.read(),
              new Promise(resolve => setTimeout(() => resolve(null), 2_000)),
            ]);
            await reader.cancel().catch(() => undefined);
          }
          return {
            endpoint,
            http_status: response.status,
            content_type: response.headers.get("content-type"),
            first_chunk_observed: Boolean(
              response.ok && firstChunk && !firstChunk.done && firstChunk.value?.byteLength
            ),
            first_chunk_byte_count: firstChunk?.value?.byteLength || 0,
            availability_state: response.ok ? "available" : "http_error",
          };
        } catch (error) {
          return {
            endpoint,
            http_status: null,
            content_type: null,
            first_chunk_observed: false,
            first_chunk_byte_count: 0,
            availability_state: error?.name === "AbortError" ? "timed_out_without_chunk" : "request_error",
            error_class: error?.name || "Error",
          };
        } finally {
          clearTimeout(timer);
        }
      });
      for (const evidence of [...endpoints, stream]) {
        recordBrowserAction(
          observations,
          "observe",
          `debug-read:${evidence.endpoint}`,
          evidence.availability_state,
        );
      }
      return {
        evidence_only: true,
        hardware_readiness_excluded: true,
        debug_ui_route_opened: false,
        endpoints,
        stream,
      };
    },
  },
  {
    id: "runtime-q0063-control-state-evidence",
    capabilityId: "dashboard.browser.complete_control_coverage",
    criticality: "P1",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 15 * 60_000,
    recordVideo: false,
    run: inspectIssue0063ControlStateEvidence,
  },
  {
    id: "runtime-all-visible-controls",
    capabilityId: "dashboard.browser.complete_control_coverage",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 90 * 60_000,
    selfManagedPages: true,
    segmentedTraceByRoute: true,
    recordVideo: false,
    run: auditAllVisibleControls,
  },
  {
    id: "runtime-all-map-surface-interactions",
    capabilityId: "dashboard.maps.all_surface_interactions",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 30 * 60_000,
    run: inspectAllDashboardMapSurfaces,
  },
  {
    id: "runtime-main-map-weather-layer-availability-evidence",
    capabilityId: "dashboard.layers.all_visible_toggle_integrity",
    criticality: "P1",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 10 * 60_000,
    recordVideo: false,
    run: inspectMainMapWeatherLayerAvailability,
  },
  {
    id: "runtime-all-layer-toggle-integrity",
    capabilityId: "dashboard.layers.all_visible_toggle_integrity",
    criticality: "P0",
    readOnly: true,
    fullOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    executionTimeoutMs: 45 * 60_000,
    run: inspectCanonicalLayerToggles,
  },
  {
    id: "diagnostic-controls",
    capabilityId: "dashboard.diagnostic.controls",
    criticality: "P1",
    readOnly: true,
    liveRuntime: true,
    executionTimeoutMs: 15 * 60_000,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "diagnostic");
      const diagnostic = page.locator('[data-diagnostic-page="true"]');
      await diagnostic.waitFor({ state: "visible", timeout: 60_000 });
      assert(await page.locator('[data-diagnostic-action="all"]').count() === 1, "Diag all is missing.");
      const cases = await page.locator("[data-diagnostic-case]").count();
      const retries = await page.locator('[data-diagnostic-action="retest"]').count();
      assert(cases === 37 && retries === 37, `Diagnostic case/retest count is ${cases}/${retries}.`);
      const individualResults = [];
      if (!fixtureHarness) {
        for (let index = 0; index < retries; index += 1) {
          const button = page.locator('[data-diagnostic-action="retest"]').nth(index);
          const caseId = await button.getAttribute("data-diagnostic-id");
          assert(caseId, `Diagnostic retest ${index + 1} has no case ID.`);
          await button.click();
          recordBrowserAction(observations, "click", `diagnostic-retest:${caseId}`);
          await page.waitForFunction(selectedCaseId => {
            const result = window.scoutDashboardDiagnostics?.snapshot?.()?.results?.[selectedCaseId];
            return result && !["idle", "running"].includes(result.status);
          }, caseId, { timeout: 120_000 });
          const result = await page.evaluate(selectedCaseId => (
            window.scoutDashboardDiagnostics.snapshot().results[selectedCaseId]
          ), caseId);
          individualResults.push({ case_id: caseId, ...result });
          recordBrowserAction(observations, "observe", `diagnostic-result:${caseId}`, result.status);
        }
      }
      const individualFailures = individualResults.filter(result => result.status === "failed");
      assert(
        individualFailures.length === 0,
        `Individual Diagnostic retests reported failures: ${JSON.stringify(individualFailures)}`,
      );
      return { cases, retries, individualResults };
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
    id: "permission-live-runtime-boundary",
    capabilityId: "dashboard.permission.fail_closed",
    criticality: "P0",
    readOnly: true,
    liveRuntime: true,
    fixtureEligible: false,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-permission");
      const shell = page.locator("[data-contextual-permission-workbench]").first();
      await shell.waitFor({ state: "attached", timeout: 120_000 });
      await shell.evaluate(node => {
        const states = [{
          state: node.getAttribute("data-contextual-permission-workbench"),
          observed_at_ms: performance.now(),
        }];
        window.__scoutQualificationPermissionStates = states;
        const observer = new MutationObserver(() => {
          const state = node.getAttribute("data-contextual-permission-workbench");
          if (states.at(-1)?.state !== state) {
            states.push({state, observed_at_ms: performance.now()});
          }
        });
        observer.observe(node, {
          attributes: true,
          attributeFilter: ["data-contextual-permission-workbench"],
        });
        window.__scoutQualificationPermissionObserver = observer;
      });
      const runtimeEvidence = await page.evaluate(async selectedProjectId => {
        const readJson = async response => {
          try {
            return await response.json();
          } catch (_error) {
            return null;
          }
        };
        const [projectionResponse, assistantResponse] = await Promise.all([
          fetch(`/admin/pretrip/projects/${encodeURIComponent(selectedProjectId)}/contextual-permission-dashboard`),
          fetch("/assistant/status"),
        ]);
        const [projectionPayload, assistantPayload] = await Promise.all([
          readJson(projectionResponse),
          readJson(assistantResponse),
        ]);
        return {
          projection: {status: projectionResponse.status, payload: projectionPayload},
          assistant: {status: assistantResponse.status, payload: assistantPayload},
        };
      }, readyProjectId);
      let terminalWaitError = null;
      await page.waitForFunction(() => {
        const state = document.querySelector("[data-contextual-permission-workbench]")
          ?.getAttribute("data-contextual-permission-workbench");
        return ["ready", "degraded", "blocked"].includes(state);
      }, null, {timeout: 120_000}).catch(error => {
        terminalWaitError = String(error?.message || error);
      });
      const state = await shell.getAttribute("data-contextual-permission-workbench");
      const observedStateTransitions = await page.evaluate(finalState => {
        window.__scoutQualificationPermissionObserver?.disconnect?.();
        const transitions = window.__scoutQualificationPermissionStates || [];
        return transitions.at(-1)?.state === finalState
          ? transitions
          : [...transitions, {state: finalState, observed_at_ms: performance.now()}];
      }, state);
      const assistantPayload = runtimeEvidence.assistant.payload || {};
      const assistantReadiness = {
        http_status: runtimeEvidence.assistant.status,
        provider: assistantPayload.provider || null,
        provider_class: assistantPayload.provider_class || null,
        startup_connection_status: assistantPayload.startup_connection_status || null,
        read_only: assistantPayload.read_only ?? null,
        workflow_available: assistantPayload.assistant_workflow?.available ?? null,
        workflow_status: assistantPayload.assistant_workflow?.status || null,
        overall_readiness_ok: assistantPayload.assistant_workflow?.overall_readiness_ok ?? null,
        token_values_exposed: assistantPayload.token_values_exposed ?? null,
      };
      assert(!terminalWaitError, `Permission runtime did not reach a typed terminal state: ${terminalWaitError}`);
      assert(["ready", "degraded", "blocked"].includes(state), `Permission runtime state is untyped: ${state}`);
      const candidateOnly = await shell.getAttribute("data-candidate-only");
      if (state !== "blocked") {
        assert(candidateOnly === "true", `Permission ${state} state is not candidate-only.`);
      } else {
        assert((await shell.textContent() || "").trim().length > 0, "Blocked Permission state has no explanation.");
      }
      assert(await page.locator("[data-emergency-review-decision]").count() === 0, "Permission exposes Emergency decisions.");
      const projection = runtimeEvidence.projection;
      recordBrowserAction(observations, "observe", "permission-runtime-state", state, {
        observed_state_transitions: observedStateTransitions,
        assistant_readiness: assistantReadiness,
      });
      return {
        state,
        observedStateTransitions,
        candidateOnly,
        projectionHttpStatus: projection.status,
        projectionStatus: projection.payload?.status || null,
        errorCode: projection.payload?.error?.code || null,
        rebuildEligible: projection.payload?.rebuild?.eligible ?? null,
        rootBlockerIds: (projection.payload?.rebuild?.blockers || [])
          .filter(blocker => blocker.blocker_kind === "root")
          .map(blocker => blocker.blocker_id),
        assistantReadiness,
      };
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
    liveRuntime: true,
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
    id: "weather-optional-rainfall-overlay-empty",
    capabilityId: "dashboard.weather.optional_rainfall_overlay",
    criticality: "P1",
    readOnly: true,
    async run(page, observations) {
      await page.goto(
        `${observations.baseUrl}/admin/pretrip?projectId=${encodeURIComponent(readyProjectId)}`,
        { waitUntil: "domcontentloaded", timeout: 60_000 },
      );
      await page.waitForFunction(() => typeof loadCwaRainfallGridOverlay === "function");
      await page.waitForFunction(selectedProjectId => state.view?.project_id === selectedProjectId, readyProjectId);
      const overlayState = await page.evaluate(async ({ pageProjectId, emptyProjectId }) => {
        const pagePath = `/admin/pretrip/projects/${encodeURIComponent(pageProjectId)}/rainfall-grid-overlay`;
        const emptyPath = `/admin/pretrip/projects/${encodeURIComponent(emptyProjectId)}/rainfall-grid-overlay`;
        const originalFetch = window.fetch.bind(window);
        window.fetch = (input, init) => originalFetch(String(input).replace(pagePath, emptyPath), init);
        try {
          const nextView = await loadCwaRainfallGridOverlay({
            project_id: pageProjectId,
            cwa_qpf: {gridOverlayEndpoint: pagePath},
          });
          return {
            status: nextView.cwa_qpf.grid_overlay_status,
            gridCells: nextView.cwa_qpf.grid_cells,
            emptyReason: nextView.cwa_qpf.grid_overlay_empty_reason,
            boundary: nextView.cwa_qpf.grid_overlay_boundary,
          };
        } finally {
          window.fetch = originalFetch;
        }
      }, { pageProjectId: readyProjectId, emptyProjectId: partialProjectId });
      const overlayResponses = observations.requests.filter(response =>
        response.url.includes(`/admin/pretrip/projects/${partialProjectId}/rainfall-grid-overlay`),
      );
      assert(overlayResponses.some(response => response.status === 200), "Optional rainfall overlay did not return HTTP 200.");
      assert(overlayState.status === "not_prepared", `Optional rainfall overlay status is ${overlayState.status}.`);
      assert(Array.isArray(overlayState.gridCells) && overlayState.gridCells.length === 0, "Optional rainfall overlay fabricated grid cells.");
      assert(overlayState.emptyReason?.code === "rainfall_projection_not_prepared", "Optional rainfall overlay lost its typed empty reason.");
      assert(overlayState.boundary?.candidateOnly === true && overlayState.boundary?.runtimeSafetyTruth === false, "Optional rainfall overlay crossed its candidate-only boundary.");
      return {
        status: overlayState.status,
        gridCellCount: overlayState.gridCells.length,
        emptyReason: overlayState.emptyReason,
        responseStatuses: overlayResponses.map(response => response.status),
      };
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
    liveRuntime: true,
    fullOnly: true,
    recordVideo: false,
    async run(page, observations) {
      await openDashboard(page, observations.baseUrl, readyProjectId, "diagnostic");
      await page.locator('[data-diagnostic-action="all"]').click();
      recordBrowserAction(observations, "click", "diagnostic:diag-all");
      await page.waitForFunction(() => {
        const snapshot = window.scoutDashboardDiagnostics?.snapshot?.();
        return snapshot && snapshot.summary.running === 0 && snapshot.summary.idle === 0;
      }, null, { timeout: 480_000 });
      const snapshot = await page.evaluate(() => window.scoutDashboardDiagnostics.snapshot());
      const zeroCountCategories = await page.evaluate(async () => {
        const project = await diagnosticProjectProjection();
        return diagnosticZeroCountEvidenceCategories(project);
      });
      assert(snapshot.summary.passed + snapshot.summary.warning + snapshot.summary.failed === snapshot.summary.total, "Diag all did not reach terminal states.");
      const failedCases = Object.entries(snapshot.results)
        .filter(([, value]) => value.status === "failed")
        .map(([id, value]) => ({ id, ...value }));
      return {
        summary: snapshot.summary,
        diagnostic_content_status: failedCases.length ? "reported_failures" : "all_checks_non_failing",
        zeroCountCategories,
        unexplainedZeroCount: zeroCountCategories.filter(
          item => item.includes("fixture_or_projection_omission"),
        ).length,
        failedCases,
        warningCases: Object.entries(snapshot.results)
          .filter(([, value]) => value.status === "warning")
          .map(([id, value]) => ({ id, ...value })),
      };
    },
  },
  {
    id: "navigation-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    liveRuntime: true,
    fullOnly: true,
    run: inspectNavigationDynamicRudyTiles,
  },
  {
    id: "architecture-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    liveRuntime: true,
    fullOnly: true,
    run: (page, observations) => inspectNativeDynamicMap(page, observations, { route: "outdoor-architecture", viewportId: "architecture-map", label: "Architecture Map" }),
  },
  {
    id: "weather-dynamic-rudy-tiles",
    capabilityId: "dashboard.maps.dynamic_rudy_tiles",
    criticality: "P0",
    readOnly: true,
    liveRuntime: true,
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
    const required = caseDefinitions.filter(definition => (
      definition.capabilityId === capabilityId && !definition.evidenceOnly
    ));
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

function groupVisualQualityFindings(checkpoints) {
  const grouped = new Map();
  for (const checkpoint of checkpoints) {
    for (const issue of checkpoint.issues || []) {
      const canonical = canonicalVisualIssueSignature(issue);
      const rootSignature = visualIssueRootSignature(issue);
      const key = `${checkpoint.case_id || "unassigned"}:${rootSignature}`;
      const current = grouped.get(key) || {
        finding_kind: "browser_visual_quality_failure",
        case_id: checkpoint.case_id,
        observed_behavior: rootSignature,
        occurrence_count: 0,
        checkpoint_ids: [],
        evidence_refs: [],
        example_observed_behaviors: [],
        disposition: "AWAITING_GPT_PRO_REVIEW",
      };
      grouped.set(key, {
        ...current,
        occurrence_count: current.occurrence_count + 1,
        checkpoint_ids: [...new Set([...current.checkpoint_ids, checkpoint.id].filter(Boolean))],
        evidence_refs: [...new Set([...current.evidence_refs, checkpoint.screenshot].filter(Boolean))],
        example_observed_behaviors: [
          ...new Set([...current.example_observed_behaviors, canonical]),
        ].slice(0, 3),
      });
    }
  }
  return [...grouped.values()];
}

function summarizeRouteVisualAuditFailure(visualAudits, visualIssueGroups) {
  const operationalIssues = [];
  for (const audit of visualAudits || []) {
    if (audit.error) operationalIssues.push(String(audit.error));
    for (const frame of audit.frames || []) {
      if (frame.error) operationalIssues.push(String(frame.error));
    }
  }
  return {
    failed_route_count: (visualAudits || []).filter(audit => audit.error).length,
    operational_issue_count: operationalIssues.length,
    operational_issue_samples: operationalIssues.slice(0, 12),
    visual_issue_group_count: (visualIssueGroups || []).length,
    visual_issue_groups: (visualIssueGroups || []).slice(0, 24).map(group => ({
      observed_behavior: group.observed_behavior,
      occurrence_count: group.occurrence_count,
      evidence_refs: (group.evidence_refs || []).slice(0, 3),
    })),
  };
}

function controlGapReason(control) {
  if (control.coverage_gap_kind) return control.coverage_gap_kind;
  const detail = String(control.detail || "");
  if (/disabled in the selected live runtime state/i.test(detail)) return "runtime_state_disabled";
  if (/only one runtime value/i.test(detail)) return "single_runtime_value";
  if (/changed to a non-visible runtime state/i.test(detail)) return "state_transitioned_nonvisible";
  if (/route_aborted_after_operation_error/i.test(detail)) return "route_aborted_after_operation_error";
  if (/timeout|exceeded \d+ms/i.test(detail)) return "operation_timeout";
  if (/authorization|required before/i.test(detail)) return "authorization_required";
  if (control.terminal_state === "MISSING_AFTER_RELOAD") return "missing_after_fresh_route_reload";
  return detail
    .replace(/q-\d+-[a-f0-9]{8}/gi, "q-<dynamic>")
    .replace(/\d+(?:\.\d+)?/g, "<number>")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160) || String(control.terminal_state || "unknown").toLowerCase();
}

function groupControlCoverageFindings(controlInventory) {
  const blockingStates = new Set([
    ...browserActionContract.control_coverage.blocking_terminal_states,
    "OPERATION_ERROR",
  ]);
  const grouped = new Map();
  for (const control of controlInventory) {
    if (!blockingStates.has(control.terminal_state)) continue;
    const reason = controlGapReason(control);
    const key = [
      control.case_id || "unassigned",
      control.route || "unassigned",
      control.terminal_state,
      reason,
    ].join(":");
    const current = grouped.get(key) || {
      finding_kind: "browser_control_coverage_gap",
      finding_classification: "qualification_coverage_gap",
      product_defect_claimed: false,
      case_id: control.case_id,
      route: control.route,
      terminal_state: control.terminal_state,
      reason,
      observed_behavior: `${control.route}:${control.terminal_state}:${reason}`,
      occurrence_count: 0,
      control_identity_samples: [],
      detail_samples: [],
      evidence_refs: [],
      disposition: "AWAITING_GPT_PRO_REVIEW",
    };
    grouped.set(key, {
      ...current,
      occurrence_count: current.occurrence_count + 1,
      control_identity_samples: [
        ...new Set([...current.control_identity_samples, control.identity].filter(Boolean)),
      ].slice(0, 5),
      detail_samples: [
        ...new Set([...current.detail_samples, control.detail].filter(Boolean)),
      ].slice(0, 3),
      evidence_refs: [
        ...new Set([
          ...current.evidence_refs,
          control.before_screenshot,
          control.after_screenshot,
        ].filter(Boolean)),
      ],
    });
  }
  return [...grouped.values()];
}

function normalizedTelemetryTarget(value) {
  try {
    const parsed = new URL(String(value).replace(/:\d+:\d+$/, ""));
    const queryKeys = [...new Set([...parsed.searchParams.keys()])].sort();
    return `${parsed.pathname}${queryKeys.length ? `?${queryKeys.join("&")}` : ""}`;
  } catch (_error) {
    return String(value || "").slice(0, 240);
  }
}

function groupBrowserTelemetryFindings(consoleErrors, pageErrors, failedRequests) {
  const grouped = new Map();
  const upsert = (key, seed, field) => {
    const current = grouped.get(key) || {
      ...seed,
      network_occurrence_count: 0,
      console_occurrence_count: 0,
      page_occurrence_count: 0,
      example_details: [],
      disposition: "AWAITING_GPT_PRO_REVIEW",
    };
    grouped.set(key, {
      ...current,
      [field]: current[field] + 1,
      example_details: [
        ...new Set([...current.example_details, seed.example_detail].filter(Boolean)),
      ].slice(0, 3),
    });
  };
  for (const item of failedRequests) {
    const target = normalizedTelemetryTarget(item.url);
    const key = `${item.case_id}:http:${item.status}:${target}`;
    upsert(key, {
      finding_kind: "browser_failed_response",
      case_id: item.case_id,
      status: item.status,
      target,
      observed_behavior: `HTTP ${item.status}: ${target}`,
      example_detail: item.url,
    }, "network_occurrence_count");
  }
  for (const item of consoleErrors) {
    const statusMatch = String(item.detail).match(/status of (\d+)/i);
    const urlMatch = String(item.detail).match(/@\s+(https?:\/\/\S+?)(?::\d+:\d+)?$/);
    if (statusMatch && urlMatch) {
      const status = Number(statusMatch[1]);
      const target = normalizedTelemetryTarget(urlMatch[1]);
      const key = `${item.case_id}:http:${status}:${target}`;
      upsert(key, {
        finding_kind: "browser_failed_response",
        case_id: item.case_id,
        status,
        target,
        observed_behavior: `HTTP ${status}: ${target}`,
        example_detail: item.detail,
      }, "console_occurrence_count");
      continue;
    }
    const signature = String(item.detail).replace(/\d+(?:\.\d+)?/g, "<number>");
    upsert(`${item.case_id}:console:${signature}`, {
      finding_kind: "browser_console_error",
      case_id: item.case_id,
      observed_behavior: signature,
      example_detail: item.detail,
    }, "console_occurrence_count");
  }
  for (const item of pageErrors) {
    const signature = String(item.detail).replace(/\d+(?:\.\d+)?/g, "<number>");
    upsert(`${item.case_id}:page:${signature}`, {
      finding_kind: "browser_page_error",
      case_id: item.case_id,
      observed_behavior: signature,
      example_detail: item.detail,
    }, "page_occurrence_count");
  }
  return [...grouped.values()].map(group => {
    const {example_detail: _unused, ...result} = group;
    return result;
  });
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
  const controlInventory = results.flatMap(result => (
    result.observations.controlInventory || result.result?.controlInventory || []
  ).map(item => ({case_id: result.id, ...item})));
  const visualAudits = results.flatMap(result => (
    result.observations.routeVisualAudits || result.result?.visualAudits || []
  ).map(item => ({case_id: result.id, ...item})));
  const visualCheckpoints = results.flatMap(result => (
    result.observations.visualCheckpoints || []
  ).map(item => ({case_id: result.id, ...item})));
  const mapInteractions = results.flatMap(result => (
    result.observations.mapInteractions || result.result?.mapInteractions || []
  ).map(item => ({case_id: result.id, ...item})));
  const layerInteractions = results.flatMap(result => (
    result.observations.layerInteractions || result.result?.layerInteractions || []
  ).map(item => ({case_id: result.id, ...item})));
  const mainMapAvailabilityLayerIds = new Set([
    "antecedent-rain",
    "cwa-qpf",
    "cwa-weather",
    "soil-moisture",
    "weather-api",
  ]);
  const mainMapAvailabilityEvidence = layerInteractions
    .filter(item => item.surface_id === "map" && mainMapAvailabilityLayerIds.has(item.layer_id))
    .map(item => ({
      case_id: item.case_id,
      surface_id: item.surface_id,
      layer_id: item.layer_id,
      terminal_state: item.terminal_state,
      availability_reason: item.availability_reason || item.initial?.availability_reason || null,
      control_present: item.initial?.control_present ?? null,
      control_disabled: item.initial?.control_disabled ?? null,
      control_visible: item.initial?.control_visible ?? null,
      control_label: item.initial?.control_label || null,
      control_title: item.initial?.control_title || null,
      dashboard_weather_layer_hidden: item.initial?.dashboard_weather_layer_hidden || null,
      dashboard_weather_layer_required: item.settled?.dashboard_weather_layer_required
        || item.initial?.dashboard_weather_layer_required
        || null,
      dashboard_weather_layer_availability: item.settled?.dashboard_weather_layer_availability
        || item.initial?.dashboard_weather_layer_availability
        || null,
      dashboard_weather_layer_availability_reason: item.settled?.dashboard_weather_layer_availability_reason
        || item.initial?.dashboard_weather_layer_availability_reason
        || null,
      dashboard_weather_layer_state_text: item.settled?.dashboard_weather_layer_state_text
        || item.initial?.dashboard_weather_layer_state_text
        || null,
      normalized_unavailable_state: item.normalized_unavailable_state || null,
      rendered_item_count: item.initial?.child_count ?? null,
      settled_rendered_item_count: item.settled?.child_count ?? null,
      render_provenance: item.initial?.render_provenance || null,
      projected_availability: item.initial?.projected_availability || null,
      map_frame_boundary: item.map_frame_boundary || null,
      paired_weather_surface_control: item.paired_weather_surface_control || null,
      paired_weather_embedded_state: item.paired_weather_embedded_state || null,
      evidence_semantics: item.evidence_semantics || null,
    }));
  const blockedMutationRequests = results.flatMap(result => (
    result.observations.blockedMutationRequests || []
  ).map(item => ({case_id: result.id, ...item})));
  const controlStateTraces = results.flatMap(result => (
    result.observations.controlStateTraces || []
  ).map(item => ({case_id: result.id, ...item})));
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
  writeJson(outputRoot, "browser-action-log.json", {
    schema: "scout.dashboardQualificationBrowserActionLog.v1",
    actions: results.flatMap(result => result.observations.browserActions.map(action => ({
      case_id: result.id,
      ...action,
    }))),
  });
  writeJson(outputRoot, "browser-control-inventory.json", {
    schema: "scout.dashboardQualificationControlInventory.v1",
    contract_tests_are_dashboard_evidence: false,
    zero_unmapped_controls_required: true,
    controls: controlInventory,
  });
  writeJson(outputRoot, "browser-control-state-traces.json", {
    schema: "scout.dashboardQualificationControlStateTraces.v1",
    issue_id: "SCOUT-Q-0063",
    product_behavior_changed: false,
    permission_reload_stability: controlStateTraces.filter(item => item.route === "outdoor-permission"),
    runtime_audit_terminal_content: controlStateTraces.filter(item => item.route === "runtime-audit"),
    weather_frame_lifecycle: controlStateTraces.filter(item => (
      item.route === "outdoor-weather" && ["frame_lifecycle", "frame_lifecycle_owner", "control_state", "network_completion"].includes(item.kind)
    )),
    emergency_discovery_timing: controlStateTraces.filter(item => (
      item.route === "emergency" && ["control_discovery_timing", "control_state", "network_completion"].includes(item.kind)
    )),
  });
  writeJson(outputRoot, "browser-visual-audit.json", {
    schema: "scout.dashboardQualificationVisualAudit.v1",
    independent_visual_review_required: true,
    route_audits: visualAudits,
    checkpoints: visualCheckpoints,
  });
  writeJson(outputRoot, "browser-map-interactions.json", {
    schema: "scout.dashboardQualificationMapInteractions.v1",
    required_surfaces: browserActionContract.map_surfaces,
    required_gestures: browserActionContract.required_map_gestures,
    interactions: mapInteractions,
  });
  writeJson(outputRoot, "browser-layer-interactions.json", {
    schema: "scout.dashboardQualificationLayerInteractions.v1",
    all_exposed_layer_controls_must_be_toggled: true,
    interactions: layerInteractions,
  });
  writeJson(outputRoot, "browser-layer-availability-evidence.json", {
    schema: "scout.dashboardQualificationLayerAvailabilityEvidence.v1",
    issue_id: "SCOUT-Q-0057",
    product_behavior_changed: false,
    contract_observation: {
      all_exposed_layer_controls_must_be_toggled: browserActionContract.required_map_content.all_exposed_layer_controls_must_be_toggled,
      per_surface_availability_contract_declared: false,
      interpretation: "Evidence only: hidden or disabled state is not attributed as a product defect without a typed per-surface contract and projected server reason.",
    },
    records: mainMapAvailabilityEvidence,
  });
  writeJson(outputRoot, "network/blocked-mutation-requests.json", {
    schema: "scout.dashboardQualificationBlockedMutationRequests.v1",
    requests: blockedMutationRequests,
  });
  writeJson(outputRoot, "coverage-map.json", {
    schema: "scout.dashboardQualificationCoverageMap.v1",
    browser_action_contract_sha256: sha256(fs.readFileSync(browserActionContractPath)),
    contract_tests_are_dashboard_evidence: false,
    required_route_count: browserActionContract.routes.length,
    required_map_surface_count: browserActionContract.map_surfaces.length,
    observed_control_count: controlInventory.length,
    visual_checkpoint_count: visualCheckpoints.length,
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
  const diagnosticWarnings = results
    .flatMap(result => result.result?.warningCases || [])
    .map(warning => ({
      finding_kind: "runtime_diagnostic_warning",
      case_id: warning.id,
      observed_behavior: warning.detail,
      disposition: "EXPECTED_TYPED_WARNING",
    }));
  const individualDiagnosticFindings = results
    .flatMap(result => result.result?.individualResults || [])
    .filter(result => ["failed", "warning"].includes(result.status))
    .map(result => ({
      finding_kind: result.status === "failed"
        ? "runtime_diagnostic_individual_failure"
        : "runtime_diagnostic_individual_warning",
      case_id: result.case_id,
      observed_behavior: result.detail,
      disposition: result.status === "failed"
        ? "AWAITING_GPT_PRO_REVIEW"
        : "EXPECTED_TYPED_WARNING",
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
  const browserTelemetryFindings = groupBrowserTelemetryFindings(
    consoleErrors,
    pageErrors,
    failedRequests,
  );
  const browserCoverageFindings = [
    ...groupControlCoverageFindings(controlInventory),
    ...groupVisualQualityFindings(visualCheckpoints),
    ...mapInteractions
      .filter(item => item.error)
      .map(item => ({
        finding_kind: "browser_map_interaction_failure",
        case_id: item.case_id,
        observed_behavior: item.error,
        disposition: "AWAITING_GPT_PRO_REVIEW",
      })),
    ...layerInteractions
      .filter(item => ["FAIL", "NOT_EXERCISED"].includes(item.terminal_state))
      .map(item => ({
        finding_kind: "browser_layer_interaction_failure",
        case_id: item.case_id,
        observed_behavior: item.error,
        disposition: "AWAITING_GPT_PRO_REVIEW",
      })),
    ...blockedMutationRequests.map(item => ({
      finding_kind: "browser_effect_coverage_requires_authorization",
      case_id: item.case_id,
      observed_behavior: `${item.method} ${item.url}`,
      disposition: "AWAITING_GPT_PRO_REVIEW",
    })),
  ];
  const findings = [
    ...browserFailures,
    ...diagnosticFailures,
    ...diagnosticWarnings,
    ...individualDiagnosticFindings,
    ...browserTelemetryFindings,
    ...browserCoverageFindings,
  ]
    .map((finding, index) => ({
      candidate_finding_id: `SCOUT-CANDIDATE-${String(index + 1).padStart(4, "0")}`,
      confirmation_state: "AWAITING_GPT_PRO_REVIEW",
      issue_record_allowed: false,
      ...finding,
    }));
  writeJson(outputRoot, "exploratory-findings.json", {
    schema: "scout.dashboardQualificationExploratoryFindings.v1",
    findings,
    operator_final_verdict_allowed: false,
  });
  writeJson(outputRoot, "candidate-findings.json", {
    schema: "scout.dashboardQualificationCandidateFindings.v1",
    findings,
    confirmation_required_from: "gpt-pro-collaboration-in-app-browser",
    canonical_review_items_written: false,
    remediation_authorized: false,
    specification_change_authorized: false,
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
      cases: results.map(result => {
        const evidenceRefs = directory === "traces"
          ? (result.evidence.traces || [result.evidence[evidenceKey]].filter(Boolean))
          : [result.evidence[evidenceKey]].filter(Boolean);
        return {
          case_id: result.id,
          evidence_ref: evidenceRefs[0] || null,
          evidence_refs: evidenceRefs,
        };
      }),
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
  const commit = spawnSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).stdout.trim();
  const runId = `${commit.slice(0, 12)}-${new Date().toISOString().replace(/[:.]/g, "-")}`;
  const outputRoot = outputArgument
    ? path.resolve(outputArgument.split("=", 2)[1])
    : path.join(repoRoot, "artifacts", "qualification", "runs", runId);
  fs.mkdirSync(outputRoot, { recursive: true });
  const python = process.env.SCOUT_PYTHON || path.join(repoRoot, "venv/bin/python");
  const expectedLayerIds = loadExpectedPretripLayerIds(python);
  writeJson(outputRoot, "browser-action-contract.snapshot.json", browserActionContract);
  let workspaceRoot = null;
  let baseUrl = null;
  let disabledBaseUrl = null;
  let server = null;
  let disabledServer = null;
  let initialRuntimeAttestation = null;
  let runtimeAttestation = null;
  const serverErrors = [];
  if (fixtureHarness) {
    workspaceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "scout-dashboard-qualification-"));
    const seedResult = spawnSync(
      python,
      ["-m", "scripts.qualification.seed_dashboard_fixture", "--workspace-root", workspaceRoot, "--output", path.join(outputRoot, "fixture-seed.json")],
      { cwd: repoRoot, encoding: "utf8" },
    );
    if (seedResult.status !== 0) throw new Error(seedResult.stderr || seedResult.stdout || "fixture seed failed");
    const port = await freePort();
    const disabledPort = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    disabledBaseUrl = `http://127.0.0.1:${disabledPort}`;
    server = spawnDashboardServer(python, port, workspaceRoot, "enabled");
    disabledServer = spawnDashboardServer(python, disabledPort, workspaceRoot, "disabled");
    server.stderr.on("data", chunk => serverErrors.push(`enabled: ${String(chunk)}`));
    disabledServer.stderr.on("data", chunk => serverErrors.push(`disabled: ${String(chunk)}`));
    writeJson(outputRoot, "fixture-harness-attestation.json", {
      schema: "scout.dashboardFixtureHarnessAttestation.v1",
      fixture_provenance: "bounded_synthetic_workspace",
      official_qualification_eligible: false,
      trusted_baseline_eligible: false,
      issue_confirmation_eligible: false,
      runtime_safety_truth: false,
    });
  } else {
    baseUrl = normalizeRuntimeBaseUrl(configuredRuntimeUrl);
    initialRuntimeAttestation = await attestLiveRuntime(baseUrl, readyProjectId, "initial");
    workspaceRoot = initialRuntimeAttestation.workspaceRoot;
  }
  let browser;
  try {
    if (fixtureHarness) {
      await Promise.all([
        waitForServer(`${baseUrl}/admin/dashboard`),
        waitForServer(`${disabledBaseUrl}/admin/dashboard`),
      ]);
    } else {
      await waitForServer(`${baseUrl}/admin/dashboard?projectId=${encodeURIComponent(readyProjectId)}`);
    }
    browser = await chromiumLauncher().launch({
      headless: true,
      ...(browserExecutable ? { executablePath: browserExecutable } : {}),
    });
    const definitions = caseDefinitions.filter(definition =>
      (scope === "full" || !definition.fullOnly)
      && (fixtureHarness ? definition.fixtureEligible !== false : definition.liveRuntime === true)
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
        expectedLayerIds,
      }));
    }
    if (!fixtureHarness) {
      const finalRuntimeAttestation = await attestLiveRuntime(baseUrl, readyProjectId, "final");
      const initial = initialRuntimeAttestation.publicEvidence;
      const final = finalRuntimeAttestation.publicEvidence;
      const listenerStable = initial.local_listener_pid_required
        ? Boolean(
          initial.local_listener_pid
          && final.local_listener_pid
          && initial.local_listener_pid === final.local_listener_pid
        )
        : true;
      const continuityVerified = (
        initial.runtime_base_url === final.runtime_base_url
        && initial.project_id === final.project_id
        && initial.dashboard_html_sha256 === final.dashboard_html_sha256
        && initial.workspace_root_path_sha256 === final.workspace_root_path_sha256
        && listenerStable
      );
      runtimeAttestation = {
        schema: "scout.dashboardRuntimeContinuityAttestation.v1",
        runtime_provenance: "live_operational_dashboard",
        runner_started_runtime: false,
        official_qualification_eligible: continuityVerified,
        continuity_verified: continuityVerified,
        continuity_checks: {
          same_base_url: initial.runtime_base_url === final.runtime_base_url,
          same_project_id: initial.project_id === final.project_id,
          same_dashboard_html: initial.dashboard_html_sha256 === final.dashboard_html_sha256,
          same_workspace_root: initial.workspace_root_path_sha256 === final.workspace_root_path_sha256,
          same_local_listener_pid: listenerStable,
        },
        initial,
        final,
        runtime_safety_truth: false,
      };
      writeJson(outputRoot, "runtime-attestation.json", runtimeAttestation);
      if (!continuityVerified) {
        results.push({
          id: "runtime-continuity",
          capability_id: "dashboard.shell.runtime_route_navigation",
          criticality: "P0",
          status: "FAIL",
          detail: "Real runtime continuity could not be proven for the entire browser round.",
          result: runtimeAttestation.continuity_checks,
          mutation_paths: [],
          observations: { consoleErrors: [], pageErrors: [], failedResponses: [], requests: [], browserActions: [] },
          evidence: { trace: null, screenshot: null, video_directory: null },
        });
      }
    }
    const capabilityResults = buildCapabilityResults(definitions, results);
    if (!fixtureHarness && runtimeAttestation?.continuity_verified === false) {
      capabilityResults["dashboard.shell.runtime_route_navigation"] = "FAIL";
    }
    const report = {
      schema: "scout.dashboardBrowserQualification.v1",
      commit_sha: commit,
      run_id: runId,
      scope,
      browser_executable: browserExecutable || "playwright-managed",
      runtime_provenance: fixtureHarness ? null : "live_operational_dashboard",
      fixture_provenance: fixtureHarness ? "bounded_synthetic_workspace" : null,
      runtime_base_url: fixtureHarness ? null : baseUrl,
      runtime_project_id: fixtureHarness ? null : readyProjectId,
      runtime_continuity_verified: fixtureHarness ? false : Boolean(runtimeAttestation?.continuity_verified),
      runner_started_runtime: fixtureHarness,
      official_qualification_eligible: !fixtureHarness && Boolean(runtimeAttestation?.continuity_verified),
      browser_action_contract_sha256: sha256(fs.readFileSync(browserActionContractPath)),
      contract_tests_are_dashboard_evidence: false,
      live_browser_counts: {
        required_routes: browserActionContract.routes.length,
        required_map_surfaces: browserActionContract.map_surfaces.length,
        required_map_gestures_per_surface: browserActionContract.required_map_gestures.length,
        discovered_controls: results.reduce((count, result) => count + (result.observations.controlInventory || []).length, 0),
        embedded_frame_controls: results.reduce((count, result) => count + (result.observations.controlInventory || [])
          .filter(item => item.context_id && item.context_id !== "main").length, 0),
        operated_controls: results.reduce((count, result) => count + (result.observations.controlInventory || [])
          .filter(item => item.terminal_state === "OPERATED").length, 0),
        delegated_controls: results.reduce((count, result) => count + (result.observations.controlInventory || [])
          .filter(item => item.terminal_state === "DELEGATED").length, 0),
        blocking_control_gaps: results.reduce((count, result) => count + (result.observations.controlInventory || [])
          .filter(item => browserActionContract.control_coverage.blocking_terminal_states.includes(item.terminal_state)
            || item.terminal_state === "VISUAL_QUALITY_FAILURE"
            || item.terminal_state === "OPERATION_ERROR").length, 0),
        map_surface_results: results.reduce((count, result) => count + (result.observations.mapInteractions || []).length, 0),
        completed_map_surface_results: results.reduce((count, result) => count + (result.observations.mapInteractions || [])
          .filter(item => !item.error).length, 0),
        layer_results: results.reduce((count, result) => count + (result.observations.layerInteractions || []).length, 0),
        operated_layer_results: results.reduce((count, result) => count + (result.observations.layerInteractions || [])
          .filter(item => item.terminal_state === "OPERATED").length, 0),
        blocking_layer_gaps: results.reduce((count, result) => count + (result.observations.layerInteractions || [])
          .filter(item => ![
            "OPERATED",
            "NOT_EXPOSED",
            "REQUIRED_AVAILABLE",
            "REQUIRED_NA",
          ].includes(item.terminal_state)).length, 0),
        visual_checkpoints: results.reduce((count, result) => count + (result.observations.visualCheckpoints || []).length, 0),
      },
      capability_results: capabilityResults,
      results,
      server_errors: serverErrors,
      candidate_findings_only: true,
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
    if (browser) {
      try {
        await runCaseFinalizerWithTimeout("browser-close", () => browser.close());
      } catch (error) {
        process.stderr.write(`Browser cleanup failed: ${error.stack || error}\n`);
        process.exitCode = 1;
      }
    }
    if (fixtureHarness) {
      await stopServer(server);
      await stopServer(disabledServer);
      if (workspaceRoot) fs.rmSync(workspaceRoot, { recursive: true, force: true });
    }
  }
}

module.exports = {
  aggregateDelegatedMapEvidenceControls,
  classifyPassiveControl,
  controlCoverageGapRecord,
  controlOperationTerminalState,
  dashboardRouteRootSelector,
  groupBrowserTelemetryFindings,
  groupControlCoverageFindings,
  groupVisualQualityFindings,
  isLoadedPopupUrl,
  isTransientControlLocatorError,
  isTransientFrameDiscoveryError,
  runCaseExecutionWithTimeout,
  runCaseFinalizerWithTimeout,
  sampleRepeatedSelectionControls,
  summarizeRouteVisualAuditFailure,
  summarizeControlCoverageFailure,
  visualIssueRootSignature,
};

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
}
