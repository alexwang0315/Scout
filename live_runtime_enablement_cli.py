from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from live_runtime_enablement import (
    LiveRuntimeGate,
    build_live_runtime_enablement_report,
)


def run_live_runtime_enablement_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, object]]:
    args = _build_parser().parse_args(argv)
    env = dict(os.environ)
    for env_file in args.env_file:
        env.update(_load_env_file(env_file))

    requested_gates = (
        {LiveRuntimeGate(gate) for gate in args.gate}
        if args.gate
        else set(LiveRuntimeGate)
    )
    report = build_live_runtime_enablement_report(
        env,
        requested_gates=requested_gates,
    )
    payload = report.model_dump(mode="json")
    output = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")

    return (0 if report.ready else 2), payload


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_live_runtime_enablement_cli(argv)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a preflight-only live runtime enablement report. This does "
            "not connect to models, send network requests, mutate Scout state, "
            "or control hardware."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        action="append",
        default=[],
        help="Optional KEY=VALUE overlay file. Values are used for availability checks only.",
    )
    parser.add_argument(
        "--gate",
        action="append",
        choices=[gate.value for gate in LiveRuntimeGate],
        help="Gate to check. May be repeated. Defaults to all gates.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report output path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{path}:{line_number}: missing key")
        values[key] = _strip_optional_quotes(value.strip())
    return values


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
