from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from assistant_readiness_check import REQUIRED_PATHS
from pi_ollama_manual_verification import (
    PiOllamaManualVerificationIndex,
    load_pi_ollama_manual_verification_index,
    summarize_pi_ollama_manual_verification_index,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "hardware"
    / "pi_ollama_manual_verification.index.example.json"
)
DOC_PATH = ROOT / "docs" / "admin" / "pi-ollama-manual-verification.md"
SPEC_PATH = ROOT / "docs" / "specs" / "scout-cross-surface-ai-assistant.md"
MODULE_PATH = ROOT / "pi_ollama_manual_verification.py"


def test_manual_verification_index_loads_optional_fixture_refs() -> None:
    index = load_pi_ollama_manual_verification_index(INDEX_PATH)

    assert index.artifact_type == "manual_only_pi_ollama_verification_index"
    assert index.index_version == 1
    assert index.entries[0].fixture_path == (
        "tests/fixtures/hardware/pi_ollama_manual_verification.example.json"
    )
    assert index.entries[0].summary_ref == "manual-pi-ollama-2026-05-19T00:00:00+08:00"
    assert index.entries[0].operator_observed_latency_ms == 5700
    assert index.entries[0].read_only is True
    assert index.entries[0].model_interpretation is True
    assert index.entries[0].phase1_state_changed is False
    assert index.entries[0].observed_fact_written is False
    assert index.entries[0].outbound_sent is False
    assert index.entries[0].hardware_controlled is False


def test_manual_verification_index_summary_is_bounded_and_secret_free() -> None:
    index = load_pi_ollama_manual_verification_index(INDEX_PATH)

    summary = summarize_pi_ollama_manual_verification_index(index)

    for token in (
        "Manual Pi/Ollama verification index summary",
        "artifact_type=manual_only_pi_ollama_verification_index",
        "entry_count=1",
        "summary_ref=manual-pi-ollama-2026-05-19T00:00:00+08:00",
        "fixture_path=tests/fixtures/hardware/pi_ollama_manual_verification.example.json",
        "operator_observed_latency_ms=5700",
        "read_only=true",
        "model_interpretation=true",
        "phase1_state_changed=false",
        "observed_fact_written=false",
        "outbound_sent=false",
        "hardware_controlled=false",
        "not part of the assistant readiness gate",
    ):
        assert token in summary

    for forbidden in ("raw_model_output", "sk-", "Bearer ", "OPENROUTER_API_KEY", "token-value"):
        assert forbidden not in summary


def test_manual_verification_index_rejects_raw_output_or_absolute_secret_paths() -> None:
    payload = _index_payload()
    payload["entries"][0]["raw_model_output"] = "do not store raw output"

    with pytest.raises(ValidationError):
        PiOllamaManualVerificationIndex.model_validate(payload)

    payload = _index_payload()
    payload["entries"][0]["fixture_path"] = "/Users/alexwang0315/.scout/assistant-models.json"

    with pytest.raises(ValidationError, match="repo-relative fixture path"):
        PiOllamaManualVerificationIndex.model_validate(payload)


def test_manual_verification_index_rejects_mutating_boundary_claims() -> None:
    payload = _index_payload()
    payload["entries"][0]["hardware_controlled"] = True

    with pytest.raises(ValidationError):
        PiOllamaManualVerificationIndex.model_validate(payload)


def test_manual_verification_index_is_optional_and_offline() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "load_pi_ollama_manual_verification_index" in source
    assert "summarize_pi_ollama_manual_verification_index" in source
    assert "tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json" not in REQUIRED_PATHS
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


def test_docs_track_slice7_optional_index_and_next_slice() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")
    spec_source = SPEC_PATH.read_text(encoding="utf-8")

    for source in (doc_source, spec_source):
        for token in (
            "Milestone 10.2 Slice 7",
            "PiOllamaManualVerificationIndex",
            "pi_ollama_manual_verification.index.example.json",
            "optional append-only index",
            "not part of the assistant readiness gate",
        ):
            assert token in source

    assert "Milestone 10.2 Slice 7 optional manual verification index is complete when" in spec_source
    assert "## Next Slice Candidates" in spec_source


def _index_payload() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
