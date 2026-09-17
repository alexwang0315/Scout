"""Execute DASH-002 against the sidebar contract and isolated failure cases.

Markup and resolved truth are controlled inputs here; live page rendering remains
part of Chrome Diagnostic acceptance. The D002 function and registered truth
entries come from the production HTML, rather than a copied validation algorithm.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"
TRUTH_FIELDS = ["surface", "data", "action", "verification", "provenance", "mode"]
CASES = [
    ("current_sidebar", None),
    ("missing_monitor", "Missing navigation routes: scout-monitor"),
    ("missing_map", "Missing navigation routes: map"),
    ("unknown_extra", "Unregistered sidebar route IDs: unknown-route"),
    ("duplicate_settings", "Duplicate sidebar route IDs: settings"),
    ("duplicate_monitor", "Duplicate sidebar route IDs: scout-monitor"),
    ("map_replaced_unknown", "Missing navigation routes: map"),
    ("empty_id", "Unregistered sidebar route IDs:"),
    ("settings_not_adjacent", "Diagnostic is not immediately after Settings."),
    ("missing_monitor_truth", "One or more routes have no truth contract."),
    ("incomplete_monitor_markup", "scout-monitor rendered an empty or incomplete page."),
    ("one_mobile_toggle", "Desktop/map mobile navigation toggles are missing."),
    ("no_mobile_toggle", "Desktop/map mobile navigation toggles are missing."),
] + [
    (f"missing_truth_{field}", f"scout-monitor truth contract is missing {field}.")
    for field in TRUTH_FIELDS
]


@pytest.fixture(scope="module")
def replay_results():
    html = PAGE.read_text(encoding="utf-8")
    sidebar = html.split('id="dashboardSidebar"', 1)[1].split("</aside>", 1)[0]
    routes = re.findall(r'\bdata-route="([^"]*)"', sidebar)
    source = "async function diagnosticCheck002() {" + html.split(
        "async function diagnosticCheck002() {", 1
    )[1].split("    async function diagnosticProjectIsolationReplay()", 1)[0]
    truth_source = "const ROUTE_TRUTH = Object.freeze({" + html.split(
        "const ROUTE_TRUTH = Object.freeze({", 1
    )[1].split("    });", 1)[0] + "    });"
    node = shutil.which("node")
    assert node, "Node.js is required to execute the production D002 check"
    script = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const registeredTruth = new Function(input.truthSource + '; return ROUTE_TRUTH;')();
async function run(caseId) {
  let routes = [...input.routes];
  const truth = {...registeredTruth};
  let toggleCount = 2;
  if (caseId === 'missing_monitor') routes = routes.filter(r => r !== 'scout-monitor');
  if (caseId === 'missing_map') routes = routes.filter(r => r !== 'map');
  if (caseId === 'unknown_extra') routes.push('unknown-route');
  if (caseId === 'duplicate_settings') routes.push('settings');
  if (caseId === 'duplicate_monitor') routes.push('scout-monitor');
  if (caseId === 'map_replaced_unknown') routes = routes.map(r => r === 'map' ? 'unknown-route' : r);
  if (caseId === 'empty_id') routes.push('');
  if (caseId === 'missing_monitor_truth') delete truth['scout-monitor'];
  if (caseId === 'one_mobile_toggle') toggleCount = 1;
  if (caseId === 'no_mobile_toggle') toggleCount = 0;
  if (caseId === 'settings_not_adjacent') {
    const first = routes.indexOf('settings');
    const second = routes.indexOf('diagnostic');
    [routes[first], routes[second]] = [routes[second], routes[first]];
  }
  const buttons = routes.map(route => ({dataset: {route}}));
  buttons.forEach((button, index) => {button.nextElementSibling = buttons[index + 1] || null;});
  const document = {querySelectorAll(selector) {
    if (selector === '#dashboardSidebar [data-route]') return buttons;
    if (selector === '[data-dashboard-nav-toggle]') return Array.from({length: toggleCount}, () => ({}));
    throw new Error('Unexpected D002 selector: ' + selector);
  }};
  const markupCalls = [];
  const truthCalls = [];
  const renderMarkup = route => {
    markupCalls.push(route);
    return caseId === 'incomplete_monitor_markup' && route === 'scout-monitor'
      ? '<section></section>' : '<section>' + 'Isolated markup fixture. '.repeat(6) + '</section>';
  };
  const resolveTruth = route => {
    truthCalls.push(route);
    const value = {...truth[route]};
    if (caseId.startsWith('missing_truth_') && route === 'scout-monitor') {
      value[caseId.slice('missing_truth_'.length)] = ' ';
    }
    return value;
  };
  const requireValue = (condition, message) => {if (!condition) throw new Error(message);};
  const execute = new Function('document', 'diagnosticRequire', 'ROUTE_TRUTH',
    'diagnosticRouteMarkup', 'resolveRouteTruth', input.source + '\nreturn diagnosticCheck002;')(
      document, requireValue, truth, renderMarkup, resolveTruth);
  try {return {accepted: true, detail: await execute(), markupCalls, truthCalls};}
  catch(error) {return {accepted: false, detail: error.message, markupCalls, truthCalls};}
}
(async () => {
  const cases = {};
  for (const caseId of input.caseIds) cases[caseId] = await run(caseId);
  process.stdout.write(JSON.stringify({routes: input.routes, cases}));
})().catch(error => {process.stderr.write(error.stack); process.exitCode = 1;});
"""
    completed = subprocess.run(
        [node, "-e", script],
        input=json.dumps({
            "routes": routes,
            "source": source,
            "truthSource": truth_source,
            "caseIds": [case_id for case_id, _ in CASES],
        }),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("case_id, expected_error", CASES)
def test_d002_executes_sidebar_and_failure_contracts(replay_results, case_id, expected_error):
    result = replay_results["cases"][case_id]
    if expected_error is None:
        assert result["accepted"] is True, result["detail"]
        routes = replay_results["routes"]
        assert len(routes) == len(set(routes)) == 25
        assert "scout-monitor" in routes
        assert set(result["markupCalls"]) == set(routes)
        assert set(result["truthCalls"]) == set(routes)
        assert len(result["markupCalls"]) == len(result["truthCalls"]) == 25
        assert result["detail"] == (
            "25 routes rendered · truth contracts complete · Diagnostic follows Settings"
        )
    else:
        assert result["accepted"] is False
        assert result["detail"] == expected_error or (
            case_id == "empty_id" and result["detail"].rstrip() == expected_error
        )
