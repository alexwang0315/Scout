import ast
import fnmatch
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase4_admin_docker_context_includes_runtime_import_closure() -> None:
    source = read("Dockerfile.pi.admin")
    dockerignore = read(".dockerignore")

    logical_lines: list[str] = []
    buffered = ""
    for raw_line in source.splitlines():
        buffered = f"{buffered} {raw_line.strip()}".strip()
        if buffered.endswith("\\"):
            buffered = buffered[:-1].rstrip()
            continue
        logical_lines.append(buffered)
        buffered = ""

    copy_patterns: list[str] = []
    for line in logical_lines:
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)[1:]
        while parts and parts[0].startswith("--"):
            parts.pop(0)
        copy_patterns.extend(parts[:-1])

    root_modules = {path.stem: path for path in ROOT.glob("*.py")}
    copied_files = {
        path.name
        for path in root_modules.values()
        if any(
            "/" not in pattern and fnmatch.fnmatch(path.name, pattern)
            for pattern in copy_patterns
        )
    }
    context_patterns = [
        line[1:].strip()
        for line in dockerignore.splitlines()
        if line.startswith("!")
    ]

    closure: set[str] = set()
    pending = ["phase4_admin_runtime"]
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited or module not in root_modules:
            continue
        visited.add(module)
        path = root_modules[module]
        closure.add(path.name)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(
                    alias.name.split(".")[0] for alias in node.names
                )
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
            ):
                imported_modules.add(node.module.split(".")[0])
        pending.extend(sorted(imported_modules - visited))

    missing_copy = sorted(closure - copied_files)
    missing_context = sorted(
        filename
        for filename in closure
        if not any(fnmatch.fnmatch(filename, pattern) for pattern in context_patterns)
    )
    assert missing_copy == [], f"admin Dockerfile misses imports: {missing_copy}"
    assert missing_context == [], f"admin build context misses imports: {missing_context}"

    assert 'python -c "import phase4_admin_runtime"' in source


def test_live_runtime_dockerfile_is_separate_from_step1_and_includes_live_modules() -> None:
    source = read("Dockerfile.pi.live")
    step1 = read("Dockerfile.pi")

    assert "SCOUT_RUNTIME_PROFILE=pi-field-live" in source
    assert "SCOUT_ENABLE_LIVE_RUNTIME=1" in source
    assert "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED=1" in source
    assert "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai" in source
    assert "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE=/data/scout/secrets/hardware-provider-control-token" in source
    for module in (
        "admin_after_action.py",
        "admin_map_layers.py",
        "admin_tile_cache_builder.py",
        "live_runtime_enablement.py",
        "live_runtime_enablement_cli.py",
        "live_runtime_soak_check.py",
        "runtime_debug_models.py",
        "runtime_stream_transport_api.py",
        "runtime_stream_signed_sample_client.py",
        "runtime_remote_provider_live_adapter.py",
        "runtime_remote_provider_live_send_cli.py",
        "assistant_pydantic_provider.py",
        "server_safety_observation_admission_config.py",
    ):
        assert f"    {module} \\" in source or f"    {module} " in source

    assert "SCOUT_ENABLE_LIVE_RUNTIME=1" not in step1
    assert "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai" not in step1
    assert 'RUN python -c "import scout_pi_runtime"' in source
    assert "!runtime_stream_signed_sample_client.py" in read(".dockerignore")
    assert "!live_runtime_soak_check.py" in read(".dockerignore")


def test_live_runtime_compose_requires_operator_secret_files_without_values() -> None:
    source = read("docker-compose.pi.live.yml")

    for token in (
        "dockerfile: Dockerfile.pi.live",
        "image: scout-fusion/pi-runtime:live",
        "env_file:",
        "- /data/scout/secrets/live-runtime.env",
        "SCOUT_RUNTIME_PROFILE: pi-field-live",
        "SCOUT_RUNTIME_STREAM_STATUS_ENABLED: \"1\"",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE: /data/scout/secrets/runtime-stream-admission-secret",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH: /data/scout/config/assistant-models.json",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH: /data/scout/config/hardware-provider-control-policy.json",
        "SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE: /data/scout/secrets/hardware-provider-control-token",
        "host.docker.internal:host-gateway",
    ):
        assert token in source

    for forbidden in (
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET:",
        "SCOUT_REMOTE_WEBHOOK_TOKEN:",
        "SCOUT_CLOUD_MODEL_TOKEN:",
        "hardware-control-token-value",
        "love0315",
        "OPENROUTER_API_KEY",
    ):
        assert forbidden not in source


def test_live_runtime_requirements_are_not_added_to_step1_runtime_core() -> None:
    live_requirements = read("requirements.pi.live.txt")
    step1_requirements = read("requirements.pi.txt")

    assert (
        "pydantic-ai-slim[duckduckgo,mcp,openai,openrouter]==2.33.0"
        in live_requirements
    )
    assert "pydantic-ai==1.88.0" not in live_requirements
    assert "pydantic-ai" not in step1_requirements
    assert "ollama" not in live_requirements.lower()
