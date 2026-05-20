from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionStatus(StrEnum):
    RESOLVED = "resolved"
    OPEN = "open"


class DecisionImpact(StrEnum):
    FIXTURE_CALIBRATION = "fixture_calibration"
    SOURCE_TREATMENT = "source_treatment"
    TERRAIN_METADATA = "terrain_metadata"
    RETREAT_POLICY = "retreat_policy"
    TIMING_SCHEMA = "timing_schema"
    UI_BOUNDARY = "ui_boundary"
    READINESS_POLICY = "readiness_policy"
    WEATHER_DAYLIGHT = "weather_daylight"
    CONTOUR_STRATEGY = "contour_strategy"
    LEGAL_FIXTURE_USE = "legal_fixture_use"
    REVIEW_DECISION_LOG = "review_decision_log"
    EXTERNAL_IMPORT_QUEUE = "external_import_queue"
    SCOPE_BOUNDARY = "scope_boundary"


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    status: DecisionStatus
    impact: DecisionImpact
    title: str
    summary: str
    resolution: str | None = None
    open_question: str | None = None
    refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_status_specific_fields(self) -> "DecisionRecord":
        if self.status == DecisionStatus.RESOLVED:
            if not self.resolution:
                raise ValueError("resolved decisions require a resolution")
            if self.open_question is not None:
                raise ValueError("resolved decisions must not carry open_question")
        if self.status == DecisionStatus.OPEN:
            if not self.open_question:
                raise ValueError("open decisions require an open_question")
            if self.resolution is not None:
                raise ValueError("open decisions must not carry resolution")
        return self


REQUIRED_RESOLVED_DECISION_IDS: frozenset[str] = frozenset(
    {
        "phase4.decision.primary_fixture.chilai_nanhua_day1",
        "phase4.decision.regression_fixture.scout_260512",
        "phase4.decision.dtm.metadata_only",
        "phase4.decision.retreat.return_to_entry",
        "phase4.decision.sources.joyhike_ptt_reference_only",
        "phase4.decision.timing.optional_fields",
        "phase4.decision.ui.fixture_backed_read_only",
        "phase4.decision.poi.corridor_coverage_policy",
        "phase4.decision.weather_daylight.quantitative_thresholds",
        "phase4.decision.contour.ai_assisted_admin_review",
        "phase4.decision.route_comparison.derived_summary_only",
        "phase4.decision.review_log.fixture_only_append_only",
        "phase4.decision.external_import_queue.url_request_only",
        "phase4.decision.backlog.current_policy_set_closed",
    }
)

REQUIRED_OPEN_QUESTION_IDS: frozenset[str] = frozenset()


class PreTripDecisionRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    register_id: str
    artifact_kind: Literal["pretrip_decision_register"] = "pretrip_decision_register"
    phase: Literal["phase_4_pretrip"] = "phase_4_pretrip"
    schema_version: str = "0.1.0"
    metadata_only: Literal[True] = True
    no_network: Literal[True] = True
    no_crawler: Literal[True] = True
    ui_scope: Literal["fixture_backed_read_only_admin_preview"] = (
        "fixture_backed_read_only_admin_preview"
    )
    no_runtime_effects: Literal[True] = True
    resolved_decisions: list[DecisionRecord]
    open_questions: list[DecisionRecord]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_expected_register_shape(self) -> "PreTripDecisionRegister":
        resolved_ids = {decision.decision_id for decision in self.resolved_decisions}
        open_ids = {question.decision_id for question in self.open_questions}
        all_ids = resolved_ids | open_ids

        if len(all_ids) != len(self.resolved_decisions) + len(self.open_questions):
            raise ValueError("decision ids must be unique across the register")
        if any(decision.status != DecisionStatus.RESOLVED for decision in self.resolved_decisions):
            raise ValueError("resolved_decisions must only contain resolved records")
        if any(question.status != DecisionStatus.OPEN for question in self.open_questions):
            raise ValueError("open_questions must only contain open records")

        missing_resolved = REQUIRED_RESOLVED_DECISION_IDS - resolved_ids
        if missing_resolved:
            raise ValueError(f"missing resolved decisions: {sorted(missing_resolved)}")
        missing_open = REQUIRED_OPEN_QUESTION_IDS - open_ids
        if missing_open:
            raise ValueError(f"missing open questions: {sorted(missing_open)}")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def load_pretrip_decision_register(path: Path | str) -> PreTripDecisionRegister:
    return PreTripDecisionRegister.model_validate_json(Path(path).read_text())
