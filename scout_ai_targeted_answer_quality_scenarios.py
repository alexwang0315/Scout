from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field

from scout_ai_six_forces_scenarios import (
    DECISIONS,
    FORCE_NAMES,
    ExpectedDecisionBoundary,
    ExpectedEvidenceContract,
    ScenarioContext,
    SixForcesCase,
    StrictModel,
    _answer_mode,
    _case_requirements,
)


TARGETED_QUESTION_RE = re.compile(
    r"^(\d+)\. \*\*REG-(EXP|RPF|PER|RTE|WTH|NAV)-(\d{3})\*\* (.+)$"
)
FAMILY_HEADING_RE = re.compile(r"^## (AQ\d)\b")

EXPECTED_FORCE_COUNTS = {
    "EXP": 30,
    "RPF": 5,
    "PER": 15,
    "RTE": 5,
    "WTH": 40,
    "NAV": 5,
}
EXPECTED_FAMILY_COUNTS = {
    "AQ1": 20,
    "AQ2": 15,
    "AQ3": 10,
    "AQ4": 10,
    "AQ5": 15,
    "AQ6": 15,
    "AQ7": 10,
    "AQ8": 5,
}

FAMILY_CONTRACTS: dict[str, dict[str, Any]] = {
    "AQ1": {
        "failure_family": "evidence_gap_first",
        "source_failure_ids": ["EXP-011", "EXP-052", "EXP-097"],
        "expected_behaviors": [
            "state the exact evidence gap in the first clause",
            "request the minimum next evidence needed",
        ],
        "forbidden_behaviors": [
            "add an unsupported factual answer after acknowledging the gap",
            "convert missing evidence into a safe or normal state",
        ],
    },
    "AQ2": {
        "failure_family": "source_grounding",
        "source_failure_ids": ["EXP-035"],
        "expected_behaviors": [
            "name attributable workspace sources",
            "separate sourced facts from candidate interpretation",
        ],
        "forbidden_behaviors": [
            "invent cultural or historical context",
            "drop all expected evidence tokens and source references",
        ],
    },
    "AQ3": {
        "failure_family": "observation_vs_inference",
        "source_failure_ids": ["EXP-052"],
        "expected_behaviors": [
            "separate observed signals from inferred causes",
            "state confidence and the evidence needed to verify the cause",
        ],
        "forbidden_behaviors": [
            "present a causal hypothesis as an observed fact",
        ],
    },
    "AQ4": {
        "failure_family": "temporal_directional_join",
        "source_failure_ids": ["EXP-097"],
        "expected_behaviors": [
            "join timestamps, route progress, and travel direction",
            "decline the comparison when the join dimensions are unavailable",
        ],
        "forbidden_behaviors": [
            "compare outbound and return states by coordinate alone",
        ],
    },
    "AQ5": {
        "failure_family": "qpf_pop_unit_discipline",
        "source_failure_ids": ["WTH-019"],
        "expected_behaviors": [
            "distinguish PoP percent, QPF millimetres, and observed rain",
            "preserve accumulation windows, units, and null semantics",
        ],
        "forbidden_behaviors": [
            "report PoP as millimetres",
            "report a null QPF value as zero rain",
        ],
    },
    "AQ6": {
        "failure_family": "severe_weather_use",
        "source_failure_ids": [
            "WTH-019",
            "WTH-027",
            "WTH-053",
            "WTH-084",
            "WTH-095",
        ],
        "expected_behaviors": [
            "preserve severe-weather signals in the answer",
            "connect route and time intersection to a bounded action",
        ],
        "forbidden_behaviors": [
            "treat no official warning as no route risk",
            "ignore route-intersecting severe signals",
        ],
    },
    "AQ7": {
        "failure_family": "freshness_and_intersection",
        "source_failure_ids": ["WTH-084", "WTH-095"],
        "expected_behaviors": [
            "check issued_at, valid time, TTL, location, and route intersection",
            "describe stale or non-intersecting evidence as unknown",
        ],
        "forbidden_behaviors": [
            "treat stale evidence as current",
            "apply distant evidence directly to the route",
        ],
    },
    "AQ8": {
        "failure_family": "compound_contradiction",
        "source_failure_ids": ["WTH-027", "WTH-053", "WTH-095"],
        "expected_behaviors": [
            "state decisive and opposing evidence",
            "give a bounded decision and an explicit change condition",
        ],
        "forbidden_behaviors": [
            "silently discard the less convenient evidence source",
            "promote candidate evidence to runtime safety truth",
        ],
    },
}

ROOT = Path(__file__).resolve().parent


class TargetedQuestion(StrictModel):
    global_ordinal: int = Field(ge=1, le=100)
    question_id: str
    force_code: str
    force_ordinal: int = Field(ge=1, le=100)
    failure_family_code: str
    question_text: str


class TargetedCaseContract(StrictModel):
    question_id: str
    failure_family_code: str
    failure_family: str
    source_failure_ids: list[str]
    expected_behaviors: list[str]
    forbidden_behaviors: list[str]


def load_targeted_questions(
    corpus_path: Path | str,
) -> tuple[list[TargetedQuestion], str]:
    path = Path(corpus_path).expanduser().resolve()
    raw = path.read_bytes()
    family_code = ""
    rows: list[TargetedQuestion] = []
    for line in raw.decode("utf-8").splitlines():
        heading_match = FAMILY_HEADING_RE.match(line)
        if heading_match:
            family_code = heading_match.group(1)
            continue
        match = TARGETED_QUESTION_RE.match(line)
        if not match:
            continue
        if family_code not in FAMILY_CONTRACTS:
            raise ValueError("targeted question appears outside an AQ family section")
        global_ordinal, force_code, force_ordinal, question = match.groups()
        rows.append(
            TargetedQuestion(
                global_ordinal=int(global_ordinal),
                question_id=f"REG-{force_code}-{force_ordinal}",
                force_code=force_code,
                force_ordinal=int(force_ordinal),
                failure_family_code=family_code,
                question_text=question,
            )
        )
    _validate_targeted_questions(rows)
    return rows, hashlib.sha256(raw).hexdigest()


def generate_targeted_case_mapping(
    corpus_path: Path | str,
    scenarios: list[ScenarioContext],
) -> tuple[list[SixForcesCase], list[TargetedCaseContract], str]:
    questions, corpus_hash = load_targeted_questions(corpus_path)
    by_rank = {scenario.boss_rank: scenario for scenario in scenarios}
    if set(by_rank) != {1, 2, 3, 4, 5}:
        raise ValueError("targeted corpus requires exactly five Boss Approach ranks")

    source_ref = portable_corpus_ref(corpus_path)
    cases: list[SixForcesCase] = []
    contracts: list[TargetedCaseContract] = []
    for row in questions:
        scenario = by_rank[((row.force_ordinal - 1) % 5) + 1]
        required_context, required_evidence = _case_requirements(row.force_code)
        answer_mode = _answer_mode(row.question_text, row.force_code)
        force_name, capability_name = FORCE_NAMES[row.force_code]
        record_hash = hashlib.sha256(
            f"{row.question_id}\n{row.question_text}".encode("utf-8")
        ).hexdigest()
        cases.append(
            SixForcesCase(
                case_id=(
                    f"answer-quality-100.{row.question_id}.{scenario.scenario_id}"
                ),
                question_id=row.question_id,
                global_ordinal=row.global_ordinal,
                force_code=row.force_code,
                force_name=force_name,
                capability_name=capability_name,
                force_ordinal=row.force_ordinal,
                subsection=row.failure_family_code,
                question_text=row.question_text,
                question_source_ref=f"{source_ref}#sha256={corpus_hash}",
                question_record_sha256=record_hash,
                scenario_id=scenario.scenario_id,
                expected_evidence_contract=ExpectedEvidenceContract(
                    required_context=required_context,
                    required_evidence=required_evidence,
                    freshness_required=row.force_code in {"RPF", "PER", "WTH", "NAV"},
                    route_intersection_required=row.force_code
                    in {"PER", "RTE", "WTH", "NAV"},
                ),
                expected_decision_boundary=ExpectedDecisionBoundary(
                    answer_mode=answer_mode,
                    allowed_decisions=(
                        list(DECISIONS) if answer_mode != "factual_context" else []
                    ),
                    forbidden_claims=[
                        "missing or stale evidence means zero risk",
                        "PoP percent is QPF millimetres",
                        "candidate evidence is runtime safety truth",
                        "unsupported cultural historical or causal fact",
                        "guaranteed safe",
                    ],
                ),
            )
        )
        contracts.append(
            TargetedCaseContract(
                question_id=row.question_id,
                failure_family_code=row.failure_family_code,
                **FAMILY_CONTRACTS[row.failure_family_code],
            )
        )
    return cases, contracts, corpus_hash


def portable_corpus_ref(corpus_path: Path | str) -> str:
    path = Path(corpus_path).expanduser().resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def targeted_artifact_statistics(
    questions: list[TargetedQuestion],
) -> dict[str, Any]:
    force_counts = Counter(item.force_code for item in questions)
    family_counts = Counter(item.failure_family_code for item in questions)
    expanded_run_count = sum(
        3 if item.force_code in {"PER", "WTH"} else 1 for item in questions
    )
    return {
        "base_question_count": len(questions),
        "expanded_model_run_count": expanded_run_count,
        "force_counts": dict(sorted(force_counts.items())),
        "failure_family_counts": dict(sorted(family_counts.items())),
    }


def _validate_targeted_questions(questions: list[TargetedQuestion]) -> None:
    if len(questions) != 100:
        raise ValueError("targeted answer-quality corpus must contain 100 questions")
    if len({item.question_id for item in questions}) != 100:
        raise ValueError("targeted answer-quality question IDs must be unique")
    if len({item.question_text for item in questions}) != 100:
        raise ValueError("targeted answer-quality question text must be unique")
    if [item.global_ordinal for item in questions] != list(range(1, 101)):
        raise ValueError("targeted answer-quality ordinals must be 1..100")

    force_counts = Counter(item.force_code for item in questions)
    if force_counts != Counter(EXPECTED_FORCE_COUNTS):
        raise ValueError(f"invalid targeted force distribution: {dict(force_counts)}")
    family_counts = Counter(item.failure_family_code for item in questions)
    if family_counts != Counter(EXPECTED_FAMILY_COUNTS):
        raise ValueError(
            f"invalid targeted failure-family distribution: {dict(family_counts)}"
        )
    for force_code, expected_count in EXPECTED_FORCE_COUNTS.items():
        force_ordinals = [
            item.force_ordinal for item in questions if item.force_code == force_code
        ]
        if force_ordinals != list(range(1, expected_count + 1)):
            raise ValueError(f"{force_code} ordinals must be contiguous from 1")
