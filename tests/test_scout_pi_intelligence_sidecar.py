from __future__ import annotations

from pathlib import Path

import yaml

from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig
from scout.nextgen.model_runtime import ModelRuntimeCapability
from scout.nextgen import model_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_nextgen_model_runtime_does_not_import_agent_package_facade() -> None:
    model_gateway = (ROOT / "src/scout/nextgen/model_gateway.py").read_text()
    model_qualification = (
        ROOT / "src/scout/nextgen/model_qualification.py"
    ).read_text()

    assert "scout.agents.pydantic_ai_compat" not in model_gateway
    assert "scout.agents.pydantic_ai_compat" not in model_qualification
    assert "scout.pydantic_ai_result" in model_gateway
    assert "scout.pydantic_ai_result" in model_qualification


def test_pi_intelligence_sidecar_is_isolated_and_unpublished() -> None:
    compose = yaml.safe_load(
        (ROOT / "docker-compose.pi.intelligence.yml").read_text(encoding="utf-8")
    )
    service = compose["services"]["scout-intelligence-edge"]

    assert "ports" not in service
    assert service["restart"] == "unless-stopped"
    assert service["environment"]["SCOUT_SAFETY_ENABLED"] == "false"
    assert service["command"][-2:] == [
        "--unix-socket",
        "/data/scout/run/intelligence-mcp.sock",
    ]
    assert "/data/scout/experimental/intelligence/jobs.sqlite3" in service["command"]
    assert compose["networks"]["default"]["external"] is True


def test_pi_intelligence_image_keeps_praison_out_of_dashboard_image() -> None:
    requirements = (ROOT / "requirements.pi.intelligence.txt").read_text(
        encoding="utf-8"
    )
    dashboard_requirements = (ROOT / "requirements.pi.admin.txt").read_text(
        encoding="utf-8"
    )
    dockerfile = (ROOT / "Dockerfile.pi.intelligence").read_text(encoding="utf-8")

    assert "praisonaiagents==" in requirements
    assert "praisonaiagents" not in dashboard_requirements
    assert "SCOUT_SAFETY_ENABLED=false" in dockerfile
    assert "scout.nextgen.intelligence_mcp_http_server" in dockerfile


def test_pi_intelligence_sidecar_cannot_mount_authoritative_workspace() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.pi.intelligence.yml").read_text())
    mounts = compose["services"]["scout-intelligence-edge"]["volumes"]
    assert not any(item["target"] == "/data/scout" for item in mounts)
    writable = {item["target"] for item in mounts if not item.get("read_only", False)}
    assert writable == {"/data/scout/run", "/data/scout/experimental/intelligence"}
    assert all(item.get("read_only") for item in mounts if "/config/" in item["target"])


def test_pi_intelligence_hailo_config_is_small_typed_and_single_slot() -> None:
    config = OpenAICompatibleBackendConfig.from_json_file(
        ROOT
        / "configs"
        / "scout-nextgen-openai-compatible.hailo-qwen3-1.7b.container.json"
    )
    profile = config.to_runtime_profile()

    assert config.max_concurrency == 1
    assert config.max_output_tokens is None
    assert config.specialist_output_mode == "compact_advisory"
    assert profile.capabilities.issuperset(
        {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.SMALL_TYPED_OUTPUT,
            ModelRuntimeCapability.OFFLINE,
        }
    )
    assert ModelRuntimeCapability.STRUCTURED_OUTPUT not in profile.capabilities


def test_container_host_model_mount_attests_raspberry_pi(
    tmp_path: Path,
    monkeypatch,
) -> None:
    host_model = tmp_path / "model"
    host_model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.1\x00")
    monkeypatch.setattr(model_runtime, "_HOST_MODEL_PATHS", (host_model,))

    assert model_runtime.detect_model_runtime_host_kind().value == "raspberry_pi"


def test_pi_intelligence_files_are_in_docker_build_context() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "!Dockerfile.pi.intelligence" in dockerignore
    assert "!requirements.pi.intelligence.txt" in dockerignore
    assert "!src/scout/**" in dockerignore


def test_pi_smoke_requires_real_candidate_and_model_execution() -> None:
    smoke = (
        ROOT / "tools/scout_ai_praison_background_mcp_smoke.py"
    ).read_text(encoding="utf-8")

    assert "successful_candidate" in smoke
    assert "finding_count > 0" in smoke
    assert "evidence_count > 0" in smoke
    assert "model_request_count > 0" in smoke
    assert '"praison_runtime_unavailable" not in uncertainty_ids' in smoke
