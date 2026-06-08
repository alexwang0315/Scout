"""Dependency and provider contracts for Scout AI OS agents."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass
class ScoutDeps:
    """Dependency container passed to agent facades.

    Phase 5 agents expose these services as callable tools only. They do not
    execute workflows, install capabilities, write learning artifacts, or run
    sandbox code.
    """

    capability_registry: Any
    memory_store: Any
    workflow_store: Any
    sandbox: Any
    permission_gate: Any
    notification_gateway: Any
    docs_search: Any
    user_id: str
    active_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoutToolbox:
    """Callable tool surface offered to local or fake providers."""

    search_memory: Callable[[str], list[str]]
    search_capabilities: Callable[[str], list[dict[str, Any]]]
    get_active_context: Callable[[], dict[str, Any]]
    get_capability: Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class ScoutAgentRequest:
    """Provider request envelope for a typed Scout agent run."""

    agent_name: str
    instructions: str
    prompt: str
    output_type: type[BaseModel]
    deps: ScoutDeps
    tools: ScoutToolbox
    context: dict[str, Any]


class ScoutAgentProvider(Protocol):
    """Provider protocol used by the typed facades.

    Tests can inject a deterministic fake provider. A future Pydantic AI backed
    provider can implement the same protocol without changing facade call sites.
    """

    def run(self, request: ScoutAgentRequest) -> Any:
        """Return an object or dict compatible with ``request.output_type``."""


def validate_provider_output(output: Any, output_type: type[OutputT]) -> OutputT:
    """Validate provider output into the declared Pydantic type."""

    if isinstance(output, output_type):
        return output
    return output_type.model_validate(output)


def build_toolbox(deps: ScoutDeps) -> ScoutToolbox:
    """Create the read-only tool surface described in the Phase 5 spec."""

    def search_memory(query: str) -> list[str]:
        memory_store = deps.memory_store
        if memory_store is None or not hasattr(memory_store, "search"):
            return []
        matches = memory_store.search(deps.user_id, query)
        return [getattr(item, "content", str(item)) for item in matches]

    def search_capabilities(query: str) -> list[dict[str, Any]]:
        registry = deps.capability_registry
        if registry is None or not hasattr(registry, "search"):
            return []
        matches = registry.search(query)
        return [_to_plain_dict(match) for match in matches]

    def get_active_context() -> dict[str, Any]:
        return dict(deps.active_context)

    def get_capability(name: str) -> dict[str, Any] | None:
        registry = deps.capability_registry
        if registry is None or not hasattr(registry, "get"):
            return None
        match = registry.get(name)
        if match is None:
            return None
        return _to_plain_dict(match)

    return ScoutToolbox(
        search_memory=search_memory,
        search_capabilities=search_capabilities,
        get_active_context=get_active_context,
        get_capability=get_capability,
    )


class DeterministicScoutAgentProvider:
    """Local typed provider used for tests and the no-LLM MVP path."""

    def run(self, request: ScoutAgentRequest) -> Any:
        if request.agent_name == "WorkflowCompilerAgent":
            return self._compile_workflow(request)
        if request.agent_name == "ExecutionPlannerAgent":
            return self._plan_execution(request)
        if request.agent_name == "CodeBuilderAgent":
            return self._build_package(request)
        if request.agent_name == "LearningAgent":
            return self._propose_learning(request)
        raise ValueError(f"unknown agent: {request.agent_name}")

    def _compile_workflow(self, request: ScoutAgentRequest) -> Any:
        from scout.schemas.permissions import PermissionSpec
        from scout.schemas.workflow import (
            ActionSpec,
            ActionType,
            RuntimeTarget,
            TriggerSpec,
            TriggerType,
            WorkflowLifecycle,
            WorkflowSpec,
        )

        utterance = str(request.context.get("utterance") or "").strip()
        lowered = utterance.casefold()
        trigger = _infer_trigger(lowered, request.deps.active_context)
        lifecycle = _infer_lifecycle(lowered, trigger.type)
        required = ["notification.send"]
        if trigger.type is TriggerType.LOCATION:
            required.append("location.read")
        elif trigger.type is TriggerType.EMAIL:
            required.append("email.read")
        elif trigger.type is TriggerType.CALENDAR:
            required.append("calendar.read")
        elif trigger.type is TriggerType.WEB_CHANGE:
            required.append("web.monitor")
        approval_required = lifecycle is WorkflowLifecycle.PERMANENT or trigger.type in {
            TriggerType.LOCATION,
            TriggerType.EMAIL,
            TriggerType.CALENDAR,
            TriggerType.WEB_CHANGE,
        }
        return WorkflowSpec(
            name=_name_from_utterance(utterance),
            source_utterance=utterance,
            user_goal=utterance,
            trigger=trigger,
            actions=[
                ActionSpec(
                    type=ActionType.NOTIFY,
                    description="Notify the user locally.",
                    config={"title": "Scout reminder", "body": utterance},
                )
            ],
            lifecycle=lifecycle,
            runtime=RuntimeTarget.PI,
            permissions=PermissionSpec(
                required=required,
                approval_required=approval_required,
                reason="Sensitive or persistent workflow." if approval_required else "",
            ),
            fallback_policy={"provider": "deterministic"},
            verification_plan=["Review workflow before installation."],
            learning_candidates=["eval_case"],
        )

    @staticmethod
    def _plan_execution(request: ScoutAgentRequest) -> Any:
        from scout.schemas.runtime import ExecutionPlan, PlanMode
        from scout.schemas.workflow import ActionType, WorkflowSpec

        workflow = WorkflowSpec.model_validate(request.context["workflow"])
        required: list[str] = []
        for action in workflow.actions:
            if action.type in {ActionType.NOTIFY, ActionType.ASK_USER}:
                required.append("manual_notification")
            elif action.type is ActionType.UI_ACTION:
                required.append("scout.ui.action_plan")
            elif action.type is ActionType.RUN_CAPABILITY:
                capability = action.config.get("capability")
                if isinstance(capability, str):
                    required.append(capability)
        required = list(dict.fromkeys(required))
        missing = [
            capability
            for capability in required
            if request.tools.get_capability(capability) is None
        ]
        if workflow.permissions.approval_required:
            mode = PlanMode.ASK_PERMISSION
        elif missing:
            mode = PlanMode.BUILD_NEW_CAPABILITY
        else:
            mode = PlanMode.USE_EXISTING
        return ExecutionPlan(
            mode=mode,
            reason="Deterministic MVP plan.",
            workflow=workflow,
            required_capabilities=required,
            missing_capabilities=missing,
            approval_message=(
                "Approve this workflow before installation."
                if workflow.permissions.approval_required
                else None
            ),
            safety_notes=["Planner does not approve generated code."],
            next_steps=["Evaluate PermissionGate."],
        )

    @staticmethod
    def _build_package(request: ScoutAgentRequest) -> Any:
        from scout.schemas.capability import (
            CapabilityBuildRequest,
            CapabilityRuntime,
            CapabilitySpec,
            GeneratedCapabilityPackage,
        )

        build_request = CapabilityBuildRequest.model_validate(
            request.context["build_request"]
        )
        spec = CapabilitySpec(
            name=build_request.capability_name,
            description=build_request.purpose,
            runtime=CapabilityRuntime.PYTHON,
            risk_level=build_request.risk_level,
            input_schema=build_request.input_schema,
            output_schema=build_request.output_schema,
            test_cases=build_request.test_cases,
        )
        return GeneratedCapabilityPackage(
            spec=spec,
            files={
                "implementation.py": (
                    "def run(payload):\n"
                    "    return payload\n"
                )
            },
            tests={
                "test_implementation.py": (
                    "from implementation import run\n\n"
                    "def test_run_returns_payload():\n"
                    "    assert run({'ok': True}) == {'ok': True}\n"
                )
            },
            install_notes="Generated candidate only.",
            security_notes=["No network, shell, or secret access requested."],
        )

    @staticmethod
    def _propose_learning(request: ScoutAgentRequest) -> Any:
        from scout.schemas.learning import (
            LearningArtifact,
            LearningArtifactType,
            LearningBundle,
        )
        from scout.schemas.workflow import WorkflowSpec

        workflow = WorkflowSpec.model_validate(request.context["workflow"])
        return LearningBundle(
            artifacts=[
                LearningArtifact(
                    type=LearningArtifactType.EVAL_CASE,
                    title=f"Eval case for {workflow.name}",
                    reason="Regression coverage for workflow compilation.",
                    content={
                        "user_utterance": workflow.source_utterance,
                        "expected": {
                            "trigger_type": workflow.trigger.type.value,
                            "action_types": [
                                action.type.value for action in workflow.actions
                            ],
                            "lifecycle": workflow.lifecycle.value,
                            "required_permissions": workflow.permissions.required,
                        },
                    },
                )
            ],
            summary="One reviewable eval-case candidate.",
        )


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    raise TypeError(f"tool result is not dict-like: {type(value)!r}")


__all__ = [
    "DeterministicScoutAgentProvider",
    "ScoutAgentProvider",
    "ScoutAgentRequest",
    "ScoutDeps",
    "ScoutToolbox",
    "build_toolbox",
    "validate_provider_output",
]


def _infer_trigger(lowered: str, active_context: dict[str, Any]) -> Any:
    from scout.schemas.workflow import TriggerSpec, TriggerType

    if any(term in lowered for term in ("100 meters", "campsite", "near ", "location")):
        return TriggerSpec(type=TriggerType.LOCATION, description="Location trigger")
    if "email" in lowered:
        return TriggerSpec(type=TriggerType.EMAIL, description="Email trigger")
    if "calendar" in lowered:
        return TriggerSpec(type=TriggerType.CALENDAR, description="Calendar trigger")
    if any(term in lowered for term in ("watch ", "booking page", "web", "page")):
        return TriggerSpec(type=TriggerType.WEB_CHANGE, description="Web change trigger")
    minutes_match = re.search(r"in (\d+) minute", lowered)
    if minutes_match:
        now = active_context.get("now")
        base = datetime.fromisoformat(now) if isinstance(now, str) else datetime.now(UTC)
        run_at = base.astimezone(UTC) + timedelta(minutes=int(minutes_match.group(1)))
        return TriggerSpec(
            type=TriggerType.TIME,
            description="Relative time trigger",
            config={"run_at": run_at.isoformat()},
        )
    if any(term in lowered for term in ("remind", "later", "time")):
        return TriggerSpec(type=TriggerType.TIME, description="Time trigger")
    return TriggerSpec(type=TriggerType.MANUAL, description="Manual trigger")


def _infer_lifecycle(lowered: str, trigger_type: Any) -> Any:
    from scout.schemas.workflow import TriggerType, WorkflowLifecycle

    if any(term in lowered for term in ("whenever", "always", "permanent", "watch ")):
        return WorkflowLifecycle.PERMANENT
    if trigger_type is TriggerType.LOCATION:
        return WorkflowLifecycle.TRIP_SCOPED
    if trigger_type is TriggerType.TIME:
        return WorkflowLifecycle.ONE_SHOT
    return WorkflowLifecycle.SESSION_SCOPED


def _name_from_utterance(utterance: str) -> str:
    if not utterance:
        return "Scout workflow"
    if len(utterance) <= 60:
        return utterance.rstrip(".")
    return utterance[:57].rstrip() + "..."
