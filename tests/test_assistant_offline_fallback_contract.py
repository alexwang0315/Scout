import json

import pytest
from pydantic import ValidationError

from assistant_offline_fallback_contract import (
    OFFLINE_FALLBACK_PROMPT_ID,
    OFFLINE_FALLBACK_SCHEMA_VERSION,
    ScoutOfflineFallbackInterpretation,
    build_offline_fallback_schema_prompt,
    format_offline_fallback_interpretation,
    parse_offline_fallback_interpretation,
)


SPEC_PATH = "docs/specs/scout-cross-surface-ai-assistant.md"
RUNBOOK_PATH = "docs/admin/cross-surface-ai-assistant-runbook.md"


def test_offline_fallback_contract_accepts_fixed_schema_json() -> None:
    interpretation = parse_offline_fallback_interpretation(
        json.dumps(_valid_payload(), ensure_ascii=False)
    )

    assert interpretation.schema_version == OFFLINE_FALLBACK_SCHEMA_VERSION
    assert interpretation.prompt_id == OFFLINE_FALLBACK_PROMPT_ID
    assert interpretation.read_only is True
    assert interpretation.model_interpretation is True
    assert interpretation.safety_authority is False
    assert interpretation.phase1_state_change_allowed is False
    assert interpretation.observed_fact_write_allowed is False
    assert interpretation.outbound_action_allowed is False
    assert interpretation.hardware_control_allowed is False

    summary = format_offline_fallback_interpretation(interpretation)
    assert "Offline fallback fixed-schema interpretation" in summary
    assert "read_only=True" in summary
    assert "model_interpretation=True" in summary
    assert "safety_authority=False" in summary


def test_offline_fallback_contract_rejects_mutation_or_secret_claims() -> None:
    payload = _valid_payload()
    payload["operator_checks"] = ["send SOS now"]

    with pytest.raises(ValidationError, match="forbidden fragment"):
        ScoutOfflineFallbackInterpretation.model_validate(payload)

    payload = _valid_payload()
    payload["summary_zh"] = "token_value=secret"

    with pytest.raises(ValidationError, match="forbidden fragment"):
        ScoutOfflineFallbackInterpretation.model_validate(payload)


def test_offline_fallback_contract_rejects_authoritative_or_action_output() -> None:
    payload = _valid_payload()
    payload["read_only"] = False

    with pytest.raises(ValidationError):
        ScoutOfflineFallbackInterpretation.model_validate(payload)

    payload = _valid_payload()
    payload["phase1_state_change_allowed"] = True

    with pytest.raises(ValidationError):
        ScoutOfflineFallbackInterpretation.model_validate(payload)


def test_offline_fallback_schema_prompt_demands_json_and_forbids_actions() -> None:
    prompt = build_offline_fallback_schema_prompt(
        "Explain current debug state.",
        local_model_name="qwen2.5:0.5b",
    )

    for token in (
        "Return only one JSON object",
        OFFLINE_FALLBACK_SCHEMA_VERSION,
        OFFLINE_FALLBACK_PROMPT_ID,
        "read_only=true",
        "model_interpretation=true",
        "safety_authority=false",
        "Do not call safety mutation endpoints",
        "Local model: qwen2.5:0.5b",
    ):
        assert token in prompt


def test_docs_track_fixed_schema_offline_fallback_contract() -> None:
    for path in (SPEC_PATH, RUNBOOK_PATH):
        source = open(path, encoding="utf-8").read()
        for token in (
            "Milestone 10.2 Slice 12",
            "ScoutOfflineFallbackInterpretation",
            OFFLINE_FALLBACK_SCHEMA_VERSION,
            OFFLINE_FALLBACK_PROMPT_ID,
            "fixed_schema_offline_fallback_contract",
            "local_schema_validation_error",
        ):
            assert token in source


def _valid_payload() -> dict:
    return {
        "schema_version": OFFLINE_FALLBACK_SCHEMA_VERSION,
        "prompt_id": OFFLINE_FALLBACK_PROMPT_ID,
        "summary_zh": "目前只能做離線備援解讀，需由人確認定位與電量狀態。",
        "risk_signals": ["GPS 訊號不穩", "電量偏低"],
        "operator_checks": ["確認最近檢查點", "確認是否仍在計畫路線附近"],
        "uncertainties": ["沒有即時雲端模型回覆"],
        "source_refs": ["assistant_context.debug"],
        "confidence": "low",
        "read_only": True,
        "model_interpretation": True,
        "safety_authority": False,
        "phase1_state_change_allowed": False,
        "observed_fact_write_allowed": False,
        "outbound_action_allowed": False,
        "hardware_control_allowed": False,
    }
