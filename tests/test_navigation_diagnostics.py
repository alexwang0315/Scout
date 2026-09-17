from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
NAVIGATION_CASE_IDS = tuple(f"DASH-{number:03d}" for number in range(39, 44))
NAVIGATION_BATCH_IDS = ("DASH-025", "DASH-038", *NAVIGATION_CASE_IDS)
PURE_VALIDATORS = (
    "diagnosticNavigationValidateWorker",
    "diagnosticNavigationValidateHypothesis",
    "diagnosticNavigationValidateScope",
    "diagnosticNavigationReviewReadiness",
    "diagnosticNavigationValidateR4Explanation",
)


def _function(html: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^    (?:async )?function {re.escape(name)}\(.*?^    \}}",
        html,
    )
    assert match, f"Dashboard function {name} is missing"
    return match.group(0)


def _array_constant(html: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^    const {re.escape(name)} = (?:Object\.freeze\()?\[.*?^    \](?:\))?;", html,
    )
    assert match, f"Dashboard array {name} is missing"
    return match.group(0)


def _run_node(source: str, probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the Navigation JavaScript contract tests")
    program = "\n".join(
        (
            '"use strict";',
            'const assert = require("node:assert/strict");',
            source,
            "(async () => {",
            probe,
            "})().catch(error => { console.error(error); process.exitCode = 1; });",
        )
    )
    result = subprocess.run(
        [node], input=program, text=True, capture_output=True, check=False,
        cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


# A detached event fixture: selectors and bubbling work independently of the binder.
DOM_FIXTURE = r"""
class FixtureElement {
  constructor(tagName, attributes = {}, children = []) {
    this.tagName = tagName.toUpperCase();
    this.attributes = {};
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.parentElement = null;
    for (const [key, value] of Object.entries(attributes)) this.setAttribute(key, value);
    children.forEach(child => this.appendChild(child));
  }
  dataKey(name) { return name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()); }
  setAttribute(name, value) {
    if (name.startsWith("data-")) this.dataset[this.dataKey(name)] = String(value);
    else this.attributes[name] = String(value);
  }
  getAttribute(name) {
    return (name.startsWith("data-") ? this.dataset[this.dataKey(name)] : this.attributes[name]) ?? null;
  }
  matches(selector) {
    return selector.split(",").some(part => {
      const descendant = part.trim().match(/^(.*)\s+([a-z][\w-]*)$/i);
      if (descendant) return this.matches(descendant[2]) && Boolean(this.parentElement?.closest(descendant[1]));
      const exclusions = [...part.matchAll(/:not\(([^()]*)\)/g)].map(match => match[1]);
      const positive = part.replace(/:not\([^()]*\)/g, "").trim();
      const tag = positive.match(/^[a-z][\w-]*/i)?.[0];
      const attributes = [...positive.matchAll(/\[([\w-]+)(?:=['"]?([^\]'"]*)['"]?)?\]/g)];
      return (!tag || this.tagName === tag.toUpperCase())
        && attributes.every(([, name, value]) => value === undefined
          ? this.getAttribute(name) !== null : this.getAttribute(name) === value)
        && exclusions.every(exclusion => !this.matches(exclusion));
    });
  }
  appendChild(child) { child.parentElement = this; this.children.push(child); return child; }
  contains(target) {
    for (let node = target; node; node = node.parentElement) if (node === this) return true;
    return false;
  }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node;
    return null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(listener);
  }
  dispatchEvent(event) {
    event.target = this;
    event.defaultPrevented = false;
    event.preventDefault = () => { event.defaultPrevented = true; };
    event.stopPropagation = () => { event.stopped = true; };
    for (let node = this; node; node = event.bubbles === false ? null : node.parentElement) {
      event.currentTarget = node;
      for (const listener of node.listeners.get(event.type) || []) listener.call(node, event);
      if (event.stopped) break;
    }
    return !event.defaultPrevented;
  }
  click() { if (this.getAttribute("disabled") === null) this.dispatchEvent({type: "click", bubbles: true}); }
  scrollIntoView(options) { this.lastScroll = options; }
}
const element = (tag, attributes = {}, children = []) => new FixtureElement(tag, attributes, children);
function guidanceFixture() {
  const content = element("strong");
  const copy = element("div", {
    "data-terrain-guidance-focus-evidence": "G1", role: "button", tabindex: "0",
    "aria-disabled": "false",
  }, [content]);
  const summaryText = element("small");
  const summary = element("div", {"data-terrain-guidance-dem-summary": "G1"}, [summaryText]);
  const previewText = element("path");
  const preview = element("svg", {"data-terrain-guidance-dem-preview": "G1"}, [previewText]);
  const focus = element("button", {"data-terrain-guidance-focus-constraint": "G1"}, [element("span")]);
  const article = element("article", {"data-terrain-guidance-constraint": "G1"}, [copy, summary, preview, focus]);
  const copy2 = element("div", {"data-terrain-guidance-focus-evidence": "G2", role: "button", tabindex: "0"});
  const article2 = element("article", {"data-terrain-guidance-constraint": "G2"}, [copy2]);
  const previous = element("button", {"data-terrain-guidance-focus-step": "previous"});
  const next = element("button", {"data-terrain-guidance-focus-step": "next"});
  const clear = element("button", {"data-terrain-guidance-focus-clear": "true"});
  const root = element("section", {}, [previous, next, clear, article, article2]);
  return {root, article, article2, copy, copy2, content, summary, summaryText, preview, previewText, focus, previous, next, clear};
}
const calls = [];
const actions = {
  focus: (...args) => calls.push(["focus", ...args]),
  step: (...args) => calls.push(["step", ...args]),
};
"""


@pytest.fixture(scope="module")
def html() -> str:
    return PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def binder_source(html: str) -> str:
    return DOM_FIXTURE + _function(html, "bindTerrainRouteGuidanceFocusControls")


@pytest.mark.parametrize(
    "target", ("article", "copy", "content", "summary", "summaryText", "preview", "previewText"),
)
def test_guidance_evidence_click_focuses_its_constraint_once(binder_source: str, target: str) -> None:
    payload = _run_node(binder_source, f"""
const fixture = guidanceFixture();
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
fixture[{json.dumps(target)}].click();
fixture.copy2.click();
process.stdout.write(JSON.stringify({{calls}}));
""")
    assert payload["calls"] == [["focus", "G1"], ["focus", "G2"]]


@pytest.mark.parametrize("key", ("Enter", " ", "Spacebar"))
def test_guidance_evidence_keyboard_focuses_and_prevents_scroll(binder_source: str, key: str) -> None:
    payload = _run_node(binder_source, f"""
const fixture = guidanceFixture();
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
const event = {{type: "keydown", key: {json.dumps(key)}, bubbles: true}};
fixture.copy.dispatchEvent(event);
process.stdout.write(JSON.stringify({{calls, prevented: event.defaultPrevented}}));
""")
    assert payload == {"calls": [["focus", "G1"]], "prevented": True}


def test_guidance_unrelated_and_descendant_keys_do_not_focus(binder_source: str) -> None:
    payload = _run_node(binder_source, """
const fixture = guidanceFixture();
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
const events = [];
for (const [target, key] of [[fixture.copy, "Tab"], [fixture.copy, "Escape"], [fixture.content, "Enter"]]) {
  const event = {type: "keydown", key, bubbles: true};
  target.dispatchEvent(event);
  events.push(event.defaultPrevented);
}
process.stdout.write(JSON.stringify({calls, events}));
""")
    assert payload == {"calls": [], "events": [False, False, False]}


@pytest.mark.parametrize(
    ("tag", "attributes"),
    (
        ("input", {"type": "checkbox"}),
        ("label", {}),
        ("button", {}),
        ("a", {"href": "#evidence-source"}),
        ("select", {}),
        ("textarea", {}),
        ("div", {"contenteditable": "true"}),
        ("div", {"contenteditable": ""}),
        ("div", {"contenteditable": "plaintext-only"}),
        ("div", {"role": "button"}),
    ),
)
def test_guidance_interactive_descendants_keep_their_own_actions(
    binder_source: str, tag: str, attributes: dict,
) -> None:
    payload = _run_node(binder_source, f"""
const fixture = guidanceFixture();
const child = element("span");
const control = element({json.dumps(tag)}, {json.dumps(attributes)}, [child]);
fixture.copy.appendChild(control);
let ownClicks = 0;
control.addEventListener("click", () => {{ ownClicks += 1; }});
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
control.click();
child.click();
const keyboard = {{type: "keydown", key: " ", bubbles: true}};
control.dispatchEvent(keyboard);
process.stdout.write(JSON.stringify({{calls, ownClicks, prevented: keyboard.defaultPrevented}}));
""")
    assert payload == {"calls": [], "ownClicks": 2, "prevented": False}


def test_guidance_noneditable_content_still_focuses(binder_source: str) -> None:
    payload = _run_node(binder_source, """
const fixture = guidanceFixture();
const child = fixture.copy.appendChild(element("span", {contenteditable: "false"}));
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
child.click();
process.stdout.write(JSON.stringify({calls}));
""")
    assert payload["calls"] == [["focus", "G1"]]


def test_guidance_busy_evidence_is_inert(binder_source: str) -> None:
    payload = _run_node(binder_source, """
const fixture = guidanceFixture();
fixture.copy.setAttribute("aria-disabled", "true");
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
fixture.content.click();
fixture.summaryText.click();
fixture.previewText.click();
fixture.copy.dispatchEvent({type: "keydown", key: "Enter", bubbles: true});
process.stdout.write(JSON.stringify({calls}));
""")
    assert payload["calls"] == []


def test_guidance_binding_is_idempotent_and_scoped_to_the_root(binder_source: str) -> None:
    payload = _run_node(binder_source, """
const fixture = guidanceFixture();
const outside = guidanceFixture();
element("main", {}, [fixture.root, outside.root]);
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
bindTerrainRouteGuidanceFocusControls(fixture.root, actions);
fixture.focus.children[0].click();
fixture.previous.click();
fixture.next.click();
fixture.clear.click();
fixture.copy.click();
fixture.copy.dispatchEvent({type: "keydown", key: "Enter", bubbles: true});
outside.copy.click();
outside.focus.click();
process.stdout.write(JSON.stringify({calls}));
""")
    assert payload["calls"] == [
        ["focus", "G1"], ["step", "previous"], ["step", "next"],
        ["focus", ""], ["focus", "G1"], ["focus", "G1"],
    ]


def test_guidance_default_actions_preserve_selection_and_delegate_fit(html: str) -> None:
    source = DOM_FIXTURE + "\n".join(
        _function(html, name)
        for name in (
            "bindTerrainRouteGuidanceFocusControls",
            "setTerrainRouteGuidanceConstraintFocus",
            "stepTerrainRouteGuidanceConstraintFocus",
            "terrainRouteGuidanceSteppedConstraintId",
        )
    )
    payload = _run_node(source, """
const fixture = guidanceFixture();
global.document = fixture.root;
const selected = Object.freeze({G1: Object.freeze(["F1"])});
const anchors = Object.freeze({G2: Object.freeze({x: 121, y: 24})});
global.state = {terrainRouteGuidanceFocusConstraintId: ""};
Object.defineProperties(state, {
  terrainRouteGuidanceSelectedFeatures: {value: selected},
  terrainRouteGuidanceManualAnchors: {value: anchors},
  terrainRouteGuidanceAnchorTarget: {value: "G2"},
});
global.terrainRouteGuidanceConstraintIds = () => ["G1", "G2"];
global.terrainRouteGuidancePlan = () => ({guidance_id: "guidance-fixture"});
global.terrainRouteGuidanceFocusedConstraintId = () => state.terrainRouteGuidanceFocusConstraintId;
global.updateTerrainRouteGuidanceFocusPresentation = () => {};
global.cssEscape = value => value;
global.refreshTerrainRouteGuidanceMapFocus = fit => calls.push([state.terrainRouteGuidanceFocusConstraintId, fit]);
bindTerrainRouteGuidanceFocusControls();
fixture.copy2.click();
fixture.previous.click();
fixture.next.click();
fixture.clear.click();
fixture.previous.click();
fixture.next.click();
assert.equal(state.terrainRouteGuidanceSelectedFeatures, selected);
assert.equal(state.terrainRouteGuidanceManualAnchors, anchors);
assert.equal(state.terrainRouteGuidanceAnchorTarget, "G2");
process.stdout.write(JSON.stringify({calls, guidanceId: state.terrainRouteGuidanceFocusGuidanceId}));
""")
    assert payload == {
        "calls": [["G2", True], ["G1", True], ["G2", True], ["", True], ["G2", True], ["G1", True]],
        "guidanceId": "guidance-fixture",
    }


def test_guidance_evidence_markup_is_keyboard_accessible_and_binder_is_used(html: str) -> None:
    workbench = _function(html, "renderTerrainRouteGuidanceWorkbench")
    evidence = re.search(r"<div\b[^>]*\bdata-terrain-guidance-focus-evidence=[^>]*>", workbench)
    assert evidence, "Guidance evidence copy needs an explicit activation target"
    assert 'role="button"' in evidence.group(0)
    assert 'tabindex="0"' in evidence.group(0)
    assert "bindTerrainRouteGuidanceFocusControls(" in _function(html, "bindQgisSpatialControls")


def test_navigation_diagnostics_register_50_unique_cases_with_executable_handlers(html: str) -> None:
    cases = _array_constant(html, "DASHBOARD_DIAGNOSTIC_CASES")
    stubs = "\n".join(
        f"const diagnosticCheck{number:03d} = () => 'DASH-{number:03d}';"
        for number in range(1, 51)
    )
    # D037 has an existing indirection for its live runner. Exercise the
    # registry callback with that dependency stubbed, without running maps.
    stubs += "\nconst diagnosticCheck037Runner = diagnosticCheck037;"
    payload = _run_node(stubs + "\n" + cases, """
const cases = DASHBOARD_DIAGNOSTIC_CASES.map(({id, category, title, description, run}) => ({
  id, category, title, description, callable: typeof run === "function",
  result: typeof run === "function" ? run() : null,
}));
process.stdout.write(JSON.stringify({cases}));
""")
    cases_by_id = {case["id"]: case for case in payload["cases"]}
    assert len(payload["cases"]) == len(cases_by_id) == 50
    assert set(cases_by_id) == {f"DASH-{number:03d}" for number in range(1, 51)}
    for case_id, case in cases_by_id.items():
        assert case["callable"] and case["result"] == case_id
        assert all(case[key].strip() for key in ("category", "title", "description"))
        _function(html, f"diagnosticCheck{case_id[-3:]}")


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('id: "DASH-050"', 'id: "DASH-051"'),
        ('id: "DASH-050"', 'id: "DASH-049"'),
        ("run: diagnosticCheck050", "run: undefined"),
        ("run: diagnosticCheck050", "run: diagnosticCheck049"),
    ],
    ids=("unknown-id", "duplicate-id", "missing-handler", "miswired-handler"),
)
def test_diagnostic_registry_rejects_incomplete_or_invalid_registration(
    html: str, original: str, replacement: str,
) -> None:
    cases = _array_constant(html, "DASHBOARD_DIAGNOSTIC_CASES")
    assert cases.count(original) == 1
    damaged = html.replace(cases, cases.replace(original, replacement, 1), 1)
    with pytest.raises(AssertionError):
        test_navigation_diagnostics_register_50_unique_cases_with_executable_handlers(damaged)


@pytest.mark.parametrize(
    "name",
    (*PURE_VALIDATORS, *(f"diagnosticCheck{number:03d}" for number in range(39, 44)),
     "runNavigationDashboardDiagnostics"),
)
def test_navigation_diagnostics_do_not_issue_mutating_requests(html: str, name: str) -> None:
    source = _function(html, name)
    assert not re.search(r"\bpostJson\s*\(", source), name
    assert not re.search(r"\bmethod\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"]", source, re.I), name
    if name in PURE_VALIDATORS:
        assert not re.search(r"\b(?:fetch|fetchJson|diagnosticJson|diagnosticEnvelope)\s*\(", source), name


def test_diagnostic_json_uses_get_retries_failed_reads_and_shares_successful_reads(html: str) -> None:
    source = "\n".join(
        _function(html, name) for name in ("fetchJson", "diagnosticResource", "diagnosticJson")
    )
    payload = _run_node(source, """
global.window = {setTimeout, clearTimeout};
global.apiBase = () => "http://navigation-fixture.invalid";
global.FETCH_TIMEOUT_MS = 1000;
global.diagnosticResourceCache = new Map();
const requests = [];
global.fetch = async (url, options = {}) => {
  requests.push({url, method: options.method || "GET", body: options.body ?? null});
  const ok = requests.length > 1;
  return {ok, status: ok ? 200 : 503, json: async () => ({status: "unavailable", reachable: false})};
};
const path = "/admin/pretrip/projects/navigation-fixture/spatial/qgis/status";
await assert.rejects(diagnosticJson(path), /503/);
const [first, second] = await Promise.all([diagnosticJson(path), diagnosticJson(path)]);
assert.equal(first, second);
process.stdout.write(JSON.stringify({requests, payload: first}));
""")
    assert payload["requests"] == [
        {
            "url": "http://navigation-fixture.invalid/admin/pretrip/projects/navigation-fixture/spatial/qgis/status",
            "method": "GET", "body": None,
        },
        {
            "url": "http://navigation-fixture.invalid/admin/pretrip/projects/navigation-fixture/spatial/qgis/status",
            "method": "GET", "body": None,
        },
    ]
    assert payload["payload"] == {"status": "unavailable", "reachable": False}


NAVIGATION_EVIDENCE_FIXTURE = r"""
function navigationEvidenceFixture() {
  const hash = character => character.repeat(64);
  const point = (x, y) => ({x, y, crs: "EPSG:4326"});
  const boundary = {authority: "candidate_only", source_type: "terrain_hypothesis",
    candidate_only: true, runtime_safety_truth: false, operational: false,
    safe_or_walkable: "not_determined", promotion_allowed: false};
  const context = {project_id: "navigation-fixture", selection_id: "fixture-run",
    band_name: "top_10_percent_corridor"};
  const bbox = {west: 121, south: 24, east: 121.02, north: 24.02};
  const start = point(121, 24), destination = point(121.02, 24.02);
  const features = Array.from({length: 5}, (_, index) => ({
    feature_id: `F${index + 1}`, supported_constraint_ids: ["G1"],
    selection_source: "dem_derived",
    geometry: {type: "Point", coordinates: [121 + index * 0.002, 24 + index * 0.002]},
    centroid: point(121 + index * 0.002, 24 + index * 0.002), ...boundary,
  }));
  const anchorFeature = {...features[1], feature_id: "H1", selection_source: "human_map_annotation"};
  const guidance = {
    artifact_kind: "terrain_route_guidance_workspace_state", project_id: context.project_id,
    status: "reviewed", ...boundary,
    guidance_plan: {guidance_id: "guidance-fixture", ...boundary, constraints: [
      {constraint_id: "G1", kind: "ordered_anchor", landform: "saddle", required_anchor: true,
        routing_applicable: true, routing_effect: "ordered_gate"},
      {constraint_id: "G2", kind: "follow_landform", landform: "ridge", required_anchor: false,
        routing_applicable: true, routing_effect: "preference"},
    ]},
    feature_index_sha256: hash("a"), resolution_sha256: hash("b"), review_sha256: hash("c"),
    feature_index: {features: [...features, anchorFeature], dem_sha256: hash("c"), dem_resolution_m: 20,
      search_window: {route_start: start, route_destination: destination}},
    resolution: {guidance_id: "guidance-fixture", plan_sha256: hash("d"), feature_index_sha256: hash("a"), constraints: [
      {constraint_id: "G1", candidate_feature_ids: [...features.map(feature => feature.feature_id), "H1"]},
      {constraint_id: "G2", candidate_feature_ids: []},
    ]},
    review: {guidance_id: "guidance-fixture", review_id: "review-fixture", reviewed: true,
      review_status: "reviewed", plan_sha256: hash("d"), resolution_sha256: hash("b"),
      selected_anchors: [{constraint_id: "G1", feature_id: "H1"}], disabled_constraint_ids: [],
      reviewed_by: "fixture-reviewer", reviewed_at: "2026-09-03T00:00:00Z", ...boundary,
      review_decisions: [{constraint_id: "G1", human_selected_feature_id: "H1",
        selected_feature_source: "human_map_annotation", ai_map_selection_performed: false,
        decision_kind: "human_map_anchor_confirmed", selection_authority: "human_map_review"}]},
    guided_execution_ready: true,
  };
  const scope = {
    artifact_kind: "terrain_guidance_map_review_scope", status: "ready",
    project_id: context.project_id, guidance_id: "guidance-fixture", scope_id: hash("d"),
    reference_hypothesis_id: context.selection_id, band_name: context.band_name,
    dem_resolution_m: 20, saddle_path_tolerance_m: 20 * Math.sqrt(2),
    source_feature_index_sha256: hash("a"), source_resolution_sha256: hash("b"),
    endpoint_alignment: "same_ab", source_route_start: start, source_route_destination: destination,
    scope_route_start: start, scope_route_destination: destination,
    start_difference_m: 0, destination_difference_m: 0,
    corridor_reference: {hypothesis_id: context.selection_id, hypothesis_sha256: hash("e"),
      cache_key: hash("f"), band_name: context.band_name, raster_ref: "outputs/fixture-corridor.tif",
      raster_sha256: hash("a"), raster_crs: "EPSG:3826", bbox_wgs84: bbox,
      parent_manifest_ref: "outputs/fixture-parent.json", parent_manifest_sha256: hash("b"),
      dem_ref: "outputs/fixture-dem.tif", dem_sha256: hash("c"), inside_value: 1,
      outside_value: 0, nodata_value: 255, sampling_backend: "fixture-only", sampled_marker_count: 5,
      sampling_semantics: "marker_centroid_only",
      threshold_semantics: "finite_symmetric_macro_terrain_relative_cost_cell_percentile"},
    reference_paths: [{selection_id: context.selection_id, hypothesis_id: "fixture-r1", display_id: "R1",
      label: "Fixture R1", alternative_index: 1, hypothesis_run_sha256: hash("e"),
      cache_key: hash("f"), path_sha256: hash("d"), crs: "EPSG:4326", path_point_count: 3,
      distance_semantics: "minimum_marker_centroid_to_full_path_segments_m"}],
    constraints: [
      {constraint_id: "G1", total_candidate_count: 6, visible_candidate_count: 2,
        excluded_candidate_count: 4, status: "candidates", candidates: [2, 5].map(rank => ({
          feature_id: `F${rank}`, rank, centroid: features[rank - 1].centroid,
          minimum_path_distance_m: rank, inside_corridor: true,
        }))},
      {constraint_id: "G2", total_candidate_count: 0, visible_candidate_count: 0,
        excluded_candidate_count: 0, status: "unknown", candidates: []},
    ],
    candidate_only: true, runtime_safety_truth: false, operational: false,
    execution_eligible: false, routing_effect: "none",
  };
  const hypothesis = {
    status: "candidate_ready", candidate: "fixture-r1", selection_id: context.selection_id,
    boundary, display_labels: ["CANDIDATE", "TERRAIN HYPOTHESIS", "NOT A VERIFIED TRAIL"],
    start, destination, dem_resolution_m: 20, cost_model_version: "fixture-cost-v1",
    source_refs: [`outputs/spatial/qgis/fixture/${hash("f")}/terrain_route_hypothesis.json`],
    provenance: {dem_sha256: hash("c"), cache_key: hash("f"), grass_version: "8-fixture",
      weights_hash: hash("d"), cache_keys: {route_hypothesis: hash("f")}, dem_crs: "EPSG:3826",
      algorithm_version: "fixture-algorithm-v1", timestamp: "2026-09-03T00:00:00Z",
      dem_resolution_m: 20, cost_model_version: "fixture-cost-v1", modules_executed: ["r.slope.aspect", "r.walk", "r.cost", "r.path"]},
    path_model: {id: "anisotropic_walk", semantics: "minimum_anisotropic_model_cost_trace"},
    best_path: {type: "FeatureCollection", features: [1, 2, 3].map(index => ({type: "Feature",
      geometry: {type: "LineString", coordinates: [[121, 24], [121.01, 24.01], [121.02, 24.02]]},
      properties: {display_id: `R${index}`, candidate_id: `R${index}`, observed: false,
        official: false, human_verified: false, ...boundary},
    }))},
    alternatives: [1, 2, 3].map(index => ({display_id: `R${index}`, candidate: `fixture-r${index}`, ...boundary})),
    corridor: {band_model: {id: "symmetric_macro_terrain_cost",
        semantics: "finite_symmetric_macro_terrain_relative_cost_cell_percentile"},
      path_relationship: "separate_model_not_path_confidence_band",
      bands: [5, 10, 20].map(percentile => ({name: `top_${percentile}_percent_corridor`,
        cell_count: 10, max_relative_corridor_cost: percentile, default_visible: percentile === 10})),
      overlays: [5, 10, 20].map(percentile => ({mode: `top_${percentile}_percent_corridor`,
      runtime_href: `/admin/pretrip/projects/${context.project_id}/terrain-route-overlays/top_${percentile}_percent_corridor.png`,
      source_ref: `outputs/fixture-corridor-${percentile}.png`, sha256: hash("e"),
      bbox_wgs84: bbox, pixel_width: 32, pixel_height: 32, percentile, ...boundary}))},
  };
  const explanation = {status: "completed", candidate: "R4", strategy: "historical_narrative_guided",
    ...boundary, provenance: {hypothesis_ref: "outputs/spatial/qgis/fixture-r4.json", hypothesis_sha256: hash("e")},
    guidance_assessment: {status: "aligned", guided_hypothesis: true, guidance_id: "guidance-fixture",
      guidance_review_sha256: hash("c"), review_decision_count: 1, ...boundary,
      ai_map_selection_performed: false, raw_narrative_forwarded_to_worker: false,
      aligned_constraint_ids: ["G1"], conflicting_constraint_ids: [], disabled_constraint_ids: [],
      alignments: [{constraint_id: "G1", status: "aligned_within_dem_tolerance",
        distance_to_candidate_path_m: 5, dem_resolution_tolerance_m: 40,
        selection_source: "human_map_annotation", candidate_only: true, runtime_safety_truth: false}]},
  };
  return {context, guidance, scope, hypothesis, explanation};
}
function expectDiagnosticFailure(callback) {
  let failure;
  try { callback(); } catch (error) { failure = error; }
  assert.ok(failure, "Invalid or unavailable evidence must not pass");
  assert.equal(failure.constructor, Error, "Expected a diagnostic rejection, not a broken fixture");
  return failure.message;
}
"""


@pytest.fixture(scope="module")
def validator_source(html: str) -> str:
    helpers = re.findall(r"(?m)^    (?:async )?function (diagnosticNavigation\w+)\(", html)
    names = dict.fromkeys((
        "asArray", "diagnosticRequire", "diagnosticWarning", "diagnosticUnavailable", "diagnosticIsSha256",
        "navigationTerrainRouteHypothesisCandidate", *PURE_VALIDATORS, *helpers,
    ))
    return "\n".join((
        NAVIGATION_EVIDENCE_FIXTURE,
        'global.apiBase = () => "";',
        _array_constant(html, "NAVIGATION_TERRAIN_ROUTE_CORRIDOR_MODES"),
        *(_function(html, name) for name in names),
    ))


def test_navigation_worker_rejects_the_reported_live_timeout(validator_source: str) -> None:
    payload = _run_node(validator_source, """
const status = {availability: "unavailable", enabled: true, configured: true,
  reachable: false, fixture_mode: false,
  boundary: {candidate_only: true, runtime_safety_truth: false, operational: false},
  errors: [{code: "MCP_UNAVAILABLE", message: "QGIS worker status timed out."}]};
const capabilities = {workflow_allowlist: ["terrain_route_hypothesis.v1"], boundary: {...status.boundary}};
const before = JSON.stringify({status, capabilities});
const detail = expectDiagnosticFailure(() => diagnosticNavigationValidateWorker(status, capabilities));
assert.equal(JSON.stringify({status, capabilities}), before);
process.stdout.write(JSON.stringify({detail}));
""")
    assert re.search(r"unavailable|reachable|timed out|MCP_UNAVAILABLE", payload["detail"], re.I)


def test_navigation_validators_accept_bound_synthetic_evidence_without_mutation(validator_source: str) -> None:
    payload = _run_node(validator_source, """
const fixture = navigationEvidenceFixture();
const before = JSON.stringify(fixture);
global.fetch = () => assert.fail("Pure validators must not fetch");
const hypothesis = diagnosticNavigationValidateHypothesis(fixture.hypothesis, fixture.context.project_id);
const scope = diagnosticNavigationValidateScope(fixture.scope, fixture.guidance, fixture.context);
const readiness = diagnosticNavigationReviewReadiness(fixture.guidance, fixture.scope);
const explanation = diagnosticNavigationValidateR4Explanation(fixture.explanation, fixture.guidance);
assert.equal(JSON.stringify(fixture), before);
process.stdout.write(JSON.stringify({lines: hypothesis.lines.length, overlays: hypothesis.overlays.length,
  sourceRef: hypothesis.sourceRef, scope, readiness, explanation}));
""")
    assert payload["lines"] == payload["overlays"] == 3
    assert payload["sourceRef"].endswith("/terrain_route_hypothesis.json")
    assert payload["scope"] == {"visible": 2, "unknownCount": 1}
    assert payload["readiness"]["ready"] is True
    assert payload["readiness"]["detail"] and payload["explanation"]


@pytest.mark.parametrize("call", (
    "diagnosticNavigationValidateWorker(null, {})",
    "diagnosticNavigationValidateHypothesis(null, f.context.project_id)",
    "diagnosticNavigationValidateScope(null, f.guidance, f.context)",
    "diagnosticNavigationReviewReadiness(null, f.scope)",
    "diagnosticNavigationValidateR4Explanation(null, f.guidance)",
))
def test_navigation_validators_reject_absent_payloads(validator_source: str, call: str) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
const detail = expectDiagnosticFailure(() => {call});
process.stdout.write(JSON.stringify({{detail}}));
""")
    assert payload["detail"]


@pytest.mark.parametrize("mutation", (
    "f.hypothesis.status = 'unavailable'",
    "f.hypothesis.source_refs = []",
    "f.hypothesis.provenance.dem_sha256 = 'invalid'",
    "f.hypothesis.provenance.cache_keys.route_hypothesis = '0'.repeat(64)",
    "f.hypothesis.boundary.runtime_safety_truth = true",
    "f.hypothesis.best_path.features[0].geometry.coordinates[0][0] = 181",
    "f.hypothesis.best_path.features[0].properties.observed = true",
    "f.hypothesis.corridor.overlays.pop()",
    "f.hypothesis.corridor.overlays[0].runtime_href = '/admin/pretrip/projects/other/terrain-route-overlays/top_5_percent_corridor.png'",
))
def test_navigation_hypothesis_rejects_incomplete_stale_or_promoted_artifacts(
    validator_source: str, mutation: str,
) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
{mutation};
const detail = expectDiagnosticFailure(() => diagnosticNavigationValidateHypothesis(f.hypothesis, f.context.project_id));
process.stdout.write(JSON.stringify({{detail}}));
""")
    assert payload["detail"]


@pytest.mark.parametrize("mutation", (
    "f.scope.status = 'unavailable'",
    "f.scope.project_id = 'other-project'",
    "f.scope.reference_hypothesis_id = 'other-run'",
    "f.scope.band_name = 'top_5_percent_corridor'",
    "f.scope.source_feature_index_sha256 = '0'.repeat(64)",
    "f.scope.source_resolution_sha256 = '0'.repeat(64)",
    "f.scope.execution_eligible = true",
    "f.scope.routing_effect = 'ordered_gate'",
    "f.scope.constraints[0].candidates[0].inside_corridor = false",
    "f.scope.constraints[0].candidates[0].rank = 1",
    "f.scope.constraints[0].candidates[0].minimum_path_distance_m = 100",
    "f.scope.reference_paths = []",
))
def test_navigation_scope_rejects_stale_or_invalid_candidate_evidence(
    validator_source: str, mutation: str,
) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
{mutation};
const detail = expectDiagnosticFailure(() => diagnosticNavigationValidateScope(f.scope, f.guidance, f.context));
process.stdout.write(JSON.stringify({{detail}}));
""")
    assert payload["detail"]


@pytest.mark.parametrize("mutation", (
    "f.guidance.review = null",
    "f.guidance.guidance_plan = null",
    "f.guidance.resolution = null",
    "f.guidance.review.selected_anchors = []",
    "f.guidance.guided_execution_ready = false",
    "f.scope.endpoint_alignment = 'different_review_context'",
    "f.scope = null",
))
def test_navigation_r4_incomplete_review_is_not_ready(validator_source: str, mutation: str) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
{mutation};
const readiness = diagnosticNavigationReviewReadiness(f.guidance, f.scope);
process.stdout.write(JSON.stringify(readiness));
""")
    assert payload["ready"] is False
    assert payload["detail"]


@pytest.mark.parametrize("mutation", (
    "f.guidance.review.resolution_sha256 = '0'.repeat(64)",
    "f.guidance.review.selected_anchors[0].feature_id = 'F2'",
    "f.guidance.feature_index.features[5].geometry.type = 'LineString'",
    "f.guidance.review.runtime_safety_truth = true",
))
def test_navigation_r4_rejects_unbound_or_automatic_anchors(validator_source: str, mutation: str) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
{mutation};
const detail = expectDiagnosticFailure(() => diagnosticNavigationReviewReadiness(f.guidance, f.scope));
process.stdout.write(JSON.stringify({{detail}}));
""")
    assert payload["detail"]


@pytest.mark.parametrize("mutation", (
    "f.explanation.status = 'unavailable'",
    "f.explanation.candidate = 'R1'",
    "f.explanation.guidance_assessment.guidance_review_sha256 = '0'.repeat(64)",
    "f.explanation.guidance_assessment.alignments = []",
    "f.explanation.guidance_assessment.conflicting_constraint_ids = ['G1']",
    "f.explanation.guidance_assessment.ai_map_selection_performed = true",
    "f.explanation.guidance_assessment.raw_narrative_forwarded_to_worker = true",
    "f.explanation.runtime_safety_truth = true",
))
def test_navigation_r4_ready_review_cannot_replace_execution_evidence(
    validator_source: str, mutation: str,
) -> None:
    payload = _run_node(validator_source, f"""
const f = navigationEvidenceFixture();
assert.equal(diagnosticNavigationReviewReadiness(f.guidance, f.scope).ready, true);
{mutation};
const detail = expectDiagnosticFailure(() => diagnosticNavigationValidateR4Explanation(f.explanation, f.guidance));
process.stdout.write(JSON.stringify({{detail}}));
""")
    assert payload["detail"]


@pytest.mark.parametrize("review_saved", (False, True))
def test_navigation_r4_diagnostic_does_not_report_missing_execution_as_success(
    html: str, validator_source: str, review_saved: bool,
) -> None:
    source = validator_source + "\n".join(
        _function(html, name)
        for name in ("fetchJson", "diagnosticResource", "diagnosticJson", "diagnosticCheck042")
    )
    payload = _run_node(source, f"""
const f = navigationEvidenceFixture();
if (!{json.dumps(review_saved)}) f.guidance.review = null;
diagnosticNavigationGuidanceScope = async () => ({{context: f.context, guidance: f.guidance, scope: f.scope}});
global.window = {{setTimeout, clearTimeout}};
global.apiBase = () => "http://navigation-fixture.invalid";
global.diagnosticResourceCache = new Map();
const requests = [];
global.fetch = async (url, options = {{}}) => {{
  requests.push({{url, method: options.method || "GET", body: options.body ?? null}});
  return {{ok: true, status: 200, json: async () => ({{
    status: "unavailable", failure_code: "candidate_not_found", candidate_only: true,
    runtime_safety_truth: false, operational: false,
  }})}};
}};
const outcome = await diagnosticCheck042();
process.stdout.write(JSON.stringify({{outcome, requests}}));
""")
    assert payload["outcome"]["status"] == "warning"
    assert "R4" in payload["outcome"]["detail"]
    assert payload["requests"] == ([{
        "url": "http://navigation-fixture.invalid/admin/pretrip/projects/navigation-fixture/terrain-route-hypotheses/explain?candidate_id=R4",
        "method": "GET", "body": None,
    }] if review_saved else [])


def test_navigation_gn_diagnostic_runs_events_and_detects_an_unwired_binder(
    html: str, validator_source: str,
) -> None:
    source = DOM_FIXTURE + validator_source + "\n".join(
        _function(html, name) for name in (
            "bindTerrainRouteGuidanceFocusControls", "terrainRouteGuidanceSteppedConstraintId",
            "diagnosticCheck043", "diagnosticRenderWithState", "diagnosticSourceText",
            "diagnosticCompactSource", "bindQgisSpatialControls",
        )
    )
    payload = _run_node(source, """
const f = navigationEvidenceFixture();
global.state = {terrainRouteGuidance: {preserved: true}, terrainRouteGuidanceSelectedFeatures: {G1: "H1"},
  terrainRouteGuidanceManualAnchors: {G1: {x: 121, y: 24}}, terrainRouteGuidanceDisabledConstraints: {},
  qgisTerrainRouteEndpoints: {start: {x: 121, y: 24}, destination: {x: 121.02, y: 24.02}}};
const before = JSON.stringify(state);
diagnosticNavigationGuidanceScope = async () => ({context: f.context, guidance: f.guidance, scope: f.scope});
global.terrainRouteGuidanceMapScopeRequest = () => ({key: "fixture-scope"});
global.renderTerrainRouteGuidanceWorkbench = () => "detached-fixture-markup";
global.diagnosticMarkupRoot = markup => {
  assert.equal(markup, "detached-fixture-markup");
  const fixture = guidanceFixture();
  fixture.copy.appendChild(element("small"));
  fixture.article.appendChild(element("button", {"data-terrain-guidance-map-anchor": "G1"}));
  fixture.article.appendChild(element("input", {"data-terrain-guidance-disable": "G1"}));
  return fixture.root;
};
global.terrainRouteGuidanceMapCandidates = id => f.scope.constraints.find(row => row.constraint_id === id)?.candidates || [];
global.terrainRouteGuidanceFeatureCollection = () => ({features:
  terrainRouteGuidanceMapCandidates(state.terrainRouteGuidanceFocusConstraintId).map(candidate => ({
    geometry: {type: "Point", coordinates: [candidate.centroid.x, candidate.centroid.y]},
    properties: {focused_constraint_candidate: true},
  })),
});
global.KeyboardEvent = class {constructor(type, options) {Object.assign(this, {type}, options);}};
const detail = await diagnosticCheck043();
assert.equal(JSON.stringify(state), before);
bindTerrainRouteGuidanceFocusControls = () => {};
let rejection;
try { await diagnosticCheck043(); } catch (error) { rejection = error; }
assert.ok(rejection, "DASH-043 must execute events and fail when the binder is absent");
assert.equal(rejection.constructor, Error);
assert.equal(JSON.stringify(state), before);
process.stdout.write(JSON.stringify({detail, rejection: rejection.message}));
""")
    assert payload["detail"] and payload["rejection"]


@pytest.fixture(scope="module")
def batch_source(html: str) -> str:
    return "\n".join((
        _array_constant(html, "NAVIGATION_DIAGNOSTIC_CASE_IDS"),
        *(_function(html, name) for name in (
            "runNavigationDashboardDiagnostics", "runDashboardDiagnostic",
            "asArray", "diagnosticNavigationScopeKey", "diagnosticExecutionBusy", "diagnosticRequire",
            "diagnosticSummary", "diagnosticResult", "diagnosticSetResult", "diagnosticSafeDetail", "diagnosticCaseScopeKey",
        )),
        """
global.state = {navigationTerrainHypothesisId: "fixture-run", navigationTerrainHypothesisBand: "top_10_percent_corridor",
  diagnosticResults: {"DASH-001": {status: "passed", detail: "preserved unrelated result"}}};
global.projectId = () => "navigation-fixture";
global.resolvedPretripProjectId = () => projectId();
global.apiBase = () => "http://navigation-fixture.invalid";
state.diagnosticResults["DASH-001"].scopeKey = diagnosticCaseScopeKey("DASH-001");
global.diagnosticResourceCache = new Map([["stale-response", Promise.resolve({})]]);
global.updateDiagnosticDom = () => {};
""",
    ))


def test_navigation_batch_runs_only_its_cases_and_preserves_failures_and_warnings(batch_source: str) -> None:
    payload = _run_node(batch_source, """
const preserved = state.diagnosticResults["DASH-001"];
const calls = [];
global.DASHBOARD_DIAGNOSTIC_CASES = [
  {id: "DASH-001", run: () => assert.fail("Unrelated diagnostic must not run")},
  ...NAVIGATION_DIAGNOSTIC_CASE_IDS.map(id => ({id, run: async () => {
    calls.push(id);
    assert.equal(state.navigationDiagnosticRunning, true);
    if (id === "DASH-039") throw new Error("MCP_UNAVAILABLE");
    if (id === "DASH-042") return {status: "warning", detail: "R4 execution UNKNOWN"};
    return "Synthetic batch handler";
  }})),
];
const summary = await runNavigationDashboardDiagnostics();
assert.equal(state.diagnosticResults["DASH-001"], preserved);
assert.equal(state.navigationDiagnosticRunning, false);
assert.equal(diagnosticResourceCache.size, 0);
const worker = diagnosticResult("DASH-039"), r4 = diagnosticResult("DASH-042");
const staleSummaries = [];
for (const key of ["navigationTerrainHypothesisId", "navigationTerrainHypothesisBand"]) {
  const previous = state[key];
  state[key] = "changed-scope";
  staleSummaries.push(diagnosticSummary(NAVIGATION_DIAGNOSTIC_CASE_IDS));
  state[key] = previous;
}
global.projectId = () => "other-project";
staleSummaries.push(diagnosticSummary(NAVIGATION_DIAGNOSTIC_CASE_IDS));
assert.equal(state.diagnosticResults["DASH-001"], preserved);
assert.equal(diagnosticResult("DASH-001").status, "idle");
process.stdout.write(JSON.stringify({calls, summary, worker, r4, staleSummaries}));
""")
    assert payload["calls"] == list(NAVIGATION_BATCH_IDS)
    assert payload["summary"] == {"total": 7, "idle": 0, "running": 0, "passed": 5, "warning": 1, "failed": 1}
    assert payload["worker"]["status"] == "failed"
    assert payload["worker"]["detail"] == "MCP_UNAVAILABLE"
    assert payload["r4"]["status"] == "warning"
    assert all(summary["idle"] == 7 and summary["passed"] == 0 for summary in payload["staleSummaries"])


def test_navigation_batch_prevents_overlap_and_stops_when_context_changes(batch_source: str) -> None:
    payload = _run_node(batch_source, """
const calls = [];
let release;
const pending = new Promise(resolve => { release = resolve; });
global.DASHBOARD_DIAGNOSTIC_CASES = NAVIGATION_DIAGNOSTIC_CASE_IDS.map(id => ({id, run: () => {
  calls.push(id);
  return pending;
}}));
const running = runNavigationDashboardDiagnostics();
const overlapping = await runNavigationDashboardDiagnostics();
assert.equal(overlapping.running, 1);
assert.deepEqual(calls, ["DASH-025"]);
state.navigationTerrainHypothesisBand = "top_5_percent_corridor";
release("This result belongs to the previous corridor");
const summary = await running;
assert.equal(state.navigationDiagnosticRunning, false);
process.stdout.write(JSON.stringify({calls, summary}));
""")
    assert payload["calls"] == ["DASH-025"]
    assert payload["summary"]["idle"] == 7
    assert payload["summary"]["passed"] == payload["summary"]["running"] == 0


def test_navigation_batch_unlocks_after_an_unexpected_runner_exception(batch_source: str) -> None:
    payload = _run_node(batch_source, """
const preserved = state.diagnosticResults["DASH-001"];
runDashboardDiagnostic = async () => { throw new Error("Synthetic runner failure"); };
await assert.rejects(runNavigationDashboardDiagnostics(), /Synthetic runner failure/);
assert.equal(state.diagnosticResults["DASH-001"], preserved);
process.stdout.write(JSON.stringify({running: state.navigationDiagnosticRunning, busy: diagnosticExecutionBusy()}));
""")
    assert payload == {"running": False, "busy": False}


def test_navigation_initial_idle_result_does_not_claim_a_changed_scope(batch_source: str) -> None:
    payload = _run_node(batch_source, """
const idle = {status: "idle", detail: "Not run yet", durationMs: null, checkedAt: null};
state.diagnosticResults["DASH-025"] = idle;
assert.equal(diagnosticResult("DASH-025"), idle);
state.diagnosticResults["DASH-025"] = {...idle, status: "passed"};
const unboundPastResult = diagnosticResult("DASH-025");
assert.equal(unboundPastResult.status, "idle");
assert.notEqual(unboundPastResult.detail, idle.detail);
process.stdout.write(JSON.stringify({initial: idle.status, unboundPast: unboundPastResult.status}));
""")
    assert payload == {"initial": "idle", "unboundPast": "idle"}


def test_navigation_scope_key_invalidates_changed_default_cache_and_review_evidence(batch_source: str) -> None:
    payload = _run_node(batch_source, """
state.navigationTerrainHypothesisId = "";
state.navigationTerrainData = {terrain_route_hypothesis: {selection: {
  default_id: "displayed-run", options: [
    {selection_id: "displayed-run", provenance: {cache_key: "a".repeat(64)}},
    {selection_id: "other-run", provenance: {cache_key: "b".repeat(64)}},
  ],
}}};
state.terrainRouteGuidance = {feature_index_sha256: "c".repeat(64), resolution_sha256: "d".repeat(64), review_sha256: "e".repeat(64)};
const scopeKey = diagnosticNavigationScopeKey();
state.diagnosticResults["DASH-039"] = {status: "passed", detail: "previous context", scopeKey};
const original = structuredClone(state);
const changed = [];
for (const mutate of [
  () => { state.navigationTerrainData.terrain_route_hypothesis.selection.default_id = "other-run"; },
  () => { state.navigationTerrainData.terrain_route_hypothesis.selection.options[0].provenance.cache_key = "f".repeat(64); },
  () => { state.terrainRouteGuidance.feature_index_sha256 = "f".repeat(64); },
  () => { state.terrainRouteGuidance.resolution_sha256 = "f".repeat(64); },
  () => { state.terrainRouteGuidance.review_sha256 = "f".repeat(64); },
]) {
  global.state = structuredClone(original);
  mutate();
  assert.notEqual(diagnosticNavigationScopeKey(), scopeKey);
  changed.push(diagnosticResult("DASH-039").status);
}
global.state = structuredClone(original);
state.navigationTerrainHypothesisId = "displayed-run";
const explicitKey = diagnosticNavigationScopeKey();
state.navigationTerrainData.terrain_route_hypothesis.selection.default_id = "other-run";
assert.equal(diagnosticNavigationScopeKey(), explicitKey);
process.stdout.write(JSON.stringify({changed}));
""")
    assert payload["changed"] == ["idle"] * 5


def test_api_switch_invalidates_every_navigation_diagnostic_case(batch_source: str) -> None:
    payload = _run_node(batch_source, """
const oldScope = diagnosticNavigationScopeKey();
for (const id of NAVIGATION_DIAGNOSTIC_CASE_IDS) {
  state.diagnosticResults[id] = {status: "passed", detail: "old API evidence", scopeKey: diagnosticCaseScopeKey(id)};
}
global.apiBase = () => "http://another-navigation-runtime.invalid";
assert.notEqual(diagnosticNavigationScopeKey(), oldScope);
const rows = NAVIGATION_DIAGNOSTIC_CASE_IDS.map(id => ({id, status: diagnosticResult(id).status}));
assert.equal(rows.length, 7);
assert(rows.every(row => row.status === "idle"));
process.stdout.write(JSON.stringify({rows}));
""")
    assert {row["id"] for row in payload["rows"]} == {"DASH-025", "DASH-038", "DASH-039", "DASH-040", "DASH-041", "DASH-042", "DASH-043"}


@pytest.mark.parametrize("selection_mode", ("explicit", "displayed-default"))
@pytest.mark.parametrize("displayed_selection_available", (True, False))
def test_navigation_context_keeps_displayed_selection_when_server_default_changes(
    html: str, validator_source: str, selection_mode: str, displayed_selection_available: bool,
) -> None:
    source = validator_source + _function(html, "diagnosticResource")
    payload = _run_node(source, f"""
const f = navigationEvidenceFixture();
global.state = {{navigationTerrainHypothesisId: {json.dumps(selection_mode)} === "explicit" ? f.context.selection_id : "",
  navigationTerrainHypothesisBand: f.context.band_name,
  navigationTerrainData: {{terrain_route_hypothesis: {{selection: {{default_id: f.context.selection_id, options: [f.hypothesis]}}}}}},
}};
global.projectId = () => f.context.project_id;
global.diagnosticResourceCache = new Map();
const requests = [];
global.diagnosticJson = async path => {{
  requests.push(path);
  const newer = {{...f.hypothesis, selection_id: "new-server-default"}};
  return {{status: "ready", project_id: f.context.project_id, boundary: {{candidate_only: true, runtime_safety_truth: false, operational: false}}, terrain_route_hypothesis: {{selection: {{
    default_id: newer.selection_id, options: {json.dumps(displayed_selection_available)} ? [newer, f.hypothesis] : [newer],
  }}}}}};
}};
if ({json.dumps(displayed_selection_available)}) {{
  const context = await diagnosticNavigationContext();
  assert.equal(context.selection_id, f.context.selection_id);
  assert.equal(context.hypothesis, f.hypothesis);
}} else {{
  await assert.rejects(diagnosticNavigationContext(), error => error.constructor === Error);
}}
process.stdout.write(JSON.stringify({{requests}}));
""")
    assert payload["requests"] == ["/admin/pretrip/projects/navigation-fixture/navigation-terrain-intelligence"]


@pytest.mark.parametrize("scope_available", (True, False))
def test_navigation_scope_loads_existing_get_apis_and_rejects_typed_unavailability(
    html: str, validator_source: str, scope_available: bool,
) -> None:
    source = validator_source + "\n".join(
        _function(html, name) for name in ("fetchJson", "diagnosticResource", "diagnosticJson")
    )
    payload = _run_node(source, f"""
const f = navigationEvidenceFixture();
global.state = {{navigationTerrainHypothesisId: f.context.selection_id, navigationTerrainHypothesisBand: f.context.band_name}};
const before = JSON.stringify(state);
global.window = {{setTimeout, clearTimeout}};
global.apiBase = () => "http://navigation-fixture.invalid";
global.projectId = () => f.context.project_id;
global.diagnosticResourceCache = new Map();
const base = `/admin/pretrip/projects/${{f.context.project_id}}`;
const expectedPaths = [base + "/navigation-terrain-intelligence", base + "/terrain-route-guidance", base + "/terrain-route-guidance/map-review-scope"];
const requests = [];
global.fetch = async (url, options = {{}}) => {{
  const parsed = new URL(url);
  const index = expectedPaths.indexOf(parsed.pathname);
  assert.notEqual(index, -1, "Only existing read-only Navigation APIs may be used");
  assert.equal(options.method || "GET", "GET");
  assert.equal(options.body, undefined);
  requests.push(parsed.pathname);
  if (index === 2) assert.deepEqual(Object.fromEntries(parsed.searchParams), {{
    reference_hypothesis_id: f.context.selection_id, corridor_band_name: f.context.band_name,
    expected_feature_index_sha256: f.guidance.feature_index_sha256,
    expected_resolution_sha256: f.guidance.resolution_sha256,
  }});
  const data = [
    {{project_id: f.context.project_id, status: "ready", boundary: {{candidate_only: true, runtime_safety_truth: false, operational: false}}, terrain_route_hypothesis: {{selection: {{default_id: f.context.selection_id, options: [f.hypothesis]}}}}}},
    f.guidance,
    {json.dumps(scope_available)} ? f.scope : {{status: "unavailable", reason: "sampler_unavailable", candidate_only: true, runtime_safety_truth: false, operational: false}},
  ][index];
  const status = index === 2 && !{json.dumps(scope_available)} ? 409 : 200;
  return {{ok: status === 200, status, json: async () => data}};
}};
if ({json.dumps(scope_available)}) {{
  const result = await diagnosticNavigationGuidanceScope();
  assert.equal(result.scope, f.scope);
}} else {{
  await assert.rejects(diagnosticNavigationGuidanceScope(), /UNKNOWN/);
}}
assert.equal(JSON.stringify(state), before);
process.stdout.write(JSON.stringify({{requests}}));
""")
    base = "/admin/pretrip/projects/navigation-fixture"
    assert payload["requests"] == [
        f"{base}/navigation-terrain-intelligence",
        f"{base}/terrain-route-guidance",
        f"{base}/terrain-route-guidance/map-review-scope",
    ]


OVERLAY_FIXTURE = r"""
const png = Buffer.from(
  "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489" +
  "0000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082", "hex",
);
const expectedHash = require("node:crypto").createHash("sha256").update(png).digest("hex");
const metrics = {requests: [], decoded: 0, closed: 0, timers: 0, cleared: 0};
const responseFixture = {status: 200, contentType: "image/png", width: 1, height: 1};
const overlay = {mode: "top_5_percent_corridor", sha256: expectedHash, pixel_width: 1, pixel_height: 1,
  runtime_href: "/admin/pretrip/projects/navigation-fixture/terrain-route-overlays/top_5_percent_corridor.png"};
const context = {project_id: "navigation-fixture", selection_id: "active-123456789abc", hypothesis: {selection_scope: "active_request"}};
global.apiBase = () => "http://navigation-fixture.invalid";
global.window = {
  crypto: require("node:crypto").webcrypto,
  setTimeout: () => ++metrics.timers,
  clearTimeout: () => { metrics.cleared += 1; },
};
global.fetch = async (url, options = {}) => {
  metrics.requests.push({url, method: options.method || "GET", cache: options.cache});
  assert.equal(options.body, undefined);
  assert.ok(options.signal instanceof AbortSignal);
  return {ok: responseFixture.status === 200, status: responseFixture.status,
    headers: {get: name => name === "content-type" ? responseFixture.contentType : null},
    arrayBuffer: async () => Uint8Array.from(png).buffer};
};
global.createImageBitmap = async blob => {
  metrics.decoded += 1;
  assert.equal(blob.type, "image/png");
  assert.deepEqual(Buffer.from(await blob.arrayBuffer()), png);
  return {width: responseFixture.width, height: responseFixture.height,
    close: () => { metrics.closed += 1; }};
};
"""


@pytest.fixture(scope="module")
def overlay_source(html: str) -> str:
    return "\n".join((
        OVERLAY_FIXTURE,
        _array_constant(html, "NAVIGATION_TERRAIN_ROUTE_CORRIDOR_MODES"),
        _function(html, "diagnosticRequire"),
        _function(html, "diagnosticNavigationVerifyOverlay"),
    ))


@pytest.mark.parametrize("selection_scope", ("active_request", "full_route"))
def test_navigation_overlay_preserves_active_or_catalog_url_and_checks_bytes(
    overlay_source: str, selection_scope: str,
) -> None:
    payload = _run_node(overlay_source, f"""
context.hypothesis.selection_scope = {json.dumps(selection_scope)};
if (context.hypothesis.selection_scope !== "active_request") {{
  context.selection_id = "saved-fixture";
  overlay.runtime_href += "?hypothesis_id=saved-fixture&v=old-digest";
}}
await diagnosticNavigationVerifyOverlay(overlay, context);
const query = Object.fromEntries(new URL(metrics.requests[0].url).searchParams);
assert.equal(query.v, expectedHash);
process.stdout.write(JSON.stringify({{metrics, query}}));
""")
    assert len(payload["metrics"]["requests"]) == 1
    assert payload["metrics"]["requests"][0]["method"] == "GET"
    assert payload["metrics"]["requests"][0]["cache"] == "no-store"
    assert payload["metrics"]["decoded"] == payload["metrics"]["closed"] == 1
    assert payload["metrics"]["timers"] == payload["metrics"]["cleared"] == 1
    assert set(payload["query"]) == ({"v"} if selection_scope == "active_request" else {"hypothesis_id", "v"})
    if selection_scope != "active_request":
        assert payload["query"]["hypothesis_id"] == "saved-fixture"


@pytest.mark.parametrize("query", ("", "?hypothesis_id=another-catalog-entry"))
def test_navigation_overlay_rejects_missing_or_wrong_catalog_binding_before_fetch(
    overlay_source: str, query: str,
) -> None:
    payload = _run_node(overlay_source, f"""
context.hypothesis.selection_scope = "full_route";
context.selection_id = "saved-fixture";
overlay.runtime_href += {json.dumps(query)};
await assert.rejects(diagnosticNavigationVerifyOverlay(overlay, context), new RegExp("active / catalog"));
process.stdout.write(JSON.stringify(metrics));
""")
    assert payload == {"requests": [], "decoded": 0, "closed": 0, "timers": 0, "cleared": 0}


@pytest.mark.parametrize(("mutation", "message", "decoded", "closed"), (
    ("responseFixture.status = 404", "HTTP 404", 0, 0),
    ("overlay.sha256 = '0'.repeat(64)", "SHA-256", 0, 0),
    ("responseFixture.width = 2", "", 1, 1),
    ("responseFixture.contentType = 'text/html'", "PNG", 0, 0),
))
def test_navigation_overlay_fails_closed_and_cleans_up_invalid_responses(
    overlay_source: str, mutation: str, message: str, decoded: int, closed: int,
) -> None:
    payload = _run_node(overlay_source, f"""
{mutation};
let failure;
try {{ await diagnosticNavigationVerifyOverlay(overlay, context); }} catch (error) {{ failure = error; }}
assert.ok(failure, "Invalid overlay evidence must not pass");
assert.equal(failure.constructor, Error);
process.stdout.write(JSON.stringify({{metrics, detail: failure.message}}));
""")
    assert payload["detail"] and message in payload["detail"]
    assert len(payload["metrics"]["requests"]) == 1
    assert payload["metrics"]["decoded"] == decoded
    assert payload["metrics"]["closed"] == closed
    assert payload["metrics"]["timers"] == payload["metrics"]["cleared"] == 1


@pytest.mark.parametrize("valid_boundary", (True, False))
def test_navigation_unprepared_data_warns_only_after_candidate_boundary_validation(
    html: str, validator_source: str, valid_boundary: bool,
) -> None:
    source = validator_source + _function(html, "diagnosticResource")
    payload = _run_node(source, f"""
global.state = {{}};
global.projectId = () => "navigation-fixture";
global.diagnosticResourceCache = new Map();
global.diagnosticJson = async () => ({{project_id: "navigation-fixture", status: "not_prepared",
  boundary: {{runtime_safety_truth: {json.dumps(not valid_boundary)}}}}});
let failure;
try {{ await diagnosticNavigationContext(); }} catch (error) {{ failure = error; }}
assert.ok(failure instanceof Error);
process.stdout.write(JSON.stringify({{status: failure.diagnosticStatus || "failed",
  structureStatus: failure.structureStatus, dataStatus: failure.dataStatus}}));
""")
    if valid_boundary:
        assert payload == {"status": "warning", "structureStatus": "passed", "dataStatus": "not_prepared"}
    else:
        assert payload["status"] == "failed"
