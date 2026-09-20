#!/usr/bin/env python3
"""Run a small Six-Forces answer slice with a visible Jev preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scout.nextgen.jev_decisions import (  # noqa: E402
    JevDecisionError,
    JevDecisionRequest,
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
)
from scout.nextgen.jev_decision_service import (  # noqa: E402
    _routing_questions,
    parse_jev_signals,
)
from tools.scout_ai_six_forces_aihat2_eval import (  # noqa: E402
    execute_run,
    expand_case_runs,
)
from tools.scout_ai_six_forces_openrouter_eval import (  # noqa: E402
    OPENROUTER_ENDPOINT,
    OpenRouterModelCaller,
    build_openrouter_model_adapter,
)


JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_SCENARIO = Path(
    "outputs/evals/scout_ai_six_forces_600_scenarios_20260919.json"
)
DEFAULT_DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_jev_preflight_request(
    *,
    model_id: str,
    projection: Any,
    run: dict[str, Any],
) -> JevDecisionRequest:
    """Build a path-free Jev request without granting execution authority."""

    force_code = str(run.get("force_code") or "")
    required_domains = {
        "EXP": ["route", "terrain", "weather"],
        "NAV": ["route", "map"],
        "RTE": ["route", "terrain"],
        "RPF": ["route", "terrain"],
        "WTH": ["weather", "route"],
        "PER": ["permission", "route"],
    }.get(force_code, ["route"])
    state = {
        "task_kind": "six_forces_answer_preflight",
        "language": "zh-tw",
        "user_question": str(run["question_text"]),
        "force_code": force_code,
        "scenario_id": str(run.get("scenario_id") or ""),
        "variant_id": str(run.get("variant_id") or ""),
        "required_domains": required_domains,
        "workspace": projection.model_dump(mode="json"),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return JevDecisionRequest(
        model=model_id,
        state=state,
        questions=_routing_questions(),
    )


def _event(
    *,
    log_file,
    event: str,
    index: int,
    total: int,
    run: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    record = {
        "event": event,
        "index": index,
        "total": total,
        "run_case_id": str(run["run_case_id"]),
        "question_id": str(run["question_id"]),
        "payload": payload,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    log_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    log_file.flush()
    prefix = (
        f"[six-jev-live] {index}/{total} "
        f"case_id={run['run_case_id']}"
    )
    if event == "jev_request":
        print(
            f"{prefix} JEV_REQUEST endpoint={JEV_ENDPOINT} "
            f"model={payload['model']} questions={','.join(payload['question_ids'])}",
            file=sys.stderr,
            flush=True,
        )
    elif event == "jev_response":
        print(
            f"{prefix} JEV_RESPONSE status={payload['status']} "
            f"latency_ms={payload['latency_ms']} "
            f"signals={json.dumps(payload.get('signals') or {}, ensure_ascii=False, sort_keys=True)}",
            file=sys.stderr,
            flush=True,
        )
    elif event == "deepseek_request":
        print(
            f"{prefix} DEEPSEEK_REQUEST model={payload['model']} "
            f"endpoint={OPENROUTER_ENDPOINT} max_model_requests={payload['max_model_requests']}",
            file=sys.stderr,
            flush=True,
        )
    elif event == "answer_result":
        print(
            f"{prefix} ANSWER_RESULT verifier={payload['verifier']} "
            f"quality={payload['quality']} model_requests={payload['model_requests']}",
            file=sys.stderr,
            flush=True,
        )


def _run_preflight(
    *,
    client: OpenRouterJevClient,
    model_id: str,
    projection: Any,
    run: dict[str, Any],
    index: int,
    total: int,
    log_file,
) -> dict[str, Any]:
    request = build_jev_preflight_request(
        model_id=model_id,
        projection=projection,
        run=run,
    )
    started = time.perf_counter()
    _event(
        log_file=log_file,
        event="jev_request",
        index=index,
        total=total,
        run=run,
        payload={
            "endpoint": JEV_ENDPOINT,
            "model": model_id,
            "question_ids": list(request.questions),
            "state_hash": _hash_payload(request.state),
        },
    )
    try:
        response = client.decide(request)
        signals = parse_jev_signals(response)
        status = "ok"
        error = None
        usage = response.usage.model_dump(mode="json")
    except (JevDecisionError, ValueError) as exc:
        signals = None
        status = "error"
        error = type(exc).__name__
        usage = None
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    payload = {
        "status": status,
        "latency_ms": latency_ms,
        "signals": signals.model_dump(mode="json") if signals is not None else None,
        "usage": usage,
        "error": error,
    }
    _event(
        log_file=log_file,
        event="jev_response",
        index=index,
        total=total,
        run=run,
        payload=payload,
    )
    return {
        "endpoint": JEV_ENDPOINT,
        "model": model_id,
        "status": status,
        "latency_ms": latency_ms,
        "state_hash": _hash_payload(request.state),
        "signals": payload["signals"],
        "usage": usage,
        "error": error,
        "request_count": 1,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--scenario-artifact", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--deepseek-model", default=DEFAULT_DEEPSEEK_MODEL)
    parser.add_argument("--jev-model", default=DEFAULT_JEV_MODEL)
    parser.add_argument("--max-runs", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--max-model-requests", type=int, default=10)
    parser.add_argument(
        "--mser-mode",
        choices=("off", "shadow", "enforce"),
        default="shadow",
    )
    parser.add_argument(
        "--guided-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--jev-timeout-seconds", type=float, default=120.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_runs <= 0:
        raise SystemExit("--max-runs must be positive")
    if args.max_model_requests < 10:
        raise SystemExit("--max-model-requests must be >= 10")
    workspace = args.workspace.expanduser().resolve(strict=True)
    scenario_path = args.scenario_artifact.expanduser()
    if not scenario_path.is_absolute():
        scenario_path = workspace / scenario_path
    artifact = json.loads(scenario_path.read_text(encoding="utf-8"))
    runs = expand_case_runs(artifact)[: args.max_runs]
    projection = build_anonymized_workspace_projection(workspace)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    events_path = args.output_dir / "jev-live-events.jsonl"
    results_path = args.output_dir / "per_case_results.jsonl"
    manifest_path = args.output_dir / "run_manifest.json"
    manifest = {
        "schema_version": "scout.six_forces_jev_smoke_manifest.v1",
        "workspace": str(workspace),
        "scenario_artifact": str(scenario_path),
        "scenario_artifact_sha256": hashlib.sha256(
            scenario_path.read_bytes()
        ).hexdigest(),
        "selected_run_count": len(runs),
        "deepseek_model": args.deepseek_model,
        "jev_model": args.jev_model,
        "jev_endpoint": JEV_ENDPOINT,
        "deepseek_endpoint": OPENROUTER_ENDPOINT,
        "workspace_projection_hash": projection.projection_hash,
        "max_model_requests": args.max_model_requests,
        "mser_mode": args.mser_mode,
        "guided_retry": args.guided_retry,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(manifest_path, manifest)
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is required in the process environment")
    jev_client = OpenRouterJevClient(
        api_key=key,
        model_id=args.jev_model,
        timeout_seconds=args.jev_timeout_seconds,
    )
    deepseek_caller = OpenRouterModelCaller(
        model_name=args.deepseek_model,
        api_key=key,
        max_tokens=None,
        thinking=None,
    )
    deepseek_adapter = build_openrouter_model_adapter(
        deepseek_caller,
        contextual_model_call=deepseek_caller.call_with_context,
    )
    summary_rows: list[dict[str, Any]] = []
    with events_path.open("w", encoding="utf-8") as event_file:
        with results_path.open("w", encoding="utf-8") as result_file:
            for index, run in enumerate(runs, 1):
                jev = _run_preflight(
                    client=jev_client,
                    model_id=args.jev_model,
                    projection=projection,
                    run=run,
                    index=index,
                    total=len(runs),
                    log_file=event_file,
                )
                _event(
                    log_file=event_file,
                    event="deepseek_request",
                    index=index,
                    total=len(runs),
                    run=run,
                    payload={
                        "endpoint": OPENROUTER_ENDPOINT,
                        "model": args.deepseek_model,
                        "max_model_requests": args.max_model_requests,
                    },
                )
                started = time.perf_counter()
                try:
                    answer = execute_run(
                        run=run,
                        project_root=workspace,
                        endpoint=OPENROUTER_ENDPOINT,
                        model=f"openrouter:{args.deepseek_model}",
                        timeout_seconds=args.timeout_seconds,
                        max_model_requests=args.max_model_requests,
                        guided_retry=args.guided_retry,
                        model_adapter=deepseek_adapter,
                        mser_mode=args.mser_mode,
                    )
                except Exception as exc:  # preserve one-row evidence on failure
                    answer = {
                        "verifier": {"status": "error", "errors": [type(exc).__name__]},
                        "answer_quality_screen": {
                            "classification": "quality_fail",
                            "failure_reasons": ["run_exception"],
                        },
                        "model_request_count": 0,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "run_error_type": type(exc).__name__,
                    }
                answer_payload = {
                    "verifier": str((answer.get("verifier") or {}).get("status")),
                    "quality": str(
                        (answer.get("answer_quality_screen") or {}).get(
                            "classification", "unknown"
                        )
                    ),
                    "model_requests": int(answer.get("model_request_count") or 0),
                    "latency_ms": max(0, int((time.perf_counter() - started) * 1000)),
                }
                _event(
                    log_file=event_file,
                    event="answer_result",
                    index=index,
                    total=len(runs),
                    run=run,
                    payload=answer_payload,
                )
                row = {
                    "run_case_id": run["run_case_id"],
                    "question_id": run["question_id"],
                    "question": run["question_text"],
                    "force": run["force_code"],
                    "jev_preflight": jev,
                    "answer": answer,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
                result_file.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                )
                result_file.flush()
                summary_rows.append(
                    {
                        "run_case_id": run["run_case_id"],
                        "question_id": run["question_id"],
                        "jev_status": jev["status"],
                        "jev_request_count": jev["request_count"],
                        "answer_verifier": answer_payload["verifier"],
                        "answer_quality": answer_payload["quality"],
                        "deepseek_model_requests": answer_payload["model_requests"],
                    }
                )
    summary = {
        "schema_version": "scout.six_forces_jev_smoke_summary.v1",
        "selected_cases": len(summary_rows),
        "jev_requests": sum(item["jev_request_count"] for item in summary_rows),
        "jev_successes": sum(item["jev_status"] == "ok" for item in summary_rows),
        "jev_failures": sum(item["jev_status"] != "ok" for item in summary_rows),
        "answer_verifier_passes": sum(
            item["answer_verifier"] == "pass" for item in summary_rows
        ),
        "deepseek_model_requests": sum(
            item["deepseek_model_requests"] for item in summary_rows
        ),
        "deepseek_model": args.deepseek_model,
        "jev_model": args.jev_model,
        "jev_endpoint": JEV_ENDPOINT,
        "deepseek_endpoint": OPENROUTER_ENDPOINT,
        "workspace_projection_hash": projection.projection_hash,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "cases": summary_rows,
    }
    _write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
