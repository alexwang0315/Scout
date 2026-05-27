from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from scout_agent_models import ScoutAgentToolBoundary
from scout_agent_runtime import load_agent_tool_plan, run_agent_tool_plan
from scout_agent_tools import (
    find_tool_manifest,
    load_tool_manifests,
    manifest_validation_error_to_payload,
    run_registered_tool,
    summarize_tool_manifest,
)


def run_scout_agent_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, object]]:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_group == "tools" and args.tool_command == "list":
            manifests = load_tool_manifests(args.manifest_dir)
            return 0, {
                "artifact_kind": "scout_agent_tool_list",
                "tools": [summarize_tool_manifest(manifest) for manifest in manifests],
                "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
            }
        if args.command_group == "tools" and args.tool_command == "describe":
            manifest = find_tool_manifest(args.manifest_dir, args.tool_id)
            return 0, {
                "artifact_kind": "scout_agent_tool_manifest",
                "manifest": manifest.model_dump(mode="json"),
                "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
            }
        if args.command_group == "tools" and args.tool_command == "run":
            manifest = find_tool_manifest(args.manifest_dir, args.tool_id)
            result = run_registered_tool(
                manifest,
                input_path=args.input,
                output_path=args.output,
                trace_log_path=args.trace_log,
                agent_run_id=args.agent_run_id,
                action_id=args.action_id,
                dry_run=args.dry_run,
                authorized_by=args.authorized_by,
            )
            exit_code = _exit_code_for_status(result.status)
            return exit_code, result.model_dump(mode="json")
        if args.command_group == "agent" and args.agent_command == "run-plan":
            plan = load_agent_tool_plan(args.plan)
            execution = run_agent_tool_plan(
                plan,
                manifest_dir=args.manifest_dir,
                trace_log_path=args.trace_log,
            )
            return _exit_code_for_status(execution.status), execution.model_dump(mode="json")
    except ValidationError as exc:
        return 2, manifest_validation_error_to_payload(exc)
    except Exception as exc:  # noqa: BLE001 - CLI reports structured failures.
        return 2, {
            "artifact_kind": "scout_agent_cli_error",
            "status": "failed",
            "error": str(exc),
            "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
        }
    return 2, {
        "artifact_kind": "scout_agent_cli_error",
        "status": "failed",
        "error": "unsupported command",
        "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout Agent tool registry CLI.")
    subparsers = parser.add_subparsers(dest="command_group", required=True)

    tools_parser = subparsers.add_parser("tools", help="List, describe, and run registered tools.")
    tools_subparsers = tools_parser.add_subparsers(dest="tool_command", required=True)

    list_parser = tools_subparsers.add_parser("list", help="List registered Scout agent tools.")
    list_parser.add_argument("--manifest-dir", type=Path, required=True)
    list_parser.add_argument("--json", action="store_true", help="Kept for the common CLI contract.")

    describe_parser = tools_subparsers.add_parser("describe", help="Describe one Scout agent tool.")
    describe_parser.add_argument("tool_id")
    describe_parser.add_argument("--manifest-dir", type=Path, required=True)
    describe_parser.add_argument("--json", action="store_true", help="Kept for the common CLI contract.")

    run_parser = tools_subparsers.add_parser("run", help="Run one registered Scout agent tool.")
    run_parser.add_argument("tool_id")
    run_parser.add_argument("--manifest-dir", type=Path, required=True)
    run_parser.add_argument("--input", type=Path, default=None)
    run_parser.add_argument("--output", type=Path, default=None)
    run_parser.add_argument("--trace-log", type=Path, default=None)
    run_parser.add_argument("--agent-run-id", default="agent_run.local.manual")
    run_parser.add_argument("--action-id", default="agent_action.local.manual")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--authorized-by", default=None)
    run_parser.add_argument("--json", action="store_true", help="Kept for the common CLI contract.")

    agent_parser = subparsers.add_parser("agent", help="Run Scout agent tool plans.")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)
    plan_parser = agent_subparsers.add_parser(
        "run-plan",
        help="Run a structured Scout agent tool plan through registered manifests.",
    )
    plan_parser.add_argument("--manifest-dir", type=Path, required=True)
    plan_parser.add_argument("--plan", type=Path, required=True)
    plan_parser.add_argument("--trace-log", type=Path, default=None)
    plan_parser.add_argument("--json", action="store_true", help="Kept for the common CLI contract.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_scout_agent_cli(argv)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _exit_code_for_status(status: object) -> int:
    value = str(status)
    if value.endswith("completed"):
        return 0
    if value.endswith("partial"):
        return 3
    if value.endswith("blocked"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
