from __future__ import annotations

from enum import StrEnum
from pathlib import Path
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerdictLevel(StrEnum):
    NO_EFFECT = "no_effect"
    EVIDENCE_IMPROVEMENT = "evidence_improvement"
    EARLIER_AWARENESS = "earlier_awareness"
    DECISION_WINDOW_CREATED = "decision_window_created"
    LIKELY_OUTCOME_IMPROVEMENT = "likely_outcome_improvement"


VERDICT_LEVELS: tuple[VerdictLevel, ...] = (
    VerdictLevel.NO_EFFECT,
    VerdictLevel.EVIDENCE_IMPROVEMENT,
    VerdictLevel.EARLIER_AWARENESS,
    VerdictLevel.DECISION_WINDOW_CREATED,
    VerdictLevel.LIKELY_OUTCOME_IMPROVEMENT,
)


class TimelineCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=r"^T-(180|120|60|30|0)$")
    minutes_to_incident: int = Field(le=0)
    safety_level: Literal["L0", "L1", "L2", "L3", "L4"]
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    remote_status_ref: str | None = None
    option_set_ref: str | None = None

    @model_validator(mode="after")
    def label_matches_offset(self) -> TimelineCheckpoint:
        expected = f"T-{abs(self.minutes_to_incident)}"
        if self.label != expected:
            raise ValueError(f"checkpoint label {self.label} does not match {self.minutes_to_incident}")
        return self


class PostIncidentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    captured_after_minutes: int = Field(ge=0)
    evidence_type: Literal[
        "track_log",
        "witness_report",
        "weather_report",
        "photo",
        "incident_package",
        "after_action_note",
        "other",
    ]
    summary: str
    artifact_refs: list[str] = Field(default_factory=list)


class ReplayAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_improved: bool = False
    earlier_awareness_minutes: int = Field(default=0, ge=0)
    decision_window_minutes: int = Field(default=0, ge=0)
    likely_outcome_improvement: bool = False
    guaranteed_outcome: bool = False
    rationale: str = ""

    @model_validator(mode="after")
    def reject_guaranteed_outcomes(self) -> ReplayAssessment:
        if self.guaranteed_outcome:
            raise ValueError("case replay verdicts cannot claim guaranteed outcomes")
        return self


class CaseReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    title: str
    incident_type: str
    location: str
    route_context: str
    incident_at: str | None = None
    timeline: list[TimelineCheckpoint] = Field(min_length=1)
    post_incident_evidence: list[PostIncidentEvidence] = Field(default_factory=list)
    baseline_summary: str
    replay_summary: str
    known_outcome_summary: str
    assessment: ReplayAssessment

    @model_validator(mode="after")
    def validate_timeline(self) -> CaseReplay:
        labels = [checkpoint.label for checkpoint in self.timeline]
        if len(labels) != len(set(labels)):
            raise ValueError("timeline checkpoint labels must be unique")

        offsets = [checkpoint.minutes_to_incident for checkpoint in self.timeline]
        if offsets != sorted(offsets):
            raise ValueError("timeline must be ordered from earliest checkpoint to T-0")

        if "T-0" not in labels:
            raise ValueError("timeline must include T-0")

        return self


class CaseReplayVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    level: VerdictLevel
    score: int = Field(ge=0, le=4)
    rationale: str


def load_case_replay(path: str | Path) -> CaseReplay:
    with Path(path).open(encoding="utf-8") as fixture_file:
        return CaseReplay.model_validate(json.load(fixture_file))


def score_case_replay(case: CaseReplay) -> CaseReplayVerdict:
    assessment = case.assessment
    if assessment.likely_outcome_improvement:
        level = VerdictLevel.LIKELY_OUTCOME_IMPROVEMENT
    elif assessment.decision_window_minutes > 0:
        level = VerdictLevel.DECISION_WINDOW_CREATED
    elif assessment.earlier_awareness_minutes > 0:
        level = VerdictLevel.EARLIER_AWARENESS
    elif assessment.evidence_improved:
        level = VerdictLevel.EVIDENCE_IMPROVEMENT
    else:
        level = VerdictLevel.NO_EFFECT

    return CaseReplayVerdict(
        case_id=case.case_id,
        level=level,
        score=VERDICT_LEVELS.index(level),
        rationale=_bounded_rationale(case, level),
    )


def _bounded_rationale(case: CaseReplay, level: VerdictLevel) -> str:
    rationale = case.assessment.rationale.strip()
    if not rationale:
        rationale = f"Replay produced {level.value} for {case.case_id}."

    return _strip_guarantee_language(rationale)


def _strip_guarantee_language(value: str) -> str:
    guarantee_pattern = re.compile(
        r"\b(guarantee[ds]?|certain(?:ly)?|would have rescued|ensures rescue)\b",
        flags=re.IGNORECASE,
    )
    return guarantee_pattern.sub("may", value)
