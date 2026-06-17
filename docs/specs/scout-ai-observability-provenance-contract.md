# Scout AI Observability and Provenance Contract

This document defines the first Scout-native contract for Scout AI intent
telemetry, provenance, and audit handoff. It adapts the generic Pydantic
starter pack into the current Scout repository shape.

## Scope

The implementation lives in:

- `scout_ai_observability_contract.py`
- `tests/test_scout_ai_observability_contract.py`

It is a schema and serialization contract only. It does not install a live
OpenTelemetry exporter, does not send telemetry to a remote collector, and does
not change Phase 1 runtime safety behavior.

## Intent Payload

Every Scout AI run that is promoted into this contract should validate an
intent payload with these fixed fields:

- `intent`
- `actions`
- `outcome`
- `prompt_hash`
- `model_id`
- `token_count`
- `latency_ms`
- `sample_rate`

The schema is Pydantic v2-first and uses `extra="forbid"`. The helper
`validate_with_model()` exists so older call sites can still use a single
validation entrypoint without depending on Pydantic v1 APIs.

Example Scout intents:

- `plan.hike.segment_risk`
- `nav.cp_eta_notify`
- `gpx.clean_simplify`
- `wx.nowcast_merge`
- `pretrip.route_context.briefing`
- `runtime.ingress_status.assess`

## Action Handling

`actions[].params` may be used for local deterministic validation and
debugging, but OTLP output must only contain action names. Parameters are not
projected into telemetry records.

Action params reject secret-like keys recursively, including:

- `api_key`
- `auth`
- `bearer`
- `credential`
- `password`
- `private_key`
- `secret`
- `session`
- `token`

## Provenance

`ScoutAiProvenance` records:

- `prompt_hash`
- `model`
- `schema_version`
- `runtime`
- `validator`

The hash must be irreversible. Raw prompts, raw model outputs, credentials,
private user payloads, and hardware telemetry payloads must not be embedded in
this contract.

## Boundary

`ScoutAiObservabilityBoundary` is deliberately non-authoritative:

- `telemetry_only: true`
- `runtime_safety_truth: false`
- `safety_mutation_allowed: false`
- `outbound_send_performed: false`
- `hardware_control_performed: false`
- `raw_prompt_embedded: false`
- `raw_model_output_embedded: false`
- `sensitive_payload_embedded: false`

Any future exporter or provider hook must preserve these flags unless a new
reviewed contract explicitly replaces this document.

## OTLP JSON Projection

`intent_payload_to_otlp_log_record()` returns a bounded OTLP-style JSON payload:

- `resourceLogs[].resource.attributes` includes service metadata.
- `scopeLogs[].scope.name` is `scout.ai.telemetry`.
- `logRecords[].body.kvlistValue.values` contains the fixed telemetry fields.
- `logRecords[].attributes` carries schema/provenance/boundary metadata.

The projection is intentionally dependency-free. A future live exporter can map
the same fields into OpenTelemetry spans, logs, or events.

## PR Handoff Checklist

Before merging changes that modify this contract or wire a new Scout AI
surface into it:

- [ ] Schema version and docs are updated together.
- [ ] `extra="forbid"` remains active for all public models.
- [ ] Valid and invalid fixtures cover missing fields, extra fields, and type
      constraints.
- [ ] OTLP output includes all fixed fields with stable names and types.
- [ ] Action params, raw prompts, and raw model outputs are not emitted.
- [ ] Every serialized record has provenance or a documented reason it cannot.
- [ ] Sensitive data handling has been reviewed.
- [ ] Runtime safety truth is not mutated or inferred from model output.
- [ ] `/safety/*`, Phase 1 runtime safety, hardware controls, and outbound send
      paths are not changed by telemetry plumbing.
- [ ] `python3 -m pytest tests/test_scout_ai_observability_contract.py -q`
      passes.

## Future Integration Points

Likely next integration points:

- Scout AI provider request/response wrapper.
- Model router selection audit records.
- Skill/workflow compiler output audit records.
- Pretrip route-context briefing provenance.
- Admin debug observability panel.
- Optional live OTLP exporter controlled by server-side environment config.

Each integration should start by validating the contract locally and only then
projecting the bounded metadata to UI, log, or collector surfaces.
