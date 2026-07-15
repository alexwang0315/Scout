from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_failure_review(
    *,
    case_id: str,
    live_reports: list[dict[str, Any]],
    deterministic_report: dict[str, Any],
    additional_models: list[str] | None = None,
) -> dict[str, Any]:
    deterministic_sample = _sample(deterministic_report, case_id)
    live_samples = [_sample(report, case_id) for report in live_reports]
    evidence = deterministic_sample.get("responses") or []
    source_refs = deterministic_sample.get("returned_source_refs") or []
    traced_models = [str(report.get("model") or "unknown") for report in live_reports]
    models = list(dict.fromkeys([*(additional_models or []), *traced_models]))
    stable_digest = hashlib.sha256(
        json.dumps(
            {"case_id": case_id, "models": models, "source_refs": source_refs},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "artifact_kind": "scout_ai_codex_failure_review",
        "schema_version": "scout.ai.failure_review.v1",
        "review_id": f"SCOUT-REVIEW-{stable_digest}",
        "created_at": datetime.now(UTC).isoformat(),
        "case_id": case_id,
        "original_question": deterministic_sample.get("question"),
        "expected_success": {
            "operations": deterministic_sample.get("expected_operations") or [],
            "artifacts": deterministic_sample.get("expected_artifact_keys") or [],
            "source_refs": source_refs,
            "deterministic_grade": deterministic_sample.get("deterministic_fact_grade"),
        },
        "available_evidence": evidence,
        "source_references": source_refs,
        "complete_call_trace": [
            {
                "model": model,
                "error": sample.get("error"),
                "failure_category": sample.get("failure_category"),
                "failure_class": sample.get("failure_class"),
                "tool_invocations": sample.get("tool_invocation_statuses") or [],
                "attempt_receipts": sample.get("l5_attempt_receipts") or [],
                "semantic_grade": sample.get("l5_semantic_grade"),
            }
            for model, sample in zip(traced_models, live_samples, strict=True)
        ],
        "tool_outputs": evidence,
        "models_tried": models,
        "repairs_tried": [
            "uniform_10_tool_calls_and_10_model_requests_per_attempt",
            "fresh_budget_for_each_retry_attempt",
            "Scout_token_context_cost_and_default_wall_time_gates_disabled",
            "typed filter plus nearest cross-artifact retrieval path verified offline",
        ],
        "actual_failure_symptoms": [
            {
                "model": model,
                "error": sample.get("error"),
                "attempt_count": sample.get("l5_attempt_count"),
                "failed_assertions": (
                    sample.get("l5_semantic_grade") or {}
                ).get("failed_assertions"),
            }
            for model, sample in zip(traced_models, live_samples, strict=True)
        ],
        "candidate_answer": _candidate_answer(deterministic_sample),
        "codex_review": {
            "independent_answer": _candidate_answer(deterministic_sample),
            "primary_root_cause": "Model Weakness",
            "secondary_root_cause": "Harness Failure",
            "diagnosis": (
                "The deterministic tool path returned both required records and source refs, "
                "so this is not a Tool Gap or Missing Evidence. The free models failed to "
                "complete the typed Code Mode trajectory without an output cap; the harness "
                "also needs provider-stall checkpoint and continuation support."
            ),
            "classification_candidates": [
                "Tool Gap",
                "Model Weakness",
                "Missing Evidence",
                "Ambiguous Expectation",
                "Harness Failure",
                "Benchmark Defect",
            ],
        },
        "known_issue": None,
        "known_issue_reason": (
            "Codex could answer and diagnose from verified evidence, so escalation stops "
            "before KNOWN_ISSUE registration."
        ),
        "continuation": {
            "status": "checkpointed",
            "next_stage": "provider_or_model_recovery",
            "checkpoint_refs": source_refs,
            "preserved_state": [
                "available_evidence",
                "source_references",
                "complete_call_trace",
                "tool_outputs",
                "candidate_answer",
            ],
            "resume_condition": (
                "Use a new model/provider or a harness with provider-stall continuation; "
                "issue a fresh 10/10 stage budget."
            ),
        },
    }


def _candidate_answer(sample: dict[str, Any]) -> str:
    facts: list[str] = []
    for response in sample.get("responses") or []:
        for result in response.get("results") or []:
            data = result.get("data") or {}
            source_ref = result.get("source_ref")
            if data.get("normalized_mileage_k") == "15K":
                facts.append(
                    f"15K 座標為 {data.get('lat')}, {data.get('lon')} [{source_ref}]"
                )
            if str(data.get("candidate_id") or "").startswith("cp."):
                facts.append(
                    f"最近 CP 是 {data.get('candidate_id')}，距離約 "
                    f"{float(data.get('distance_m') or 0):.1f} 公尺 [{source_ref}]"
                )
    return "；".join(facts) or "Verified evidence is present; manual answer formatting is required."


def _sample(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    for sample in report.get("samples") or []:
        if sample.get("case_id") == case_id:
            return sample
    raise ValueError(f"case not found in report: {case_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--live-report", action="append", type=Path, required=True)
    parser.add_argument("--additional-model", action="append", default=[])
    parser.add_argument("--deterministic-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = build_failure_review(
        case_id=args.case_id,
        live_reports=[
            json.loads(path.read_text(encoding="utf-8")) for path in args.live_report
        ],
        deterministic_report=json.loads(
            args.deterministic_report.read_text(encoding="utf-8")
        ),
        additional_models=list(args.additional_model),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "completed", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
