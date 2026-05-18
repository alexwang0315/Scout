from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from assistant_readiness_check import (
    ASSISTANT_FOUNDATION_PATHS,
    REQUIRED_PATHS,
    RUNBOOK_TOKENS,
    SPEC_GUARDRAILS,
    build_readiness_check,
)


ROOT = Path(__file__).resolve().parents[1]


def test_complete_minimal_milestone10_fixture_passes(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)

    result = build_readiness_check(tmp_path)

    assert result["ok"], result["missing_required_artifacts"]
    assert result["failed_checks"] == []
    assert result["checks"]["required_paths"]["missing"] == []
    assert result["checks"]["spec_guardrails"]["missing"] == []
    assert result["checks"]["assistant_foundation_static_boundaries"]["missing"] == []
    assert result["checks"]["server_opt_in_mount"]["missing"] == []
    assert result["checks"]["runbook"]["missing"] == []


@pytest.mark.parametrize(
    ("path", "forbidden_token", "expected_missing"),
    [
        (
            "assistant_provider.py",
            "requests.post('https://example.invalid')",
            "assistant_foundation_forbidden_token:assistant_provider.py:requests",
        ),
        (
            "assistant_api.py",
            "@router.delete('/assistant/query')",
            "assistant_foundation_forbidden_token:assistant_api.py:@router.delete",
        ),
        (
            "pretrip_assistant_context.py",
            "ObservedFactWriter",
            "assistant_foundation_forbidden_token:pretrip_assistant_context.py:ObservedFactWriter",
        ),
        (
            "hardware_readiness_assistant_context.py",
            "SafetyRuntimeSession",
            "assistant_foundation_forbidden_token:hardware_readiness_assistant_context.py:SafetyRuntimeSession",
        ),
    ],
)
def test_forbidden_assistant_foundation_tokens_fail_readiness(
    tmp_path: Path,
    path: str,
    forbidden_token: str,
    expected_missing: str,
) -> None:
    _write_complete_minimal_repo(tmp_path)
    _write(tmp_path / path, forbidden_token)

    result = build_readiness_check(tmp_path)

    assert result["ok"] is False
    assert expected_missing in result["checks"]["assistant_foundation_static_boundaries"]["missing"]
    assert expected_missing in result["missing_required_artifacts"]


def test_missing_spec_server_and_runbook_tokens_are_reported(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    _write(tmp_path / "docs/specs/scout-cross-surface-ai-assistant.md", "Milestone 10 only")
    _write(tmp_path / "server.py", "SCOUT_AI_ASSISTANT_ENABLED")
    _write(tmp_path / "docs/admin/cross-surface-ai-assistant-runbook.md", "mock provider")

    result = build_readiness_check(tmp_path)

    assert result["ok"] is False
    assert result["checks"]["spec_guardrails"]["missing"] == [
        f"spec_guardrail:{token}" for token in SPEC_GUARDRAILS if token != "Milestone 10"
    ]
    assert result["checks"]["server_opt_in_mount"]["missing"]
    assert result["checks"]["runbook"]["missing"] == [
        f"runbook_token:{token}" for token in RUNBOOK_TOKENS if token != "mock provider"
    ]


def test_current_runbook_covers_required_operational_tokens() -> None:
    result = build_readiness_check(ROOT)

    assert result["checks"]["runbook"]["missing"] == []


def test_cli_prints_json_and_returns_nonzero_when_repo_is_not_ready(tmp_path: Path) -> None:
    _write_complete_minimal_repo(tmp_path)
    (tmp_path / "assistant_api.py").unlink()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "assistant_readiness_check.py"),
            "--repo-root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert "assistant_api.py" in payload["missing_required_artifacts"]


def _write_complete_minimal_repo(root: Path) -> None:
    for path in REQUIRED_PATHS:
        _write(root / path, _default_content(path))

    for path in ASSISTANT_FOUNDATION_PATHS:
        _write(root / path, _default_content(path))

    _write(
        root / "docs/specs/scout-cross-surface-ai-assistant.md",
        "\n".join(SPEC_GUARDRAILS),
    )
    _write(
        root / "server.py",
        "\n".join(
            [
                "SCOUT_AI_ASSISTANT_ENABLED",
                "SCOUT_AI_ASSISTANT_PROVIDER",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH",
                "create_assistant_router",
                "create_assistant_context_resolver",
                "_include_assistant_router",
                "provider_name = os.getenv('SCOUT_AI_ASSISTANT_PROVIDER', 'mock')",
                "SCOUT_AI_ASSISTANT_CONFIG_PATH",
                "app.include_router(create_assistant_router(context_resolver=create_assistant_context_resolver()))",
            ]
        ),
    )
    _write(
        root / "docs/admin/cross-surface-ai-assistant-runbook.md",
        "\n".join(RUNBOOK_TOKENS),
    )


def _default_content(path: str) -> str:
    if path.endswith(".py"):
        return "from __future__ import annotations\n\nBOUNDARY = 'read-only model interpretation'\n"
    return "Milestone 10 readiness artifact\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
