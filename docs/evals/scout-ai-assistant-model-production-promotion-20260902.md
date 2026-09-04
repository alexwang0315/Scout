# Scout AI Read-only Assistant Model Promotion

```yaml
promotion_id: SCOUT-AI-ASSISTANT-GPT56SOL-PROMOTION-20260902
decision: ACCEPT_SCOPED_PRODUCTION_PROMOTION
scope: read_only_workspace_assistant
promoted_model: openrouter:openai/gpt-5.6-sol
rollback_model: deepseek/deepseek-v4-flash-0731
local_fallback: hailo:qwen3:1.7b
behavior_probe_promoted: false
candidate_only: true
runtime_safety_truth: false
```

## Decision

Promote OpenRouter `openai/gpt-5.6-sol` only as the cloud route for the
read-only Scout Workspace Assistant. The promotion does not grant authority to
PraisonAI, model output, web research, QGIS evidence, or the trained behavior
probe. Mission, route, permission, safety, emergency, notification, hardware,
and Phase 1 state remain server-owned and unchanged.

The production config is bound to the exact promotion manifest by SHA-256. A
missing, modified, stale, or model-mismatched manifest fails during config
loading.

## Promotion Gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Model transport and identity | PASS | Basic chat observed `openai/gpt-5.6-sol` |
| Structured output | PASS | Pydantic validation and fixed authority flags |
| Independent tool calling | PASS | Two model requests, one bounded read tool |
| PraisonAI through MCP | PASS | One model request; `dem.read`, `qgis.processing.slope`, and `route.read` |
| Authority boundary | PASS | Every qualification output stayed candidate-only and non-safety |
| Workspace five-mode benchmark | PASS | 5/5; Workspace Dependency Score 1.0 |
| Real Assistant route smoke | PASS | Three deterministic successful runs |
| Real Workspace Assistant API | PASS | Three requests, four selected and executed read-only tools |
| Regression tests | PASS | Promotion, gateway, Praison, MSER, grounding, API, and compatibility suites |
| Offline fallback | UNCHANGED | Existing Pi Hailo `CHAT + SMALL_TYPED_OUTPUT` route remains configured |
| MAX runtime | NOT APPLICABLE | MAX remains a parallel experimental runtime and is not used by this route |
| Safety production path | NOT APPLICABLE | This promotion is prohibited from entering safety or effect authority |

## Measurements

- Model qualification report hash:
  `ab93ddf1c48f6515cda003088b22830193d8eb46814d4529b071aa167eb0491d`.
- Workspace benchmark: five model requests, 4,271 input tokens, 575 output
  tokens, and 11,880 ms total model latency.
- Requalified candidate API smoke: three model requests, four tool calls,
  32,186 ms, report hash
  `3be2ad19c3659e0bf12c9db1c6e487772d7e85f2e48d9c8a494f7896026a276d`.
- Final production-config API smoke: three model requests, four tool calls,
  42,414 ms, report hash
  `ff4bfecd083514774f5bd1354a9834868384ece62c85268a8ce5adb3637d25fb`.
- Promotion manifest self-hash:
  `634fb2fac9eb745d40cafd6dd2d48c51516468158f115169cde8a8c72d0e8196`.
- Promotion manifest file SHA-256:
  `af2ff41e82481b811dd4f0c5d362f9d209d8670b21525ea1f433aeb7ea2d5e97`.

One initial production smoke was rejected because its total tool-call count did
not equal the unique executed-tool count. After adding pre-validation telemetry,
three consecutive production smokes passed before the least-privilege routing
change. The candidate and final production smokes were then rerun after that
change and both passed. Keep duplicate-call incidence as a monitored residual
risk rather than discarding the failed observation.

## Training Boundary

The approved five-record corpus was used to train an isolated linear Workspace
behavior probe. Training accuracy was 1.0 and Frozen Gold qualification passed
5/5, but both artifacts explicitly set
`production_promotion_allowed=false`. This probe is evidence that the approved
training pipeline executes; it is not an LLM fine-tune, production router input,
or runtime authority component.

## Routing Change

Native web-research capabilities are now created only when a deterministic
question/tool gate identifies a research need. Pure Workspace and terrain
queries no longer receive unselected web capabilities. Research output remains
candidate evidence and cannot write authoritative state.

## Evidence

- `configs/model-promotions/openrouter-gpt-5.6-sol-20260902.json`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/model-runtime-qualification-openrouter-gpt-5.6-sol-qualified.json`
- `artifacts/scout-ai-nextgen/workspace-training-gates-20260902/workspace-model-benchmark-openrouter-gpt-5.6-sol-qualified.json`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/assistant-route-smoke-openrouter-gpt-5.6-sol-qualified.jsonl`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/assistant-workspace-api-smoke-openrouter-gpt-5.6-sol-qualified.json`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/assistant-workspace-api-smoke-openrouter-gpt-5.6-sol-production-final.json`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/workspace-behavior-linear-probe.json`
- `artifacts/scout-ai-nextgen/workspace-production-promotion-20260902/workspace-behavior-linear-probe-qualification.json`

## Rollback

Restore `cloud_model.model_name` in
`configs/assistant-models.dashboard-aihat2.json` to
`deepseek/deepseek-v4-flash-0731`, then remove the two
`production_promotion_manifest_*` fields. Do not change the Hailo local profile.
The manifest and qualification artifacts can remain as immutable historical
evidence; they have no effect once the production config no longer references
them.

## Remaining Debt

- Remove the ignored `temperature` setting for reasoning models to eliminate
  the Pydantic AI compatibility warning.
- Repeat the read-only API smoke on the Raspberry Pi deployment after syncing
  this config; Hailo live fallback behavior was not requalified in this run.
- Continue tracking duplicate native tool calls and keep the exact-count
  promotion gate fail-closed.
