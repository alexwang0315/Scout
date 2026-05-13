from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ActivationDecision = Literal["allow", "disallow", "defer", "degrade"]


SAFETY_LEVEL_ORDER = {
    "L0": 0,
    "L1": 1,
    "L2": 2,
    "L3": 3,
    "L4": 4,
}


@dataclass(frozen=True)
class LnConstraintContext:
    skill_id: str
    safety_level: str
    route_type: str
    duration_class: str
    activity: str
    weather: str
    team_state: str
    evidence_refs: tuple[str, ...] = ()
    now_minutes: int | None = None
    last_prompt_at_minutes: int | None = None
    acknowledged_prompt_at_minutes: int | None = None
    previous_evidence_refs: tuple[str, ...] = ()
    acknowledged_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class LnConstraintDecision:
    decision: ActivationDecision
    policy_id: str
    policy_version: str
    skill_id: str
    evidence_refs: tuple[str, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)


class LnConstraintPolicyError(ValueError):
    pass


class LnConstraintEvaluator:
    def __init__(self, policy: dict[str, Any]):
        self.policy = policy
        self.policy_id = str(policy.get("policy_id", "unknown"))
        self.policy_version = str(policy.get("version", "unknown"))
        if "skills" not in policy or not isinstance(policy["skills"], dict):
            raise LnConstraintPolicyError("policy requires a skills object")

    @classmethod
    def from_file(cls, path: Path | str) -> "LnConstraintEvaluator":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def evaluate(
        self,
        skill_id: str,
        safety_level: str,
        route_type: str,
        duration_class: str,
        activity: str,
        weather: str,
        team_state: str,
        evidence_refs: list[str] | tuple[str, ...],
        *,
        now_minutes: int | None = None,
        last_prompt_at_minutes: int | None = None,
        acknowledged_prompt_at_minutes: int | None = None,
        previous_evidence_refs: list[str] | tuple[str, ...] = (),
        acknowledged_evidence_refs: list[str] | tuple[str, ...] = (),
    ) -> LnConstraintDecision:
        context = LnConstraintContext(
            skill_id=skill_id,
            safety_level=safety_level,
            route_type=route_type,
            duration_class=duration_class,
            activity=activity,
            weather=weather,
            team_state=team_state,
            evidence_refs=tuple(evidence_refs),
            now_minutes=now_minutes,
            last_prompt_at_minutes=last_prompt_at_minutes,
            acknowledged_prompt_at_minutes=acknowledged_prompt_at_minutes,
            previous_evidence_refs=tuple(previous_evidence_refs),
            acknowledged_evidence_refs=tuple(acknowledged_evidence_refs),
        )
        return self.evaluate_context(context)

    def evaluate_context(self, context: LnConstraintContext) -> LnConstraintDecision:
        skill_policy = self.policy["skills"].get(context.skill_id)
        if skill_policy is None:
            return self._decision(
                "disallow",
                context,
                f"skill {context.skill_id} is not listed in policy",
            )
        if skill_policy.get("disabled", False):
            return self._decision("disallow", context, "skill is disabled by policy")

        context_match = self._match_context_policy(context)
        if context_match is not None and context_match.get("decision") == "disallow":
            return self._decision("disallow", context, context_match.get("reason", "context is disallowed"))

        noise_decision = self._evaluate_noise_control(skill_policy, context)
        if noise_decision is not None:
            return noise_decision

        for rule in skill_policy.get("defer_when", []):
            if self._rule_matches(rule, context):
                return self._decision("defer", context, rule.get("reason", "context requires deferral"))

        required_level = self._required_safety_level(skill_policy, context, context_match)
        if not self._safety_at_least(context.safety_level, required_level):
            return self._decision(
                "disallow",
                context,
                f"safety level {context.safety_level} is below required {required_level}",
            )

        for rule in skill_policy.get("degrade_when", []):
            if self._rule_matches(rule, context):
                return self._decision("degrade", context, rule.get("reason", "degraded mode required"))

        return self._decision(
            "allow",
            context,
            f"safety level {context.safety_level} satisfies required {required_level}",
        )

    def _evaluate_noise_control(
        self, skill_policy: dict[str, Any], context: LnConstraintContext
    ) -> LnConstraintDecision | None:
        noise_control = skill_policy.get("noise_control", {})
        if not noise_control:
            return None

        current_evidence = set(context.evidence_refs)
        prior_evidence = set(context.previous_evidence_refs)
        acknowledged_evidence = set(context.acknowledged_evidence_refs)
        has_new_evidence = bool(current_evidence - prior_evidence - acknowledged_evidence)

        if noise_control.get("require_new_evidence", False) and not has_new_evidence:
            return self._decision("defer", context, "suppressed until new evidence is available")

        if (
            noise_control.get("suppress_if_recently_acknowledged", False)
            and context.now_minutes is not None
            and context.acknowledged_prompt_at_minutes is not None
        ):
            acknowledgement_window = int(noise_control.get("acknowledgement_window_minutes", 0))
            age = context.now_minutes - context.acknowledged_prompt_at_minutes
            if 0 <= age < acknowledgement_window:
                return self._decision("defer", context, "suppressed because prompt was recently acknowledged")

        if context.now_minutes is not None and context.last_prompt_at_minutes is not None:
            cooldown_minutes = int(noise_control.get("cooldown_minutes", 0))
            age = context.now_minutes - context.last_prompt_at_minutes
            if 0 <= age < cooldown_minutes and not has_new_evidence:
                return self._decision("defer", context, "suppressed by cooldown without new evidence")

        return None

    def _match_context_policy(
        self, context: LnConstraintContext
    ) -> dict[str, Any] | None:
        for context_policy in self.policy.get("contexts", []):
            if self._context_policy_matches(context_policy, context):
                return context_policy
        return None

    def _context_policy_matches(self, context_policy: dict[str, Any], context: LnConstraintContext) -> bool:
        route_types = context_policy.get("route_types")
        if route_types is not None and context.route_type not in route_types:
            return False
        duration_classes = context_policy.get("duration_classes")
        if duration_classes is not None and context.duration_class not in duration_classes:
            return False
        activities = context_policy.get("activities")
        if activities is not None and context.activity not in activities:
            return False
        weather_states = context_policy.get("weather")
        if weather_states is not None and context.weather not in weather_states:
            return False
        team_states = context_policy.get("team_states")
        if team_states is not None and context.team_state not in team_states:
            return False
        return True

    def _required_safety_level(
        self,
        skill_policy: dict[str, Any],
        context: LnConstraintContext,
        context_match: dict[str, Any] | None,
    ) -> str:
        if context_match is not None:
            skill_overrides = context_match.get("skill_overrides", {})
            override = skill_overrides.get(context.skill_id, {})
            if "min_safety_level" in override:
                return str(override["min_safety_level"])
        return str(skill_policy.get("min_safety_level", "L0"))

    def _rule_matches(self, rule: dict[str, Any], context: LnConstraintContext) -> bool:
        for field_name in ("route_type", "duration_class", "activity", "weather", "team_state", "safety_level"):
            allowed_values = rule.get(field_name)
            if allowed_values is None:
                continue
            if isinstance(allowed_values, str):
                allowed_values = [allowed_values]
            if getattr(context, field_name) not in allowed_values:
                return False
        required_evidence = rule.get("requires_any_evidence")
        if required_evidence is not None and not set(required_evidence).intersection(context.evidence_refs):
            return False
        return True

    def _safety_at_least(self, current: str, required: str) -> bool:
        if current not in SAFETY_LEVEL_ORDER:
            raise LnConstraintPolicyError(f"unknown safety level: {current}")
        if required not in SAFETY_LEVEL_ORDER:
            raise LnConstraintPolicyError(f"unknown required safety level: {required}")
        return SAFETY_LEVEL_ORDER[current] >= SAFETY_LEVEL_ORDER[required]

    def _decision(
        self,
        decision: ActivationDecision,
        context: LnConstraintContext,
        *reasons: str,
    ) -> LnConstraintDecision:
        return LnConstraintDecision(
            decision=decision,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            skill_id=context.skill_id,
            evidence_refs=context.evidence_refs,
            reasons=tuple(reason for reason in reasons if reason),
        )
