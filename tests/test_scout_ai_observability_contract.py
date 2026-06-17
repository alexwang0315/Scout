import json

import pytest
from pydantic import ValidationError

from scout_ai_observability_contract import (
    SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION,
    SCOUT_AI_REQUIRED_TELEMETRY_FIELDS,
    ScoutAiIntentPayload,
    ScoutAiObservabilityBoundary,
    ScoutAiProvenance,
    build_provenance_for_intent,
    build_telemetry_envelope,
    intent_payload_to_otlp_log_record,
    validate_with_model,
)


VALID_PAYLOAD = {
    "intent": "plan.hike.segment_risk",
    "actions": [
        {"name": "gpx_simplify", "params": {"tolerance": 12}},
        {"name": "wx_fetch", "params": {"dataset": "F-C0041-001"}},
    ],
    "outcome": "partial",
    "prompt_hash": "9f8c2d10a1b2c3d4",
    "model_id": "openai/gpt-4o-mini",
    "token_count": 1842,
    "latency_ms": 320,
    "sample_rate": 0.5,
}


def test_intent_payload_validates_with_pydantic_v2_helper():
    payload = validate_with_model(ScoutAiIntentPayload, VALID_PAYLOAD)

    assert payload.schema_version == SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION
    assert payload.intent == "plan.hike.segment_risk"
    assert payload.actions[0].name == "gpx_simplify"
    assert payload.actions[0].params == {"tolerance": 12}
    assert payload.outcome == "partial"


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"actions": [{"name": "notify", "params": {}}]},
        {**VALID_PAYLOAD, "unexpected": "boom"},
        {**VALID_PAYLOAD, "sample_rate": 1.1},
        {**VALID_PAYLOAD, "outcome": "unknown"},
    ],
)
def test_intent_payload_rejects_missing_extra_and_invalid_fields(bad_payload):
    with pytest.raises(ValidationError):
        validate_with_model(ScoutAiIntentPayload, bad_payload)


@pytest.mark.parametrize(
    "params",
    [
        {"api_key": "do-not-embed"},
        {"nested": {"Authorization": "Bearer do-not-embed"}},
        {"headers": [{"x_session_token": "do-not-embed"}]},
    ],
)
def test_action_params_reject_secret_like_keys(params):
    with pytest.raises(ValidationError):
        ScoutAiIntentPayload.model_validate(
            {
                **VALID_PAYLOAD,
                "actions": [{"name": "wx_fetch", "params": params}],
            }
        )


def test_provenance_and_envelope_are_non_authoritative():
    payload = ScoutAiIntentPayload.model_validate(VALID_PAYLOAD)
    provenance = build_provenance_for_intent(
        payload,
        runtime="python3.12+pydantic2",
    )
    envelope = build_telemetry_envelope(
        payload,
        runtime="python3.12+pydantic2",
    )

    assert provenance.prompt_hash == payload.prompt_hash
    assert provenance.model == payload.model_id
    assert provenance.schema_version == SCOUT_AI_OBSERVABILITY_SCHEMA_VERSION
    assert envelope.boundary.telemetry_only is True
    assert envelope.boundary.runtime_safety_truth is False
    assert envelope.boundary.safety_mutation_allowed is False
    assert envelope.boundary.outbound_send_performed is False
    assert envelope.boundary.hardware_control_performed is False

    with pytest.raises(ValidationError):
        ScoutAiProvenance(
            prompt_hash=payload.prompt_hash,
            model=payload.model_id,
            runtime="python3.12",
            validator="test",
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        ScoutAiObservabilityBoundary(runtime_safety_truth=True)


def test_otlp_log_record_contains_fixed_fields_and_no_action_params():
    payload = ScoutAiIntentPayload.model_validate(VALID_PAYLOAD)
    provenance = build_provenance_for_intent(
        payload,
        runtime="python3.12+pydantic2",
    )

    otlp = intent_payload_to_otlp_log_record(
        payload,
        provenance=provenance,
        time_unix_nano=1718537600000000000,
        trace_id="c4f1",
        span_id="ab12",
        service_version="0.1.0",
        deployment_environment="test",
    )

    record = otlp["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    body_values = record["body"]["kvlistValue"]["values"]
    body_by_key = {entry["key"]: entry["value"] for entry in body_values}

    assert tuple(body_by_key) == SCOUT_AI_REQUIRED_TELEMETRY_FIELDS
    assert body_by_key["intent"]["stringValue"] == "plan.hike.segment_risk"
    assert body_by_key["outcome"]["stringValue"] == "partial"
    assert body_by_key["prompt_hash"]["stringValue"] == "9f8c2d10a1b2c3d4"
    assert body_by_key["model_id"]["stringValue"] == "openai/gpt-4o-mini"
    assert body_by_key["token_count"]["intValue"] == "1842"
    assert body_by_key["latency_ms"]["intValue"] == "320"
    assert body_by_key["sample_rate"]["doubleValue"] == 0.5
    assert body_by_key["actions"]["arrayValue"]["values"] == [
        {"stringValue": "gpx_simplify"},
        {"stringValue": "wx_fetch"},
    ]

    serialized = json.dumps(otlp, ensure_ascii=False, sort_keys=True)
    assert "tolerance" not in serialized
    assert "F-C0041-001" not in serialized
    assert "raw_prompt" not in serialized
    assert "raw_model_output" not in serialized
    assert "api_key" not in serialized.lower()

    attributes = {item["key"]: item["value"] for item in record["attributes"]}
    assert attributes["scout.telemetry_only"]["boolValue"] is True
    assert attributes["scout.runtime_safety_truth"]["boolValue"] is False
    assert attributes["trace_id"]["stringValue"] == "c4f1"
    assert attributes["span_id"]["stringValue"] == "ab12"

    resource_attributes = {
        item["key"]: item["value"]
        for item in otlp["resourceLogs"][0]["resource"]["attributes"]
    }
    assert resource_attributes["service.name"]["stringValue"] == "scout-ai"
    assert resource_attributes["service.version"]["stringValue"] == "0.1.0"
    assert resource_attributes["deployment.environment"]["stringValue"] == "test"
