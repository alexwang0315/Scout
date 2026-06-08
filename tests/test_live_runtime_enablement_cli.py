from __future__ import annotations

import json
from pathlib import Path

from live_runtime_enablement import HardwareProviderControlPolicy
from live_runtime_enablement_cli import run_live_runtime_enablement_cli


def test_live_runtime_enablement_cli_outputs_blocked_report_without_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_path = tmp_path / "blocked.json"
    monkeypatch.delenv("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET", raising=False)
    monkeypatch.delenv("SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE", raising=False)

    exit_code, payload = run_live_runtime_enablement_cli(
        [
            "--gate",
            "runtime_stream",
            "--output",
            str(output_path),
            "--pretty",
        ]
    )
    serialized = output_path.read_text(encoding="utf-8")

    assert exit_code == 2
    assert payload["status"] == "live_enablement_blocked"
    assert payload["boundary"]["network_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert "missing_runtime_stream_admission_secret" in payload["blocker_reasons"]
    assert "super-secret" not in serialized


def test_live_runtime_enablement_cli_accepts_env_file_refs_without_echoing_values(
    tmp_path: Path,
) -> None:
    admission_secret = tmp_path / "runtime-stream-admission-secret"
    hardware_token = tmp_path / "hardware-control-token"
    assistant_config = tmp_path / "assistant-models.json"
    hardware_policy = tmp_path / "hardware-control-policy.json"
    output_path = tmp_path / "ready.json"
    env_file = tmp_path / "operator.env"

    admission_secret.write_text("secret-admission-value\n", encoding="utf-8")
    hardware_token.write_text("secret-hardware-token\n", encoding="utf-8")
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
    hardware_policy.write_text(
        HardwareProviderControlPolicy(
            policy_id="hardware_control_policy.pi5_live.v0",
            allowed_provider_refs=["provider.gnss.live.v0"],
            allowed_actions=["read_provider_status"],
        ).to_json(),
        encoding="utf-8",
    )
    env_file.write_text(
        "\n".join(
            [
                f"SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE={admission_secret}",
                "SCOUT_REMOTE_WEBHOOK_URL=https://example.invalid/webhook",
                "SCOUT_REMOTE_WEBHOOK_TOKEN=secret-webhook-token",
                "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET=secret-hmac",
                "SCOUT_REMOTE_PRIMARY_TARGET_REF=secret-primary-target",
                "SCOUT_REMOTE_BACKUP_TARGET_REF=secret-backup-target",
                f"SCOUT_AI_ASSISTANT_CONFIG_PATH={assistant_config}",
                "SCOUT_CLOUD_MODEL_TOKEN=secret-cloud-token",
                f"SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH={hardware_policy}",
                f"SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE={hardware_token}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code, payload = run_live_runtime_enablement_cli(
        ["--env-file", str(env_file), "--output", str(output_path), "--pretty"]
    )
    serialized = output_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert payload["status"] == "live_enablement_ready"
    assert set(payload["ready_gates"]) == {
        "hardware_provider_control",
        "local_model_ollama_fallback",
        "remote_provider_live_send",
        "runtime_stream",
    }
    assert payload["boundary"]["secret_values_embedded"] is False
    assert payload["boundary"]["network_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    for forbidden in (
        "secret-admission-value",
        "secret-hardware-token",
        "secret-webhook-token",
        "secret-cloud-token",
        "secret-primary-target",
    ):
        assert forbidden not in serialized
