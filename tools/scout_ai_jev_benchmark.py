#!/usr/bin/env python3
"""Run the Scout Jev baseline/shadow/active benchmark on one workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from scout.nextgen.jev_decisions import (  # noqa: E402
    JEvEndpoint,
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
)
from scout.nextgen.jev_decision_service import (  # noqa: E402
    build_jev_experiment_cases,
    build_jev_experiment_dataset,
    run_jev_experiment,
)


DEFAULT_MODELS = ("typesafe/jev-1.13", "~typesafe/jev-latest")


def _read_env_value(path: Path, key: str) -> str:
    """Read one dotenv value without exposing the file or any other secret."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"cannot read env file: {path}") from exc
    prefix = f"{key}="
    for line in lines:
        candidate = line.strip()
        if candidate.startswith("export "):
            candidate = candidate[7:].lstrip()
        if not candidate.startswith(prefix):
            continue
        value = candidate[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            return value
    raise SystemExit(f"{key} is absent or empty in the supplied env file")


def _api_key(env_file: Path | None) -> str:
    if env_file is not None:
        return _read_env_value(env_file, "OPENROUTER_API_KEY")
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not value:
        raise SystemExit(
            "OPENROUTER_API_KEY is required; use --env-file or the process environment"
        )
    return value


def _safe_model_filename(model_id: str) -> str:
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", model_id).strip("._")
    return filename or "model"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        help="OpenRouter Decisions model id; repeat to compare models",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/jev-experiment-20260919"),
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help=(
            "Run only the first N deterministic experiment cases while "
            "retaining the full dataset hash"
        ),
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help=(
            "Print redacted per-case routing, JEV request/response, "
            "and mode-result events"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write the anonymized dataset but do not call OpenRouter",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.max_cases is not None and args.max_cases <= 0:
        raise SystemExit("--max-cases must be positive")
    projection = build_anonymized_workspace_projection(args.workspace)
    all_cases = build_jev_experiment_cases(projection)
    cases = (
        all_cases[: args.max_cases]
        if args.max_cases is not None
        else all_cases
    )
    dataset = build_jev_experiment_dataset(projection, all_cases)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.output_dir / "jev-anonymized-dataset.json"
    _write_json(dataset_path, dataset.model_dump(mode="json"))
    selection_path = args.output_dir / "jev-run-selection.json"
    _write_json(
        selection_path,
        {
            "dataset_hash": dataset.dataset_hash,
            "workspace_projection_hash": projection.projection_hash,
            "full_case_count": len(all_cases),
            "selected_case_count": len(cases),
            "selected_case_ids": [case.case_id for case in cases],
            "candidate_only": dataset.candidate_only,
            "runtime_safety_truth": dataset.runtime_safety_truth,
        },
    )
    print(
        json.dumps(
            {
                "dataset": str(dataset_path),
                "selection": str(selection_path),
                "dataset_hash": dataset.dataset_hash,
                "full_cases": len(all_cases),
                "selected_cases": len(cases),
                "workspace_projection_hash": projection.projection_hash,
                "endpoint": JEvEndpoint,
                "dry_run": args.dry_run,
                "candidate_only": dataset.candidate_only,
                "runtime_safety_truth": dataset.runtime_safety_truth,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.dry_run:
        return 0

    key = _api_key(args.env_file)
    for model_id in tuple(args.models or DEFAULT_MODELS):
        client = OpenRouterJevClient(
            api_key=key,
            model_id=model_id,
            timeout_seconds=args.timeout_seconds,
        )
        case_index = {case.case_id: index for index, case in enumerate(cases, 1)}

        def progress_callback(event, case, payload):
            if not args.progress:
                return
            index = case_index[case.case_id]
            prefix = (
                f"[jev-live] model={model_id} "
                f"case={index}/{len(cases)} case_id={case.case_id}"
            )
            if event == "case_route":
                print(
                    f"{prefix} route={payload['deterministic_route']} "
                    f"fast_lane={payload['fast_lane']} "
                    f"jev_called={not payload['fast_lane']}",
                    file=sys.stderr,
                    flush=True,
                )
            elif event == "jev_request":
                print(
                    f"{prefix} JEV_REQUEST endpoint={JEvEndpoint} "
                    f"questions={','.join(payload['question_ids'])}",
                    file=sys.stderr,
                    flush=True,
                )
            elif event == "jev_response":
                signals = payload.get("signals") or {}
                print(
                    f"{prefix} JEV_RESPONSE status={payload['status']} "
                    f"latency_ms={payload['latency_ms']} "
                    f"signals={json.dumps(signals, ensure_ascii=False, sort_keys=True)}",
                    file=sys.stderr,
                    flush=True,
                )
            elif event == "mode_result":
                print(
                    f"{prefix} mode={payload['mode']} "
                    f"jev_called={payload['jev_called']} "
                    f"disposition={payload['final_disposition']} "
                    f"passed={payload['passed']}",
                    file=sys.stderr,
                    flush=True,
                )

        report = run_jev_experiment(
            model_id=model_id,
            cases=cases,
            client=client,
            dataset_hash=dataset.dataset_hash,
            workspace_projection_hash=projection.projection_hash,
            workspace_root=args.workspace,
            progress_callback=progress_callback,
        )
        report_path = args.output_dir / f"jev-experiment-{_safe_model_filename(model_id)}.json"
        _write_json(report_path, report.model_dump(mode="json"))
        print(
            json.dumps(
                {
                    "model": model_id,
                    "report": str(report_path),
                    "modes": [
                        {
                            "mode": mode.mode.value,
                            "passed_cases": mode.metrics.passed_cases,
                            "total_cases": mode.metrics.total_cases,
                            "decision_accuracy": mode.metrics.decision_accuracy,
                            "raw_signal_accuracy": mode.metrics.raw_signal_accuracy,
                            "evidence_score_accuracy": mode.metrics.evidence_score_accuracy,
                            "route_accuracy": mode.metrics.route_accuracy,
                            "disposition_accuracy": mode.metrics.disposition_accuracy,
                            "fast_lane_cases": mode.metrics.fast_lane_cases,
                            "jev_called_cases": mode.metrics.jev_called_cases,
                            "model_requests": mode.metrics.total_model_requests,
                            "input_tokens": mode.metrics.total_input_tokens,
                            "output_tokens": mode.metrics.total_output_tokens,
                            "cost": mode.metrics.total_cost,
                            "latency_ms": mode.metrics.total_latency_ms,
                            "over_escalations": mode.metrics.over_escalations,
                            "boundary_guard_triggers": mode.metrics.boundary_guard_triggers,
                            "query_cases": mode.metrics.query_cases,
                            "query_executor_successes": mode.metrics.query_executor_successes,
                            "expensive_disposition_count": mode.metrics.expensive_disposition_count,
                            "critical_safety_boundary_violations": (
                                mode.metrics.critical_safety_boundary_violations
                            ),
                            "failure_counts": mode.metrics.failure_counts,
                        }
                        for mode in report.mode_reports
                    ],
                    "candidate_only": report.candidate_only,
                    "runtime_safety_truth": report.runtime_safety_truth,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
