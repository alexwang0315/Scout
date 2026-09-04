import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _function(html: str, name: str) -> str:
    match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", html)
    assert match, name
    return match.group(0)


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the Diagnostic runner")
    html = PAGE.read_text(encoding="utf-8")
    source = "\n".join(_function(html, name) for name in (
        "runDashboardDiagnostic", "diagnosticResult", "diagnosticSetResult",
        "diagnosticCaseScopeKey", "diagnosticRequire", "diagnosticSafeDetail",
        "diagnosticCheck044", "diagnosticMapOrderGap",
    ))
    program = source + r"""
let project = 'workspace-a';
let base = '';
const apiBase = () => base;
const projectId = () => project;
const NAVIGATION_DIAGNOSTIC_CASE_IDS = [];
const diagnosticExecutionBusy = () => false;
const diagnosticResourceCache = new Map();
const updateDiagnosticDom = () => {};
const state = {diagnosticResults: {}};
const surfaces = [{id: 'weather-map', status: 'failed', layers: [],
  violations: [{code: 'background_over_route', detail: 'radar is above route'}], gaps: []}];
const DASHBOARD_DIAGNOSTIC_CASES = [{id: 'DASH-044', run: async () => ({
  status: 'failed', detail: 'one order error', mapLayerOrder: {projectId: project, surfaces},
})}];
""" + "\n(async () => {\n" + probe + "\n})().catch(error => {console.error(error); process.exitCode = 1;});"
    completed = subprocess.run([node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_map_order_failure_keeps_per_surface_evidence() -> None:
    result = _run("console.log(JSON.stringify(await runDashboardDiagnostic('DASH-044')));")
    assert result["status"] == "failed"
    assert result["detail"] == "one order error"
    assert result["mapLayerOrder"]["surfaces"][0]["violations"][0]["code"] == "background_over_route"


def test_project_switch_invalidates_map_order_evidence() -> None:
    result = _run("""
await runDashboardDiagnostic('DASH-044');
project = 'workspace-b';
console.log(JSON.stringify(diagnosticResult('DASH-044')));
""")
    assert result["status"] == "idle"
    assert "mapLayerOrder" not in result


def test_project_switch_during_probe_cannot_publish_old_project_success() -> None:
    result = _run("""
DASHBOARD_DIAGNOSTIC_CASES[0].run = async () => {
  project = 'workspace-b';
  return {status: 'passed', detail: 'stale success', mapLayerOrder: {surfaces}};
};
await runDashboardDiagnostic('DASH-044');
console.log(JSON.stringify({stored: state.diagnosticResults['DASH-044'], displayed: diagnosticResult('DASH-044')}));
""")
    assert result["stored"]["status"] == "failed"
    assert result["stored"]["mapLayerOrder"] is None
    assert result["displayed"]["status"] == "idle"


def test_warning_does_not_become_pass_and_keeps_coverage() -> None:
    result = _run("""
DASHBOARD_DIAGNOSTIC_CASES[0].run = async () => ({
  status: 'warning', detail: 'map not loaded', mapLayerOrder: {surfaces: [{id: 'map', status: 'warning'}]},
});
console.log(JSON.stringify(await runDashboardDiagnostic('DASH-044')));
""")
    assert result["status"] == "warning"
    assert result["mapLayerOrder"]["surfaces"][0]["id"] == "map"


@pytest.mark.parametrize("base", ["https://other.example", "http://127.0.0.1:9099/proxy"])
def test_different_api_source_is_not_replaced_by_same_named_local_project(base: str) -> None:
    result = _run(f"""
base = {json.dumps(base)};
global.location = new URL('http://127.0.0.1:9099/admin/dashboard');
global.window = {{ScoutMapLibreEvidence: {{inspectSvgLayerOrder() {{}}, inspectMapLibreLayerOrder() {{}}}}}};
global.DASHBOARD_MAP_ORDER_SURFACES = [{{id: 'map', label: 'Map'}}];
console.log(JSON.stringify(await diagnosticCheck044()));
""")
    assert result["status"] == "warning"
    assert result["mapLayerOrder"]["surfaces"][0]["variant"] == "source"
