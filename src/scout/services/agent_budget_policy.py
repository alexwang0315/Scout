"""Typed deterministic budget policy for bounded Scout agent runs."""

from __future__ import annotations

from collections.abc import Sequence

from scout.schemas.agent_runtime import (
    AgentRecoveryStage,
    AgentRunBudget,
    AgentStageBudget,
    QuestionClass,
)


_CLASS_LIMITS: dict[QuestionClass, tuple[int, int]] = {
    QuestionClass.STATIC_WORKSPACE_FACT: (10, 10),
    QuestionClass.AGGREGATE_WORKSPACE_FACT: (10, 10),
    QuestionClass.CROSS_ARTIFACT_JOIN: (10, 10),
    QuestionClass.SPATIAL_ROUTE_FACT: (10, 10),
    QuestionClass.WEATHER_TERRAIN_COMPOUND: (10, 10),
    QuestionClass.LIVE_RUNTIME_FACT: (10, 10),
    QuestionClass.SAFETY_DECISION: (10, 10),
    QuestionClass.UNKNOWN: (10, 10),
}

_CLASS_STAGE_LIMITS: dict[QuestionClass, tuple[int, int, int, int]] = {
    QuestionClass.STATIC_WORKSPACE_FACT: (10, 10, 10, 10),
    QuestionClass.AGGREGATE_WORKSPACE_FACT: (10, 10, 10, 10),
    QuestionClass.CROSS_ARTIFACT_JOIN: (10, 10, 10, 10),
    QuestionClass.SPATIAL_ROUTE_FACT: (10, 10, 10, 10),
    QuestionClass.WEATHER_TERRAIN_COMPOUND: (10, 10, 10, 10),
    QuestionClass.LIVE_RUNTIME_FACT: (10, 10, 10, 10),
    QuestionClass.SAFETY_DECISION: (10, 10, 10, 10),
    QuestionClass.UNKNOWN: (10, 10, 10, 10),
}


class AgentBudgetPolicy:
    """Map query complexity to policy; Pydantic AI only enforces the result."""

    @classmethod
    def for_query(
        cls,
        *,
        question_class: QuestionClass | str | None,
        expected_operations: Sequence[str] = (),
        selected_tool_ids: Sequence[str] = (),
        requires_join: bool = False,
        requires_live_state: bool = False,
        recovery_stage: AgentRecoveryStage = AgentRecoveryStage.INITIAL,
        attempt_index: int = 1,
        requested_tool_calls: int | None = None,
        requested_model_requests: int | None = None,
    ) -> AgentRunBudget:
        resolved_class = cls._resolve_question_class(question_class)
        if requires_join and resolved_class not in {
            QuestionClass.WEATHER_TERRAIN_COMPOUND,
            QuestionClass.SAFETY_DECISION,
        }:
            resolved_class = QuestionClass.CROSS_ARTIFACT_JOIN
        elif requires_live_state and resolved_class in {
            QuestionClass.STATIC_WORKSPACE_FACT,
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
        }:
            resolved_class = QuestionClass.LIVE_RUNTIME_FACT
        max_tool_calls, max_requests = _CLASS_LIMITS[resolved_class]
        operation_count = len(set(expected_operations))
        selected_count = len(set(selected_tool_ids))
        max_tool_calls = max(
            max_tool_calls,
            operation_count + selected_count,
            requested_tool_calls or 0,
        )
        max_requests = max(max_requests, requested_model_requests or 0)
        discover, query, join, verify = _CLASS_STAGE_LIMITS[resolved_class]
        return AgentRunBudget(
            question_class=resolved_class,
            recovery_stage=recovery_stage,
            attempt_index=attempt_index,
            max_requests=max_requests,
            max_tool_calls=max_tool_calls,
            max_repairs=10,
            stage_budget=AgentStageBudget(
                discover_tool_calls=discover,
                query_tool_calls=query,
                join_tool_calls=join,
                verify_tool_calls=verify,
                planner_model_requests=10,
                retriever_model_requests=10,
                synthesis_model_requests=10,
                verifier_model_requests=10,
                reviewer_model_requests=10,
                repair_model_requests=10,
                retry_model_requests=10,
                replan_model_requests=10,
                browser_model_requests=10,
                subagent_model_requests=10,
            ),
        )

    @classmethod
    def for_recovery(
        cls,
        *,
        prior_budget: AgentRunBudget,
        recovery_stage: AgentRecoveryStage,
    ) -> AgentRunBudget:
        """Issue a fresh 10/10 budget instead of sharing exhausted counters."""

        return cls.for_query(
            question_class=prior_budget.question_class,
            recovery_stage=recovery_stage,
            attempt_index=prior_budget.attempt_index + 1,
            requested_tool_calls=prior_budget.max_tool_calls,
            requested_model_requests=prior_budget.max_requests,
        )

    @staticmethod
    def _resolve_question_class(value: QuestionClass | str | None) -> QuestionClass:
        if isinstance(value, QuestionClass):
            return value
        try:
            return QuestionClass(str(value))
        except ValueError:
            return QuestionClass.UNKNOWN


__all__ = ["AgentBudgetPolicy"]
