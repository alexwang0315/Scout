from __future__ import annotations

from uuid import uuid4

from scout.nextgen.failure_qualification import (
    AUTHORITATIVE_STATE_SURFACES,
    FailureScenario,
    build_nextgen_failure_matrix,
)
from scout.nextgen.model_runtime import (
    ModelRuntimeCapability,
    ModelRuntimeRequest,
    ModelRuntimeTier,
    ScoutModelRuntimeRouter,
    default_runtime_profiles,
)


def test_failure_matrix_covers_every_required_scenario() -> None:
    matrix = build_nextgen_failure_matrix()

    assert {case.scenario for case in matrix.cases} == set(FailureScenario)
    assert len(matrix.cases) == 13
    assert all(case.probe_node_ids for case in matrix.cases)
    assert all(case.provenance_event for case in matrix.cases)
    assert matrix.candidate_only is True
    assert matrix.runtime_safety_truth is False


def test_failure_matrix_keeps_level_zero_and_authority_unchanged() -> None:
    matrix = build_nextgen_failure_matrix()

    assert all(case.scout_operational for case in matrix.cases)
    assert all(case.level_zero_available for case in matrix.cases)
    assert all(
        case.unaffected_authoritative_state == AUTHORITATIVE_STATE_SURFACES
        for case in matrix.cases
    )
    assert all(case.unknown_code for case in matrix.cases)
    assert all(case.candidate_only for case in matrix.cases)
    assert all(not case.runtime_safety_truth for case in matrix.cases)


def test_ai_hat_loss_routes_only_to_an_explicit_registered_cpu_fallback() -> None:
    available_profiles = tuple(
        profile
        for profile in default_runtime_profiles()
        if profile.runtime_id == "local.fast.function"
    )
    selection = ScoutModelRuntimeRouter(available_profiles).select(
        ModelRuntimeRequest(
            request_id=uuid4(),
            task="offline terrain summary after Hailo loss",
            required_capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                }
            ),
            allowed_tiers=frozenset(
                {
                    ModelRuntimeTier.HAILO_LOCAL,
                    ModelRuntimeTier.LOCAL_FAST,
                }
            ),
            requires_offline=True,
            privacy_sensitive=True,
            allow_cloud=False,
            max_model_requests=10,
        )
    )

    assert selection.selected is True
    assert selection.selected_runtime is not None
    assert selection.selected_runtime.runtime_id == "local.fast.function"
    assert "edge.hailo.local" not in selection.considered_runtime_ids


def test_cloud_loss_keeps_registered_local_path_available() -> None:
    available_profiles = tuple(
        profile
        for profile in default_runtime_profiles()
        if profile.runtime_id == "local.fast.function"
    )
    selection = ScoutModelRuntimeRouter(available_profiles).select(
        ModelRuntimeRequest(
            request_id=uuid4(),
            task="workspace answer while cloud is unavailable",
            required_capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                }
            ),
            allowed_tiers=frozenset(
                {
                    ModelRuntimeTier.LOCAL_FAST,
                    ModelRuntimeTier.CLOUD_REASONING,
                }
            ),
            prefer_local=False,
            allow_cloud=True,
            privacy_sensitive=True,
            max_model_requests=10,
        )
    )

    assert selection.selected is True
    assert selection.selected_runtime is not None
    assert selection.selected_runtime.runtime_id == "local.fast.function"
    assert selection.selected_runtime.offline_capable is True
