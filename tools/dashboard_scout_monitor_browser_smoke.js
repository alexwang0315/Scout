#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const DEFAULT_BASE_URL = "http://127.0.0.1:9099";
const DEFAULT_SCREENSHOT_DIR = "/tmp/scout-dashboard-hardware-monitor-smoke";
let browser = null;

function option(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function fail(message) {
  throw new Error(message);
}

async function run() {
  const baseUrl = option("--base-url", DEFAULT_BASE_URL).replace(/\/$/, "");
  const screenshotDir = option("--screenshots-dir", DEFAULT_SCREENSHOT_DIR);
  fs.mkdirSync(screenshotDir, { recursive: true });
  browser = await chromium.launch({
    headless: true,
    executablePath: process.env.SCOUT_CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  const consoleErrors = [];
  const failedResponses = [];
  const hardwareResponses = [];
  const macMonitorRequests = [];
  let phase = "initial-load";
  page.on("request", (request) => {
    if (/\/admin\/dashboard\/scout-monitor\/api\/(snapshot|health)$/.test(new URL(request.url()).pathname)) macMonitorRequests.push(request.url());
  });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/api/v1/hardware-monitor/")) {
      const parsedUrl = new URL(url);
      hardwareResponses.push({ origin: parsedUrl.origin, path: parsedUrl.pathname, status: response.status(), method: response.request().method() });
    }
  });
  page.on("requestfailed", (request) => {
    if (request.url().includes("/api/v1/hardware-monitor/")) failedResponses.push({ url: request.url(), error: request.failure()?.errorText, phase, at: new Date().toISOString(), timing: request.timing() });
  });

  await page.goto(`${baseUrl}/admin/dashboard#home`, { waitUntil: "domcontentloaded", timeout: 60000 });
  const firstStatusResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/api/v1/hardware-monitor/status"));
  const firstEventsResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/api/v1/hardware-monitor/events"));
  const systemSection = page.locator('details[data-nav-primary]').filter({ hasText: "System" }).first();
  await systemSection.locator("summary").click();
  await page.getByRole("button", { name: "scout monitor" }).click();
  const frame = page.frameLocator('iframe[src="/admin/dashboard/scout-monitor"]');
  await frame.getByRole("heading", { name: "硬體監控" }).waitFor({ state: "visible", timeout: 30000 });
  const macUiElements = await frame.locator("#hostName, #cpuCard, #memoryCard, #diskCard, #historyChart, #processTable, #intervalSelect").count();
  if (macUiElements) fail("Mac monitoring elements remain in the Dashboard monitor");
  await frame.locator("#hardwareOverallStatus").waitFor({ state: "visible", timeout: 30000 });
  await frame.locator("#hardwareTrendMeta").filter({ hasText: "歷史紀錄" }).waitFor({ state: "visible", timeout: 30000 });
  const statusPayload = await (await firstStatusResponse).json();
  const eventsPayload = await (await firstEventsResponse).json();
  if (!statusPayload.data) fail("live API has no snapshot for smoke verification");

  const overallStatus = await frame.locator("#hardwareOverallStatus").innerText();
  const lastSampleAt = await frame.locator("#hardwareLastSampleAt").innerText();
  const dataAge = await frame.locator("#hardwareDataAge").innerText();
  const diskRows = await frame.locator("#hardwareDiskTable tr:not(.empty-row)").count();
  const trendMeta = await frame.locator("#hardwareTrendMeta").innerText();
  const eventText = await frame.locator("#hardwareEventList").innerText();
  const nvmeText = await frame.locator("#hardwareNvmeTemperatures").innerText();
  const hardwareText = await frame.locator("#hardwareMonitorPanel").innerText();
  if (!hardwareText.includes("電池與供電") || !hardwareText.includes("記憶體") || !hardwareText.includes("磁碟狀態")) fail("hardware sections are not visible");
  if (!/^\d{4}\/\d{2}\/\d{2}/.test(lastSampleAt)) fail(`Taipei sample time is not rendered: ${lastSampleAt}`);
  if (dataAge === "未知") fail("data age is unknown for the live API");
  if (diskRows < 1) fail("live disk rows are missing");
  if (!trendMeta.includes("歷史紀錄")) fail(`history trend is missing: ${trendMeta}`);
  if (!eventsPayload.items.length && !eventText.includes("目前沒有狀態變更事件")) fail(`empty event state is missing: ${eventText}`);
  for (const item of eventsPayload.items) {
    for (const message of item.events) if (!eventText.includes(message)) fail("live event message was not rendered");
  }
  const expectedState = statusPayload.status === "stale" || statusPayload.freshness.state === "stale" ? "資料已過期"
    : ({ ok: "正常", warning: "警告", critical: "嚴重告警", unavailable: "無法連線" })[statusPayload.status];
  if (overallStatus !== expectedState) fail(`status mismatch: ${overallStatus} vs ${expectedState}`);
  if (!nvmeText.includes("/sys/class/hwmon/")) fail(`NVMe source is missing: ${nvmeText}`);

  const inventorySections = statusPayload.data.inventory?.sections;
  if (!inventorySections) fail("live API has no inventory for device smoke verification");
  const inventoryEvidence = [];
  const inventoryScreenshots = [];
  phase = "desktop-inventory";
  for (const key of ["network", "bluetooth", "usb", "pcie", "i2c", "gpio", "serial"]) {
    const section = frame.locator(`.inventory-section[data-section="${key}"]`);
    const expected = inventorySections[key];
    if (!expected) fail(`live API is missing ${key} inventory`);
    await section.locator(":scope > summary").click();
    const itemCount = await section.locator(".inventory-device").count();
    if (itemCount !== expected.items.length) fail(`${key}: item count differs from the live API`);
    const text = await section.innerText();
    for (const item of expected.items) {
      if (!text.includes(item.name) || !text.includes(item.id)) fail(`${key}: a live device name or id is missing`);
    }
    const sectionStatus = await section.locator(".inventory-section-status").innerText();
    const expectedSectionState = { ok: "已讀取", partial: "部分讀取", unavailable: "無法讀取" }[expected.status];
    if (!sectionStatus.includes(expectedSectionState)) fail(`${key}: incorrect information-read state`);
    const properties = section.locator(".inventory-properties").first();
    if (itemCount) await properties.locator(":scope > summary").click();
    await section.locator(".inventory-notes > summary").click();
    if (key === "gpio" && itemCount) {
      await section.locator(".inventory-lines > summary").first().focus();
      await section.locator(".inventory-lines > summary").first().press("Enter");
      const lineRows = section.locator(".inventory-lines").first().locator("tbody tr");
      if (await lineRows.count() !== expected.items[0].lines.length) fail("GPIO line count differs from the API");
      if (expected.items[0].lines.some((line) => line.value === null) && !(await section.innerText()).includes("未採樣")) fail("GPIO null voltage is not marked unsampled");
    }
    const screenshot = path.join(screenshotDir, `desktop-inventory-${key}.png`);
    await section.evaluate((node) => node.scrollIntoView({ block: "start" }));
    await page.screenshot({ path: screenshot });
    inventoryScreenshots.push(screenshot);
    inventoryEvidence.push({ section: key, itemCount, expectedItems: expected.items.length, sectionStatus, notesOpened: true, propertiesOpened: itemCount > 0 });
  }
  const expandedBefore = await frame.locator("#hardwareInventoryGrid details[open]").evaluateAll((nodes) => nodes.map((node) => node.dataset.detailKey).sort());

  const refreshResponse = page.waitForResponse((response) => response.url().includes("/api/v1/hardware-monitor/status"));
  phase = "manual-refresh";
  const refreshButton = frame.getByRole("button", { name: /重新讀取/ });
  await refreshButton.focus();
  const focusedControl = await frame.locator("body").evaluate(() => document.activeElement && document.activeElement.id);
  if (focusedControl !== "hardwareRefreshButton") fail(`refresh button is not keyboard focusable: ${focusedControl}`);
  await refreshButton.press("Enter");
  await refreshResponse;
  await frame.locator("#hardwareRefreshButton:not([disabled])").waitFor();
  const expandedAfter = await frame.locator("#hardwareInventoryGrid details[open]").evaluateAll((nodes) => nodes.map((node) => node.dataset.detailKey).sort());
  if (JSON.stringify(expandedBefore) !== JSON.stringify(expandedAfter)) fail("device expansion changed after manual refresh");

  const desktopScreenshot = path.join(screenshotDir, "desktop.png");
  await frame.locator("#hardwareMonitorPanel").evaluate((panel) => panel.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: desktopScreenshot, fullPage: false });

  await page.setViewportSize({ width: 390, height: 844 });
  phase = "mobile-reload";
  await page.reload({ waitUntil: "domcontentloaded" });
  const mobileFrame = page.frameLocator('iframe[src="/admin/dashboard/scout-monitor"]');
  await mobileFrame.getByRole("heading", { name: "硬體監控" }).waitFor({ state: "visible", timeout: 30000 });
  await mobileFrame.locator("#hardwareTrendMeta").filter({ hasText: "歷史紀錄" }).waitFor({ state: "visible", timeout: 30000 });
  phase = "mobile-inventory";
  const mobileLayout = await mobileFrame.locator("body").evaluate((body) => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    scrollHeight: document.documentElement.scrollHeight,
    hardwarePanel: Boolean(document.querySelector("#hardwareMonitorPanel")),
  }));
  if (mobileLayout.scrollWidth > mobileLayout.clientWidth + 2) fail(`mobile horizontal overflow: ${JSON.stringify(mobileLayout)}`);
  const mobileScreenshot = path.join(screenshotDir, "mobile.png");
  await mobileFrame.locator("#hardwareMonitorPanel").evaluate((panel) => panel.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: mobileScreenshot, fullPage: false });
  const mobileMemoryScreenshot = path.join(screenshotDir, "mobile-memory.png");
  await mobileFrame.locator("#hardwareMemoryCard").screenshot({ path: mobileMemoryScreenshot });
  const mobileThermalScreenshot = path.join(screenshotDir, "mobile-thermal.png");
  await mobileFrame.locator("#hardwareThermalCard").screenshot({ path: mobileThermalScreenshot });

  const inventoryLayouts = [];
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    for (const key of ["network", "gpio"]) {
      const section = mobileFrame.locator(`.inventory-section[data-section="${key}"]`);
      if (!(await section.getAttribute("open") === "")) await section.locator(":scope > summary").click();
      if (key === "gpio") {
        const lines = section.locator(".inventory-lines").first();
        if (await lines.count() && await lines.getAttribute("open") !== "") await lines.locator(":scope > summary").click();
      }
      await section.evaluate((node) => node.scrollIntoView({ block: "start" }));
      const shot = path.join(screenshotDir, `mobile-${width}-inventory-${key}.png`);
      await page.screenshot({ path: shot });
      inventoryScreenshots.push(shot);
    }
    const layout = await mobileFrame.locator("body").evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }));
    if (layout.scrollWidth > layout.clientWidth + 2) fail(`expanded inventory overflows at ${width}px: ${JSON.stringify(layout)}`);
    inventoryLayouts.push({ viewport: width, ...layout });
  }

  fs.writeFileSync(path.join(screenshotDir, "network-observations.json"), JSON.stringify({ at: new Date().toISOString(), hardwareResponses, macMonitorRequests, consoleErrors, pageErrors, failedResponses }, null, 2));
  if (hardwareResponses.some(entry => entry.origin !== new URL(baseUrl).origin)) fail("browser made a cross-origin hardware request");
  if (macMonitorRequests.length) fail(`Mac monitor requests remain: ${JSON.stringify(macMonitorRequests)}`);
  if (hardwareResponses.some(entry => entry.status !== 200)) fail(`live hardware HTTP failure: ${JSON.stringify(hardwareResponses)}`);
  if (consoleErrors.length || pageErrors.length || failedResponses.length) fail(`browser errors: ${JSON.stringify({ consoleErrors, pageErrors, failedResponses })}`);
  const methods = new Set(hardwareResponses.map((entry) => entry.method));
  if ([...methods].some((method) => method !== "GET")) fail(`non-GET hardware request observed: ${JSON.stringify([...methods])}`);

  const result = {
    ok: true,
    baseUrl,
    route: "scout-monitor",
    overallStatus,
    lastSampleAt,
    dataAge,
    diskRows,
    trendMeta,
    eventText,
    nvmeSourceVisible: nvmeText.includes("/sys/class/hwmon/"),
    hardwareResponses,
    macUiElements,
    macMonitorRequests,
    consoleErrors,
    pageErrors,
    failedResponses,
    mobileLayout,
    inventoryEvidence,
    inventoryExpansionPreserved: true,
    inventoryLayouts,
    screenshots: [desktopScreenshot, mobileScreenshot, mobileMemoryScreenshot, mobileThermalScreenshot, ...inventoryScreenshots],
  };
  fs.writeFileSync(path.join(screenshotDir, "browser-smoke.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
}

run().catch(async (error) => {
  if (browser) await browser.close().catch(() => {});
  console.error(error.stack || error);
  process.exitCode = 1;
});
