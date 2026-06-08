"""CLI for Scout AI OS hardware-safe readiness smoke."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scout.hardware import build_hardware_smoke_profile, run_hardware_smoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Scout AI OS hardware-safe smoke profile."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Scout Fusion repository root.",
    )
    parser.add_argument(
        "--hardware-target",
        default="scout_hardware",
        help="Human-readable hardware target label for the report.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional .env path. Defaults to <repo-root>/.env.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional external model alias, used only with --allow-external-model.",
    )
    parser.add_argument(
        "--allow-external-model",
        action="store_true",
        help="Allow this smoke to use an external Pydantic AI model provider.",
    )
    parser.add_argument(
        "--evidence-json",
        default=None,
        help="Optional hardware/mobile evidence JSON to validate for boundary flags.",
    )
    parser.add_argument(
        "--profile-only",
        action="store_true",
        help="Print the hardware smoke profile without running checks.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    env_file = Path(args.env_file) if args.env_file else None
    if args.profile_only:
        payload = build_hardware_smoke_profile(
            repo_root=repo_root,
            hardware_target=args.hardware_target,
            model=args.model,
            allow_external_model=args.allow_external_model,
            env_file=env_file,
        )
    else:
        report = run_hardware_smoke(
            repo_root=repo_root,
            hardware_target=args.hardware_target,
            model=args.model,
            allow_external_model=args.allow_external_model,
            env_file=env_file,
            evidence_json=Path(args.evidence_json) if args.evidence_json else None,
        )
        payload = report.model_dump(mode="json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
