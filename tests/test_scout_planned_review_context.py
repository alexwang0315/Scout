"""Real immutable review persistence and assessor-input joins on a saved bundle."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import scout_planned_review_context as review
from scout_planned_route_artifacts import get_planned_version
from scout_planned_route_models import PlannedRouteConflict
from test_scout_planned_route_artifacts import planned, _request, _save, _files


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _setup(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    bundle = get_planned_version(root, saved["version_id"])
    graph = {"input_binding": review.review_context_binding(bundle),
             "nodes": [{"point_index": i, "candidate_id": f"cp.{i}"} for i in range(5)],
             "edges": [{"start_point_index": i, "end_point_index": i + 1, "candidate_id": f"seg.{i}"} for i in range(4)]}
    return root, saved, bundle, graph


def _evidence(root, role, text=None):
    ref = f"review_inputs/{role}.json"
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"fixture": True, "source_kind": role, "text": text or "Declared test evidence"}).encode()
    path.write_bytes(raw)
    return {"evidence_id": role, "ref": ref, "sha256": _sha(raw),
            "source_kind": role, "description": "Deterministic test evidence; not real route knowledge"}


def _statement(evidence_id):
    return {"status": "reviewed", "reviewer_alias": "fixture-reviewer",
            "reviewed_at": "2026-09-10T09:00:00+08:00", "conclusion": "Fixture evidence reviewed for this plan",
            "evidence_ids": [evidence_id]}


def _declaration(root, *, complete=True):
    value = {"declared_by": "fixture-planner", "declared_at": "2026-09-10T08:30:00+08:00"}
    if not complete:
        return value
    evidence = [_evidence(root, role) for role in ("route_condition", "forecast", "daylight", "human_review", "narrative")]
    return {**value, "team_size": 2,
            "members": [{"member_id": "one", "experience": "Fixture mountain experience", "planned_pace_kmh": 3.6},
                        {"member_id": "two", "experience": "Fixture mountain experience", "planned_pace_kmh": 2.7}],
            "equipment": [{"item": "rain shell", "state": "ready", "member_id": "one"}],
            "navigation": {**{key: True for key in review.NAVIGATION_FIELDS}, "team_map_user_count": 2},
            "transport": {"mode": "bus", "latest_return_at": "2026-09-10T19:30:00+08:00", "return_limit_point_index": 4},
            "goals": ["攝影", "依照明示計畫比較"], "evidence": evidence,
            "route_condition_evidence_ids": ["route_condition"],
            "segment_policies": [{"from_point_index": i, "to_point_index": i + 1,
                "requires_daylight": True, "water_available": False, "retreat_available": False, "signal_expected": True,
                "review": _statement("route_condition")} for i in range(4)],
            "checkpoint_reviews": [{"point_index": 1, "water_available": False,
                "stop_suitability": "candidate", "camp_suitability": "unknown", "review": _statement("route_condition")}],
            "permission_reviews": [{"point_index": 1, "remaining_safety_buffer_minutes": 70,
                "weather_reserve_minutes": 15, "daylight_reserve_minutes": 20, "retreat_reserve_minutes": 5,
                "review": _statement("human_review"), "weather_review": _statement("forecast"),
                "daylight_review": _statement("daylight"), "retreat_review": _statement("route_condition")}],
            "narrative": {"briefing_evidence_id": "narrative", "review": _statement("narrative")}}


def _command(saved, declaration, *, key="review.one", parent=None, **updates):
    return review.PlannedReviewContextRequest.model_validate({
        "version_id": saved["version_id"], "expected_manifest_sha256": saved["manifest_sha256"],
        "expected_geometry_sha256": saved["geometry_sha256"], "expected_itinerary_sha256": saved["itinerary_sha256"],
        "expected_parent_revision_id": parent, "idempotency_key": key,
        "declaration": declaration, "explicit_confirmation": True, **updates})


def test_empty_get_is_read_only_and_no_golden_fallback(planned):
    root, saved, bundle, graph = _setup(planned)
    before = _files(root)
    assert review.current_planned_review_context(root, saved["version_id"]) is None
    result = review.materialize_planned_review_inputs(root, bundle, root / "outputs/attempt/analysis", graph)
    assert result["status"] == "missing" and result["project_refs"] == {}
    assert result["assessor_kwargs"]["navigation"] == {}
    assert result["missing_inputs"][0]["code"] == "planned_review_context"
    assert _files(root) == before


def test_complete_saved_review_materializes_real_assessor_inputs_and_source_hashes(planned):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root)
    narrative = next(e for e in declaration["evidence"] if e["evidence_id"] == "narrative")
    narrative_path = root / narrative["ref"]
    narrative_path.write_text(json.dumps({"artifact_kind": "planned_route_context_briefing",
        "subject_binding": review.review_context_binding(bundle), "candidate_only": True,
        "runtime_safety_truth": False, "sections": [{"title": "Fixture same-version briefing"}]}))
    narrative["sha256"] = _sha(narrative_path.read_bytes())
    before = _files(root)
    context = review.save_planned_review_context(root, _command(saved, declaration))
    assert context["candidate_only"] and not context["runtime_safety_truth"]
    assert not context["departure_approval_granted"] and not context["recorded_track"]
    after_save = _files(root)
    assert all(after_save[ref] == sha for ref, sha in before.items())
    assert review.current_planned_review_context(root, saved["version_id"])["context_sha256"] == context["context_sha256"]
    assert _files(root) == after_save
    target = root.parent / "isolated_analysis"
    result = review.materialize_planned_review_inputs(root, bundle, target, graph, context)
    assert _files(root) == after_save
    assert result["status"] == "ready" and result["missing_inputs"] == []
    assert result["subject_binding"]["review_context_sha256"] == context["context_sha256"]
    assert result["assessor_kwargs"]["navigation"] == declaration["navigation"]
    assert result["assessor_kwargs"]["pace_fit"]["team_members"][0]["planned_pace_mps"] == 1.0
    assert result["assessor_kwargs"]["pace_fit"]["team_members"][1]["planned_pace_mps"] == .75
    assert not result["assessor_kwargs"]["pace_fit"]["team_members"][0]["capability_observed"]
    assert result["assessor_kwargs"]["permission"][0]["kwargs"]["remaining_safety_buffer_minutes"] == 70
    assert result["assessor_kwargs"]["permission"][0]["kwargs"]["daylight_reserve_minutes"] == 20
    assert result["segment_policy_updates"][0]["requirement"]["water_available"] is False
    assert result["segment_policy_updates"][0]["requirement"]["requires_daylight"] is True
    assert result["narrative"]["briefing_sha256"] == next(e["sha256"] for e in declaration["evidence"] if e["evidence_id"] == "narrative")
    assert result["pretrip_input_bundle"]["transport"]["latest_return_at"].endswith("+08:00")
    assert len(result["pretrip_input_bundle"]["members"]) == 2
    for ref, sha in result["input_hashes"].items():
        assert _sha((target / ref).read_bytes()) == sha
    for source in result["source_report"]:
        assert _sha((root / source["ref"]).read_bytes()) == source["sha256"]
    # Exercise existing actual collectors: positive declarations enter their real parameters.
    (target / "project.json").write_text(json.dumps({"project_id": target.name, **result["project_refs"]}))
    from pretrip_navigation_terrain_collection import collect_pretrip_navigation_terrain
    navigation = collect_pretrip_navigation_terrain(target, dry_run=True, **result["assessor_kwargs"]["navigation"])
    assert navigation["missing_fields"] == []
    from scout_pace_guardian_tool import assess_scout_pace_guardian
    pace = assess_scout_pace_guardian(target, **result["assessor_kwargs"]["pace_fit"])
    assert "team_members" not in pace["missing_fields"]
    from scout_contextual_permission_tool import assess_scout_contextual_permission
    permission = assess_scout_contextual_permission(target, action="stop", requested_duration_minutes=10,
                                                     **result["assessor_kwargs"]["permission"][0]["kwargs"])
    assert "remaining_safety_buffer_minutes" not in permission["missing_fields"]


def test_supplement_revision_keeps_prior_bytes_and_replay_does_not_roll_back(planned):
    root, saved, _, _ = _setup(planned)
    initial = _command(saved, _declaration(root, complete=False))
    first = review.save_planned_review_context(root, initial)
    first_bytes = (root / first["context_ref"]).read_bytes()
    assert review.save_planned_review_context(root, initial)["replayed"]
    second_declaration = _declaration(root)
    second = review.save_planned_review_context(root, _command(saved, second_declaration, key="review.two", parent=first["revision_id"]))
    assert first["revision_id"] != second["revision_id"] and second["parent_revision_id"] == first["revision_id"]
    assert (root / first["context_ref"]).read_bytes() == first_bytes
    before = _files(root)
    replay = review.save_planned_review_context(root, initial)
    assert replay["superseded"] and not replay["is_current"]
    assert review.current_planned_review_context(root, saved["version_id"])["revision_id"] == second["revision_id"]
    assert _files(root) == before
    with pytest.raises(PlannedRouteConflict, match="different review data"):
        review.save_planned_review_context(root, _command(saved, second_declaration))
    with pytest.raises(PlannedRouteConflict, match="newer supplement"):
        review.save_planned_review_context(root, _command(saved, second_declaration, key="stale.parent"))


def test_concurrent_same_parent_allows_only_one_supplement(planned):
    root, saved, _, _ = _setup(planned)
    commands = [_command(saved, _declaration(root, complete=False), key=f"race.{i}") for i in range(2)]
    def save(command):
        try:
            return review.save_planned_review_context(root, command)
        except PlannedRouteConflict as exc:
            return {"error_code": exc.code}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, commands))
    assert sum(r.get("writes_performed") is True for r in results) == 1
    assert sum(r.get("error_code") == "planned_review_parent_changed" for r in results) == 1
    assert len(list((root / review.STORE_REF / saved["version_id"] / "revisions").glob("*.json"))) == 1


@pytest.mark.parametrize("field", ["manifest_sha256", "geometry_sha256", "itinerary_sha256"])
def test_wrong_expected_binding_rejected_before_revision_writes(planned, field):
    root, saved, _, _ = _setup(planned)
    command = _command(saved, _declaration(root, complete=False), **{f"expected_{field}": "e" * 64})
    with pytest.raises(PlannedRouteConflict) as raised:
        review.save_planned_review_context(root, command)
    assert raised.value.code == "planned_review_binding_stale"
    assert not list((root / review.STORE_REF).rglob("revisions/*.json"))


def test_source_change_rejects_load_and_new_save(planned):
    root, saved, _, _ = _setup(planned)
    declaration = _declaration(root)
    context = review.save_planned_review_context(root, _command(saved, declaration))
    (root / declaration["evidence"][0]["ref"]).write_text("changed after review")
    with pytest.raises(PlannedRouteConflict) as raised:
        review.current_planned_review_context(root, saved["version_id"])
    assert raised.value.code == "planned_review_evidence_stale"
    with pytest.raises(PlannedRouteConflict):
        review.save_planned_review_context(root, _command(saved, declaration, key="retry", parent=context["revision_id"]))


def test_changed_original_plan_source_cannot_be_masked_by_review(planned):
    root, saved, _, _ = _setup(planned)
    (root / "source.gpx").write_text("different route source")
    with pytest.raises(PlannedRouteConflict) as raised:
        review.save_planned_review_context(root, _command(saved, _declaration(root, complete=False)))
    assert raised.value.code == "planned_review_sources_stale"


@pytest.mark.parametrize("ref", ["../outside.json", "/tmp/outside.json", ".env", "reviews/.env.production", "secrets/key.json", "inputs/private.pem", "reviews\\x.json"])
def test_secret_or_escaping_evidence_refs_are_rejected_by_schema(ref):
    with pytest.raises(ValidationError):
        review.ReviewEvidenceRef(evidence_id="bad", ref=ref, sha256="a" * 64, source_kind="human_review", description="bad source")


def test_symlinked_evidence_never_read(planned):
    root, saved, _, _ = _setup(planned)
    declaration = _declaration(root, complete=False)
    outside = root.parent / "outside.json"
    outside.write_text("private unrelated input")
    (root / "symlink.json").symlink_to(outside)
    declaration["evidence"] = [{"evidence_id": "s", "ref": "symlink.json", "sha256": _sha(outside.read_bytes()),
        "source_kind": "human_review", "description": "symlink must be rejected"}]
    with pytest.raises(PlannedRouteConflict):
        review.save_planned_review_context(root, _command(saved, declaration))


def test_pending_or_rejected_review_never_populates_assessor_policy(planned):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root)
    declaration["segment_policies"][0]["review"] = {"status": "pending"}
    declaration["permission_reviews"][0]["review"] = {"status": "pending"}
    declaration["permission_reviews"][0]["weather_review"] = {**_statement("forecast"), "status": "rejected"}
    declaration["navigation"]["offline_map_downloaded"] = False
    declaration["navigation"]["gpx_loaded_on_device"] = None
    review.save_planned_review_context(root, _command(saved, declaration))
    result = review.materialize_planned_review_inputs(root, bundle, root.parent / "isolated", graph)
    assert result["status"] == "partial"
    assert result["assessor_kwargs"]["navigation"]["offline_map_downloaded"] is False
    assert "gpx_loaded_on_device" not in result["assessor_kwargs"]["navigation"]
    assert result["assessor_kwargs"]["permission"][0]["kwargs"] == {}
    assert all(p["segment_id"] != "seg.0" for p in result["segment_policy_updates"])
    assert any(m["code"] == "planned_permission_weather_review" for m in result["missing_inputs"])


def test_exact_route_occurrence_and_bundle_binding_required(planned):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root)
    bad = deepcopy(declaration)
    bad["checkpoint_reviews"][0]["point_index"] = 5
    with pytest.raises(PlannedRouteConflict, match="outside the saved route axis"):
        review.save_planned_review_context(root, _command(saved, bad))
    review.save_planned_review_context(root, _command(saved, declaration))
    bad_graph = deepcopy(graph)
    bad_graph["input_binding"]["itinerary_sha256"] = "b" * 64
    with pytest.raises(PlannedRouteConflict, match="not bound"):
        review.materialize_planned_review_inputs(root, bundle, root.parent / "isolated", bad_graph)
    gap_graph = deepcopy(graph)
    gap_graph["edges"] = gap_graph["edges"][1:]
    with pytest.raises(PlannedRouteConflict, match="no exact edge"):
        review.materialize_planned_review_inputs(root, bundle, root.parent / "isolated", gap_graph)
    with pytest.raises(PlannedRouteConflict, match="isolated analysis"):
        review.materialize_planned_review_inputs(root, bundle, root, graph)


def test_stale_context_rejected_and_caller_modified_declaration_ignored(planned):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root, complete=False)
    first = review.save_planned_review_context(root, _command(saved, declaration))
    second = review.save_planned_review_context(root, _command(saved, _declaration(root), key="v2", parent=first["revision_id"]))
    with pytest.raises(PlannedRouteConflict, match="no longer current"):
        review.materialize_planned_review_inputs(root, bundle, root.parent / "old", graph, first)
    forged = deepcopy(second)
    forged["declaration"]["members"][0]["planned_pace_kmh"] = 18
    result = review.materialize_planned_review_inputs(root, bundle, root.parent / "new", graph, forged)
    assert result["assessor_kwargs"]["pace_fit"]["team_members"][0]["planned_pace_mps"] == 1.0


def test_crash_after_revision_before_pointer_recovers_same_immutable_bytes(planned, monkeypatch):
    root, saved, _, _ = _setup(planned)
    command = _command(saved, _declaration(root, complete=False))
    original = review._atomic_json
    def crash(*args):
        raise OSError("fixture interruption before current pointer")
    monkeypatch.setattr(review, "_atomic_json", crash)
    with pytest.raises(OSError, match="fixture interruption"):
        review.save_planned_review_context(root, command)
    assert review.current_planned_review_context(root, saved["version_id"]) is None
    revision = next((root / review.STORE_REF).rglob("revisions/*.json"))
    before = revision.read_bytes()
    monkeypatch.setattr(review, "_atomic_json", original)
    restored = review.save_planned_review_context(root, command)
    assert restored["replayed"] and restored["is_current"]
    assert revision.read_bytes() == before


def test_tampered_context_and_wrong_expected_context_hash_fail_closed(planned):
    root, saved, _, _ = _setup(planned)
    context = review.save_planned_review_context(root, _command(saved, _declaration(root, complete=False)))
    with pytest.raises(PlannedRouteConflict, match="changed"):
        review.get_planned_review_context(root, saved["version_id"], expected_context_sha256="f" * 64)
    path = root / context["context_ref"]
    record = json.loads(path.read_text())
    record["runtime_safety_truth"] = True
    path.write_text(json.dumps(record))
    with pytest.raises(PlannedRouteConflict):
        review.current_planned_review_context(root, saved["version_id"])


@pytest.mark.parametrize("mutation", ["naive_time", "bool_string", "missing_source", "bad_weather_kind", "duplicate_member", "fake_review", "nan"])
def test_schema_rejects_untraceable_or_ambiguous_data(planned, mutation):
    root, _, _, _ = _setup(planned)
    declaration = _declaration(root)
    if mutation == "naive_time":
        declaration["declared_at"] = "2026-09-10T08:00:00"
    elif mutation == "bool_string":
        declaration["navigation"]["offline_map_downloaded"] = "false"
    elif mutation == "missing_source":
        declaration["route_condition_evidence_ids"] = ["absent"]
    elif mutation == "bad_weather_kind":
        declaration["permission_reviews"][0]["weather_review"] = _statement("route_condition")
    elif mutation == "duplicate_member":
        declaration["members"][1]["member_id"] = "one"
    elif mutation == "fake_review":
        declaration["segment_policies"][0]["review"] = {"status": "reviewed"}
    elif mutation == "nan":
        declaration["members"][0]["planned_pace_kmh"] = float("nan")
    with pytest.raises(ValidationError):
        review.PlannedReviewDeclaration.model_validate(declaration)


@pytest.mark.parametrize("kind", ["text", "unbound", "foreign_version", "unsafe", "same_version"])
def test_narrative_current_binding_keeps_historical_evidence_separate(planned, kind):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root)
    evidence = next(e for e in declaration["evidence"] if e["evidence_id"] == "narrative")
    path = root / evidence["ref"]
    payload = {"input_binding": review.review_context_binding(bundle), "candidate_only": True, "runtime_safety_truth": False}
    if kind == "text":
        path.write_text("Historical diary: passed a creek and climbed a ridge.")
    elif kind == "unbound":
        path.write_text(json.dumps({"text": "Historical briefing"}))
    else:
        if kind == "foreign_version":
            payload["input_binding"]["version_id"] = "plan." + "a" * 24
        if kind == "unsafe":
            payload["runtime_safety_truth"] = True
        path.write_text(json.dumps(payload))
    evidence["sha256"] = _sha(path.read_bytes())
    review.save_planned_review_context(root, _command(saved, declaration))
    result = review.materialize_planned_review_inputs(root, bundle, root.parent / "isolated", graph)
    assert result["narrative"]["binding_valid"] is (kind == "same_version")
    assert result["narrative"]["briefing_ref"]  # historical source was retained even if not current
    assert any(m["code"] == "planned_narrative_review" for m in result["missing_inputs"]) is (kind != "same_version")


def test_review_cannot_cross_a_geometry_gap(planned, monkeypatch):
    root, saved, bundle, _ = _setup(planned)
    modified = deepcopy(bundle)
    modified["preview"]["route_axis"]["points"] = [{"point_index": i, "break_before": i == 2} for i in range(5)]
    monkeypatch.setattr(review, "_bundle", lambda *_: modified)
    declaration = _declaration(root)
    with pytest.raises(PlannedRouteConflict) as raised:
        review.save_planned_review_context(root, _command(saved, declaration))
    assert raised.value.code == "planned_review_crosses_gap"


def test_another_version_with_same_geometry_does_not_inherit_review(planned):
    root, saved, bundle, graph = _setup(planned)
    first = review.save_planned_review_context(root, _command(saved, _declaration(root, complete=False)))
    _, compiler, _ = planned
    request, _ = _request(root, compiler)
    request = request.model_copy(update={"human_text": "Different plan declaration, same geometry", "parent_version_id": saved["version_id"]})
    second = _save(root, request, compiler(root, request), key="second.plan")
    other = get_planned_version(root, second["version_id"])
    assert other["manifest"]["geometry_sha256"] == bundle["manifest"]["geometry_sha256"]
    assert second["version_id"] != saved["version_id"]
    other_graph = {**graph, "input_binding": review.review_context_binding(other)}
    assert review.current_planned_review_context(root, second["version_id"]) is None
    with pytest.raises(PlannedRouteConflict, match="no longer current"):
        review.materialize_planned_review_inputs(root, other, root.parent / "other", other_graph, first)


@pytest.mark.parametrize("mutation", ["readiness_string", "turnaround_without_point", "naive_turnaround", "turnaround_after_return"])
def test_readiness_and_turnaround_require_explicit_typed_values(planned, mutation):
    root, _, _, _ = _setup(planned)
    declaration = _declaration(root)
    if mutation == "readiness_string":
        declaration["readiness"] = {"equipment_confirmed": "true"}
    elif mutation == "turnaround_without_point":
        declaration["transport"]["turnaround_at"] = "2026-09-10T10:00:00+08:00"
    elif mutation == "naive_turnaround":
        declaration["transport"].update(turnaround_point_index=2, turnaround_at="2026-09-10T10:00:00")
    else:
        declaration["transport"].update(turnaround_point_index=2, turnaround_at="2026-09-10T23:00:00+08:00")
    with pytest.raises(ValidationError):
        review.PlannedReviewDeclaration.model_validate(declaration)


def test_readiness_declaration_reaches_pretrip_bundle_without_becoming_permission(planned):
    root, saved, bundle, graph = _setup(planned)
    declaration = _declaration(root)
    declaration["readiness"] = {"team_slowest_basis_confirmed": True, "departure_time_confirmed": False,
                               "equipment_confirmed": True, "remote_contact_confirmed": None}
    declaration["transport"].update(turnaround_point_index=2, turnaround_at="2026-09-10T10:00:00+08:00")
    review.save_planned_review_context(root, _command(saved, declaration))
    result = review.materialize_planned_review_inputs(root, bundle, root.parent / "readiness_inputs", graph)
    assert result["pretrip_input_bundle"]["readiness"] == declaration["readiness"]
    assert result["readiness"]["departure_time_confirmed"] is False
    assert result["transport"]["turnaround_point_index"] == 2
    assert result["departure_approval_granted"] is False
