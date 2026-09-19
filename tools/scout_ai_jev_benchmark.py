#!/usr/bin/env python3
"""Run the isolated Jev compatibility benchmark against one Scout workspace.

The workspace is read-only.  The only payload sent to OpenRouter is the
allowlisted aggregate projection and synthetic benchmark question state built
by :mod:`scout.nextgen.jev_decisions`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from scout.nextgen.jev_decisions import (
    JEvEndpoint,
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
    build_jev_benchmark_cases,
    build_jev_dataset,
    run_jev_benchmark,
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
        default=Path("artifacts/jev-benchmark-20260919"),
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
    projection = build_anonymized_workspace_projection(args.workspace)
    cases = build_jev_benchmark_cases(projection)
    dataset = build_jev_dataset(projection, cases)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.output_dir / "jev-anonymized-dataset.json"
    _write_json(dataset_path, dataset.model_dump(mode="json"))

    print(
        json.dumps(
            {
                "dataset": str(dataset_path),
                "dataset_hash": dataset.dataset_hash,
                "cases": len(cases),
                "workspace_projection_hash": projection.projection_hash,
                "endpoint": JEvEndpoint,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.dry_run:
        return 0

    key = _api_key(args.env_file)
    models = tuple(args.models or DEFAULT_MODELS)
    for model_id in models:
        client = OpenRouterJevClient(
            api_key=key,
            model_id=model_id,
            timeout_seconds=args.timeout_seconds,
        )
        report = run_jev_benchmark(
            model_id=model_id,
            cases=cases,
            client=client,
            workspace_root=args.workspace,
            dataset_hash=dataset.dataset_hash,
            workspace_projection_hash=projection.projection_hash,
        )
        report_path = args.output_dir / f"jev-report-{_safe_model_filename(model_id)}.json"
        _write_json(report_path, report.model_dump(mode="json"))
        print(
            json.dumps(
                {
                    "model": model_id,
                    "report": str(report_path),
                    "disposition": report.disposition.value,
                    "passed_cases": report.metrics.passed_cases,
                    "total_cases": report.metrics.total_cases,
                    "decision_accuracy": report.metrics.decision_accuracy,
                    "critical_failures": report.metrics.critical_failures,
                    "query_executor_successes": report.metrics.query_executor_successes,
                    "query_cases": report.metrics.query_cases,
                    "input_tokens": report.metrics.total_input_tokens,
                    "output_tokens": report.metrics.total_output_tokens,
                    "cost": report.metrics.total_cost,
                    "latency_ms": report.metrics.total_latency_ms,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
