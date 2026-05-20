from __future__ import annotations

import re
from pathlib import Path

from assistant_readiness_check import REQUIRED_PATHS


ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_manual_pi_ollama_verification_doc_is_chinese_first_and_manual_only() -> None:
    source = read_doc()
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", source)

    assert len(cjk_chars) > 450
    for token in (
        "Milestone 10.2 Slice 4",
        "manual Pi/Ollama verification artifact",
        "hardware prototype track",
        "not part of the assistant readiness gate",
        "不納入 assistant_readiness_check.py",
        "不啟動本地模型",
        "不啟動 Ollama",
        "read-only model interpretation",
    ):
        assert token in source


def test_manual_pi_ollama_verification_doc_includes_safe_command_shape() -> None:
    source = read_doc()

    for token in (
        "SCOUT_RUNTIME_PROFILE=pi-field",
        "SCOUT_AI_ASSISTANT_ENABLED=1",
        "SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH",
        "fallback_to_local_on_error=true",
        "curl --max-time 2 http://127.0.0.1:11434/api/tags",
        "curl --max-time 5 http://127.0.0.1:9110/assistant/status",
        "curl --max-time 10 -X POST http://127.0.0.1:9110/assistant/query",
        "operator_observed_latency_ms",
        "manual_only_pi_ollama_verification",
    ):
        assert token in source


def test_manual_pi_ollama_verification_doc_blocks_mutation_and_secret_leaks() -> None:
    source = read_doc()

    for token in (
        "不呼叫 `/safety/*` mutation",
        "不改 Phase 1 safety decision",
        "不寫 ObservedFact",
        "不寫 Phase 2 Brain",
        "不寫 IncidentStore",
        "不接受或拒絕 pretrip candidate",
        "不改 HumanReview",
        "不送 outbound message",
        "不控制 hardware",
        "不讀取 token value",
        "token_values_exposed=false",
        "phase1_state_changed=false",
        "observed_fact_written=false",
        "outbound_sent=false",
        "hardware_controlled=false",
    ):
        assert token in source


def test_manual_pi_ollama_verification_doc_is_not_readiness_required_path() -> None:
    source = read_doc()

    assert "docs/admin/pi-ollama-manual-verification.md" not in REQUIRED_PATHS
    assert "assistant_readiness_check.py --pretty" in source
    assert "must stay outside the assistant readiness gate" in source


def test_cross_surface_assistant_spec_tracks_slice4_and_next_slice() -> None:
    source = SPEC_PATH.read_text(encoding="utf-8")

    for token in (
        "Milestone 10.2 Slice 4: Manual Pi/Ollama Verification Artifact",
        "docs/admin/pi-ollama-manual-verification.md",
        "manual_only_pi_ollama_verification",
        "operator_observed_latency_ms",
        "not part of the assistant readiness gate",
        "must stay outside the assistant readiness gate",
        "Milestone 10.2 Slice 4 manual Pi/Ollama verification artifact is complete when",
    ):
        assert token in source
    assert "## Next Slice Candidates" in source
