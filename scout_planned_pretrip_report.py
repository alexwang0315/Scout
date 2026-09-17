"""Section 18.2 planning report from one Planned revision and six verified results.

The existing deterministic readiness assessor executes in an isolated view with
explicit inputs. Old Golden readiness or mission files cannot enter through its
fallback paths. The resulting recommendation is planning evidence, never an
actual departure approval or live safety fact.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from scout_planned_analysis_inputs import parse_time, safe_path
from scout_planned_route_artifacts import canonical_bytes
from scout_planned_route_models import PlannedRouteConflict


REPORT_VERSION = "plannedPretripReport.v1"
ROLES = ("permission", "pace_fit", "architecture", "navigation", "weather", "route_context")
BINDING_FIELDS = ("project_id", "version_id", "manifest_sha256", "geometry_sha256", "itinerary_sha256",
                  "review_context_revision_id", "review_context_sha256")
BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False, "departure_approval_granted": False,
            "operational": False, "promotion_allowed": False, "recorded_track": False,
            "human_review_required": True}
DECISIONS = {"GO", "CONDITIONAL_GO", "GUIDED_ONLY", "CHANGE_PLAN", "DELAY", "NO_GO", "ESCALATE"}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(root: Path, ref: str) -> dict:
    try:
        payload = json.loads(safe_path(root, ref).read_bytes())
    except (OSError, ValueError, UnicodeError) as exc:
        raise PlannedRouteConflict("planned_pretrip_artifact_invalid", f"Pre-trip input is unavailable or invalid: {ref}") from exc
    if not isinstance(payload, dict):
        raise PlannedRouteConflict("planned_pretrip_artifact_invalid", f"Pre-trip input is not an object: {ref}")
    return payload


def _write(root: Path, ref: str, payload: dict) -> str:
    path = safe_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(payload)
    if path.exists():
        if path.read_bytes() != raw:
            raise PlannedRouteConflict("planned_pretrip_artifact_exists", "A different report input already exists in this immutable attempt.")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return _sha(raw)


def _assert_binding(value: dict, binding: dict, *, context_required: bool = True) -> None:
    keys = BINDING_FIELDS if context_required else BINDING_FIELDS[:5]
    if any(value.get(key) != binding.get(key) for key in keys):
        raise PlannedRouteConflict("planned_pretrip_binding_mismatch", "A pre-trip source belongs to another plan, geometry, timetable or review context.")


def _verified_projections(run_root: Path, projections: dict, binding: dict) -> dict:
    if set(projections) != set(ROLES):
        raise PlannedRouteConflict("planned_pretrip_six_results_required", "The pre-trip report requires all six exact analysis projections, including explicit blocked results.")
    results = {}
    for role in ROLES:
        projection = projections[role]
        sha = projection.get("artifact_sha256", "")
        ref = projection.get("artifact_ref", "")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise PlannedRouteConflict("planned_pretrip_projection_hash", "A six-force result has no valid artifact hash.")
        path = safe_path(run_root, ref)
        if not path.is_file() or _sha(path.read_bytes()) != sha:
            raise PlannedRouteConflict("planned_pretrip_projection_hash", f"The {role} result changed or is unavailable.")
        payload = _load(run_root, ref)
        for record in (projection, payload):
            if record.get("role") != role or record.get("status") not in {"ready", "partial", "blocked"}:
                raise PlannedRouteConflict("planned_pretrip_projection_identity", "A six-force artifact has the wrong role or status.")
            if (record.get("candidate_only") is not True or record.get("runtime_safety_truth") is not False
                    or record.get("departure_approval_granted") is True or record.get("operational") is True):
                raise PlannedRouteConflict("planned_pretrip_projection_authority", "Pre-trip evidence must remain a planning candidate.")
            if record.get("input_binding") != binding:
                raise PlannedRouteConflict("planned_pretrip_binding_mismatch", "The six-force result does not belong to this exact analysis binding.")
        for key in ("status", "missing_inputs", "summary"):
            if projection.get(key) != payload.get(key):
                raise PlannedRouteConflict("planned_pretrip_projection_identity", "Compact and full six-force result records disagree.")
        results[role] = payload
    return results


def _missing(code: str, reason: str, *, role: str = "pretrip", severity: str = "warning", **target) -> dict:
    return {"code": code, "reason": reason, "role": role, "severity": severity, **target}


def _unique(values: list[dict]) -> list[dict]:
    keys = ("role", "code", "segment_id", "day_id", "point_index", "member_id", "item")
    return list({tuple(str(value.get(key, "")) for key in keys): value for value in values}.values())


def _source_roles(results: dict, projections: dict) -> dict:
    return {role: {"role": role, "status": results[role]["status"], "summary": results[role]["summary"],
                   "artifact_ref": projections[role]["artifact_ref"], "artifact_sha256": projections[role]["artifact_sha256"],
                   "decision": results[role].get("result", {}).get("decision"),
                   "missing_inputs": results[role].get("missing_inputs", []), **BOUNDARY} for role in ROLES}


def _timetable(inputs: dict, transport: dict) -> tuple[dict, dict, dict, list[dict]]:
    graph = inputs["graph"]
    nodes = {n["point_index"]: n for n in graph["nodes"]}
    edges = graph["edges"]
    days = inputs.get("itinerary", {}).get("days", [])
    departure = next((d.get("departure_at") for d in days if parse_time(d.get("departure_at"))), None)
    unknown_segments = [e["candidate_id"] for e in edges if e.get("expected_duration_minutes") is None]
    complete = not graph.get("gaps") and not unknown_segments and bool(days)
    arrival = days[-1].get("arrival_at") if days else None
    complete = complete and parse_time(arrival) is not None
    eta = deepcopy(inputs.get("planned_eta", {}))
    assumption = eta.setdefault("assumption", {})
    # The final target is unavailable if any route portion remains unknown.
    assumption["planned_start_time"] = departure
    assumption["target_eta"] = arrival if complete else None
    assumption["team_multiplier_status"] = None
    assumption["turn_back_checkpoint_eta"] = None
    assumption["turn_back_checkpoint_node_name"] = None
    turn_point, turn_time = transport.get("turnaround_point_index"), transport.get("turnaround_at")
    turnaround = {"available": False, "checkpoint_id": None, "point_index": None, "deadline": None,
                  "basis": "unknown", "reason": "No explicit, version-bound turnaround occurrence and deadline were declared."}
    missing = []
    if turn_point is not None or turn_time is not None:
        if turn_point not in nodes or parse_time(turn_time) is None:
            raise PlannedRouteConflict("planned_pretrip_turnaround_invalid", "The turnaround limit must identify an exact CP occurrence and timezone-aware date/time.")
        turnaround = {"available": True, "checkpoint_id": nodes[turn_point]["candidate_id"], "point_index": turn_point,
                      "label": nodes[turn_point].get("label") or nodes[turn_point]["candidate_id"], "deadline": turn_time,
                      "basis": "declared_planning_constraint", "return_path_duration_verified": False,
                      "reason": "A declared cutoff is preserved; it does not prove the reverse route duration."}
        assumption["turn_back_checkpoint_eta"] = turn_time
        assumption["turn_back_checkpoint_node_name"] = turnaround["label"]
    else:
        missing.append(_missing("planned_turnaround_limit", turnaround["reason"]))
    return_point = transport.get("return_limit_point_index")
    deadline = transport.get("latest_return_at")
    return_cp = nodes.get(return_point) if return_point is not None else None
    # Even a stated arrival on the far side of a gap cannot prove return timing.
    if return_cp:
        prior_edges = [e for e in edges if e["end_point_index"] <= return_point]
        prior_gaps = [g for g in graph.get("gaps", []) if g.get("from_point_index", 0) <= return_point]
        return_eta = return_cp.get("arrival_at") if not prior_gaps and all(e.get("expected_duration_minutes") is not None for e in prior_edges) else None
    else:
        return_eta = arrival if complete else None
    conflict = bool(parse_time(deadline) and parse_time(return_eta) and parse_time(return_eta) > parse_time(deadline))
    return_constraint = {"available": bool(parse_time(deadline)), "mode": transport.get("mode"),
                         "deadline": deadline, "point_index": return_point,
                         "checkpoint_id": return_cp.get("candidate_id") if return_cp else None,
                         "planned_arrival_at": return_eta, "conflict": conflict,
                         "comparison_status": "conflict" if conflict else "within_declared_limit" if parse_time(deadline) and parse_time(return_eta) else "unknown",
                         "basis": "declared_transport_limit_and_planned_timing"}
    if not complete:
        missing.append(_missing("planned_full_eta", "A route gap, unknown segment time or missing final arrival prevents a full-trip ETA.", segment_ids=unknown_segments))
    if parse_time(deadline) is None:
        missing.append(_missing("planned_return_deadline", "No timezone-aware latest return deadline has been declared."))
    elif parse_time(return_eta) is None:
        missing.append(_missing("planned_return_eta", "Unknown route duration prevents comparison with the declared return deadline."))
    if departure and turnaround["available"] and parse_time(turn_time) < parse_time(departure):
        missing.append(_missing("planned_turnaround_before_departure", "The declared turnaround deadline is before route departure.", severity="blocker"))
    if conflict:
        missing.append(_missing("planned_transport_conflict", "Planned arrival exceeds the exact return constraint.", severity="blocker", point_index=return_point))
    return eta, turnaround, return_constraint, missing


def _stop_policies(inputs: dict, results: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    context = inputs.get("review_context", {})
    node_by_index = {n["point_index"]: n for n in inputs["graph"]["nodes"]}
    reviews = {r["point_index"]: r for r in context.get("checkpoint_reviews", [])}
    assessments = {a.get("event", {}).get("point_index"): a.get("assessment", {})
                   for a in results["permission"].get("result", {}).get("assessments", [])}
    declared = context.get("pretrip_input_bundle") or {}
    team_size = declared.get("team_size")
    suggested, avoided, camps, missing = [], [], [], []
    for event in inputs.get("itinerary", {}).get("timeline", []):
        if event.get("kind") not in {"fixed_stop", "stop", "camp"}:
            continue
        point = event.get("point_index")
        node, review = node_by_index.get(point), reviews.get(point, {})
        assessment = assessments.get(point, {})
        human_reviewed = review.get("review", {}).get("status") == "reviewed"
        limit = assessment.get("max_duration_minutes")
        requested = event.get("duration_minutes")
        result = {"point_index": point, "checkpoint_id": node.get("candidate_id") if node else None,
                  "label": (node or {}).get("label") or event.get("label") or f"Planned point {point}",
                  "kind": event["kind"], "requested_duration_minutes": requested,
                  "maximum_duration_minutes": limit, "arrival_at": event.get("arrival_at"),
                  "departure_at": event.get("departure_at"), "permission_decision": assessment.get("decision"),
                  "checkpoint_review": review, **BOUNDARY}
        if event["kind"] == "camp":
            checks = {"human_reviewed": human_reviewed, "camp_candidate": review.get("camp_suitability") == "candidate",
                      "legal_use_confirmed": review.get("campsite_legal_use") is True,
                      "water_confirmed": review.get("water_available") is True,
                      "capacity_sufficient": bool(team_size and isinstance(review.get("campsite_capacity"), int) and review["campsite_capacity"] >= team_size)}
            camps.append({**result, "checks": checks, "status": "reviewed_candidate" if all(checks.values()) else "needs_review",
                          "site_verified_for_actual_overnight": False})
            if not all(checks.values()):
                avoided.append({**result, "policy": "camp_conditions_unresolved"})
                missing.append(_missing("planned_camp_conditions", "Overnight water, legal use, capacity or source-backed review remains unresolved.", point_index=point))
            else:
                suggested.append({**result, "policy": "reviewed_camp_candidate_only"})
        elif (human_reviewed and review.get("stop_suitability") == "candidate" and assessment.get("allowed") is True
              and isinstance(requested, (int, float)) and isinstance(limit, (int, float)) and requested <= limit):
            suggested.append({**result, "policy": "reviewed_stop_with_declared_duration_limit"})
        else:
            avoided.append({**result, "policy": "stop_review_or_duration_unresolved"})
            missing.append(_missing("planned_stop_review", "The requested stop lacks an exact reviewed CP and supported Permission duration limit.", point_index=point))
    return suggested, avoided, camps, missing


def _short_routes(inputs: dict) -> list[dict]:
    """Expose reviewable prefixes only at explicitly reviewed retreat occurrences."""
    context = inputs.get("review_context", {})
    axis = inputs.get("route_axis", [])
    result = []
    for review in context.get("checkpoint_reviews", []):
        point = review["point_index"]
        if (review.get("review", {}).get("status") != "reviewed" or review.get("retreat_available") is not True
                or not isinstance(point, int) or not 0 < point < len(axis) - 1):
            continue
        parts, current = [], []
        for vertex in axis[:point + 1]:
            if vertex.get("break_before") and current:
                parts.append(current)
                current = []
            current.append([vertex["lon"], vertex["lat"]])
        if current:
            parts.append(current)
        lines = [part for part in parts if len(part) >= 2]
        if not lines:
            continue
        result.append({"candidate_id": f"planned.short.prefix.{point}", "end_point_index": point,
                       "source_point_range": [0, point], "geometry": {"type": "MultiLineString", "coordinates": lines},
                       "source_binding": inputs["subject_binding"], "retreat_review": review["review"],
                       "role": "short_route_prefix_candidate", "complete_return_route": False,
                       "return_path_status": "requires_separate_geometry_and_timing_review",
                       "unresolved_geometry_breaks": max(0, len(parts) - 1),
                       "next_action": "Review the return connection, timing and transport before creating a new Planned version.", **BOUNDARY})
    return result


def _readiness_workspace(analysis_root: Path, inputs: dict, results: dict, binding: dict,
                         eta: dict, turnaround: dict, missing: list[dict]) -> tuple[dict, dict, dict]:
    from scout_route_readiness_tool import assess_scout_route_readiness

    root = safe_path(analysis_root, "workspaces/pretrip_readiness")
    context = inputs.get("review_context", {})
    declared = deepcopy(context.get("pretrip_input_bundle") or {})
    graph = inputs["graph"]
    transport = context.get("transport") or declared.get("transport") or {}
    confirmations = context.get("readiness") or declared.get("readiness") or {}
    members = declared.get("members", [])
    equipment = deepcopy(declared.get("equipment", []))
    for item in equipment:
        item["review_state"] = "declared_ready" if item.get("state") == "ready" else "needs_review"
    unknown_members = [m for m in members if not (m.get("experience") or m.get("experience_level")) or m.get("planned_pace_kmh") is None]
    for member in members:
        if member in unknown_members:
            member["review_state"] = "needs_review"
    if any(m.get("candidate_only") is False or m.get("capability_observed") is True for m in members):
        raise PlannedRouteConflict("planned_pretrip_declaration_authority", "Declared team data cannot claim measured capability.")
    permission_reviews = context.get("assessor_kwargs", {}).get("permission", [])
    weather_reviewed = bool(permission_reviews) and all(p.get("review", {}).get("weather_review", {}).get("status") == "reviewed" for p in permission_reviews)
    daylight_reviewed = bool(permission_reviews) and all(p.get("review", {}).get("daylight_review", {}).get("status") == "reviewed" for p in permission_reviews)
    weather_result = results["weather"].get("result", {})
    expected_segments = len(graph.get("edges", []))
    coverage_complete = expected_segments > 0 and weather_result.get("matched_segment_count") == expected_segments
    weather_reviewed = weather_reviewed and coverage_complete
    daylight_reviewed = daylight_reviewed and not any("daylight" in str(m.get("code", "")) for m in results["weather"].get("missing_inputs", []))
    profiles = [m.get("experience_level") for m in members]
    order = {"beginner": 0, "novice": 1, "intermediate": 2, "experienced": 3, "expert": 4}
    experience = min(profiles, key=order.get) if profiles and all(p in order for p in profiles) else None
    if experience is None and members and all(m.get("experience") for m in members):
        experience = " / ".join(m["experience"] for m in members)
    common = {"input_binding": binding, **BOUNDARY}
    route_adapter = {"artifact_kind": "planned_candidate_cp_graph_adapter", "name": f"Planned {binding['version_id']}",
                     "checkpoints": graph["nodes"], "segments": graph["edges"], "gaps": graph.get("gaps", []),
                     "reviewed_mission_graph": False, "topology_role": "planned_candidate_cp_edges", **common}
    package = {"artifact_kind": "planned_pretrip_candidate_package", "route_summary": inputs.get("route_summary", {}),
               "boundary": {**BOUNDARY, "departure_gate_required_before_runtime": True,
                            "reviewed_package_is_not_departure_approval": True}, **common}
    resource = {"team_members": members, "equipment": equipment,
                "remote_contact_plan": {"review_state": "declared_confirmed" if confirmations.get("remote_contact_confirmed") is True else "needs_review"},
                "input_role": "declared_user_input", **common}
    findings = [dict(item) for item in missing if item.get("severity") == "blocker"]
    readiness = {"status": "blocked" if findings else "warning" if missing else "ready", "findings": findings,
                 "assessment_scope": "same_planned_six_force_coverage", "hardware_probe_performed": False, **common}
    payloads = {"inputs/cp_graph.candidate.json": route_adapter, "inputs/planned_eta.json": {**eta, **common},
                "inputs/resource_plan.json": resource, "inputs/pretrip_package.candidate.json": package,
                "inputs/readiness_findings.json": readiness, "inputs/pretrip_input_bundle.json": {**declared, **common}}
    weather_source = "outputs/route_weather_package.json"
    if weather_result.get("new_package_built") is True and safe_path(analysis_root, weather_source).is_file():
        weather_package = _load(analysis_root, weather_source)
        _assert_binding(weather_package.get("input_binding", {}), binding, context_required=False)
        if weather_package.get("candidate_only") is False or weather_package.get("runtime_safety_truth") is True:
            raise PlannedRouteConflict("planned_pretrip_weather_authority", "The route weather package has an invalid planning boundary.")
        payloads["inputs/route_weather_package.json"] = {**weather_package, **common}
    weather_evidence = []
    for source in declared.get("source_evidence", []):
        if source.get("source_kind") != "daylight" or not source.get("input_ref"):
            continue
        ref = source["input_ref"]
        path = safe_path(analysis_root, ref)
        if not path.is_file() or _sha(path.read_bytes()) != source.get("sha256"):
            raise PlannedRouteConflict("planned_pretrip_review_evidence_changed", "The daylight source changed after the review snapshot.")
        try:
            value = json.loads(path.read_bytes())
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict):
            weather_evidence.append(value)
    days = inputs.get("itinerary", {}).get("days", [])
    windows = [value.get("daylight", {}) for value in weather_evidence]
    day_coverage = []
    for day in days:
        start, end = parse_time(day.get("departure_at")), parse_time(day.get("arrival_at"))
        matching = [window for window in windows if parse_time(window.get("sunrise")) and parse_time(window.get("sunset"))
                    and start and parse_time(window["sunrise"]).date() == start.date()]
        day_coverage.append(bool(matching and start and end))
        if start and end and matching and any(e.get("requires_daylight") is True for e in graph["edges"]):
            if not any(parse_time(window["sunrise"]) <= start and end <= parse_time(window["sunset"]) for window in matching):
                missing.append(_missing("planned_daylight_window_conflict", "A daylight-required Planned day extends outside its cited sun window.", day_id=day.get("day_id")))
    daylight_reviewed = daylight_reviewed and bool(day_coverage) and all(day_coverage)
    weather_reviewed = weather_reviewed and "inputs/route_weather_package.json" in payloads
    if not daylight_reviewed:
        missing.append(_missing("planned_daylight_review", "A completed human review and dated sun window are required for each Planned day."))
    if not weather_reviewed:
        missing.append(_missing("planned_weather_review", "A completed human review and matching route forecast package are required."))
    if weather_evidence:
        payloads["inputs/weather_daylight.json"] = {"sources": weather_evidence,
            "daylight": weather_evidence[0].get("daylight", {}),
            "human_review_required": not (weather_reviewed and daylight_reviewed), **common}
    hashes = {}
    _write(root, "project.json", {"project_id": binding["project_id"], "route_role": "planned", "analysis_subject_kind": "planned_gpx", **common})
    for ref, payload in payloads.items():
        hashes[ref] = _write(root, ref, payload)
    direct = {"user_experience_level": experience, "user_goal": "、".join(context.get("goals") or declared.get("goals") or []),
              "transport_access_plan": transport.get("mode"), "latest_return_time": transport.get("latest_return_at"),
              "team_slowest_basis_confirmed": confirmations.get("team_slowest_basis_confirmed"),
              "departure_time_confirmed": confirmations.get("departure_time_confirmed"),
              "equipment_confirmed": confirmations.get("equipment_confirmed"),
              "remote_contact_confirmed": confirmations.get("remote_contact_confirmed"),
              "weather_reviewed": weather_reviewed, "daylight_reviewed": daylight_reviewed}
    kwargs = {"query": "同一 Planned 版本的行前綜合審查；這是候選規劃建議，不授予出發權限。",
              "readiness_report_path": "inputs/readiness_findings.json", "planned_eta_path": "inputs/planned_eta.json",
              "resource_plan_path": "inputs/resource_plan.json", "weather_daylight_path": "inputs/weather_daylight.json",
              "route_weather_package_path": "inputs/route_weather_package.json", "pretrip_package_path": "inputs/pretrip_package.candidate.json",
              "mission_graph_path": "inputs/cp_graph.candidate.json", "route_comparison_path": "inputs/unavailable_comparison.json",
              "pretrip_input_bundle_path": "inputs/pretrip_input_bundle.json", **direct}
    result = assess_scout_route_readiness(root, **kwargs)
    # Old defaults can never hide in this fresh view; every loaded path was written above.
    if any(source.get("status") == "loaded" and source.get("source_path") not in payloads for source in result.get("source_report", [])):
        raise PlannedRouteConflict("planned_pretrip_unexpected_source", "The readiness assessor loaded a source outside its Planned input allowlist.")
    return result, {"workspace_ref": root.relative_to(analysis_root).as_posix(), "input_hashes": hashes,
                    "explicit_kwargs": kwargs, "source_report": result.get("source_report", [])}, confirmations


def _decision(base: str, results: dict, missing: list[dict], return_constraint: dict) -> str:
    if base not in DECISIONS:
        return "ESCALATE"
    route_decisions = {results[role].get("result", {}).get("decision") for role in ("weather", "navigation", "architecture", "pace_fit")}
    if base == "NO_GO" or "NO_GO" in route_decisions:
        return "NO_GO"
    if base == "ESCALATE" or "ESCALATE" in route_decisions:
        return "ESCALATE"
    if return_constraint.get("conflict") or base == "CHANGE_PLAN":
        return "CHANGE_PLAN"
    if base == "GUIDED_ONLY" or "GUIDED_ONLY" in route_decisions:
        return "GUIDED_ONLY"
    if missing or any(p["status"] != "ready" for p in results.values()):
        return "DELAY"
    return base


def build_planned_pretrip_report(analysis_root: Path, inputs: dict, projections: dict,
                                 *, binding: dict, run_root: Path | None = None) -> dict:
    """Write the complete Sec.18.2 package and return its registered artifact ref.

    projection artifact refs are relative to run_root (analysis_root by default).
    ``inputs['review_context']`` is the verified W1 materializer output. All
    mandatory outputs are present even when their value is explicitly unknown.
    """
    analysis_root = Path(analysis_root).resolve()
    run_root = Path(run_root).resolve() if run_root is not None else analysis_root
    if analysis_root != run_root and not analysis_root.is_relative_to(run_root):
        raise PlannedRouteConflict("planned_pretrip_workspace_mismatch", "The analysis workspace must belong to this analysis attempt.")
    if any(not binding.get(key) for key in BINDING_FIELDS[:5]):
        raise PlannedRouteConflict("planned_pretrip_binding_mismatch", "The Planned version, manifest, geometry and timetable must all be identified.")
    _assert_binding(inputs.get("subject_binding", {}), binding, context_required=False)
    _assert_binding(inputs.get("graph", {}).get("input_binding", {}), binding, context_required=False)
    review_context = inputs.get("review_context") or {}
    for field, key in (("context_revision_id", "review_context_revision_id"), ("context_sha256", "review_context_sha256")):
        if review_context.get(field) != binding.get(key):
            raise PlannedRouteConflict("planned_pretrip_binding_mismatch", "The review supplement does not match this analysis run.")
    verified = _verified_projections(run_root, projections, binding)
    for ref, expected in inputs.get("input_hashes", {}).items():
        path = safe_path(analysis_root, ref)
        if not path.is_file() or _sha(path.read_bytes()) != expected:
            raise PlannedRouteConflict("planned_pretrip_input_hash", f"A derived Planned input changed: {ref}")
    missing = [dict(item, role=role, severity="blocker" if artifact["status"] == "blocked" else item.get("severity", "warning"))
               for role, artifact in verified.items() for item in artifact.get("missing_inputs", [])]
    missing += [dict(item, role="review_context", severity=item.get("severity", "warning")) for item in review_context.get("missing_inputs", [])]
    for role, artifact in verified.items():
        if artifact["status"] == "blocked" and not artifact.get("missing_inputs"):
            missing.append(_missing("planned_producer_unavailable", "The deterministic producer did not complete.", role=role, severity="blocker"))
    for gap in inputs["graph"].get("gaps", []):
        missing.append(_missing("planned_geometry_gap", "The plan contains an unresolved route geometry gap.", severity="blocker", **{k: v for k, v in gap.items() if k in {"from_point_index", "to_point_index", "break_point_indices"}}))
    transport = review_context.get("transport") or (review_context.get("pretrip_input_bundle") or {}).get("transport") or {}
    eta, turnaround, return_constraint, timing_missing = _timetable(inputs, transport)
    missing.extend(timing_missing)
    suggested, avoided, camps, stop_missing = _stop_policies(inputs, verified)
    missing.extend(stop_missing)
    raw_assessor, adapter, confirmations = _readiness_workspace(analysis_root, inputs, verified, binding, eta, turnaround, missing)
    for key, value in confirmations.items():
        if value is not True:
            missing.append(_missing(f"planned_readiness_{key}", "This required planning confirmation remains false or unknown."))
    for field in ("team_slowest_basis_confirmed", "departure_time_confirmed", "equipment_confirmed", "remote_contact_confirmed"):
        if field not in confirmations:
            missing.append(_missing(f"planned_readiness_{field}", "This required planning confirmation has not been declared."))
    for field in raw_assessor.get("missing_fields", []):
        missing.append(_missing(f"readiness_{field}", f"The readiness assessor requires {field}.", role="readiness_assessor"))
    missing = _unique(missing)
    decision = _decision(raw_assessor["decision"], verified, missing, return_constraint)
    source_roles = _source_roles(verified, projections)
    required_conditions = [m["reason"] for m in missing]
    required_conditions += list(raw_assessor.get("route_readiness", {}).get("required_conditions", []))
    required_conditions = list(dict.fromkeys(required_conditions))
    risks = [{"code": m["code"], "role": m["role"], "severity": m["severity"], "reason": m["reason"],
              "source_ref": projections[m["role"]]["artifact_ref"] if m["role"] in projections else None,
              "source_sha256": projections[m["role"]]["artifact_sha256"] if m["role"] in projections else None,
              "target": {k: m[k] for k in ("point_index", "segment_id", "day_id", "member_id") if k in m}}
             for m in missing]
    risks.sort(key=lambda row: (0 if row["severity"] == "blocker" else 1, ROLES.index(row["role"]) if row["role"] in ROLES else len(ROLES)))
    for role in ROLES:
        role_decision = verified[role].get("result", {}).get("decision")
        if role_decision in {"NO_GO", "CHANGE_PLAN", "GUIDED_ONLY", "DELAY", "ESCALATE"}:
            risks.append({"code": "role_assessment_restriction", "role": role,
                          "severity": "blocker" if role_decision in {"NO_GO", "ESCALATE"} else "warning",
                          "reason": f"{role} 的同版分析建議為 {role_decision}。", "source_ref": projections[role]["artifact_ref"],
                          "source_sha256": projections[role]["artifact_sha256"]})
    risks.sort(key=lambda row: (0 if row["severity"] == "blocker" else 1,
                               0 if row["code"] == "role_assessment_restriction" else 1,
                               ROLES.index(row["role"]) if row["role"] in ROLES else len(ROLES)))
    short_routes = _short_routes(inputs)
    alternatives = [{"action": text, "kind": "planning_adjustment", **BOUNDARY}
                    for text in raw_assessor.get("route_readiness", {}).get("alternative_actions", [])]
    alternatives += [{"action": f"檢視到 point {item['end_point_index']} 的短版前綴，另補回程連接與節奏審查。",
                      "kind": "short_route_prefix_candidate", "candidate_id": item["candidate_id"], **BOUNDARY} for item in short_routes]
    checklist = [{"item": field, "status": "provided" if covered else "missing", "basis": "same_version_readiness_assessor"}
                 for field, covered in raw_assessor.get("departure_gate", {}).get("input_coverage", {}).items()]
    for item in checklist:
        if item["item"] in confirmations:
            item["status"] = "confirmed" if confirmations[item["item"]] is True else "not_confirmed"
            item["basis"] = "explicit_same_version_human_declaration"
    checklist += [{"item": m["code"], "status": "required", "reason": m["reason"], "role": m["role"]} for m in missing]
    residual_risk = ["本報告是同版候選規劃分析；人工採用、GPX 匯出及審查紀錄均不授予實際出發或即時導航權限。",
                     "人員與裝備資料是明示輸入；未視為實測能力、現場硬體測試或路線可通行證明。"]
    residual_risk += list(raw_assessor.get("pretrip_decision_package", {}).get("required_outputs", {}).get("residual_risk", []))
    if missing:
        residual_risk.append("未解路段、時程或證據缺口維持可見；不得將有資料路段的小計當作全程 ETA。")
    report_ref = "reports/planned_pretrip_report.json"
    legacy_ref = "reports/planned_pretrip_readiness_assessor.json"
    legacy_sha = _write(run_root, legacy_ref, {"artifact_kind": "planned_readiness_assessor_evidence", "input_binding": binding,
                                              "readiness_assessor": raw_assessor, "adapter": adapter, **BOUNDARY})
    generated = sorted(p.get("generated_at") for p in verified.values() if isinstance(p.get("generated_at"), str))
    report = {"artifact_kind": "planned_pretrip_report", "schema_version": REPORT_VERSION,
              "project_id": binding["project_id"], "status": "partial" if missing else "ready",
              "report_status": "completed_with_gaps" if missing else "completed",
              "decision": decision, "decision_scope": "candidate_pretrip_planning_review",
              "input_binding": binding, "generated_at": generated[-1] if generated else None,
              "required_outputs": {"pretrip_decision": decision, "top_risk_sources": risks[:3],
                  "required_conditions": required_conditions,
                  "cp_graph": {**inputs["graph"], "available": True, "reviewed_mission_graph": False},
                  "latest_turnaround": {**turnaround, "source_ref": review_context.get("context_file_ref"),
                                        "source_sha256": review_context.get("context_file_sha256")},
                  "suggested_stop_points": suggested, "not_recommended_stop_points": avoided,
                  "alternatives_or_short_routes": alternatives, "pretrip_checklist": checklist,
                  "residual_risk": list(dict.fromkeys(residual_risk))},
              "planned_timetable": eta, "return_constraint": return_constraint, "camp_candidates": camps,
              "short_route_candidates": short_routes, "six_force_results": source_roles, "missing_inputs": missing,
              "risk_sources": risks, "decision_limits": {"planning_assessment_only": True,
                  "autonomous_departure_allowed": False, "departure_approval_granted": False,
                  "must_leave_by": turnaround["deadline"], "latest_return_at": return_constraint["deadline"]},
              "provenance": {"projection_hashes": {role: projections[role]["artifact_sha256"] for role in ROLES},
                  "review_context_revision_id": review_context.get("context_revision_id"),
                  "review_context_sha256": review_context.get("context_sha256"),
                  "derived_input_hashes": deepcopy(inputs.get("input_hashes", {})),
                  "readiness_assessor_ref": legacy_ref, "readiness_assessor_sha256": legacy_sha,
                  "readiness_adapter": adapter, "golden_readiness_fallback_used": False},
              "standard_alignment": ["SCOUT_OUTDOOR_AI_AGENT_STANDARD 18.1", "SCOUT_OUTDOOR_AI_AGENT_STANDARD 18.2", "SCOUT_OUTDOOR_AI_AGENT_STANDARD 18.6"],
              **BOUNDARY}
    _verified_projections(run_root, projections, binding)
    report_sha = _write(run_root, report_ref, report)
    return {"status": report["status"], "decision": decision, "artifact_ref": report_ref,
            "artifact_sha256": report_sha, "input_binding": binding, "report": report,
            "missing_input_count": len(missing), **BOUNDARY}
