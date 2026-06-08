from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scout.agents import (
    CodeBuilderAgent,
    DeterministicScoutAgentProvider,
    ExecutionPlannerAgent,
    LearningAgent,
    PydanticScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    WorkflowCompilerAgent,
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
