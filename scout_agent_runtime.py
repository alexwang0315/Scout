from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_agent_models import ScoutAgentToolBoundary
from scout_agent_tools import (
    find_tool_manifest,
    load_tool_manifests,
    run_registered_tool,
    summarize_tool_manifest,
)


PlannerRunnerFactory = Callable[[Any], "ScoutAgentPlannerRunner"]


class ScoutAgentPlannerRunner(Protocol):
    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        ...


class ScoutAgentRuntimeBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutAgentToolCall(ScoutAgentRuntimeBaseModel):
    tool_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    input_path: str | None = None
    output_path: str | None = None
    dry_run: bool = True
    authorized_by: str | None = None


class ScoutAgentToolPlan(ScoutAgentRuntimeBaseModel):
    artifact_kind: str = "scout_agent_tool_plan"
    plan_id: str = Field(min_length=1)
    agent_run_id: str = Field(min_length=1)
    user_intent: str = Field(min_length=1)
    tool_calls: list[ScoutAgentToolCall] = Field(min_length=1)
    rationale: str | None = None
    boundary: ScoutAgentToolBoundary = Field(default_factory=ScoutAgentToolBoundary)

    @model_validator(mode="after")
    def validate_boundary(self) -> "ScoutAgentToolPlan":
        if self.boundary.live_safety_api_calls_allowed:
            raise ValueError("agent tool plans must not allow live safety API calls")
        if self.boundary.phase1_safety_mutation_allowed:
            raise ValueError("agent tool plans must not allow Phase 1 safety mutation")
        return self


class ScoutAgentToolPlanExecution(ScoutAgentRuntimeBaseModel):
    artifact_kind: str = "scout_agent_tool_plan_execution"
    plan_id: str
    agent_run_id: str
    status: str
    result_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    tool_results: list[dict[str, Any]]
    boundary: ScoutAgentToolBoundary = Field(default_factory=ScoutAgentToolBoundary)


class ScoutAgentPlannerProviderStatus(ScoutAgentRuntimeBaseModel):
    artifact_kind: str = "scout_agent_planner_provider_status"
    active_profile: str
    cloud_model: str
    local_model: str
    fallback_to_local_on_error: bool
    local_fallback_fixed_schema_used: bool = False
    runner_profile: str | None = None
    failover_count: int = 0
    failover_reason: str | None = None
    token_env_refs: list[str] = Field(default_factory=list)
    boundary: ScoutAgentToolBoundary = Field(default_factory=ScoutAgentToolBoundary)


def build_agent_tool_registry_context(manifest_dir: str | Path) -> dict[str, Any]:
    manifests = load_tool_manifests(manifest_dir)
    return {
        "artifact_kind": "scout_agent_tool_registry_context",
        "tool_count": len(manifests),
        "tools": [summarize_tool_manifest(manifest) for manifest in manifests],
        "boundary": ScoutAgentToolBoundary().model_dump(mode="json"),
    }


def build_agent_tool_planning_prompt(
    *,
    user_intent: str,
    manifest_dir: str | Path,
    context: dict[str, Any] | None = None,
) -> str:
    registry = build_agent_tool_registry_context(manifest_dir)
    payload = {
        "instruction": (
            "Return only JSON matching scout_agent_tool_plan. Choose registered "
            "Scout tools only. Prefer dry_run unless the user/operator has explicit "
            "authorization. Do not request live /safety/*, Phase 1 mutation, real "
            "outbound send, or hardware control."
        ),
        "user_intent": user_intent,
        "context": _redact_context(context or {}),
        "tool_registry": registry,
        "required_fields": {
            "artifact_kind": "scout_agent_tool_plan",
            "plan_id": "agent_plan.<stable id>",
            "agent_run_id": "agent_run.<stable id>",
            "user_intent": user_intent,
            "tool_calls": [
                {
                    "tool_id": "registered tool id",
                    "action_id": "agent_action.<stable id>",
                    "input_path": "optional local JSON input path",
                    "output_path": "optional output path",
                    "dry_run": True,
                    "authorized_by": None,
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_agent_tool_plan(model_output: str) -> ScoutAgentToolPlan:
    payload = json.loads(model_output)
    return ScoutAgentToolPlan.model_validate(payload)


def load_agent_tool_plan(path: str | Path) -> ScoutAgentToolPlan:
    return ScoutAgentToolPlan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def run_agent_tool_plan(
    plan: ScoutAgentToolPlan,
    *,
    manifest_dir: str | Path,
    trace_log_path: str | Path | None = None,
) -> ScoutAgentToolPlanExecution:
    results = []
    for call in plan.tool_calls:
        manifest = find_tool_manifest(manifest_dir, call.tool_id)
        result = run_registered_tool(
            manifest,
            input_path=call.input_path,
            output_path=call.output_path,
            trace_log_path=trace_log_path,
            agent_run_id=plan.agent_run_id,
            action_id=call.action_id,
            dry_run=call.dry_run,
            authorized_by=call.authorized_by,
        )
        results.append(result)
    payloads = [result.model_dump(mode="json") for result in results]
    completed = sum(1 for result in results if str(result.status).endswith("completed"))
    blocked = sum(1 for result in results if str(result.status).endswith("blocked"))
    failed = sum(1 for result in results if str(result.status).endswith("failed"))
    if failed:
        status = "failed"
    elif blocked:
        status = "blocked" if blocked == len(results) else "partial"
    else:
        status = "completed"
    return ScoutAgentToolPlanExecution(
        plan_id=plan.plan_id,
        agent_run_id=plan.agent_run_id,
        status=status,
        result_count=len(results),
        completed_count=completed,
        blocked_count=blocked,
        failed_count=failed,
        tool_results=payloads,
    )


def run_pydantic_agent_tool_plan(
    runner: ScoutAgentPlannerRunner,
    *,
    user_intent: str,
    manifest_dir: str | Path,
    context: dict[str, Any] | None = None,
    trace_log_path: str | Path | None = None,
    timeout_seconds: int = 8,
) -> ScoutAgentToolPlanExecution:
    prompt = build_agent_tool_planning_prompt(
        user_intent=user_intent,
        manifest_dir=manifest_dir,
        context=context,
    )
    model_output = runner.run(prompt, timeout_seconds=timeout_seconds)
    plan = parse_agent_tool_plan(model_output)
    return run_agent_tool_plan(
        plan,
        manifest_dir=manifest_dir,
        trace_log_path=trace_log_path,
    )


def create_configured_scout_agent_planner_runner(
    config: Any,
    *,
    environ: dict[str, str] | None = None,
    runner_factory: PlannerRunnerFactory | None = None,
) -> ScoutAgentPlannerRunner:
    from assistant_pydantic_provider import FallbackPydanticAIRunner, PydanticAIEnvRunner

    factory = runner_factory or (
        lambda profile: PydanticAIEnvRunner.from_profile(profile, environ=environ)
    )
    cloud_runner = factory(config.cloud_model)
    if config.active_profile == "local":
        return factory(config.local_model)
    if not config.fallback_to_local_on_error:
        return cloud_runner
    return FallbackPydanticAIRunner(
        primary_runner=cloud_runner,
        fallback_runner=factory(config.local_model),
        primary_profile="cloud",
        fallback_profile="local",
        enforce_local_fixed_schema=False,
    )


def build_scout_agent_planner_provider_status(
    config: Any,
    runner: ScoutAgentPlannerRunner,
) -> ScoutAgentPlannerProviderStatus:
    token_env_refs = [
        profile.token_env_var
        for profile in (config.cloud_model, config.local_model)
        if getattr(profile, "token_env_var", None)
    ]
    return ScoutAgentPlannerProviderStatus(
        active_profile=config.active_profile,
        cloud_model=config.cloud_model.model_name,
        local_model=config.local_model.model_name,
        fallback_to_local_on_error=config.fallback_to_local_on_error,
        local_fallback_fixed_schema_used=False,
        runner_profile=getattr(runner, "last_profile", None),
        failover_count=int(getattr(runner, "failover_count", 0) or 0),
        failover_reason=getattr(runner, "last_failover_reason", None),
        token_env_refs=token_env_refs,
    )


def run_configured_scout_agent_tool_plan(
    *,
    config: Any,
    user_intent: str,
    manifest_dir: str | Path,
    context: dict[str, Any] | None = None,
    trace_log_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
    runner_factory: PlannerRunnerFactory | None = None,
) -> tuple[ScoutAgentToolPlanExecution, ScoutAgentPlannerProviderStatus]:
    runner = create_configured_scout_agent_planner_runner(
        config,
        environ=environ,
        runner_factory=runner_factory,
    )
    execution = run_pydantic_agent_tool_plan(
        runner,
        user_intent=user_intent,
        manifest_dir=manifest_dir,
        context=context,
        trace_log_path=trace_log_path,
        timeout_seconds=config.timeout_seconds,
    )
    return execution, build_scout_agent_planner_provider_status(config, runner)


def _redact_context(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(token in normalized for token in ("secret", "token", "api_key", "password")):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = _redact_context(item)
        return redacted
    if isinstance(value, list):
        return [_redact_context(item) for item in value]
    return value
