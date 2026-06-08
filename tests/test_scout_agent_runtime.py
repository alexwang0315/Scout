from __future__ import annotations

import json
from pathlib import Path

from assistant_model_config import AssistantModelConfig
from scout_agent_runtime import (
    build_agent_tool_planning_prompt,
    build_agent_tool_registry_context,
    build_scout_agent_planner_provider_status,
    create_configured_scout_agent_planner_runner,
    run_configured_scout_agent_tool_plan,
    run_pydantic_agent_tool_plan,
)
from scout_agent_trace import load_agent_trace


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"


class FakePlanningRunner:
    def __init__(self, output: dict):
        self.output = output
        self.calls = []

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        self.calls.append({"prompt": prompt, "timeout_seconds": timeout_seconds})
        return json.dumps(self.output)


class FailingPlanningRunner:
    def __init__(self, *, model_name: str):
        self.model_name = model_name

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        raise RuntimeError(f"{self.model_name} failed")


def test_tool_registry_context_is_compact_and_boundary_closed() -> None:
    context = build_agent_tool_registry_context(MANIFEST_DIR)

    assert context["tool_count"] >= 2
    assert {tool["id"] for tool in context["tools"]} >= {
        "scout.local_evidence.status",
        "scout.cp.propose_add",
        "scout.cp.propose_delete",
        "scout.cp.proposal_preview",
        "scout.imprint.trigger_dry_run",
        "scout.kb.pretrip_view_summary",
        "scout.safety_action.shelter_direction",
    }
    assert context["boundary"]["live_safety_api_calls_allowed"] is False
    assert context["boundary"]["phase1_safety_mutation_allowed"] is False


def test_pydantic_agent_tool_plan_can_call_read_and_proposal_tools(tmp_path: Path) -> None:
    evidence_request = tmp_path / "evidence.request.json"
    evidence_request.write_text(json.dumps({"trip_id": "chilai_nanhua_day1"}), encoding="utf-8")
    cp_request = tmp_path / "cp.request.json"
    cp_request.write_text(
        json.dumps(
            {
                "operation": "propose_add",
                "candidate_ref": "cp.agent_proposed.002",
                "label": "臨時避雨點",
            }
        ),
        encoding="utf-8",
    )
    trace_log = tmp_path / "agent-trace.jsonl"
    runner = FakePlanningRunner(
        {
            "artifact_kind": "scout_agent_tool_plan",
            "plan_id": "agent_plan.test.001",
            "agent_run_id": "agent_run.test.runtime",
            "user_intent": "查詢本地證據並預覽新增 CP proposal",
            "tool_calls": [
                {
                    "tool_id": "scout.local_evidence.status",
                    "action_id": "agent_action.test.read",
                    "input_path": str(evidence_request),
                    "dry_run": True,
                },
                {
                    "tool_id": "scout.cp.proposal_preview",
                    "action_id": "agent_action.test.proposal",
                    "input_path": str(cp_request),
                    "dry_run": True,
                },
            ],
        }
    )

    execution = run_pydantic_agent_tool_plan(
        runner,
        user_intent="查詢本地證據並預覽新增 CP proposal",
        manifest_dir=MANIFEST_DIR,
        trace_log_path=trace_log,
        timeout_seconds=4,
    )

    assert execution.status == "completed"
    assert execution.result_count == 2
    assert execution.completed_count == 2
    assert execution.boundary.live_safety_api_calls_allowed is False
    assert execution.tool_results[0]["tool_id"] == "scout.local_evidence.status"
    assert execution.tool_results[1]["tool_id"] == "scout.cp.proposal_preview"
    assert execution.tool_results[1]["effects"]["workspace_write_count"] == 0
    assert len(load_agent_trace(trace_log)) == 2
    prompt = runner.calls[0]["prompt"]
    assert "scout_agent_tool_plan" in prompt
    assert "scout.local_evidence.status" in prompt
    assert "scout.cp.proposal_preview" in prompt
    assert "Do not request live /safety/*" in prompt


def test_agent_tool_planning_prompt_does_not_expose_raw_secret_context() -> None:
    prompt = build_agent_tool_planning_prompt(
        user_intent="status",
        manifest_dir=MANIFEST_DIR,
        context={"token": "should-not-be-used-as-secret", "note": "fixture text"},
    )

    assert "Scout tools only" in prompt
    assert "live /safety" in prompt
    assert "api_key" not in prompt.lower()
    assert "should-not-be-used-as-secret" not in prompt
    assert "[redacted]" in prompt


def test_configured_agent_planner_falls_back_to_local_without_assistant_fixed_schema(
    tmp_path: Path,
) -> None:
    evidence_request = tmp_path / "evidence.request.json"
    evidence_request.write_text(json.dumps({"trip_id": "chilai_nanhua_day1"}), encoding="utf-8")
    trace_log = tmp_path / "agent-trace.jsonl"
    config = _agent_model_config()

    def runner_factory(profile):
        if profile.profile == "cloud":
            return FailingPlanningRunner(model_name=profile.model_name)
        return FakePlanningRunner(
            {
                "artifact_kind": "scout_agent_tool_plan",
                "plan_id": "agent_plan.failover.001",
                "agent_run_id": "agent_run.failover.001",
                "user_intent": "查詢本地證據",
                "tool_calls": [
                    {
                        "tool_id": "scout.local_evidence.status",
                        "action_id": "agent_action.failover.read",
                        "input_path": str(evidence_request),
                        "dry_run": True,
                    }
                ],
            }
        )

    execution, status = run_configured_scout_agent_tool_plan(
        config=config,
        user_intent="查詢本地證據",
        manifest_dir=MANIFEST_DIR,
        trace_log_path=trace_log,
        runner_factory=runner_factory,
        environ={"SCOUT_CLOUD_MODEL_TOKEN": "super-secret-token"},
    )

    assert execution.status == "completed"
    assert execution.completed_count == 1
    assert status.runner_profile == "local"
    assert status.failover_count == 1
    assert status.failover_reason == "primary_run_error:RuntimeError"
    assert status.local_fallback_fixed_schema_used is False
    serialized = status.model_dump_json()
    assert "super-secret-token" not in serialized
    assert "SCOUT_CLOUD_MODEL_TOKEN" in serialized
    assert len(load_agent_trace(trace_log)) == 1


def test_configured_agent_planner_status_redacts_provider_secret_values() -> None:
    config = _agent_model_config()
    runner = create_configured_scout_agent_planner_runner(
        config,
        runner_factory=lambda profile: FakePlanningRunner(
            {
                "artifact_kind": "scout_agent_tool_plan",
                "plan_id": "agent_plan.status.001",
                "agent_run_id": "agent_run.status.001",
                "user_intent": "status",
                "tool_calls": [
                    {
                        "tool_id": "scout.local_evidence.status",
                        "action_id": "agent_action.status.read",
                        "dry_run": True,
                    }
                ],
            }
        ),
        environ={"SCOUT_CLOUD_MODEL_TOKEN": "secret-cloud-value"},
    )

    status = build_scout_agent_planner_provider_status(config, runner)

    assert status.cloud_model == "cloud/test"
    assert status.local_model == "local/test"
    assert status.token_env_refs == ["SCOUT_CLOUD_MODEL_TOKEN"]
    assert "secret-cloud-value" not in status.model_dump_json()
    assert status.boundary.live_safety_api_calls_allowed is False


def _agent_model_config() -> AssistantModelConfig:
    return AssistantModelConfig.model_validate(
        {
            "active_profile": "cloud",
            "cloud_model": {
                "profile": "cloud",
                "model_name": "cloud/test",
                "token_env_var": "SCOUT_CLOUD_MODEL_TOKEN",
                "token_id": "operator-managed-cloud-token",
            },
            "local_model": {
                "profile": "local",
                "model_name": "local/test",
            },
            "timeout_seconds": 4,
            "fallback_to_local_on_error": True,
            "local_fallback_fixed_schema": True,
        }
    )
