# Scout AI Matched Model Recovery Qualification

## Experiment Packet

- Experiment ID: `SCOUT-AI-EXP-MODEL-RECOVERY-001`
- Date: `2026-09-01`
- Hypothesis: an explicit DeepSeek V3.2 recovery attempt can complement
  DeepSeek V4 Flash after bounded primary repair fails, without changing Scout
  authority boundaries.
- Current baseline: the repaired V4 Flash fixed-set run passed `100/100` with
  three guided retries, `candidate_only=true`, and
  `runtime_safety_truth=false`.
- Decision: `CONTINUE_RESEARCH`

## Matched Design

Both providers used the same OpenRouter transport, scenario artifact, four
question IDs, twelve expanded runs, four workers, `thinking=off`, MSER enforce,
guided retry, the conservative response composer, a ten-request per-attempt
ceiling, a 180-second provider timeout, and no Scout total-run deadline.

The subset intentionally covered:

- `PER-063`: historical malformed-output and unsupported comparison behavior.
- `PER-071`: safety-compound retreat reasoning that required a V4 retry.
- `WTH-061`: weather/ETA compound reasoning that required a V4 retry.
- `WTH-091`: contradictory forecast reasoning that required a V4 retry.

## Results

| Metric | V4 Flash 0731 | V3.2 |
|---|---:|---:|
| Strict verifier and quality acceptance | 11/12 | 12/12 |
| Identity pass | 12/12 | 12/12 |
| Harness model requests | 16 | 14 |
| Native Pydantic AI tool calls | 31 | 26 |
| Mean latency | 22.94 s/run | 17.02 s/run |
| Semantic answer quality mean | 97.92 | 100.00 |
| Safe uncertainty mean | 100.00 | 100.00 |
| Transport/schema mean | 100.00 | 100.00 |

V4 failed closed on `PER-063/sheltered_flat_time_available`. Its first answer
selected `CHANGE_PLAN` while typed evidence gaps remained, so MSER rejected it
as `non_conservative_gap_decision`. Its repair response contained explanatory
prose around a JSON candidate and was rejected as invalid structured output.
V3.2 passed the same run in one request with a conservative, evidence-bound
candidate and preserved both authority flags.

## Recovery Policy Candidate

The evidence supports an experimental recovery path, not a global model
promotion:

1. Run the explicitly selected primary model through its bounded repair path.
2. Allow recovery only after deterministic schema, evidence, or MSER validation
   rejects the primary result.
3. Record the primary model, primary errors, request count, latency, and output
   hash before invoking the alternate model.
4. Invoke the explicitly configured alternate model with the same typed input,
   evidence refs, capability scope, and authority flags.
5. Re-run all Pydantic, provenance, MSER, and quality gates. A fallback result
   receives no authority from having passed a second model.
6. Record both attempts and expose the recovery reason. Silent fallback is not
   allowed.
7. If the alternate model fails, return the original fail-closed/UNKNOWN result;
   do not continue an unbounded model chain.

The experimental trigger may cover `invalid_json_output`, typed output
validation failure, and deterministic answer-verification failure after primary
repair is exhausted. Provider outage and timeout remain separate availability
fallback classes and require their own qualification.

## Acceptance And Promotion Debt

Accepted for an EXP-only implementation:

- one explicit alternate-model attempt;
- immutable attempt ledger with both model identities;
- a fresh shared request budget of at least 10 for the recovery stage;
- full revalidation and unchanged candidate-only authority.

Not accepted:

- silent model routing;
- replacing V4 globally with V3.2 from this twelve-run sample;
- model output deciding whether its own failure is recoverable;
- fallback output mutating mission, permission, safety, notification, route, or
  hardware state;
- treating lower latency in this sample as a production routing guarantee.

Additional promotion evidence requires a wider stratified recovery corpus,
provider-unavailable and timeout tests, repeated-run variance, cost telemetry,
and a live Model Gateway attempt ledger visible to the Dashboard.

## Evidence

- Repaired V4 fixed-set run:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_deepseek_v4_flash_0731_repaired60x100_typed_gap_fix_20260901`
- V4 matched run:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_deepseek_v4_flash_0731_matched_fallback_v4_4x12_20260901`
- V3.2 matched run:
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI/outputs/evals/six_forces_600_openrouter_deepseek_deepseek_v3_2_matched_fallback_v32_4x12_20260901`
