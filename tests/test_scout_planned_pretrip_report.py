"""Section 18.2 report evidence: six exact artifacts, real readiness, unknowns."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scout_contextual_permission_tool import assess_scout_contextual_permission
from scout_planned_pretrip_report import build_planned_pretrip_report, ROLES
from scout_planned_route_artifacts import canonical_bytes
from scout_planned_route_models import PlannedRouteConflict


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(root, ref, value):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))
    return _sha(path.read_bytes())


def _binding():
    return {"project_id": "report_fixture", "version_id": "plan." + "a" * 24,
            "manifest_sha256": "a" * 64, "geometry_sha256": "b" * 64, "itinerary_sha256": "c" * 64,
            "review_context_revision_id": "context." + "d" * 24, "review_context_sha256": "d" * 64,
            "producer_version": "fixture", "candidate_only": True, "runtime_safety_truth": False}


@pytest.fixture
def analysis(tmp_path):
    run = tmp_path / "attempt"
    root = run / "workspaces/analysis"
    root.mkdir(parents=True)
    binding = _binding()
    base_binding = {k: binding[k] for k in ("project_id", "version_id", "manifest_sha256", "geometry_sha256", "itinerary_sha256")}
    # These deliberately misleading old defaults must never enter the real assessor.
    _json(root, "project.json", {"project_id": "report_fixture", "readiness_report_ref": "inputs/golden_blocked.json"})
    _json(root, "inputs/golden_blocked.json", {"status": "blocked", "findings": [{"severity": "blocker", "message": "OLD GOLDEN"}]})
    _json(root, "outputs/readiness_report.json", {"status": "blocked", "findings": [{"severity": "blocker", "message": "OLD FALLBACK"}]})
    axis = [{"point_index": 0, "lat": 23., "lon": 121., "route_order_m": 0},
            {"point_index": 1, "lat": 23.01, "lon": 121.01, "route_order_m": 1500},
            {"point_index": 2, "lat": 23.02, "lon": 121.02, "route_order_m": 3000}]
    nodes = [{"candidate_id": "cp.0", "point_index": 0, "label": "起點", "arrival_at": "2026-09-10T06:00:00+08:00", "departure_at": "2026-09-10T06:00:00+08:00"},
             {"candidate_id": "cp.1", "point_index": 1, "label": "休息 CP", "arrival_at": "2026-09-10T07:00:00+08:00", "departure_at": "2026-09-10T07:20:00+08:00"},
             {"candidate_id": "cp.2", "point_index": 2, "label": "交通接點", "arrival_at": "2026-09-10T08:20:00+08:00", "departure_at": "2026-09-10T08:20:00+08:00"}]
    edges = [{"candidate_id": f"seg.{i}", "start_point_index": i, "end_point_index": i + 1,
              "from_candidate_id": f"cp.{i}", "to_candidate_id": f"cp.{i+1}", "distance_m": 1500,
              "expected_duration_minutes": 60, "requires_daylight": True,
              "retreat_available": True, "water_available": False, "signal_expected": True} for i in range(2)]
    itinerary = {"days": [{"day_id": "D1", "start_point_index": 0, "end_point_index": 2,
                           "departure_at": "2026-09-10T06:00:00+08:00", "arrival_at": "2026-09-10T08:20:00+08:00"}],
                 "timeline": [{"kind": "fixed_stop", "point_index": 1, "duration_minutes": 20,
                               "arrival_at": "2026-09-10T07:00:00+08:00", "departure_at": "2026-09-10T07:20:00+08:00"}]}
    eta = {"input_binding": base_binding, "assumption": {"target_eta": "2026-09-10T08:20:00+08:00"},
           "estimates": [{"to_node_id": n["candidate_id"], "eta": n["arrival_at"]} for n in nodes]}
    day_ref = "inputs/planned_review_context/evidence/daylight.json"
    day_sha = _json(root, day_ref, {"date": "2026-09-10", "daylight": {
        "sunrise": "2026-09-10T05:30:00+08:00", "sunset": "2026-09-10T18:10:00+08:00"}})
    context = {"status": "ready", "context_revision_id": binding["review_context_revision_id"], "context_sha256": binding["review_context_sha256"],
               "context_file_ref": "reviews/planned_context.json", "context_file_sha256": "e" * 64,
               "missing_inputs": [], "transport": {"mode": "bus", "latest_return_at": "2026-09-10T09:00:00+08:00",
                   "return_limit_point_index": 2, "turnaround_point_index": 1, "turnaround_at": "2026-09-10T08:00:00+08:00"},
               "goals": ["訓練"], "readiness": {"team_slowest_basis_confirmed": True, "departure_time_confirmed": True,
                                                  "equipment_confirmed": True, "remote_contact_confirmed": True},
               "checkpoint_reviews": [{"point_index": 1, "review": {"status": "reviewed", "evidence_ids": ["map.review"]},
                   "stop_suitability": "candidate", "retreat_available": True}],
               "assessor_kwargs": {"permission": [{"point_index": 1, "review": {
                   "weather_review": {"status": "reviewed"}, "daylight_review": {"status": "reviewed"}}}]},
               "pretrip_input_bundle": {"team_size": 2,
                    "members": [{"member_id": f"member.{i}", "planned_pace_kmh": 2.0,
                                  "experience": "experienced", "experience_level": "experienced", "capability_observed": False} for i in range(2)],
                    "equipment": [{"item": "rain shell", "state": "ready"}],
                    "source_evidence": [{"source_kind": "daylight", "input_ref": day_ref, "sha256": day_sha}]}}
    weather_package = {"input_binding": base_binding, "provider": "test.fixture", "issued_at": "2026-09-10T01:00:00+08:00",
                       "valid_from": "2026-09-10T04:00:00+08:00", "valid_to": "2026-09-10T10:00:00+08:00", "ttl_s": 3600,
                       "date": "2026-09-10", "segments": [{"segmentId": f"seg.{i}"} for i in range(2)],
                       "candidate_only": True, "runtime_safety_truth": False, "human_review_required": True}
    _json(root, "outputs/route_weather_package.json", weather_package)
    permission = assess_scout_contextual_permission(root, action="stop", requested_duration_minutes=20,
        remaining_safety_buffer_minutes=100, weather_reserve_minutes=10, daylight_reserve_minutes=10,
        retreat_reserve_minutes=10, next_segment_uncertainty_minutes=0, slowest_member_reserve_minutes=0)
    assert permission["allowed"] is True and permission["max_duration_minutes"] >= 20
    results = {role: {"decision": "CONDITIONAL_GO"} for role in ROLES}
    results["permission"].update(assessments=[{"event": itinerary["timeline"][0], "assessment": permission}])
    results["weather"].update(matched_segment_count=2, new_package_built=True)
    projections = {}
    for role in ROLES:
        ref = f"projections/{role}.json"
        artifact = {"role": role, "status": "ready", "summary": f"Fixture {role} completed", "missing_inputs": [],
                    "input_binding": binding, "result": results[role], "generated_at": "2026-09-10T02:00:00+00:00",
                    "candidate_only": True, "runtime_safety_truth": False}
        sha = _json(run, ref, artifact)
        projections[role] = {key: artifact[key] for key in ("role", "status", "summary", "missing_inputs", "input_binding", "candidate_only", "runtime_safety_truth")}
        projections[role].update(artifact_ref=ref, artifact_sha256=sha)
    inputs = {"subject_binding": base_binding, "graph": {"input_binding": base_binding, "nodes": nodes, "edges": edges, "gaps": []},
              "route_axis": axis, "route_summary": {"distance_m": 3000, "route_name": "Fixture Planned"},
              "itinerary": itinerary, "planned_eta": eta, "review_context": context, "input_hashes": {day_ref: day_sha}}
    return root, run, inputs, projections, binding


def _build(analysis):
    root, run, inputs, projections, binding = analysis
    return build_planned_pretrip_report(root, inputs, projections, binding=binding, run_root=run)


def _change_projection(analysis, role, **changes):
    _, run, _, projections, _ = analysis
    current = projections[role]
    payload = json.loads((run / current["artifact_ref"]).read_bytes())
    payload.update(changes)
    current["artifact_sha256"] = _json(run, current["artifact_ref"], payload)
    for key in ("status", "summary", "missing_inputs", "input_binding", "candidate_only", "runtime_safety_truth"):
        if key in changes:
            current[key] = changes[key]


def test_full_report_uses_real_readiness_and_contains_all_section18_outputs(analysis):
    root, run, inputs, projections, binding = analysis
    old = (root / "outputs/readiness_report.json").read_bytes()
    result = _build(analysis)
    report = result["report"]
    assert result["status"] == "ready", report["missing_inputs"]
    assert result["decision"] == "CONDITIONAL_GO"
    assert report["input_binding"] == binding
    assert set(report["required_outputs"]) == {"pretrip_decision", "top_risk_sources", "required_conditions", "cp_graph", "latest_turnaround",
        "suggested_stop_points", "not_recommended_stop_points", "alternatives_or_short_routes", "pretrip_checklist", "residual_risk"}
    assert report["required_outputs"]["cp_graph"]["nodes"] == inputs["graph"]["nodes"]
    assert not report["required_outputs"]["cp_graph"]["reviewed_mission_graph"]
    assert report["required_outputs"]["latest_turnaround"]["point_index"] == 1
    assert report["required_outputs"]["latest_turnaround"]["basis"] == "declared_planning_constraint"
    assert report["return_constraint"]["comparison_status"] == "within_declared_limit"
    assert report["required_outputs"]["suggested_stop_points"][0]["checkpoint_id"] == "cp.1"
    assert report["required_outputs"]["suggested_stop_points"][0]["requested_duration_minutes"] == 20
    assert report["short_route_candidates"][0]["complete_return_route"] is False
    assert report["short_route_candidates"][0]["source_point_range"] == [0, 1]
    assert report["provenance"]["projection_hashes"] == {role: p["artifact_sha256"] for role, p in projections.items()}
    assert not report["decision_limits"]["autonomous_departure_allowed"] and not report["departure_approval_granted"]
    assert _sha((run / result["artifact_ref"]).read_bytes()) == result["artifact_sha256"]
    legacy = json.loads((run / report["provenance"]["readiness_assessor_ref"]).read_bytes())
    assert legacy["readiness_assessor"]["tool_id"] == "scout.ai.route_readiness.assess.v0"
    assert legacy["readiness_assessor"]["route_state"]["checkpoint_count"] == 3
    assert legacy["readiness_assessor"]["route_state"]["segment_count"] == 2
    assert all("golden" not in str(s).lower() for s in legacy["readiness_assessor"]["source_report"])
    assert (root / "outputs/readiness_report.json").read_bytes() == old
    assert _build(analysis)["artifact_sha256"] == result["artifact_sha256"]  # deterministic same-attempt replay


def test_unknown_segment_never_becomes_complete_eta_or_turnaround(analysis):
    _, _, inputs, _, _ = analysis
    inputs["graph"]["edges"][1]["expected_duration_minutes"] = None
    inputs["review_context"]["transport"].pop("turnaround_at")
    inputs["review_context"]["transport"].pop("turnaround_point_index")
    result = _build(analysis)
    report = result["report"]
    assert result["status"] == "partial" and result["decision"] in {"DELAY", "NO_GO"}
    assert report["planned_timetable"]["assumption"]["target_eta"] is None
    assert report["required_outputs"]["latest_turnaround"]["deadline"] is None
    assert report["return_constraint"]["planned_arrival_at"] is None
    codes = {m["code"] for m in report["missing_inputs"]}
    assert {"planned_full_eta", "planned_return_eta", "planned_turnaround_limit"} <= codes


def test_declared_transport_conflict_forces_plan_change_or_no_go(analysis):
    analysis[2]["review_context"]["transport"]["latest_return_at"] = "2026-09-10T08:05:00+08:00"
    result = _build(analysis)
    assert result["decision"] in {"NO_GO", "CHANGE_PLAN"}
    assert result["report"]["return_constraint"]["conflict"]
    assert any(m["code"] == "planned_transport_conflict" for m in result["report"]["missing_inputs"])


def test_partial_six_force_keeps_role_source_and_exact_missing_reason(analysis):
    _change_projection(analysis, "weather", status="partial", missing_inputs=[{"code": "forecast_spatiotemporal_coverage", "reason": "No forecast for segment 1.", "segment_id": "seg.1"}])
    result = _build(analysis)
    assert result["status"] == "partial" and result["decision"] == "DELAY"
    risk = next(r for r in result["report"]["risk_sources"] if r["code"] == "forecast_spatiotemporal_coverage")
    assert risk["role"] == "weather" and risk["target"]["segment_id"] == "seg.1"
    assert risk["source_sha256"] == analysis[3]["weather"]["artifact_sha256"]


def test_missing_declarations_do_not_use_golden_ready_defaults(analysis):
    analysis[2]["review_context"]["readiness"] = {}
    result = _build(analysis)
    assert result["status"] == "partial" and result["decision"] == "DELAY"
    codes = {m["code"] for m in result["report"]["missing_inputs"]}
    assert "planned_readiness_departure_time_confirmed" in codes
    assert "planned_readiness_remote_contact_confirmed" in codes


def test_explicit_false_equipment_confirmation_is_not_hidden_by_legacy_defaults(analysis):
    analysis[2]["review_context"]["readiness"]["equipment_confirmed"] = False
    report = _build(analysis)["report"]
    assert any(m["code"] == "planned_readiness_equipment_confirmed" for m in report["missing_inputs"])
    item = next(c for c in report["required_outputs"]["pretrip_checklist"] if c["item"] == "equipment_confirmed")
    assert item["status"] == "not_confirmed"


def test_unreviewed_camp_does_not_inherit_flat_terrain_as_water_or_legal_use(analysis):
    inputs = analysis[2]
    inputs["itinerary"]["timeline"][0].update(kind="camp", duration_minutes=720)
    inputs["review_context"]["checkpoint_reviews"][0].update(camp_suitability="candidate")
    report = _build(analysis)["report"]
    assert report["camp_candidates"][0]["status"] == "needs_review"
    assert not report["camp_candidates"][0]["checks"]["water_confirmed"]
    assert not report["camp_candidates"][0]["checks"]["legal_use_confirmed"]
    assert report["required_outputs"]["not_recommended_stop_points"][0]["policy"] == "camp_conditions_unresolved"


def test_declared_reviewed_camp_stays_candidate_only(analysis):
    inputs = analysis[2]
    inputs["itinerary"]["timeline"][0].update(kind="camp", duration_minutes=720)
    inputs["review_context"]["checkpoint_reviews"][0].update(camp_suitability="candidate", water_available=True,
                                                              campsite_legal_use=True, campsite_capacity=2)
    report = _build(analysis)["report"]
    assert report["camp_candidates"][0]["status"] == "reviewed_candidate"
    assert report["camp_candidates"][0]["site_verified_for_actual_overnight"] is False


@pytest.mark.parametrize("fault", ["missing_role", "wrong_hash", "foreign_version", "wrong_context", "authority", "compact_mismatch"])
def test_invalid_projection_never_produces_final_report(analysis, fault):
    root, run, inputs, projections, binding = analysis
    if fault == "missing_role":
        del projections["navigation"]
    elif fault == "wrong_hash":
        projections["navigation"]["artifact_sha256"] = "f" * 64
    elif fault in {"foreign_version", "wrong_context"}:
        other = deepcopy(binding)
        other["version_id" if fault == "foreign_version" else "review_context_sha256"] = "plan." + "f" * 24 if fault == "foreign_version" else "f" * 64
        _change_projection(analysis, "navigation", input_binding=other)
    elif fault == "authority":
        _change_projection(analysis, "navigation", runtime_safety_truth=True)
    else:
        projections["navigation"]["summary"] = "Caller tried to swap summary"
    with pytest.raises(PlannedRouteConflict):
        _build(analysis)
    assert not (run / "reports/planned_pretrip_report.json").exists()


def test_modified_review_input_file_is_rejected(analysis):
    root, _, inputs, _, _ = analysis
    ref = next(iter(inputs["input_hashes"]))
    (root / ref).write_text("changed source data")
    with pytest.raises(PlannedRouteConflict) as raised:
        _build(analysis)
    assert raised.value.code == "planned_pretrip_input_hash"


def test_changed_projection_during_readiness_does_not_publish(analysis, monkeypatch):
    import scout_route_readiness_tool
    original = scout_route_readiness_tool.assess_scout_route_readiness
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        (analysis[1] / analysis[3]["pace_fit"]["artifact_ref"]).write_text("changed during actual assessor call")
        return result
    monkeypatch.setattr(scout_route_readiness_tool, "assess_scout_route_readiness", changing)
    with pytest.raises(PlannedRouteConflict) as raised:
        _build(analysis)
    assert raised.value.code == "planned_pretrip_projection_hash"
    assert not (analysis[1] / "reports/planned_pretrip_report.json").exists()


def test_daylight_human_review_requires_actual_dated_sun_windows(analysis):
    root, _, inputs, _, _ = analysis
    ref = next(iter(inputs["input_hashes"]))
    sha = _json(root, ref, {"description": "A human said daylight is fine; no sun window"})
    inputs["input_hashes"][ref] = sha
    inputs["review_context"]["pretrip_input_bundle"]["source_evidence"][0]["sha256"] = sha
    report = _build(analysis)["report"]
    assert any(m["code"] == "planned_daylight_review" for m in report["missing_inputs"])


def test_daylight_required_trip_outside_window_keeps_conflict(analysis):
    root, _, inputs, _, _ = analysis
    ref = next(iter(inputs["input_hashes"]))
    sha = _json(root, ref, {"date": "2026-09-10", "daylight": {"sunrise": "2026-09-10T07:30:00+08:00", "sunset": "2026-09-10T18:10:00+08:00"}})
    inputs["input_hashes"][ref] = sha
    inputs["review_context"]["pretrip_input_bundle"]["source_evidence"][0]["sha256"] = sha
    report = _build(analysis)["report"]
    assert any(m["code"] == "planned_daylight_window_conflict" for m in report["missing_inputs"])
    assert report["decision"] == "DELAY"


def test_known_no_go_is_never_upgraded_by_other_ready_projections(analysis):
    _, run, _, projections, _ = analysis
    payload = json.loads((run / projections["weather"]["artifact_ref"]).read_bytes())
    payload["result"]["decision"] = "NO_GO"
    _change_projection(analysis, "weather", result=payload["result"])
    report = _build(analysis)["report"]
    assert report["decision"] == "NO_GO"
    assert report["required_outputs"]["top_risk_sources"][0]["role"] == "weather"
    assert not report["departure_approval_granted"]
