from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RUNTIME_CORE_MODULES = {
    "checkpoint_manager.py",
    "communication_provider.py",
    "communication_tool.py",
    "environment_provider.py",
    "geo_utils.py",
    "go_no_go.py",
    "incident_package.py",
    "incident_store.py",
    "mission_graph.py",
    "mission_models.py",
    "mission_progress.py",
    "observation_adapter.py",
    "offline_map.py",
    "offline_map_models.py",
    "pdr_fallback.py",
    "phase1_incident_bridge.py",
    "phase1_phase2_adapter.py",
    "phase2_brain_ingest.py",
    "phase2_brain_models.py",
    "phase2_brain_store.py",
    "phase2_refs.py",
    "phase2_store_utils.py",
    "phase2_writeback_policy.py",
    "provider_context.py",
    "recording_policy_runtime.py",
    "replay_runner.py",
    "resource_provider.py",
    "risk_rules.py",
    "route_matching.py",
    "route_progress.py",
    "safety_api.py",
    "safety_models.py",
    "safety_runtime_session.py",
    "safety_state_machine.py",
    "scout_pi_runtime.py",
    "skill_registry_models.py",
    "skill_runtime.py",
}

REQUIRED_STEP1_ENV = {
    "SCOUT_DATA_ROOT": "/data/scout",
    "SCOUT_RUNTIME_PROFILE": "pi-field",
    "SCOUT_ENABLE_LIVE_HARDWARE": "0",
    "SCOUT_ENABLE_AI_INFERENCE": "0",
    "SCOUT_ENABLE_LOCAL_MODEL": "0",
    "SCOUT_EVENT_BUS": "none",
}

FORBIDDEN_RUNTIME_TERMS = (
    "docker-compose.pi.ai.yml",
    "ollama",
    "openai",
    "transformers",
    "torch",
    "tensorflow",
    "mqtt",
    "nats",
    "k3s",
    "coral",
    "jetson",
)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pi_dockerfile_targets_arm64_step1_runtime_core() -> None:
    source = read("Dockerfile.pi")

    assert "ARG TARGETPLATFORM=linux/arm64" in source
    assert "FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm" in source
    assert "SCOUT_SAFETY_MISSION_GRAPH=/app/tests/fixtures/mission_graph/normal_climb_mission.json" in source
    assert "SCOUT_SAFETY_INCIDENT_STORE=/data/scout/incidents" in source
    assert 'CMD ["python", "-m", "uvicorn", "scout_pi_runtime:app"' in source
    assert "COPY *.py" not in source

    for key, value in REQUIRED_STEP1_ENV.items():
        assert f"{key}={value}" in source

    for module in RUNTIME_CORE_MODULES:
        assert f"    {module} \\" in source or f"    {module} " in source


def test_pi_compose_keeps_step1_profile_without_live_hardware_ai_or_event_bus() -> None:
    source = read("docker-compose.pi.yml")

    assert "platform: linux/arm64" in source
    assert "dockerfile: Dockerfile.pi" in source
    assert "image: scout-fusion/pi-runtime:step1" in source
    assert "source: /data/scout" in source
    assert "target: /data/scout" in source
    assert "depends_on:" not in source

    for key, value in REQUIRED_STEP1_ENV.items():
        expected = f'{key}: "{value}"' if value == "0" else f"{key}: {value}"
        assert expected in source


def test_pi_docker_context_does_not_collect_dirty_worktree_or_ai_compose() -> None:
    dockerignore = read(".dockerignore")

    assert dockerignore.splitlines()[0] == "*"
    assert "!*.py" not in dockerignore
    assert "!docker-compose.pi.ai.yml" not in dockerignore
    assert "!docker-compose.pi.yml" not in dockerignore
    assert "!PdrSample/" not in dockerignore
    assert "!catographydata/" not in dockerignore

    for module in RUNTIME_CORE_MODULES:
        assert f"!{module}" in dockerignore

    for fixture in (
        "!tests/fixtures/mission_graph/normal_climb_mission.json",
        "!tests/fixtures/routes/normal_climb.gpx",
    ):
        assert fixture in dockerignore


def test_pi_requirements_stay_runtime_core_and_do_not_pull_model_or_bus_packages() -> None:
    requirements = read("requirements.pi.txt").lower()

    assert "fastapi==0.136.1" in requirements
    assert "pydantic==2.13.3" in requirements
    assert "uvicorn==0.46.0" in requirements
    assert "uvicorn[standard]" not in requirements

    for term in FORBIDDEN_RUNTIME_TERMS:
        assert term not in requirements


def test_pi_docker_artifacts_do_not_reference_future_hardware_ladder() -> None:
    combined = "\n".join(
        read(path).lower()
        for path in (
            ".dockerignore",
            "Dockerfile.pi",
            "docker-compose.pi.yml",
            "requirements.pi.txt",
        )
    )

    for term in FORBIDDEN_RUNTIME_TERMS:
        assert term not in combined
