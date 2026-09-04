import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for Weather refresh tests")
    html = PAGE.read_text(encoding="utf-8")
    names = (
        "loadWeatherData", "scheduleConnectedPreparationPolling",
        "stopConnectedPreparationPolling", "weatherRefreshState",
        "loadConnectedPreparationStatus", "triggerDashboardConnectedPreparation",
        "weatherDecisionReadiness",
    )
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", html)
        assert match, name
        functions.append(match.group(0))
    program = "\n".join(functions) + r"""
let project = "alpha";
let base = "";
const projectId = () => project;
const apiBase = () => base;
const refreshCurrentDataView = () => {};
const formatCwaTimestamp = value => value;
const asArray = value => Array.isArray(value) ? value : [];
const state = {route: "outdoor-weather", weatherData: {}, weatherDataRequestId: 0,
  connectedPreparation: null, connectedPreparationPollTimer: null};
let timer;
const window = {setTimeout: callback => {timer = callback; return 1;}, clearTimeout() {}};
const completed = {projectId: "alpha", status: "ready", completedAt: "2026-09-04T03:00:00Z"};
const dashboard = {projectId: "alpha", status: "ready", evaluatedAt: "2026-09-04T03:00:01Z",
  decision: {candidateDecision: "GO"}, rainfall: {pairId: "rain-new"}, imagery: {pairId: "image-new"}};
const calls = [];
let fetchJson = async path => {calls.push(path); return path.endsWith("/connected-preparation") ? completed : dashboard;};
const postJson = async () => completed;
""" + "\n(async () => {\n" + probe + "\n})().catch(error => {console.error(error); process.exitCode = 1;});"
    completed_run = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed_run.returncode == 0, completed_run.stderr
    return json.loads(completed_run.stdout)


def test_decision_read_starts_after_preparation_status_is_known() -> None:
    result = _run("await loadWeatherData(); console.log(JSON.stringify({calls, weather: state.weatherData}));")
    assert result["calls"][0].endswith("/connected-preparation")
    assert result["calls"][1].endswith("/weather-dashboard")
    review = result["weather"]["decisionReview"]
    assert review["status"] == "reevaluated"
    assert review["preparationCompletedAt"] == "2026-09-04T03:00:00Z"
    assert review["rainfallPairId"] == "rain-new"
    assert review["imageryPairId"] == "image-new"


def test_completed_job_reloads_decision_even_after_navigation_away() -> None:
    result = _run("""
state.route = "home";
state.connectedPreparation = {status: "running"};
scheduleConnectedPreparationPolling();
await timer();
console.log(JSON.stringify({calls, weather: state.weatherData}));
""")
    assert any(path.endswith("/weather-dashboard") for path in result["calls"])
    assert result["weather"]["decision"]["candidateDecision"] == "GO"


def test_status_read_cannot_consume_completion_before_decision_reload() -> None:
    result = _run("""
state.connectedPreparation = {status: "running"};
scheduleConnectedPreparationPolling();
state.connectedPreparation = completed;
await timer();
console.log(JSON.stringify({calls, weather: state.weatherData}));
""")
    assert any(path.endswith("/weather-dashboard") for path in result["calls"])
    assert result["weather"]["decisionReview"]["status"] == "reevaluated"


@pytest.mark.parametrize("change", ['project = "beta";', 'base = "https://other.example";'])
def test_old_project_or_api_response_cannot_replace_current_weather(change: str) -> None:
    result = _run("""
let resolveOld;
fetchJson = async path => path.endsWith("/connected-preparation") ? completed
  : new Promise(resolve => {resolveOld = resolve;});
const pending = loadWeatherData();
await Promise.resolve(); await Promise.resolve();
""" + change + """
state.weatherData = {marker: "current-scope"};
resolveOld(dashboard);
await pending;
console.log(JSON.stringify(state.weatherData));
""")
    assert result == {"marker": "current-scope"}


def test_slow_older_read_cannot_overwrite_post_refresh_decision() -> None:
    result = _run("""
let resolveOld;
let count = 0;
fetchJson = async path => path.endsWith("/connected-preparation") ? completed
  : ++count === 1 ? new Promise(resolve => {resolveOld = resolve;}) : dashboard;
const pending = loadWeatherData();
await Promise.resolve(); await Promise.resolve();
await loadWeatherData();
resolveOld({...dashboard, status: "stale_data", decision: {candidateDecision: "DELAY"}});
await pending;
console.log(JSON.stringify(state.weatherData));
""")
    assert result["decision"]["candidateDecision"] == "GO"


def test_refresh_can_be_reassessed_and_still_delay_for_stale_evidence() -> None:
    result = _run("""
fetchJson = async path => path.endsWith("/connected-preparation") ? completed
  : {...dashboard, status: "stale_data", decision: {candidateDecision: "DELAY"}};
await loadWeatherData();
console.log(JSON.stringify(state.weatherData));
""")
    assert result["decisionReview"]["status"] == "reevaluated"
    assert result["decisionReview"]["evidenceStatus"] == "stale_data"
    assert result["decision"]["candidateDecision"] == "DELAY"


def test_pre_completion_response_is_not_claimed_as_a_refresh_reassessment() -> None:
    result = _run("""
fetchJson = async path => path.endsWith("/connected-preparation") ? completed
  : {...dashboard, evaluatedAt: "2026-09-04T02:59:59Z"};
await loadWeatherData();
console.log(JSON.stringify(state.weatherData));
""")
    assert result["decisionReview"]["status"] == "unverified"


def test_failed_decision_read_cannot_show_successful_refresh_confirmation() -> None:
    result = _run("""
fetchJson = async path => {
  if (path.endsWith("/connected-preparation")) return completed;
  throw new Error("Decision API unavailable");
};
await loadWeatherData();
console.log(JSON.stringify({...state.weatherData,
  posture: weatherDecisionReadiness({weather: state.weatherData,
    imageryFamilies: [], preferredRainfall: null})}));
""")
    assert result["decisionReview"]["status"] == "failed"
    assert result["decision"] is None
    assert result["posture"]["label"] == "UNAVAILABLE"


@pytest.mark.parametrize("entrypoint", [
    "loadConnectedPreparationStatus()",
    "triggerDashboardConnectedPreparation('operator-refresh', {force: true})",
])
def test_every_completion_entrypoint_reloads_decision(entrypoint: str) -> None:
    result = _run(f"await {entrypoint}; console.log(JSON.stringify({{calls, weather: state.weatherData}}));")
    assert any(path.endswith("/weather-dashboard") for path in result["calls"])
    assert result["weather"]["decisionReview"]["status"] == "reevaluated"


def test_transient_status_failure_does_not_abandon_a_running_refresh() -> None:
    result = _run("""
state.connectedPreparation = {projectId: "alpha", status: "running"};
fetchJson = async path => {
  if (path.endsWith("/connected-preparation")) throw new Error("temporary status failure");
  return dashboard;
};
await loadWeatherData();
console.log(JSON.stringify({preparation: state.connectedPreparation, weather: state.weatherData, polling: Boolean(timer)}));
""")
    assert result["preparation"]["status"] == "running"
    assert result["weather"]["decisionReview"]["status"] == "awaiting_refresh"
    assert result["polling"] is True


@pytest.mark.parametrize("entrypoint", ["await timer();", "await loadConnectedPreparationStatus();"])
def test_transient_poll_or_status_failure_retains_refresh_tracking(entrypoint: str) -> None:
    result = _run("""
state.connectedPreparation = {projectId: "alpha", status: "running"};
scheduleConnectedPreparationPolling();
fetchJson = async () => {throw new Error("temporary status failure");};
""" + entrypoint + """
console.log(JSON.stringify({preparation: state.connectedPreparation,
  polling: Boolean(state.connectedPreparationPollTimer)}));
""")
    assert result["preparation"]["status"] == "running"
    assert result["preparation"]["lastError"]["message"] == "temporary status failure"
    assert result["polling"] is True
