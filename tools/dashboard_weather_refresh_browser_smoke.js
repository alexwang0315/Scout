#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const {chromium} = require("playwright");

const baseUrl = process.env.SCOUT_WEATHER_REFRESH_URL
  || "http://127.0.0.1:9099/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport#outdoor-weather";
const outputDir = process.env.SCOUT_WEATHER_REFRESH_OUTPUT_DIR
  || "artifacts/browser/dashboard-weather-refresh";
const project = new URL(baseUrl).searchParams.get("projectId");
const prefix = `/admin/pretrip/projects/${encodeURIComponent(project)}`;
const assert = (condition, message) => {if (!condition) throw new Error(message);};

async function main() {
  const initialResponse = await fetch(new URL(`${prefix}/weather-dashboard`, baseUrl));
  assert(initialResponse.ok, "Cached Weather API is unavailable.");
  const cached = await initialResponse.json();
  fs.mkdirSync(outputDir, {recursive: true});
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.SCOUT_BROWSER_EXECUTABLE ? {executablePath: process.env.SCOUT_BROWSER_EXECUTABLE} : {}),
  });
  const events = [];
  const blockedWrites = [];
  const pageErrors = [];
  const scenarios = [];
  let run = 0;
  let polls = 0;
  let completedAt = null;
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.on("pageerror", error => pageErrors.push(error.message));
    await page.route("**/*", route => {
      if (["GET", "HEAD"].includes(route.request().method())) return route.continue();
      blockedWrites.push(route.request().url());
      return route.abort("blockedbyclient");
    });
    await page.route(`**${prefix}/connected-preparation`, async route => {
      if (route.request().method() === "POST") {
        const payload = route.request().postDataJSON();
        assert(payload.reason === "operator-refresh" && payload.force === true, "Refresh did not request a forced server update.");
        run += 1;
        polls = 0;
        completedAt = null;
        events.push({run, event: "refresh-post-intercepted"});
        return route.fulfill({json: {projectId: project, status: "queued", runCount: run}});
      }
      if (!run) return route.fulfill({json: {projectId: project, status: "idle", runCount: 0}});
      polls += 1;
      if (polls < 2) return route.fulfill({json: {projectId: project, status: "running", runCount: run}});
      completedAt ||= new Date().toISOString();
      events.push({run, event: "preparation-complete", completedAt});
      return route.fulfill({json: {
        projectId: project, status: run === 2 ? "partial" : "ready", completedAt, runCount: run,
        weatherDecisionInputs: {status: run === 2 ? "incomplete" : "current_run"},
      }});
    });
    await page.route(`**${prefix}/weather-dashboard`, async route => {
      events.push({run, event: "decision-get", afterCompletion: Boolean(completedAt)});
      if (run === 3 && completedAt) return route.fulfill({status: 503, json: {detail: "Controlled Decision API failure"}});
      const fresh = run === 1 && completedAt;
      const result = structuredClone(cached);
      result.status = fresh ? "ready" : "stale_data";
      result.evaluatedAt = new Date().toISOString();
      result.decision = {...result.decision, candidateDecision: fresh ? "CHANGE_PLAN" : "DELAY"};
      if (fresh) {
        result.decision.summary = "Controlled replay: refreshed weather evidence changed the candidate.";
        result.rainfall.pairId = "fixture-rainfall-new";
        result.imagery.pairId = "fixture-imagery-new";
        result.routeRisk.generatedAt = completedAt;
      }
      return route.fulfill({json: result});
    });
    await page.goto(baseUrl, {waitUntil: "domcontentloaded"});
    await page.locator('[data-route="outdoor-weather"]').first().click();
    await page.waitForFunction(() => state.weatherData?.decisionReview?.status === "reevaluated");
    for (const expected of ["CHANGE_PLAN", "DELAY", null]) {
      await page.locator('[data-weather-refresh-primary="true"]').click();
      await page.waitForFunction(() => ["queued", "running"].includes(state.connectedPreparation?.status));
      const expectedRun = run;
      assert(await page.locator('[data-weather-refresh-primary="true"]').isDisabled(), "Refresh button was not held busy.");
      await page.waitForFunction(({expectedRun, expected}) => {
        const review = state.weatherData?.decisionReview;
        return state.connectedPreparation?.runCount === expectedRun
          && (expected === null ? review?.status === "failed"
            : review?.status === "reevaluated" && Boolean(review.preparationCompletedAt)
              && state.weatherData?.decision?.candidateDecision === expected);
      }, {expectedRun, expected}, {timeout: 60000});
      const actual = await page.evaluate(() => ({
        decision: state.weatherData.decision?.candidateDecision || null,
        review: state.weatherData.decisionReview,
        statusText: document.querySelector('[data-weather-refresh-status="primary"]')?.textContent,
      }));
      assert(actual.decision === expected, "Decision candidate did not update.");
      if (expected !== null) {
        assert(Date.parse(actual.review.evaluatedAt) >= Date.parse(completedAt), "Decision predates preparation completion.");
        assert(actual.statusText.includes("Decision API 已重新審視"), "Reassessment confirmation was missing.");
      }
      if (expected === "DELAY") {
        assert(actual.statusText.includes("資料仍過期"), "Stale evidence was presented as a successful current update.");
        assert(await page.locator('[data-weather-historical-evidence="true"]').count() === 1, "Historical analysis was not disclosed.");
        assert(!(await page.locator('[data-weather-critical-window="true"]').textContent()).includes("min estimated arrival"),
          "Expired arrival estimate was still shown as a current critical window.");
      }
      if (expected === null) {
        assert(actual.statusText.includes("Decision API 重審失敗"), "Failed reassessment was presented as success.");
        assert((await page.locator(".weather-decision-primary > strong").textContent()) === "UNAVAILABLE",
          "A failed Decision API read was presented as an API-issued candidate.");
        assert((await page.locator("[data-weather-preparation-completed-at]").getAttribute("data-weather-preparation-completed-at")) === completedAt,
          "Decision failure erased the separately verified CWA completion timestamp.");
      }
      for (const [name, viewport] of [["desktop", {width: 1440, height: 1000}], ["mobile", {width: 390, height: 844}]]) {
        await page.setViewportSize(viewport);
        await page.locator('[data-weather-decision-band="true"]').evaluate(node => node.scrollIntoView({block: "start"}));
        await page.screenshot({path: path.join(outputDir, `run-${run}-${name}.png`), animations: "disabled"});
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
        assert(!overflow, `${name} Weather page has horizontal overflow.`);
      }
      scenarios.push({run, ...actual});
      await page.setViewportSize({width: 1440, height: 1000});
    }
    for (const scenario of scenarios) {
      const sequence = events.filter(event => event.run === scenario.run);
      const completion = sequence.findIndex(event => event.event === "preparation-complete");
      const review = sequence.findIndex(event => event.event === "decision-get" && event.afterCompletion);
      assert(completion >= 0 && review > completion, "Decision read was not linked to a completed refresh.");
    }
    assert(blockedWrites.length === 0, "Unexpected write attempt occurred.");
    assert(pageErrors.length === 0, "Uncaught browser errors occurred.");
    const evidence = {mode: "controlled_refresh_replay", actualCwaRefreshPerformed: false,
      baseUrl, scenarios, events, blockedWrites, pageErrors};
    fs.writeFileSync(path.join(outputDir, "evidence.json"), JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify({status: "passed", mode: evidence.mode, scenarios: scenarios.length, outputDir}));
  } finally {
    await browser.close();
  }
}

main().catch(error => {console.error(error); process.exitCode = 1;});
