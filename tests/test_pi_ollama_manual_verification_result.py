from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from assistant_readiness_check import REQUIRED_PATHS
from pi_ollama_manual_verification import (
    PiOllamaManualVerificationResult,
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


def test_example_fixture_loads_as_manual_only_result() -> None:
    result = load_pi_ollama_manual_verification_result(FIXTURE_PATH)

    assert result.artifact_type == "manual_only_pi_ollama_verification"
    assert result.runtime_profile == "pi-field"
    assert result.assistant_provider == "pydantic_ai"
    assert result.fallback_to_local_on_error is True
    assert result.ollama_tags_checked is True
    assert result.local_model_name == "qwen2.5:0.5b"
    assert result.operator_observed_latency_ms >= 0
    assert result.assistant_status.local_fallback_mode == "pi_field_manual_opt_in"
    assert result.assistant_status.token_values_exposed is False
    assert result.assistant_status.status_model_switch_allowed is False
    assert result.assistant_response.read_only is True
    assert result.assistant_response.model_interpretation is True
    assert result.boundary_observation.phase1_state_changed is False
    assert result.boundary_observation.observed_fact_written is False
    assert result.boundary_observation.outbound_sent is False
    assert result.boundary_observation.hardware_controlled is False


def test_manual_result_rejects_secret_like_values() -> None:
    payload = _example_payload()
    payload["config_path_ref"] = "sk-test-token-value-that-must-not-appear"

    with pytest.raises(ValidationError, match="secret-like value"):
        PiOllamaManualVerificationResult.model_validate(payload)


def test_manual_result_rejects_mutation_boundary_changes() -> None:
    payload = _example_payload()
    payload["boundary_observation"]["phase1_state_changed"] = True

    with pytest.raises(ValidationError):
        PiOllamaManualVerificationResult.model_validate(payload)


def test_manual_result_rejects_readiness_or_provider_switch_claims() -> None:
    payload = _example_payload()
    payload["assistant_status"]["readiness_starts_local_model"] = True

    with pytest.raises(ValidationError):
        PiOllamaManualVerificationResult.model_validate(payload)

    payload = _example_payload()
    payload["assistant_status"]["status_model_switch_allowed"] = True

    with pytest.raises(ValidationError):
        PiOllamaManualVerificationResult.model_validate(payload)


def test_example_fixture_is_small_optional_and_secret_free() -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8")

    assert len(raw.encode("utf-8")) < 8192
    assert "docs/admin/pi-ollama-manual-verification.md" not in REQUIRED_PATHS
    assert "tests/fixtures/hardware/pi_ollama_manual_verification.example.json" not in REQUIRED_PATHS
    for forbidden in ("sk-", "Bearer ", "OPENROUTER_API_KEY=", "token-value"):
        assert forbidden not in raw


def test_schema_module_is_offline_and_non_mutating() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    for forbidden in (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "/safety/",
        "ObservedFactWriter",
        "BrainFileStore",
        "IncidentStore",
        "send_outbound",
        "MockOutboundTransport",
        "Twilio",
        "subprocess",
    ):
        assert forbidden not in source


def test_docs_track_slice5_schema_and_optional_fixture() -> None:
    doc_source = DOC_PATH.read_text(encoding="utf-8")
    spec_source = SPEC_PATH.read_text(encoding="utf-8")

    for source in (doc_source, spec_source):
        for token in (
            "Milestone 10.2 Slice 5",
            "pi_ollama_manual_verification.py",
            "pi_ollama_manual_verification.example.json",
            "optional operator-recorded fixture",
            "not part of the assistant readiness gate",
        ):
            assert token in source

    assert "Milestone 10.2 Slice 5 manual verification schema is complete when" in spec_source
    assert "## Next Slice Candidates" in spec_source


def _example_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
