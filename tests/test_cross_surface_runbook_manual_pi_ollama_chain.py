from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK_PATH = ROOT / "docs" / "admin" / "cross-surface-ai-assistant-runbook.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"


def test_cross_surface_runbook_summarizes_manual_pi_ollama_artifact_chain() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "Milestone 10.2 Slice 10",
        "manual Pi/Ollama artifact chain",
        "docs/admin/pi-ollama-manual-verification.md",
        "pi_ollama_manual_verification.py",
        "pi_ollama_manual_verification.example.json",
        "pi_ollama_manual_verification.index.example.json",
        "pi_ollama_manual_verification_cli.py",
        "operator checklist",
        "not part of the assistant readiness gate",
    ):
        assert token in source


def test_cross_surface_runbook_keeps_manual_chain_out_of_runtime_and_readiness() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "不啟動本地模型",
        "不啟動 Ollama",
        "不呼叫 `/assistant/*`",
        "不呼叫 `/safety/*` mutation",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不寫 IncidentStore",
        "不送 outbound",
        "不控制 hardware",
        "不控制 provider",
        "read-only model interpretation",
    ):
        assert token in source


def test_spec_tracks_slice10_consolidation_and_commit_checkpoint() -> None:
    source = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "Milestone 10.2 Slice 10: Cross-Surface Runbook Consolidation",
        "manual Pi/Ollama artifact chain",
        "cross-surface runbook",
        "not part of the assistant readiness gate",
        "Milestone 10.2 Slice 11 hardware experiment assets are complete when",
        "docker-compose.pi.ai.yml",
        "tools/pi_ollama_stress.py",
        "After Milestone 10.2 Slice 11",
    ):
        assert token in source
