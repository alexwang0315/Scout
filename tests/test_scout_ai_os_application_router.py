from __future__ import annotations

from scout.services.application_router import (
    ROUTE_READINESS_TOOL_ID,
    UI_ACTION_ARTIFACT_VERSION,
    UI_ACTION_TOOL_ID,
    ApplicationRouter,
    RequestRoute,
)
from scout.ui_action_plan import list_scout_ui_action_prompts


def test_router_sends_ui_operation_to_action_plan_bridge() -> None:
    routed = ApplicationRouter().route(
        "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
        active_context={"surface": "pretrip"},
    )

    assert routed.route_class is RequestRoute.UI_OPERATION
    assert routed.tool_id == UI_ACTION_TOOL_ID
    assert routed.output_artifact_version == UI_ACTION_ARTIFACT_VERSION
    assert routed.artifact is not None
    assert routed.artifact["status"] == "planned"
    assert routed.artifact["actions"][0]["action_kind"] == "set_layer_preset"
    assert routed.permission is not None
    assert routed.permission.allowed is True
    assert routed.permission.requires_user_approval is False


def test_router_keeps_all_twenty_ui_prompts_on_bridge_contract() -> None:
    corpus = list_scout_ui_action_prompts()

    for prompt in corpus["prompts"]:
        routed = ApplicationRouter().route(
            prompt["prompt_zh"],
            active_context={"surface": prompt["surface"]},
        )

        assert routed.route_class is RequestRoute.UI_OPERATION, prompt
        assert routed.artifact is not None
        assert routed.artifact["artifact_version"] == UI_ACTION_ARTIFACT_VERSION
        assert routed.artifact["status"] == "planned"
        assert routed.permission is not None
        assert routed.permission.allowed is True
        assert routed.permission.requires_user_approval is bool(
            prompt.get("requires_confirmation")
        )


def test_router_refuses_safety_outbound_and_hardware_route() -> None:
    routed = ApplicationRouter().route(
        "請直接觸發 Ln 並發送 SOS",
        active_context={"surface": "debug"},
    )

    assert routed.route_class is RequestRoute.BOUNDARY_EXPLAINER
    assert routed.tool_id == UI_ACTION_TOOL_ID
    assert routed.artifact is not None
    assert routed.artifact["status"] == "unsupported"
    assert routed.permission is not None
    assert routed.permission.allowed is False


def test_router_contracts_route_readiness_and_workflow_requests() -> None:
    readiness = ApplicationRouter().route("我現在是不是偏離路線？")
    workflow = ApplicationRouter().route("Remind me in 10 minutes.")

    assert readiness.route_class is RequestRoute.ROUTE_READINESS
    assert readiness.tool_id == ROUTE_READINESS_TOOL_ID
    assert workflow.route_class is RequestRoute.WORKFLOW_AUTOMATION
