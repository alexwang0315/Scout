from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DockerBuildDryRunBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run_only: bool = True
    docker_build_executed: bool = False
    container_started: bool = False
    network_calls_performed: bool = False
    local_model_start_allowed: bool = False
    event_bus_start_allowed: bool = False


class DockerBuildDryRunCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_file_count: int
    blocker_count: int
    warning_count: int


class DockerBuildDryRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["scout_pi_docker_build_dry_run_report"]
    status: Literal["ready_for_manual_docker_build", "blocked"]
    blockers: list[str]
    warnings: list[str]
    boundary: DockerBuildDryRunBoundary
    counts: DockerBuildDryRunCounts


def build_docker_build_dry_run_report(repo_root: Path | str = ".") -> DockerBuildDryRunReport:
    root = Path(repo_root)
    files = {
        "Dockerfile.pi": _read(root / "Dockerfile.pi"),
        "docker-compose.pi.yml": _read(root / "docker-compose.pi.yml"),
        ".dockerignore": _read(root / ".dockerignore"),
        "requirements.pi.txt": _read(root / "requirements.pi.txt"),
    }
    blockers = _blockers(files)
    warnings = ["manual_operator_must_run_docker_build"] if not blockers else []
    return DockerBuildDryRunReport(
        artifact_kind="scout_pi_docker_build_dry_run_report",
        status="blocked" if blockers else "ready_for_manual_docker_build",
        blockers=blockers,
        warnings=warnings,
        boundary=DockerBuildDryRunBoundary(),
        counts=DockerBuildDryRunCounts(
            checked_file_count=len(files),
            blocker_count=len(blockers),
            warning_count=len(warnings),
        ),
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _blockers(files: dict[str, str]) -> list[str]:
    blockers: list[str] = []
    dockerfile = files["Dockerfile.pi"]
    compose = files["docker-compose.pi.yml"]
    dockerignore = files[".dockerignore"]
    requirements = files["requirements.pi.txt"].lower()
    combined = "\n".join(files.values()).lower()

    required_tokens = {
        "dockerfile_arm64": "ARG TARGETPLATFORM=linux/arm64" in dockerfile,
        "compose_arm64": "platform: linux/arm64" in compose,
        "data_root": "SCOUT_DATA_ROOT=/data/scout" in dockerfile
        and "SCOUT_DATA_ROOT: /data/scout" in compose,
        "runtime_profile": "SCOUT_RUNTIME_PROFILE=pi-field" in dockerfile
        and "SCOUT_RUNTIME_PROFILE: pi-field" in compose,
        "live_hardware_off": "SCOUT_ENABLE_LIVE_HARDWARE=0" in dockerfile
        and 'SCOUT_ENABLE_LIVE_HARDWARE: "0"' in compose,
        "ai_off": "SCOUT_ENABLE_AI_INFERENCE=0" in dockerfile
        and 'SCOUT_ENABLE_AI_INFERENCE: "0"' in compose,
        "local_model_off": "SCOUT_ENABLE_LOCAL_MODEL=0" in dockerfile
        and 'SCOUT_ENABLE_LOCAL_MODEL: "0"' in compose,
        "event_bus_none": "SCOUT_EVENT_BUS=none" in dockerfile
        and "SCOUT_EVENT_BUS: none" in compose,
        "allowlist_context": dockerignore.splitlines()[0] == "*",
    }
    blockers.extend(key for key, ok in required_tokens.items() if not ok)

    forbidden_terms = ("ollama", "docker-compose.pi.ai.yml", "mqtt", "nats", "k3s", "coral", "jetson")
    blockers.extend(f"forbidden_term:{term}" for term in forbidden_terms if term in combined)
    model_packages = ("torch", "tensorflow", "transformers", "uvicorn[standard]")
    blockers.extend(f"forbidden_requirement:{term}" for term in model_packages if term in requirements)
    return blockers
