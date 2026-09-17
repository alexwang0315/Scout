"""Production standalone Hailo DOM replays; no server, SSH, .env or hardware.

One JSDOM process exercises the actual imported HTML and app.js. These checks
are construction evidence, not a substitute for main's deployed browser smoke.
"""
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "loading_and_first_read", "zero_is_a_real_reading", "null_and_missing_are_unknown",
    "partial_preserves_readings_and_errors", "unavailable_is_not_health",
    "legacy_null_and_missing_clear_old_values", "new_null_metrics_clear_old_values",
    "null_snapshot_clears_devices", "empty_devices_have_honest_read_states",
    "every_device_id_is_separate", "unsafe_strings_are_text",
    "http_503_stale_retains_marked_old_values", "freshness_state_overrides_ok",
    "clock_marks_expired_readings", "hailo_timestamp_can_be_expired", "hailo_age_uses_own_query_timestamp",
    "own_missing_invalid_timestamps_are_not_current", "unknown_freshness_is_not_current",
    "missing_freshness_time_is_not_current", "scout_age_ignores_mac_clock_skew_and_jumps",
    "freshness_offset_without_server_time", "query_end_one_second_after_snapshot_is_valid",
    "timezone_less_hailo_history_timestamps_break",
    "disconnect_and_automatic_poll_recovery", "initial_disconnect_and_manual_recovery",
    "disclosures_survive_refresh_and_reordering", "disclosures_survive_legacy_sample", "actual_hailo_timestamps_space_trends",
    "missing_null_invalid_and_large_gaps_break_trends", "history_all_ids_and_partial",
    "history_empty_unavailable_and_transport_recovery", "pagehide_aborts_and_stops_polling",
    "existing_resources_inventory_alerts_events_preserved",
)

REPLAY = r"""
const assert = require('node:assert/strict'), fs = require('node:fs');
const {JSDOM, VirtualConsole} = require('jsdom');
const html = fs.readFileSync('docs/admin/hardware-monitor/index.html', 'utf8');
const source = fs.readFileSync('docs/admin/hardware-monitor/app.js', 'utf8');
const NOW = Date.parse('2026-09-15T02:00:00Z'), GIB = 1024 ** 3;
const stamp = offset => new Date(NOW + offset * 1000).toISOString();
const device = (overrides = {}) => ({device_id: 'pci/0001:03:00.0', architecture: 'HAILO10H',
  status: 'ok', nnc_utilization_percent: 12.5, cpu_utilization_percent: 0.2,
  ram_utilization_percent: 7.1, ram_used_bytes: GIB / 2, ram_total_bytes: GIB * 7,
  temperature_c: 46.2, voltage_mv: 802, errors: [], ...overrides});
const hailo = (overrides = {}) => ({captured_at: stamp(0), status: 'ok', source: 'hailortcli.monitor',
  sample_window_ms: 1000, read_only: true, devices: [device()], errors: [], ...overrides});
const snapshot = (overrides = {}) => ({captured_at: stamp(0), status: 'ok',
  power: {status: 'ok', ups_status: 'ok', battery_percent: 73, battery_power_w: 3,
    flow: 'charging', ext5v_v: 5.1}, memory: {used_percent: 25, used_bytes: 2 * GIB,
    total_bytes: 8 * GIB, available_bytes: 6 * GIB, swap_used_bytes: 0},
  disks: [{mount: '/', used_percent: 20, available_bytes: 80 * GIB, total_bytes: 100 * GIB}],
  sensors: [{name: 'cpu_thermal', source: '/sys/pi-cpu', temperature_c: 52}],
  cpu_used_percent: 11, load_average: [1, 2, 3], uptime_seconds: 3600, alerts: {},
  inventory: null, hailo: hailo(), ...overrides});
const envelope = (overrides = {}) => ({schema_version: 'scout.hardware-monitor.api.v1',
  status: 'ok', server_time: stamp(0), summary: '採樣可讀', read_only: true, data: snapshot(),
  freshness: {state: 'fresh', captured_at: stamp(0), age_seconds: 0,
    sample_interval_seconds: 60, stale_after_seconds: 150}, ...overrides});
const listing = (items = [], status = 'ok') => ({schema_version: 'scout.hardware-monitor.api.v1',
  status, summary: '既有紀錄', items});
const windows = [], jsdomErrors = [];
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
async function monitor(mode = 'ok') {
  const errors = [], virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => { errors.push(String(error)); jsdomErrors.push(String(error)); });
  const win = new JSDOM(html, {url: 'http://scout.test/monitor', runScripts: 'outside-only',
    virtualConsole}).window;
  windows.push(win);
  const net = {mode, status: envelope(), history: listing(), events: listing(), http: 200};
  const requests = [], timers = new Map(), clock = {now: NOW, elapsed: 0}; let timer = 0;
  win.Date.now = () => clock.now;
  win.performance.now = () => clock.elapsed;
  win.setInterval = (fn, ms) => { const id = ++timer; timers.set(id, {fn, ms}); return id; };
  win.clearInterval = id => timers.delete(id);
  win.fetch = async (path, options) => {
    assert.match(path, /^\/api\/v1\/hardware-monitor\/(status|history\?limit=60|events\?limit=50)$/);
    assert.equal(options.method || 'GET', 'GET'); assert.equal(options.cache, 'no-store');
    assert.ok(options.signal);
    requests.push({path, options});
    if (net.mode === 'offline') throw Error('Synthetic disconnect: network is disabled');
    if (net.mode === 'pending') return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new win.DOMException('Cancelled', 'AbortError')), {once: true});
    });
    const kind = path.split('/').at(-1).split('?')[0];
    if (net.mode === 'history-offline' && kind === 'history') throw Error('Synthetic history failure');
    return {ok: kind !== 'status' || net.http === 200, status: kind === 'status' ? net.http : 200,
      json: async () => structuredClone(net[kind])};
  };
  // Strict eval keeps top-level declarations scoped. Expose references to the
  // unmodified production handlers, rather than replacing their implementation.
  win.eval(source + '\nwindow.refresh = refresh; window.statusClock = statusClock;');
  await flush();
  const doc = win.document, $ = id => doc.getElementById(id);
  return {win, doc, $, net, timers, requests, errors, clock,
    panel: () => $('hailo-panel').textContent,
    value: (name, index = 0) => doc.querySelectorAll(`#hailo-devices [data-hailo-metric="${name}"]`)[index]?.textContent,
    apply: async (next, http = 200) => { net.mode = 'ok'; net.status = next; net.http = http; await win.refresh(); },
    history: async body => { net.mode = 'ok'; net.history = body; await win.refresh(); }};
}
const cases = {};
cases.loading_and_first_read = async () => {
  const ui = await monitor('pending');
  assert.equal(ui.$('hailo-panel').getAttribute('aria-busy'), 'true');
  assert.equal(ui.$('hailo-state').textContent, '正在讀取');
  await ui.apply(envelope());
  assert.equal(ui.$('hailo-panel').getAttribute('aria-busy'), 'false');
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
  assert.equal(ui.value('ram_used_bytes'), '0.50 GiB');
  assert.equal(ui.value('ram_total_bytes'), '7.00 GiB');
  assert.equal(ui.value('voltage_mv'), '802 mV');
  assert.equal(ui.doc.querySelector('[data-hailo-device]').dataset.hailoDevice, 'pci/0001:03:00.0');
  assert.match(ui.$('hailo-meta').textContent, /hailortcli\.monitor/);
  assert.match(ui.$('hailo-meta').textContent, /觀測窗口 1\.0 秒/);
  assert.match(ui.$('hailo-meta').textContent, /Asia\/Taipei/);
  assert.match(ui.panel(), /每 60 秒採樣/);
  assert.match(ui.panel(), /晶片電壓 mV 不是功耗 W/);
  assert.doesNotMatch(ui.$('metrics').textContent, /Hailo|HAILO/);
};
cases.zero_is_a_real_reading = async () => {
  const ui = await monitor(), zeros = device();
  for (const key of Object.keys(zeros).filter(key => /percent$|bytes$|_c$|_mv$/.test(key))) zeros[key] = 0;
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices: [zeros]})})}));
  for (const field of ['nnc_utilization_percent', 'cpu_utilization_percent', 'ram_utilization_percent']) assert.equal(ui.value(field), '0.0 %');
  assert.equal(ui.value('ram_used_bytes'), '0.00 GiB');
  assert.equal(ui.value('ram_total_bytes'), '0.00 GiB');
  assert.equal(ui.value('temperature_c'), '0.0 °C');
  assert.equal(ui.value('voltage_mv'), '0 mV');
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
  assert.equal(ui.doc.querySelectorAll('#hailo-panel .critical').length, 0);
};
cases.null_and_missing_are_unknown = async () => {
  const ui = await monitor();
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices: [{device_id: 'missing', status: 'partial',
    nnc_utilization_percent: null, cpu_utilization_percent: null, ram_total_bytes: null}]})})}));
  const readings = [...ui.doc.querySelectorAll('#hailo-devices dd')];
  assert.equal(readings.length, 7); assert.ok(readings.every(node => node.textContent === '未知'));
};
cases.partial_preserves_readings_and_errors = async () => {
  const ui = await monitor();
  await ui.apply(envelope({data: snapshot({hailo: hailo({status: 'partial', errors: ['部分採樣失敗'],
    devices: [device({status: 'partial', temperature_c: null, errors: ['溫度不可讀']})]})})}));
  assert.equal(ui.$('hailo-state').textContent, '部分可讀');
  assert.equal(ui.value('nnc_utilization_percent'), '12.5 %');
  assert.equal(ui.value('temperature_c'), '未知');
  assert.match(ui.panel(), /部分採樣失敗/); assert.match(ui.panel(), /溫度不可讀/);
  assert.equal(ui.$('status').textContent, '正常'); // Hailo read state must not invent global health.
};
cases.unavailable_is_not_health = async () => {
  const ui = await monitor();
  await ui.apply(envelope({data: snapshot({hailo: hailo({status: 'unavailable', errors: ['無法查詢'],
    devices: [device({status: 'unavailable', nnc_utilization_percent: null})]})})}));
  assert.equal(ui.$('hailo-state').textContent, '無法讀取');
  assert.equal(ui.doc.querySelector('.hailo-read-status').textContent, '無法讀取');
  assert.equal(ui.value('nnc_utilization_percent'), '未知');
};
cases.legacy_null_and_missing_clear_old_values = async () => {
  const ui = await monitor();
  for (const legacy of [snapshot({hailo: null}), (() => { const s = snapshot(); delete s.hailo; return s; })()]) {
    await ui.apply(envelope()); assert.equal(ui.value('voltage_mv'), '802 mV');
    await ui.apply(envelope({data: legacy}));
    assert.equal(ui.doc.querySelectorAll('.hailo-device').length, 0);
    assert.equal(ui.$('hailo-state').textContent, '等待更新');
    assert.match(ui.$('hailo-devices').textContent, /舊版採樣.*等待/);
    assert.doesNotMatch(ui.$('hailo-devices').textContent, /802|46\.2/);
  }
};
cases.new_null_metrics_clear_old_values = async () => {
  const ui = await monitor();
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices: [device({voltage_mv: null, temperature_c: null})]})})}));
  assert.equal(ui.value('voltage_mv'), '未知'); assert.equal(ui.value('temperature_c'), '未知');
  assert.doesNotMatch(ui.$('hailo-devices').textContent, /802|46\.2/);
};
cases.null_snapshot_clears_devices = async () => {
  const ui = await monitor();
  await ui.apply(envelope({status: 'unavailable', data: null,
    freshness: {state: 'missing', captured_at: null, age_seconds: null}}), 503);
  assert.equal(ui.doc.querySelectorAll('.hailo-device').length, 0);
  assert.equal(ui.$('hailo-state').textContent, '資料不可用');
  assert.match(ui.$('hailo-devices').textContent, /沒有可顯示/);
};
cases.empty_devices_have_honest_read_states = async () => {
  const ui = await monitor();
  for (const [status, label, message] of [['ok', '已讀取', /沒有偵測到/],
    ['partial', '部分可讀', /部分資料不可讀/], ['unavailable', '無法讀取', /無法確認裝置清單/]]) {
    await ui.apply(envelope({data: snapshot({hailo: hailo({status, devices: []})})}));
    assert.equal(ui.$('hailo-state').textContent, label);
    assert.match(ui.$('hailo-devices').textContent, message);
    assert.equal(ui.doc.querySelectorAll('.hailo-device').length, 0);
  }
};
cases.every_device_id_is_separate = async () => {
  const ui = await monitor(), devices = ['pci/0001:03:00.0', 'pci/0001:04:00.0', 'custom-device-3']
    .map((device_id, index) => device({device_id, nnc_utilization_percent: index * 10, architecture: `架構 ${index}`}));
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices})})}));
  assert.equal(ui.doc.querySelectorAll('.hailo-device').length, 3);
  devices.forEach((d, index) => {
    assert.equal(ui.doc.querySelectorAll('.hailo-device')[index].dataset.deviceId, d.device_id);
    assert.equal(ui.value('nnc_utilization_percent', index), `${index * 10}.0 %`);
  });
};
cases.unsafe_strings_are_text = async () => {
  const ui = await monitor(), attack = '<img src=x onerror="window.hailoInjected=1"><script>window.hailoInjected=1</script>';
  const unsafe = device({device_id: attack, architecture: attack, errors: [attack], status: attack});
  const payload = hailo({source: attack, devices: [unsafe], errors: [attack]});
  await ui.apply(envelope({data: snapshot({hailo: payload})}));
  await ui.history(listing([snapshot({hailo: payload}), snapshot({hailo: {...payload, captured_at: stamp(60)}})]));
  assert.ok(ui.$('hailo-meta').textContent.includes(attack));
  assert.ok(ui.$('hailo-devices').textContent.includes(attack));
  assert.ok(ui.$('hailo-errors').textContent.includes(attack));
  assert.ok(ui.$('hailo-trends').textContent.includes(attack));
  assert.equal(ui.doc.querySelectorAll('#hailo-panel img, #hailo-panel script').length, 0);
  assert.equal(ui.win.hailoInjected, undefined);
  assert.equal(ui.doc.querySelector('.hailo-read-status').textContent, '未知');
};
cases.http_503_stale_retains_marked_old_values = async () => {
  const ui = await monitor(), stale = envelope({status: 'stale'});
  stale.data.status = 'ok'; stale.data.hailo.status = 'ok';
  await ui.apply(stale, 503);
  assert.equal(ui.value('voltage_mv'), '802 mV');
  assert.equal(ui.$('hailo-state').textContent, '資料已過期');
  assert.equal(ui.$('hailo-freshness').hidden, false);
  assert.match(ui.$('hailo-freshness').textContent, /最後紀錄.*不能代表目前/);
  assert.equal(ui.doc.querySelector('.hailo-read-status').textContent, '最後紀錄 · 已讀取');
  assert.ok(ui.$('hailo-panel').classList.contains('hailo-old'));
};
cases.freshness_state_overrides_ok = async () => {
  const ui = await monitor(), body = envelope();
  body.freshness.state = 'stale'; body.freshness.age_seconds = null;
  await ui.apply(body); assert.equal(ui.$('hailo-state').textContent, '資料已過期');
  for (const state of ['invalid', 'unreadable', 'missing']) {
    body.freshness.state = state; await ui.apply(body);
    assert.equal(ui.$('hailo-state').textContent, '資料時間未知／無效');
    assert.equal(ui.value('voltage_mv'), '802 mV');
  }
};
cases.clock_marks_expired_readings = async () => {
  const ui = await monitor(); ui.clock.now = NOW + 150000; ui.clock.elapsed = 150000; ui.win.statusClock();
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
  ui.clock.now++; ui.clock.elapsed++; ui.win.statusClock();
  assert.equal(ui.$('hailo-state').textContent, '資料已過期');
  assert.equal(ui.value('nnc_utilization_percent'), '12.5 %');
};
cases.hailo_timestamp_can_be_expired = async () => {
  const ui = await monitor();
  await ui.apply(envelope({data: snapshot({hailo: hailo({captured_at: stamp(-151)})})}));
  assert.equal(ui.$('hailo-state').textContent, '資料已過期');
};
cases.hailo_age_uses_own_query_timestamp = async () => {
  const ui = await monitor(), body = envelope();
  body.freshness.age_seconds = 11; body.freshness.captured_at = stamp(-11);
  body.data.hailo.captured_at = stamp(-10);
  await ui.apply(body);
  assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：10 秒');
  assert.match(ui.$('hailo-meta').textContent, /09:59:50/);
  ui.clock.now += 3000; ui.clock.elapsed += 3000; ui.win.statusClock();
  assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：13 秒');
  body.data.hailo.captured_at = null; await ui.apply(body);
  assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：未知');
  assert.match(ui.$('hailo-meta').textContent, /最後採樣 未知/);
  assert.equal(ui.$('hailo-state').textContent, '資料時間未知／無效');
};
cases.own_missing_invalid_timestamps_are_not_current = async () => {
  const ui = await monitor();
  for (const time of [null, undefined, '', 'not-a-time', '2026-09-15T02:00:00', 0]) {
    const body = envelope(); body.data.hailo.captured_at = time;
    await ui.apply(body);
    assert.equal(ui.$('hailo-state').textContent, '資料時間未知／無效');
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：未知');
    assert.match(ui.$('hailo-meta').textContent, /最後採樣 未知/);
    assert.equal(ui.$('hailo-freshness').hidden, false);
    assert.match(ui.$('hailo-freshness').textContent, /不能代表目前運作/);
    assert.equal(ui.value('voltage_mv'), '802 mV');
    assert.equal(ui.doc.querySelector('.hailo-read-status').textContent, '最後紀錄 · 已讀取');
  }
  await ui.apply(envelope());
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
  assert.equal(ui.$('hailo-freshness').hidden, true);
};
cases.unknown_freshness_is_not_current = async () => {
  const ui = await monitor();
  for (const freshness of [undefined, null, {}, ...[null, 'unknown', 'missing', 'invalid', 'unreadable']
    .map(state => ({...envelope().freshness, state}))]) {
    await ui.apply(envelope({freshness}));
    assert.equal(ui.$('hailo-state').textContent, '資料時間未知／無效');
    assert.equal(ui.$('hailo-freshness').hidden, false);
    assert.equal(ui.value('temperature_c'), '46.2 °C');
  }
};
cases.missing_freshness_time_is_not_current = async () => {
  const ui = await monitor();
  for (const changes of [{age_seconds: null}, {age_seconds: undefined}, {age_seconds: -1},
    {captured_at: null}, {captured_at: ''}, {captured_at: 'invalid'}, {captured_at: '2026-09-15T02:00:00'}]) {
    const body = envelope(); Object.assign(body.freshness, changes);
    await ui.apply(body);
    assert.equal(ui.$('hailo-state').textContent, '資料時間未知／無效');
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：未知');
  }
};
cases.scout_age_ignores_mac_clock_skew_and_jumps = async () => {
  const ui = await monitor(), body = envelope();
  body.freshness.captured_at = stamp(-11); body.freshness.age_seconds = 11;
  body.data.captured_at = stamp(-11); body.data.hailo.captured_at = stamp(-10);
  for (const skew of [-600000, 600000]) {
    ui.clock.now = NOW + skew; await ui.apply(body);
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：10 秒');
    assert.equal(ui.$('hailo-state').textContent, '已讀取');
    // The browser wall clock can jump after the response. Elapsed time is monotonic.
    ui.clock.now -= 900000; ui.clock.elapsed += 5000; ui.win.statusClock();
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：15 秒');
    assert.equal(ui.$('hailo-state').textContent, '已讀取');
  }
};
cases.freshness_offset_without_server_time = async () => {
  const ui = await monitor(); ui.clock.now = NOW + 600000;
  for (const server_time of [null, undefined, '', 'invalid']) {
    const body = envelope({server_time});
    body.freshness.captured_at = stamp(-11); body.freshness.age_seconds = 11;
    body.data.captured_at = stamp(-11); body.data.hailo.captured_at = stamp(-10);
    await ui.apply(body);
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：10 秒');
    assert.equal(ui.$('hailo-state').textContent, '已讀取');
  }
};
cases.query_end_one_second_after_snapshot_is_valid = async () => {
  const ui = await monitor();
  for (const server_time of [stamp(0), undefined]) {
    const body = envelope({server_time}); body.freshness.captured_at = stamp(-1);
    body.freshness.age_seconds = 1; body.data.captured_at = stamp(-1);
    body.data.hailo.captured_at = stamp(0);
    await ui.apply(body);
    assert.equal(ui.$('hailo-age').textContent, 'Hailo 資料年齡：0 秒');
    assert.equal(ui.$('hailo-state').textContent, '已讀取');
    assert.equal(ui.$('hailo-freshness').hidden, true);
  }
};
cases.disconnect_and_automatic_poll_recovery = async () => {
  const ui = await monitor();
  ui.net.mode = 'offline'; await ui.win.refresh();
  assert.equal(ui.$('hailo-state').textContent, '連線失敗');
  assert.equal(ui.value('voltage_mv'), '802 mV');
  assert.match(ui.$('hailo-freshness').textContent, /最後取得.*每 60 秒自動重試/);
  ui.net.mode = 'ok'; ui.net.status.data.hailo.devices[0].nnc_utilization_percent = 25;
  const poll = [...ui.timers.values()].find(timer => timer.ms === 60000); assert.ok(poll);
  await poll.fn();
  assert.equal(ui.value('nnc_utilization_percent'), '25.0 %');
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
  assert.equal(ui.$('hailo-freshness').hidden, true);
  assert.equal(ui.$('hailo-panel').classList.contains('hailo-old'), false);
};
cases.initial_disconnect_and_manual_recovery = async () => {
  const ui = await monitor('offline');
  assert.equal(ui.$('hailo-state').textContent, '連線失敗');
  assert.equal(ui.$('hailo-panel').getAttribute('aria-busy'), 'false');
  assert.match(ui.$('hailo-devices').textContent, /尚未取得.*等待連線恢復/);
  assert.equal(ui.$('refresh').disabled, false);
  ui.net.mode = 'ok'; ui.$('refresh').click(); await flush();
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
};
cases.disclosures_survive_refresh_and_reordering = async () => {
  const ui = await monitor(), a = device(), b = device({device_id: 'second'});
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices: [a, b]})})}));
  ui.doc.querySelectorAll('.hailo-device')[0].open = false;
  ui.doc.querySelectorAll('.hailo-device')[1].open = true;
  ui.$('hailo-history-details').open = true;
  ui.doc.querySelectorAll('.hailo-device')[0].firstElementChild.focus();
  await ui.apply(envelope({data: snapshot({hailo: hailo({devices: [b, {...a, temperature_c: 47}]})})}));
  const nodes = [...ui.doc.querySelectorAll('.hailo-device')];
  assert.deepEqual(nodes.map(node => [node.dataset.deviceId, node.open]), [['second', true], [a.device_id, false]]);
  assert.equal(ui.$('hailo-history-details').open, true);
  assert.ok(nodes.every(node => node.firstElementChild.tagName === 'SUMMARY'));
  assert.equal(ui.doc.activeElement, nodes[1].firstElementChild);
};
cases.disclosures_survive_legacy_sample = async () => {
  const ui = await monitor(); ui.doc.querySelector('.hailo-device').open = false;
  await ui.apply(envelope({data: snapshot({hailo: null})}));
  assert.equal(ui.doc.querySelector('.hailo-device'), null);
  await ui.apply(envelope()); assert.equal(ui.doc.querySelector('.hailo-device').open, false);
};
const historyItem = (offset, value = 10, overrides = {}) => snapshot({
  captured_at: stamp(offset + 20000), // Snapshot time is NOT the Hailo measurement time.
  hailo: hailo({captured_at: stamp(offset), devices: [device({nnc_utilization_percent: value})], ...overrides})});
const points = line => line.getAttribute('points').split(' ').map(pair => pair.split(',').map(Number));
cases.timezone_less_hailo_history_timestamps_break = async () => {
  const ui = await monitor();
  await ui.history(listing([historyItem(0), historyItem(60),
    historyItem(90, 30, {captured_at: '2026-09-15T02:01:30'}), historyItem(120), historyItem(180)]));
  const lines = [...ui.doc.querySelectorAll('#hailo-trends [data-metric="nnc_utilization_percent"] polyline')];
  assert.equal(lines.length, 2); assert.ok(lines.every(line => points(line).length === 2));
};
cases.actual_hailo_timestamps_space_trends = async () => {
  const ui = await monitor();
  await ui.history(listing([historyItem(0, 0), historyItem(60, 20), historyItem(180, 40)]));
  const chart = ui.doc.querySelector('#hailo-trends [data-metric="nnc_utilization_percent"]');
  const line = chart.querySelector('polyline'), plotted = points(line);
  assert.equal(plotted.length, 3);
  assert.equal(plotted[0][0], 10); assert.equal(plotted[2][0], 590);
  assert.ok(Math.abs(plotted[1][0] - (10 + 580 / 3)) < 0.0001);
  assert.match(chart.querySelector('svg').getAttribute('aria-label'), /0\.0 至 40\.0%/);
  assert.match(ui.$('hailo-history-state').textContent, /10:00:00.*10:03:00/);
};
cases.missing_null_invalid_and_large_gaps_break_trends = async () => {
  const ui = await monitor();
  const items = [historyItem(0), historyItem(60), historyItem(120, null), historyItem(180), historyItem(240),
    snapshot({hailo: null}), historyItem(360), historyItem(420), historyItem(600), historyItem(660),
    historyItem(720, 20, {captured_at: 'invalid'}), historyItem(780), historyItem(840),
    historyItem(900, 20, {devices: []}), historyItem(960), historyItem(1020)];
  await ui.history(listing(items));
  const lines = [...ui.doc.querySelectorAll('#hailo-trends [data-metric="nnc_utilization_percent"] polyline')];
  assert.equal(lines.length, 6); assert.ok(lines.every(line => points(line).length === 2));
  assert.ok(lines.flatMap(points).flat().every(Number.isFinite));
  // A numeric zero joins adjacent real measurements, but never bridges null.
  await ui.history(listing([historyItem(0, 0), historyItem(60, null), historyItem(120, 0)]));
  const isolated = [...ui.doc.querySelectorAll('#hailo-trends [data-metric="nnc_utilization_percent"] polyline')];
  assert.equal(isolated.length, 2); assert.ok(isolated.every(line => points(line).length === 1));
  assert.equal(ui.doc.querySelectorAll('#hailo-trends [data-metric="nnc_utilization_percent"] circle').length, 2);
};
cases.history_all_ids_and_partial = async () => {
  const ui = await monitor(), a = device(), b = device({device_id: 'historical-only'});
  await ui.history(listing([historyItem(0, 0, {devices: [a, b]}), historyItem(60, 0, {devices: [a, b]})], 'partial'));
  assert.equal(ui.doc.querySelectorAll('#hailo-trends .chart').length, 4);
  assert.match(ui.$('hailo-trends').textContent, /historical-only/);
  assert.match(ui.$('hailo-history-state').textContent, /部分紀錄不可用/);
  assert.equal(ui.$('history').querySelectorAll('.chart').length, 2); // Existing host memory/battery history remains.
};
cases.history_empty_unavailable_and_transport_recovery = async () => {
  const ui = await monitor(), valid = listing([historyItem(0), historyItem(60)]);
  await ui.history(valid); ui.net.mode = 'history-offline'; await ui.win.refresh();
  assert.equal(ui.$('hailo-trends').querySelectorAll('svg').length, 2);
  assert.match(ui.$('hailo-history-state').textContent, /讀取失敗.*上次取得/);
  await ui.history(listing([], 'unavailable'));
  assert.equal(ui.$('hailo-trends').querySelectorAll('svg').length, 0);
  assert.match(ui.$('hailo-history-state').textContent, /不可用/);
  await ui.history(listing([snapshot({hailo: null})]));
  assert.match(ui.$('hailo-history-state').textContent, /尚無 Hailo 歷史採樣/);
  assert.equal(ui.$('hailo-trends').querySelectorAll('svg').length, 0);
  await ui.history(valid);
  assert.equal(ui.$('hailo-trends').querySelectorAll('svg').length, 2);
};
cases.pagehide_aborts_and_stops_polling = async () => {
  const ui = await monitor('pending');
  assert.equal(ui.requests.length, 3);
  ui.win.dispatchEvent(new ui.win.Event('pagehide')); await flush();
  assert.equal(ui.timers.size, 0); assert.ok(ui.requests.every(request => request.options.signal.aborted));
  assert.equal(ui.requests.length, 3);
};
cases.existing_resources_inventory_alerts_events_preserved = async () => {
  const ui = await monitor();
  const data = snapshot({alerts: {ups: {severity: 'warning', message: '既有 UPS 告警'}},
    inventory: {sections: {gpio: {status: 'ok', summary: '控制器', notes: ['僅讀取'], errors: [],
      items: [{id: 'gpiochip0', name: 'GPIO', state: 'present', driver: 'gpio', properties: {line_count: 1},
        lines: [{offset: 0, name: 'pin', direction: 'input', consumer: null, active_low: false, value: null}]}]}}}});
  ui.net.events = listing([{captured_at: stamp(-60), events: ['既有狀態變更']}]);
  await ui.apply(envelope({status: 'warning', data}));
  assert.equal(ui.$('metrics').querySelectorAll('.metric').length, 4);
  assert.match(ui.$('metrics').textContent, /73%.*25\.0%.*20\.0%.*52\.0°C/);
  assert.match(ui.$('alerts').textContent, /既有 UPS 告警/);
  assert.match(ui.$('inventory').textContent, /GPIO.*未採樣/);
  assert.match(ui.$('events').textContent, /既有狀態變更/);
  assert.equal(ui.$('events').querySelector('time').dateTime, stamp(-60));
  assert.equal(ui.$('status').textContent, '警告');
  assert.equal(ui.$('hailo-state').textContent, '已讀取');
};
(async () => {
  const results = {};
  for (const [name, run] of Object.entries(cases)) {
    try { await run(); assert.deepEqual(jsdomErrors, []); results[name] = {ok: true}; }
    catch (error) { results[name] = {ok: false, error: error.stack}; }
    finally { windows.splice(0).forEach(win => win.close()); jsdomErrors.length = 0; }
  }
  console.log(JSON.stringify(results));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


@pytest.fixture(scope="module")
def replays():
    result = subprocess.run(
        ["node", "-e", REPLAY], cwd=ROOT, capture_output=True, text=True,
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    outcomes = json.loads(result.stdout)
    assert set(outcomes) == set(CASES)
    return outcomes


@pytest.mark.parametrize("case_name", CASES)
def test_standalone_hailo_production_render(case_name, replays):
    assert replays[case_name]["ok"], replays[case_name].get("error")
