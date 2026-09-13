#!/usr/bin/env node

const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const { createHash } = require("crypto");

const baseUrl = (process.argv[2] || "http://127.0.0.1:9099").replace(/\/$/, "");
const chromePath = process.env.SCOUT_CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const completedScenarios = [];
const scenarioResults = [];
const skippedScenarios = [];
const scenarioFilter = process.env.SCOUT_STATE_SCENARIOS ? new RegExp(process.env.SCOUT_STATE_SCENARIOS) : null;
const inventorySectionKeys = ["network", "bluetooth", "usb", "pcie", "i2c", "gpio", "serial"];
const inventoryStatusLabels = { ok: "已讀取", partial: "部分讀取", unavailable: "無法讀取" };
const artifactsRoot = path.resolve(__dirname, "../artifacts");
let artifactDir;
let replayHtml;

// All responses below are synthetic harness evidence, never real-device qualification.
// Network addresses use documentation ranges; names and MAC placeholders are invented.
function inventoryItem(id, name, properties = {}, overrides = {}) {
  return { id, name, state: "present", driver: "synthetic_driver", properties, lines: [], ...overrides };
}

function inventorySection(items = [], overrides = {}) {
  return { status: "ok", summary: "Synthetic section sample", items, notes: [], errors: [], ...overrides };
}

function inventorySnapshot() {
  return {
    captured_at: "2026-09-11T01:59:48Z",
    status: "ok",
    sections: {
      network: inventorySection([
        inventoryItem("synthetic-wifi", "Synthetic wireless adapter", {
          interface: "synthetic-wlan-0", kind: "wifi", operstate: "up", ssid: "SYNTHETIC_SSID_ONLY",
          ipv4: ["192.0.2.10/24"], ipv6: ["2001:db8::10/64"], mac: "synthetic-mac-not-assigned",
          carrier: true, mtu: 1500, tx_bitrate_mbps: 144.4, signal_dbm: -47,
          frequency_mhz: 5180, rx_bytes: 0, tx_bytes: 4096,
          extra_evidence: ["SYNTHETIC_ARRAY_PROPERTY", 0, false, null],
        }, { state: "connected", driver: "synthetic_wifi_driver" }),
        inventoryItem("synthetic-ethernet", "Synthetic wired adapter", {
          interface: "synthetic-eth-0", kind: "ethernet", operstate: "down", carrier: false, tx_bitrate_mbps: 0,
        }, { state: "disconnected", driver: "synthetic_ethernet_driver" }),
        inventoryItem("synthetic-network-unknown", "Synthetic unknown interface", {
          tx_bitrate_mbps: null,
        }, { state: "unknown", driver: null }),
      ]),
      bluetooth: inventorySection([
        inventoryItem("synthetic-bt-on", "Synthetic Bluetooth adapter", {
          kind: "controller", powered: true, discoverable: false, pairable: false, discovering: false,
          address: "synthetic-bluetooth-address-not-assigned",
        }, { state: "powered_on" }),
        inventoryItem("synthetic-bt-blocked", "Synthetic blocked Bluetooth adapter", {
          kind: "controller", powered: false, soft_blocked: true, hard_blocked: false,
        }, { state: "blocked" }),
        inventoryItem("synthetic-bt-device", "Synthetic connected Bluetooth device", {
          kind: "connected_device", address: "synthetic-connected-bt-address",
        }, { state: "connected" }),
      ]),
      usb: inventorySection([
        ...[1, 2].map(index => inventoryItem(`synthetic-usb-root-${index}`, `Synthetic USB root hub ${index}`, {
          root_hub: true, device_class: "09", speed: 480, busnum: index,
        })),
        inventoryItem("synthetic-usb-unclassified", "Synthetic unclassified USB device", {
          device_class: "00", speed: 5000, busnum: 1,
        }),
        ...[1, 2, 3].map(index => inventoryItem(`synthetic-usb-device-${index}`, `Synthetic USB peripheral ${index}`, {
          root_hub: false, device_class: "00", speed: 12, busnum: 1,
          idVendor: "ffff", idProduct: `fff${index}`, manufacturer: "Synthetic manufacturer",
          interface_drivers: ["synthetic_usb_driver"], product: `Synthetic product ${index}`,
        })),
      ]),
      pcie: inventorySection([
        inventoryItem("synthetic-pcie-0", "Synthetic PCIe endpoint A", {
          address: "0000:01:00.0", current_link_speed: "5.0 GT/s", current_link_width: 1,
          max_link_speed: "8.0 GT/s", max_link_width: 2,
        }, { driver: "synthetic_pcie_a" }),
        inventoryItem("synthetic-pcie-1", "Synthetic PCIe endpoint B", {
          address: "0000:02:00.0", current_link_speed: "8.0 GT/s", current_link_width: 2,
        }, { driver: "synthetic_pcie_b" }),
      ]),
      i2c: inventorySection([
        inventoryItem("synthetic-i2c-bus", "Synthetic I2C adapter", {
          kind: "adapter", device_node: "/dev/i2c-synthetic", bus: 99,
        }),
        inventoryItem("synthetic-i2c-client", "Synthetic bound I2C client", {
          kind: "registered_device", address: "0x7f", bus: 99, evidence: "synthetic sysfs binding",
        }, { state: "present", driver: "synthetic_i2c_driver" }),
        inventoryItem("synthetic-i2c-telemetry", "Synthetic prior telemetry device", {
          kind: "telemetry_device", bus: 99, address: "0x7e", evidence: "existing_ups_telemetry",
          captured_at: "2026-09-11T01:59:48Z",
        }, { state: "observed" }),
      ], { notes: ["SYNTHETIC_I2C_PASSIVE_NOTE"] }),
      gpio: inventorySection([
        inventoryItem("synthetic-gpio-a", "Synthetic GPIO controller A", {
          device_node: "/dev/gpiochip-synthetic-a", label: "synthetic-gpio-a", line_count: 2,
        }, { lines: [
          { offset: 0, name: "SYNTHETIC_INPUT", direction: "input", consumer: "synthetic-input-consumer", active_low: false, value: null },
          { offset: 7, name: "SYNTHETIC_OUTPUT", direction: "output", consumer: "synthetic-output-consumer", active_low: true, value: null },
        ] }),
        inventoryItem("synthetic-gpio-b", "Synthetic GPIO controller B", {
          device_node: "/dev/gpiochip-synthetic-b", label: "synthetic-gpio-b", line_count: 1,
        }, { lines: [
          { offset: 0, name: "SYNTHETIC_OTHER_INPUT", direction: "input", consumer: "", active_low: false, value: null },
        ] }),
      ], { notes: ["SYNTHETIC_GPIO_NOTE"], errors: [] }),
      serial: inventorySection([
        inventoryItem("synthetic-serial-a", "Synthetic serial node", {
          device_node: "/dev/ttySYNTHETIC0", subsystem: "tty", kind: "uart",
        }, { state: "present", driver: "synthetic_uart_driver" }),
      ], { notes: ["SYNTHETIC_SERIAL_NODE_NOTE"] }),
    },
  };
}

function inventoryEnvelope(inventory = inventorySnapshot(), options = {}) {
  return envelope({ data: snapshot({ inventory }), ...options });
}

function sectionLocator(frame, key) {
  return frame.locator(`#hardwareInventoryGrid details.inventory-section[data-section=${JSON.stringify(key)}]`);
}

function deviceLocator(frame, key, id) {
  return sectionLocator(frame, key).locator(`article.inventory-device[data-device-id=${JSON.stringify(id)}]`);
}

async function setDetailsOpen(details, open = true) {
  assert(await details.count() === 1, `expected one details element: ${details}`);
  if (await details.evaluate(node => node.open) !== open) await details.locator(":scope > summary").click();
  assert(await details.evaluate(node => node.open) === open, `details did not become ${open ? "open" : "closed"}: ${details}`);
}

async function checkInventoryShell(frame, inventory, { collapsed = true, stale = false } = {}) {
  assert(await frame.locator("#hardwareInventoryPanel").isVisible(), "inventory panel is missing or hidden");
  assert(await frame.locator("#hardwareInventoryMeta").isVisible(), "inventory freshness metadata is missing");
  assert(await frame.locator("#hardwareInventoryGrid").isVisible(), "inventory grid is missing or hidden");
  assert(await frame.locator("#hardwareInventoryGrid details.inventory-section").count() === 7, "inventory contract incomplete: expected all seven sections");
  for (const key of inventorySectionKeys) {
    const section = sectionLocator(frame, key);
    assert(await section.count() === 1, `${key}: section missing or duplicated`);
    assert(await section.locator(":scope > summary").isVisible(), `${key}: direct summary missing`);
    const status = await section.locator(".inventory-section-status").innerText();
    assert(status.includes(inventoryStatusLabels[inventory.sections[key].status]), `${key}: wrong section status: ${status}`);
    if (stale) assert(status.includes("上次採樣"), `${key}: retained section lacks last-sample label: ${status}`);
    if (collapsed) assert(!await section.evaluate(node => node.open), `${key}: new section should start collapsed`);
  }
}

async function checkProperty(device, key, expected) {
  // A promoted field may also occur in the complete properties disclosure.
  const fields = device.locator(`dl.inventory-fields > div[data-property=${JSON.stringify(key)}]`);
  assert(await fields.count() > 0, `${key}: property field is missing`);
  for (const field of await fields.all()) {
    assert(await field.locator("dt").count() === 1 && await field.locator("dd").count() === 1, `${key}: property is not a dt/dd pair`);
    assert((await field.locator("dt").innerText()).trim(), `${key}: property label is empty`);
    const actual = (await field.locator("dd").innerText()).trim();
    assert(expected instanceof RegExp ? expected.test(actual) : actual.includes(String(expected)), `${key}: expected ${expected}, got ${actual}`);
  }
}

async function refreshInventory(frame, page) {
  const count = await page.evaluate(() => window.hardwareRequestEvidence.length);
  await frame.locator("#hardwareRefreshButton").click();
  await page.waitForFunction(previous => window.hardwareRequestEvidence.length >= previous + 3 && !document.querySelector("#hardwareRefreshButton").disabled, count);
}

async function checkInvalidInventory(frame, inventory, expectedStatus) {
  await waitForText(frame, "#hardwareOverallStatus", expectedStatus);
  await checkInventoryShell(frame, inventory, { collapsed: false, stale: true });
  const meta = await frame.locator("#hardwareInventoryMeta").innerText();
  assert(/過期|失效|無效|無法連線|斷線|不可.*目前|不能.*目前/.test(meta), `retained inventory lacks explicit invalidity: ${meta}`);
  assert(/上次|保留/.test(meta), `retained inventory lacks last-sample notice: ${meta}`);
  for (const key of inventorySectionKeys) {
    const ids = await sectionLocator(frame, key).locator("article.inventory-device").evaluateAll(nodes => nodes.map(node => node.dataset.deviceId).sort());
    assert(JSON.stringify(ids) === JSON.stringify(inventory.sections[key].items.map(item => item.id).sort()), `${key}: invalidation lost or invented devices`);
  }
}

async function captureScenario(page, result, label) {
  const screenshotPath = path.join(artifactDir, `${String(scenarioResults.length + 1).padStart(2, "0")}-${result.name}-${label}.png`);
  const screenshot = await page.screenshot({ fullPage: true, timeout: 10000 });
  fs.writeFileSync(screenshotPath, screenshot, { flag: "wx" });
  result.screenshots.push(screenshotPath);
}

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
  if (scenarioFilter && !scenarioFilter.test(name)) {
    skippedScenarios.push(name);
    return;
  }
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, serviceWorkers: "block" });
  page.setDefaultTimeout(10000);
  const result = { name, ok: false, evidence_kind: "synthetic_browser_harness", screenshots: [], pageErrors: [] };
  const startedAt = Date.now();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  fixture.capture = label => captureScenario(page, result, label);
  try {
  // Only the HTML entrypoint may reach the supplied origin. Every API is mocked.
  await page.route("**/*", route => {
    const request = route.request();
    if (request.method() === "GET" && request.url() === `${baseUrl}/admin/dashboard/scout-monitor`) return route.continue();
    return route.abort("blockedbyclient");
  });
  if (replayHtml !== undefined) {
    await page.route("**/admin/dashboard/scout-monitor", route => route.fulfill({ contentType: "text/html", body: replayHtml }));
  }
  if (fixture.clock) {
    const now = new Date("2026-09-11T02:00:00Z");
    await page.clock.install({ time: now });
    await page.clock.pauseAt(now);
  }
  await page.addInitScript(({ auditInventoryHtml }) => {
    window.hardwareRequestEvidence = [];
    window.macMonitorRequestEvidence = [];
    window.inventoryHtmlWrites = [];
    window.inventoryXssExecuted = 0;
    if (auditInventoryHtml) {
      const record = (sink, value) => {
        if (String(value).includes("SCOUT_SYNTHETIC_XSS")) window.inventoryHtmlWrites.push(sink);
      };
      for (const property of ["innerHTML", "outerHTML"]) {
        const original = Object.getOwnPropertyDescriptor(Element.prototype, property);
        Object.defineProperty(Element.prototype, property, {
          ...original,
          set(value) { record(property, value); original.set.call(this, value); },
        });
      }
      const insertOriginal = Element.prototype.insertAdjacentHTML;
      Element.prototype.insertAdjacentHTML = function (position, value) {
        record("insertAdjacentHTML", value);
        return insertOriginal.call(this, position, value);
      };
    }
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = (input, options) => {
      if (/\/api\/(snapshot|health)$/.test(String(input))) window.macMonitorRequestEvidence.push(String(input));
      if (String(input).includes("hardware-monitor/")) {
        const evidence = { url: String(input), method: options && options.method || "GET", aborted: false };
        window.hardwareRequestEvidence.push(evidence);
        if (options && options.signal) options.signal.addEventListener("abort", () => { evidence.aborted = true; });
      }
      return fetchOriginal(input, options);
    };
  }, { auditInventoryHtml: Boolean(fixture.auditInventoryHtml) });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status**", async (route) => {
    if (fixture.stall) return;
    if (fixture.delayMs) await new Promise((resolve) => setTimeout(resolve, fixture.delayMs));
    if (fixture.disconnect) return route.abort("failed");
    return route.fulfill({ status: fixture.statusCode || 200, contentType: "application/json", body: JSON.stringify(fixture.statusPayload) });
  });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/history**", async (route) => {
    if (fixture.stall || fixture.stallHistory) return;
    if (fixture.disconnect || fixture.listDisconnect) return route.abort("failed");
    if (fixture.deferHistory) {
      fixture.releaseHistory = () => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture.historyPayload || listEnvelope([])) });
      return;
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture.historyPayload || listEnvelope([])) });
  });
  await page.route("**/admin/dashboard/scout-monitor/api/v1/hardware-monitor/events**", async (route) => {
    if (fixture.stall) return;
    if (fixture.disconnect || fixture.listDisconnect) return route.abort("failed");
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixture.eventsPayload || listEnvelope([])) });
  });
  const navigation = await page.goto(`${baseUrl}/admin/dashboard/scout-monitor`, { waitUntil: "domcontentloaded", timeout: 60000 });
  result.html_sha256 = createHash("sha256").update(await navigation.body()).digest("hex");
  const frame = page.mainFrame();
  await frame.getByRole("heading", { name: "硬體監控" }).waitFor({ state: "visible", timeout: 10000 });
  if (fixture.loading) {
    assert(await frame.locator("#hardwareOverallStatus").innerText() === "載入中", "loading state was not visible");
  }
  await waitForText(frame, "#hardwareOverallStatus", fixture.expectedStatus);
  if (fixture.expectedNotice) await waitForText(frame, "#hardwareNoticeText", fixture.expectedNotice);
  if (!fixture.stallHistory && !fixture.deferHistory) await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
  if (fixture.check) await fixture.check(frame, page, fixture);
  assert(await page.evaluate(() => window.macMonitorRequestEvidence.length) === 0, `${name}: Mac monitor polling remains`);
  assert(await page.evaluate(() => window.hardwareRequestEvidence.every(request => request.method === "GET")), `${name}: non-GET hardware request`);
  assert(pageErrors.length === 0, `${name}: JavaScript errors: ${pageErrors.join("; ")}`);
  await fixture.capture("final");
  result.ok = true;
  completedScenarios.push(name);
  } catch (error) {
    result.error = error.stack || String(error);
    try { await fixture.capture("failed"); } catch (captureError) { result.screenshotError = String(captureError); }
  } finally {
    result.pageErrors = pageErrors;
    result.duration_ms = Date.now() - startedAt;
    try {
      result.requests = await page.evaluate(() => window.hardwareRequestEvidence || []);
      result.inventoryHtmlWrites = await page.evaluate(() => window.inventoryHtmlWrites || []);
    } catch (error) { result.browserEvidenceError = String(error); }
    scenarioResults.push(result);
    console.error(`${result.ok ? "PASS" : "FAIL"} ${name}${result.ok ? "" : `: ${result.error.split("\n")[0]}`}`);
    await page.close();
  }
}

async function runInventoryScenarios(browser) {
  for (const missing of [false, true]) {
    const data = snapshot({ inventory: null });
    if (missing) delete data.inventory;
    await runScenario(browser, `inventory-${missing ? "missing" : "null"}-waits-for-update`, {
      statusPayload: envelope({ data }),
      expectedStatus: "正常",
      check: async frame => {
        assert(await frame.locator("#hardwareInventoryPanel").isVisible(), "waiting inventory panel missing");
        const meta = await frame.locator("#hardwareInventoryMeta").innerText();
        assert(/等待.*更新|等待.*採樣|尚未.*(?:提供|包含|清單)|舊版|舊.*採樣/.test(meta), `old inventory contract lacks waiting notice: ${meta}`);
        assert(await frame.locator("#hardwareInventoryGrid article.inventory-device").count() === 0, "missing inventory invented devices");
        assert(!/全部.*已讀取|0.*設備.*正常/.test(meta), "missing inventory was presented as a healthy empty inventory");
      },
    });
  }

  const full = inventorySnapshot();
  await runScenario(browser, "inventory-seven-sections-fields-units-and-usb-counts", {
    statusPayload: inventoryEnvelope(full),
    expectedStatus: "正常",
    check: async (frame, page, fixture) => {
      await checkInventoryShell(frame, full);
      const meta = await frame.locator("#hardwareInventoryMeta").innerText();
      assert(/採樣|更新|觀測/.test(meta) && /2026|秒|分/.test(meta), `inventory freshness missing: ${meta}`);
      await fixture.capture("collapsed");
      for (const key of inventorySectionKeys) {
        await setDetailsOpen(sectionLocator(frame, key));
        assert(await sectionLocator(frame, key).locator("article.inventory-device").count() === full.sections[key].items.length, `${key}: device count differs from fixture`);
        for (const item of full.sections[key].items) {
          const card = deviceLocator(frame, key, item.id);
          assert(await card.count() === 1, `${key}: missing stable device id ${item.id}`);
          assert((await card.innerText()).includes(item.name), `${item.id}: device name missing`);
          if (item.driver) assert((await card.innerText()).includes(item.driver), `${item.id}: driver missing`);
          await setDetailsOpen(card.locator("details.inventory-properties"));
          for (const property of Object.keys(item.properties)) {
            const value = item.properties[property];
            if (typeof value === "string" && !["kind", "operstate", "captured_at"].includes(property)) await checkProperty(card, property, value);
          }
          const propertyKeys = await card.locator(":scope > details.inventory-properties > dl.inventory-fields > div[data-property]").evaluateAll(nodes => nodes.map(node => node.dataset.property).sort());
          assert(JSON.stringify(propertyKeys) === JSON.stringify(Object.keys(item.properties).sort()), `${item.id}: complete properties disclosure omitted or duplicated fields`);
        }
      }
      const wifi = deviceLocator(frame, "network", "synthetic-wifi");
      await checkProperty(wifi, "kind", /Wi-Fi/i);
      await checkProperty(wifi, "operstate", /up/i);
      await checkProperty(wifi, "tx_bitrate_mbps", /144\.4(?:0)?\s*(?:Mbps|Mb\/s|Mbit\/s)/i);
      await checkProperty(wifi, "signal_dbm", /-47\s*dBm/i);
      await checkProperty(wifi, "frequency_mhz", /5,?180\s*MHz/i);
      await checkProperty(wifi, "mtu", /1,?500/);
      await checkProperty(wifi, "rx_bytes", /^0(?:\.0+)?(?:\s*(?:B|bytes?|位元組))?$/i);
      await checkProperty(wifi, "ipv4", "192.0.2.10/24");
      await checkProperty(wifi, "ipv6", "2001:db8::10/64");
      await checkProperty(wifi, "extra_evidence", "SYNTHETIC_ARRAY_PROPERTY");
      const ethernet = deviceLocator(frame, "network", "synthetic-ethernet");
      await checkProperty(ethernet, "tx_bitrate_mbps", /^0(?:\.0+)?\s*(?:Mbps|Mb\/s|Mbit\/s)$/i);
      await checkProperty(ethernet, "carrier", /false|否|無|未連線/i);
      await checkProperty(deviceLocator(frame, "network", "synthetic-network-unknown"), "tx_bitrate_mbps", /未知|未提供|未讀取|—/);
      await checkProperty(deviceLocator(frame, "bluetooth", "synthetic-bt-on"), "powered", /true|是|開啟|啟用/i);
      await checkProperty(deviceLocator(frame, "bluetooth", "synthetic-bt-on"), "discoverable", /false|否|關閉|停用/i);
      await checkProperty(deviceLocator(frame, "usb", "synthetic-usb-unclassified"), "speed", /5,?000\s*(?:Mbps|Mb\/s|Mbit\/s)/i);
      await checkProperty(deviceLocator(frame, "pcie", "synthetic-pcie-0"), "current_link_speed", "5.0 GT/s");
      await checkProperty(deviceLocator(frame, "pcie", "synthetic-pcie-0"), "current_link_width", /(?:[×x]\s*1|1\s*(?:lane|通道)|^1$)/i);
      const states = [
        ["network", "synthetic-wifi", /up|已連線|啟用|運作中/i],
        ["network", "synthetic-ethernet", /down|未連線|停用|未啟用/i],
        ["network", "synthetic-network-unknown", /unknown|未知/i],
        ["bluetooth", "synthetic-bt-on", /powered_on|已開啟|啟用|已供電|電源開啟/i],
        ["bluetooth", "synthetic-bt-blocked", /blocked|封鎖|阻擋|禁用|停用/i],
        ["i2c", "synthetic-i2c-client", /present|存在/i],
        ["i2c", "synthetic-i2c-telemetry", /observed|已有觀測/i],
        ["serial", "synthetic-serial-a", /present|存在|已偵測|已列出/i],
      ];
      for (const [key, id, expected] of states) {
        const text = await deviceLocator(frame, key, id).locator(".inventory-item-state").innerText();
        assert(expected.test(text), `${id}: state missing or mistranslated: ${text}`);
      }
      const counts = await sectionLocator(frame, "usb").locator(".inventory-counts").innerText();
      assert(/(?:root[ _-]?hub|根集線器)\s*[:：×x]?\s*2|2\s*(?:個\s*)?(?:root[ _-]?hub|根集線器)/i.test(counts), `USB root-hub count wrong: ${counts}`);
      assert(/外接裝置\s*3/.test(counts), `USB external-device count wrong: ${counts}`);
      assert(/類型未知\s*1/.test(counts), `USB unclassified-device count wrong: ${counts}`);
    },
  });

  const partial = inventorySnapshot();
  partial.status = "partial";
  partial.sections.network.status = "partial";
  partial.sections.network.notes = ["SYNTHETIC_NETWORK_PARTIAL_NOTE"];
  partial.sections.network.errors = ["SYNTHETIC_NETWORK_PARTIAL_ERROR"];
  partial.sections.bluetooth = inventorySection([], { status: "unavailable", errors: ["SYNTHETIC_BT_UNAVAILABLE"] });
  partial.sections.usb = inventorySection([]);
  partial.sections.pcie = inventorySection([], { status: "partial", notes: ["SYNTHETIC_PCIE_EMPTY_PARTIAL"] });
  partial.sections.i2c = inventorySection([], { status: "unavailable" });
  partial.sections.i2c.items = null;
  partial.sections.gpio = inventorySection([], { status: "partial", errors: ["SYNTHETIC_GPIO_MISSING_ITEMS"] });
  delete partial.sections.gpio.items;
  partial.sections.serial = inventorySection([]);
  delete partial.sections.serial.items;
  await runScenario(browser, "inventory-partial-unavailable-empty-and-missing-items", {
    statusPayload: inventoryEnvelope(partial),
    expectedStatus: "正常",
    check: async frame => {
      await checkInventoryShell(frame, partial);
      assert(/部分/.test(await frame.locator("#hardwareInventoryMeta").innerText()), "partial inventory was not marked partial");
      for (const key of inventorySectionKeys) {
        const section = sectionLocator(frame, key);
        await setDetailsOpen(section);
        const items = partial.sections[key].items || [];
        assert(await section.locator("article.inventory-device").count() === items.length, `${key}: missing/empty items invented devices`);
        if (!Array.isArray(partial.sections[key].items)) assert((await section.locator(".inventory-counts").innerText()).includes("未知"), `${key}: missing items became a known zero count`);
        if (!items.length) assert(/沒有|尚無|無可|未取得|未讀取|未列出|無法|未知|空/.test(await section.innerText()), `${key}: empty/unavailable explanation missing`);
        if (partial.sections[key].notes.length || partial.sections[key].errors.length) {
          await setDetailsOpen(section.locator("details.inventory-notes"));
          const notes = await section.locator("details.inventory-notes").innerText();
          for (const message of [...partial.sections[key].notes, ...partial.sections[key].errors]) assert(notes.includes(message), `${key}: note/error omitted: ${message}`);
        }
      }
    },
  });

  await runScenario(browser, "inventory-pcie-count-follows-response-not-fixed-hardware", {
    statusPayload: inventoryEnvelope(),
    expectedStatus: "正常",
    check: async (frame, page, fixture) => {
      await checkInventoryShell(frame, fixture.statusPayload.data.inventory);
      for (const count of [2, 5, 0]) {
        const next = inventorySnapshot();
        next.sections.pcie.items = Array.from({ length: count }, (_, index) => inventoryItem(`synthetic-pcie-dynamic-${index}`, `Synthetic dynamic endpoint ${index}`));
        fixture.statusPayload = inventoryEnvelope(next);
        await refreshInventory(frame, page);
        const section = sectionLocator(frame, "pcie");
        await setDetailsOpen(section);
        assert(await section.locator("article.inventory-device").count() === count, `PCIe renderer did not follow ${count} fixture devices`);
        const counts = await section.locator(".inventory-counts").innerText();
        assert(new RegExp(`(?:^|\\D)${count}(?:\\D|$)`).test(counts), `PCIe count is fixed or missing for ${count}: ${counts}`);
        assert(!/固定|必須.*[23456789].*(?:個|台)/.test(counts), `PCIe count implies a fixed hardware configuration: ${counts}`);
        await fixture.capture(`pcie-${count}`);
      }
    },
  });

  const xss = label => `<img src="/SCOUT_SYNTHETIC_XSS_${label}" onerror="window.inventoryXssExecuted+=1"><svg onload="window.inventoryXssExecuted+=1"></svg>SCOUT_SYNTHETIC_XSS_${label}`;
  const malicious = inventorySnapshot();
  malicious.status = "partial";
  const wifi = malicious.sections.network.items[0];
  wifi.name = xss("name");
  wifi.driver = xss("driver");
  wifi.state = xss("state");
  wifi.properties.ssid = xss("ssid");
  wifi.properties.extra_evidence = [xss("array_property"), false, 0];
  wifi.properties[xss("property_key")] = xss("property_value");
  malicious.sections.gpio.items[0].lines[0].consumer = xss("consumer");
  malicious.sections.gpio.items[0].lines[0].name = xss("line_name");
  malicious.sections.network.summary = xss("summary");
  malicious.sections.network.status = "partial";
  malicious.sections.network.notes = [xss("notes")];
  malicious.sections.network.errors = [xss("errors")];
  await runScenario(browser, "inventory-xss-ssid-name-consumer-properties-notes-errors-are-text", {
    statusPayload: inventoryEnvelope(malicious),
    expectedStatus: "正常",
    auditInventoryHtml: true,
    check: async (frame, page) => {
      await checkInventoryShell(frame, malicious);
      for (const key of ["network", "gpio"]) await setDetailsOpen(sectionLocator(frame, key));
      const card = deviceLocator(frame, "network", wifi.id);
      await setDetailsOpen(card.locator("details.inventory-properties"));
      await setDetailsOpen(sectionLocator(frame, "network").locator("details.inventory-notes"));
      await setDetailsOpen(deviceLocator(frame, "gpio", "synthetic-gpio-a").locator("details.inventory-lines"));
      await checkProperty(card, "ssid", wifi.properties.ssid);
      const text = await frame.locator("#hardwareInventoryGrid").innerText();
      for (const label of ["name", "driver", "ssid", "array_property", "property_key", "property_value", "consumer", "line_name", "summary", "notes", "errors"]) {
        assert(text.includes(xss(label)), `${label}: API markup was interpreted, truncated, or omitted instead of displayed literally`);
      }
      assert((await card.locator(".inventory-item-state").innerText()).includes("未知"), "unrecognized API state should fall back to unknown");
      assert(await frame.locator("#hardwareInventoryGrid img, #hardwareInventoryGrid svg, #hardwareInventoryGrid script, #hardwareInventoryGrid iframe, #hardwareInventoryGrid [onerror], #hardwareInventoryGrid [onload]").count() === 0, "API payload created executable markup");
      assert(await page.evaluate(() => window.inventoryXssExecuted) === 0, "inventory XSS payload executed");
      assert(await page.evaluate(() => window.inventoryHtmlWrites.length) === 0, "API text was passed through an HTML sink instead of textContent");
    },
  });

  await runScenario(browser, "inventory-gpio-input-output-null-values-and-false-active-low", {
    statusPayload: inventoryEnvelope(),
    expectedStatus: "正常",
    check: async frame => {
      await checkInventoryShell(frame, full);
      await setDetailsOpen(sectionLocator(frame, "gpio"));
      const card = deviceLocator(frame, "gpio", "synthetic-gpio-a");
      const details = card.locator("details.inventory-lines");
      assert(!await details.evaluate(node => node.open), "new GPIO line table should start collapsed");
      await setDetailsOpen(details);
      const rows = details.locator("tbody tr");
      assert(await rows.count() === 2, "GPIO line count was invented or incomplete");
      const headers = await details.locator("thead th").allInnerTexts();
      const column = pattern => headers.findIndex(text => pattern.test(text));
      const directionColumn = column(/方向|direction/i);
      const activeLowColumn = column(/active.?low|低.*有效|低電位/i);
      const valueColumn = column(/數值|讀值|電位|^值$|value/i);
      assert(directionColumn >= 0 && activeLowColumn >= 0 && valueColumn >= 0 && activeLowColumn !== valueColumn, `GPIO columns missing: ${headers}`);
      for (const [index, expectedDirection, expectedActiveLow] of [[0, "輸入", false], [1, "輸出", true]]) {
        const cells = rows.nth(index).locator("td");
        assert((await cells.nth(directionColumn).innerText()).includes(expectedDirection), `GPIO ${index}: direction label wrong`);
        assert((await cells.nth(valueColumn).innerText()).trim() === "未採樣", `GPIO ${index}: null became a sampled value`);
        const activeLow = (await cells.nth(activeLowColumn).innerText()).trim();
        assert((expectedActiveLow ? /^(?:true|是|啟用|低有效)(?:\s*\(true\))?$/i : /^(?:false|否|停用|高有效)(?:\s*\(false\))?$/i).test(activeLow), `GPIO ${index}: active_low ${expectedActiveLow} lost: ${activeLow}`);
      }
      assert((await rows.nth(0).locator("td").first().innerText()).trim() === "0", "GPIO offset zero was lost");
      assert((await rows.nth(0).innerText()).includes("synthetic-input-consumer"), "GPIO consumer missing");
    },
  });

  await runScenario(browser, "inventory-i2c-passive-evidence-and-serial-node-not-connection", {
    statusPayload: inventoryEnvelope(),
    expectedStatus: "正常",
    check: async (frame, page) => {
      await checkInventoryShell(frame, full);
      for (const key of ["i2c", "serial"]) await setDetailsOpen(sectionLocator(frame, key));
      const i2c = await sectionLocator(frame, "i2c").innerText();
      assert(/被動|未執行主動位址掃描/.test(i2c) && /(?:sysfs|既有|驅動|綁定)/i.test(i2c), `I2C evidence boundary missing: ${i2c}`);
      assert(/(?:不|未|無|沒有).{0,16}(?:掃描|探測|probe|scan)|僅.{0,16}(?:綁定|被動)/i.test(i2c), `I2C copy implies active bus probing: ${i2c}`);
      const serial = await sectionLocator(frame, "serial").innerText();
      assert(/節點/.test(serial) && /(?:不代表|不等於|無法確認|不能確認|不保證).{0,40}(?:外部|連線|連接)/.test(serial), `serial node was equated with an external connection: ${serial}`);
      assert(await frame.locator("#hardwareInventoryPanel button, #hardwareInventoryPanel input, #hardwareInventoryPanel select").count() === 0, "passive inventory unexpectedly exposes hardware controls");
      assert(await page.evaluate(() => window.hardwareRequestEvidence.length) === 3, "opening passive evidence triggered extra hardware requests");
    },
  });

  // Exercise identity under item and section reordering, including two GPIO chips.
  for (const automatic of [false, true]) {
    await runScenario(browser, `inventory-${automatic ? "60-second-poll" : "refresh"}-preserves-keyed-disclosures`, {
      clock: true,
      statusPayload: inventoryEnvelope(),
      expectedStatus: "正常",
      check: async (frame, page, fixture) => {
        await checkInventoryShell(frame, full);
        const gpio = sectionLocator(frame, "gpio");
        await setDetailsOpen(gpio);
        const linesA = deviceLocator(frame, "gpio", "synthetic-gpio-a").locator("details.inventory-lines");
        const propertiesA = deviceLocator(frame, "gpio", "synthetic-gpio-a").locator("details.inventory-properties");
        const notes = gpio.locator("details.inventory-notes");
        for (const details of [linesA, propertiesA, notes]) await setDetailsOpen(details);
        await setDetailsOpen(sectionLocator(frame, "network"));
        await setDetailsOpen(deviceLocator(frame, "network", "synthetic-wifi").locator("details.inventory-properties"));
        await fixture.capture("before-refresh");
        const next = inventorySnapshot();
        next.captured_at = "2026-09-11T02:00:48Z";
        next.sections.network.items[0].name = "Synthetic wireless adapter UPDATED";
        next.sections.network.items[0].properties.ssid = "SYNTHETIC_SSID_UPDATED";
        next.sections.network.items.reverse();
        next.sections.gpio.items[0].lines[0].consumer = "synthetic-updated-consumer";
        next.sections.gpio.items.reverse();
        next.sections.gpio.items.unshift(inventoryItem("synthetic-gpio-new", "Synthetic new GPIO chip", { line_count: 0 }));
        next.sections = Object.fromEntries(Object.entries(next.sections).reverse());
        fixture.statusPayload = inventoryEnvelope(next);
        const count = () => page.evaluate(() => window.hardwareRequestEvidence.length);
        assert(await count() === 3, "unexpected initial request count");
        if (automatic) {
          await page.clock.runFor(59999);
          assert(await count() === 3, "inventory polled before 60 seconds");
          await page.clock.runFor(1);
          await page.waitForFunction(() => window.hardwareRequestEvidence.length === 6 && !document.querySelector("#hardwareRefreshButton").disabled);
        } else await refreshInventory(frame, page);
        await checkInventoryShell(frame, next, { collapsed: false });
        const opened = [gpio, sectionLocator(frame, "network"), linesA, propertiesA, notes, deviceLocator(frame, "network", "synthetic-wifi").locator("details.inventory-properties")];
        for (const details of opened) assert(await details.evaluate(node => node.open), `refresh forgot expanded key: ${details}`);
        for (const key of ["bluetooth", "usb", "pcie", "i2c", "serial"]) assert(!await sectionLocator(frame, key).evaluate(node => node.open), `${key}: refresh opened an untouched section`);
        for (const id of ["synthetic-gpio-b", "synthetic-gpio-new"]) {
          for (const details of await deviceLocator(frame, "gpio", id).locator("details").all()) assert(!await details.evaluate(node => node.open), `${id}: another chip's open state leaked`);
        }
        assert((await linesA.innerText()).includes("synthetic-updated-consumer"), "disclosure preservation prevented content refresh");
        assert((await deviceLocator(frame, "network", "synthetic-wifi").innerText()).includes("Synthetic wireless adapter UPDATED"), "refreshed item name not rendered");
        await checkProperty(deviceLocator(frame, "network", "synthetic-wifi"), "ssid", "SYNTHETIC_SSID_UPDATED");
        // Closing is also state: a later refresh must not resurrect an earlier open key.
        await setDetailsOpen(notes, false);
        await setDetailsOpen(propertiesA, false);
        await setDetailsOpen(sectionLocator(frame, "network"), false);
        await refreshInventory(frame, page);
        for (const details of [notes, propertiesA, sectionLocator(frame, "network")]) assert(!await details.evaluate(node => node.open), `closed state not preserved: ${details}`);
        assert(await linesA.evaluate(node => node.open) && await gpio.evaluate(node => node.open), "closing one disclosure closed another");
      },
    });
  }

  for (const failure of ["stale-503", "disconnect", "unavailable-503", "local-age"]) {
    await runScenario(browser, `inventory-${failure}-retains-but-invalidates-sample`, {
      clock: true,
      statusPayload: inventoryEnvelope(full, { age: failure === "local-age" ? 149 : 12 }),
      expectedStatus: "正常",
      check: async (frame, page, fixture) => {
        await checkInventoryShell(frame, full);
        await setDetailsOpen(sectionLocator(frame, "gpio"));
        const lines = deviceLocator(frame, "gpio", "synthetic-gpio-a").locator("details.inventory-lines");
        await setDetailsOpen(lines);
        const before = await lines.innerText();
        await fixture.capture("fresh");
        if (failure === "local-age") await page.clock.runFor(2000);
        else {
          if (failure === "disconnect") fixture.disconnect = true;
          else {
            fixture.statusCode = 503;
            fixture.statusPayload = failure === "stale-503"
              ? inventoryEnvelope(full, { status: "stale", freshnessState: "stale", age: 181 })
              : envelope({ status: "unavailable", data: null, freshnessState: "unreadable", age: null });
          }
          await refreshInventory(frame, page);
        }
        await checkInvalidInventory(frame, full, ["stale-503", "local-age"].includes(failure) ? "資料已過期" : "無法連線");
        assert(await lines.evaluate(node => node.open), "invalidation collapsed retained GPIO evidence");
        assert(await lines.innerText() === before, "invalidation changed or erased last sampled GPIO lines");
        await fixture.capture("invalid");
        fixture.disconnect = false;
        fixture.statusCode = 200;
        fixture.statusPayload = inventoryEnvelope(full);
        await refreshInventory(frame, page);
        await checkInventoryShell(frame, full, { collapsed: false });
        const meta = await frame.locator("#hardwareInventoryMeta").innerText();
        assert(!/已過期|目前.*失效|目前.*無效|無法連線/.test(meta), `successful refresh did not clear invalidity: ${meta}`);
        for (const key of inventorySectionKeys) assert(!(await sectionLocator(frame, key).locator(".inventory-section-status").innerText()).includes("上次採樣"), `${key}: fresh recovery still labeled retained`);
        assert(await lines.evaluate(node => node.open), "recovery lost expanded GPIO state");
      },
    });
  }
}

async function run() {
  const requestedReport = process.argv[3] ? path.resolve(process.argv[3]) : null;
  if (requestedReport) {
    const relative = path.relative(artifactsRoot, requestedReport);
    assert(relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative), "report must be inside artifacts/");
    assert(!fs.existsSync(requestedReport), `refusing to overwrite existing evidence: ${requestedReport}`);
  }
  // One immutable in-memory HTML revision per run, even during parallel UI edits.
  const htmlPath = process.argv[4] ? path.resolve(process.argv[4]) : null;
  if (htmlPath) replayHtml = fs.readFileSync(htmlPath, "utf8");
  fs.mkdirSync(artifactsRoot, { recursive: true });
  artifactDir = fs.mkdtempSync(path.join(artifactsRoot, "scout-monitor-state-synthetic-"));
  console.error(`Synthetic harness artifacts: ${artifactDir}`);
  const browser = await chromium.launch({ headless: true, executablePath: chromePath });
  try {
    const splitPower = {
      status: "unavailable", ups_status: "unavailable", supply_status: "ok",
      captured_at: snapshot().captured_at, age_seconds: 1,
      ups_error_code: "communication_error", supply_error_code: null,
      battery_percent: null, flow: null, battery_power_w: null, battery_voltage_mv: null,
      ups_vbus_power_mw: null, ext5v_v: 5.18, active_throttle_bits: 0,
    };
    for (const state of ["fresh", "stale", "critical"]) {
      const status = state === "fresh" ? "warning" : state;
      await runScenario(browser, `split-power-ups-failure-${state}`, {
        statusCode: state === "stale" ? 503 : 200,
        statusPayload: envelope({ status, freshnessState: state === "stale" ? "stale" : "fresh", age: state === "stale" ? 181 : 1,
          data: snapshot({ status: state === "critical" ? "critical" : "warning", power: { ...splitPower, active_throttle_bits: state === "critical" ? 1 : 0 },
            alerts: { power_telemetry: { severity: "warning", message: "UPS 通訊失敗（I²C），主機 5V 供電仍可讀" },
              ...(state === "critical" ? { power_throttling: { severity: "critical", message: "Scout 偵測到欠壓" } } : {}) } }) }),
        expectedStatus: { fresh: "警告", stale: "資料已過期", critical: "嚴重告警" }[state],
        check: async (frame, page, fixture) => {
          assert(await frame.locator("#hardwareBatteryPercent").innerText() === "未知", "failed UPS became a battery reading");
          assert((await frame.locator("#hardwareSupplyStatus").innerText()).includes("5V 5.18 V"), "valid 5V hidden by UPS failure");
          assert((await frame.locator("#hardwarePowerNotice").innerText()).includes("UPS 通訊失敗（I²C）"), "UPS error not explained");
          assert(await frame.locator("#hardwareBatteryCard").getAttribute("data-state") === status, "power alert or staleness was hidden");
          if (state === "stale") assert((await frame.locator("#hardwareSupplyStatus").innerText()).includes("上次採樣"), "stale supply looks current");
          await page.setViewportSize({ width: 390, height: 844 });
          assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2), "partial power overflows mobile");
          await fixture.capture("mobile");
          if (state === "fresh") {
            fixture.disconnect = true;
            await frame.locator("#hardwareRefreshButton").click();
            await waitForText(frame, "#hardwareOverallStatus", "無法連線");
            assert((await frame.locator("#hardwareSupplyStatus").innerText()).includes("上次採樣"), "offline supply looks current");
            fixture.disconnect = false;
            fixture.statusPayload = envelope();
            await frame.locator("#hardwareRefreshButton").click();
            await waitForText(frame, "#hardwareOverallStatus", "正常");
            assert(await frame.locator("#hardwarePowerNotice").isHidden(), "recovery retained UPS failure notice");
            assert((await frame.locator("#hardwareBatteryPercent").innerText()).includes("80"), "recovered UPS not restored");
          }
        },
      });
    }
    await runScenario(browser, "split-power-supply-failure-keeps-battery", {
      statusPayload: envelope({ status: "critical", data: snapshot({ status: "critical",
        power: { ...snapshot().power, status: "unavailable", ups_status: "ok", supply_status: "unavailable",
          supply_error_code: "communication_error", battery_percent: 10, ext5v_v: null, active_throttle_bits: null },
        alerts: { battery: { severity: "critical", message: "電池剩餘 10%" } } }) }),
      expectedStatus: "嚴重告警",
      check: async (frame) => {
        assert((await frame.locator("#hardwareBatteryPercent").innerText()).includes("10"), "supply failure erased battery");
        assert(!(await frame.locator("#hardwareSupplyStatus").innerText()).includes("5V 0"), "missing voltage filled with zero");
        assert((await frame.locator("#hardwarePowerNotice").innerText()).includes("主機供電資料部分不可讀"), "supply failure not explained");
        assert(await frame.locator("#hardwareBatteryCard").getAttribute("data-state") === "critical", "battery alert erased by supply failure");
      },
    });
    await runScenario(browser, "split-power-missing-throttle-keeps-voltage", {
      statusPayload: envelope({ status: "warning", data: snapshot({ status: "warning", power: {
        ...snapshot().power, status: "unavailable", ups_status: "ok", supply_status: "unavailable",
        ext5v_v: 5.18, active_throttle_bits: null, supply_error_code: "communication_error",
      } }) }), expectedStatus: "警告",
      check: async (frame) => {
        const text = await frame.locator("#hardwareSupplyStatus").innerText();
        assert(text.includes("5V 5.18 V"), "failed throttle read erased voltage");
        assert(!text.includes("未見供電／效能限制"), "unknown flags were treated as zero");
      },
    });
    await runScenario(browser, "split-power-legacy-unavailable-keeps-valid-supply", {
      statusPayload: envelope({ status: "warning", data: snapshot({ status: "warning", power: {
        ...splitPower, ups_status: null, supply_status: null, ups_error_code: null, supply_error_code: null,
      } }) }), expectedStatus: "警告",
      check: async (frame) => {
        assert((await frame.locator("#hardwareSupplyStatus").innerText()).includes("5V 5.18 V"), "legacy null component statuses hid valid voltage");
        assert(await frame.locator("#hardwareBatteryPercent").innerText() === "未知", "legacy aggregate unavailable was promoted to healthy UPS");
      },
    });
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
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "正常", "status did not render independently of pending history");
        assert(await frame.locator("#hardwareRefreshButton").isDisabled(), "refresh became enabled before history completed");
        await page.clock.runFor(12000);
        const historyRequest = () => page.evaluate(() => window.hardwareRequestEvidence.find(request => request.url.includes("/history")));
        assert(!(await historyRequest()).aborted, "history was still aborted at the old 12-second timeout");
        assert(await frame.locator("#hardwareRefreshButton").isDisabled(), "pending history released refresh at 12 seconds");
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "正常", "pending history hid successful status");
        await page.clock.runFor(17999);
        assert(!(await historyRequest()).aborted, "history aborted before 30 seconds");
        await page.clock.runFor(1);
        await waitForText(frame, "#hardwareTrendMeta", "無法取得");
        await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
        assert((await historyRequest()).aborted, "history request was not bounded by the 30-second timeout");
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "正常", "history timeout discarded successful status");
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
    await runScenario(browser, "history-13-second-response-succeeds-with-independent-status", {
      clock: true,
      deferHistory: true,
      statusPayload: envelope(),
      historyPayload: listEnvelope(history),
      expectedStatus: "正常",
      check: async (frame, page, fixture) => {
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "正常", "status waited for the delayed history response");
        assert(await frame.locator("#hardwareRefreshButton").isDisabled(), "history was not pending");
        await page.clock.runFor(12000);
        assert(await page.evaluate(() => window.hardwareRequestEvidence.filter(request => request.url.includes("/history")).every(request => !request.aborted)), "13-second history was aborted at 12 seconds");
        await page.clock.runFor(1000);
        assert(typeof fixture.releaseHistory === "function", "delayed history route was not captured");
        await fixture.releaseHistory();
        await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
        await waitForText(frame, "#hardwareTrendMeta", "歷史紀錄");
        assert(await frame.locator("#hardwareCpuPathPoints circle").count() === 5, "13-second history response did not render fixture points");
        assert(await page.evaluate(() => window.hardwareRequestEvidence.filter(request => request.url.includes("/history")).every(request => !request.aborted)), "successful delayed history was aborted");
        assert(await frame.locator("#hardwareOverallStatus").innerText() === "正常", "successful delayed history changed status");
      },
    });
    await runScenario(browser, "status-events-keep-12-second-timeout-while-history-has-30", {
      clock: true,
      stall: true,
      stallHistory: true,
      expectedStatus: "載入中",
      check: async (frame, page) => {
        await page.clock.runFor(11999);
        assert(await page.evaluate(() => window.hardwareRequestEvidence.length === 3 && window.hardwareRequestEvidence.every(request => !request.aborted)), "a hardware request timed out before 12 seconds");
        await page.clock.runFor(1);
        await waitForText(frame, "#hardwareOverallStatus", "無法連線");
        await page.waitForFunction(() => window.hardwareRequestEvidence.filter(request => /\/(?:status|events)(?:\?|$)/.test(request.url)).every(request => request.aborted));
        assert(await page.evaluate(() => window.hardwareRequestEvidence.find(request => request.url.includes("/history")).aborted === false), "history inherited the status/events timeout");
        assert(await frame.locator("#hardwareRefreshButton").isDisabled(), "pending history did not keep refresh busy");
        await page.clock.runFor(18000);
        await page.waitForFunction(() => !document.querySelector("#hardwareRefreshButton").disabled);
        assert(await page.evaluate(() => window.hardwareRequestEvidence.every(request => request.aborted)), "a stalled endpoint remained unbounded");
      },
    });
    await runInventoryScenarios(browser);
    const report = {
      ok: scenarioResults.length > 0 && scenarioResults.every(result => result.ok),
      evidence_kind: "synthetic_browser_harness",
      real_runtime_qualification: false,
      runtime_safety_truth: false,
      baseUrl,
      html: htmlPath ? {
        source: htmlPath,
        sha256: createHash("sha256").update(replayHtml).digest("hex"),
        changed_on_disk_during_run: replayHtml !== fs.readFileSync(htmlPath, "utf8"),
      } : { source: "served_entrypoint", api_responses: "synthetic_stubs_only" },
      artifactDir,
      suite_complete: skippedScenarios.length === 0,
      scenario_filter: process.env.SCOUT_STATE_SCENARIOS || null,
      skippedScenarios,
      scenarios: completedScenarios,
      failedScenarios: scenarioResults.filter(result => !result.ok).map(result => result.name),
      results: scenarioResults,
    };
    const reportPath = path.join(artifactDir, "report.json");
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), { flag: "wx" });
    if (requestedReport && requestedReport !== reportPath) {
      fs.mkdirSync(path.dirname(requestedReport), { recursive: true });
      fs.writeFileSync(requestedReport, JSON.stringify(report, null, 2), { flag: "wx" });
    }
    if (!report.ok) process.exitCode = 1;
    console.log(JSON.stringify({ ...report, reportPath, results: undefined }, null, 2));
  } finally {
    await browser.close();
  }
}

run().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
