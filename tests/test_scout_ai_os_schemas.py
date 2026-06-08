from __future__ import annotations

import pytest
from pydantic import ValidationError

from scout.schemas import (
    ActionSpec,
    ActionType,
    CapabilityBuildRequest,
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    ConditionSpec,
    ExecutionPlan,
    GeneratedCapabilityPackage,
    InstallDecision,
    InstallScope,
    LearningArtifact,
    LearningArtifactType,
    LearningBundle,
    PermissionDecision,
    PermissionSpec,
    PlanMode,
    RuntimeTarget,
    SandboxResult,
    TriggerSpec,
    TriggerType,
    WorkflowLifecycle,
    WorkflowSpec,
)


def make_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        name="Trip weather reminder",
        source_utterance="Remind me if the trip forecast changes.",
        user_goal="Notify the user about weather changes before a trip.",
        trigger=TriggerSpec(
            type=TriggerType.TIME,
            description="Check every morning",
            config={"hour": 7},
        ),
        conditions=[
            ConditionSpec(
                description="Weather forecast changed",
                expression="forecast.delta in ['rain', 'storm']",
                required_data_sources=["weather"],
            )
        ],
        actions=[
            ActionSpec(
                type=ActionType.NOTIFY,
                description="Notify the user locally",
                config={"priority": "normal"},
            )
        ],
        lifecycle=WorkflowLifecycle.TRIP_SCOPED,
        runtime=RuntimeTarget.PI,
        permissions=PermissionSpec(
            required=["weather.read"],
            approval_required=True,
            reason="Trip-scoped weather monitoring requires approval.",
        ),
        verification_plan=["Validate forecast payload shape"],
        learning_candidates=["Possible weather reminder template"],
    )


def test_workflow_spec_validates_and_serializes_enums() -> None:
    workflow = make_workflow()

    assert workflow.id is None
    assert workflow.trigger.type is TriggerType.TIME
    assert workflow.actions[0].type is ActionType.NOTIFY
    assert workflow.permissions.required == ["weather.read"]

    dumped = workflow.model_dump(mode="json")
    assert dumped["trigger"]["type"] == "time"
    assert dumped["actions"][0]["type"] == "notify"
    assert dumped["lifecycle"] == "trip_scoped"
    assert dumped["runtime"] == "pi"


def test_workflow_requires_at_least_one_action() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec(
            name="Incomplete workflow",
            source_utterance="Do something",
            user_goal="Something should happen",
            trigger=TriggerSpec(type=TriggerType.MANUAL, description="Manual"),
            actions=[],
            lifecycle=WorkflowLifecycle.ONE_SHOT,
            runtime=RuntimeTarget.SANDBOX,
            permissions=PermissionSpec(),
        )


def test_workflow_accepts_session_local_ui_action_contract() -> None:
    workflow = WorkflowSpec(
        name="Pretrip map layer action",
        source_utterance="Only show risk score layers.",
        user_goal="Plan a session-local browser UI action.",
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

    dumped = workflow.model_dump(mode="json")

    assert workflow.actions[0].type is ActionType.UI_ACTION
    assert dumped["actions"][0]["type"] == "ui_action"
    assert dumped["runtime"] == "browser"


def test_workflow_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TriggerSpec(
            type=TriggerType.MANUAL,
            description="Manual",
            unsupported=True,
        )


def test_capability_spec_build_request_and_package_contracts() -> None:
    spec = CapabilitySpec(
        name="json_transform",
        description="Transform a JSON object using a declared mapping.",
        runtime=CapabilityRuntime.PYTHON,
        risk_level=CapabilityRisk.LOW,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=[],
        test_cases=[{"input": {"a": 1}, "output": {"a": 1}}],
    )
    build_request = CapabilityBuildRequest(
        capability_name="json_transform",
        purpose="Transform JSON without network access.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        constraints=["No network access"],
        risk_level=CapabilityRisk.LOW,
    )
    package = GeneratedCapabilityPackage(
        spec=spec,
        files={"implementation.py": "def run(payload): return payload"},
        tests={"test_implementation.py": "def test_run(): assert True"},
        install_notes="Generated package candidate only.",
        security_notes=["No network access requested"],
    )

    assert spec.install_scope is InstallScope.USER
    assert build_request.risk_level is CapabilityRisk.LOW
    assert package.spec.name == "json_transform"
    assert package.model_dump(mode="json")["spec"]["runtime"] == "python"


def test_capability_rejects_invalid_risk_level() -> None:
    with pytest.raises(ValidationError):
        CapabilitySpec(
            name="bad",
            description="Invalid risk example",
            runtime=CapabilityRuntime.PYTHON,
            risk_level="critical",
            input_schema={},
            output_schema={},
        )


def test_execution_plan_sandbox_and_install_decision_contracts() -> None:
    workflow = make_workflow()
    plan = ExecutionPlan(
        mode=PlanMode.USE_EXISTING,
        reason="Built-in notification capability is available.",
        workflow=workflow,
        required_capabilities=["manual_notification"],
        safety_notes=["No outbound third-party message send"],
        next_steps=["Request user approval before installing workflow"],
    )
    sandbox_result = SandboxResult(
        passed=True,
        test_summary="1 passed",
        resource_usage={"seconds": 0.03},
    )
    install_decision = InstallDecision(
        approved_for_install=False,
        reason="Generated package still requires user approval.",
        install_scope=InstallScope.SESSION,
        required_user_approval=True,
    )

    assert plan.mode is PlanMode.USE_EXISTING
    assert plan.workflow.name == "Trip weather reminder"
    assert sandbox_result.security_findings == []
    assert install_decision.required_user_approval is True


def test_learning_bundle_is_reviewable_by_default() -> None:
    artifact = LearningArtifact(
        type=LearningArtifactType.WORKFLOW_TEMPLATE,
        title="Trip weather reminder template",
        reason="The workflow may be reusable for similar trips.",
        content={"workflow_name": "Trip weather reminder"},
    )
    bundle = LearningBundle(
        artifacts=[artifact],
        summary="One reviewable workflow template candidate.",
    )

    assert artifact.requires_review is True
    assert bundle.artifacts[0].type is LearningArtifactType.WORKFLOW_TEMPLATE


def test_permission_decision_contract() -> None:
    decision = PermissionDecision(
        allowed=False,
        requires_user_approval=True,
        reason="Permanent monitoring requires explicit approval.",
        user_message="Please approve this workflow before it is installed.",
    )

    assert decision.model_dump()["allowed"] is False
