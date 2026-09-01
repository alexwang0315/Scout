from __future__ import annotations

import json

import pytest

from scout_runtime_safety_phase1_writer_live_qualification import (
    Phase1WriterRuntimeObservation,
    run_phase1_writer_live_qualification,
)


def _observation(**updates: object) -> Phase1WriterRuntimeObservation:
    values: dict[str, object] = {
        "observed_at": "2026-08-31T05:00:00Z",
        "host": "scout",
        "architecture": "aarch64",
        "admin_container_running": True,
        "admin_container_health": "healthy",
        "container_image_identity_sha256": "a" * 64,
        "module_present": True,
        "deployed_module_sha256": "b" * 64,
        "writer_invocation_request_symbol_present": True,
        "writer_invocation_function_present": True,
        "deployment_manifest_symbol_present": True,
        "deployment_readiness_function_present": True,
    }
    values.update(updates)
    return Phase1WriterRuntimeObservation.model_validate(values)


def test_phase1_writer_runtime_qualification_accepts_matching_deployment() -> None:
    report = run_phase1_writer_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/phase1-writer",
        observation=_observation(),
        reviewed_module_sha256="b" * 64,
    )

    assert report.status == "phase1_writer_runtime_verified"
    assert report.phase1_writer_runtime_deployed is True
    assert report.blockers == []
    assert report.production_runtime_write_performed is False
    assert report.phase1_l0_l4_state_mutated is False


def test_phase1_writer_runtime_qualification_rejects_outdated_surface() -> None:
    report = run_phase1_writer_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/phase1-writer",
        observation=_observation(
            writer_invocation_request_symbol_present=False,
            writer_invocation_function_present=False,
            deployment_manifest_symbol_present=False,
            deployment_readiness_function_present=False,
        ),
        reviewed_module_sha256="c" * 64,
    )

    encoded = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert report.status == "blocked_phase1_writer_runtime_outdated"
    assert report.phase1_writer_runtime_deployed is False
    assert report.blockers == [
        "deployed_module_hash_mismatch",
        "deployed_writer_guard_surface_missing",
        "deployed_writer_boundary_surface_missing",
    ]
    assert "credential_value" not in encoded


def test_phase1_writer_runtime_qualification_fails_when_pi_is_unhealthy() -> None:
    report = run_phase1_writer_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/phase1-writer",
        observation=_observation(admin_container_health="unhealthy"),
        reviewed_module_sha256="b" * 64,
    )

    assert report.status == "blocked_pi_runtime_unavailable"
    assert report.pi_runtime_observed is False


def test_phase1_writer_runtime_observation_rejects_sensitive_payload_flags() -> None:
    with pytest.raises(ValueError, match="sensitive data"):
        _observation(credential_material_embedded=True)
