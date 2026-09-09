"""Execute shipped shared-identity/Pace renderers with isolated VM data, not browser QA."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


PAGE = Path(__file__).resolve().parents[1] / "docs/admin/scout-dashboard-v0.1.html"


def _run(probe):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for isolated Dashboard tests")
    page = PAGE.read_text()
    names = ("selectedAnalysisSubject", "renderAnalysisSubject", "renderAdoptedPaceSchedule",
             "loadAnalysisSubject", "refreshSixAxisAfterBaselineChange", "applyAnalysisSubjectTruth")
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", page)
        assert match, name
        functions.append(match.group(0))
    setup = r'''
const assert = require("node:assert/strict");
let project = "analysis-a";
const resolvedPretripProjectId = () => project;
const escapeHtml = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;");
const asArray = value => Array.isArray(value) ? value : [];
const PRETRIP_PROJECT_FETCH_TIMEOUT_MS = 60000;
const roles = ["route_context", "pace_fit", "permission", "architecture", "weather", "navigation"];
const subject = {project_id: project, subject_id: "golden.abc", analysis_revision: "r1".repeat(32),
  geometry_fingerprint: "g".repeat(64), timing_fingerprint: "t".repeat(64), timezone: "Asia/Taipei",
  selected_baseline_sha256: "b".repeat(64), schedule_status: "adopted",
  schedule_time_role: "historical_reconstruction", sources: {golden_geometry: {sha256: "a".repeat(64), status: "available", ref: "golden.gpx"}},
  dependencies: Object.fromEntries(roles.map(role => [role, {status: role === "weather" ? "separate_current_context" : "adopted", time_role: role === "weather" ? "目前預報；歷史天候未知" : "採用日程"}])),
  mission_day_estimates: [{mission_day_id: "D1", reference_replay: {source_day_id: "historical.001", departure_clock: "06:00:00", arrival_clock: "16:00:00", elapsed_minutes: 600,
    rest_stops: [{label: "derived stay", duration_minutes: 25, start_clock: "07:00:00", end_clock: "07:25:00"}], checkpoint_windows: [{anchor_id:"cp.001",arrival_clock:"08:32:00",status:"exact"},{anchor_id:"cp.002",status:"unknown"}], unknown_ranges:[{reason:"missing_timestamp"}]}},
  {mission_day_id:"D2",reference_replay:{departure_clock:"06:00:00",arrival_clock:"12:00:00",elapsed_minutes:360,rest_stops:[],checkpoint_windows:[],unknown_ranges:[]}}],
  overnight_gaps: [{duration_minutes:840}], unknown_ranges: [{reason:"missing_timestamp"}], issues: []};
const state = {route: "outdoor-permission", analysisSubject: subject, analysisSubjectStatus: "ready"};
const scopes = ["analysis_subject", "project", "briefing", "permission", "weather", "navigation_terrain", "qgis_spatial"];
const loadedDataScopes = new Set(scopes);
const dataScopePromises = new Map();
let payload = subject;
let reads = [], refreshes = 0;
const fetchFirstPretripJson = async factory => { reads.push(factory(project)); return payload; };
const refreshCurrentDataView = () => { refreshes += 1; };
let reloads = [];
const loadDataForRoute = async (route, options) => { reloads.push({route, options, loaded: [...loadedDataScopes]}); };
'''
    source = setup + "\n".join(functions) + "\n(async () => {" + probe + "})().then(value => process.stdout.write(JSON.stringify(value)));"
    result = subprocess.run([node, "-e", source], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_all_six_headers_expose_one_revision_and_explicit_weather_role():
    result = _run(r'''
const html = roles.map(role => renderAnalysisSubject("outdoor-" + role.replaceAll("_", "-")));
for (const page of html) {
  assert.ok(page.includes('data-analysis-project="analysis-a"'));
  assert.ok(page.includes('data-analysis-revision="' + subject.analysis_revision + '"'));
  assert.ok(page.includes(subject.selected_baseline_sha256));
}
assert.ok(html[4].includes("歷史天候未知"));
subject.dependencies.navigation.reason = '<script>retained</script>';
assert.ok(renderAnalysisSubject("outdoor-navigation").includes('&lt;script>retained&lt;/script>'));
return {headers: html.length};
''')
    assert result["headers"] == 6


def test_adopted_pace_preserves_long_days_stops_clocks_and_unknowns():
    result = _run(r'''
const html = renderAdoptedPaceSchedule();
assert.ok(html.includes('data-pace-mission-day="D1"'));
assert.ok(html.includes('data-pace-mission-day="D2"'));
for (const value of ["600.0 分", "360.0 分", "25.0 分", "08:32:00", "cp.002", "missing_timestamp"]) assert.ok(html.includes(value), value);
assert.equal((html.match(/data-pace-mission-day=/g) || []).length, 2);
subject.schedule_status = "stale";
assert.ok(!renderAdoptedPaceSchedule().includes("600.0 分"));
project = "analysis-b";
assert.ok(!renderAnalysisSubject("outdoor-pace-fit").includes(subject.analysis_revision));
return {days: 2, stale_hidden: true, other_workspace_hidden: true};
''')
    assert result == {"days": 2, "stale_hidden": True, "other_workspace_hidden": True}


def test_changed_revision_waits_for_old_reads_then_invalidates_every_dependent_scope():
    result = _run(r'''
let complete;
dataScopePromises.set("project", new Promise(resolve => { complete = () => { loadedDataScopes.add("project"); resolve(); }; }));
payload = {...subject, analysis_revision: "r2".repeat(32)};
const pending = loadAnalysisSubject();
await Promise.resolve();
complete();
await pending;
for (const scope of scopes.filter(scope => scope !== "analysis_subject")) assert.ok(!loadedDataScopes.has(scope), scope);
assert.equal(state.analysisSubject.analysis_revision, payload.analysis_revision);
assert.equal(reads[0], "/admin/pretrip/projects/analysis-a/analysis-subject");
return {invalidated: scopes.length - 1};
''')
    assert result["invalidated"] == 6


def test_post_accept_refresh_invalidates_all_six_views_and_is_project_guarded():
    result = _run(r'''
await refreshSixAxisAfterBaselineChange();
assert.deepEqual(reloads, [{route:"outdoor-permission",options:{force:true},loaded:[]}]);
assert.equal(state.analysisSubject, null);
for (const scope of scopes) loadedDataScopes.add(scope);
let complete;
dataScopePromises.set("project", new Promise(resolve => { complete = resolve; }));
const pending = refreshSixAxisAfterBaselineChange();
project = "analysis-b";
complete(); await pending;
assert.equal(reloads.length, 1);
assert.equal(loadedDataScopes.size, scopes.length);
return {refreshes: reloads.length, foreign_project_untouched: true};
''')
    assert result == {"refreshes": 1, "foreign_project_untouched": True}


def test_retained_projection_cannot_keep_a_current_analysis_truth_label():
    result = _run(r'''
const existing = {surface:"Operational",mode:"Candidate analysis",verification:"Old prepared evidence"};
subject.dependencies.navigation = {status:"stale_or_unverified",reason:"Golden changed"};
const navigation = applyAnalysisSubjectTruth(existing,"outdoor-navigation");
assert.equal(navigation.surface,"Sources need review");
assert.equal(navigation.mode,"Retained evidence");
assert.equal(navigation.verification,"Golden changed");
const pace = applyAnalysisSubjectTruth(existing,"outdoor-pace-fit");
assert.ok(pace.data.includes("2 adopted days"));
assert.equal(pace.surface,"Historical pace analysis");
return {retained_labelled:true,adopted_pace_labelled:true};
''')
    assert result == {"retained_labelled": True, "adopted_pace_labelled": True}
