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
    build_weather_evidence_receipt,
    generate_boss_approach_anchors,
)
from scout_ai_targeted_answer_quality_scenarios import (  # noqa: E402
    generate_targeted_case_mapping,
    load_targeted_questions,
    portable_corpus_ref,
    targeted_artifact_statistics,
)


DEFAULT_WORKSPACE = Path("/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI")
DEFAULT_CORPUS = (
    ROOT / "docs/specs/scout-ai-targeted-answer-quality-100-question-corpus.md"
)
DEFAULT_REPLAY_FIXTURE = (
    ROOT / "tests/fixtures/scout_ai_six_forces/deterministic_cwa_replay.json"
)


def build_artifact(args: argparse.Namespace) -> dict[str, object]:
    observed_at = args.observed_at or datetime.now(timezone.utc).isoformat()
    scenarios = generate_boss_approach_anchors(
        args.workspace,
        observed_at=observed_at,
        source_mode="synthetic_replay",
    )
    weather = build_weather_evidence_receipt(
        scenarios,
        mode="deterministic_weather_replay",
        replay_fixture_path=args.weather_replay_fixture,
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
    cases, contracts, corpus_sha256 = generate_targeted_case_mapping(
        args.corpus,
        scenarios,
    )
    questions, _ = load_targeted_questions(args.corpus)
    return {
        "artifact_kind": "scout_ai_targeted_answer_quality_100_scenarios",
        "artifact_version": "scout_ai_targeted_answer_quality_100_scenarios.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": scenarios[0].project_id,
        "corpus_ref": portable_corpus_ref(args.corpus),
        "corpus_sha256": corpus_sha256,
        "source_eval_ref": args.source_eval_ref,
        "source_mode": "synthetic_replay",
        "weather_mode": "deterministic_weather_replay",
        "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
        "weather_evidence": weather.model_dump(mode="json"),
        "cases": [case.model_dump(mode="json") for case in cases],
        "targeted_case_contracts": [
            contract.model_dump(mode="json") for contract in contracts
        ],
        "statistics": targeted_artifact_statistics(questions),
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
        description=(
            "Generate the Scout AI targeted 100-question answer-quality scenarios."
        )
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Defaults to <workspace>/outputs/evals/"
            "scout_ai_targeted_answer_quality_100_scenarios.json"
        ),
    )
    parser.add_argument(
        "--weather-replay-fixture",
        type=Path,
        default=DEFAULT_REPLAY_FIXTURE,
    )
    parser.add_argument("--weather-area", default=None)
    parser.add_argument("--weather-requested-at", default=None)
    parser.add_argument("--observed-at", default=None)
    parser.add_argument(
        "--source-eval-ref",
        default=(
            "outputs/evals/six_forces_600_total_info_v230-qwen3-full1000-20260816T0140Z"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.workspace = args.workspace.expanduser().resolve()
    args.corpus = args.corpus.expanduser().resolve()
    args.weather_replay_fixture = args.weather_replay_fixture.expanduser().resolve()
    output = args.output or (
        args.workspace
        / "outputs/evals/scout_ai_targeted_answer_quality_100_scenarios.json"
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
                **artifact["statistics"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
