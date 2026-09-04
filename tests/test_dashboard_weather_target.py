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
        pytest.skip("Node is required for Weather target tests")
    html = PAGE.read_text(encoding="utf-8")
    names = (
        "weatherTrendTargets", "selectedWeatherTrendTarget", "weatherNumberLabel",
        "weatherBooleanLabel", "weatherPercentLabel", "weatherDecisionReadiness",
        "weatherRainfallTrendResultText", "requestAuthorizedRainfallTrend",
        "renderWeatherDecisionEvidence", "bindWeatherCwaControls", "loadWeatherData",
        "selectWeatherTrendTarget", "clearWeatherTargetResult", "weatherRainfallPointText",
        "weatherRainfallSourceDetails", "refreshWeatherTargetView", "bindWeatherTargetControls",
        "weatherRefreshState", "weatherCriticalWindowLabel",
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
let renders = 0;
const refreshCurrentDataView = () => {renders++;};
const asArray = value => Array.isArray(value) ? value : [];
const formatCwaTimestampOr = (value, fallback) => value || fallback;
const formatCwaTimestamp = value => value;
const escapeHtml = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
const scheduleConnectedPreparationPolling = () => {};
const state = {
  route: "outdoor-weather", weatherDataRequestId: 0, weatherTargetRequestId: 0,
  weatherTargetCheckpointId: "cp103", weatherLocationTrendStatus: {status: "idle"},
  project: {checkpoints: [
    {candidate_id: "cp102", label: "CP 102", lat: 23.4, lon: 120.6},
    {candidate_id: "cp103", label: "CP 103", lat: 23.5, lon: 120.7},
  ]},
  weatherData: {
    status: "ready", schemaVersion: "weatherDecisionDashboard.v1",
    decision: {candidateDecision: "GO", summary: "old route decision"},
    routeTrend: {target: {id: "cp102", past1hMm: 1, next1hMm: 1}},
    rainfall: {pairId: "rain-old"}, imagery: {pairId: "imagery-old"},
    routeRisk: {generatedAt: "2026-09-04T09:00:00+08:00"},
    loraAlert: {alertId: "route-preview-old", byteLength: 78, sent: false},
    decisionReview: {status: "reevaluated", evaluatedAt: "2026-09-04T09:01:00+08:00",
      preparationCompletedAt: "2026-09-04T09:00:00+08:00", preparationInputsStatus: "current_run"},
  },
  connectedPreparation: {projectId: "alpha", status: "ready", completedAt: "2026-09-04T09:00:00+08:00"},
};
const clone = value => JSON.parse(JSON.stringify(value));
const sampledTrend = id => ({
  schemaVersion: "route_precipitation_trend.v1", status: "ready",
  evaluatedAt: "2026-09-04T09:45:00+08:00",
  currentPosition: {status: "ready", past1hMm: 10, next1hMm: 37.6, trend: "increasing"},
  target: {id, status: "missing_cell", past1hMm: 0, next1hMm: null, trend: "unknown"},
  sourceTimestamps: {past1hQpe: "2026-09-04T09:30:00+08:00", next1hQpf: "2026-09-04T09:40:00+08:00"},
  validWindows: {
    past1hQpe: ["2026-09-04T08:30:00+08:00", "2026-09-04T09:30:00+08:00"],
    next1hQpf: ["2026-09-04T09:40:00+08:00", "2026-09-04T10:40:00+08:00"],
  },
  boundary: {rawCoordinatesPersisted: false, runtimeSafetyTruth: false},
});
const responseFor = id => {
  const trend = sampledTrend(id);
  return {...trend,
    decisionReview: {status: "reevaluated", trigger: "target-rainfall-trend", projectId: "alpha",
      targetId: id, evaluatedAt: trend.evaluatedAt, evidenceStatus: "partial",
      rainfallPairId: "rain-new", imageryPairId: "imagery-new",
      sourceFrameIds: {qpe_past_1h: "qpe-frame", qpf_next_1h: "qpf-frame"}},
    weatherDashboard: {
      schemaVersion: "weatherDecisionDashboard.v1", projectId: "alpha", status: "partial",
      evaluatedAt: trend.evaluatedAt, rainfall: {pairId: "rain-new"}, imagery: {pairId: "imagery-new"},
      routeTrend: trend, routeRisk: {generatedAt: "2026-09-04T09:42:00+08:00", imageryFeatures: {}},
      decision: {candidateDecision: "CHANGE_PLAN", summary: `reviewed ${id}`, where: [id]},
      trendContext: {scope: "request_only", targetId: id, rawCoordinatesPersisted: false},
      loraAlert: {alertId: "cached-route-preview", byteLength: 78, sent: false,
        basis: "persisted_route_risk", targetSpecific: false},
    },
  };
};
const approval = {reference: "fixture-approval", approvedAt: "2026-09-04T09:44:00+08:00",
  scope: "current_trip_rainfall_sampling"};
const position = {coords: {latitude: 23.45, longitude: 120.65, accuracy: 10}, timestamp: 1788486240000};
let geoCalls = 0;
let browserCurrentPosition = async () => {geoCalls++; return position;};
const calls = [];
let postHandler = async (path, body) => path.endsWith("rainfall-location-approvals")
  ? approval : responseFor(body.targetPosition.id);
const postJson = async (path, body) => {calls.push({path, body: clone(body)}); return postHandler(path, body);};
const routeDashboard = {...responseFor("route-cache").weatherDashboard,
  routeTrend: {target: {status: "not_provided"}, currentPosition: {status: "not_provided"}},
  decision: {candidateDecision: "DELAY", summary: "route cache"}};
let fetchHandler = async path => path.endsWith("connected-preparation") ? state.connectedPreparation : routeDashboard;
const fetchJson = async path => {calls.push({path}); return fetchHandler(path);};
const handlers = {};
let viewUpdates = 0;
let evidenceMarkup = "";
const decisionPanel = {set outerHTML(value) {viewUpdates++; evidenceMarkup = value;}};
const postureLabel = {textContent: "GO"};
const postureSummary = {textContent: "old route decision"};
const actionLabel = {textContent: "GO candidate"};
const actionSummary = {textContent: "old route action"};
const primary = {dataset: {}, querySelector: selector => selector === "strong" ? postureLabel : postureSummary};
const refreshLabel = {textContent: "old review"};
const criticalWindowLabel = {textContent: "old arrival estimate"};
let provenanceMarkup = "";
const provenancePanel = {set outerHTML(value) {provenanceMarkup = value;}};
const renderWeatherLiveSummary = snapshot => snapshot.routeTrend?.status || "not_prepared";
const document = {
  querySelector: selector => selector === '[data-weather-target-checkpoint="true"]'
    ? {addEventListener: (event, callback) => {handlers.targetChange = callback;}}
    : selector === '[data-weather-authorize-location="true"]'
      ? {addEventListener: (event, callback) => {handlers.authorize = callback;}}
      : selector === '[data-weather-decision-evidence="true"]' ? decisionPanel
        : selector === '[data-weather-decision-band="true"] .weather-decision-primary' ? primary
          : selector === '[data-weather-actions="true"] .weather-action-item:first-child strong' ? actionLabel
            : selector === '[data-weather-actions="true"] .weather-action-item:first-child span' ? actionSummary
              : selector === '[data-weather-critical-window="true"] strong' ? criticalWindowLabel
                : selector === '[data-weather-status]' ? provenancePanel : null,
  querySelectorAll: selector => selector === '[data-weather-refresh-status]' ? [refreshLabel] : [],
};
const window = {};
const localStorage = {setItem: () => {throw new Error("coordinate storage forbidden");}};
const sessionStorage = localStorage;
const changeTarget = id => {bindWeatherCwaControls(); handlers.targetChange({currentTarget: {value: id}});};
const snapshot = () => ({weather: state.weatherData, decision: state.weatherData.decision,
  loading: ["idle", "loading"].includes(state.weatherData.status),
  routeTrend: state.weatherData.routeTrend, routeRisk: state.weatherData.routeRisk,
  loraAlert: state.weatherData.loraAlert, connectedPreparation: state.connectedPreparation,
  imageryFamilies: [], preferredRainfall: {}, derived: state.weatherData.status});
const weatherCandidateSnapshot = () => snapshot();
const deferred = () => {let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject};};
const tick = async () => {for (let index = 0; index < 8; index++) await Promise.resolve();};
""" + "\n(async () => {\n" + probe + "\n})().catch(error => {console.error(error); process.exitCode = 1;});"
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_sampling_consumes_the_bound_decision_dashboard_without_new_cwa_or_rf() -> None:
    result = _run("""
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  paths: calls.map(item => item.path), geoCalls, markup: renderWeatherDecisionEvidence(snapshot())}));
""")
    weather = result["weather"]
    assert weather["decision"]["candidateDecision"] == "CHANGE_PLAN"
    assert weather["dashboard"]["routeTrend"]["target"]["id"] == "cp103"
    assert weather["routeTrend"]["currentPosition"]["next1hMm"] == 37.6
    assert weather["rainfall"]["pairId"] == "rain-new"
    assert weather["imagery"]["pairId"] == "imagery-new"
    assert weather["decisionReview"]["targetId"] == "cp103"
    assert weather["decisionReview"]["trigger"] == "target-rainfall-trend"
    assert weather["decisionReview"]["status"] == "reevaluated"
    assert weather["decisionReview"]["sourceFrameIds"]["qpf_next_1h"] == "qpf-frame"
    assert weather["dashboard"]["trendContext"] == {
        "scope": "request_only", "targetId": "cp103", "rawCoordinatesPersisted": False,
    }
    assert weather["decisionReview"]["preparationCompletedAt"] == "2026-09-04T09:00:00+08:00"
    assert "Decision API 已重審" in result["location"]["text"]
    assert "CP 103" in result["location"]["text"]
    assert "2026-09-04T09:45:00+08:00" in result["location"]["text"]
    assert result["geoCalls"] == 1
    assert result["paths"] == [
        "/admin/pretrip/projects/alpha/rainfall-location-approvals",
        "/admin/pretrip/projects/alpha/rainfall-trend",
    ]
    assert weather["loraAlert"]["alertId"] == "route-preview-old"
    assert "route-level unsent preview" in result["markup"]
    assert "sent=false" in result["markup"]
    assert "no RF action is authorized" in result["markup"]
    assert 'data-weather-decision-target="cp103"' in result["markup"]
    assert '"latitude"' not in json.dumps(weather)
    assert '"lat"' not in json.dumps(weather)


@pytest.mark.parametrize("omit", ["both", "dashboard", "review"])
def test_legacy_or_incomplete_backend_cannot_relabel_old_go_as_target_decision(omit: str) -> None:
    result = _run("""
postHandler = async path => {
  if (path.endsWith("rainfall-location-approvals")) return approval;
  const response = responseFor("cp103");
""" + ("delete response.decisionReview;\n" if omit in {"both", "review"} else "")
        + ("delete response.weatherDashboard;\n" if omit in {"both", "dashboard"} else "") + """
  return response;
};
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  posture: weatherDecisionReadiness(snapshot())}));
""")
    assert result["weather"]["routeTrend"]["target"]["id"] == "cp103"
    assert result["weather"]["decision"] is None
    assert result["weather"]["decisionReview"]["status"] == "unverified"
    assert result["posture"]["label"] == "UNVERIFIED"
    assert "尚未重審" in result["location"]["text"]
    assert "已重算" in result["location"]["text"]


def test_target_change_invalidates_old_result_without_location_or_network() -> None:
    result = _run("""
await requestAuthorizedRainfallTrend();
const before = {calls: calls.length, geoCalls};
changeTarget("cp102");
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  before, after: {calls: calls.length, geoCalls}, posture: weatherDecisionReadiness(snapshot()), viewUpdates}));
""")
    assert result["before"] == result["after"]
    assert result["weather"]["routeTrend"] is None
    assert result["weather"]["decision"] is None
    assert result["location"]["status"] == "pending"
    assert "CP 102" in result["location"]["text"]
    assert "以目前位置重算降雨趨勢" in result["location"]["text"]
    assert result["posture"]["label"] == "UNVERIFIED"
    assert result["viewUpdates"] >= 3


def test_target_updates_do_not_rebuild_the_map_or_leave_a_stale_action() -> None:
    result = _run("""
changeTarget("cp103");
const pending = {posture: postureLabel.textContent, action: actionLabel.textContent};
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({pending, renders, viewUpdates, evidenceMarkup,
  posture: postureLabel.textContent, action: actionLabel.textContent}));
""")
    assert result["renders"] == 0
    assert result["viewUpdates"] >= 3
    assert result["pending"]["posture"] == "UNVERIFIED"
    assert "GO" not in result["pending"]["action"]
    assert result["posture"] == "CHANGE PLAN"
    assert result["action"] == "CHANGE_PLAN candidate"
    assert 'data-weather-decision-target="cp103"' in result["evidenceMarkup"]
    assert "iframe" not in result["evidenceMarkup"]


def test_target_refresh_updates_provenance_and_drops_stale_arrival_estimate() -> None:
    result = _run("""
state.weatherData = {...state.weatherData, status: "stale_data",
  routeTrend: {status: "stale_data"},
  routeRisk: {imageryFeatures: {estimatedRainArrivalMinutes: 12}}};
refreshWeatherTargetView();
console.log(JSON.stringify({provenanceMarkup, criticalWindow: criticalWindowLabel.textContent, renders}));
""")
    assert result["provenanceMarkup"] == "stale_data"
    assert "過期估計" in result["criticalWindow"]
    assert "12 min" not in result["criticalWindow"]
    assert result["renders"] == 0


@pytest.mark.parametrize("old_outcome", ["success", "failure"])
def test_slow_cp102_response_cannot_overwrite_cp103(old_outcome: str) -> None:
    result = _run("""
const old = deferred();
postHandler = async (path, body) => path.endsWith("rainfall-location-approvals") ? approval
  : body.targetPosition.id === "cp102" ? old.promise : responseFor("cp103");
changeTarget("cp102");
const pending = requestAuthorizedRainfallTrend();
await tick();
changeTarget("cp103");
await requestAuthorizedRainfallTrend();
""" + ("old.resolve(responseFor('cp102'));" if old_outcome == "success" else "old.reject(new Error('late failure'));") + """
await pending;
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus}));
""")
    assert result["weather"]["decisionReview"]["targetId"] == "cp103"
    assert result["weather"]["decision"]["summary"] == "reviewed cp103"
    assert result["location"]["status"] == "ready"
    assert "CP 102" not in result["location"]["text"]


def test_later_request_for_same_target_wins() -> None:
    result = _run("""
const old = deferred(); let count = 0;
postHandler = async path => path.endsWith("rainfall-location-approvals") ? approval
  : ++count === 1 ? old.promise : responseFor("cp103");
const pending = requestAuthorizedRainfallTrend(); await tick();
await requestAuthorizedRainfallTrend();
const stale = responseFor("cp103"); stale.weatherDashboard.decision.summary = "obsolete";
old.resolve(stale); await pending;
console.log(JSON.stringify(state.weatherData.decision));
""")
    assert result["summary"] == "reviewed cp103"


@pytest.mark.parametrize("change", ['project = "beta";', 'base = "https://other.invalid";'])
def test_old_project_or_api_result_is_discarded(change: str) -> None:
    result = _run("""
const old = deferred();
postHandler = async path => path.endsWith("rainfall-location-approvals") ? approval : old.promise;
const pending = requestAuthorizedRainfallTrend(); await tick();
""" + change + """
state.weatherData = {marker: "new-scope"};
state.weatherLocationTrendStatus = {marker: "new-scope"};
old.resolve(responseFor("cp103")); await pending;
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus}));
""")
    assert result == {"weather": {"marker": "new-scope"}, "location": {"marker": "new-scope"}}


@pytest.mark.parametrize("stage", ["position", "approval"])
def test_target_change_stops_later_steps_of_pending_location_flow(stage: str) -> None:
    result = _run("""
const old = deferred();
""" + ("browserCurrentPosition = () => {geoCalls++; return old.promise;};" if stage == "position"
        else "postHandler = () => old.promise;") + """
const pending = requestAuthorizedRainfallTrend(); await tick();
changeTarget("cp102");
old.resolve(""" + ("position" if stage == "position" else "approval") + """); await pending;
console.log(JSON.stringify({paths: calls.map(item => item.path), location: state.weatherLocationTrendStatus}));
""")
    assert len(result["paths"]) == (0 if stage == "position" else 1)
    assert not any(path.endswith("/rainfall-trend") for path in result["paths"])
    assert result["location"]["status"] == "pending"


@pytest.mark.parametrize("stage", ["position", "approval", "trend"])
def test_sampling_failures_clear_old_decisions(stage: str) -> None:
    result = _run("""
""" + ("browserCurrentPosition = async () => {throw new Error('permission denied');};" if stage == "position"
        else "postHandler = async path => {if (path.endsWith('rainfall-location-approvals') && "
        + ("false" if stage == "approval" else "true")
        + ") return approval; throw new Error('sampling unavailable');};") + """
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  posture: weatherDecisionReadiness(snapshot())}));
""")
    assert result["location"]["status"] == "error"
    assert result["weather"]["decision"] is None
    assert result["weather"]["routeTrend"] is None
    assert result["weather"]["decisionReview"]["status"] == "failed"
    assert result["posture"]["label"] == "UNAVAILABLE"


def test_explicit_failed_reassessment_retains_trend_but_not_old_go() -> None:
    result = _run("""
postHandler = async path => {
  if (path.endsWith("rainfall-location-approvals")) return approval;
  const response = responseFor("cp103"); response.weatherDashboard = null;
  response.decisionReview = {...response.decisionReview, status: "failed", errorCode: "risk_unavailable"};
  return response;
};
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  posture: weatherDecisionReadiness(snapshot())}));
""")
    assert result["weather"]["routeTrend"]["target"]["id"] == "cp103"
    assert result["weather"]["decision"] is None
    assert result["posture"]["label"] == "UNAVAILABLE"
    assert "重審失敗" in result["location"]["text"]
    assert "Decision API 已重審" not in result["location"]["text"]


@pytest.mark.parametrize("tamper", [
    'response.decisionReview.projectId = "beta";',
    'response.decisionReview.targetId = "cp102";',
    'response.weatherDashboard.routeTrend.target.id = "cp102";',
    'response.weatherDashboard.projectId = "beta";',
    'response.decisionReview.evaluatedAt = "not-a-time";',
    'response.weatherDashboard.evaluatedAt = "2026-09-04T09:00:00+08:00";',
    'response.decisionReview.rainfallPairId = "different-generation";',
    'response.weatherDashboard.decision = null;',
])
def test_mismatched_reassessment_is_not_accepted(tamper: str) -> None:
    result = _run("""
postHandler = async path => {
  if (path.endsWith("rainfall-location-approvals")) return approval;
  const response = clone(responseFor("cp103"));
""" + tamper + """
  return response;
};
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify(state.weatherData));
""")
    assert result["decision"] is None
    assert result["decisionReview"]["status"] != "reevaluated"


def test_cache_reload_invalidates_pending_target_and_resets_location_context() -> None:
    result = _run("""
const old = deferred();
postHandler = async path => path.endsWith("rainfall-location-approvals") ? approval : old.promise;
const pending = requestAuthorizedRainfallTrend(); await tick();
await loadWeatherData();
old.resolve(responseFor("cp103")); await pending;
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  selection: state.weatherTargetCheckpointId}));
""")
    assert result["weather"]["decision"]["summary"] == "route cache"
    assert result["weather"]["decisionReview"].get("targetId") is None
    assert result["location"]["status"] == "idle"
    assert "路線快取" in result["location"]["text"]
    assert "已重算" not in result["location"]["text"]
    assert result["selection"] == ""


def test_older_cache_read_cannot_replace_a_new_target_decision() -> None:
    result = _run("""
const old = deferred();
fetchHandler = async path => path.endsWith("connected-preparation") ? state.connectedPreparation : old.promise;
const pending = loadWeatherData(); await tick();
changeTarget("cp103"); await requestAuthorizedRainfallTrend();
old.resolve(routeDashboard); await pending;
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus}));
""")
    assert result["weather"]["decision"]["summary"] == "reviewed cp103"
    assert result["weather"]["decisionReview"]["targetId"] == "cp103"
    assert result["location"]["status"] == "ready"


def test_cache_reload_after_sampling_explicitly_replaces_the_cp_context() -> None:
    result = _run("""
await requestAuthorizedRainfallTrend(); await loadWeatherData();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  selection: state.weatherTargetCheckpointId}));
""")
    assert result["weather"]["decision"]["summary"] == "route cache"
    assert result["weather"]["routeTrend"]["target"]["status"] == "not_provided"
    assert result["selection"] == ""
    assert result["location"]["status"] == "idle"
    assert "路線快取" in result["location"]["text"]


def test_target_change_alone_invalidates_an_older_cache_read() -> None:
    result = _run("""
const old = deferred();
fetchHandler = async path => path.endsWith("connected-preparation") ? state.connectedPreparation : old.promise;
const pending = loadWeatherData(); await tick();
changeTarget("cp103");
const before = calls.length;
old.resolve(routeDashboard); await pending;
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  geoCalls, additionalCalls: calls.length - before}));
""")
    assert result["weather"]["decision"] is None
    assert result["weather"]["routeTrend"] is None
    assert result["location"]["status"] == "pending"
    assert result["location"]["targetId"] == "cp103"
    assert result["geoCalls"] == result["additionalCalls"] == 0


@pytest.mark.parametrize("initial_status", ["idle", "loading"])
def test_pending_target_does_not_keep_an_invalidated_loading_posture(initial_status: str) -> None:
    result = _run("""
state.weatherData.status = """ + json.dumps(initial_status) + """;
changeTarget("cp103");
console.log(JSON.stringify({location: state.weatherLocationTrendStatus, posture: postureLabel.textContent}));
""")
    assert result["location"]["status"] == "pending"
    assert result["posture"] == "UNVERIFIED"


def test_missing_target_does_not_request_location() -> None:
    result = _run("""
state.project.checkpoints = [];
await requestAuthorizedRainfallTrend();
console.log(JSON.stringify({weather: state.weatherData, location: state.weatherLocationTrendStatus,
  geoCalls, count: calls.length}));
""")
    assert result["weather"]["decision"] is None
    assert result["weather"]["decisionReview"]["status"] == "unverified"
    assert result["location"]["status"] == "error"
    assert result["geoCalls"] == result["count"] == 0


@pytest.mark.parametrize("status, explanation", [("missing_cell", "格點缺值"), ("outside_grid", "無格點覆蓋")])
def test_unknown_is_explained_and_qpe_qpf_have_separate_times_and_windows(status: str, explanation: str) -> None:
    result = _run("""
const trend = sampledTrend("cp103");
trend.target.status = """ + json.dumps(status) + """;
console.log(JSON.stringify({text: weatherRainfallTrendResultText({label: "CP 103", id: "cp103"}, trend)}));
""")
    text = result["text"]
    assert "0.0" in text
    assert "UNKNOWN" in text
    assert explanation in text
    assert status in text
    assert "不等於 0" in text
    for marker in ("past1hQpe", "next1hQpf", "QPE", "QPF", "08:30:00", "09:30:00", "09:40:00", "10:40:00"):
        assert marker in text
    assert "未下載新 CWA" in text
    assert "座標未保存" in text
