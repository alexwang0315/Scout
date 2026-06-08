from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scout.agents import (
    CodeBuilderAgent,
    DeterministicScoutAgentProvider,
    ExecutionPlannerAgent,
    LearningAgent,
    ModelPolicyMode,
    ModelPolicySource,
    PydanticScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    WorkflowCompilerAgent,
    resolve_model_policy,
)
from scout.schemas import (
    ActionSpec,
    ActionType,
    CapabilityBuildRequest,
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
    LearningArtifact,
    LearningArtifactType,
    LearningBundle,
    PermissionSpec,
    PlanMode,
    RuntimeTarget,
    TriggerSpec,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)
from scout.services import (
    CapabilityRegistry,
    MemoryStore,
    NotificationGateway,
    PermissionGate,
    WorkflowStore,
    open_database,
)
from scout.services.docs_search import DocsSearch
from scout.services.sandbox_runner import SandboxRunner


ROOT = Path(__file__).resolve().parents[1]


def make_deps(tmp_path: Path) -> ScoutDeps:
    connection = open_database(tmp_path / "agents.sqlite")
    workflow_store = WorkflowStore(connection)
    memory_store = MemoryStore(connection)
    capability_registry = CapabilityRegistry(connection)
    capability_registry.load_builtins(ROOT / "src/scout/capabilities/builtins")
    return ScoutDeps(
        capability_registry=capability_registry,
        memory_store=memory_store,
        workflow_store=workflow_store,
        sandbox=SandboxRunner(),
        permission_gate=PermissionGate(),
        notification_gateway=NotificationGateway(workflow_store),
        docs_search=DocsSearch(ROOT / "docs"),
        user_id="user-1",
        active_context={"now": "2026-06-08T00:00:00+00:00"},
    )


def test_deterministic_workflow_compiler_returns_typed_location_workflow(
    tmp_path: Path,
) -> None:
    workflow = WorkflowCompilerAgent(DeterministicScoutAgentProvider()).compile(
        "Notify me 100 meters before the next campsite.",
        make_deps(tmp_path),
    )

    assert workflow.trigger.type is TriggerType.LOCATION
    assert "location.read" in workflow.permissions.required
    assert workflow.permissions.approval_required is True


def test_pydantic_ai_provider_runs_workflow_compiler_agent(tmp_path: Path) -> None:
    workflow = WorkflowCompilerAgent(PydanticScoutAgentProvider()).compile(
        "Remind me in 10 minutes.",
        make_deps(tmp_path),
    )

    assert workflow.trigger.type is TriggerType.TIME
    assert workflow.actions[0].type is ActionType.NOTIFY
    assert workflow.permissions.required == ["notification.send"]


def test_model_policy_defaults_to_local_function_model() -> None:
    policy = resolve_model_policy(env={})

    assert policy.mode is ModelPolicyMode.LOCAL_FUNCTION
    assert policy.source is ModelPolicySource.DEFAULT
    assert policy.model_for_agent is None
    assert policy.requires_network is False
    assert policy.missing_credential_env == []
    assert policy.timeout_seconds == 30.0
    assert policy.max_cost_usd is None
    assert policy.estimated_call_cost_usd == 0.0
    assert policy.fallback_model == "local FunctionModel"


def test_model_policy_normalizes_openrouter_alias_and_checks_key() -> None:
    policy = resolve_model_policy("gpt-4o-mini", env={})

    assert policy.mode is ModelPolicyMode.EXTERNAL_PYDANTIC_AI
    assert policy.source is ModelPolicySource.EXPLICIT
    assert policy.model_for_agent == "openrouter:openai/gpt-4o-mini"
    assert policy.required_credential_env == ["OPENROUTER_API_KEY"]
    assert policy.missing_credential_env == ["OPENROUTER_API_KEY"]

    with_key = resolve_model_policy(
        "gemma3-27b",
        env={"OPENROUTER_API_KEY": "sk-test-secret"},
    )
    assert with_key.model_for_agent == "openrouter:google/gemma-3-27b-it"
    assert with_key.missing_credential_env == []
    assert "sk-test-secret" not in str(with_key.model_dump(mode="json"))


def test_model_policy_uses_env_model_when_explicit_model_is_absent() -> None:
    policy = resolve_model_policy(
        env={
            "SCOUT_AI_OS_MODEL": "openrouter:openai/gpt-4o-mini",
            "OPENROUTER_API_KEY": "sk-test-secret",
        },
    )

    assert policy.source is ModelPolicySource.ENV
    assert policy.model_for_agent == "openrouter:openai/gpt-4o-mini"
    assert policy.missing_credential_env == []


def test_model_policy_reports_rollout_timeout_budget_and_fallback() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test-secret",
            "SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "12.5",
            "SCOUT_AI_OS_MODEL_MAX_COST_USD": "0.02",
            "SCOUT_AI_OS_MODEL_FALLBACK": "gemma3-27b",
        },
    )

    assert policy.timeout_seconds == 12.5
    assert policy.max_cost_usd == 0.02
    assert policy.estimated_call_cost_usd == 0.001
    assert policy.fallback_model == "openrouter:google/gemma-3-27b-it"
    assert "sk-test-secret" not in str(policy.model_dump(mode="json"))


def test_model_policy_reports_estimated_call_cost() -> None:
    policy = resolve_model_policy(
        "openrouter:openai/gpt-4o-mini",
        env={
            "OPENROUTER_API_KEY": "sk-test-secret",
            "SCOUT_AI_OS_MODEL_ESTIMATED_CALL_COST_USD": "0.004",
        },
    )

    assert policy.estimated_call_cost_usd == 0.004


def test_model_policy_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS"):
        resolve_model_policy(env={"SCOUT_AI_OS_MODEL_TIMEOUT_SECONDS": "0"})


def test_workflow_compiler_rejects_sensitive_output_without_approval(
    tmp_path: Path,
) -> None:
    class UnsafeProvider:
        def run(self, request: ScoutAgentRequest) -> Any:
            return WorkflowSpec(
                name="Unsafe location workflow",
                source_utterance="Notify me near camp.",
                user_goal="Notify near camp.",
                trigger=TriggerSpec(
                    type=TriggerType.LOCATION,
                    description="Near camp",
                ),
                actions=[
                    ActionSpec(
                        type=ActionType.NOTIFY,
                        description="Notify locally.",
                    )
                ],
                lifecycle=WorkflowLifecycle.TRIP_SCOPED,
                runtime=RuntimeTarget.PI,
                permissions=PermissionSpec(
                    required=["location.read"],
                    approval_required=False,
                ),
            )

    with pytest.raises(ValueError):
        WorkflowCompilerAgent(UnsafeProvider()).compile(
            "Notify me near camp.",
            make_deps(tmp_path),
        )


def test_execution_planner_prefers_existing_capabilities(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    workflow = WorkflowCompilerAgent(DeterministicScoutAgentProvider()).compile(
        "Remind me in 10 minutes.",
        deps,
    )

    plan = ExecutionPlannerAgent(DeterministicScoutAgentProvider()).plan(
        workflow,
        deps,
    )

    assert plan.required_capabilities == ["manual_notification"]
    assert plan.missing_capabilities == []


def test_execution_planner_maps_ui_action_to_builtin_capability(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    workflow = WorkflowSpec(
        name="Pretrip UI action",
        source_utterance="Only show risk score layers.",
        user_goal="Plan a browser-local UI action.",
        trigger=TriggerSpec(type=TriggerType.MANUAL, description="Manual"),
        actions=[
            ActionSpec(
                type=ActionType.UI_ACTION,
                description="Plan risk-only layer visibility.",
                config={
                    "surface": "pretrip",
                    "request_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
                },
            )
        ],
        lifecycle=WorkflowLifecycle.SESSION_SCOPED,
        runtime=RuntimeTarget.BROWSER,
        permissions=PermissionSpec(required=["session_local_ui"]),
    )

    plan = ExecutionPlannerAgent(DeterministicScoutAgentProvider()).plan(
        workflow,
        deps,
    )

    assert plan.mode is PlanMode.USE_EXISTING
    assert plan.required_capabilities == ["scout.ui.action_plan"]
    assert plan.missing_capabilities == []


def test_execution_planner_repairs_missing_approval_message(
    tmp_path: Path,
) -> None:
    class MissingApprovalMessageProvider:
        def run(self, request: ScoutAgentRequest) -> Any:
            if request.agent_name == "WorkflowCompilerAgent":
                return DeterministicScoutAgentProvider().run(request)
            if request.agent_name == "ExecutionPlannerAgent":
                workflow = WorkflowSpec.model_validate(request.context["workflow"])
                return {
                    "mode": "use_existing",
                    "reason": "Provider forgot approval message.",
                    "workflow": workflow.model_dump(mode="json"),
                    "required_capabilities": ["manual_notification"],
                    "missing_capabilities": [],
                    "approval_message": None,
                    "safety_notes": [],
                    "next_steps": [],
                }
            raise ValueError(request.agent_name)

    deps = make_deps(tmp_path)
    provider = MissingApprovalMessageProvider()
    workflow = WorkflowCompilerAgent(provider).compile(
        "Notify me 100 meters before the next campsite.",
        deps,
    )

    plan = ExecutionPlannerAgent(provider).plan(workflow, deps)

    assert plan.mode is PlanMode.ASK_PERMISSION
    assert plan.approval_message == "Approve this workflow before installation."


def test_code_builder_requires_low_risk_and_tests(tmp_path: Path) -> None:
    package = CodeBuilderAgent(DeterministicScoutAgentProvider()).build(
        CapabilityBuildRequest(
            capability_name="payload_echo",
            purpose="Echo a JSON payload.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            risk_level=CapabilityRisk.LOW,
        ),
        make_deps(tmp_path),
    )

    assert package.spec.name == "payload_echo"
    assert package.files
    assert package.tests


def test_code_builder_rejects_high_risk_provider_output(tmp_path: Path) -> None:
    class HighRiskProvider:
        def run(self, request: ScoutAgentRequest) -> Any:
            return GeneratedCapabilityPackage(
                spec=CapabilitySpec(
                    name="bad",
                    description="Bad package",
                    runtime=CapabilityRuntime.PYTHON,
                    risk_level=CapabilityRisk.HIGH,
                    input_schema={},
                    output_schema={},
                ),
                files={"implementation.py": "def run(payload): return payload"},
                tests={"test_implementation.py": "def test_run(): assert True"},
                install_notes="bad",
            )

    with pytest.raises(ValueError):
        CodeBuilderAgent(HighRiskProvider()).build(
            CapabilityBuildRequest(
                capability_name="bad",
                purpose="Bad package",
                input_schema={},
                output_schema={},
                risk_level=CapabilityRisk.LOW,
            ),
            make_deps(tmp_path),
        )


def test_learning_agent_requires_reviewable_artifacts(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    workflow = WorkflowCompilerAgent(DeterministicScoutAgentProvider()).compile(
        "Remind me in 10 minutes.",
        deps,
    )

    bundle = LearningAgent(DeterministicScoutAgentProvider()).propose(workflow, deps)

    assert bundle.artifacts
    assert all(artifact.requires_review for artifact in bundle.artifacts)
    assert bundle.artifacts[0].content["expected"]["trigger_type"] == "time"


def test_learning_agent_rejects_non_reviewable_artifact(tmp_path: Path) -> None:
    class NonReviewableProvider:
        def run(self, request: ScoutAgentRequest) -> Any:
            return LearningBundle(
                artifacts=[
                    LearningArtifact(
                        type=LearningArtifactType.MEMORY,
                        title="Unsafe memory",
                        reason="No review",
                        content={"content": "store without review"},
                        requires_review=False,
                    )
                ],
                summary="unsafe",
            )

    deps = make_deps(tmp_path)
    workflow = WorkflowCompilerAgent(DeterministicScoutAgentProvider()).compile(
        "Remind me in 10 minutes.",
        deps,
    )

    with pytest.raises(ValueError):
        LearningAgent(NonReviewableProvider()).propose(workflow, deps)
