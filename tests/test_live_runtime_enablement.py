from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from live_runtime_enablement import (
    HardwareProviderControlPolicy,
    LiveRuntimeGate,
    build_live_runtime_enablement_report,
)


def test_live_runtime_enablement_blocks_all_gates_without_required_secrets_or_policy() -> None:
    report = build_live_runtime_enablement_report(
        {},
        requested_gates=set(LiveRuntimeGate),
    )
    payload = report.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert report.status == "live_enablement_blocked"
    assert report.ready is False
    assert set(report.requested_gates) == {gate.value for gate in LiveRuntimeGate}
    assert "missing_runtime_stream_admission_secret" in report.blocker_reasons
    assert "missing_remote_provider_secret_refs" in report.blocker_reasons
    assert "missing_assistant_model_config" in report.blocker_reasons
    assert "missing_hardware_control_policy" in report.blocker_reasons
    assert payload["boundary"]["secret_values_embedded"] is False
    assert payload["boundary"]["network_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert "super-secret" not in serialized


def test_live_runtime_enablement_ready_with_explicit_refs_config_and_policy(tmp_path: Path) -> None:
    assistant_config = tmp_path / "assistant-models.json"
    assistant_config.write_text(
        json.dumps(
            {
                "active_profile": "cloud",
                "cloud_model": {
                    "profile": "cloud",
                    "model_name": "gpt-4.1-mini",
                    "base_url": "https://api.openai.com/v1",
                    "token_env_var": "SCOUT_CLOUD_MODEL_TOKEN",
                },
                "local_model": {
                    "profile": "local",
                    "model_name": "qwen2.5:0.5b",
                    "base_url": "http://scout-ollama:11434/v1",
                },
                "connect_on_startup": True,
                "fallback_to_local_on_error": True,
                "local_fallback_fixed_schema": True,
            }
        ),
        encoding="utf-8",
    )
    hardware_policy = tmp_path / "hardware-control-policy.json"
    hardware_policy.write_text(
        HardwareProviderControlPolicy(
            policy_id="hardware_control_policy.pi5_live.v0",
            allowed_provider_refs=["provider.gnss.live.v0"],
            allowed_actions=["read_provider_status", "set_device_mode"],
        ).to_json(),
        encoding="utf-8",
    )
    env = {
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "super-secret-admission-value",
        "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
        "SCOUT_REMOTE_WEBHOOK_TOKEN": "super-secret-provider-token",
        "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "super-secret-hmac",
        "SCOUT_REMOTE_PRIMARY_TARGET_REF": "primary-target-secret",
        "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup-target-secret",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(assistant_config),
        "SCOUT_CLOUD_MODEL_TOKEN": "super-secret-cloud-token",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH": str(hardware_policy),
        "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN": "super-secret-hardware-control-token",
    }

    report = build_live_runtime_enablement_report(
        env,
        requested_gates=set(LiveRuntimeGate),
    )
    payload = report.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert report.status == "live_enablement_ready"
    assert report.ready is True
    assert report.blocker_reasons == []
    assert payload["env_overlay"]["SCOUT_RUNTIME_PROFILE"] == "pi-field-live"
    assert payload["env_overlay"]["SCOUT_RUNTIME_STREAM_STATUS_ENABLED"] == "1"
    assert payload["env_overlay"]["SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED"] == "1"
    assert payload["env_overlay"]["SCOUT_AI_ASSISTANT_PROVIDER"] == "pydantic_ai"
    assert payload["env_overlay"]["SCOUT_ENABLE_LOCAL_MODEL"] == "1"
    assert payload["env_overlay"]["SCOUT_REMOTE_PROVIDER_LIVE_SEND_ENABLED"] == "1"
    assert payload["env_overlay"]["SCOUT_ENABLE_LIVE_HARDWARE"] == "1"
    assert "env:SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET" in report.required_secret_refs
    assert "env:SCOUT_REMOTE_WEBHOOK_URL" in report.required_secret_refs
    assert "env:SCOUT_CLOUD_MODEL_TOKEN" in report.required_secret_refs
    assert "env:SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN" in report.required_secret_refs
    assert report.hardware_control_policy_id == "hardware_control_policy.pi5_live.v0"
    assert report.local_model_base_url_configured is True
    assert "super-secret-admission-value" not in serialized
    assert "super-secret-provider-token" not in serialized
    assert "super-secret-cloud-token" not in serialized
    assert "super-secret-hardware-control-token" not in serialized
    assert "primary-target-secret" not in serialized


def test_hardware_provider_control_policy_rejects_arbitrary_shell_and_safety_mutation() -> None:
    with pytest.raises(ValidationError):
        HardwareProviderControlPolicy(
            policy_id="bad.hardware.policy",
            allowed_provider_refs=["provider.gnss.live.v0"],
            allowed_actions=["arbitrary_shell"],
        )

    with pytest.raises(ValidationError):
        HardwareProviderControlPolicy(
            policy_id="bad.hardware.policy",
            allowed_provider_refs=["provider.gnss.live.v0"],
            allowed_actions=["read_provider_status"],
            safety_mutation_allowed=True,
        )


def test_live_runtime_enablement_accepts_hardware_control_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "hardware-control-token"
    token_file.write_text("secret-value-not-in-path\n", encoding="utf-8")
    hardware_policy = tmp_path / "hardware-control-policy.json"
    hardware_policy.write_text(
        HardwareProviderControlPolicy(
            policy_id="hardware_control_policy.pi5_live.v0",
            allowed_provider_refs=["provider.gnss.live.v0"],
            allowed_actions=["read_provider_status"],
        ).to_json(),
        encoding="utf-8",
    )

    report = build_live_runtime_enablement_report(
        {
            "SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH": str(hardware_policy),
            "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE": str(token_file),
        },
        requested_gates={LiveRuntimeGate.HARDWARE_PROVIDER_CONTROL},
    )
    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)

    assert report.status == "live_enablement_ready"
    assert f"file:{token_file}" in report.required_secret_refs
    assert report.missing_secret_refs == []
    assert "secret-value-not-in-path" not in serialized
