"""Focused Hailo UI replays, not live hardware or Dashboard qualification.

Execute the real monitor document. All network responses are fixtures; no SSH,
server, .env, hardware control, existing Diagnostic, or deployment is involved.
"""

import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = r"""
const assert = require('node:assert/strict'), fs = require('node:fs');
const html = fs.readFileSync('tools/scout_hardware_monitor.html', 'utf8');
const base = Date.parse('2026-09-15T04:00:00Z');
const stamp = seconds => new Date(base + seconds * 1000).toISOString();
const id = 'pci/0001:03:00.0', otherId = 'pci/0001:04:00.0';
function device(overrides = {}) {
  return {device_id: id, architecture: 'HAILO10H', status: 'ok',
    nnc_utilization_percent: 12.5, cpu_utilization_percent: 0.2,
    ram_utilization_percent: 18.75, ram_used_bytes: 1.5 * 1024 ** 3,
    ram_total_bytes: 8 * 1024 ** 3, temperature_c: 46.3, voltage_mv: 802,
    errors: [], ...overrides};
}
function hailo(overrides = {}) {
  return {captured_at: stamp(300), status: 'ok', source: 'hailortcli.monitor',
    sample_window_ms: 1000, read_only: true, devices: [device()], errors: [], ...overrides};
}
function snapshot(value) {
  return {captured_at: stamp(301), status: 'ok', host: 'fixture-scout',
    cpu_used_percent: 33.3, memory: null, power: null, sensors: [], disks: [],
    thresholds: {}, alerts: {}, errors: {}, inventory: null,
    ...(value === undefined ? {} : {hailo: value})};
}
function envelope(value = hailo(), overrides = {}) {
  return {status: 'ok', data: snapshot(value), freshness: {state: 'fresh',
    captured_at: stamp(301), age_seconds: 0, stale_after_seconds: 150,
    sample_interval_seconds: 60}, ...overrides};
}
function historySample(seconds, devices = [device()]) {
  return {...snapshot(hailo({captured_at: stamp(seconds), devices})), captured_at: stamp(seconds + 1)};
}
const apiRoot = '/admin/dashboard/scout-monitor/api/v1/hardware-monitor/';
"""

DOM_REPLAY = FIXTURES + r"""
const {JSDOM, VirtualConsole} = require('jsdom');
const errors = [], requests = [], results = {};
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => errors.push(String(error)));
const win = new JSDOM(html, {url: 'http://scout-monitor.test/admin/dashboard/scout-monitor',
  runScripts: 'outside-only', virtualConsole}).window;
const doc = win.document;
win.Date.now = () => base + 301000;
win.fetch = async (path, options) => {
  requests.push({path, method: options.method});
  throw Error('Test network disabled');
};
for (const script of doc.querySelectorAll('script:not([src])')) win.eval(script.textContent);
const initial = {state: doc.getElementById('hardwareHailoPanel').dataset.state,
  text: doc.getElementById('hardwareHailoMeta').textContent,
  count: doc.querySelectorAll('[data-hailo-metric]').length};
const panel = () => doc.getElementById('hardwareHailoPanel');
const devices = () => [...doc.querySelectorAll('#hardwareHailoDevices > details')];
const card = (key = id) => devices().find(node => node.dataset.hailoDevice === key);
const metric = (name, key = id) => card(key).querySelector(`[data-hailo-metric="${name}"]`).textContent;
const trend = (key = id) => [...doc.querySelectorAll('#hardwareHailoTrends > details')].find(node => node.dataset.hailoTrendDevice === key);
const chart = (name, key = id) => trend(key).querySelector(`[data-hailo-series="${name}"]`);
const text = id => doc.getElementById(id).textContent;
function apply(value = hailo(), overrides = {}, httpStatus = 200) {
  win.applyHardwareStatusResult({response: {ok: httpStatus === 200, status: httpStatus},
    payload: envelope(value, overrides)});
}
function history(items, status = 'ok') {
  win.applyHardwareHistoryResult({response: {ok: true, status: 200},
    payload: {status, items, meta: {count: items.length}}});
}
const cases = {
  loading_placement_and_readonly_boundary() {
    assert.equal(initial.state, 'loading');
    assert.match(initial.text, /正在讀取 Hailo/);
    assert.equal(initial.count, 0);
    assert.equal(panel().previousElementSibling.className, 'hardware-metrics-grid');
    assert.ok(panel().nextElementSibling.querySelector('#hardwareDisksTitle'));
    assert.equal(text('hardwareHailoTitle'), 'AI HAT／Hailo');
    assert.match(panel().textContent, /每 60 秒採樣約 1 秒/);
    assert.match(panel().textContent, /不是連續推論或功能健康證明/);
    assert.match(panel().textContent, /NNC 0% 不代表故障/);
    assert.match(panel().textContent, /晶片電壓不等於功耗/);
    assert.equal(panel().querySelectorAll('button,input,select,textarea,a').length, 0);
    assert.equal(doc.querySelectorAll('.hardware-thresholds > summary').length, 1,
      'Hailo history must not reuse the existing alert-threshold disclosure identity');
  },
  values_units_source_and_actual_taipei_time() {
    apply();
    assert.equal(metric('nnc_utilization_percent'), '12.5%');
    assert.equal(metric('cpu_utilization_percent'), '0.2%');
    assert.equal(metric('ram_utilization_percent'), '18.8%');
    assert.equal(metric('ram_used_bytes'), '1.50 GiB');
    assert.equal(metric('ram_total_bytes'), '8.00 GiB');
    assert.equal(metric('temperature_c'), '46.3 °C');
    assert.equal(metric('voltage_mv'), '802 mV');
    assert.equal(metric('source'), 'hailortcli.monitor');
    assert.match(metric('captured_at'), /2026\/09\/15.*12:05:00/);
    assert.match(text('hardwareHailoMeta'), /採樣視窗 1 秒.*唯讀旗標 是/);
    assert.equal(card().querySelector('.inventory-section-status').textContent, '✓ 已讀取');
    assert.equal(text('hardwareHailoStatus'), '✓ 已讀取');
    assert.equal(text('hardwareHailoAge'), '1 秒');
    assert.equal(text('hardwareCpuPercent'), '33.3%'); // Never replace host CPU with Hailo CPU.
  },
  zero_null_missing_and_new_null_replace_previous_values() {
    const numeric = ['nnc_utilization_percent', 'cpu_utilization_percent', 'ram_utilization_percent',
      'ram_used_bytes', 'ram_total_bytes', 'temperature_c', 'voltage_mv'];
    apply(hailo({devices: [device(Object.fromEntries(numeric.map(name => [name, 0])))]}));
    for (const name of numeric.slice(0, 3)) assert.equal(metric(name), '0.0%');
    assert.equal(metric('ram_used_bytes'), '0.00 GiB');
    assert.equal(metric('ram_total_bytes'), '0.00 GiB');
    assert.equal(metric('temperature_c'), '0.0 °C');
    assert.equal(metric('voltage_mv'), '0 mV');
    assert.equal(panel().dataset.state, 'ok');
    for (const unknown of [null, undefined, '0', false, NaN, Infinity]) {
      apply(hailo({devices: [device(Object.fromEntries(numeric.map(name => [name, unknown])))]}));
      for (const name of [...numeric.slice(0, 3), 'temperature_c', 'voltage_mv']) assert.equal(metric(name), '未知');
      assert.equal(metric('ram_used_bytes'), '未知');
      assert.equal(metric('ram_total_bytes'), '未知');
    }
    apply();
    apply(hailo({devices: [device({nnc_utilization_percent: null, temperature_c: null, ram_used_bytes: null})]}));
    assert.equal(metric('nnc_utilization_percent'), '未知');
    assert.equal(metric('temperature_c'), '未知');
    assert.equal(metric('ram_used_bytes'), '未知');
    assert.equal(metric('ram_total_bytes'), '8.00 GiB');
  },
  legacy_null_empty_and_missing_device_list_are_distinct() {
    for (const value of [null, undefined]) {
      apply();
      win.applyHardwareStatusResult({response: {ok: true, status: 200}, payload: envelope(hailo(), {data: snapshot(value)})});
      assert.equal(devices().length, 0);
      assert.match(text('hardwareHailoMeta'), /這筆採樣沒有 Hailo 資料，等待更新/);
      assert.doesNotMatch(panel().textContent, /12\.5%/);
    }
    apply(hailo({devices: []}));
    assert.match(text('hardwareHailoDevices'), /此筆採樣未列出 Hailo 裝置/);
    apply(hailo({devices: null}));
    assert.match(text('hardwareHailoDevices'), /裝置清單未知/);
    apply(hailo(), {data: null});
    assert.equal(devices().length, 0);
    assert.match(text('hardwareHailoMeta'), /尚無 Hailo 採樣，等待更新/);
  },
  partial_unavailable_multiple_devices_and_errors() {
    const thirdId = 'pci/0002:01:00.0';
    apply(hailo({status: 'partial', errors: ['一個裝置讀取不完整'], devices: [device(),
      device({device_id: otherId, status: 'partial', nnc_utilization_percent: 0,
        temperature_c: null, errors: ['temperature unavailable']}),
      device({device_id: thirdId, status: 'unavailable', nnc_utilization_percent: null,
        temperature_c: null, errors: ['monitor unavailable']})]}));
    assert.equal(devices().length, 3);
    assert.equal(panel().dataset.state, 'partial');
    assert.match(text('hardwareHailoMeta'), /△ 部分讀取/);
    assert.equal(metric('nnc_utilization_percent', otherId), '0.0%');
    assert.equal(metric('temperature_c', otherId), '未知');
    assert.match(card(otherId).textContent, /△ 部分讀取.*temperature unavailable/s);
    assert.match(card(thirdId).textContent, /\? 無法讀取.*monitor unavailable/s);
    assert.match(text('hardwareHailoErrorList'), /一個裝置讀取不完整/);
    apply(hailo({status: 'unavailable', devices: [], errors: ['HailoRT 未提供採樣']}));
    assert.match(text('hardwareHailoMeta'), /無法讀取/);
    assert.equal(text('hardwareOverallStatus'), '正常'); // Backend overall status, not invented alerts.
  },
  empty_device_read_failure_never_claims_absence() {
    for (const status of ['unavailable', 'partial', null, undefined, 'unexpected']) {
      apply(); // A newly returned empty list replaces a previous device, not a transport failure.
      apply(hailo({status, devices: []}));
      assert.equal(devices().length, 0);
      assert.match(text('hardwareHailoDevices'), /裝置清單無法確認/);
      assert.doesNotMatch(text('hardwareHailoDevices'), /未列出|沒有偵測到|未偵測到|沒有裝置/);
      assert.equal(text('hardwareOverallStatus'), '正常');
    }
    apply(hailo({status: 'ok', devices: []}));
    assert.match(text('hardwareHailoDevices'), /此筆採樣未列出 Hailo 裝置/);
    assert.doesNotMatch(text('hardwareHailoDevices'), /無法確認/);
    apply(hailo({status: 'unavailable', devices: []}), {status: 'stale'}, 503);
    assert.match(text('hardwareHailoDevices'), /裝置清單無法確認/);
    assert.match(text('hardwareHailoMeta'), /資料已過期/);
  },
  stale_disconnect_unknown_and_recovery_keep_truthful_values() {
    apply();
    apply(hailo(), {status: 'stale'}, 503);
    assert.equal(text('hardwareOverallStatus'), '資料已過期');
    assert.equal(panel().dataset.state, 'stale');
    assert.equal(metric('nnc_utilization_percent'), '12.5%');
    assert.match(text('hardwareHailoMeta'), /資料已過期.*保留最後採樣/);
    assert.match(card().querySelector('.inventory-section-status').textContent, /上次採樣/);
    win.applyHardwareStatusResult({response: null, payload: null, error: Error('offline')});
    assert.equal(panel().dataset.state, 'unavailable');
    assert.match(text('hardwareHailoMeta'), /斷線.*上次採樣/);
    assert.equal(metric('temperature_c'), '46.3 °C');
    apply(hailo({devices: [device({nnc_utilization_percent: 6.7})]}));
    assert.equal(metric('nnc_utilization_percent'), '6.7%');
    assert.equal(panel().dataset.state, 'ok');
    assert.doesNotMatch(text('hardwareHailoMeta'), /上次採樣|資料已過期|斷線/);
    apply(hailo(), {freshness: {...envelope().freshness, state: 'stale'}});
    assert.equal(panel().dataset.state, 'stale');
    apply(hailo(), {freshness: {...envelope().freshness, age_seconds: 151}});
    assert.equal(panel().dataset.state, 'stale');
    apply(hailo(), {freshness: null});
    assert.equal(panel().dataset.state, 'unknown');
    assert.match(text('hardwareHailoMeta'), /資料有效性未知/);
    apply(hailo(), {status: 'stale', data: null}, 503);
    assert.equal(devices().length, 0);
    assert.match(text('hardwareHailoMeta'), /資料已過期.*等待更新/);
  },
  hailo_age_and_staleness_are_independent_of_host_capture() {
    apply(hailo({captured_at: stamp(302)}), {freshness: {...envelope().freshness, age_seconds: 2}});
    // Hailo query ended one second after the host snapshot; its age is one second less.
    assert.match(metric('captured_at'), /12:05:02/);
    assert.equal(text('hardwareHailoAge'), '1 秒');
    assert.equal(panel().dataset.state, 'ok');
    apply(hailo({captured_at: stamp(150)})); // Host envelope is fresh, Hailo is 151s old.
    assert.equal(text('hardwareOverallStatus'), '正常');
    assert.equal(text('hardwareDataAge'), '0 秒');
    assert.equal(text('hardwareHailoAge'), '2 分 31 秒');
    assert.equal(panel().dataset.state, 'stale');
    assert.equal(metric('temperature_c'), '46.3 °C');
    assert.match(text('hardwareHailoMeta'), /資料已過期/);
    apply(hailo({captured_at: stamp(152)}));
    assert.equal(panel().dataset.state, 'ok');
    win.Date.now = () => base + 304000;
    win.updateHardwareHailoAge();
    assert.equal(panel().dataset.state, 'stale');
    assert.equal(text('hardwareHailoAge'), '2 分 32 秒');
    assert.equal(text('hardwareOverallStatus'), '正常');
    win.Date.now = () => base + 301000;
    apply(hailo({captured_at: null}));
    assert.equal(panel().dataset.state, 'unknown');
    assert.equal(text('hardwareHailoAge'), '未知');
  },
  scout_time_anchor_survives_mac_clock_skew_and_future_samples_fail_unknown() {
    try {
      for (const offset of [-86400000, 86400000]) {
        win.Date.now = () => base + 301000 + offset;
        apply(hailo({captured_at: stamp(302)}), {
          freshness: {...envelope().freshness, age_seconds: 42}, server_time: stamp(900)});
        assert.equal(text('hardwareDataAge'), '42 秒');
        assert.equal(text('hardwareHailoAge'), '41 秒'); // Prefer freshness to a conflicting server_time.
        assert.equal(panel().dataset.state, 'ok');
        win.Date.now = () => base + 306000 + offset;
        win.updateHardwareHailoAge();
        assert.equal(text('hardwareHailoAge'), '46 秒');
        win.applyHardwareStatusResult({response: null, payload: null});
        assert.equal(text('hardwareHailoAge'), '46 秒'); // Failure does not reset the anchor.
        apply(hailo({captured_at: stamp(100)}), {freshness: {...envelope().freshness, age_seconds: 0}});
        assert.equal(panel().dataset.state, 'stale');
        assert.equal(text('hardwareHailoAge'), '3 分 21 秒');
        assert.equal(text('hardwareOverallStatus'), '正常');
        apply(hailo(), {freshness: {...envelope().freshness, captured_at: null}, server_time: stamp(345)});
        assert.equal(text('hardwareHailoAge'), '45 秒');
        for (const captured_at of [null, undefined, 'not-a-date', '2026-09-15T04:05:00']) {
          apply(hailo({captured_at}));
          assert.equal(text('hardwareHailoAge'), '未知');
          assert.equal(metric('captured_at'), '未知');
          assert.equal(panel().dataset.state, 'unknown');
        }
        apply(hailo({captured_at: stamp(900)}));
        assert.equal(text('hardwareHailoAge'), '未知');
        assert.equal(panel().dataset.state, 'unknown');
        assert.match(text('hardwareHailoStatus'), /有效性未知/);
        assert.equal(text('hardwareOverallStatus'), '正常');
      }
    } finally { win.Date.now = () => base + 301000; }
    apply(hailo({captured_at: stamp(299)}), {freshness: null}); // No Scout anchor: local-clock fallback only.
    assert.equal(text('hardwareHailoAge'), '2 秒');
    apply(hailo({captured_at: stamp(900)}), {freshness: null});
    assert.equal(text('hardwareHailoAge'), '未知');
  },
  untrusted_ids_sources_architectures_and_errors_are_plain_text() {
    const payload = '<img src=x onerror="globalThis.__hailoXss=1"><svg onload=alert(1)>',
      poisoned = device({device_id: payload, architecture: payload, errors: [payload]});
    apply(hailo({source: payload, devices: [poisoned], errors: [payload]}));
    history([historySample(0, [poisoned]), historySample(60, [poisoned])]);
    assert.equal(devices().length, 1);
    assert.ok(card(payload));
    assert.equal(metric('source', payload), payload);
    assert.match(card(payload).textContent, /<img src=x/);
    assert.ok(text('hardwareHailoErrorList').includes(payload));
    assert.ok(trend(payload));
    assert.equal(panel().querySelectorAll('img,iframe,script,svg[onload],[onerror]').length, 0);
    assert.equal(win.__hailoXss, undefined);
    apply(hailo({source: null, captured_at: null, sample_window_ms: null, read_only: null}));
    assert.equal(metric('source'), '未知');
    assert.equal(metric('captured_at'), '未知');
    assert.match(text('hardwareHailoMeta'), /採樣視窗 未知.*唯讀旗標 未知/);
  },
  trends_use_actual_times_separate_axes_and_all_gap_boundaries() {
    const point = (seconds, nnc, temp) => historySample(seconds, [device({nnc_utilization_percent: nnc, temperature_c: temp})]);
    const items = [point(0, 0, 40), point(60, 20, 42), point(120, null, 43), point(180, 30, null),
      historySample(240, [device({device_id: otherId})]), {...snapshot(null), captured_at: stamp(301)},
      point(360, 40, 46), point(510, 50, 48), point(661, 60, 49), point(721, null, 50), point(781, 70, 51),
      {...point(810, 90, 55), hailo: hailo({captured_at: null})}, point(840, 80, 52)];
    history(items);
    assert.equal(doc.querySelectorAll('#hardwareHailoTrends > details').length, 2);
    const nnc = chart('nnc_utilization_percent'), temp = chart('temperature_c');
    const commands = node => node.querySelector('path').getAttribute('d').match(/[ML]/g).join('');
    assert.equal(commands(nnc), 'MLMMLMMM');
    assert.equal(commands(temp), 'MLLMLMLLM');
    assert.equal(nnc.querySelectorAll('circle').length, 8);
    assert.equal(temp.querySelectorAll('circle').length, 9);
    assert.equal(nnc.querySelector('circle').dataset.value, '0');
    assert.equal(nnc.querySelector('circle').dataset.capturedAt, stamp(0));
    assert.notEqual(nnc.querySelector('circle').dataset.capturedAt, items[0].captured_at);
    assert.equal(nnc.querySelector('.chart-axis-label').textContent, '100');
    assert.equal(temp.querySelector('.chart-axis-label').textContent, '52');
    assert.match(nnc.getAttribute('aria-label'), /NNC.*%/);
    assert.match(temp.getAttribute('aria-label'), /晶片溫度.*°C/);
    const rows = trend().querySelectorAll('tbody tr');
    assert.equal(rows.length, items.length);
    assert.match(rows[0].cells[0].textContent, /12:00:01/);
    assert.match(rows[0].cells[1].textContent, /12:00:00/);
    assert.equal(rows[5].cells[1].textContent, '未知');
    assert.equal(rows[5].cells[2].textContent, '未知');
    // x positions reflect elapsed 840 seconds, not evenly spaced sample indexes.
    const points = nnc.querySelectorAll('circle');
    assert.ok(Math.abs(Number(points[1].getAttribute('cx')) - (48 + 60 / 840 * 256)) < 0.01);
    assert.equal(chart('nnc_utilization_percent', otherId).querySelectorAll('circle').length, 1);
    history([point(60, 1, 40), point(60, 2, 41), point(0, 3, 42)]);
    assert.equal(commands(chart('nnc_utilization_percent')), 'MMM'); // Duplicate/reversed times never join.
  },
  history_partial_failure_empty_legacy_and_null_after_good() {
    const items = [historySample(0), historySample(60)];
    history(items, 'partial');
    assert.match(text('hardwareHailoHistoryMeta'), /部分資料/);
    apply(hailo(), {status: 'stale'}, 503);
    assert.match(text('hardwareHailoHistoryMeta'), /資料已過期/);
    win.applyHardwareHistoryResult({response: null, payload: null});
    assert.match(text('hardwareHailoHistoryMeta'), /保留上次歷史資料/);
    assert.equal(chart('nnc_utilization_percent').querySelectorAll('circle').length, 2);
    apply(null);
    assert.equal(devices().length, 0);
    assert.ok(trend()); // Explicitly historic, not resurrected current measurements.
    assert.match(trend().textContent, /歷史採樣（非目前狀態）/);
    history([]);
    assert.equal(doc.querySelectorAll('#hardwareHailoTrends svg').length, 0);
    assert.match(text('hardwareHailoTrends'), /沒有 Hailo 裝置採樣/);
    history([snapshot(undefined), snapshot(null)]);
    assert.equal(doc.querySelectorAll('#hardwareHailoTrends svg').length, 0);
    history([historySample(0, [device({nnc_utilization_percent: null, temperature_c: null})])]);
    assert.equal(trend().querySelectorAll('svg').length, 0);
    assert.match(trend().textContent, /沒有可繪製的讀值/);
  },
  refresh_preserves_keyed_disclosures_focus_and_table_scroll() {
    const values = [device(), device({device_id: otherId})];
    apply(hailo({devices: values}));
    history([historySample(0, values), historySample(60, values)]);
    const rootHistory = doc.getElementById('hardwareHailoHistory');
    const rootErrors = doc.getElementById('hardwareHailoErrors');
    rootHistory.open = true; rootErrors.open = true;
    card().open = true; card().querySelector('details').open = true;
    trend().open = true; trend().querySelector('.hailo-samples').open = true;
    const table = trend().querySelector('.table-wrap');
    table.scrollLeft = 32; table.scrollTop = 42;
    card().querySelector('summary').focus();
    apply(hailo({devices: [...values].reverse()}));
    history([historySample(0, [...values].reverse()), historySample(60, values)]);
    assert.equal(card().open, true);
    assert.equal(card(otherId).open, false);
    assert.equal(card().querySelector('details').open, true);
    assert.equal(doc.activeElement, card().querySelector('summary'));
    assert.equal(trend().open, true);
    assert.equal(trend().querySelector('.hailo-samples').open, true);
    assert.equal(trend().querySelector('.table-wrap').scrollLeft, 32);
    assert.equal(trend().querySelector('.table-wrap').scrollTop, 42);
    assert.equal(rootHistory.open, true); assert.equal(rootErrors.open, true);
    card().open = false; apply(); assert.equal(card().open, false);
    card().open = true; apply(null); apply(); assert.equal(card().open, true);
  },
  backend_alerts_only_no_utilization_temperature_or_voltage_thresholds() {
    apply(hailo({devices: [device({nnc_utilization_percent: 100, temperature_c: 150, voltage_mv: 0})]}));
    assert.equal(text('hardwareAlertCount'), '0');
    assert.equal(text('hardwareOverallStatus'), '正常');
    assert.equal(card().querySelector('.inventory-section-status').dataset.state, 'ok');
    const data = snapshot(hailo());
    data.alerts = {hailo_temperature: {severity: 'critical', message: '後端回報的 Hailo 告警'}};
    data.thresholds = {hailo_temperature_c: {warning: 80, critical: 95}};
    apply(hailo(), {status: 'critical', data});
    assert.equal(text('hardwareOverallStatus'), '嚴重告警');
    assert.match(text('hardwareAlertList'), /後端回報的 Hailo 告警/);
    assert.match(text('hardwareThresholdList'), /80.*95/s);
  },
  async manual_refresh_uses_existing_three_gets_and_cancels_polling() {
    apply(); card().open = true;
    win.fetch = async (path, options) => {
      requests.push({path, method: options.method});
      assert.equal(options.method, 'GET');
      assert.equal(options.cache, 'no-store');
      assert.ok(options.signal);
      return {ok: true, status: 200, json: async () => path.endsWith('/status')
        ? envelope(hailo({devices: [device({nnc_utilization_percent: 9.8})]}))
        : {status: 'ok', items: [], meta: {count: 0}}};
    };
    win.startHardwarePolling();
    await new Promise(resolve => setImmediate(resolve));
    const start = requests.length;
    doc.getElementById('hardwareRefreshButton').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(metric('nnc_utilization_percent'), '9.8%');
    assert.equal(card().open, true);
    assert.deepEqual(requests.slice(start).map(row => row.path).sort(),
      [apiRoot + 'status', apiRoot + 'history?limit=60', apiRoot + 'events?limit=50'].sort());
    const pendingSignals = [];
    win.fetch = (path, options) => new Promise((resolve, reject) => {
      requests.push({path, method: options.method});
      pendingSignals.push(options.signal);
      options.signal.addEventListener('abort', () => reject(new win.DOMException('Page left', 'AbortError')), {once: true});
    });
    doc.getElementById('hardwareRefreshButton').click();
    assert.equal(pendingSignals.length, 3);
    win.dispatchEvent(new win.Event('pagehide'));
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(pendingSignals.every(signal => signal.aborted));
    const stoppedCount = requests.length;
    await win.refreshHardwareMonitor();
    assert.equal(requests.length, stoppedCount);
    assert.ok(requests.every(row => row.method === 'GET' && row.path.startsWith(apiRoot)));
    assert.deepEqual(errors, []);
  },
};
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  win.stopHardwarePolling();
  await new Promise(resolve => setImmediate(resolve));
  for (const [name, run] of Object.entries(cases)) {
    try {
      apply(); history([]);
      await run();
      results[name] = {passed: true};
    } catch (error) { results[name] = {passed: false, error: error.stack}; }
  }
  console.log(JSON.stringify(results));
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => win.close());
"""


@pytest.fixture(scope="module")
def hailo_ui_replays():
    """One JSDOM startup for all focused cases; no broad suites or live API."""
    result = subprocess.run(
        ["node", "-e", DOM_REPLAY], cwd=ROOT, capture_output=True,
        text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", [
    "loading_placement_and_readonly_boundary",
    "values_units_source_and_actual_taipei_time",
    "zero_null_missing_and_new_null_replace_previous_values",
    "legacy_null_empty_and_missing_device_list_are_distinct",
    "partial_unavailable_multiple_devices_and_errors",
    "empty_device_read_failure_never_claims_absence",
    "stale_disconnect_unknown_and_recovery_keep_truthful_values",
    "hailo_age_and_staleness_are_independent_of_host_capture",
    "scout_time_anchor_survives_mac_clock_skew_and_future_samples_fail_unknown",
    "untrusted_ids_sources_architectures_and_errors_are_plain_text",
    "trends_use_actual_times_separate_axes_and_all_gap_boundaries",
    "history_partial_failure_empty_legacy_and_null_after_good",
    "refresh_preserves_keyed_disclosures_focus_and_table_scroll",
    "backend_alerts_only_no_utilization_temperature_or_voltage_thresholds",
    "manual_refresh_uses_existing_three_gets_and_cancels_polling",
])
def test_hailo_ui_replay(hailo_ui_replays, case):
    assert hailo_ui_replays[case]["passed"], hailo_ui_replays[case].get("error")


def test_hailo_ui_keyboard_and_320px_layout_in_browser():
    """Small isolated browser replay. No server, real API, or screenshot writes."""
    script = FIXTURES + r"""
console.error('Hailo browser: loading Playwright');
const {chromium} = require('playwright');
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async () => {
  console.error('Hailo browser: launching isolated Chrome');
  const browser = await chromium.launch({headless: true,
    ...(fs.existsSync(chrome) ? {executablePath: chrome} : {})});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(String(error)));
    const current = hailo({devices: [device(), device({device_id: otherId})]});
    const items = [historySample(0, current.devices), historySample(60, current.devices)];
    await page.route('**/*', async route => {
      const req = route.request(), path = new URL(req.url()).pathname;
      assert.equal(req.method(), 'GET');
      if (req.isNavigationRequest()) return route.fulfill({contentType: 'text/html', body: html});
      requests.push(path);
      assert.ok(path.startsWith(apiRoot), 'unexpected network request: ' + path);
      const payload = path.endsWith('/status') ? envelope(current)
        : {status: 'ok', items: path.endsWith('/history') ? items : [], meta: {count: 2}};
      await route.fulfill({contentType: 'application/json', body: JSON.stringify(payload)});
    });
    page.setDefaultTimeout(10000);
    console.error('Hailo browser: opening fixture document');
    await page.goto('http://scout-monitor.test/admin/dashboard/scout-monitor');
    await page.locator('#hardwareHailoDevices > details').first().waitFor();
    const summary = page.locator('#hardwareHailoDevices > details > summary').first();
    await summary.focus(); await summary.press('Enter');
    assert.equal(await page.locator('#hardwareHailoDevices > details').first().evaluate(el => el.open), true);
    await page.locator('#hardwareHailoHistory > summary').focus();
    await page.locator('#hardwareHailoHistory > summary').press('Space');
    const trend = page.locator('#hardwareHailoTrends > details').first();
    await trend.locator(':scope > summary').focus(); await trend.locator(':scope > summary').press('Enter');
    await trend.locator('.hailo-samples > summary').focus(); await trend.locator('.hailo-samples > summary').press('Enter');
    assert.equal(await trend.locator('.hailo-samples').evaluate(el => el.open), true);
    // Open every returned device before measuring, including nested charts;
    // an open outer history disclosure does not make a closed child visible.
    for (const details of await page.locator('#hardwareHailoDevices > details, #hardwareHailoTrends > details').all()) {
      if (!await details.evaluate(el => el.open)) {
        await details.locator(':scope > summary').focus();
        await details.locator(':scope > summary').press('Enter');
      }
    }
    for (const width of [1280, 320]) {
      console.error('Hailo browser: checking viewport ' + width);
      await page.setViewportSize({width, height: 900});
      await trend.scrollIntoViewIfNeeded();
      const layout = await page.evaluate(() => {
        const panel = document.getElementById('hardwareHailoPanel');
        return {scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
          charts: [...panel.querySelectorAll('details[open] .hailo-chart svg')].map(svg => {
            const rect = svg.getBoundingClientRect(); return {left: rect.left, right: rect.right, width: rect.width};
          })};
      });
      assert.ok(layout.scroll <= layout.client, JSON.stringify({width, ...layout}));
      assert.ok(layout.charts.length >= 2);
      assert.ok(layout.charts.every(box => box.width > 0 && box.left >= 0 && box.right <= width));
    }
    const before = requests.length;
    await page.locator('#hardwareRefreshButton').focus(); await page.locator('#hardwareRefreshButton').press('Enter');
    await page.waitForFunction(() => !document.getElementById('hardwareRefreshButton').disabled);
    assert.equal(requests.length, before + 3);
    assert.equal(await page.locator('#hardwareHailoDevices > details').first().evaluate(el => el.open), true);
    assert.equal(await page.locator('#hardwareHailoHistory').evaluate(el => el.open), true);
    assert.equal(await trend.evaluate(el => el.open), true);
    assert.equal(await trend.locator('.hailo-samples').evaluate(el => el.open), true);
    assert.deepEqual(errors, []);
    console.error('Hailo browser: keyboard, refresh and both viewports passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    try:
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired as error:
        progress = error.stderr or b"No browser stage was reached."
        if isinstance(progress, bytes):
            progress = progress.decode("utf-8", errors="replace")
        pytest.fail(f"Hailo browser exceeded 60s (not a pass):\n{progress}")
    assert result.returncode == 0, result.stderr
