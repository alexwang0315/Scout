"""DASH-050 contract/production-render replays; never hardware-health evidence.

No server, real .env, device, SSH, or Gateway is used. The monitor document and
functions are the production source, executed in JSDOM with network disabled.
"""
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
  const httpStatus = item.httpStatus ?? 200;
  probe.apply({response: httpStatus ? {ok: httpStatus === 200, status: httpStatus} : null, payload: item.payload});
  return () => api.verifyRendered(probe.doc, item.payload, httpStatus, item.retainedPower);
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
  'http://127.0.0.1:9099/admin/dashboard/scout-monitor?ui=20260914-ssh1');
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
    assert 'category: "System", title: "scout monitor 電池／主機供電分離"' in registry
    nav = source.split("const NAVIGATION_DIAGNOSTIC_CASE_IDS =", 1)[1].split("]);", 1)[0]
    assert "DASH-050" not in nav
    advanced = source.split("const DIAGNOSTIC_ADVANCED_CASES =", 1)[1].split("];", 1)[0]
    assert "DASH-050" not in advanced
    wrapper = re.search(r"(?ms)^    async function diagnosticCheck050\(\).*?^    }", source).group()
    inline = source.split("// scout-monitor-power-diagnostic-inline:start\n", 1)[1].split("// scout-monitor-power-diagnostic-inline:end", 1)[0]
    assert inline == MODULE.read_text()
    assert 'src: "/admin/dashboard/scout-monitor?ui=20260914-ssh1"' in source
    assert 'ScoutMonitorPowerDiagnostic.run({document})' in wrapper
    assert 'import("/admin/scout-monitor-power-diagnostic.js")' not in source  # no new backend route/restart needed
    node(wrapper + r"""
const document = {}, window = {ScoutMonitorPowerDiagnostic: {run: async context => {
  assert.equal(context.document, document); return {status: 'passed', detail: 'new check only'};
}}};
const diagnosticRequire = (value, message) => assert.ok(value, message);
assert.equal((await diagnosticCheck050()).detail, 'new check only');
""")
