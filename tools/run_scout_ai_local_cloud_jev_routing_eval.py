"""Run deterministic or live JEV routing on the mixed 20-question corpus."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.nextgen.jev_decisions import (  # noqa: E402
    JevDecisionError,
    OpenRouterJevClient,
)
from scout.nextgen.jev_model_routing import (  # noqa: E402
    ModelRoute,
    build_jev_route_request,
    deterministic_route,
    evaluate_jev_route,
    load_routing_corpus,
)


DEFAULT_CORPUS = ROOT / "docs/specs/scout-ai-local-cloud-mixed-20-question-eval.json"
DEFAULT_OUTPUT = ROOT / "outputs/evals/local_cloud_jev_routing_smoke"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"


def _row(question, *, mode: str, decision=None, error=None, latency_ms=0) -> dict[str, Any]:
    expected = question.expected_route
    deterministic = deterministic_route(question)
    return {
        "question_id": question.question_id,
        "question": question.question,
        "expected_route": expected.value,
        "deterministic_route": deterministic.value,
        "deterministic_route_correct": deterministic is expected,
        "mode": mode,
        "jev_status": decision.jev_status if decision else "not_called",
        "jev_choice": decision.jev_choice.value if decision and decision.jev_choice else None,
        "final_route": decision.final_route.value if decision else deterministic.value,
        "jev_choice_correct": bool(decision and decision.jev_choice is expected),
        "final_route_correct": None
        if error
        else bool(decision and decision.final_route is expected)
        if decision
        else deterministic is expected,
        "downgrade_blocked": decision.downgrade_blocked if decision else False,
        "reason": decision.reason if decision else "dry_run_no_jev_call",
        "latency_ms": latency_ms,
        "error": error,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def run(args: argparse.Namespace) -> int:
    corpus = load_routing_corpus(args.corpus)
    args.output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    client = None
    mode = "dry_run"
    if not args.dry_run:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            rows = [
                _row(
                    question,
                    mode="live_jev",
                    error="OPENROUTER_API_KEY_ABSENT",
                )
                for question in corpus.questions
            ]
            summary = {
                "schema_version": "scout.ai.local_cloud_jev_routing_eval.v1",
                "corpus": str(args.corpus),
                "jev_model": args.jev_model,
                "mode": "live_jev",
                "question_count": len(rows),
                "completed_count": 0,
                "error_count": len(rows),
                "jev_call_count": 0,
                "status": "BLOCKED",
                "blocker": "OPENROUTER_API_KEY_ABSENT",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            (args.output / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (args.output / "per_question.jsonl").write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                    for row in rows
                ),
                encoding="utf-8",
            )
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 2
        client = OpenRouterJevClient(
            api_key=api_key,
            model_id=args.jev_model,
            timeout_seconds=args.timeout_seconds,
        )
        mode = "live_jev"

    for index, question in enumerate(corpus.questions, 1):
        decision = None
        error = None
        started = time.perf_counter()
        if client is not None:
            print(
                f"[JEV-ROUTING] {index}/{len(corpus.questions)} "
                f"id={question.question_id} expected={question.expected_route.value} "
                f"question={question.question}",
                flush=True,
            )
            try:
                response = client.decide(
                    build_jev_route_request(question, model_id=args.jev_model)
                )
                decision = evaluate_jev_route(question, response)
            except (JevDecisionError, ValueError, TimeoutError) as exc:
                error = type(exc).__name__
            latency_ms = max(0, round((time.perf_counter() - started) * 1000))
            row = _row(
                question,
                mode=mode,
                decision=decision,
                error=error,
                latency_ms=latency_ms,
            )
            print(
                f"[JEV-ROUTING] result id={question.question_id} "
                f"jev={row['jev_choice'] or 'ERROR'} final={row['final_route']} "
                f"correct={row['jev_choice_correct']} latency_ms={latency_ms}",
                flush=True,
            )
        else:
            row = _row(question, mode=mode)
            print(
                f"[JEV-ROUTING-DRY] {index}/{len(corpus.questions)} "
                f"id={question.question_id} expected={question.expected_route.value} "
                f"deterministic={row['deterministic_route']}",
                flush=True,
            )
        rows.append(row)

    completed = [row for row in rows if row["error"] is None]
    summary = {
        "schema_version": "scout.ai.local_cloud_jev_routing_eval.v1",
        "corpus": str(args.corpus),
        "jev_model": args.jev_model if client else None,
        "mode": mode,
        "question_count": len(rows),
        "completed_count": len(completed),
        "error_count": len(rows) - len(completed),
        "jev_choice_correct": sum(row["jev_choice_correct"] for row in completed),
        "final_route_correct": sum(row["final_route_correct"] for row in completed),
        "over_escalation_count": sum(
            row["expected_route"] == "local" and row["final_route"] != "local"
            for row in completed
        ),
        "downgrade_blocked_count": sum(row["downgrade_blocked"] for row in completed),
        "status": "PASS"
        if client and len(completed) == len(rows) and all(row["jev_choice_correct"] for row in completed)
        else "PARTIAL"
        if client
        else "NOT_VERIFIED",
        "started_at": datetime.now(UTC).isoformat(),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "per_question.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] in {"PASS", "NOT_VERIFIED"} else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--jev-model", default=DEFAULT_JEV_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
