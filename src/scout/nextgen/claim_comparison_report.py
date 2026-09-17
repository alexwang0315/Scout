"""Verify actual cloud egress before attributing a comparison to a model."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.claim_selection_comparison import authorize_frozen_comparison
from scout.nextgen.claim_selection_qualification import qualification_scenarios, score_scenario_response
from scout.nextgen.intelligence_gateway import IntelligenceRequest, IntelligenceResponse, intelligence_response_hash


def _timestamp(value) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("comparison evidence requires timezone-aware timestamps")
    return parsed.astimezone(UTC)


def _case_egress_associations(*, case_id, response, audit, records, config, expects_model: bool):
    execution = response.provenance.model_execution_records
    scoped = [item for item in records if item.get("case_id") == case_id]
    if not expects_model:
        return [] if not execution and not scoped else None
    if (not execution or "terrain.subject_selection" not in response.provenance.agent_path
            or any(record.runtime_id != config.runtime_id or record.provider != config.provider
                   or record.model_id != config.model_id or record.observed_model_id != config.model_id
                   or record.locality != "cloud" or record.status != "completed" or record.fallback_used
                   or record.parent_request_id != response.request_id or record.inference_id is None
                   or _timestamp(record.completed_at) > _timestamp(response.provenance.generated_at)
                   for record in execution)):
        return None
    if len({record.inference_id for record in execution}) != len(execution):
        return None
    sent = [item for item in scoped if item.get("status") == "authorized_before_network"]
    received = [item for item in scoped if item.get("status") == "response_received"]
    expected = sum(record.model_request_count for record in execution)
    if len(sent) != expected or len(received) != expected or len(scoped) != expected * 2:
        return None
    by_id = {item["egress_id"]: item for item in sent}
    if len(by_id) != expected or len({item["egress_id"] for item in received}) != expected:
        return None
    for item in scoped:
        if (item.get("allowed") is not True or item.get("runtime_id") != config.runtime_id
                or item.get("requested_model") != config.model_id
                or item.get("model_prompt_sha256") != audit["model_prompt_sha256"]
                or item.get("wire_output_schema_sha256") != audit["wire_output_schema_sha256"]):
            return None
    associations = []
    for item in received:
        authorized = by_id.get(item["egress_id"], {})
        if (item.get("http_status") != 200 or item.get("observed_model") != config.model_id
                or any(not item.get(key) or item[key] != authorized.get(key)
                       for key in ("body_sha256", "messages_sha256", "started_at"))
                or not item.get("response_body_sha256")):
            return None
        started, completed = _timestamp(item["started_at"]), _timestamp(item["completed_at"])
        matches = [record for record in execution
                   if _timestamp(record.started_at) <= started <= completed <= _timestamp(record.completed_at)]
        if len(matches) != 1:
            return None
        associations.append({"egress_id": item["egress_id"], "request_id": str(response.request_id),
                             "inference_id": str(matches[0].inference_id), "association_method": "interval_derived_v0"})
    if any(sum(item["inference_id"] == str(record.inference_id) for item in associations) != record.model_request_count
           for record in execution):
        return None
    return associations


def verify_case_egress(**kwargs) -> bool:
    try:
        return _case_egress_associations(**kwargs) is not None
    except (ValueError, TypeError, KeyError):
        return False


def _unique_case_ids(summary, expected_ids) -> set[str]:
    ids = [case["case_id"] for case in summary["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate comparison case IDs")
    if set(ids) != expected_ids:
        raise ValueError("comparison requires the complete frozen case set")
    return set(ids)


def _historical_case(directory: Path, scenario):
    request = IntelligenceRequest.model_validate_json((directory / f"{scenario.case_id}.request.json").read_bytes())
    receipt = json.loads((directory / f"{scenario.case_id}.json").read_bytes())
    response = IntelligenceResponse.model_validate(receipt["response"])
    if (receipt["case"] != scenario.model_dump(mode="json") or receipt["request_id"] != str(request.request_id)
            or receipt["final_state"] != "completed" or receipt.get("error_type") is not None
            or intelligence_response_hash(response) != receipt["output_hash"]):
        raise ValueError("comparison case receipt binding mismatch")
    generated = _timestamp(response.provenance.generated_at)
    if generated >= _timestamp(request.capability_grant.expires_at) or any(
        not _timestamp(record.started_at) <= _timestamp(record.completed_at) <= generated
        for record in response.provenance.model_execution_records
    ):
        raise ValueError("comparison execution outside the recorded authorization window")
    score = score_scenario_response(scenario, request, response, evaluated_at=generated)
    return request, response, receipt, score


def build_comparison_report(*, baseline_dir: Path, result_dir: Path, egress_dir: Path, config) -> dict:
    baseline = json.loads((baseline_dir / "qualification.json").read_bytes())
    current = json.loads((result_dir / "qualification.json").read_bytes())
    records = [json.loads(path.read_bytes()) for path in sorted(egress_dir.glob("*.json"))]
    scenarios = {case.case_id: case for case in qualification_scenarios()}
    expected_ids = _unique_case_ids(current, set(scenarios))
    _unique_case_ids(baseline, set(scenarios))
    global_egress_valid = bool(records) and all(
        item.get("case_id") in expected_ids
        and item.get("status") in {"authorized_before_network", "response_received"} for item in records
    ) and len({item.get("egress_id") for item in records}) * 2 == len(records)
    checks, associations, executions, request_ids = [], [], [], []
    request_count, elapsed = 0, 0.0
    for case in current["cases"]:
        case_id = case["case_id"]
        request, response, receipt, score = _historical_case(result_dir, scenarios[case_id])
        _, _, _, baseline_score = _historical_case(baseline_dir, scenarios[case_id])
        _, audit = authorize_frozen_comparison(request, case_id=case_id, baseline_dir=baseline_dir, cloud_authorized=True)
        try:
            matched = _case_egress_associations(
                case_id=case_id, response=response, audit=audit, records=records, config=config,
                expects_model=scenarios[case_id].expected_execution == "model",
            )
        except (ValueError, TypeError, KeyError):
            matched = None
        comparable = matched is not None and score["contract_accepted"] and baseline_score["contract_accepted"]
        associations.extend(matched or ())
        executions.extend(response.provenance.model_execution_records)
        request_ids.append(response.request_id)
        request_count += score["model_request_count"]
        elapsed += receipt["elapsed_seconds"]
        checks.append({"case_id": case_id, "comparable": comparable,
                       "baseline_model_behavior_passed": baseline_score["model_behavior_passed"],
                       "model_behavior_passed": score["model_behavior_passed"],
                       "deterministic_no_context_passed": score["deterministic_no_context_passed"],
                       "contract_accepted": score["contract_accepted"]})
    ordered = sorted(executions, key=lambda record: _timestamp(record.started_at))
    unique_execution = (len(set(request_ids)) == len(request_ids)
                        and len({record.inference_id for record in executions}) == len(executions)
                        and len({item["egress_id"] for item in associations}) == len(associations)
                        and all(_timestamp(left.completed_at) <= _timestamp(right.started_at)
                                for left, right in zip(ordered, ordered[1:])))
    comparable = global_egress_valid and unique_execution and all(case["comparable"] for case in checks)
    return {
        "schema_version": "scout.claim_selection_model_comparison.v0",
        "experiment_id": "SCOUT-AI-CLAIM-SELECTION-MODEL-COMPARISON-20260903",
        "generated_at": datetime.now(UTC).isoformat(),
        "comparison_valid": comparable, "same_complete_case_set": True,
        "actual_egress_verified": comparable,
        "scoring_time_basis": "verified_response_generated_at",
        "association_method": "interval_derived_v0", "native_request_binding_verified": False,
        "unique_serial_execution_verified": unique_execution, "egress_associations": associations,
        "configured_runtime_id": config.runtime_id, "observed_model_id": config.model_id if comparable else None,
        "baseline_model_passed": sum(case["baseline_model_behavior_passed"] is True for case in checks),
        "baseline_model_cases": sum(case.expected_execution == "model" for case in scenarios.values()),
        "current_model_passed": sum(case["model_behavior_passed"] is True for case in checks),
        "current_model_cases": sum(case.expected_execution == "model" for case in scenarios.values()),
        "deterministic_no_context_passed": sum(case["deterministic_no_context_passed"] is True for case in checks),
        "verified_http_requests": sum(item.get("status") == "response_received" for item in records),
        "model_request_count": request_count, "elapsed_seconds": round(elapsed, 3),
        "checks": checks, "model_responsibility": "subject_relevance_only",
        "raw_first_attempt_output_captured": False,
        "conclusion_scope": "model_and_provider_runtime_pair_not_isolated_model_weights",
        "decision": "CONTINUE_RESEARCH" if comparable else "MORE_EVIDENCE_REQUIRED",
        "production_routing_changed": False, "candidate_only": True, "runtime_safety_truth": False,
    }
