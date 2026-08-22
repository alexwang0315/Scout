from __future__ import annotations

import re
from pathlib import Path

from assistant_model_config import load_assistant_model_config
from live_runtime_enablement import load_hardware_provider_control_policy


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_PATH = ROOT / "docs/admin/scout-live-runtime-operator-runbook.md"
LIVE_FIXTURE_ROOT = ROOT / "tests/fixtures/live_runtime"


def read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_live_runtime_operator_runbook_is_chinese_first_and_names_approved_gates() -> None:
    source = read_runbook()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)

    assert len(cjk_chars) > 380
    for token in (
        "這份 runbook 是 live runtime enablement 的人工部署指南",
        "live runtime stream transport",
        "remote provider live send",
        "local model / Ollama deployed fallback",
        "hardware provider control",
        "Phase 1 deterministic safety decision 仍是權威",
        "read-only model interpretation",
    ):
        assert token in source


def test_live_runtime_operator_runbook_documents_external_config_and_secret_refs() -> None:
    source = read_runbook()

    for token in (
        "/data/scout/config/assistant-models.json",
        "/data/scout/config/hardware-provider-control-policy.json",
        "/data/scout/secrets/runtime-stream-admission-secret",
        "/data/scout/secrets/hardware-provider-control-token",
        "/data/scout/secrets/live-runtime.env",
        "SCOUT_CLOUD_MODEL_TOKEN",
        "SCOUT_REMOTE_PROVIDER_KIND=telegram_bot",
        "SCOUT_TELEGRAM_BOT_TOKEN",
        "SCOUT_TELEGRAM_TARGET_CHAT_ID",
        "SCOUT_REMOTE_WEBHOOK_URL",
        "SCOUT_REMOTE_WEBHOOK_TOKEN",
        "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
        "SCOUT_REMOTE_PRIMARY_TARGET_REF",
        "SCOUT_REMOTE_BACKUP_TARGET_REF",
        "token_id",
        "不是真 token 值",
    ):
        assert token in source


def test_live_runtime_operator_runbook_documents_startup_fallback_and_validation() -> None:
    source = read_runbook()

    for token in (
        "active_profile=cloud",
        "connect_on_startup=true",
        "fallback_to_local_on_error=true",
        "local_fallback_fixed_schema=false",
        "startup_connection_status",
        "connected:cloud",
        "connected:local",
        "token_values_exposed=false",
        "docker compose -f docker-compose.pi.live.yml build scout-live",
        "docker compose -f docker-compose.pi.live.yml up -d scout-live",
        "curl --max-time 5 http://127.0.0.1:9099/assistant/status",
        "--env-file /data/scout/secrets/live-runtime.env",
        "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED=1",
        "runtime_stream_signed_sample_client.py",
        "signed-http-push.dry-run.json",
        "signed-http-push.sent.json",
        "response_admission_status=admitted_not_forwarded",
        "raw_payloads_embedded=false",
    ):
        assert token in source


def test_live_runtime_operator_runbook_preserves_phase_boundaries_and_rollback() -> None:
    source = read_runbook()

    for token in (
        "不允許任意 shell",
        "不呼叫 `/safety/*` mutation",
        "不送 outbound",
        "不讓 assistant 自動控制硬體",
        "hardware_driver_invoked=false",
        "no Phase 1 incident bridge auto-enable",
        "no Phase 2 Brain writeback",
        "docker compose -f docker-compose.pi.live.yml down",
        "cd /home/alexwang0315/scout-fusion-live",
        "cd /home/alexwang0315/scout-fusion-runtime",
        "docker compose -f docker-compose.pi.yml up -d scout",
        "GET /health` on `9099` returns `runtime_profile=pi-field`",
        "/data/scout/deployments/live-cutover-20260520T100435Z",
        "scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z",
        "do not execute rollback during a documentation-only drill",
        "stop `scout-pi-runtime-live` before starting `scout-pi-runtime`",
        "SCOUT_ENABLE_LIVE_HARDWARE=0",
        "SCOUT_ENABLE_AI_INFERENCE=0",
        "SCOUT_ENABLE_LOCAL_MODEL=0",
    ):
        assert token in source


def test_live_runtime_example_assistant_model_config_parses_and_uses_secret_refs() -> None:
    config_path = LIVE_FIXTURE_ROOT / "assistant-models.example.json"
    config = load_assistant_model_config(config_path)
    serialized = config_path.read_text(encoding="utf-8")

    assert config.active_profile == "cloud"
    assert config.cloud_model.profile == "cloud"
    assert config.cloud_model.token_env_var == "SCOUT_CLOUD_MODEL_TOKEN"
    assert config.cloud_model.token_id == "operator-managed-cloud-token"
    assert config.local_model.profile == "local"
    assert config.local_model.base_url == "http://host.docker.internal:11434/v1"
    assert config.connect_on_startup is True
    assert config.fallback_to_local_on_error is True
    assert config.local_fallback_fixed_schema is False
    assert "<operator" not in serialized
    assert "love0315" not in serialized


def test_live_runtime_example_hardware_policy_parses_without_secret_values() -> None:
    policy_path = LIVE_FIXTURE_ROOT / "hardware-provider-control-policy.example.json"
    policy = load_hardware_provider_control_policy(policy_path)
    serialized = policy_path.read_text(encoding="utf-8")

    assert policy.policy_id == "hardware_control_policy.pi5_live.v0"
    assert "provider.gnss.live.v0" in policy.allowed_provider_refs
    assert "read_provider_status" in [action.value for action in policy.allowed_actions]
    assert policy.operator_authorization_required is True
    assert policy.arbitrary_shell_allowed is False
    assert policy.safety_mutation_allowed is False
    assert policy.phase1_safety_decision_mutation_allowed is False
    assert policy.outbound_send_allowed is False
    assert policy.token_values_embedded is False
    assert "<operator" not in serialized
    assert "love0315" not in serialized


def test_live_runtime_operator_env_example_uses_file_refs_without_raw_secrets() -> None:
    source = (LIVE_FIXTURE_ROOT / "operator-env.example").read_text(encoding="utf-8")

    for token in (
        "SCOUT_RUNTIME_PROFILE=pi-field-live",
        "SCOUT_ENABLE_LIVE_RUNTIME=1",
        "SCOUT_RUNTIME_STREAM_TRANSPORT_ENABLED=1",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE=/data/scout/secrets/runtime-stream-admission-secret",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH=/data/scout/config/assistant-models.json",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE=/data/scout/secrets/hardware-provider-control-token",
    ):
        assert token in source

    for forbidden in (
        "SCOUT_CLOUD_MODEL_TOKEN=",
        "SCOUT_REMOTE_WEBHOOK_TOKEN=",
        "SCOUT_REMOTE_WEBHOOK_URL=",
        "love0315",
        "<operator",
    ):
        assert forbidden not in source
