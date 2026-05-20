from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_runtime_dockerfile_is_separate_from_step1_and_includes_live_modules() -> None:
    source = read("Dockerfile.pi.live")
    step1 = read("Dockerfile.pi")

    assert "SCOUT_RUNTIME_PROFILE=pi-field-live" in source
    assert "SCOUT_ENABLE_LIVE_RUNTIME=1" in source
    assert "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED=1" in source
    assert "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai" in source
    assert "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE=/data/scout/secrets/hardware-provider-control-token" in source
    for module in (
        "live_runtime_enablement.py",
        "live_runtime_enablement_cli.py",
        "runtime_stream_transport_api.py",
        "runtime_remote_provider_live_adapter.py",
        "runtime_remote_provider_live_send_cli.py",
        "assistant_pydantic_provider.py",
        "server_safety_observation_admission_config.py",
    ):
        assert f"    {module} \\" in source or f"    {module} " in source

    assert "SCOUT_ENABLE_LIVE_RUNTIME=1" not in step1
    assert "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai" not in step1


def test_live_runtime_compose_requires_operator_secret_files_without_values() -> None:
    source = read("docker-compose.pi.live.yml")

    for token in (
        "dockerfile: Dockerfile.pi.live",
        "image: scout-fusion/pi-runtime:live",
        "SCOUT_RUNTIME_PROFILE: pi-field-live",
        "SCOUT_RUNTIME_STREAM_STATUS_ENABLED: \"1\"",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE: /data/scout/secrets/runtime-stream-admission-secret",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH: /data/scout/config/assistant-models.json",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH: /data/scout/config/hardware-provider-control-policy.json",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE: /data/scout/secrets/hardware-provider-control-token",
    ):
        assert token in source

    for forbidden in (
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET:",
        "SCOUT_REMOTE_WEBHOOK_TOKEN:",
        "SCOUT_CLOUD_MODEL_TOKEN:",
        "hardware-control-token-value",
        "love0315",
    ):
        assert forbidden not in source


def test_live_runtime_requirements_are_not_added_to_step1_runtime_core() -> None:
    live_requirements = read("requirements.pi.live.txt")
    step1_requirements = read("requirements.pi.txt")

    assert "pydantic-ai==1.88.0" in live_requirements
    assert "pydantic-ai" not in step1_requirements
    assert "ollama" not in live_requirements.lower()
