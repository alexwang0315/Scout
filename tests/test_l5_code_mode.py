from __future__ import annotations

from scout.schemas.l5_code_mode import (
    L5ActivationRequest,
    L5ActivationState,
    L5SafetyLevel,
)
from scout.services.l5_code_mode import (
    L5CodeModeRuntimeUnavailable,
    L5CodeModePolicy,
    L5_CODE_MODE_MAX_RETRIES,
    build_l5_code_mode_capability,
    detect_l5_code_mode_runtime,
    resolve_l5_under_construction,
    validate_l5_project_root,
)
from scout.services.permission_gate import PermissionGate
import pytest
from pydantic import ValidationError


def test_under_construction_makes_l5_code_mode_available_without_human_approval() -> None:
    decision = L5CodeModePolicy().evaluate(
        L5ActivationRequest(
            under_construction=True,
            safety_level=L5SafetyLevel.NORMAL,
            critical_capability_gap=False,
            sandbox_available=False,
            resource_budget_available=False,
            expected_information_value=0.0,
            system_assessment=False,
        )
    )

    assert decision.l5_code_mode is True
    assert decision.state is L5ActivationState.ENABLED_UNDER_CONSTRUCTION
    assert decision.requires_human_approval is False
    assert decision.human_can_activate_l5 is False
    assert decision.model_can_activate_l5 is False
    assert decision.boundary.workspace_read_allowed is True
    assert decision.boundary.host_shell_allowed is False
    assert decision.boundary.workspace_write_allowed is False
    assert decision.boundary.unrestricted_network_allowed is False
    assert decision.boundary.secret_access_allowed is False
    assert decision.boundary.hardware_control_allowed is False
    assert decision.boundary.direct_outbound_send_allowed is False
    assert decision.boundary.runtime_safety_truth_mutation_allowed is False


def test_system_can_activate_production_l5_from_l3_with_critical_gap() -> None:
    decision = L5CodeModePolicy(under_construction=False).evaluate(
        L5ActivationRequest(
            under_construction=False,
            safety_level=L5SafetyLevel.DISTRESS,
            critical_capability_gap=True,
            sandbox_available=True,
            resource_budget_available=True,
            expected_information_value=0.8,
            system_assessment=True,
        )
    )

    assert decision.l5_code_mode is True
    assert decision.state is L5ActivationState.ENABLED_SYSTEM
    assert decision.blockers == []
    assert decision.requires_human_approval is False


def test_human_request_alone_cannot_activate_production_l5() -> None:
    decision = L5CodeModePolicy(under_construction=False).evaluate(
        L5ActivationRequest(
            under_construction=False,
            safety_level=L5SafetyLevel.EMERGENCY,
            critical_capability_gap=True,
            sandbox_available=True,
            resource_budget_available=True,
            expected_information_value=1.0,
            system_assessment=False,
            human_requested=True,
        )
    )

    assert decision.l5_code_mode is False
    assert decision.state is L5ActivationState.BLOCKED
    assert "system_assessment_required" in decision.blockers
    assert decision.human_can_activate_l5 is False


def test_production_l5_requires_all_deterministic_prerequisites() -> None:
    decision = L5CodeModePolicy(under_construction=False).evaluate(
        L5ActivationRequest(
            under_construction=False,
            safety_level=L5SafetyLevel.CONCERN,
            critical_capability_gap=False,
            sandbox_available=False,
            resource_budget_available=False,
            expected_information_value=0.2,
            system_assessment=True,
        )
    )

    assert decision.l5_code_mode is False
    assert decision.state is L5ActivationState.BLOCKED
    assert set(decision.blockers) == {
        "minimum_safety_level_l3_required",
        "critical_capability_gap_required",
        "sandbox_required",
        "resource_budget_required",
        "information_value_below_threshold",
    }


def test_runtime_detection_fails_closed_when_harness_is_not_installed() -> None:
    status = detect_l5_code_mode_runtime()

    assert status.backend == "pydantic_ai_harness.CodeMode"
    if not status.available:
        assert status.stop_condition
        assert status.install_hint


def test_under_construction_flag_has_explicit_and_environment_entry_points() -> None:
    assert resolve_l5_under_construction(explicit=True, environ={}) is True
    assert resolve_l5_under_construction(explicit=False, environ={}) is False
    assert (
        resolve_l5_under_construction(
            environ={"SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION": "true"}
        )
        is True
    )
    assert resolve_l5_under_construction(environ={}) is False


def test_missing_harness_never_falls_back_to_host_execution(tmp_path) -> None:
    status = detect_l5_code_mode_runtime()
    if status.available:
        pytest.skip("Harness runtime is installed in this environment")
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.json").write_text(
        '{"project_id":"project"}', encoding="utf-8"
    )

    with pytest.raises(L5CodeModeRuntimeUnavailable, match="Do not fall back"):
        build_l5_code_mode_capability(
            project_root=project,
            workspace_root=tmp_path,
            activation_request=L5ActivationRequest(under_construction=True),
        )


def test_l5_decision_is_immutable() -> None:
    decision = L5CodeModePolicy().evaluate(
        L5ActivationRequest(under_construction=True)
    )

    with pytest.raises(ValidationError):
        decision.l5_code_mode = False


def test_l5_project_root_must_be_a_manifest_project_inside_workspace(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "safe-project"
    project.mkdir(parents=True)
    (project / "project.json").write_text(
        '{"project_id":"safe-project"}', encoding="utf-8"
    )

    assert validate_l5_project_root(
        project_root=project,
        workspace_root=workspace,
    ) == project.resolve()
    with pytest.raises(ValueError, match="outside configured workspace"):
        validate_l5_project_root(
            project_root=tmp_path,
            workspace_root=workspace,
        )


def test_l5_factory_has_no_external_tool_selector() -> None:
    import inspect

    assert "tool_selector" not in inspect.signature(
        build_l5_code_mode_capability
    ).parameters


def test_l5_harness_retry_capacity_is_ten_when_runtime_is_available(tmp_path) -> None:
    if not detect_l5_code_mode_runtime().available:
        pytest.skip("Harness runtime is not installed in this environment")
    project = tmp_path / "project"
    project.mkdir()
    (project / "project.json").write_text(
        '{"project_id":"project"}', encoding="utf-8"
    )

    capability = build_l5_code_mode_capability(
        project_root=project,
        workspace_root=tmp_path,
        activation_request=L5ActivationRequest(under_construction=True),
    )

    assert L5_CODE_MODE_MAX_RETRIES == 10
    assert capability.max_retries == 10


def test_permission_gate_exposes_the_same_under_construction_contract() -> None:
    decision = PermissionGate().evaluate_l5_code_mode(
        L5ActivationRequest(under_construction=True)
    )

    assert decision.l5_code_mode is True
    assert decision.state is L5ActivationState.ENABLED_UNDER_CONSTRUCTION


def test_permission_gate_honors_process_under_construction_flag(monkeypatch) -> None:
    monkeypatch.setenv("SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION", "true")

    decision = PermissionGate().evaluate_l5_code_mode(L5ActivationRequest())

    assert decision.l5_code_mode is True
    assert decision.state is L5ActivationState.ENABLED_UNDER_CONSTRUCTION
