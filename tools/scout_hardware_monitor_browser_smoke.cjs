const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const {chromium} = require('playwright');

async function main() {
  const base = process.argv[2] || 'http://127.0.0.1:9151';
  const output = process.argv[3] || '/tmp/scout-hardware-monitor-browser';
  await fs.mkdir(output, {recursive: true});
  const browser = await chromium.launch({headless: true, ...(process.env.SCOUT_CHROME_PATH ? {executablePath: process.env.SCOUT_CHROME_PATH} : {})});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [];
    const hardwareRequests = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', request => {
      if (new URL(request.url()).pathname.startsWith('/api/v1/hardware-monitor/')) hardwareRequests.push({url: request.url(), method: request.method()});
    });
    const statusResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/hardware-monitor/status');
    const historyResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/hardware-monitor/history');
    await page.goto(base + '/monitor');
    const real = await (await statusResponse).json();
    const history = await (await historyResponse).json();
    assert.ok(real.data?.inventory, 'real inventory must be present');
    assert.ok(real.data.hailo?.devices.length, 'real Hailo telemetry must be present; legacy data cannot qualify the new feature');
    await page.locator('#inventory .device').first().waitFor();
    const hailoReadings = [];
    for (const device of real.data.hailo.devices) {
      const card = page.locator('[data-hailo-device]').filter({has: page.locator('h3', {hasText: device.device_id})});
      assert.equal(await card.count(), 1);
      if (await card.getAttribute('open') === null) await card.locator(':scope > summary').click();
      const actual = {};
      for (const field of ['nnc_utilization_percent', 'cpu_utilization_percent', 'ram_utilization_percent', 'ram_used_bytes', 'ram_total_bytes', 'temperature_c', 'voltage_mv']) {
        const value = device[field];
        const expected = !Number.isFinite(value) ? '未知' : field.endsWith('_bytes') ? `${(value / 1024 ** 3).toFixed(2)} GiB`
          : field.endsWith('_percent') ? `${value.toFixed(1)} %` : field === 'temperature_c' ? `${value.toFixed(1)} °C` : `${value.toFixed(0)} mV`;
        actual[field] = await card.locator(`[data-hailo-metric="${field}"]`).innerText();
        assert.equal(actual[field], expected, `real Hailo ${field}`);
      }
      hailoReadings.push({device_id: device.device_id, captured_at: real.data.hailo.captured_at, actual});
    }
    assert.ok((await page.locator('#hailo-meta').innerText()).includes('hailortcli.monitor'));
    await page.locator('#hailo-history-details > summary').focus();
    await page.keyboard.press('Enter');
    const expectedHistoryDevices = [...new Set(history.items.flatMap(item => (item.hailo?.devices || []).map(device => device.device_id)))].sort();
    const historyDevices = await page.locator('#hailo-trends [data-device-id]').evaluateAll(nodes => [...new Set(nodes.map(node => node.dataset.deviceId))].sort());
    assert.deepEqual(historyDevices, expectedHistoryDevices, 'real Hailo historical device IDs');
    const firstHailo = page.locator('[data-hailo-device]').first();
    await firstHailo.locator(':scope > summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await firstHailo.getAttribute('open'), null, 'keyboard collapses device');
    const actualPower = real.data.power;
    if (actualPower.ups_status === 'unavailable') assert.match(await page.locator('#metrics .metric').first().innerText(), /—%/);
    if (actualPower.supply_status && Number.isFinite(actualPower.ext5v_v)) assert.ok((await page.locator('#metrics').innerText()).includes(`5V 供電 ${actualPower.ext5v_v.toFixed(2)} V`));
    if (actualPower.ups_error_code === 'communication_error') assert.match(await page.locator('#metrics').innerText(), /UPS 通訊失敗（I²C）/);
    assert.ok(await page.getByText('無線／有線網路', {exact: true}).count());
    assert.ok(await page.getByText('藍牙', {exact: true}).count());
    for (const width of [1440, 1024, 768, 320]) {
      await page.setViewportSize({width, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow at ${width}`);
      if ([1440, 320].includes(width)) await page.screenshot({path: `${output}/monitor-${width}.png`, fullPage: true});
    }
    await page.setViewportSize({width: 1280, height: 900});
    await page.locator('details[data-key="gpio"] > summary').click();
    await page.locator('.line-details > summary').first().click();
    await page.locator('.line-details[open] table').first().waitFor();
    await page.locator('#refresh').focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.ok(await page.locator('.line-details[open]').count(), 'expanded lines should survive refresh');
    assert.equal(await firstHailo.getAttribute('open'), null, 'Hailo collapsed device survives refresh');
    assert.notEqual(await page.locator('#hailo-history-details').getAttribute('open'), null, 'Hailo history remains expanded');
    await firstHailo.locator(':scope > summary').click();
    for (const width of [1440, 320]) {
      await page.setViewportSize({width, height: 1000});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `expanded Hailo overflow at ${width}`);
      await page.locator('#hailo-panel').screenshot({path: `${output}/hailo-${width}.png`});
    }
    await page.screenshot({path: `${output}/monitor-gpio.png`, fullPage: true});

    const scenarios = ['warning', 'critical', 'stale', 'unavailable', 'unknown', 'offline', 'empty', 'ups_failure', 'supply_failure', 'throttle_failure', 'power_recovery', 'legacy_partial', 'hailo_legacy', 'hailo_partial', 'hailo_stale', 'hailo_zero', 'hailo_offline_retained', 'hailo_recovery'];
    for (const scenario of scenarios) {
      const fixture = JSON.parse(JSON.stringify(real));
      fixture.server_time = new Date().toISOString();
      fixture.freshness.age_seconds = scenario === 'stale' ? 151 : 1;
      fixture.status = ['warning', 'critical', 'stale', 'unavailable'].includes(scenario) ? scenario : 'ok';
      fixture.freshness.state = scenario === 'stale' ? 'stale' : scenario === 'unavailable' ? 'missing' : 'fresh';
      fixture.freshness.captured_at = fixture.server_time;
      fixture.data.hailo.captured_at = fixture.server_time;
      if (scenario === 'hailo_legacy') fixture.data.hailo = null;
      if (scenario === 'hailo_stale') fixture.data.hailo.captured_at = new Date(Date.now() - 151000).toISOString();
      if (scenario === 'hailo_partial') {
        fixture.data.hailo.status = 'partial';
        fixture.data.hailo.devices[0].status = 'partial';
        fixture.data.hailo.devices[0].temperature_c = null;
        fixture.data.hailo.devices[0].errors = ['<img src=x onerror="window.unwanted=true"> unknown:temperature_c'];
      }
      if (scenario === 'hailo_zero') fixture.data.hailo.devices[0].nnc_utilization_percent = 0;
      if (scenario === 'unavailable') fixture.data = null;
      if (scenario === 'unknown') {
        fixture.data.power = {status: 'unavailable', battery_percent: null};
        fixture.data.cpu_used_percent = null;
      }
      if (scenario === 'ups_failure') {
        fixture.status = 'warning';
        fixture.data.power = {status: 'unavailable', ups_status: 'unavailable', supply_status: 'ok', ups_error_code: 'communication_error',
          captured_at: fixture.data.captured_at, battery_percent: null, ext5v_v: 5.18, active_throttle_bits: 0};
      }
      if (scenario === 'legacy_partial') {
        fixture.status = 'warning';
        fixture.data.power = {status: 'unavailable', ups_status: null, supply_status: null,
          captured_at: fixture.data.captured_at, battery_percent: null, ext5v_v: 5.18, active_throttle_bits: 0};
      }
      if (['supply_failure', 'throttle_failure', 'power_recovery'].includes(scenario)) {
        fixture.status = scenario === 'power_recovery' ? 'ok' : 'warning';
        fixture.data.power = {status: scenario === 'power_recovery' ? 'ok' : 'unavailable', ups_status: 'ok', supply_status: scenario === 'power_recovery' ? 'ok' : 'unavailable',
          battery_percent: 80, battery_power_w: -2.5, ext5v_v: scenario === 'supply_failure' ? null : 5.18,
          active_throttle_bits: scenario === 'throttle_failure' ? null : 0, captured_at: fixture.data.captured_at};
      }
      if (scenario === 'warning' || scenario === 'critical') fixture.data.alerts = {test: {severity: scenario, message: '<img src=x onerror="window.unwanted=true"> fixture alert'}};
      await page.route('**/api/v1/hardware-monitor/status', (route) => ['offline', 'hailo_offline_retained'].includes(scenario) ? route.abort() : route.fulfill({status: ['stale','unavailable'].includes(scenario) ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fixture)}));
      if (scenario === 'empty') {
        await page.route('**/api/v1/hardware-monitor/history?*', (route) => route.fulfill({json: {schema_version: real.schema_version, status: 'ok', items: []}}));
        await page.route('**/api/v1/hardware-monitor/events?*', (route) => route.fulfill({json: {schema_version: real.schema_version, status: 'ok', items: []}}));
      }
      await page.locator('#refresh').click();
      await page.waitForFunction(() => !document.getElementById('refresh').disabled);
      assert.equal(await page.evaluate(() => window.unwanted === true), false, 'API text must not execute markup');
      if (scenario === 'stale') assert.match(await page.locator('#status').innerText(), /資料已過期/);
      if (['stale', 'hailo_stale'].includes(scenario)) assert.match(await page.locator('#hailo-state').innerText(), /資料已過期/);
      if (scenario === 'hailo_legacy') assert.match(await page.locator('#hailo-devices').innerText(), /等待.*更新/);
      if (scenario === 'hailo_partial') {
        assert.equal(await page.locator('[data-hailo-metric="temperature_c"]').first().innerText(), '未知');
        assert.match(await page.locator('#hailo-state').innerText(), /部分可讀/);
        assert.equal(await page.locator('#hailo-panel img').count(), 0);
      }
      if (['hailo_zero', 'hailo_offline_retained'].includes(scenario)) assert.equal(await page.locator('[data-hailo-metric="nnc_utilization_percent"]').first().innerText(), '0.0 %');
      if (scenario === 'hailo_offline_retained') assert.match(await page.locator('#hailo-freshness').innerText(), /與 Scout 斷線.*最後取得/);
      if (scenario === 'hailo_recovery') { assert.match(await page.locator('#hailo-state').innerText(), /已讀取/); assert.equal(await page.locator('#hailo-freshness').isVisible(), false); }
      if (scenario === 'offline') assert.match(await page.locator('#status').innerText(), /連線失敗/);
      if (scenario === 'unavailable') assert.match(await page.locator('#metrics').innerText(), /沒有可顯示/);
      if (scenario === 'unknown') assert.match(await page.locator('#metrics .metric').first().innerText(), /—%/);
      if (scenario === 'empty') assert.match(await page.locator('#events').innerText(), /沒有狀態變更/);
      if (scenario === 'ups_failure') {
        assert.match(await page.locator('#metrics .metric').first().innerText(), /—%/);
        assert.match(await page.locator('#metrics').innerText(), /5V 供電 5\.18 V/);
        assert.match(await page.locator('#metrics').innerText(), /UPS 通訊失敗（I²C）/);
      }
      if (scenario === 'legacy_partial') {
        assert.match(await page.locator('#metrics .metric').first().innerText(), /—%/);
        assert.match(await page.locator('#metrics').innerText(), /5V 供電 5\.18 V/);
      }
      if (['supply_failure', 'throttle_failure', 'power_recovery'].includes(scenario)) {
        assert.match(await page.locator('#metrics .metric').first().innerText(), /80%/);
        if (scenario !== 'supply_failure') assert.match(await page.locator('#metrics').innerText(), /5V 供電 5\.18 V/);
        if (scenario === 'power_recovery') assert.doesNotMatch(await page.locator('#metrics').innerText(), /通訊失敗|部分不可讀/);
      }
      await page.unrouteAll({behavior: 'wait'});
    }
    assert.deepEqual(errors, []);
    assert.ok(hardwareRequests.every(request => request.method === 'GET' && new URL(request.url).origin === new URL(base).origin), 'fixed same-origin read-only APIs');
    const report = {status: 'passed', base, viewport_widths: [1440,1024,768,320], scenarios, page_errors: errors, actual_power: actualPower,
      actual_inventory_sections: Object.keys(real.data.inventory.sections), hailoReadings, realHailoHistoryDevices: historyDevices,
      hardwareRequests, fixture_scenarios_are_runtime_qualification: false, screenshots: output};
    await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report));
    await context.close();
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
