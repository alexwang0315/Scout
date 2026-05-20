from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent
READ_ONLY_BOUNDARY = "read-only model interpretation"
EXPECTED_OFFLINE_FALLBACK_TEXT = "No offline fallback schema returned."
FORBIDDEN_ACTION_BUTTON_TOKENS = (
    "accept",
    "approve",
    "reject",
    "send",
    "write",
    "mutate",
    "control",
)
ASSISTANT_BROWSER_SURFACES = (
    {
        "name": "debug",
        "path": "/admin/debug",
        "expected_surface": "debug",
    },
    {
        "name": "pretrip",
        "path": "/admin/pretrip?tileSource=local",
        "expected_surface": "pretrip",
    },
    {
        "name": "admin",
        "path": "/admin",
        "expected_surface": "admin",
    },
    {
        "name": "hardware_readiness",
        "path": "/admin/hardware-readiness",
        "expected_surface": "hardware_readiness",
    },
)
ASSISTANT_BROWSER_VIEWPORTS = (
    {"name": "desktop", "width": 1440, "height": 1000},
    {"name": "mobile", "width": 390, "height": 844},
)


NODE_BROWSER_SMOKE_SCRIPT = r"""
(async () => {
  const { chromium } = require("playwright");
  const config = JSON.parse(process.env.SCOUT_BROWSER_SMOKE_CONFIG || "{}");
  const browser = await chromium.launch({headless: true});
  const observations = [];

  async function collectPageData(page, forbiddenTokens) {
    return await page.evaluate((forbiddenTokens) => {
      const shell = document.querySelector("[data-assistant-surface]");
      const offline = document.querySelector("#assistantOfflineFallbackList");
      const html = document.documentElement;
      const scrollEl = document.scrollingElement || html;
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const buttonInfo = shell
        ? Array.from(shell.querySelectorAll("button")).map((button) => {
            const text = [
              button.textContent,
              button.getAttribute("aria-label"),
              button.getAttribute("title"),
              button.getAttribute("value"),
              button.getAttribute("data-assistant-question"),
            ]
              .filter(Boolean)
              .join(" ")
              .replace(/\s+/g, " ")
              .trim();
            const words = new Set((text.toLowerCase().match(/[a-z]+/g) || []));
            return {label: text, forbidden: forbiddenTokens.filter((token) => words.has(token))};
          })
        : [];
      return {
        status: document.readyState,
        documentScroll: {
          clientWidth: html.clientWidth,
          scrollWidth: html.scrollWidth,
          horizontalOverflowPx: Math.max(0, html.scrollWidth - html.clientWidth),
          clientHeight: scrollEl.clientHeight,
          scrollHeight: scrollEl.scrollHeight,
        },
        shellPresent: Boolean(shell),
        shellSurface: shell?.getAttribute("data-assistant-surface") || null,
        boundary: shell?.getAttribute("data-assistant-boundary") || null,
        shellVisible: visible(shell),
        offlineVisible: visible(offline),
        offlineText: offline?.textContent.replace(/\s+/g, " ").trim() || null,
        assistantButtonCount: buttonInfo.length,
        forbiddenButtons: buttonInfo.filter((item) => item.forbidden.length),
      };
    }, forbiddenTokens);
  }

  async function collectPretripDetail(page) {
    return await page.evaluate(() => ({
      tabs: Array.from(document.querySelectorAll(".tab-button")).map((button) => ({
        text: button.textContent.replace(/\s+/g, " ").trim(),
        selected: button.getAttribute("aria-selected"),
        className: button.className,
      })),
      title: document.getElementById("detailTitle")?.textContent || "",
      source: document.getElementById("detailSource")?.textContent || "",
      summary: Array.from(document.querySelectorAll("#tabSummary div")).map((node) => node.textContent.replace(/\s+/g, " ").trim()),
      sectionCount: document.querySelectorAll("#sectionList .section-card").length,
      assistantScroll: (() => {
        const el = document.getElementById("assistantPanel");
        return el ? {clientHeight: el.clientHeight, scrollHeight: el.scrollHeight, overflowY: getComputedStyle(el).overflowY} : null;
      })(),
    }));
  }

  for (const viewport of config.viewports || []) {
    for (const surface of config.surfaces || []) {
      const context = await browser.newContext({
        viewport: {width: viewport.width, height: viewport.height},
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await page.goto(`${config.baseUrl}${surface.path}`, {waitUntil: "domcontentloaded", timeout: config.timeoutMs || 20000});
      await page.waitForTimeout(config.settleMs || 800);
      if (surface.name === "pretrip") {
        try {
          await page.waitForSelector("#sectionList .section-card", {timeout: config.timeoutMs || 20000});
        } catch (error) {
          // Keep the observation; Python-side evaluation will report the missing sections.
        }
      }
      const data = await collectPageData(page, config.forbiddenActionButtonTokens || []);
      let pretripTabCheck = null;
      if (surface.name === "pretrip") {
        const before = await collectPretripDetail(page);
        await page.locator("#postAnalysisTab").click({timeout: config.timeoutMs || 20000});
        await page.waitForTimeout(200);
        const afterPost = await collectPretripDetail(page);
        await page.locator("#preTripTab").click({timeout: config.timeoutMs || 20000});
        await page.waitForTimeout(200);
        const afterPre = await collectPretripDetail(page);
        pretripTabCheck = {before, afterPost, afterPre};
      }
      observations.push({
        surface: surface.name,
        path: surface.path,
        expectedSurface: surface.expected_surface,
        viewport: viewport.name,
        viewportSize: {width: viewport.width, height: viewport.height},
        consoleErrors,
        pageErrors,
        pretripTabCheck,
        ...data,
      });
      await context.close();
    }
  }

  await browser.close();
  console.log(JSON.stringify(observations));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""


def build_assistant_browser_smoke_check(
    *,
    base_url: str,
    observations: Sequence[dict[str, Any]],
    surfaces: Sequence[dict[str, Any]] = ASSISTANT_BROWSER_SURFACES,
    viewports: Sequence[dict[str, Any]] = ASSISTANT_BROWSER_VIEWPORTS,
) -> dict[str, Any]:
    observed_by_key = {
        (str(item.get("surface")), str(item.get("viewport"))): item
        for item in observations
    }
    missing_required: list[str] = []
    checks: list[dict[str, Any]] = []

    for viewport in viewports:
        for surface in surfaces:
            key = (str(surface["name"]), str(viewport["name"]))
            observation = observed_by_key.get(key)
            if observation is None:
                missing_required.append(f"observation_missing:{key[0]}:{key[1]}")
                continue
            check_missing = _missing_observation_requirements(surface, viewport, observation)
            missing_required.extend(check_missing)
            checks.append(
                {
                    "surface": key[0],
                    "viewport": key[1],
                    "ok": not check_missing,
                    "missing": check_missing,
                    "horizontalOverflowPx": observation.get("documentScroll", {}).get("horizontalOverflowPx"),
                }
            )

    failed_checks = [
        f"{check['surface']}:{check['viewport']}"
        for check in checks
        if not check["ok"]
    ]
    missing_required = sorted(set(missing_required))
    return {
        "ok": not missing_required,
        "base_url": base_url,
        "check": "assistant_browser_smoke",
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_required_artifacts": missing_required,
        "observations": list(observations),
    }


def run_assistant_browser_smoke_check(
    *,
    base_url: str,
    node_executable: str,
    node_path: str | None,
    timeout_ms: int,
    process_timeout_sec: int,
) -> dict[str, Any]:
    config = {
        "baseUrl": base_url.rstrip("/"),
        "surfaces": list(ASSISTANT_BROWSER_SURFACES),
        "viewports": list(ASSISTANT_BROWSER_VIEWPORTS),
        "forbiddenActionButtonTokens": list(FORBIDDEN_ACTION_BUTTON_TOKENS),
        "timeoutMs": timeout_ms,
        "settleMs": 800,
    }
    env = dict(os.environ)
    env["SCOUT_BROWSER_SMOKE_CONFIG"] = json.dumps(config)
    if node_path:
        env["NODE_PATH"] = (
            node_path
            if not env.get("NODE_PATH")
            else f"{node_path}{os.pathsep}{env['NODE_PATH']}"
        )

    try:
        completed = subprocess.run(
            [node_executable],
            input=NODE_BROWSER_SMOKE_SCRIPT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=process_timeout_sec,
        )
    except FileNotFoundError as exc:
        return _runtime_failure(base_url, f"browser_runtime:node_not_found:{exc}")
    except subprocess.TimeoutExpired as exc:
        return _runtime_failure(base_url, f"browser_runtime:timeout:{exc}")

    if completed.returncode != 0:
        stderr = " ".join(completed.stderr.split())
        if "Cannot find module 'playwright'" in completed.stderr or "Module not found: playwright" in completed.stderr:
            reason = "browser_runtime:playwright_unavailable"
        else:
            reason = "browser_runtime:node_failed"
        return _runtime_failure(base_url, reason, stderr)

    try:
        observations = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _runtime_failure(base_url, f"browser_runtime:invalid_json:{exc}", completed.stdout[-500:])

    if not isinstance(observations, list):
        return _runtime_failure(base_url, "browser_runtime:invalid_observation_shape")

    return build_assistant_browser_smoke_check(base_url=base_url, observations=observations)


def _missing_observation_requirements(
    surface: dict[str, Any],
    viewport: dict[str, Any],
    observation: dict[str, Any],
) -> list[str]:
    surface_name = str(surface["name"])
    viewport_name = str(viewport["name"])
    prefix = f"{surface_name}:{viewport_name}"
    missing: list[str] = []

    if observation.get("consoleErrors"):
        missing.append(f"{prefix}:console_errors")
    if observation.get("pageErrors"):
        missing.append(f"{prefix}:page_errors")
    if observation.get("status") != "complete":
        missing.append(f"{prefix}:document_not_complete")
    if observation.get("shellPresent") is not True:
        missing.append(f"{prefix}:assistant_shell_missing")
    if observation.get("shellSurface") != surface.get("expected_surface"):
        missing.append(f"{prefix}:assistant_surface_mismatch")
    if observation.get("boundary") != READ_ONLY_BOUNDARY:
        missing.append(f"{prefix}:read_only_boundary_missing")
    if observation.get("shellVisible") is not True:
        missing.append(f"{prefix}:assistant_shell_not_visible")
    if observation.get("offlineVisible") is not True:
        missing.append(f"{prefix}:offline_fallback_not_visible")
    if EXPECTED_OFFLINE_FALLBACK_TEXT not in str(observation.get("offlineText") or ""):
        missing.append(f"{prefix}:offline_fallback_placeholder_missing")
    if int(observation.get("assistantButtonCount") or 0) < 1:
        missing.append(f"{prefix}:assistant_query_button_missing")
    if observation.get("forbiddenButtons"):
        missing.append(f"{prefix}:forbidden_action_buttons")

    document_scroll = observation.get("documentScroll") or {}
    if int(document_scroll.get("horizontalOverflowPx") or 0) != 0:
        missing.append(f"{prefix}:horizontal_overflow:{document_scroll.get('horizontalOverflowPx')}")

    if surface_name == "pretrip":
        missing.extend(_missing_pretrip_tab_requirements(prefix, viewport_name, observation))

    return missing


def _missing_pretrip_tab_requirements(
    prefix: str,
    viewport_name: str,
    observation: dict[str, Any],
) -> list[str]:
    tab_check = observation.get("pretripTabCheck") or {}
    after_post = tab_check.get("afterPost") or {}
    after_pre = tab_check.get("afterPre") or {}
    missing: list[str] = []

    if after_post.get("title") != "Post-analysis overview":
        missing.append(f"{prefix}:post_analysis_tab_did_not_render")
    if int(after_post.get("sectionCount") or 0) < 1:
        missing.append(f"{prefix}:post_analysis_sections_missing")
    if after_pre.get("title") != "Pre-trip planning overview":
        missing.append(f"{prefix}:pretrip_tab_did_not_restore")
    if int(after_pre.get("sectionCount") or 0) < 1:
        missing.append(f"{prefix}:pretrip_sections_missing")

    assistant_scroll = after_pre.get("assistantScroll") or after_post.get("assistantScroll") or {}
    if viewport_name == "desktop":
        if assistant_scroll.get("overflowY") != "auto":
            missing.append(f"{prefix}:assistant_panel_not_scrollable")
        if int(assistant_scroll.get("scrollHeight") or 0) <= int(assistant_scroll.get("clientHeight") or 0):
            missing.append(f"{prefix}:assistant_panel_scroll_height_not_larger")

    return missing


def _runtime_failure(base_url: str, reason: str, detail: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "base_url": base_url,
        "check": "assistant_browser_smoke",
        "checks": [],
        "failed_checks": ["browser_runtime"],
        "missing_required_artifacts": [reason],
        "runtime_error": detail,
        "observations": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Scout assistant browser smoke gate against a running local server."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9110")
    parser.add_argument("--node", default=os.getenv("SCOUT_BROWSER_NODE", "node"))
    parser.add_argument("--node-path", default=os.getenv("SCOUT_BROWSER_NODE_PATH"))
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--process-timeout-sec", type=int, default=90)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = run_assistant_browser_smoke_check(
        base_url=args.base_url,
        node_executable=args.node,
        node_path=args.node_path,
        timeout_ms=args.timeout_ms,
        process_timeout_sec=args.process_timeout_sec,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
