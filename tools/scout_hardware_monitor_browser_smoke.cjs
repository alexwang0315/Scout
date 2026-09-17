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
    page.on('pageerror', (error) => errors.push(error.message));
    const response = await page.request.get(base + '/api/v1/hardware-monitor/status');
    const real = await response.json();
    assert.ok(real.data?.inventory, 'real inventory must be present');
    await page.goto(base + '/monitor');
    await page.locator('#inventory .device').first().waitFor();
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
    await page.screenshot({path: `${output}/monitor-gpio.png`, fullPage: true});

    const scenarios = ['warning', 'critical', 'stale', 'unavailable', 'unknown', 'offline', 'empty', 'ups_failure', 'supply_failure', 'throttle_failure', 'power_recovery', 'legacy_partial'];
    for (const scenario of scenarios) {
      const fixture = JSON.parse(JSON.stringify(real));
      fixture.server_time = new Date().toISOString();
      fixture.freshness.age_seconds = scenario === 'stale' ? 151 : 1;
      fixture.status = ['warning', 'critical', 'stale', 'unavailable'].includes(scenario) ? scenario : 'ok';
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
      await page.route('**/api/v1/hardware-monitor/status', (route) => scenario === 'offline' ? route.abort() : route.fulfill({status: ['stale','unavailable'].includes(scenario) ? 503 : 200, contentType: 'application/json', body: JSON.stringify(fixture)}));
      if (scenario === 'empty') {
        await page.route('**/api/v1/hardware-monitor/history?*', (route) => route.fulfill({json: {schema_version: real.schema_version, status: 'ok', items: []}}));
        await page.route('**/api/v1/hardware-monitor/events?*', (route) => route.fulfill({json: {schema_version: real.schema_version, status: 'ok', items: []}}));
      }
      await page.locator('#refresh').click();
      await page.waitForFunction(() => !document.getElementById('refresh').disabled);
      assert.equal(await page.evaluate(() => window.unwanted === true), false, 'API text must not execute markup');
      if (scenario === 'stale') assert.match(await page.locator('#status').innerText(), /資料已過期/);
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
    const report = {status: 'passed', base, viewport_widths: [1440,1024,768,320], scenarios, page_errors: errors, actual_power: actualPower,
      actual_inventory_sections: Object.keys(real.data.inventory.sections), screenshots: output};
    await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report));
    await context.close();
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
