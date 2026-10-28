"""Build the 10-local plus EXP-001..EXP-010 mixed routing smoke corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.nextgen.jev_model_routing import (  # noqa: E402
    AnswerContract,
    ModelRoute,
    RoutingCapability,
    RoutingCorpus,
    RoutingQuestion,
    validate_routing_corpus,
)


DEFAULT_LOCAL = ROOT / "docs/specs/scout-ai-local-cloud-routing-100-question-corpus.json"
DEFAULT_SCENARIOS = Path(
    "/home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport/outputs/evals/scout_ai_six_forces_600_scenarios_20260919.json"
)
DEFAULT_OUTPUT = ROOT / "docs/specs/scout-ai-local-cloud-mixed-20-question-eval.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_mixed(local_path: Path, scenario_path: Path) -> RoutingCorpus:
    local_document = _load(local_path)
    local_cases = [
        item for item in local_document["questions"] if item["expected_route"] == "local"
    ][:10]
    if len(local_cases) != 10:
        raise ValueError("local corpus must contain at least ten local cases")

    scenario_document = _load(scenario_path)
    # The six-forces artifact contains five physical scenario rows plus the
    # 600 question/case rows.  EXP-001..010 live in `cases`.
    scenarios = scenario_document.get("cases", [])
    exp_cases = {
        item["question_id"]: item
        for item in scenarios
        if item.get("question_id") in {f"EXP-{index:03d}" for index in range(1, 11)}
    }
    if len(exp_cases) != 10:
        raise ValueError("scenario artifact must contain EXP-001 through EXP-010")

    questions = [RoutingQuestion.model_validate(item) for item in local_cases]
    for index in range(1, 11):
        item = exp_cases[f"EXP-{index:03d}"]
        questions.append(
            RoutingQuestion(
                question_id=item["question_id"],
                question=item["question_text"],
                category="six_forces_exp_workspace_grounded",
                expected_route=ModelRoute.CLOUD,
                capabilities=(
                    RoutingCapability.TOOL_USE,
                    RoutingCapability.CROSS_ARTIFACT_JOIN,
                ),
                standard_answer="需使用 workspace route context 與 provenance 證據後回答；不能用固定答案代替查證。",
                answer_contract=AnswerContract(
                    kind="evidence_grounded",
                    required_fields=(
                        "answer",
                        "decisive_evidence",
                        "opposing_evidence",
                        "evidence_gaps",
                        "decision_change_conditions",
                        "source_refs",
                    ),
                    must_state_unknowns=True,
                ),
                source_refs=(
                    "workspace://route_context",
                    "workspace://source_provenance",
                ),
                required_tools=("scout_workspace_query",),
                cloud_reason="EXP six-forces 題要求 workspace route context、scenario identity 與 source provenance。",
            )
        )

    corpus = RoutingCorpus(
        schema_version="scout.ai.local_cloud_routing_corpus.v1",
        workspace_id="dongqing_batongguan_historic_trail_newImport",
        description="10 題 local 標準答案與 EXP-001～EXP-010 cloud workspace-grounded 題的 JEV routing smoke corpus。",
        routing_authority="deterministic_gate_with_jev_advisory",
        questions=tuple(questions),
        candidate_only=True,
        runtime_safety_truth=False,
    )
    errors = validate_routing_corpus(corpus)
    if errors:
        raise ValueError("; ".join(errors))
    return corpus


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-corpus", type=Path, default=DEFAULT_LOCAL)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    corpus = build_mixed(args.local_corpus, args.scenarios)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(corpus.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} ({len(corpus.questions)} questions: 10 local + 10 cloud)")


if __name__ == "__main__":
    main()
