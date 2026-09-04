#!/usr/bin/env python3
"""Qualify task-relevant fact selection and abstention through the Pi MCP queue."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.claim_selection_qualification import (
    EXPERIMENT_ID, build_scenario_request, counterfactual_payload, qualification_catalog,
    qualification_scenarios, score_scenario_response,
)
from scout.nextgen.intelligence_gateway import intelligence_response_hash
from scout.nextgen.intelligence_mcp_http import IntelligenceMcpHttpClient, IntelligenceMcpHttpClientConfig
from scout.nextgen.praison_background_queue import BackgroundIntelligenceJobState
from scout.nextgen.workspace_terrain_projection import WorkspaceTerrainProjection, verify_projection_sources


def _write_new(path: Path, value: dict) -> None:
    data = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data)


def _prepare(args, projection, scenarios) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prepared = {
        "evidence-catalog.json": qualification_catalog(projection).model_dump(mode="json"),
        "controlled-counterfactual.json": counterfactual_payload(projection),
        "case-definitions.json": {
            "experiment_id": EXPERIMENT_ID,
            "parent_workspace_input_hash": projection.workspace_binding.input_hash,
            "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
            "purpose": "development_and_held_out_behavior_qualification_not_training",
            "controlled_states_are_real_observations": False,
            "expected_decisions_sent_to_model": False,
            "candidate_only": True, "runtime_safety_truth": False,
        },
    }
    if args.comparison_baseline is not None:
        from scout.nextgen.claim_selection_comparison import authorize_frozen_comparison

        inputs = [authorize_frozen_comparison(
            build_scenario_request(projection, case), case_id=case.case_id,
            baseline_dir=args.comparison_baseline, cloud_authorized=args.allow_cloud_comparison,
        )[1] for case in scenarios]
        prepared["cloud-input-review.json"] = {
            "schema_version": "scout.claim_selection_cloud_input_review.v0",
            "baseline_path": str(args.comparison_baseline), "cases": inputs,
            "raw_workspace_authorized_for_cloud": False,
            "candidate_only": True, "runtime_safety_truth": False,
        }
    for name, value in prepared.items():
        path = args.output_dir / name
        if path.exists():
            if json.loads(path.read_bytes()) != value:
                raise ValueError(f"prepared artifact changed; choose a new output directory: {name}")
        else:
            _write_new(path, value)


def _run_case(client, projection, scenario, output_dir, *, comparison_baseline=None) -> dict:
    request = build_scenario_request(projection, scenario)
    comparison = None
    if comparison_baseline is not None:
        from scout.nextgen.claim_selection_comparison import authorize_frozen_comparison

        request, comparison = authorize_frozen_comparison(
            request, case_id=scenario.case_id, baseline_dir=comparison_baseline,
            cloud_authorized=True,
        )
    receipt_path = output_dir / f"{scenario.case_id}.json"
    request_path = output_dir / f"{scenario.case_id}.request.json"
    if receipt_path.exists() or request_path.exists():
        raise ValueError(f"case already started; preserve its evidence and use a new directory: {scenario.case_id}")
    _write_new(request_path, request.model_dump(mode="json"))
    started = time.monotonic()
    submission = client.submit_background(request)
    _write_new(output_dir / f"{scenario.case_id}.submission.json", submission.model_dump(mode="json"))
    progress, stages = submission.progress, [submission.progress.stage]
    response, error_type = None, None
    terminal = {BackgroundIntelligenceJobState.COMPLETED, BackgroundIntelligenceJobState.FAILED,
                BackgroundIntelligenceJobState.CANCELLED}
    try:
        while progress.state not in terminal:
            time.sleep(1)
            progress = client.background_progress(submission.access)
            if progress.stage != stages[-1]:
                stages.append(progress.stage)
        if progress.state is BackgroundIntelligenceJobState.COMPLETED:
            verify_projection_sources(projection)
            response = client.background_result(
                submission.access, request=request, current_binding=request.workspace_binding,
            )
        error_type = progress.error_type
    except (Exception, KeyboardInterrupt) as exc:
        error_type = type(exc).__name__
        try:
            progress = client.cancel_background(submission.access)
        except Exception:
            # The saved submission identifies the job for recovery after transport loss.
            stages.append("transport_lost_recovery_required")
        if isinstance(exc, KeyboardInterrupt):
            stages.append("operator_interrupted")
    records = response.provenance.model_execution_records if response is not None else progress.model_execution_records
    score = (score_scenario_response(scenario, request, response) if response is not None else {
        "case_id": scenario.case_id, "mode": scenario.mode, "split": scenario.split,
        "expected_execution": scenario.expected_execution,
        "passed": False, "model_completed": False, "contract_accepted": False,
        "model_behavior_passed": False if scenario.expected_execution == "model" else None,
        "deterministic_no_context_passed": False if scenario.expected_execution != "model" else None,
        "model_request_count": sum(item.model_request_count for item in records),
    })
    receipt = {
        "schema_version": "scout.claim_selection_case_receipt.v0",
        "experiment_id": EXPERIMENT_ID, "generated_at": datetime.now(UTC).isoformat(),
        "case": scenario.model_dump(mode="json"), "request_id": str(request.request_id),
        "job_id": str(submission.access.job_id), "stages": stages, "final_state": progress.state.value,
        "elapsed_seconds": round(time.monotonic() - started, 3), "error_type": error_type,
        "model_execution_records": [record.model_dump(mode="json") for record in records],
        "workspace_binding": request.workspace_binding.model_dump(mode="json"),
        "parent_workspace_input_hash": projection.workspace_binding.input_hash,
        "response": response.model_dump(mode="json") if response is not None else None,
        "output_hash": intelligence_response_hash(response) if response is not None else None,
        "score": score, "candidate_only": True, "runtime_safety_truth": False,
    }
    if comparison is not None:
        receipt["comparison_input"] = comparison
    _write_new(receipt_path, receipt)
    print(json.dumps({"case_id": scenario.case_id, "score": score,
                      "elapsed_seconds": receipt["elapsed_seconds"], "error_type": error_type}), flush=True)
    if "operator_interrupted" in stages:
        raise KeyboardInterrupt
    if "transport_lost_recovery_required" in stages:
        raise RuntimeError("job cancellation unconfirmed; recover saved submission before continuing")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--comparison-baseline", type=Path)
    parser.add_argument("--allow-cloud-comparison", action="store_true")
    args = parser.parse_args()
    if bool(args.comparison_baseline) != args.allow_cloud_comparison:
        parser.error("cloud comparison requires both --comparison-baseline and --allow-cloud-comparison")
    if not args.prepare_only and args.socket is None:
        parser.error("--socket is required for live qualification")
    projection = WorkspaceTerrainProjection.model_validate_json(args.projection.read_bytes())
    verify_projection_sources(projection)
    scenarios = qualification_scenarios()
    if args.case_id and not set(args.case_id).issubset({case.case_id for case in scenarios}):
        parser.error("unknown --case-id")
    _prepare(args, projection, scenarios)
    if args.prepare_only:
        print(json.dumps({"prepared_case_count": len(scenarios), "model_requests": 0,
                          "output_dir": str(args.output_dir)}))
        return 0
    selected = tuple(case for case in scenarios if not args.case_id or case.case_id in args.case_id)
    client = IntelligenceMcpHttpClient(IntelligenceMcpHttpClientConfig(unix_socket=args.socket, timeout_seconds=60))
    receipts = [_run_case(client, projection, case, args.output_dir,
                          comparison_baseline=args.comparison_baseline) for case in selected]
    verify_projection_sources(projection)
    summary = {
        "schema_version": "scout.claim_selection_qualification.v0", "experiment_id": EXPERIMENT_ID,
        "generated_at": datetime.now(UTC).isoformat(), "case_count": len(receipts),
        "passed_count": sum(item["score"]["passed"] for item in receipts),
        "model_case_count": sum(item["case"]["expected_execution"] == "model" for item in receipts),
        "model_behavior_passed_count": sum(item["score"]["model_behavior_passed"] is True for item in receipts),
        "deterministic_no_context_passed_count": sum(item["score"]["deterministic_no_context_passed"] is True for item in receipts),
        "model_request_count": sum(item["score"]["model_request_count"] for item in receipts),
        "elapsed_seconds_total": round(sum(item["elapsed_seconds"] for item in receipts), 3),
        "cases": [{**item["score"], "elapsed_seconds": item["elapsed_seconds"]} for item in receipts],
        "bound_workspace_sources_unchanged": True, "model_authored_prose_qualified": False,
        "raw_first_attempt_success_measured": False, "controlled_states_are_real_observations": False,
        "expected_decisions_sent_to_model": False, "candidate_only": True, "runtime_safety_truth": False,
    }
    name = "qualification.json" if not args.case_id else "qualification-" + "-".join(args.case_id) + ".json"
    if args.comparison_baseline is not None:
        baseline = json.loads((args.comparison_baseline / "qualification.json").read_bytes())
        summary["comparison"] = {
            "baseline_path": str(args.comparison_baseline),
            "baseline_model_passed": baseline["model_behavior_passed_count"],
            "baseline_model_cases": baseline["model_case_count"],
            "planned_question_evidence_binding_and_schema_match": all(
                item["comparison_input"]["planned_question_evidence_binding_and_schema_match"] for item in receipts
            ),
            "execution_comparison_status": "requires_egress_receipt_verification",
            "cloud_comparison_explicitly_authorized": True,
            "production_routing_changed": False,
        }
    _write_new(args.output_dir / name, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["passed_count"] == len(receipts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
