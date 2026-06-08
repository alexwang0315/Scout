from __future__ import annotations

from pathlib import Path

from assistant_readiness_check import REQUIRED_PATHS
from pi_ollama_manual_verification import (
    format_pi_ollama_manual_verification_summary,
    load_pi_ollama_manual_verification_result,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "hardware"
    / "pi_ollama_manual_verification.example.json"
)
DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"
MODULE_PATH = ROOT / "pi_ollama_manual_verification.py"


def test_manual_verification_summary_is_human_readable_and_bounded() -> None:
    result = load_pi_ollama_manual_verification_result(FIXTURE_PATH)

    summary = format_pi_ollama_manual_verification_summary(result)

    for token in (
        "Manual Pi/Ollama verification summary",
        "runtime_profile=pi-field",
        "assistant_provider=pydantic_ai",
        "local_model_name=qwen2.5:0.5b",
        "operator_observed_latency_ms=5700",
        "model_profile_used=local",
        "read_only=true",
        "model_interpretation=true",
        "read-only model interpretation",
        "optional operator-recorded fixture",
        "not part of the assistant readiness gate",
    ):
        assert token in summary


def test_manual_verification_summary_preserves_status_and_boundary_flags() -> None:
    result = load_pi_ollama_manual_verification_result(FIXTURE_PATH)

    summary = format_pi_ollama_manual_verification_summary(result)

    for token in (
        "local_fallback_mode=pi_field_manual_opt_in",
        "manual_verification_required=true",
        "local_fallback_max_concurrency=1",
        "readiness_starts_local_model=false",
        "local_model_listener_required_for_readiness=false",
        "status_model_switch_allowed=false",
        "token_values_exposed=false",
        "phase1_state_changed=false",
        "observed_fact_written=false",
        "phase2_brain_written=false",
        "incident_store_written=false",
        "review_decision_changed=false",
        "outbound_sent=false",
        "hardware_controlled=false",
    ):
        assert token in summary


def test_manual_verification_summary_does_not_expose_paths_or_secret_markers() -> None:
    result = load_pi_ollama_manual_verification_result(FIXTURE_PATH)

    summary = format_pi_ollama_manual_verification_summary(result)

    for forbidden in (
        "/Users/alexwang0315/.scout/assistant-models.json",
        "SCOUT_AI_ASSISTANT_CONFIG_PATH",
        "token_id",
        "token_env_var",
        "sk-",
        "Bearer ",
        "OPENROUTER_API_KEY",
        "api_key",
    ):
        assert forbidden not in summary


def test_manual_verification_summary_formatter_is_offline_and_optional() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "format_pi_ollama_manual_verification_summary" in source
    assert "tests/fixtures/hardware/pi_ollama_manual_verification.example.json" not in REQUIRED_PATHS
    for forbidden in (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "/assistant/query",
        "/assistant/status",
        "/safety/",
        "ObservedFactWriter",
        "BrainFileStore",
        "IncidentStore",
        "send_outbound",
        "MockOutboundTransport",
    ):
        assert forbidden not in source


def test_docs_track_slice6_summary_formatter_and_next_slice() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")
    spec_source = SPEC_PATH.read_text(encoding="utf-8")

    for source in (doc_source, spec_source):
        for token in (
            "Milestone 10.2 Slice 6",
            "format_pi_ollama_manual_verification_summary",
            "Manual Pi/Ollama verification summary",
            "optional operator-recorded fixture",
            "not part of the assistant readiness gate",
        ):
            assert token in source

    assert "Milestone 10.2 Slice 6 manual verification summary formatter is complete when" in spec_source
    assert "## Next Slice Candidates" in spec_source
