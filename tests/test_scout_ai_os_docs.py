from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_scout_ai_os_docs_reflect_phase_9_completion() -> None:
    for relative_path in [
        "docs/IMPLEMENTATION_PLAN.md",
        "docs/ARCHITECTURE.md",
        "docs/API.md",
        "docs/SECURITY_MODEL.md",
        "docs/SCOUT_AI_OS_HARDWARE_SMOKE.md",
        "README.md",
    ]:
        source = read(relative_path)
        assert (
            "Phase 9" in source
            or "Phase 0-9" in source
            or "Hardware Smoke Profile" in source
        ), relative_path


def test_scout_ai_os_docs_preserve_mvp_safety_limits() -> None:
    combined = "\n".join(
        [
            read("AGENTS.md"),
            read("docs/SECURITY_MODEL.md"),
            read("README.md"),
        ]
    )

    required = [
        "no production-grade sandbox isolation",
        "no mutation of Scout Phase 1 L0-L4 safety truth",
        "let generated code access unrestricted host shell, network, secrets",
        "external notification",
        "scout-ai-os-hardware-smoke",
    ]
    for token in required:
        assert token in combined
