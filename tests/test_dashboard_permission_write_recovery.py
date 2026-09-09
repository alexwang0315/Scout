"""Exercise the shipped Permission command code with isolated VM transports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"
PAGE_TEXT = PAGE.read_text(encoding="utf-8")
PAGE_SHA256 = hashlib.sha256(PAGE_TEXT.encode()).hexdigest()
FUNCTION_NAMES = (
    "postJson",
    "fetchJson",
    "sha256Hex",
    "permissionProjectionPath",
    "permissionDailyReviewPath",
    "permissionBaselineReviewRequirements",
    "permissionBaselineReviewComplete",
    "permissionHasReferenceReplay",
    "renderPermissionBaselineQuickReview",
    "resetPermissionBaselineReviewChecks",
    "loadPermissionBaselineCandidates",
    "loadPermissionData",
    "postPermissionBaselineCommand",
    "closePermissionBaselineConfirmation",
    "submitPermissionBaselineWrite",
)


@pytest.fixture(scope="module", autouse=True)
def _record_dashboard_source(record_testsuite_property) -> None:
    record_testsuite_property("dashboard_source_sha256", PAGE_SHA256)


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for isolated Dashboard command tests")
    functions = []
    for name in FUNCTION_NAMES:
        match = re.search(
            rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", PAGE_TEXT
        )
        assert match, f"Dashboard function missing: {name}"
        functions.append(match.group(0))
    review_handler = re.search(
        r'(?ms)^      document\.querySelectorAll\("\[data-permission-review-check\]"\)'
        r"\.forEach\(input => \{.*?^      \}\);",
        PAGE_TEXT,
    )
    assert review_handler, "Dashboard Quick review change handler missing"
    source = "\n".join([*functions, review_handler.group(0)])
    setup = r"""
const HASH = {candidate: "a".repeat(64), source: "b".repeat(64),
  reviewed: "c".repeat(64), snapshot: "d".repeat(64)};
let project = "workspace-a";
const resolvedPretripProjectId = () => project;
const apiBase = () => "";
const asArray = value => Array.isArray(value) ? value : [];
const FETCH_TIMEOUT_MS = 20000;
const FETCH_TIMEOUT = FETCH_TIMEOUT_MS;
const DIAGNOSTIC_MAP_PROBE = false;
let renders = 0;
const render = () => { renders += 1; };
const reviewInputs = ["dayEnds", "timingUncertainty", "safetyHandoff"].map(name => ({
  dataset: {permissionReviewCheck: name}, checked: false, listeners: {},
  addEventListener(event, listener) { this.listeners[event] = listener; },
}));
const document = {querySelectorAll(selector) {
  assert.equal(selector, '[data-permission-review-check]');
  return reviewInputs;
}};
const state = {
  route: "outdoor-permission", permissionLens: "baseline",
  permissionBaselineBusy: false,
  permissionBaselinePendingAction: {kind: "accept", idempotencyKey: "pending-old"},
  permissionBaselineDraft: {
    source_sha256: HASH.source, proposal_profile: "ref_gpx_proposal_v1",
    review_requirements: {required_reviewed_day_ids: ["D1"],
      required_acknowledgment_uncertainty_ids: [], safety_handoff_required: false},
  },
  permissionBaselineSavedCandidate: {
    version_ref: "candidates/mission_baselines/alpha/versions/one.json",
    version_sha256: HASH.candidate, review_ready: true,
  },
  permissionBaselineCandidates: [],
  permissionBaselineCandidateRef: "",
  permissionBaselineReviewChecks: {candidateSha256: HASH.candidate,
    dayEnds: true, timingUncertainty: true, safetyHandoff: true},
  permissionProjection: {project_id: project, status: "blocked",
    baseline: {baseline_sha256: "old"},
    rebuild: {reviewed_baseline_sha256: HASH.reviewed,
      canonical_snapshot_sha256: HASH.snapshot, evaluator_version: "admission.v1"}},
};
const loadedDataScopes = new Set(["permission"]);
const calls = [];
const timers = [];
const clearedTimers = [];
const reads = [];
window.setTimeout = (_callback, delay) => { timers.push(delay); return timers.length; };
window.clearTimeout = id => { clearedTimers.push(id); };
let catalogPayload = {project_id: project, candidates: []};
let projectionPayload = {project_id: project, status: "ready",
  baseline: {baseline_sha256: HASH.reviewed}};
let postBehavior = async () => ({reviewed_baseline_ref: "outputs/reviewed/one.json",
  workbench_seed_sha256: "e".repeat(64), version_ref: "candidate/new.json",
  version_sha256: "f".repeat(64)});
let getBehavior = async path => path.endsWith("/mission-baseline/candidates")
  ? catalogPayload : projectionPayload;
async function fetch(path, options = {}) {
  const method = options.method || "GET";
  const payload = options.body ? JSON.parse(options.body) : null;
  calls.push({method, path, payload});
  const data = method === "POST"
    ? await postBehavior(path, payload)
    : await getBehavior(path);
  return {ok: true, status: 200, json: async () => data};
}
const fetchFirstPretripJson = (factory, options) => fetchJson(factory(project), options);
const loadPermissionBaselineMapContext = async () => ({});
async function loadDataScope(scope, options) {
  reads.push({scope, options});
  assert.equal(scope, "permission");
  return loadPermissionData();
}
function acceptedRow(overrides = {}) {
  return {...state.permissionBaselineSavedCandidate, accepted: true, ...overrides};
}
function transportLost() { throw new Error("transport disconnected after request"); }
function readLost() { throw new Error("projection read unavailable"); }
function postCount() { return calls.filter(call => call.method === "POST").length; }
function changeReviewCheck(name, checked) {
  const input = reviewInputs.find(item => item.dataset.permissionReviewCheck === name);
  input.checked = checked;
  input.listeners.change();
}
function summary() {
  return {status: state.permissionBaselineStatus,
    pending: state.permissionBaselinePendingAction,
    busy: state.permissionBaselineBusy, calls, timers, clearedTimers, reads};
}
"""
    program = (
        "const vm = require('node:vm');\n"
        "const assert = require('node:assert/strict');\n"
        "const {webcrypto} = require('node:crypto');\n"
        "const context = vm.createContext({assert, TextEncoder, AbortController,\n"
        "  window: {crypto: webcrypto}, console: {log() { throw Error('unexpected log'); }}});\n"
        f"const source = {json.dumps(setup + source + '(async () => {' + probe + '})()')};\n"
        "Promise.resolve(vm.runInContext(source, context, {timeout: 5000}))\n"
        ".then(result => process.stdout.write(JSON.stringify(result)))\n"
        ".catch(error => { process.stderr.write(String(error.stack || error)); process.exitCode = 1; });\n"
    )
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30,
        # The VM has no require/process/filesystem/network. Do not forward NODE_OPTIONS.
        env={"PATH": str(Path(node).parent), "TZ": "UTC"},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize("kind", ["save", "save_patch", "accept", "rebuild"])
def test_baseline_command_key_survives_fresh_vm_and_pending_key_change(kind) -> None:
    keys = []
    for previous_key in ["first-page-key", "new-key-after-reload"]:
        result = _run(
            f"const pending = {{kind: {json.dumps(kind)}, idempotencyKey: {json.dumps(previous_key)}}};"
            f"await postPermissionBaselineCommand(project, pending, '/baseline-command', {{"
            f"candidate_sha256: HASH.candidate, idempotency_key: {json.dumps(previous_key)}, "
            "explicit_confirmation: true}); return {key: pending.idempotencyKey, "
            "submitted: pending.submitted, calls, timers};"
        )
        keys.append(result["key"])
        assert result["submitted"] is True
        assert result["calls"][0]["payload"]["idempotency_key"] == result["key"]
        assert result["timers"] == []
    assert keys[0] == keys[1]


@pytest.mark.parametrize("change", ["project", "content", "kind"])
def test_command_key_changes_when_immutable_command_identity_changes(change) -> None:
    result = _run(
        "const one = {kind: 'accept'}; const two = {kind: 'accept'};"
        "const payload = {candidate_sha256: HASH.candidate, explicit_confirmation: true};"
        "await postPermissionBaselineCommand(project, one, '/command', payload);"
        + {
            "project": "project = 'workspace-b';",
            "content": "payload.candidate_sha256 = '9'.repeat(64);",
            "kind": "two.kind = 'rebuild';",
        }[change]
        + "await postPermissionBaselineCommand(project, two, '/command', payload);"
        "return {one: one.idempotencyKey, two: two.idempotencyKey};"
    )
    assert result["one"] != result["two"]


def test_unlimited_timeout_is_scoped_to_baseline_commands() -> None:
    result = _run("""
await postJson('/ordinary-command', {value: 1});
await postPermissionBaselineCommand(project, {kind: 'accept'}, '/baseline-command',
  {candidate_sha256: HASH.candidate});
return {timers, clearedTimers, calls};
""")
    assert result["timers"] == [20000]
    assert result["clearedTimers"] == [1]
    assert [call["path"] for call in result["calls"]] == [
        "/ordinary-command", "/baseline-command"
    ]


def test_busy_submit_suppresses_duplicate_command_while_post_is_pending() -> None:
    result = _run("""
let release, started;
const inFlight = new Promise(resolve => { started = resolve; });
postBehavior = () => { started(); return new Promise(resolve => { release = resolve; }); };
const first = submitPermissionBaselineWrite();
await inFlight;
assert.equal(state.permissionBaselineBusy, true);
await submitPermissionBaselineWrite();
assert.equal(postCount(), 1);
release({reviewed_baseline_ref: 'outputs/reviewed/one.json'});
await first;
return summary();
""")
    assert result["busy"] is False
    assert len([c for c in result["calls"] if c["method"] == "POST"]) == 1


@pytest.mark.parametrize("kind", ["accept", "rebuild"])
def test_post_receipt_survives_failed_display_reload(kind) -> None:
    result = _run(
        f"state.permissionBaselinePendingAction.kind = {json.dumps(kind)};"
        "getBehavior = readLost; await submitPermissionBaselineWrite(); return summary();"
    )
    assert "write completed" in result["status"]
    assert "refresh incomplete" in result["status"]
    assert result["pending"] is None
    assert result["busy"] is False


def test_transport_loss_recovers_only_fresh_exact_accepted_candidate() -> None:
    result = _run("""
postBehavior = transportLost;
catalogPayload.candidates = [acceptedRow()];
await submitPermissionBaselineWrite();
return summary();
""")
    assert "Saved review recovered and verified" in result["status"]
    assert result["pending"] is None
    assert any(c["path"].endswith("/mission-baseline/candidates") for c in result["calls"])


@pytest.mark.parametrize("mismatch", ["version_ref", "version_sha256", "not_accepted", "workspace"])
def test_accept_recovery_rejects_nonmatching_catalog_evidence(mismatch) -> None:
    change = {
        "version_ref": "row.version_ref = 'candidate/other-version.json';",
        "version_sha256": "row.version_sha256 = '8'.repeat(64);",
        "not_accepted": "row.accepted = false;",
        "workspace": "catalogPayload.project_id = 'workspace-b';",
    }[mismatch]
    result = _run(
        "postBehavior = transportLost; const row = acceptedRow(); "
        + change
        + "catalogPayload.candidates = [row]; await submitPermissionBaselineWrite(); return summary();"
    )
    assert "Write outcome unconfirmed" in result["status"]
    assert "recovered" not in result["status"]
    assert result["pending"] is not None


@pytest.mark.parametrize("status", ["ready", "degraded"])
def test_transport_loss_recovers_exact_current_rebuilt_baseline(status) -> None:
    result = _run(
        "state.permissionBaselinePendingAction.kind = 'rebuild'; postBehavior = transportLost;"
        f"projectionPayload.status = {json.dumps(status)};"
        "await submitPermissionBaselineWrite(); return summary();"
    )
    assert "Rebuilt projection recovered and verified" in result["status"]
    assert result["pending"] is None


@pytest.mark.parametrize("mismatch", ["project", "baseline", "status"])
def test_rebuild_recovery_rejects_nonmatching_projection(mismatch) -> None:
    change = {
        "project": "projectionPayload.project_id = 'workspace-b';",
        "baseline": "projectionPayload.baseline.baseline_sha256 = '7'.repeat(64);",
        "status": "projectionPayload.status = 'blocked';",
    }[mismatch]
    result = _run(
        "state.permissionBaselinePendingAction.kind = 'rebuild'; postBehavior = transportLost;"
        + change
        + "await submitPermissionBaselineWrite(); return summary();"
    )
    assert "Write outcome unconfirmed" in result["status"]
    assert "recovered" not in result["status"]
    assert result["pending"] is not None


@pytest.mark.parametrize("kind", ["accept", "rebuild"])
def test_failed_reconciliation_read_cannot_promote_cached_old_success(kind) -> None:
    result = _run(
        f"state.permissionBaselinePendingAction.kind = {json.dumps(kind)};"
        "state.permissionBaselineCandidates = [acceptedRow()];"
        "state.permissionProjection = {...state.permissionProjection, status: 'ready', "
        "baseline: {baseline_sha256: HASH.reviewed}};"
        "postBehavior = transportLost; getBehavior = readLost;"
        "await submitPermissionBaselineWrite(); return summary();"
    )
    assert "Write outcome unconfirmed" in result["status"]
    assert "recovered" not in result["status"]
    assert result["pending"] is not None


def test_project_switch_during_command_cannot_publish_previous_project_recovery() -> None:
    result = _run("""
let rejectPost, started;
const inFlight = new Promise(resolve => { started = resolve; });
postBehavior = () => { started(); return new Promise((_resolve, reject) => { rejectPost = reject; }); };
const operation = submitPermissionBaselineWrite();
await inFlight;
project = 'workspace-b';
state.permissionBaselineStatus = 'workspace-b untouched';
state.permissionBaselineCandidates = [acceptedRow()];
rejectPost(new Error('old project transport failed'));
await operation;
return summary();
""")
    assert result["status"] == "workspace-b untouched"
    assert result["reads"] == []


def test_close_before_submit_sends_nothing() -> None:
    result = _run("closePermissionBaselineConfirmation(); return summary();")
    assert "before submission" in result["status"]
    assert result["calls"] == []
    assert result["pending"] is None


def test_close_after_post_started_does_not_claim_cancellation_prevented_write() -> None:
    result = _run("""
let release, started;
const inFlight = new Promise(resolve => { started = resolve; });
postBehavior = () => { started(); return new Promise(resolve => { release = resolve; }); };
const operation = submitPermissionBaselineWrite();
await inFlight;
closePermissionBaselineConfirmation();
const closedStatus = state.permissionBaselineStatus;
release({reviewed_baseline_ref: 'outputs/reviewed/one.json'});
await operation;
return {closedStatus, ...summary()};
""")
    assert "may still complete" in result["closedStatus"]
    assert "no command sent" not in result["closedStatus"]
    assert "appended" in result["status"]


def test_close_during_submit_hashing_does_not_claim_no_command_will_run() -> None:
    result = _run("""
let releaseHash;
sha256Hex = () => new Promise(resolve => { releaseHash = resolve; });
const operation = submitPermissionBaselineWrite();
assert.equal(state.permissionBaselineBusy, true);
closePermissionBaselineConfirmation();
const closedStatus = state.permissionBaselineStatus;
releaseHash('1'.repeat(64));
await operation;
return {closedStatus, ...summary()};
""")
    posts = [call for call in result["calls"] if call["method"] == "POST"]
    assert not posts or "no command sent" not in result["closedStatus"]


def _review_inputs(html: str) -> dict[str, dict[str, str | None]]:
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.controls = {}

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "input" and "data-permission-review-check" in attributes:
                self.controls[attributes["data-permission-review-check"]] = attributes

    parser = Inputs()
    parser.feed(html)
    return parser.controls


@pytest.mark.parametrize("readiness", ["stale", "null", "string_true", "numeric_one", "missing"])
def test_unready_candidate_disables_quick_review_and_preserves_source_error(readiness) -> None:
    change = {
        "stale": "state.permissionBaselineSavedCandidate.review_ready = false;",
        "null": "state.permissionBaselineSavedCandidate.review_ready = null;",
        "string_true": "state.permissionBaselineSavedCandidate.review_ready = 'true';",
        "numeric_one": "state.permissionBaselineSavedCandidate.review_ready = 1;",
        "missing": "delete state.permissionBaselineSavedCandidate.review_ready;",
    }[readiness]
    result = _run(change + """
state.permissionBaselineDraft.review_requirements.required_acknowledgment_uncertainty_ids = ['gap-1'];
state.permissionBaselineDraft.review_requirements.safety_handoff_required = true;
state.permissionBaselineStatus = 'source_stale: selected source hash changed';
const before = JSON.stringify(state.permissionBaselineReviewChecks);
const html = renderPermissionBaselineQuickReview();
changeReviewCheck('dayEnds', false);
changeReviewCheck('timingUncertainty', false);
changeReviewCheck('safetyHandoff', false);
return {html, complete: permissionBaselineReviewComplete(),
  unchanged: before === JSON.stringify(state.permissionBaselineReviewChecks),
  status: state.permissionBaselineStatus, renders, calls};
""")
    assert result["complete"] is False
    assert "not ready for review" in result["html"]
    controls = _review_inputs(result["html"])
    assert set(controls) == {"dayEnds", "timingUncertainty", "safetyHandoff"}
    assert all("disabled" in attrs and "checked" not in attrs for attrs in controls.values())
    assert result["unchanged"] is True
    assert result["status"] == "source_stale: selected source hash changed"
    assert result["renders"] == 0
    assert result["calls"] == []


def test_quick_review_rejects_checks_bound_to_different_candidate_hash() -> None:
    result = _run("""
state.permissionBaselineReviewChecks.candidateSha256 = '9'.repeat(64);
state.permissionBaselineStatus = 'candidate hash changed; review required';
const before = JSON.stringify(state.permissionBaselineReviewChecks);
const html = renderPermissionBaselineQuickReview();
changeReviewCheck('dayEnds', false);
return {html, complete: permissionBaselineReviewComplete(),
  unchanged: before === JSON.stringify(state.permissionBaselineReviewChecks),
  status: state.permissionBaselineStatus, renders};
""")
    assert result["complete"] is False
    assert "Review complete" not in result["html"]
    assert "disabled" in _review_inputs(result["html"])["dayEnds"]
    assert "checked" not in _review_inputs(result["html"])["dayEnds"]
    assert result["unchanged"] is True
    assert result["status"] == "candidate hash changed; review required"
    assert result["renders"] == 0


@pytest.mark.parametrize(
    "checks,uncertainty_required,handoff_required,complete",
    [
        ({"dayEnds": True}, False, False, True),
        ({"dayEnds": False}, False, False, False),
        ({"dayEnds": "true"}, False, False, False),
        ({"dayEnds": True, "timingUncertainty": False}, True, False, False),
        ({"dayEnds": True, "timingUncertainty": True}, True, False, True),
        ({"dayEnds": True, "safetyHandoff": False}, False, True, False),
        ({"dayEnds": True, "timingUncertainty": True, "safetyHandoff": True}, True, True, True),
    ],
    ids=["day_only", "day_unchecked", "day_not_boolean", "gap_unchecked", "gap_checked", "handoff_unchecked", "all_required_checked"],
)
def test_current_candidate_requires_exact_applicable_review_checks(
    checks, uncertainty_required, handoff_required, complete
) -> None:
    result = _run(
        f"state.permissionBaselineReviewChecks = {{candidateSha256: HASH.candidate, ...{json.dumps(checks)}}};"
        "state.permissionBaselineDraft.review_requirements = "
        + json.dumps({
            "required_reviewed_day_ids": ["D1"],
            "required_acknowledgment_uncertainty_ids": ["gap-1"] if uncertainty_required else [],
            "safety_handoff_required": handoff_required,
        })
        + "; return {complete: permissionBaselineReviewComplete(), html: renderPermissionBaselineQuickReview()};"
    )
    assert result["complete"] is complete
    controls = _review_inputs(result["html"])
    assert all("disabled" not in attrs for attrs in controls.values())
    assert ("timingUncertainty" in controls) is uncertainty_required
    assert ("safetyHandoff" in controls) is handoff_required
    assert ("Review complete for this candidate hash" in result["html"]) is complete


def test_current_quick_review_change_handler_updates_only_required_checks() -> None:
    result = _run("""
state.permissionBaselineDraft.review_requirements = {
  required_reviewed_day_ids: ['D1'], required_acknowledgment_uncertainty_ids: ['gap-1'],
  safety_handoff_required: true,
};
resetPermissionBaselineReviewChecks(HASH.candidate);
const steps = [];
for (const name of ['dayEnds', 'timingUncertainty', 'safetyHandoff']) {
  changeReviewCheck(name, true);
  steps.push({complete: permissionBaselineReviewComplete(), status: state.permissionBaselineStatus});
}
changeReviewCheck('dayEnds', false);
return {steps, complete: permissionBaselineReviewComplete(),
  status: state.permissionBaselineStatus, renders, calls};
""")
    assert [step["complete"] for step in result["steps"]] == [False, False, True]
    assert "Ready for Permission acceptance" in result["steps"][-1]["status"]
    assert result["complete"] is False
    assert result["status"] == "Quick review updated · no write performed."
    assert result["renders"] == 4
    assert result["calls"] == []
