from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from safety_models import SafetyLevel


LEVEL_RANK = {
    SafetyLevel.NORMAL: 0,
    SafetyLevel.WATCH: 1,
    SafetyLevel.CONCERN: 2,
    SafetyLevel.DISTRESS: 3,
    SafetyLevel.EMERGENCY: 4,
}


class RiskRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    name: str
    hazard_types: list[str] = Field(default_factory=list)
    hazard_match: Literal["any", "all"] = "any"
    min_duration_s: float = Field(default=0.0, ge=0.0)
    min_map_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_weak_gps: bool | None = None
    segment_ids: list[str] = Field(default_factory=list)
    output_level: SafetyLevel = SafetyLevel.CONCERN
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    reason: str


class RiskRuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruleset_id: str
    mission_id: str
    source: str = "fixture"
    source_version: str = "unknown"
    rules: list[RiskRule] = Field(default_factory=list)


class RiskRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hazard_types: list[str] = Field(default_factory=list)
    duration_s: float = Field(ge=0.0)
    map_confidence: float = Field(ge=0.0, le=1.0)
    weak_gps: bool = False
    segment_id: str | None = None
    route_id: str | None = None
    context: dict = Field(default_factory=dict)


class RiskRuleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    level: SafetyLevel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    details: dict = Field(default_factory=dict)


def load_risk_rules(path: Path | str) -> RiskRuleSet:
    payload = json.loads(Path(path).read_text())
    return RiskRuleSet.model_validate(payload)


class RiskRuleEvaluator:
    def __init__(self, ruleset: RiskRuleSet):
        self.ruleset = ruleset

    def evaluate(self, risk_input: RiskRuleInput) -> RiskRuleDecision | None:
        matches = [rule for rule in self.ruleset.rules if _rule_matches(rule, risk_input)]
        if not matches:
            return None

        rule = max(matches, key=lambda item: (LEVEL_RANK[item.output_level], item.confidence))
        return RiskRuleDecision(
            rule_id=rule.rule_id,
            level=rule.output_level,
            confidence=rule.confidence,
            reason=rule.reason,
            details={
                "ruleset_id": self.ruleset.ruleset_id,
                "mission_id": self.ruleset.mission_id,
                "source": self.ruleset.source,
                "source_version": self.ruleset.source_version,
                "hazard_types": risk_input.hazard_types,
                "duration_s": risk_input.duration_s,
                "map_confidence": risk_input.map_confidence,
                "weak_gps": risk_input.weak_gps,
                "segment_id": risk_input.segment_id,
                "route_id": risk_input.route_id,
                "context": risk_input.context,
            },
        )


def _rule_matches(rule: RiskRule, risk_input: RiskRuleInput) -> bool:
    if risk_input.duration_s < rule.min_duration_s:
        return False
    if risk_input.map_confidence < rule.min_map_confidence:
        return False
    if rule.requires_weak_gps is not None and risk_input.weak_gps != rule.requires_weak_gps:
        return False
    if rule.segment_ids and risk_input.segment_id not in rule.segment_ids:
        return False
    if not rule.hazard_types:
        return True

    observed = set(risk_input.hazard_types)
    required = set(rule.hazard_types)
    if rule.hazard_match == "all":
        return required.issubset(observed)
    return bool(required & observed)
