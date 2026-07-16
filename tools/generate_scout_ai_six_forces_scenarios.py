from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout_ai_six_forces_scenarios import (  # noqa: E402
    artifact_statistics,
    build_per095_replay_contexts,
    build_weather_evidence_receipt,
    generate_boss_approach_anchors,
    generate_case_mapping,
)


DEFAULT_WORKSPACE = Path(
    "/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI"
)
DEFAULT_CORPUS = ROOT / "docs/specs/scout-ai-six-forces-600-question-corpus.md"
DEFAULT_REPLAY_FIXTURE = (
    ROOT / "tests/fixtures/scout_ai_six_forces/deterministic_cwa_replay.json"
)


def build_artifact(args: argparse.Namespace) -> dict[str, object]:
    observed_at = args.observed_at or datetime.now(timezone.utc).isoformat()
    scenarios = generate_boss_approach_anchors(
        args.workspace,
        observed_at=observed_at,
        source_mode=args.source_mode,
    )
    weather = build_weather_evidence_receipt(
        scenarios,
        mode=args.weather_mode,
        replay_fixture_path=(
            args.weather_replay_fixture
            if args.weather_mode == "deterministic_weather_replay"
            else None
        ),
        requested_at=args.weather_requested_at,
        weather_area=args.weather_area,
    )
    scenarios = [
        scenario.model_copy(
            update={
                "condition_overlay_refs": [
                    *scenario.condition_overlay_refs,
                    f"weather_receipt:{weather.receipt_id}",
                ]
            }
        )
        for scenario in scenarios
    ]
    cases, corpus_sha256 = generate_case_mapping(args.corpus, scenarios)
    per095_base = next(scenario for scenario in scenarios if scenario.boss_rank == 5)
    return {
        "artifact_kind": "scout_ai_six_forces_boss_approach_scenarios",
        "artifact_version": "scout_ai_six_forces_boss_approach_scenarios.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": scenarios[0].project_id,
        "corpus_ref": args.corpus.as_posix(),
        "corpus_sha256": corpus_sha256,
        "source_mode": args.source_mode,
        "weather_mode": args.weather_mode,
        "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
        "weather_evidence": weather.model_dump(mode="json"),
        "cases": [case.model_dump(mode="json") for case in cases],
        "supplemental_per095_replays": build_per095_replay_contexts(per095_base),
        "statistics": artifact_statistics(cases),
        "boundary": {
            "read_only_evaluation_context": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
            "outbound_send_allowed": False,
            "hardware_control_allowed": False,
            "reference_answers_embedded": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the Scout AI six-forces 600-case Boss Approach contexts."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to <workspace>/outputs/evals/scout_ai_six_forces_600_scenarios.json",
    )
    parser.add_argument(
        "--source-mode",
        choices=("hardware_live", "synthetic_replay"),
        default="synthetic_replay",
    )
    parser.add_argument(
        "--weather-mode",
        choices=("live_weather_integration", "deterministic_weather_replay"),
        default="deterministic_weather_replay",
    )
    parser.add_argument(
        "--weather-replay-fixture",
        type=Path,
        default=DEFAULT_REPLAY_FIXTURE,
    )
    parser.add_argument("--weather-area", default=None)
    parser.add_argument("--weather-requested-at", default=None)
    parser.add_argument("--observed-at", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.workspace = args.workspace.expanduser().resolve()
    args.corpus = args.corpus.expanduser().resolve()
    output = args.output or (
        args.workspace / "outputs/evals/scout_ai_six_forces_600_scenarios.json"
    )
    artifact = build_artifact(args)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "output": str(output),
                "scenario_count": len(artifact["scenarios"]),
                "case_count": artifact["statistics"]["case_count"],
                "weather_mode": artifact["weather_mode"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
