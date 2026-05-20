from __future__ import annotations

import py_compile
from pathlib import Path

from assistant_readiness_check import REQUIRED_PATHS


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.pi.ai.yml"
BASE_COMPOSE_PATH = ROOT / "docker-compose.pi.yml"
STRESS_TOOL_PATH = ROOT / "tools" / "pi_ollama_stress.py"
PI_EXPERIMENT_SPEC_PATH = ROOT / "docs" / "specs" / "pi5-local-ai-runtime-experiment.md"
HARDWARE_DIRECTION_PATH = ROOT / "docs" / "specs" / "scout-hardware-direction.md"
MANUAL_VERIFICATION_DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
CROSS_SURFACE_SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"


def test_pi_ollama_compose_is_manual_profile_and_not_base_runtime() -> None:
    source = COMPOSE_PATH.read_text(encoding="utf-8")
    base_source = BASE_COMPOSE_PATH.read_text(encoding="utf-8")

    for token in (
        "profiles:",
        "ai-experimental",
        "platform: linux/arm64",
        "ollama/ollama:latest",
        "container_name: scout-ollama",
        "127.0.0.1:11434:11434",
        "source: /data/scout/models/ollama",
        "target: /root/.ollama",
    ):
        assert token in source

    assert "docker-compose.pi.ai.yml" not in REQUIRED_PATHS
    assert "scout-ollama" not in base_source
    assert "OLLAMA_HOST" not in base_source
    assert "SCOUT_ENABLE_LOCAL_MODEL: \"0\"" in base_source

    for forbidden in (
        "OPENROUTER_API_KEY",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH",
        "token_id",
        "sk-",
        "/safety/",
    ):
        assert forbidden not in source


def test_pi_ollama_stress_tool_is_compileable_manual_probe() -> None:
    py_compile.compile(str(STRESS_TOOL_PATH), doraise=True)
    source = STRESS_TOOL_PATH.read_text(encoding="utf-8")

    for token in (
        "already-running Pi/Ollama service",
        "Manual Pi/Ollama stress probe",
        "http://127.0.0.1:11434/api/generate",
        "qwen2.5:0.5b",
        "--duration-s",
        "--workers",
        "--num-predict",
        "vcgencmd",
        "/proc/loadavg",
        '"stream": False',
        "manual_hardware_experiment_no_scout_state_writes",
    ):
        assert token in source

    for forbidden in (
        "/safety/",
        "/assistant/",
        "ObservedFact",
        "BrainFileStore",
        "IncidentStore",
        "send_outbound",
        "Twilio",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH",
        "OPENROUTER_API_KEY",
        "token_id",
        "docker compose",
    ):
        assert forbidden not in source


def test_pi_ollama_docs_track_assets_without_readiness_coupling() -> None:
    pi_spec = PI_EXPERIMENT_SPEC_PATH.read_text(encoding="utf-8")
    hardware_direction = HARDWARE_DIRECTION_PATH.read_text(encoding="utf-8")
    manual_doc = MANUAL_VERIFICATION_DOC_PATH.read_text(encoding="utf-8")
    assistant_spec = CROSS_SURFACE_SPEC_PATH.read_text(encoding="utf-8")

    for source in (pi_spec, hardware_direction, manual_doc, assistant_spec):
        for token in (
            "docker-compose.pi.ai.yml",
            "tools/pi_ollama_stress.py",
            "ai-experimental",
            "not part of the assistant readiness gate",
            "不啟動本地模型",
            "不呼叫 `/safety/*` mutation",
            "read-only model interpretation",
        ):
            assert token in source

    assert "docker-compose.pi.ai.yml" not in REQUIRED_PATHS
    assert "tools/pi_ollama_stress.py" not in REQUIRED_PATHS
