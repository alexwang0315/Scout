const { test } = require("node:test");
const assert = require("node:assert/strict");
const { classifyDiagnosticProbeFailures: classify } = require("../tools/dashboard_scout_monitor_probe_requests.cjs");

function fixture() {
  const frame = {}, baseUrl = "http://127.0.0.1:9099";
  return { failures: ["status", "history?limit=60", "events?limit=50"].map(endpoint => ({
    url: `${baseUrl}/admin/dashboard/scout-monitor/api/v1/hardware-monitor/${endpoint}`,
    method: "GET", frame, startedPhase: "existing-dash-050", phase: "existing-dash-050", error: "net::ERR_ABORTED",
  })), context: { baseUrl, probes: [{ frame, newFrame: true, directChild: true, detached: true,
    url: `${baseUrl}/admin/dashboard/scout-monitor?ui=20260915-hailo1`,
    title: "scout monitor 電源分離與 Hailo 隔離檢查", hidden: true, ariaHidden: "true", tabIndex: -1 }],
    report: { id: "DASH-050", status: "passed", structureStatus: "passed", probeCleanup: "passed" } } };
}

test("known three initial probe cancellations retain evidence with separate classification", () => {
  const { failures, context } = fixture();
  // Equivalent replay of the preserved original smoke failure: all three were
  // previously in the failing requestfailed list even though D050 passed.
  assert.equal(failures.length, 3);
  const result = classify(failures, context);
  assert.equal(result.failedResponses.length, 0);
  assert.equal(result.expectedCancelledRequests.length, 3);
  assert.ok(result.expectedCancelledRequests.every(item => item.error === "net::ERR_ABORTED"
    && item.classification === "expected_cancelled" && item.frameScope === "diagnostic-owned-probe"));
  assert.doesNotThrow(() => JSON.stringify(result));
  assert.ok(!("frame" in result.probeEvidence[0]));
});

for (const [name, mutate] of [
  ["visible monitor with identical URL and error", f => { f.failures[0].frame = {}; }],
  ["unknown frame", f => { f.failures[0].frame = null; }],
  ["request started before retest", f => { f.failures[0].startedPhase = "manual-refresh"; }],
  ["request failed outside retest", f => { f.failures[0].phase = "mobile-reload"; }],
  ["real connection failure in probe", f => { f.failures[0].error = "net::ERR_CONNECTION_REFUSED"; }],
  ["POST to expected route", f => { f.failures[0].method = "POST"; }],
  ["cross-origin request", f => { f.failures[0].url = f.failures[0].url.replace(":9099", ":9151"); }],
  ["other endpoint", f => { f.failures[0].url += "/healthz"; }],
  ["unexpected query", f => { f.failures[0].url += "?retry=true"; }],
  ["changed history limit", f => { f.failures[1].url = f.failures[1].url.replace("limit=60", "limit=100"); }],
  ["invalid URL", f => { f.failures[0].url = "not a URL"; }],
  ["missing phase evidence", f => { delete f.failures[0].startedPhase; }],
]) test(`${name} still fails`, () => {
  const f = fixture(); mutate(f);
  const result = classify(f.failures, f.context);
  assert.equal(result.failedResponses.length, 1);
  assert.equal(result.expectedCancelledRequests.length, 2);
});

for (const [name, mutate] of [
  ["no probe", f => { f.context.probes = []; f.failures[0].frame = undefined; }],
  ["ambiguous probes", f => { f.context.probes.push({ ...f.context.probes[0], frame: {} }); }],
  ["existing user frame", f => { f.context.probes[0].newFrame = false; }],
  ["nested unrelated frame", f => { f.context.probes[0].directChild = false; }],
  ["wrong frame URL", f => { f.context.probes[0].url += "&other=true"; }],
  ["wrong title", f => { f.context.probes[0].title = "scout monitor"; }],
  ["visible probe", f => { f.context.probes[0].hidden = false; }],
  ["no aria-hidden", f => { f.context.probes[0].ariaHidden = null; }],
  ["focusable frame", f => { f.context.probes[0].tabIndex = 0; }],
  ["frame not removed", f => { f.context.probes[0].detached = false; }],
  ["missing report", f => { f.context.report = null; }],
  ["wrong Diagnostic", f => { f.context.report.id = "DASH-049"; }],
  ["failed Diagnostic", f => { f.context.report.status = "failed"; }],
  ["warning Diagnostic", f => { f.context.report.status = "warning"; }],
  ["failed structure", f => { f.context.report.structureStatus = "failed"; }],
  ["failed cleanup", f => { f.context.report.probeCleanup = "failed"; }],
]) test(`${name} cannot exempt any failure`, () => {
  const f = fixture(); mutate(f);
  const result = classify(f.failures, f.context);
  assert.equal(result.failedResponses.length, 3);
  assert.equal(result.expectedCancelledRequests.length, 0);
  if (!f.context.probes.length) assert.ok(result.failedResponses.every(item => item.frameScope === "ordinary-or-unverified"));
});

test("duplicate cancelled route is not an expected initial read", () => {
  const f = fixture(); f.failures.push({ ...f.failures[0] });
  const result = classify(f.failures, f.context);
  assert.equal(result.failedResponses.length, 2);
  assert.equal(result.expectedCancelledRequests.length, 2);
});

test("successful initial reads need no cancellation exception", () => {
  const f = fixture();
  assert.deepEqual(classify([], f.context).expectedCancelledRequests, []);
  assert.deepEqual(classify([], f.context).failedResponses, []);
});
