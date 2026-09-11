#!/usr/bin/env node

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const baseUrl = (process.argv[2] || "http://127.0.0.1:9099").replace(/\/$/, "");
const chromePath = process.env.SCOUT_CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const completedScenarios = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function snapshot(overrides = {}) {
  return {
    captured_at: "2026-09-11T01:56:00Z",
    host: "scout",
    status: "ok",
    uptime_seconds: 3600,
    cpu_count: 4,
    cpu_used_percent: 12.5,
    load_average: [0.2, 0.3, 0.4],
    power: {
      status: "ok",
      captured_at: "2026-09-11T01:56:00Z",
      age_seconds: 1,
      battery_percent: 80,
      flow: "charging",
      battery_power_w: 1.5,
      battery_voltage_mv: 16000,
      ups_vbus_power_mw: 7000,
      ext5v_v: 5.1,
    },
    memory: {
      total_bytes: 8 * 1024 ** 3,
      used_bytes: 7 * 1024 ** 3,
      available_bytes: 1 * 1024 ** 3,
      used_percent: 87.5,
      swap_total_bytes: 2 * 1024 ** 3,
      swap_used_bytes: 0,
    },
    disks: [{
      mount: "/",
      device: "/dev/test",
      total_bytes: 1000,
      used_bytes: 900,
      available_bytes: 100,
      used_percent: 90,
      inode_used_percent: null,
      read_only: false,
    }],
    sensors: [
      { name: "cpu_thermal", source: "cpu-source", temperature_c: 70, rpm: null },
      { name: "nvme", source: "nvme-source-a", temperature_c: 40, rpm: null },
      { name: "nvme", source: "nvme-source-b", temperature_c: 41, rpm: null },
      { name: "pwmfan", source: "fan-source", temperature_c: null, rpm: 0 },
    ],
    alerts: {},
    errors: {},
    thresholds: {
      battery_percent: { warning: 20, critical: 10 },
      memory_used_percent: { warning: 90, critical: 95 },
      disk_used_percent: { warning: 85, critical: 95 },
      inode_used_percent: { warning: 85, critical: 95 },
      cpu_temperature_c: { warning: 75, critical: 85 },
      nvme_temperature_c: { warning: 65, critical: 75 },
      ups_stale_seconds: 15,
    },
    ...overrides,
  };
}

function envelope({ status = "ok", data = snapshot(), freshnessState = "fresh", age = 12, nextSteps = [] } = {}) {
  return {
    schema_version: "scout.hardware-monitor.api.v1",
    server_time: "2026-09-11T02:00:00Z",
    status,
    summary: "fixture hardware response",
    freshness: { state: freshnessState, captured_at: data && data.captured_at, age_seconds: age, sample_interval_seconds: 60, stale_after_seconds: 150 },
    data,
    next_steps: nextSteps,
    read_only: true,
  };
}

function listEnvelope(items, status = "ok") {
  return { schema_version: "scout.hardware-monitor.api.v1", server_time: "2026-09-11T02:00:00Z", status, summary: "fixture list", items, meta: { limit: 60, count: items.length, order: "oldest_first", has_more: false } };
}

async function waitForText(frame, selector, text) {
  await frame.locator(selector).filter({ hasText: text }).waitFor({ state: "visible", timeout: 10000 });
}

async function runScenario(browser, name, fixture) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  if (process.argv[4]) {
    const html = fs.readFileSync(process.argv[4], "utf8");
    await page.route("**/admin/dashboard/scout-monitor", (route) => route.fulfill({ contentType: "text/html", body: html }));
  }
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  if (fixture.clock) {
    const now = new Date("2026-09-11T02:00:00Z");
    await page.clock.install({ time: now });
    await page.clock.pauseAt(now);
  }
  await page.addInitScript(() => {
    window.hardwareRequestEvidence = [];
    window.macMonitorRequestEvidence = [];
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = (input, options) => {
      if (/\/api\/(snapshot|health)$/.test(String(input))) window.macMonitorRequestEvidence.push(String(input));
      if (String(input).includes("hardware-monitor/")) {
        const evidence = { url: String(input), aborted: false };
        window.hardwareRequestEvidence.push(evidence);
        options.signal.addEventListener("abort", () => { evidence.aborted = true; });
      }
      return fetchOriginal(input, options);
    };
  });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status**", async (route) => {
    if (fixture.stall) return;
    if (fixture.delayMs) await new Promise((resolve) => setTimeout(resolve, fixture.delayMs));
    if (fixture.disconnect) return route.abort("failed");
    return route.fulfill({ status: fixture.statusCode || 200, contentType: "application/json", body: JSON.stringify(fixture.statusPayload) });
  });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/history**", async (route) => {
    if (fixture.stall || fixture.stallHistory) return;
    if (fixture.disconnect || fixture.listDisconnect) return route.abort("failed");
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture.historyPayload || listEnvelope([])) });
  });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/events**", async (route) => {
    if (fixture.stall) return;
    if (fixture.disconnect || fixture.listDisconnect) return route.abort("failed");
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture.eventsPayload || listEnvelope([])) });
  });
  await page.goto(`${baseUrl}/admin/dashboard/scout-monitor`, { waitUntil: "domcontentloaded", timeout: 60000 });
  const frame = page.mainFrame();
  await frame.getByRole("heading", { name: "硬體監控" }).waitFor({ state: "visible", timeout: 10000 });
  if (fixture.loading) {
    assert(await frame.locator("#hardwareOverallStatus").innerText() === "載入中", "loading state was not visible");
  }
  await waitForText(frame, "#hardwareOverallStatus", fixture.expectedStatus);
  if (fixture.expectedNotice) await waitForText(frame, "#hardwareNoticeText", fixture.expectedNotice);
  if (!fixture.stallHistory) await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
  if (fixture.check) await fixture.check(frame, page, fixture);
  assert(await page.evaluate(() => window.macMonitorRequestEvidence.length) === 0, `${name}: Mac monitor polling remains`);
  assert(pageErrors.length === 0, `${name}: JavaScript errors: ${pageErrors.join("; ")}`);
  completedScenarios.push(name);
  await page.close();
}

async function run() {
  const browser = await chromium.launch({ headless: true, executablePath: chromePath });
  try {
    const staleData = snapshot({ power: { ...snapshot().power, battery_percent: null, flow: null, battery_power_w: null }, memory: null });
    await runScenario(browser, "loading-and-stale", {
      loading: true,
      delayMs: 1500,
      statusCode: 503,
      statusPayload: envelope({ status: "stale", data: staleData, freshnessState: "stale", age: 181, nextSteps: ["等待下一次採樣"] }),
      historyPayload: listEnvelope([snapshot({ cpu_used_percent: null }), snapshot({ memory: null, cpu_used_percent: 10 })]),
      eventsPayload: listEnvelope([{ captured_at: "2026-09-11T01:55:00Z", events: ["記憶體使用率變更"] }]),
      expectedStatus: "資料已過期",
      expectedNotice: "資料已過期",
      check: async (frame) => {
        assert(await frame.locator("#hardwareBatteryPercent").innerText() === "未知", "null battery was not rendered as unknown");
        assert(await frame.locator("#hardwareBatteryCard").getAttribute("data-state") === "stale", "stale data was presented as a normal card");
        assert((await frame.locator("#hardwareFanSpeeds").innerText()).includes("0 RPM"), "zero RPM was not displayed");
        const nvme = await frame.locator("#hardwareNvmeTemperatures").innerText();
        assert(nvme.includes("nvme-source-a") && nvme.includes("nvme-source-b"), "same-name NVMe sources were merged");
        assert((await frame.locator("#hardwareEventList").innerText()).includes("記憶體使用率變更"), "event item was not rendered");
      },
    });

    const warningData = snapshot({ status: "warning", alerts: { memory_used_percent: { severity: "warning", message: "記憶體接近門檻" } } });
    await runScenario(browser, "warning", {
      statusPayload: envelope({ status: "warning", data: warningData }),
      expectedStatus: "警告",
      check: async (frame) => {
        assert((await frame.locator("#hardwareAlertList").innerText()).includes("警告"), "warning alert was not rendered");
        await frame.locator(".hardware-thresholds summary").click();
        assert((await frame.locator("#hardwareThresholdList").innerText()).includes("90"), "thresholds were not rendered");
      },
    });

    const criticalData = snapshot({ status: "critical", alerts: { nvme_temperature_c: { severity: "critical", message: "NVMe 溫度過高" } } });
    await runScenario(browser, "critical", {
      statusPayload: envelope({ status: "critical", data: criticalData }),
      expectedStatus: "嚴重告警",
      check: async (frame) => assert((await frame.locator("#hardwareAlertList").innerText()).includes("嚴重告警"), "critical alert was not rendered"),
    });

    await runScenario(browser, "disconnected", {
      disconnect: true,
      expectedStatus: "無法連線",
      expectedNotice: "斷線",
      check: async (frame) => assert((await frame.locator("#hardwareBatteryPercent").innerText()) === "未知", "disconnected state filled a value"),
    });

    await runScenario(browser, "503-unavailable-is-not-stale", {
      statusCode: 503,
      statusPayload: envelope({ status: "unavailable", data: null, freshnessState: "unreadable", age: null }),
      expectedStatus: "無法連線",
      check: async (frame) => assert(await frame.locator("#hardwareAlertCount").innerText() === "未知", "missing alerts became zero"),
    });

    await runScenario(browser, "fresh-null-readings-and-sensor-sources", {
      statusPayload: envelope({ data: snapshot({
        power: { ...snapshot().power, battery_percent: null, battery_power_w: -2.5, flow: "discharging" },
        memory: null,
        sensors: snapshot().sensors.map(sensor => sensor.source === "nvme-source-b" ? { ...sensor, temperature_c: null } : sensor),
      }) }),
      expectedStatus: "正常",
      check: async (frame) => {
        assert(await frame.locator("#hardwareMemoryCard").getAttribute("data-state") === "unknown", "null memory has a normal icon");
        assert(await frame.locator("#hardwareBatteryCard").getAttribute("data-state") === "unknown", "null battery has a normal icon");
        assert((await frame.locator("#hardwareBatteryPower").innerText()).includes("放電 -2.50 W"), "power sign is wrong");
        assert((await frame.locator("#hardwareNvmeTemperatures .hardware-sensor-value").nth(1).innerText()).includes("未知"), "null sensor was dropped");
        assert((await frame.locator("#hardwareEventList").innerText()).includes("目前沒有狀態變更事件"), "empty event state missing");
        assert((await frame.locator("#hardwareTrendEmpty").innerText()).includes("沒有可用的歷史採樣"), "empty history state missing");
      },
    });

    await runScenario(browser, "empty-status-data-is-unknown", {
      statusPayload: envelope({ data: null, freshnessState: "missing", age: null }),
      expectedStatus: "未知",
      check: async (frame) => assert(await frame.locator("#hardwareMemoryPercent").innerText() === "未知", "empty data filled memory"),
    });

    const history = [
      snapshot({ captured_at: "2026-09-11T01:50:00Z", cpu_used_percent: 10 }),
      snapshot({ captured_at: "2026-09-11T01:51:00Z", cpu_used_percent: 20 }),
      snapshot({ captured_at: "2026-09-11T01:52:00Z", cpu_used_percent: null }),
      snapshot({ captured_at: "2026-09-11T01:53:00Z", cpu_used_percent: 30 }),
      snapshot({ captured_at: "2026-09-11T01:56:00Z", cpu_used_percent: 40 }),
      snapshot({ captured_at: "2026-09-11T01:57:00Z", cpu_used_percent: 50 }),
    ];
    await runScenario(browser, "timestamp-gaps-thresholds-gib-and-zero-rpm", {
      statusPayload: envelope(),
      historyPayload: listEnvelope(history),
      expectedStatus: "正常",
      check: async (frame) => {
        const commands = await frame.locator("#hardwareCpuPath").getAttribute("d");
        assert((commands.match(/M/g) || []).length === 3, `history gaps bridged: ${commands}`);
        assert((commands.match(/L/g) || []).length === 2, `invented history segments: ${commands}`);
        const xs = await frame.locator("#hardwareCpuPathPoints circle").evaluateAll(nodes => nodes.map(node => Number(node.getAttribute("cx"))));
        assert(xs.length === 5 && Math.abs((xs[3] - xs[2]) / (xs[1] - xs[0]) - 3) < 0.01, "history x axis is not time-based");
        assert(await frame.locator("#hardwareMemoryTotal").innerText() === "8.00 GiB", "GiB conversion wrong");
        assert((await frame.locator("#hardwareSwap").innerText()).startsWith("0.00 GiB"), "valid zero swap lost");
        assert((await frame.locator("#hardwareDiskTable").innerText()).includes("警告"), "disk API threshold was ignored");
        assert(await frame.locator("#hardwareThermalCard").getAttribute("data-state") === "ok", "zero RPM alone was flagged");
      },
    });

    await runScenario(browser, "local-age-crosses-150-seconds", {
      clock: true,
      statusPayload: envelope({ age: 149 }),
      expectedStatus: "正常",
      check: async (frame, page) => {
        await page.clock.runFor(2000);
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "資料已過期", "old data stayed normal between polls");
        assert(await frame.locator("#hardwareDataAge").innerText() === "2 分 31 秒", "data age did not advance");
      },
    });

    await runScenario(browser, "partial-and-retained-list-failures", {
      statusPayload: envelope(),
      historyPayload: listEnvelope(history, "partial"),
      eventsPayload: listEnvelope([{ captured_at: snapshot().captured_at, events: ["狀態變更測試"] }], "partial"),
      expectedStatus: "正常",
      check: async (frame, page, fixture) => {
        assert((await frame.locator("#hardwareTrendMeta").innerText()).includes("部分資料"), "partial history unmarked");
        fixture.listDisconnect = true;
        fixture.statusCode = 503;
        fixture.statusPayload = envelope({ status: "unavailable", data: null, freshnessState: "unreadable", age: null });
        await frame.locator("#hardwareRefreshButton").click();
        await waitForText(frame, "#hardwareOverallStatus", "無法連線");
        await waitForText(frame, "#hardwareTrendMeta", "保留");
        await waitForText(frame, "#hardwareEventsMeta", "上次資料");
        assert(await frame.locator("#hardwareMemoryTotal").innerText() === "8.00 GiB", "last data not retained after disconnect");
        assert((await frame.locator("#hardwareAlertList").innerText()).includes("目前狀態未知"), "retained alerts implied currently normal");
      },
    });

    await runScenario(browser, "independent-status-and-request-timeout", {
      clock: true,
      statusPayload: envelope(),
      stallHistory: true,
      expectedStatus: "正常",
      check: async (frame, page) => {
        await page.clock.runFor(12000);
        await waitForText(frame, "#hardwareTrendMeta", "無法取得");
        await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
      },
    });

    await runScenario(browser, "60-second-poll-abort-leave-and-restore", {
      clock: true,
      statusPayload: envelope(),
      expectedStatus: "正常",
      check: async (frame, page, fixture) => {
        const count = () => page.evaluate(() => window.hardwareRequestEvidence.length);
        assert(await count() === 3, "initial request count wrong");
        await page.clock.runFor(59999);
        assert(await count() === 3, "polled before 60 seconds");
        await page.clock.runFor(1);
        await page.waitForFunction(() => window.hardwareRequestEvidence.length === 6 && !document.querySelector("#hardwareRefreshButton").disabled);
        fixture.stall = true;
        await frame.locator("#hardwareRefreshButton").click();
        await page.waitForFunction(() => window.hardwareRequestEvidence.length === 9);
        await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true })));
        const aborted = await page.evaluate(() => window.hardwareRequestEvidence.slice(-3).every(item => item.aborted));
        assert(aborted, "in-flight requests were not aborted on leave");
        await page.clock.runFor(120000);
        assert(await count() === 9, "polling continued after pagehide");
        fixture.stall = false;
        await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })));
        await page.waitForFunction(() => window.hardwareRequestEvidence.length === 12 && !document.querySelector("#hardwareRefreshButton").disabled);
      },
    });
    const report = { ok: true, baseUrl, scenarios: completedScenarios };
    const reportPath = process.argv[3];
    if (reportPath) {
      fs.mkdirSync(path.dirname(reportPath), { recursive: true });
      fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
    }
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
