#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.qualification.domains.contextual_permission_runner import (  # noqa: E402
    run_contextual_permission_qualification,
)
from tests.qualification.phase3_catalog import DOMAIN_IDS  # noqa: E402
from tests.qualification.phase3_runner import (  # noqa: E402
    run_phase3_all_qualification,
    run_phase3_domain_qualification,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run pre-release Dashboard program-logic qualification."
    )
    parser.add_argument(
        "--domain",
        choices=DOMAIN_IDS,
        default=None,
    )
    parser.add_argument(
        "--execution-dir",
        type=Path,
        required=True,
        help="Unique empty root for isolated production replays.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Unique non-existent result root for canonical outputs.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the Phase 3 construction gate across all Dashboard domains.",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Run the full gate against an explicitly supplied sealed workspace inventory.",
    )
    parser.add_argument(
        "--workspace-inventory",
        type=Path,
        help="Explicit read-only workspace root; required only with --release.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    selected_modes = sum(
        (
            args.domain is not None,
            bool(args.all),
            bool(args.release),
        )
    )
    if selected_modes > 1:
        print("INVALID: choose exactly one of --domain, --all, or --release.", file=sys.stderr)
        return 2
    domain = args.domain or (None if args.all or args.release else "contextual-permission")
    if args.release and args.workspace_inventory is None:
        print("INVALID: --release requires --workspace-inventory PATH.", file=sys.stderr)
        return 2
    if not args.release and args.workspace_inventory is not None:
        print("INVALID: --workspace-inventory is only valid with --release.", file=sys.stderr)
        return 2
    try:
        if args.all or args.release:
            phase3 = run_phase3_all_qualification(
                repository_root=REPOSITORY_ROOT,
                execution_root=args.execution_dir,
                result_root=args.output_dir,
                release=bool(args.release),
                workspace_inventory=args.workspace_inventory,
            )
            print(
                f"{phase3.report.verdict.upper()} "
                f"run={phase3.report.run_id} "
                f"claim={phase3.report.claim} "
                f"report={phase3.finalized.aggregate_json} "
                f"sha256={phase3.finalized.content_sha256}"
            )
            return phase3.exit_code
        assert domain is not None
        if domain == "contextual-permission":
            outcome = run_contextual_permission_qualification(
                repository_root=REPOSITORY_ROOT,
                execution_root=args.execution_dir,
                result_root=args.output_dir,
            )
        else:
            focused = run_phase3_domain_qualification(
                domain,
                repository_root=REPOSITORY_ROOT,
                execution_root=args.execution_dir,
                result_root=args.output_dir,
            )
            print(
                f"{focused.report.verdict.upper()} "
                f"run={focused.report.run_id} "
                f"domain={focused.report.domain_id} "
                f"report={focused.finalized.canonical_json} "
                f"sha256={focused.finalized.content_sha256}"
            )
            return focused.exit_code
    except (OSError, RuntimeError, ValueError) as error:
        print(f"INVALID: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(
        f"{outcome.report.verdict.upper()} "
        f"run={outcome.report.run_id} "
        f"report={outcome.finalized.canonical_json} "
        f"sha256={outcome.finalized.content_sha256}"
    )
    return outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
