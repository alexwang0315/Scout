from __future__ import annotations

import re
import subprocess
from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "docs/admin/scout-dashboard-v0.1.html"
FUNCTIONS = (
    "asArray",
    "escapeHtml",
    "permissionBaselineReviewRequirements",
    "resetPermissionBaselineReviewChecks",
    "permissionBaselineReviewComplete",
    "permissionFiniteNumber",
    "permissionHasReferenceReplay",
    "permissionFormatMinutes",
    "permissionFormatReferenceDuration",
    "permissionReferenceClock",
    "renderPermissionEta",
    "permissionFormatRouteKm",
    "permissionFormatCoordinate",
    "permissionCompactAnchorLabel",
    "renderPermissionReferenceCheckpointTable",
    "renderPermissionReferenceGaps",
    "renderPermissionReferenceDayDetails",
    "renderPermissionReferenceRecordingContext",
    "permissionEtaHeadline",
    "renderPermissionBaselineProposal",
    "renderPermissionBaselineQuickReview",
    "renderPermissionBaselineConfirmationSheet",
    "previewPermissionBaseline",
)


def _run_renderer(assertions: str) -> None:
    html = PAGE.read_text(encoding="utf-8")
    sources = []
    for name in FUNCTIONS:
        match = re.search(rf"^    (?:async )?function {name}\(", html, re.MULTILINE)
        assert match is not None, name
        end = html.index("\n    }\n", match.start()) + len("\n    }")
        sources.append(html[match.start():end])
    program = "\n".join(sources) + r"""
const assert = require("node:assert/strict");
const state = {};
const permissionMapAnchor = () => ({});
const permissionDayAnchorContext = () => "Reference route";
const renderPermissionDayMap = () => "<figure data-test-map></figure>";
function fixture() {
  const replay = {
    source_day_id: "2025-10-03", departure_clock: "05:03:04", arrival_clock: "12:17:09",
    elapsed_minutes: 434.0833333333333,
    start: {lat: 23.12345, lon: 121.12345, route_order_m: 0},
    end: {lat: 23.22345, lon: 121.22345, route_order_m: 12000},
    rest_stops: [{stop_id: "stop.1", label: "Recorded cluster", route_order_m: 3500,
      start_clock: "07:08:09", end_clock: "07:20:12", duration_minutes: 12.05,
      basis: "filtered_gpx_stationary_cluster", lat: 23.15345, lon: 121.15345}],
    checkpoint_windows: [{anchor_id: "cp.1", label: "CP 001", route_order_m: 500,
      arrival_clock: "05:15:07", status: "recorded_trackpoint", from_previous_minutes: 12.05,
      from_previous_distance_m: 500, from_previous_speed_kmh: 2.4896,
      remaining_to_day_end_minutes: 422.0333333333333}],
    unknown_ranges: [{reason: "intra_day_recording_gap", start_clock: "08:10:11",
      end_clock: "08:40:11", duration_minutes: 30, start_route_order_m: 6200,
      end_route_order_m: 6225, point_count: 3}],
  };
  return {
    proposal_profile: "ref_gpx_proposal_v1",
    proposal_strategy_id: "reference-gpx.historical-reconstruction",
    source_sha256: "source-hash",
    reference_reconstruction: {source_ref: "inputs/reference.gpx", source_sha256: "gpx-hash",
      timezone: "Asia/Taipei", overnight_gaps: [{reason: "overnight_recording_gap",
        start_timestamp: "2025-10-02T16:12:13+08:00", end_timestamp: "2025-10-03T05:03:04+08:00",
        from_day_index: 1, to_day_index: 2, start_distance_m: 12000, end_distance_m: 12037,
        recording_gap_distance_m: 37}],
      unassigned_checkpoint_windows: []},
    proposal_summary: {reconstructed_day_count: 1, day_count: 1, route_length_m: 12000,
      historical_checkpoint_count: 1, historical_timed_checkpoint_count: 1,
      historical_rest_stop_count: 1, target_p75_minutes_per_day: null},
    review_requirements: {required_reviewed_day_ids: ["D1"],
      required_acknowledgment_uncertainty_ids: ["recording-gap.1"],
      pending_safety_handoff_item_ids: ["safety.1"], safety_handoff_required: true},
    days: [{mission_day_id: "D1", day_kind: "on_trail", segment_ids: ["history.D1"],
      start_anchor: {anchor_id: "start", display_label: "Historical trailhead", route_order_m: 0},
      primary_day_end_proposal: {proposal_id: "proposal.1", target: {anchor_id: "end",
        display_label: "Historical day end", route_order_m: 12000,
        artifact: {ref: "inputs/reference.gpx", sha256: "gpx-hash"}}},
      eta_proposal: {state: "reference_replayed", method: "reference_track_elapsed",
        observed_elapsed_minutes: replay.elapsed_minutes},
      reference_replay: replay}],
  };
}
""" + assertions
    result = subprocess.run(
        ["node"], input=program, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_reference_replay_renders_days_clocks_stops_and_observed_elapsed() -> None:
    _run_renderer(r"""
const draft = fixture();
const result = renderPermissionBaselineProposal(draft);
for (const expected of ["Copied historical itinerary", "Recorded days", "2025-10-03",
  "Historical start", "05:03:04", "12:17:09", "7 h 14 m 5 s", "07:08:09",
  "07:20:12", "12 m 3 s", "filtered gpx stationary cluster", "05:15:07",
  "0.500 km", "2.49 km/h", "7 h 2 m 2 s", "Between-day recording gaps",
  "2025-10-02T16:12:13+08:00", "intra day recording gap", "08:40:11",
  "N23.22345", "N23.15345", "1 / 1 CP clocks", "1 inferred stops", "D1 → D2",
  "12.000 km → 12.037 km", "37.0 m in recording gap", "6.200 km → 6.225 km", "3 source points"]) {
  assert.ok(result.includes(expected), expected);
}
assert.ok(result.includes("Elapsed time includes recorded stops"));
assert.ok(result.includes("neither moving-only time nor a p75 estimate"));
assert.ok(result.includes("not moving-only walking speed"));
assert.ok(result.includes("do not confirm the activity or approve a rest or overnight site"));
assert.ok(!result.includes("Complete p75 coverage"));
assert.ok(!result.includes("missing p75"));
assert.ok(!result.includes("Proposed days"));
""")


def test_reference_replay_renders_every_cp_and_preserves_unknown_values() -> None:
    _run_renderer(r"""
const draft = fixture();
const prototype = draft.days[0].reference_replay.checkpoint_windows[0];
draft.days[0].reference_replay.checkpoint_windows = Array.from({length: 218}, (_, index) => ({
  ...prototype, anchor_id: `cp.${index + 1}`, label: `CP ${index + 1}`,
}));
draft.reference_reconstruction.unassigned_checkpoint_windows = [{anchor_id: "cp.219",
  label: "CP 219 <script>alert(1)</script>", route_order_m: null, arrival_clock: null,
  status: "outside_recorded_day", from_previous_minutes: null, from_previous_distance_m: null,
  from_previous_speed_kmh: null, remaining_to_day_end_minutes: null}];
const result = renderPermissionBaselineProposal(draft);
assert.equal((result.match(/data-permission-reference-checkpoint=/g) || []).length, 219);
const unknownRow = result.match(/<tr data-permission-reference-checkpoint="cp\.219">[\s\S]*?<\/tr>/)[0];
assert.equal((unknownRow.match(/unknown/g) || []).length, 6);
assert.ok(!unknownRow.includes("0.000 km"));
assert.ok(!unknownRow.includes("0.00 km/h"));
assert.ok(!unknownRow.includes("0 m 0 s"));
assert.ok(!result.includes("<script>alert(1)</script>"));
assert.ok(result.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
for (const missing of [null, undefined, "", "  ", false, "invalid"]) {
  assert.equal(permissionFormatMinutes(missing), "unknown");
  assert.equal(permissionFormatRouteKm(missing), "unknown");
  assert.equal(permissionFormatReferenceDuration(missing), "unknown");
  assert.equal(permissionFormatCoordinate(missing, "lat"), "coordinate unavailable");
}
assert.equal(permissionFormatMinutes(0), "0 min");
assert.equal(permissionFormatReferenceDuration(0), "0 m 0 s");
assert.equal(permissionFormatRouteKm(0), "0.0 km");
assert.equal(permissionFormatCoordinate(0, "lat"), "N0.00000");
""")


def test_reference_adoption_keeps_hash_bound_review_and_final_confirmation() -> None:
    _run_renderer(r"""
state.permissionBaselineDraft = fixture();
state.permissionBaselineSavedCandidate = {version_sha256: "candidate-hash", review_ready: true};
resetPermissionBaselineReviewChecks("candidate-hash");
state.permissionBaselinePendingAction = {kind: "accept"};
assert.equal(permissionBaselineReviewComplete(), false);
assert.ok(renderPermissionBaselineConfirmationSheet().includes('data-permission-baseline-confirm-submit="true" disabled'));
const review = renderPermissionBaselineQuickReview();
assert.ok(review.includes("I adopt the reference trip’s recorded daily starts, endpoints, route and time windows"));
assert.ok(review.includes("recorded daily endpoints are already bound to the source"));
assert.ok(review.includes("missing CP clocks and unrecorded movement remain unknown"));
state.permissionBaselineReviewChecks.dayEnds = true;
state.permissionBaselineReviewChecks.timingUncertainty = true;
assert.equal(permissionBaselineReviewComplete(), false);
state.permissionBaselineReviewChecks.safetyHandoff = true;
assert.equal(permissionBaselineReviewComplete(), true);
const sheet = renderPermissionBaselineConfirmationSheet();
assert.ok(sheet.includes("Record your adoption of this copied historical itinerary"));
assert.ok(sheet.includes("1 copied historical days"));
assert.ok(!sheet.includes('data-permission-baseline-confirm-submit="true" disabled'));
state.permissionBaselineReviewChecks.candidateSha256 = "old-candidate-hash";
assert.equal(permissionBaselineReviewComplete(), false);
""")


def test_legacy_proposals_keep_quantile_rendering_and_review_text() -> None:
    _run_renderer(r"""
const draft = fixture();
draft.proposal_strategy_id = "reference-gpx.evidence-bound-day-proposal";
draft.reference_reconstruction = null;
draft.days[0].reference_replay = null;
draft.days[0].eta_proposal = {state: "partial_derived", supported_segment_p50_sum_minutes: null,
  supported_segment_p75_sum_minutes: 25, supporting_segment_ids: ["s1"],
  unsupported_segment_ids: ["s2"]};
draft.proposal_summary = {day_count: 1, route_length_m: 12000,
  observed_p75_segment_count: 1, missing_p75_segment_count: 1};
const result = renderPermissionBaselineProposal(draft);
assert.ok(result.includes("Proposal-first daily itinerary"));
assert.ok(result.includes("Known p75 subtotal 25 min"));
assert.ok(result.includes("1 usable / 1 missing p75"));
assert.ok(!result.includes("Supported-segment p50 subtotal"));
assert.ok(!result.includes("Reference recorded elapsed time"));
assert.ok(!result.includes("data-permission-reference-checkpoint"));
state.permissionBaselineDraft = draft;
assert.ok(renderPermissionBaselineQuickReview().includes("I confirm the exact day-end target"));
""")


def test_preview_reports_reference_counts_without_changing_human_review() -> None:
    _run_renderer(r"""
const render = () => {};
const resolvedPretripProjectId = () => "test-workspace";
const loadPermissionBaselineMapContext = async id => assert.equal(id, "test-workspace");
const postJson = async (path, payload) => {
  assert.equal(path, "/admin/pretrip/projects/test-workspace/mission-baseline/generate-draft");
  assert.deepEqual(payload, {mode: "reference_gpx", reference_strategy: "historical_reconstruction", reference_route_ref: "outputs/compiled_mission_graph.reviewed.json"});
  return fixture();
};
state.permissionBaselineMode = "reference_gpx";
state.permissionBaselineSavedCandidate = {version_sha256: "prior-hash", review_ready: true};
state.permissionBaselineReviewChecks = {candidateSha256: "prior-hash", dayEnds: true,
  timingUncertainty: true, safetyHandoff: true};
previewPermissionBaseline(true).then(() => {
  assert.equal(state.permissionBaselineStatus, "Reference itinerary reconstructed · 1 recorded days · 1 / 1 CP clocks · 1 inferred stops · writes_performed=false");
  assert.equal(state.permissionBaselineSavedCandidate, null);
  assert.deepEqual(state.permissionBaselineReviewChecks, {candidateSha256: "", dayEnds: false,
    timingUncertainty: false, safetyHandoff: false});
}).catch(error => { console.error(error); process.exitCode = 1; });
""")
