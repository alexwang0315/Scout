from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from ln_constraints import LnConstraintContext, LnConstraintDecision, LnConstraintEvaluator
from phase2_brain_models import ConfidenceLevel, DecisionOption, DecisionOptionSet


RESOURCE_COST_RANK = {"low": 3, "medium": 2, "high": 1, "unknown": 0}
RISK_RANK = {"low": 3, "medium": 2, "high": 1, "unknown": 0}
CHANCE_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
REVERSIBILITY_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
CONFIDENCE_RANK = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
    ConfidenceLevel.UNKNOWN: 0,
}


@dataclass(frozen=True)
class DecisionOptionCandidate:
    id: str
    label: str
    action: str
    estimated_time_minutes: int | None
    resource_cost: str
    daylight_risk: str
    communication_chance: str
    team_impact: str
    reversibility: str
    failure_modes: tuple[str, ...]
    confidence: ConfidenceLevel


class OptionGenerationBlockedError(RuntimeError):
    def __init__(self, gate_decision: LnConstraintDecision):
        self.gate_decision = gate_decision
        reason = "; ".join(gate_decision.reasons) or gate_decision.decision
        super().__init__(
            f"decision option generation blocked by {gate_decision.decision} gate: {reason}"
        )


def option_candidate(
    *,
    id: str,
    label: str,
    action: str,
    estimated_time_minutes: int | None = None,
    resource_cost: str = "unknown",
    daylight_risk: str = "unknown",
    communication_chance: str = "unknown",
    team_impact: str = "",
    reversibility: str = "unknown",
    failure_modes: Iterable[str] = (),
    confidence: ConfidenceLevel | str = ConfidenceLevel.UNKNOWN,
) -> DecisionOptionCandidate:
    return DecisionOptionCandidate(
        id=id,
        label=label,
        action=action,
        estimated_time_minutes=estimated_time_minutes,
        resource_cost=resource_cost,
        daylight_risk=daylight_risk,
        communication_chance=communication_chance,
        team_impact=team_impact,
        reversibility=reversibility,
        failure_modes=tuple(failure_modes),
        confidence=ConfidenceLevel(confidence),
    )


def build_decision_option(candidate: DecisionOptionCandidate | DecisionOption) -> DecisionOption:
    if isinstance(candidate, DecisionOption):
        return candidate
    return DecisionOption(
        id=candidate.id,
        label=candidate.label,
        action=candidate.action,
        estimated_time_minutes=candidate.estimated_time_minutes,
        resource_cost=candidate.resource_cost,
        daylight_risk=candidate.daylight_risk,
        communication_chance=candidate.communication_chance,
        team_impact=candidate.team_impact,
        reversibility=candidate.reversibility,
        failure_modes=list(candidate.failure_modes),
        confidence=candidate.confidence,
    )


def build_decision_option_set(
    *,
    id: str,
    generated_at: str,
    current_safety_level: str,
    pilot_in_command: str,
    options: Iterable[DecisionOptionCandidate | DecisionOption],
    mission_id: str | None = None,
    artifact_refs: Iterable[str] = (),
    input_refs: Iterable[str] = (),
    scout_preference: Mapping[str, object] | None = None,
) -> DecisionOptionSet:
    built_options = [build_decision_option(option) for option in options]
    preference = dict(scout_preference or _scout_preference_for(built_options))
    return DecisionOptionSet(
        id=id,
        mission_id=mission_id,
        generated_at=generated_at,
        current_safety_level=current_safety_level,
        pilot_in_command=pilot_in_command,
        artifact_refs=list(artifact_refs),
        options=built_options,
        scout_preference=preference,
        input_refs=list(input_refs),
    )


def generate_option_set_with_ln_gate(
    *,
    evaluator: LnConstraintEvaluator,
    context: LnConstraintContext,
    id: str,
    generated_at: str,
    current_safety_level: str,
    pilot_in_command: str,
    options: Iterable[DecisionOptionCandidate | DecisionOption],
    degraded_options: Iterable[DecisionOptionCandidate | DecisionOption] | None = None,
    mission_id: str | None = None,
    artifact_refs: Iterable[str] = (),
    input_refs: Iterable[str] = (),
    scout_preference: Mapping[str, object] | None = None,
    intrusive: bool = True,
) -> DecisionOptionSet:
    gate_decision = evaluator.evaluate_context(context)
    if intrusive and gate_decision.decision in {"disallow", "defer"}:
        raise OptionGenerationBlockedError(gate_decision)

    generation_mode = "normal"
    selected_options = options
    if gate_decision.decision == "degrade":
        generation_mode = "degraded"
        selected_options = degraded_options if degraded_options is not None else options

    option_set = build_decision_option_set(
        id=id,
        mission_id=mission_id,
        generated_at=generated_at,
        current_safety_level=current_safety_level,
        pilot_in_command=pilot_in_command,
        artifact_refs=artifact_refs,
        input_refs=input_refs,
        options=selected_options,
        scout_preference=scout_preference,
    )
    option_set.scout_preference.update(
        {
            "generation_mode": generation_mode,
            "ln_gate": {
                "decision": gate_decision.decision,
                "policy_id": gate_decision.policy_id,
                "policy_version": gate_decision.policy_version,
                "skill_id": gate_decision.skill_id,
                "reasons": list(gate_decision.reasons),
            },
        }
    )
    return option_set


def _scout_preference_for(options: list[DecisionOption]) -> dict[str, object]:
    if not options:
        return {"preferred_option_id": None, "ranking": [], "rationale": "no options supplied"}

    ranked = sorted(options, key=_option_score, reverse=True)
    preferred = ranked[0]
    return {
        "preferred_option_id": preferred.id,
        "ranking": [option.id for option in ranked],
        "rationale": (
            "prefers higher confidence, lower resource and daylight risk, better "
            "communication chance, higher reversibility, fewer failure modes, and shorter time"
        ),
    }


def _option_score(option: DecisionOption) -> tuple[int, int, int, int, int, int, int, str]:
    time_score = -1 if option.estimated_time_minutes is None else -option.estimated_time_minutes
    return (
        CONFIDENCE_RANK[option.confidence],
        RESOURCE_COST_RANK[option.resource_cost],
        RISK_RANK[option.daylight_risk],
        CHANCE_RANK[option.communication_chance],
        REVERSIBILITY_RANK[option.reversibility],
        -len(option.failure_modes),
        time_score,
        option.id,
    )
