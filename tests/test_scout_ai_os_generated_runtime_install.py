from __future__ import annotations

import pytest

from scout.schemas import (
    CapabilityRisk,
    CapabilityRuntime,
    CapabilitySpec,
    GeneratedCapabilityPackage,
)
from scout.services import (
    GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE,
    GeneratedRuntimeDispatcher,
    GeneratedRuntimeDispatchRequest,
    GeneratedRuntimeInstallApproval,
    GeneratedRuntimeInstaller,
    RuntimeIsolationProfile,
    generated_package_hash,
)


def _package(*, risk: CapabilityRisk = CapabilityRisk.LOW) -> GeneratedCapabilityPackage:
    return GeneratedCapabilityPackage(
        spec=CapabilitySpec(
            name="payload_echo",
            description="Echo a payload.",
            runtime=CapabilityRuntime.PYTHON,
            risk_level=risk,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        files={"payload_echo.py": "def run(payload):\n    return payload\n"},
        tests={
            "test_payload_echo.py": (
                "from payload_echo import run\n\n"
                "def test_echo():\n"
                "    assert run({'ok': True}) == {'ok': True}\n"
            )
        },
        install_notes="Fixture package.",
    )


def _profile(**overrides: object) -> RuntimeIsolationProfile:
    payload = {
        "profile_id": "unit-test-container",
        "kind": "container",
        "network_allowed": False,
        "read_only_root": True,
        "secrets_mounted": False,
        "host_paths_writable": False,
        "revoke_supported": True,
        "rollback_supported": True,
    }
    payload.update(overrides)
    return RuntimeIsolationProfile.model_validate(payload)


def _approval(**overrides: object) -> GeneratedRuntimeInstallApproval:
    payload = {
        "approved_by": "operator-1",
        "phrase": GENERATED_RUNTIME_INSTALL_APPROVAL_PHRASE,
        "risk_accepted": CapabilityRisk.LOW,
        "reason": "unit test",
    }
    payload.update(overrides)
    return GeneratedRuntimeInstallApproval.model_validate(payload)


def test_generated_package_hash_is_deterministic() -> None:
    assert generated_package_hash(_package()) == generated_package_hash(_package())
    assert generated_package_hash(_package()).startswith("sha256:")


def test_generated_runtime_install_blocks_insecure_isolation() -> None:
    plan = GeneratedRuntimeInstaller().verify_install_ready(
        _package(),
        isolation_profile=_profile(network_allowed=True),
        approval=_approval(),
    )

    assert plan.status == "blocked"
    assert "network_must_be_disabled" in plan.block_reasons
    assert plan.runtime_code_executed is False


def test_generated_runtime_install_blocks_non_low_risk_package() -> None:
    plan = GeneratedRuntimeInstaller().verify_install_ready(
        _package(risk=CapabilityRisk.HIGH),
        isolation_profile=_profile(),
        approval=_approval(),
    )

    assert plan.status == "blocked"
    assert "capability_risk_not_low" in plan.block_reasons


def test_generated_runtime_install_revoke_and_rollback_lifecycle() -> None:
    installer = GeneratedRuntimeInstaller()
    package = _package()

    installed = installer.install(
        package,
        isolation_profile=_profile(),
        approval=_approval(),
    )
    revoked = installer.revoke(installed.install_id)
    rolled_back = installer.rollback(installed.install_id)

    assert installed.status == "installed"
    assert installed.artifact_hash == generated_package_hash(package)
    assert installed.runtime_code_executed is False
    assert installed.active_runtime_dispatch_enabled is False
    assert revoked.status == "revoked"
    assert rolled_back.status == "rolled_back"
    assert rolled_back.rollback_of == installed.install_id


def test_generated_runtime_dispatch_proof_executes_in_isolated_boundary() -> None:
    installer = GeneratedRuntimeInstaller()
    package = _package()
    installed = installer.install(
        package,
        isolation_profile=_profile(),
        approval=_approval(),
    )

    result = GeneratedRuntimeDispatcher().dispatch_proof(
        package=package,
        install_record=installed,
        request=GeneratedRuntimeDispatchRequest(
            install_id=installed.install_id,
            capability_name=installed.capability_name,
            payload={"ok": True},
        ),
    )

    assert result.status == "completed"
    assert result.output == {"ok": True}
    assert result.runtime_code_executed is True
    assert result.proof_runtime_code_executed is True
    assert result.active_runtime_dispatch_enabled is False
    assert result.safety_api_called is False
    assert result.outbound_sent is False
    assert result.boundary["active_runtime_dispatch_enabled"] is False


def test_generated_runtime_dispatch_proof_blocks_hash_mismatch() -> None:
    installer = GeneratedRuntimeInstaller()
    package = _package()
    installed = installer.install(
        package,
        isolation_profile=_profile(),
        approval=_approval(),
    )
    changed_package = _package()
    changed_package.files["payload_echo.py"] = (
        "def run(payload):\n"
        "    return {'changed': True, 'payload': payload}\n"
    )

    result = GeneratedRuntimeDispatcher().dispatch_proof(
        package=changed_package,
        install_record=installed,
        request=GeneratedRuntimeDispatchRequest(
            install_id=installed.install_id,
            capability_name=installed.capability_name,
            payload={"ok": True},
        ),
    )

    assert result.status == "blocked"
    assert "artifact_hash_mismatch" in result.block_reasons
    assert result.runtime_code_executed is False


def test_generated_runtime_dispatch_proof_blocks_network_package() -> None:
    installer = GeneratedRuntimeInstaller()
    package = _package()
    package.files["payload_echo.py"] = (
        "import socket\n\n"
        "def run(payload):\n"
        "    return {'ok': True}\n"
    )
    installed = installer.install(
        _package(),
        isolation_profile=_profile(),
        approval=_approval(),
    ).model_copy(update={"artifact_hash": generated_package_hash(package)})

    result = GeneratedRuntimeDispatcher().dispatch_proof(
        package=package,
        install_record=installed,
        request=GeneratedRuntimeDispatchRequest(
            install_id=installed.install_id,
            capability_name=installed.capability_name,
            payload={"ok": True},
        ),
    )

    assert result.status == "blocked"
    assert "sandbox_failed" in result.block_reasons
    assert result.runtime_code_executed is False


def test_generated_runtime_install_raises_when_plan_blocked() -> None:
    with pytest.raises(ValueError, match="approval_phrase_mismatch"):
        GeneratedRuntimeInstaller().install(
            _package(),
            isolation_profile=_profile(),
            approval=_approval(phrase="install"),
        )
