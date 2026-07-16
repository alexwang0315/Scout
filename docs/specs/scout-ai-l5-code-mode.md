# Scout AI L5 Code Mode

## Status

Under construction. The activation contract, pinned optional Pydantic AI
Harness runtime, Monty integration smoke, immutable execution receipt, and
100-case readiness/live runner are implemented. The runtime remains outside
the production dependency set.

The host agent facade currently runs on Pydantic AI 2.10.0. L5 keeps its own
optional Harness 0.7.0 and Monty 0.0.18 attestation pins; these are compatible
surfaces, not a request to downgrade the host facade.

Set this process-level development flag while implementing and evaluating L5:

```bash
SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION=true
```

When the flag is true, the typed activation decision returns:

```json
{
  "artifact_kind": "scout_l5_code_mode_activation_decision",
  "schema_version": "scout.l5_code_mode.activation.v1",
  "l5_code_mode": true,
  "state": "enabled_under_construction",
  "requires_human_approval": false,
  "human_can_activate_l5": false,
  "model_can_activate_l5": false
}
```

This is an eligibility override, not a sandbox-availability claim and not an
authority escalation.

## Purpose

L5 lets Scout respond to a critical capability gap by temporarily composing
read-only tools with model-authored Python inside a reviewed sandbox. It is
intended for questions that existing fixed tools cannot answer but whose input
evidence is already available to Scout.

L5 is not part of the canonical L0-L4 human-safety signal. L0-L4 describes the
observed safety state; L5 describes an exceptional computation mode.

## Activation

Under construction, the development override makes L5 eligible at every
safety level so agents can implement and test it without applying production
activation rules.

In production, all of these deterministic prerequisites are required:

1. a system assessment is present;
2. current safety state is L3_DISTRESS or L4_EMERGENCY;
3. a critical capability gap is present;
4. the reviewed sandbox is available;
5. the resource budget is available;
6. expected information value meets the configured threshold.

A human request alone cannot activate L5. A model statement alone cannot
activate L5. Human action may reject Scout's advice; that divergence becomes a
new observation and does not stop Scout from continuing to search for safer
options.

## Immutable Boundary

Development and production L5 share the same immutable boundary:

- ephemeral sandbox required;
- read-only Scout project access allowed;
- host shell denied;
- workspace writes denied;
- unrestricted network denied;
- secret access denied;
- hardware control denied;
- direct outbound send denied;
- production database writes denied;
- runtime safety truth mutation denied.

Emergency communication remains the responsibility of the deterministic
notification and standing-grant policies. L5 may produce new evidence that
raises communication frequency, but generated code does not send directly.

## Runtime Availability

The adapter pins `pydantic-ai-harness[codemode]==0.7.0` and
`pydantic-monty==0.0.18` through `requirements.l5-codemode.txt`. Runtime
availability is reported separately from activation eligibility and attests
the exact package versions, importability, and installed module origins.

The first 100-case slice deliberately uses `mount=None`. Model-authored code
cannot read host files, environment variables, the clock, or the network. It
can only call the frozen `query_scout_workspace` allowlist entry, whose host
implementation confines typed JSON/GeoJSON queries to the selected manifest
project. Direct read-only mounts remain deferred until file reads can produce
the same evidence and receipt guarantees.

If Harness or Monty is absent, execution stops with an explicit runtime status.
It must not fall back to host Python, Node.js, or shell execution.

## Current Implementation

- Contract: `src/scout/schemas/l5_code_mode.py`
- Policy and adapter: `src/scout/services/l5_code_mode.py`
- Tool admission and receipt: `src/scout/services/l5_code_mode_execution.py`
- Optional runtime pin: `requirements.l5-codemode.txt`
- 100-case readiness/live runner: `tools/scout_ai_l5_code_mode_eval.py`
- Deterministic mileage post-verifier: `src/scout/services/workspace_query.py`
- Reproducible 12.5K water fixtures:
  `tests/fixtures/scout_ai_l5_code_mode_water_12_5k_cases.json` and
  `tests/fixtures/scout_ai_l5_code_mode_water_12_5k_gold.json`
- Tests: `tests/test_l5_code_mode.py`,
  `tests/test_l5_code_mode_execution.py`, and
  `tests/test_scout_ai_l5_code_mode_eval.py`

Readiness check:

```bash
SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION=true \
  ./venv/bin/python tools/scout_ai_l5_code_mode_eval.py --check
```

One-case live smoke:

```bash
SCOUT_L5_CODE_MODE_UNDER_CONSTRUCTION=true \
  ./venv/bin/python tools/scout_ai_l5_code_mode_eval.py \
  --case-id workspace-20260713-002
```

The L5 eval runner defaults to the fixed free model
`openrouter:poolside/laguna-m.1:free`. It does not use OpenRouter's random
free-model router, so model identity remains reproducible across cases. A paid
or different model is never selected unless an operator explicitly supplies
`--model`.

## Mileage-Axis Post-Verification

Questions such as "12.5K 附近最近的水源在哪裡" use a typed FILTER over
`mileage_tag_alignment_geojson_ref`. The sandbox may parse and rank the labels,
but the host verifier repeats the critical computation before answer release:

1. parse signed K values from `source_label`;
2. deduplicate the same location observed in multiple reference tracks;
3. compare on the label-mileage axis, never against full-route
   `route_distance_m`;
4. preserve every tied nearest location;
5. verify directions, coordinates, source refs, freshness/contradiction state,
   and candidate-only boundaries against formal gold expectations.

The raw model output is retained separately from the released answer. An empty
or inaccurate synthesis cannot remove a tied candidate: the deterministic
answer renderer uses the verified result and states that a static workspace
marker does not guarantee live water presence or potability. No result is
promoted to runtime safety truth.

Every attempt records its fresh 10/10 budget and a secret-minimized tool trace
with argument hashes, operations, status, source refs, evidence IDs, and root
cause. If a provider omits token accounting, the report marks those token
values unavailable while recovering request and model-tool-call counts from the
Pydantic message trace.

Ten-operation live smoke uses repeated `--case-id` for cases 002, 004, 011,
015, 017, 018, 026, 051, 066, and 093. After that passes, omit `--case-id` and
`--max-cases` to run all 100 cases. The legacy domain-tool exact-set score is
retained as diagnostic-only; L5 gates on valid receipts, completed workspace
operations, grounded answers, and zero user-visible unsupported claims.

Static workspace questions use an acceptance ceiling of 10 tool calls on
average. The per-question policy ceiling is also 10; evidence sufficiency and
duplicate/no-progress checks may stop substantially earlier.
