"""Execute read-only Diagnostic coverage cases against bounded response fixtures."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_coverage_availability_and_boundary_failures() -> None:
    html = (ROOT / "docs/admin/scout-dashboard-v0.1.html").read_text()
    names = ["diagnosticCoverageResult", "diagnosticCoverageRead"] + [
        f"diagnosticCheck{number:03d}" for number in range(45, 49)
    ]
    functions = []
    for name in names:
        match = re.search(
            rf"^    (?:async )?function {name}\(.*?(?=^    (?:async )?function |^    const |\Z)",
            html,
            re.MULTILINE | re.DOTALL,
        )
        assert match, f"Missing Diagnostic function {name}"
        functions.append(match.group())
    harness = r'''
const assert = require("node:assert/strict");
let payload, unavailable = false;
let reads = [];
const window = {indexedDB: {}, crypto: {subtle: {}}};
const location = {href: "http://127.0.0.1:8000/admin/dashboard"};
const RUNTIME_AUDIT_PATH = "/admin/runtime-audit";
const DASHBOARD_LIVING_PATH = "/admin/dashboard/living";
const diagnosticRequire = (condition, message) => {if (!condition) throw Error(message)};
const diagnosticEnvelope = async path => {
  reads.push(path);
  if (unavailable) throw Error("private transport detail");
  return {data: path === "/admin/intelligence" ? 'data-intelligence-telemetry-page "/admin/intelligence/telemetry"' : payload};
};
const diagnosticMarkupRoot = () => ({querySelector: () => ({getAttribute: () => "/admin/intelligence"})});
const diagnosticRouteMarkup = () => "iframe";
const renderRuntimeAuditPage = () => "logs";
const renderLivingPage = () => "living";
const renderEmergencyPage = () => "data-daily-emergency-review data-emergency-review-pane data-emergency-field-operations data-emergency-offline-banner";
const loadRuntimeAuditData = () => "fetchJson(";
const diagnosticCompactSource = fn => String(fn);
const diagnosticRenderWithState = (_state, renderer) => renderer();
const projectId = () => "fixture_project";
const permissionProjectionPath = (project, lens) => `/admin/pretrip/projects/${project}/contextual-permission-dashboard?lens=${lens}`;
const permissionDailyReviewPath = (project, day) => `/admin/pretrip/projects/${project}/safety-emergency/mission-days/${day}/night-review`;
const diagnosticIsSha256 = value => /^[a-f0-9]{64}$/.test(value);
'''
    checks = r'''
(async () => {
  unavailable = true;
  for (const run of [diagnosticCheck045, diagnosticCheck046, diagnosticCheck047, diagnosticCheck048]) {
    const result = await run();
    assert.equal(result.structureStatus, "passed");
    assert.equal(result.status, "warning");
    assert.equal(result.dataStatus, "unavailable");
    assert.ok(!result.detail.includes("private transport detail"));
  }
  unavailable = false;
  payload = {schema_version: "scout_runtime_audit_list.v1", events: [], boundary: {telemetry_only: true, runtime_safety_truth: false, raw_payloads_embedded: false}, integrity: {verified: true}, writer_health: {status: "healthy"}};
  assert.equal((await diagnosticCheck045()).status, "warning");
  payload.events.push({event_id: "redacted"});
  assert.equal((await diagnosticCheck045()).status, "passed");
  payload.integrity.verified = false;
  await assert.rejects(diagnosticCheck045, /integrity failure/);
  payload = {schema_version: "scout.emergency_mobile_closed_loop.living.v0", timeline: [], status: "unavailable", boundary: {}};
  for (const key of ["local_only", "synthetic_scenario", "candidate_only"]) payload.boundary[key] = true;
  for (const key of ["runtime_safety_truth", "phase1_runtime_safety_truth", "phase1_l0_l4_state_mutated", "safety_api_called", "real_outbound_send_performed", "production_transport_invoked", "hardware_control_invoked", "network_mqtt_publish_performed", "precise_real_user_location_embedded", "raw_health_payload_embedded"]) payload.boundary[key] = false;
  assert.equal((await diagnosticCheck046()).status, "warning");
  payload.transport_receipt = {simulated_transport: true, simulated_receipt_correlated: true, production_delivery_verified: true, production_send_performed: false, sent: false};
  await assert.rejects(diagnosticCheck046, /production_delivery_verified/);
  payload = {schema_version: "scout.intelligence_telemetry.v0", jobs: [], status: "unavailable", read_only: true, candidate_only: true, runtime_safety_truth: false, promotion_result: "not_promoted", store_available: false};
  assert.equal((await diagnosticCheck047()).status, "warning");
  payload.jobs.push({candidate_only: true, runtime_safety_truth: true});
  await assert.rejects(diagnosticCheck047, /job claims runtime authority/);
  payload = {project_id: "fixture_project", candidate_only: true, runtime_safety_truth: false, movement_groups: []};
  assert.equal((await diagnosticCheck048()).status, "warning");
  payload.project_id = "wrong_project";
  await assert.rejects(diagnosticCheck048, /another project/);
  assert.ok(reads.every(path => path.startsWith("/admin/")));
})().catch(error => {console.error(error); process.exitCode = 1});
'''
    result = subprocess.run(
        ["node", "-e", harness + "\n".join(functions) + checks],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
