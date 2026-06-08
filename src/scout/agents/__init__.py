"""Typed Pydantic AI facade package for Scout AI OS."""

from scout.agents.code_builder import CodeBuilderAgent
from scout.agents.deps import (
    DeterministicScoutAgentProvider,
    ScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    ScoutToolbox,
)
from scout.agents.execution_planner import ExecutionPlannerAgent
from scout.agents.learner import LearningAgent
from scout.agents.model_policy import (
    DEFAULT_LOCAL_MODEL_LABEL,
    ModelPolicy,
    ModelPolicyMode,
    ModelPolicySource,
    resolve_model_policy,
)
from scout.agents.pydantic_provider import PydanticScoutAgentProvider
from scout.agents.workflow_compiler import WorkflowCompilerAgent


__all__ = [
    "CodeBuilderAgent",
    "DeterministicScoutAgentProvider",
    "ExecutionPlannerAgent",
    "LearningAgent",
    "DEFAULT_LOCAL_MODEL_LABEL",
    "ModelPolicy",
    "ModelPolicyMode",
    "ModelPolicySource",
    "PydanticScoutAgentProvider",
    "ScoutAgentProvider",
    "ScoutAgentRequest",
    "ScoutDeps",
    "ScoutToolbox",
    "WorkflowCompilerAgent",
    "resolve_model_policy",
]
