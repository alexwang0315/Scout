"""DASH-050 contract/production-render replays; never hardware-health evidence.

No server, real .env, device, SSH, or Gateway is used. The monitor document and
functions are the production source, executed in JSDOM with network disabled.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"
MODULE = ROOT / "docs/admin/scout-monitor-power-diagnostic.js"

BOOT = r"""
const assert = require('node:assert/strict'), fs = require('node:fs');
const {JSDOM, VirtualConsole} = require('jsdom');
const api = require('./docs/admin/scout-monitor-power-diagnostic.js');
const windows = [], requests = [];
async function monitor() {
  const html = fs.readFileSync('tools/scout_hardware_monitor.html', 'utf8');
  const win = new JSDOM(html, {url: 'http://127.0.0.1:9099/admin/dashboard/scout-monitor',
    runScripts: 'outside-only', virtualConsole: new VirtualConsole()}).window;
  windows.push(win);
  win.fetch = async (path, options) => {
    requests.push({path, method: options.method});
    assert.equal(options.method, 'GET');
    throw new Error('Synthetic test: network disabled');
  };
  for (const script of win.document.querySelectorAll('script:not([src])')) win.eval(script.textContent);
  // Let JSDOM's initial load/pageshow finish; otherwise pageshow resumes a
  // just-stopped poll and its microtasks can outlive window.close().
  await new Promise(resolve => setImmediate(resolve));
  win.stopHardwarePolling();
  await new Promise(resolve => setImmediate(resolve));
  return {doc: win.document, apply: value => win.applyHardwareStatusResult(value), close: () => win.close()};
}
function render(probe, item) {
  if (item.seed) probe.apply({response: {ok: true, status: 200}, payload: item.seed});
  const httpStatus = item.httpStatus ?? 200;
  probe.apply({response: httpStatus ? {ok: httpStatus === 200, status: httpStatus} : null, payload: item.payload});
  return () => api.verifyRendered(probe.doc, item.payload, httpStatus, item.retainedPower, item.retainedHailo);
}
"""


def node(body: str) -> None:
    script = BOOT + "\n(async () => {\n" + body + r"""
})().catch(error => {console.error(error); process.exitCode = 1;})
  .finally(() => windows.forEach(win => win.close()));
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_contract_supports_new_split_partial_supply_and_legacy_nulls():
    node(r"""
for (const item of api.scenarios().filter(item => item.payload)) api.verifyContract(item.payload);
const legacy = structuredClone(api.scenarios()[0].payload);
delete legacy.data.power.ups_status; delete legacy.data.power.supply_status;
api.verifyContract(legacy);
for (const [field, value] of [['ups_status', 'present'], ['supply_status', 'partial'],
    ['ups_error_code', 'raw_private_error'], ['supply_error_code', 'raw_private_error'], ['status', 'normal']]) {
  const payload = structuredClone(api.scenarios()[0].payload); payload.data.power[field] = value;
  assert.throws(() => api.verifyContract(payload));
}
const inconsistent = structuredClone(api.scenarios()[1].payload);
inconsistent.data.power.status = 'ok';
assert.throws(() => api.verifyContract(inconsistent), /全體可用性/);
""")


def test_real_monitor_render_matrix_keeps_all_split_states_and_recovers():
    node(r"""
const result = api.runRenderScenarios(await monitor());
assert.ok(result.length >= 23);
assert.deepEqual(result.filter(row => row.status !== 'passed'), []);
assert.ok(requests.every(row => row.method === 'GET'
  && row.path.startsWith('/admin/dashboard/scout-monitor/api/v1/hardware-monitor/')));
""")


def test_old_aggregate_gate_is_actually_rejected_and_valid_5v_passes():
    node(r"""
const probe = await monitor(), item = api.scenarios().find(row => row.id === 'ups-communication_error-supply-preserved');
const verify = render(probe, item);
verify();
// Equivalent replay of the old power.status !== 'ok' gate hiding supplyParts.
probe.doc.getElementById('hardwareSupplyStatus').textContent = '未知';
assert.throws(verify, /有效 5V 被隱藏/);
assert.equal(probe.doc.getElementById('hardwareBatteryPercent').textContent, '未知');
render(probe, item)();
""")


@pytest.mark.parametrize("case_id, selector, replacement, message", [
    ("ups-communication_error-supply-preserved", "hardwareBatteryPercent", "0.0%", "電池百分比"),
    ("unknown-values-are-not-zero", "hardwareSupplyStatus", "5V 0.00 V", "補成數字"),
    ("unknown-values-are-not-zero", "hardwareSupplyStatus", "未見供電／效能限制", "未知旗標"),
    ("http-503-retains-last-values", "hardwareOverallStatus", "正常", "資料已過期"),
    ("critical-top-level-status", "hardwareOverallStatus", "正常", "頂層 status"),
    ("partial-supply-retains-valid-voltage", "hardwareSupplyStatus", "未知", "有效 5V"),
    ("partial-supply-retains-valid-flags", "hardwareSupplyStatus", "未知", "零限制旗標"),
    ("ups-communication_error-supply-preserved", "hardwarePowerNotice", "UPS 電池讀值未知", "通訊失敗原因"),
    ("ssh_unavailable", "hardwareNoticeText", "確認本機 SSH 轉接是否仍在執行", "自動重試"),
    ("scout_api_unavailable", "hardwareNoticeText", "每 60 秒自動重試，請確認 SSH", "失聯原因"),
])
def test_guard_rejects_false_normal_and_lost_or_invented_values(case_id, selector, replacement, message):
    import json
    node("const [id, selector, replacement, message] = " + json.dumps([case_id, selector, replacement, message]) + r""";
const probe = await monitor(), item = api.scenarios().find(row => row.id === id);
// A retained-value case requires an actual earlier good sample, even when
// this mutation test runs independently of the full sequential matrix.
if (item.retainedPower) render(probe, api.scenarios()[0])();
const verify = render(probe, item);
verify();
probe.doc.getElementById(selector).textContent = replacement;
assert.throws(verify, new RegExp(message));
""")


def test_fixed_same_origin_get_decodes_503_json_without_healthz_or_writes():
    node(r"""
let count = 0, decoded = false; const controller = new AbortController();
const payload = api.scenarios().find(row => row.id === 'http-503-retains-last-values').payload;
const result = await api.readStatus({signal: controller.signal, fetch: async (path, options) => {
  count++;
  assert.equal(path, '/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status');
  assert.equal(options.method, 'GET'); assert.equal(options.signal, controller.signal);
  assert.equal(options.mode, 'same-origin'); assert.equal(options.credentials, 'same-origin');
  assert.equal(options.redirect, 'error'); assert.equal(options.cache, 'no-store');
  return {status: 503, ok: false, headers: {get: name => {
    assert.equal(name, 'X-Scout-Monitor-Transport'); return 'ssh';
  }}, json: async () => {decoded = true; return payload;}};
}});
assert.equal(count, 1); assert.equal(decoded, true);
assert.equal(result.httpStatus, 503); assert.equal(result.payload.status, 'stale');
assert.equal(result.transport, 'ssh');
await assert.rejects(api.readStatus({signal: controller.signal, fetch: async () => {throw Error('offline')}}), /offline/);
""")


def test_probe_cancellation_removes_owned_frame_and_does_not_touch_other_frames():
    node(r"""
const win = new JSDOM('<iframe id="user-frame"></iframe>', {url: 'http://127.0.0.1:9099/admin/dashboard'}).window;
windows.push(win); const controller = new AbortController();
const pending = api.openProbe({document: win.document, signal: controller.signal});
assert.equal(win.document.querySelectorAll('iframe').length, 2);
assert.equal(win.document.querySelector('iframe[aria-hidden="true"]').src,
  'http://127.0.0.1:9099/admin/dashboard/scout-monitor?ui=20260915-hailo1');
controller.abort(); await assert.rejects(pending, /已取消/);
assert.equal(win.document.querySelectorAll('iframe').length, 1);
assert.ok(win.document.getElementById('user-frame'));
const expired = new AbortController(); expired.abort();
await assert.rejects(api.openProbe({document: win.document, signal: expired.signal}), /已取消/);
assert.equal(win.document.querySelectorAll('iframe').length, 1);
""")


def test_registered_only_in_existing_regular_diagnostic_not_navigation_or_advanced():
    source = PAGE.read_text()
    registry = source.split("const DASHBOARD_DIAGNOSTIC_CASES = Object.freeze([", 1)[1].split("\n    ]);", 1)[0]
    ids = re.findall(r'id: "(DASH-\d+)"', registry)
    assert ids.count("DASH-050") == 1
    assert {f"DASH-{number:03d}" for number in range(1, 50)} <= set(ids)
    assert 'category: "System", title: "scout monitor 電源／Hailo 讀值判讀"' in registry
    nav = source.split("const NAVIGATION_DIAGNOSTIC_CASE_IDS =", 1)[1].split("]);", 1)[0]
    assert "DASH-050" not in nav
    advanced = source.split("const DIAGNOSTIC_ADVANCED_CASES =", 1)[1].split("];", 1)[0]
    assert "DASH-050" not in advanced
    wrapper = re.search(r"(?ms)^    async function diagnosticCheck050\(\).*?^    }", source).group()
    inline = source.split("// scout-monitor-power-diagnostic-inline:start\n", 1)[1].split("// scout-monitor-power-diagnostic-inline:end", 1)[0]
    assert inline == MODULE.read_text()
    assert 'src: "/admin/dashboard/scout-monitor?ui=20260915-hailo1"' in source
    assert 'ScoutMonitorPowerDiagnostic.run({document})' in wrapper
    assert 'import("/admin/scout-monitor-power-diagnostic.js")' not in source  # no new backend route/restart needed
    node(wrapper + r"""
const document = {}, window = {ScoutMonitorPowerDiagnostic: {run: async context => {
  assert.equal(context.document, document); return {status: 'passed', detail: 'new check only'};
}}};
const diagnosticRequire = (value, message) => assert.ok(value, message);
assert.equal((await diagnosticCheck050()).detail, 'new check only');
""")


def test_hailo_diagnostic_fixtures_match_current_typed_backend_contract():
    from scout_hardware_monitor_api import HailoDevice, HailoTelemetry

    result = subprocess.run(["node", "-e", r"""
const api = require('./docs/admin/scout-monitor-power-diagnostic.js');
process.stdout.write(JSON.stringify(api.scenarios().filter(row => row.id.startsWith('hailo-'))));
"""], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert {"hailo-first-null-data", "hailo-zero-is-measured-not-failure",
            "hailo-partial-null-replaces-last-values", "hailo-legacy-missing-waits",
            "hailo-legacy-null-clears-last-devices", "hailo-empty-list-is-read-not-health",
            "hailo-empty-unavailable-is-not-absence",
            "hailo-multi-device-independent-metrics", "hailo-multi-device-partial-is-not-all-ok",
            "hailo-own-stale-with-fresh-host", "hailo-global-503-retains-not-current",
            "hailo-captured-after-host-anchor", "hailo-future-source-time-is-unknown",
            "hailo-transport-disconnect-retains-last-values", "hailo-ssh-503-retains-last-values",
            "hailo-architecture-and-errors-safe-text", "hailo-recovery-clears-invalid-state"} <= set(ids)
    required_metrics = {"nnc_utilization_percent", "cpu_utilization_percent", "ram_utilization_percent",
                        "ram_used_bytes", "ram_total_bytes", "temperature_c", "voltage_mv"}
    assert required_metrics <= HailoDevice.model_fields.keys()
    now = datetime.now(timezone.utc)
    for row in rows:
        for payload in (row.get("payload"), row.get("seed")):
            data = payload and payload.get("data")
            if not data or data.get("hailo") is None:
                continue
            sample = HailoTelemetry.model_validate(data["hailo"])
            age = (now - sample.captured_at).total_seconds()
            if row["id"] == "hailo-own-stale-with-fresh-host":
                assert 150 < age < 240
                assert payload["freshness"]["state"] == "fresh"
                anchor = datetime.fromisoformat(payload["freshness"]["captured_at"].replace("Z", "+00:00"))
                assert payload["freshness"]["age_seconds"] + (anchor - sample.captured_at).total_seconds() > 150
            elif row["id"] == "hailo-future-source-time-is-unknown":
                assert -301 < age < -240  # Deliberate future-source negative case, never current.
            else:
                assert 0 <= age < 60  # Generated now, not fixed historical "fresh" evidence.
            assert sample.read_only is True and sample.sample_window_ms == 1000
        if row.get("retainedHailo"):
            assert row["retainedHailo"] == row["seed"]["data"]["hailo"]
            assert row["retainedPower"] == row["seed"]["data"]["power"]
    assert rows[0]["payload"]["data"] is None and rows[0]["seed"]["data"] is None


def test_hailo_contract_rejects_typed_and_aggregate_regressions():
    node(r"""
const fresh = () => structuredClone(api.scenarios().find(row => row.id === 'hailo-current-metrics-and-source-time').payload.data.hailo);
const rejectDevice = (key, value) => {
  const sample = fresh(); sample.devices[0][key] = value;
  assert.throws(() => api.verifyHailoContract(sample), /Hailo|hailo/);
};
for (const key of ['nnc_utilization_percent', 'cpu_utilization_percent', 'ram_utilization_percent',
    'ram_used_bytes', 'ram_total_bytes', 'temperature_c', 'voltage_mv']) {
  for (const value of [false, true, '0', NaN, Infinity, {}, []]) rejectDevice(key, value);
}
for (const [key, value] of [['nnc_utilization_percent', -1], ['cpu_utilization_percent', 101],
    ['ram_utilization_percent', 101], ['ram_used_bytes', -1], ['ram_used_bytes', 1.5],
    ['ram_used_bytes', 2**50], ['ram_total_bytes', 0], ['ram_total_bytes', 0.1],
    ['temperature_c', -274], ['temperature_c', -1], ['voltage_mv', -1],
    ['status', 'unavailable'], ['device_id', '<img src=x>'], ['architecture', {}], ['errors', ['ok', 0]]]) rejectDevice(key, value);
for (const [key, value] of [['captured_at', '2026-09-15'], ['captured_at', 'not-a-date'],
    ['captured_at', '2026-09-15T12:00:00'], ['source', 'host.cpu'], ['read_only', false],
    ['sample_window_ms', 60000], ['devices', null], ['errors', 'timeout'], ['status', 'partial']]) {
  const sample = fresh(); sample[key] = value;
  assert.throws(() => api.verifyHailoContract(sample), /Hailo|hailo/);
}
const duplicate = fresh(); duplicate.devices.push(structuredClone(duplicate.devices[0]));
assert.throws(() => api.verifyHailoContract(duplicate), /重複/);
const mixed = structuredClone(api.scenarios().find(row => row.id === 'hailo-multi-device-partial-is-not-all-ok').payload);
mixed.data.hailo.status = 'ok';
assert.throws(() => api.verifyContract(mixed), /全體讀取狀態/);
api.verifyHailoContract(null); api.verifyHailoContract(undefined);
""")


def test_hailo_verifier_uses_backend_sample_values_units_and_actual_source_time():
    from test_scout_hailo_monitor import sample

    node("const sample = " + json.dumps(sample()) + r""";
const probe = await monitor();
const item = api.scenarios().find(row => row.id === 'hailo-current-metrics-and-source-time');
// The backend parser fixture supplies real units, not values copied from the UI.
item.payload.data.hailo = sample;
render(probe, item)();
const metric = key => probe.doc.querySelector(`[data-hailo-metric="${key}"]`).textContent;
assert.equal(metric('ram_used_bytes'), `${(sample.devices[0].ram_used_bytes / 1024 ** 3).toFixed(2)} GiB`);
assert.equal(metric('temperature_c'), `${sample.devices[0].temperature_c.toFixed(1)} °C`);
assert.equal(api.verifyCurrentHailo(probe.doc, item.payload).status, 'passed');
// Change the source without rebuilding expectations around one physical HAT.
item.payload.data.hailo.devices[0].temperature_c = 52.8;
item.payload.data.hailo.devices[0].voltage_mv = 806;
item.payload.data.hailo.devices[0].ram_used_bytes = 1536 * 1024 ** 2;
item.payload.data.hailo.captured_at = new Date(Date.now() - 32000).toISOString();
render(probe, item)();
assert.equal(metric('ram_used_bytes'), '1.50 GiB');
assert.equal(api.verifyCurrentHailo(probe.doc, item.payload).capturedAt, item.payload.data.hailo.captured_at);
""")


def test_hailo_current_payload_gap_is_not_hidden_by_successful_fixture_replays():
    node(r"""
const probe = await monitor(), cases = api.scenarios();
const checks = [
  ['hailo-current-metrics-and-source-time', 'current', 'passed'],
  ['hailo-zero-is-measured-not-failure', 'current', 'passed'],
  ['hailo-legacy-missing-waits', 'missing_field', 'warning'],
  ['hailo-legacy-null-clears-last-devices', 'missing_field', 'warning'],
  ['hailo-first-null-data', 'missing_field', 'warning'],
  ['hailo-empty-list-is-read-not-health', 'empty_devices', 'warning'],
  ['hailo-partial-null-replaces-last-values', 'partial_metrics', 'warning'],
  ['hailo-unavailable-all-null', 'partial_metrics', 'warning'],
  ['hailo-own-stale-with-fresh-host', 'unavailable_or_stale', 'warning'],
  ['hailo-future-source-time-is-unknown', 'unavailable_or_stale', 'warning'],
  ['hailo-global-503-retains-not-current', 'unavailable_or_stale', 'warning'],
  ['hailo-recovery-clears-invalid-state', 'current', 'passed'],
];
for (const [id, dataStatus, status] of checks) {
  const item = cases.find(row => row.id === id); render(probe, item)();
  const actual = api.verifyCurrentHailo(probe.doc, item.payload, item.httpStatus ?? 200);
  assert.equal(actual.id, 'live-hailo-current-payload');
  assert.equal(actual.dataStatus, dataStatus, id); assert.equal(actual.status, status, id);
}
assert.ok(api.runRenderScenarios(probe).every(row => row.status === 'passed'));
const legacy = cases.find(row => row.id === 'hailo-legacy-missing-waits'); render(probe, legacy)();
assert.equal(api.verifyCurrentHailo(probe.doc, legacy.payload).status, 'warning');
assert.match(api.verifyCurrentHailo(probe.doc, legacy.payload).detail, /缺口/);
for (const field of ['status', 'freshness']) {
  const item = structuredClone(cases.find(row => row.id === 'hailo-current-metrics-and-source-time'));
  if (field === 'status') item.payload.status = 'unknown';
  else item.payload.freshness.state = 'unreadable';
  probe.apply({response: {ok: true, status: 200}, payload: item.payload});
  const actual = api.verifyCurrentHailo(probe.doc, item.payload);
  assert.equal(actual.status, 'warning');
  assert.equal(actual.evidence.validity, 'unknown');
}
""")


def test_hailo_age_uses_scout_anchor_across_mac_clock_skew_and_elapsed_time():
    node(r"""
const probe = await monitor(), cases = api.scenarios();
const realNow = Date.now, browserNow = probe.doc.defaultView.Date.now, base = realNow();
try {
  for (const skew of [-86400000, 86400000]) {
    let clock = base + skew;
    Date.now = () => clock; probe.doc.defaultView.Date.now = () => clock;
    const current = cases.find(row => row.id === 'hailo-captured-after-host-anchor');
    render(probe, current)();
    let evidence = api.verifyHailoRendered(probe.doc, current.payload);
    assert.equal(evidence.validity, 'current'); assert.equal(evidence.ageSeconds, 2);
    assert.equal(probe.doc.getElementById('hardwareHailoAge').textContent, '2 秒');
    clock += 5000; probe.doc.defaultView.updateHardwareHailoAge();
    evidence = api.verifyHailoRendered(probe.doc, current.payload, 200, null, 5);
    assert.equal(evidence.ageSeconds, 7);
    assert.equal(probe.doc.getElementById('hardwareHailoAge').textContent, '7 秒');
    probe.apply({response: null, payload: null});
    evidence = api.verifyHailoRendered(probe.doc, null, 0, current.payload.data.hailo, 5);
    assert.equal(evidence.validity, 'unavailable');
    assert.equal(evidence.ageSeconds, null); // No response anchor: do not claim an independently verified age.
    assert.equal(probe.doc.getElementById('hardwareHailoAge').textContent, '7 秒');
    const old = cases.find(row => row.id === 'hailo-own-stale-with-fresh-host');
    render(probe, old)();
    assert.equal(api.verifyHailoRendered(probe.doc, old.payload).validity, 'stale');
    const future = cases.find(row => row.id === 'hailo-future-source-time-is-unknown');
    render(probe, future)();
    assert.equal(api.verifyCurrentHailo(probe.doc, future.payload).status, 'warning');
    assert.equal(probe.doc.getElementById('hardwareHailoAge').textContent, '未知');
    assert.match(probe.doc.getElementById('hardwareHailoStatus').textContent, /有效性未知/);
    for (const captured_at of [null, undefined, 'not-a-date', '2026-09-15T12:00:00']) {
      const invalid = structuredClone(current); invalid.payload.data.hailo.captured_at = captured_at;
      assert.throws(() => api.verifyContract(invalid.payload), /captured_at/);
      probe.apply({response: {ok: true, status: 200}, payload: invalid.payload});
      assert.equal(api.verifyHailoRendered(probe.doc, invalid.payload).validity, 'unknown');
      assert.equal(probe.doc.getElementById('hardwareHailoAge').textContent, '未知');
    }
    render(probe, current)();
    const unknownValidity = structuredClone(current);
    unknownValidity.payload.freshness.captured_at = null;
    unknownValidity.payload.server_time = new Date(Date.parse(current.payload.data.hailo.captured_at) + 45000).toISOString();
    render(probe, unknownValidity)();
    assert.equal(api.verifyHailoRendered(probe.doc, unknownValidity.payload).ageSeconds, 45);
    // Hailo ages out even if host snapshot age remains below 150 seconds.
    const edge = structuredClone(current);
    edge.payload.freshness.age_seconds = 1;
    edge.payload.data.hailo.captured_at = new Date(Date.parse(edge.payload.freshness.captured_at) - 148000).toISOString();
    render(probe, edge)();
    clock += 3000; probe.doc.defaultView.updateHardwareHailoAge();
    evidence = api.verifyHailoRendered(probe.doc, edge.payload, 200, null, 3);
    assert.equal(evidence.validity, 'stale'); assert.equal(evidence.ageSeconds, 152);
    assert.equal(probe.doc.getElementById('hardwareOverallStatus').textContent, '正常');
  }
} finally { Date.now = realNow; probe.doc.defaultView.Date.now = browserNow; }
""")


def test_existing_dash050_full_report_keeps_missing_live_hailo_as_warning():
    node(r"""
// Drive the production run/openProbe/report functions. Only iframe loading and
// its network result are substituted; all render functions are real page code.
for (const missing of [true, false]) {
  const probe = await monitor();
  const host = new JSDOM('<main></main>', {url: 'http://127.0.0.1:9099/admin/dashboard'}).window;
  windows.push(host);
  const payload = api.scenarios().find(row => row.id === 'hailo-current-metrics-and-source-time').payload;
  if (missing) delete payload.data.hailo;
  host.fetch = async (path, options) => {
    assert.equal(path, '/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status');
    assert.equal(options.method, 'GET');
    return {ok: true, status: 200, headers: {get: () => 'ssh'}, json: async () => payload};
  };
  const append = host.document.body.appendChild.bind(host.document.body);
  host.document.body.appendChild = frame => {
    const result = append(frame);
    Object.defineProperties(frame, {contentDocument: {value: probe.doc},
      contentWindow: {value: probe.doc.defaultView}});
    setImmediate(() => frame.onload?.());
    return result;
  };
  const report = await api.run({document: host.document});
  assert.equal(report.id, 'DASH-050');
  assert.equal(report.status, missing ? 'warning' : 'passed', JSON.stringify(report.rows.filter(row => row.status !== 'passed')));
  assert.equal(report.dataStatus, 'current'); // Host sample current does not fill the Hailo gap.
  assert.equal(report.hailoDataStatus, missing ? 'missing_field' : 'current');
  assert.equal(report.rows.find(row => row.id === 'live-hailo-current-payload').status, missing ? 'warning' : 'passed');
  assert.ok(report.rows.filter(row => row.id !== 'live-hailo-current-payload').every(row => row.status === 'passed'));
  assert.equal(report.probeCleanup, 'passed');
  assert.equal(host.document.querySelectorAll('iframe').length, 0);
  assert.equal(report.hardware_control_invoked, false);
  assert.equal(report.runtime_safety_truth, false);
  assert.equal(report.official_qualification_eligible, false);
  assert.match(report.detail, /電源分離與 Hailo/);
  assert.match(report.detail, /不代表.*Hailo 推論成功/);
  assert.equal(api.snapshot().hailoDataStatus, report.hailoDataStatus);
}
""")


def test_hailo_render_guard_rejects_old_ui_wrong_units_mixed_devices_and_fake_zero():
    node(r"""
const probe = await monitor(), cases = api.scenarios();
const metricCases = [
  ['hailo-current-metrics-and-source-time', 'nnc_utilization_percent', '未知'],
  ['hailo-current-metrics-and-source-time', 'cpu_utilization_percent', '33.3%'],
  ['hailo-current-metrics-and-source-time', 'ram_utilization_percent', '82%'],
  ['hailo-current-metrics-and-source-time', 'ram_used_bytes', '82 GiB'],
  ['hailo-current-metrics-and-source-time', 'ram_total_bytes', '7221 MB'],
  ['hailo-current-metrics-and-source-time', 'temperature_c', '46.2 V'],
  ['hailo-current-metrics-and-source-time', 'voltage_mv', '0.802 W'],
  ['hailo-zero-is-measured-not-failure', 'nnc_utilization_percent', '未知'],
  ['hailo-partial-null-replaces-last-values', 'nnc_utilization_percent', '0.0%'],
  ['hailo-partial-null-replaces-last-values', 'ram_used_bytes', '0.08 GiB'],
  ['hailo-unavailable-all-null', 'temperature_c', '0.0 °C'],
];
for (const [id, metric, falseReading] of metricCases) {
  const item = cases.find(row => row.id === id), verify = render(probe, item); verify();
  probe.doc.querySelector(`[data-hailo-metric="${metric}"]`).textContent = falseReading;
  assert.throws(verify, /Hailo/, `${id}: ${metric}`);
}
const multi = cases.find(row => row.id === 'hailo-multi-device-independent-metrics');
let verify = render(probe, multi); verify();
const cards = [...probe.doc.querySelectorAll('[data-hailo-device]')];
cards[1].querySelector('[data-hailo-metric="temperature_c"]').textContent = cards[0].querySelector('[data-hailo-metric="temperature_c"]').textContent;
assert.throws(verify, /temperature_c/);
verify = render(probe, multi); verify();
probe.doc.querySelector('[data-hailo-device]').remove();
assert.throws(verify, /數量/);
const current = cases.find(row => row.id === 'hailo-current-metrics-and-source-time');
verify = render(probe, current); verify();
probe.doc.querySelector('[data-hailo-metric="captured_at"]').textContent = '重新整理時間，不是來源時間';
assert.throws(verify, /captured_at/);
verify = render(probe, current); verify();
probe.doc.getElementById('hardwareHailoPanel').remove();
assert.throws(verify, /缺少/); // Equivalent old UI still passes power but must fail Hailo.
""")


def test_hailo_render_guard_rejects_false_current_unsafe_text_and_lost_retained_values():
    node(r"""
const probe = await monitor(), cases = api.scenarios();
for (const id of ['hailo-own-stale-with-fresh-host', 'hailo-global-503-retains-not-current',
    'hailo-transport-disconnect-retains-last-values', 'hailo-ssh-503-retains-last-values']) {
  const item = cases.find(row => row.id === id), verify = render(probe, item); verify();
  probe.doc.getElementById('hardwareHailoPanel').dataset.state = 'ok';
  probe.doc.getElementById('hardwareHailoStatus').textContent = '✓ 已讀取';
  probe.doc.getElementById('hardwareHailoMeta').textContent = '目前 Hailo 正常';
  assert.throws(verify, /Hailo/);
  render(probe, item)();
  probe.doc.querySelector('[data-hailo-metric="nnc_utilization_percent"]').textContent = '未知';
  assert.throws(verify, /nnc_utilization_percent/);
}
const hostile = cases.find(row => row.id === 'hailo-architecture-and-errors-safe-text');
const verify = render(probe, hostile); verify();
assert.equal(probe.doc.defaultView.hailoInjected, undefined);
const name = probe.doc.querySelector('.hailo-grid .inventory-section-summary');
name.innerHTML = hostile.payload.data.hailo.devices[0].architecture;
assert.throws(verify, /安全純文字/);
render(probe, hostile)();
probe.doc.querySelector('#hardwareHailoErrorList li').textContent = '丟棄原始錯誤';
probe.doc.querySelector('[data-hailo-device] .inventory-errors li').textContent = '丟棄原始錯誤';
assert.throws(verify, /錯誤未原樣/);
const recovery = cases.find(row => row.id === 'hailo-recovery-clears-invalid-state'); render(probe, recovery)();
assert.equal(api.verifyCurrentHailo(probe.doc, recovery.payload).status, 'passed');
""")
