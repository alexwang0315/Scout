# Spec: Scout Cross-Surface AI Assistant Guardrails

Date: 2026-06-30

## Status

Implemented through Slice 26 for the current Milestone 10 guardrail path.
Milestone 10.2 Slice 1 adds the cloud-to-local assistant failover contract as a
spec/readiness-gate slice. Milestone 10.2 Slice 2 adds provider failover
hardening with mocked runners only. Milestone 10.2 Slice 3 adds Pi field
profile status and a manual failover runbook boundary. Milestone 10.2 Slice 4
adds a manual Pi/Ollama verification artifact that stays outside the assistant
readiness gate. Milestone 10.2 Slice 5 adds an optional operator-recorded
fixture schema for manual Pi/Ollama experiment results. Milestone 10.2 Slice 6
adds a bounded text summary formatter for those validated manual results.
Milestone 10.2 Slice 7 adds an optional append-only index for validated manual
fixture references. Milestone 10.2 Slice 8 adds a read-only CLI renderer for
validated optional result/index files. Milestone 10.2 Slice 9 adds an operator
checklist for the optional manual verification flow. Milestone 10.2 Slice 10
consolidates the manual Pi/Ollama artifact chain in the cross-surface runbook.
Milestone 10.2 Slice 11 records the repo-owned Pi/Ollama hardware experiment
assets, `docker-compose.pi.ai.yml` and `tools/pi_ollama_stress.py`, while
keeping them under the `ai-experimental` manual hardware prototype profile and
not part of the assistant readiness gate.

2026-06-30 update: Scout AI provider compatibility now targets Pydantic AI
v2.1.x. The assistant and Mac-local fallback paths keep Scout's read-only,
typed-output contract by using `end_strategy="early"`, normalizing
`openai:<model>` to `openai-chat:<model>`, and using the dedicated OpenRouter
provider for `openrouter:<vendor/model>`. Native WebSearch, WebFetch, and
provider-native MCP are not enabled automatically by the Pydantic AI v2
upgrade. Operators can enable trusted no-per-query-approval WebSearch/WebFetch
research with `SCOUT_AI_OS_NATIVE_RESEARCH=1`; this remains candidate-only
assistant research and cannot mutate runtime safety truth or hardware state.

This document defines the cross-surface assistant guardrails that now anchor the
mock provider, bounded context adapters, read-only API, UI shell, opt-in
Pydantic AI provider, cloud/local model fallback config, readiness gate,
hardware-readiness runbook, static assistant UI smoke gate, browser-backed
visual QA, and map-layer selected source labels.

Implementation note: this milestone is complete for the current read-only
assistant foundation. Future slices may improve UI reuse, add richer context, or
harden the opt-in Pi local fallback provider, but they must preserve the
guardrails in this spec.

## Milestone Name

Recommended name:

```text
Milestone 10: Cross-Surface AI Assistant Guardrails
```

Alternative phase-style name:

```text
Phase 3.6: Cross-Surface AI Assistant Readiness
```

Use `Milestone 10` in implementation notes because this capability cuts across
admin, debug, pre-planning, and future hardware-readiness surfaces. It should
not be treated as a sub-feature of Phase 3.5 or Phase 4.

## Assumptions

- Phase 1 remains the deterministic live safety authority.
- Phase 3.5 runtime debug tooling is complete and read-only.
- Phase 4 pre-trip planning remains a candidate/provenance/review workspace.
- Existing Pydantic AI usage in `agent.py` and `server.py` is navigation advice
  over already-computed context, not PDR math, route-progress logic, or safety
  state transition logic.
- The first implementation should be mock-backed and deterministic before any
  live Pydantic AI provider is enabled.
- The assistant is a data-state explanation tool first. It must not trigger
  irreversible runtime, store, review, outbound, or hardware actions.

## Objective

Build a shared Scout AI assistant capability that can be embedded into multiple
admin-facing surfaces while preserving each surface's constraints.

The assistant should answer questions such as:

```text
Why did Scout enter L2?
Which provider was degraded at this timeline node?
What incident package was created from this event?
What pre-trip candidates still need review?
Which source registry items support this planning decision?
What is the current departure/readiness gate state?
What hardware-readiness provider looks degraded?
```

Success means Scout can offer useful data-state answers without turning model
output into facts, runtime decisions, planning approvals, or outbound actions.

## Non-Goals

This milestone must not:

- change Phase 1 safety decisions;
- call `/safety/*` mutation endpoints;
- write `ObservedFact`, `DerivedMeasurement`, `HumanReview`, review decisions,
  or IncidentStore records;
- modify Phase 2 Brain data;
- accept or reject pre-trip planning candidates;
- send outbound messages;
- control hardware, sensors, providers, transport, SOS, SMS, or satellite
  integrations;
- replace `/navigate` or make Pydantic AI part of PDR, route progress, risk
  rules, or L0-L4 state transitions.

## Chinese Guardrails

中文註釋：這不是 Scout safety runtime。AI assistant 只能解釋目前資料狀態，不可以影響 Phase 1 route progress、risk rules、IncidentPackage 或 L0-L4 決策。

中文註釋：這不是自動規劃批准。pre-planning 介面中的 AI 回答只能說明 candidate、source、review state、readiness state，不可以自動接受候選或產生出發批准。

中文註釋：這不是 ObservedFact writer。模型輸出必須標示為 `ModelInterpretation` 或 debug explanation，不能被寫成 `ObservedFact`。

中文註釋：這不是 outbound action surface。任何回答都不能送真 SOS、真簡訊、真衛星，也不能把 mock outbound 轉成真 transport。

中文註釋：這是跨介面資料狀態助理。不同 surface 可以給 AI 不同 context，但每個 context adapter 必須是 read-only、bounded、auditable。

## Surface Constraint Matrix

| Surface | Context adapter may read | Assistant may answer | Assistant must not do |
| --- | --- | --- | --- |
| `/admin/debug` | debug events, selected timeline node, `/debug/state`, `/debug/messages`, Phase 3.5 boundary snapshot | runtime timeline explanation, L0-L4 transition explanation, provider degraded status, mock outbound status, Ln gate and skill run visibility | mutate safety runtime, call `/safety/*`, send outbound, change debug log |
| `/admin` after-action | rendered evidence tree, incident package refs, map/evidence selection, Phase 2 preview snapshots | what happened, which evidence supports it, what persisted package or adapter output exists | rewrite historical incident/evidence, write Brain nodes, alter after-action package |
| `/admin/pretrip` | project manifest, candidates, source registry, review queue, readiness/departure gate artifacts | planning state, candidate provenance, missing review items, readiness blockers | accept/reject candidates, create reviewed facts, compile runtime handoff, approve departure |
| hardware readiness | provider health fixture, sample replay timeline, runtime debug log, mock transport queue | provider status, sample replay interpretation, debug readiness checklist | control hardware, change provider state, open real transport, start Pi/Docker deployment |

## Weather / Environment Evidence Across Surfaces

For route-weather and environment questions, the cross-surface assistant must
route through the Scout AI tool registry instead of prompt-only weather
reasoning.

Required tool layering:

- `scout.ai.weather_window.assess.v0` frames the weather/daylight/camp/shelter
  decision.
- `scout.ai.cwa_environment.assess.v0` reads prepared CWA warning,
  observation, QPF, forecast, astronomy, tide/marine, and provenance artifacts.
- `scout.ai.gee_environment.assess.v0` reads prepared GEE SMAP/GPM soil
  moisture, antecedent-rain, grid/timeline, and hydrologic corridor artifacts.

Surface-specific behavior:

- `/admin/pretrip`: may show CWA/GEE candidate evidence, missing/stale gaps,
  QPF peak windows, warning layers, SMAP/GPM corridor summaries, and
  go/no-go review inputs. It must not approve departure or promote those
  artifacts to runtime truth.
- `/admin/debug`: may explain which weather/environment evidence was available
  to the assistant and whether an answer was limited by stale/missing artifacts.
  It must not call live CWA/GEE or mutate debug/runtime state.
- `/admin`: may explain after-action provenance for weather/environment
  evidence used in an incident or post-trip review. It must not rewrite
  historical evidence or Brain facts.
- hardware readiness: may only display fixture-backed or operator-recorded
  weather/environment readiness evidence. It must not initialize Earth Engine,
  fetch live CWA, or start network research.

All weather/environment assistant answers must label CWA/GEE outputs as
candidate-only, human-review-required, and not runtime safety truth. If CWA QPF
or GEE SMAP/GPM evidence is missing or stale, the assistant reports that gap
and avoids saying conditions are safe.

## Route Context / Mileage / OCR Evidence Across Surfaces

For route-context, mileage-anchor, and OCR questions, the cross-surface
assistant must route through Scout workspace tools instead of prompt-only map
interpretation.

Required tool layering:

- `pydantic_ai.tool.assess_scout_route_context.v0` answers route-context,
  observation-point, and K/mileage anchor questions using
  `route_context_points_ref`, `route_mileage_k_anchors_ref`, and bounded
  `mileage_tag_alignment_ref` slices.
- `pydantic_ai.tool.search_scout_map_perception.v0` searches legacy MCP OCR,
  normalized raster OCR GeoJSON, contour labels, tile/source refs, and map
  perception candidates.
- `pydantic_ai.tool.search_scout_evidence_fulltext.v0` provides fallback
  full-text retrieval for mileage anchors, OCR labels, route notes, source
  snippets, and review/provenance records.

Surface-specific behavior:

- `/admin/pretrip`: may answer "15K 在哪", "OCR 讀到哪些地圖文字", or "哪些點值得停
  3 分鐘" using candidate-only workspace evidence. It must not write review
  decisions or rebuild the workspace.
- `/admin/debug`: may explain which route-context/OCR evidence was available to
  the assistant and why an answer is limited. It must not mutate debug/runtime
  state.
- `/admin`: may explain after-action route-context/OCR provenance. It must not
  rewrite historical evidence or Brain facts.
- Mac local chat fallback: may use the same read-only tool outputs when Scout
  hardware is unavailable, but it must label answers as local fallback model
  interpretation when a model was involved.

Raw raster tiles, raw OCR payloads, and full mileage alignment files must stay
out of model prompts and UI responses. Tool outputs should return bounded,
source-linked records with `candidate_only=true` and
`runtime_safety_truth=false`.

## Architecture

The milestone should introduce four concepts.

### 1. Assistant Request Contract

The request is a read-only query, even if transported as HTTP `POST` because it
contains a structured body.

Proposed shape:

```python
class ScoutAssistantQuery(BaseModel):
    surface: Literal["debug", "admin", "pretrip", "hardware_readiness"]
    question: str
    context_ref: str | None = None
    selected_event_id: str | None = None
    selected_artifact_id: str | None = None
    project_id: str | None = None
```

### 2. Assistant Response Contract

Every response must be explicitly labeled as interpretation:

```python
class ScoutAssistantResponse(BaseModel):
    answer: str
    surface: str
    model_interpretation: bool = True
    read_only: bool = True
    sources: list[AssistantSourceRef]
    boundary: AssistantBoundary
    limitations: list[str]
```

The response should never include a field that looks like a runtime command,
review decision, writeback instruction, outbound send request, or hardware
control request.

### 3. Surface Context Adapters

Each adapter owns one read-only projection:

- `debug_assistant_context.py`: debug timeline, selected event, debug state,
  messages, boundary snapshot.
- `admin_assistant_context.py`: after-action selected evidence, incident refs,
  Phase 2 preview snapshots.
- `pretrip_assistant_context.py`: project manifest, candidates, source registry,
  review queue, readiness and departure gate summaries.
- `hardware_readiness_assistant_context.py`: provider health, sample replay,
  runtime debug log, mock outbound queue.

Adapters should return compact context envelopes. They should not pass large raw
stores, raw GPX, raw SensorLog, raw website payloads, or secrets to the model.

### 4. Provider Layer

Provider support should be staged:

1. `mock`: deterministic, no model call, used for tests and UI contract.
2. `pydantic_ai`: opt-in provider behind environment flags.

Current Pydantic AI provider policy:

- supported runtime family: Pydantic AI v2.1.x;
- default model path: local `FunctionModel`;
- external OpenRouter model path: `openrouter:<vendor/model>` with
  `OPENROUTER_API_KEY`;
- direct OpenAI chat path: `openai-chat:<model>` with `OPENAI_API_KEY`;
- compatibility alias: `openai:<model>` is normalized to
  `openai-chat:<model>` to avoid an implicit switch to Responses API behavior;
- `end_strategy="early"` is required for typed Scout assistant calls;
- WebSearch and WebFetch are off by default. `SCOUT_AI_OS_NATIVE_RESEARCH=1`
  enables trusted no-per-query-approval candidate-only research.
- provider-native MCP remains off unless separately reviewed and permissioned.

Proposed flags:

```text
SCOUT_AI_ASSISTANT_ENABLED=1
SCOUT_AI_ASSISTANT_PROVIDER=mock|pydantic_ai
SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS=8
SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS=12000
SCOUT_AI_ASSISTANT_CONFIG_PATH=/secure/local/scout-assistant-models.json
```

The Pydantic AI provider should be separate from `/navigate`. It may reuse
shared model configuration, but it should have its own system prompt and tools
because `/navigate` is navigation advice while this assistant is read-only
state explanation.

When `pydantic_ai` is enabled, the server may load an external JSON model
configuration at startup. That file must define two profiles:

- `cloud_model`: the preferred cloud model, including `model_name`, optional
  `base_url`, `token_id`, and `token_env_var`;
- `local_model`: the fallback local model, including `model_name`, optional
  local `base_url`, and `token_id`.
- `fallback_to_local_on_error`: defaults to `true`; when set to `false`, Scout
  keeps the local model profile as configuration data but does not connect to or
  query the local model after cloud failure.

`token_id` is a token reference, not a secret payload. Secrets should stay in
environment variables referenced by `token_env_var`.

Startup behavior:

- try the cloud model connection first;
- if cloud communication fails or times out, fall back to the local model only
  when `fallback_to_local_on_error` is enabled;
- if provider startup or runtime execution fails, return a safe read-only
  assistant error response and leave the source surface unaffected.

### 4.1. Milestone 10.2: Cloud-to-Local Assistant Failover Guardrail

This follow-up guardrail connects the assistant provider contract to the Pi 5
local AI runtime evidence in `docs/specs/pi5-local-ai-runtime-experiment.md`.
The Pi experiment accepted `qwen2.5:0.5b` CPU-only inference as prototype
evidence for low-frequency offline fallback interpretation, not as safety
authority.

The contract is deliberately narrower than "run local AI everywhere":

- Mac/dev default remains mock or cloud-only.
- A Pi field profile may opt in to local fallback only through an external model
  config with `SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai` and
  `fallback_to_local_on_error=true`.
- The assistant readiness gate and browser smoke checks must not start Ollama,
  Pi services, Docker, k3s, MQTT, NATS, Coral, Jetson, hardware providers, or
  local model runners.
- If cloud communication fails or times out, the assistant may use the local
  model only for the current read-only query. It must not switch global provider
  state, expose a UI model switch, or change source-surface state.
- If the local model is unavailable or too slow, the result is a safe assistant
  failure response, not a delayed safety/runtime action.

Required local fallback constraints:

- max local concurrency = 1;
- short timeout, initially 6-10s;
- no unbounded queue;
- discard stale model requests instead of delaying Phase 1 runtime, UI state, or
  source-surface behavior;
- local output remains `read-only model interpretation`;
- never let local AI directly change L0-L4 safety state;
- never let local AI directly trigger SOS, evacuation, route-deviation,
  provider-control, review, departure, outbound, or hardware actions.

Required provenance for any future live fallback response:

- `model_profile_used`;
- `failover_reason`;
- `local_model_name`;
- latency or timeout class;
- startup connection status;
- context budget used;
- token reference metadata only, never token values.

Slice 1 acceptance:

- this spec names the Pi experiment as prototype evidence while preserving the
  assistant read-only boundary;
- the readiness gate checks these contract tokens;
- no local model listener is started by readiness checks;
- no provider code is changed to perform live Ollama calls in this slice.

Slice 2 provider hardening acceptance:

- `FallbackPydanticAIRunner` limits local fallback with `max_fallback_concurrency`
  and rejects overlapping local requests as `LocalFallbackBusy`;
- stale local fallback requests are discarded with
  `local_busy:discard_stale_request` rather than queued;
- primary cloud failures are recorded as `primary_run_error:*` or
  `primary_connect_error:*`;
- local fallback failures are recorded as `local_run_error:*` and are isolated
  by `/assistant/query` as safe read-only provider failures;
- `AssistantObservability` can expose `model_profile_used`, `failover_reason`,
  and `local_model_name` without token values;
- all tests use mocked runners only and do not require live Ollama, Pi, Docker,
  hardware providers, network connectivity, or local model listeners.

Slice 12 fixed-schema offline fallback provider contract acceptance:

- `assistant_offline_fallback_contract.py` defines
  `ScoutOfflineFallbackInterpretation` with
  `schema_version=scout.offline_fallback.v1` and
  `prompt_id=scout.offline_fallback.fixed_schema.v1`;
- local fallback prompts require one JSON object and set `read_only=true`,
  `model_interpretation=true`, `safety_authority=false`,
  `phase1_state_change_allowed=false`, `observed_fact_write_allowed=false`,
  `outbound_action_allowed=false`, and `hardware_control_allowed=false`;
- `FallbackPydanticAIRunner` can enforce the fixed schema on the local fallback
  path and records `fixed_schema_offline_fallback_contract`;
- invalid local fallback schema output fails safely as
  `local_schema_validation_error:*`;
- this remains provider-contract work only: no local model listener startup, no
  `/safety/*` mutation, no Scout state writes, no outbound send, and no
  hardware/provider control.

Milestone 10.2 Slice 3: Pi Field Profile Status + Manual Failover Runbook

Slice 3 status/runbook acceptance:

- `/assistant/status` reports `SCOUT_RUNTIME_PROFILE=pi-field` as
  `runtime_profile=pi-field` without changing provider state;
- when external config has `fallback_to_local_on_error=true`,
  `/assistant/status` reports `local_fallback_mode=pi_field_manual_opt_in`,
  `manual_verification_required=true`, and `local_fallback_max_concurrency=1`;
- when the same fallback config is loaded under Mac/dev profile,
  `/assistant/status` reports `local_fallback_mode=configured_not_pi_field`
  rather than treating local fallback as a field-approved runtime path;
- status output must keep `readiness_starts_local_model=false`,
  `local_model_listener_required_for_readiness=false`, and
  `status_model_switch_allowed=false`;
- manual Pi/Ollama verification is documented as hardware prototype work and is
  not part of the assistant readiness gate;
- this slice must not start a local model listener, run Ollama, require Pi
  hardware, switch provider from status, expose token values, or weaken the
  read-only assistant boundary.

Milestone 10.2 Slice 4: Manual Pi/Ollama Verification Artifact

Slice 4 manual artifact acceptance:

- `docs/admin/pi-ollama-manual-verification.md` exists as a hardware prototype
  track artifact, not a readiness-gate requirement;
- the artifact records manual_only_pi_ollama_verification evidence shape,
  including `operator_observed_latency_ms`, assistant status excerpts, and
  boundary observations;
- the artifact documents safe manual command shape for already-running Pi/Ollama
  services without asking Scout, CI, browser smoke, or readiness checks to start
  Ollama;
- recorded status must include `token_values_exposed=false`,
  `status_model_switch_allowed=false`, and local fallback provenance without
  token values;
- recorded boundaries must include `phase1_state_changed=false`,
  `observed_fact_written=false`, `outbound_sent=false`, and
  `hardware_controlled=false`;
- manual Pi/Ollama verification remains not part of the assistant readiness gate
  and must stay outside the assistant readiness gate.

Milestone 10.2 Slice 5: Manual Verification Result Schema / Example Fixture

Slice 5 schema acceptance:

- `pi_ollama_manual_verification.py` defines a strict offline Pydantic schema
  for manual Pi/Ollama observation results;
- `tests/fixtures/hardware/pi_ollama_manual_verification.example.json` provides
  an optional operator-recorded fixture example with no secret values and no raw
  model transcript;
- the schema accepts only `manual_only_pi_ollama_verification`,
  `runtime_profile=pi-field`, `assistant_provider=pydantic_ai`,
  `fallback_to_local_on_error=true`, and `ollama_tags_checked=true`;
- the schema requires `operator_observed_latency_ms` as manual evidence, not
  Scout runtime state;
- assistant status observation requires `token_values_exposed=false`,
  `readiness_starts_local_model=false`,
  `local_model_listener_required_for_readiness=false`, and
  `status_model_switch_allowed=false`;
- boundary observation requires `phase1_state_changed=false`,
  `observed_fact_written=false`, `phase2_brain_written=false`,
  `incident_store_written=false`, `outbound_sent=false`, and
  `hardware_controlled=false`;
- the schema module must remain offline-only: no network calls, no `/safety/*`
  mutation, no store writes, no provider control, and no local model startup;
- this optional operator-recorded fixture remains not part of the assistant
  readiness gate.

Milestone 10.2 Slice 6: Manual Verification Summary Formatter

Slice 6 formatter acceptance:

- `format_pi_ollama_manual_verification_summary` converts a validated
  `PiOllamaManualVerificationResult` into a bounded human-readable report headed
  `Manual Pi/Ollama verification summary`;
- the report includes runtime profile, assistant provider, local model name,
  `operator_observed_latency_ms`, local fallback status, model interpretation
  flags, and mutation boundary flags;
- the report keeps `readiness_starts_local_model=false`,
  `local_model_listener_required_for_readiness=false`,
  `status_model_switch_allowed=false`, `token_values_exposed=false`,
  `phase1_state_changed=false`, `observed_fact_written=false`,
  `outbound_sent=false`, and `hardware_controlled=false`;
- the report must not expose config paths, token ids, token env vars, API keys,
  bearer strings, or secret-like values;
- the formatter remains offline-only: no network calls, no `/assistant/*`
  calls, no `/safety/*` mutation, no store writes, no provider control, and no
  local model startup;
- this summary is an optional operator-recorded fixture report and remains not
  part of the assistant readiness gate.

Milestone 10.2 Slice 7: Optional Manual Verification Index

Slice 7 index acceptance:

- `PiOllamaManualVerificationIndex` defines an optional append-only index for
  multiple operator-recorded Pi/Ollama verification fixture references;
- `tests/fixtures/hardware/pi_ollama_manual_verification.index.example.json`
  provides a small secret-free example that references the optional result
  fixture rather than embedding raw model output;
- entries store only `summary_ref`, repo-relative `fixture_path`, timestamp,
  runtime profile, local model name, observed latency, read-only/model
  interpretation flags, and non-mutation boundary flags;
- index validation rejects raw output fields, absolute paths, parent-directory
  paths, secret-like values, and any mutation boundary claim;
- `summarize_pi_ollama_manual_verification_index` renders a bounded text report
  headed `Manual Pi/Ollama verification index summary`;
- the index remains offline-only: no network calls, no `/assistant/*` calls, no
  `/safety/*` mutation, no store writes, no provider control, and no local model
  startup;
- this optional append-only index remains not part of the assistant readiness
  gate.

Milestone 10.2 Slice 8: Read-Only Manual Verification CLI Renderer

Slice 8 CLI acceptance:

- `pi_ollama_manual_verification_cli.py` renders validated optional manual
  result files with `--result`;
- the same CLI renders validated optional manual index files with `--index`;
- `--result` and `--index` are mutually exclusive;
- the CLI prints summaries to stdout only and does not write files;
- the CLI remains offline-only: no network calls, no `/assistant/*` calls, no
  `/safety/*` mutation, no store writes, no provider control, and no local model
  startup;
- this read-only CLI renderer remains not part of the assistant readiness gate.

Milestone 10.2 Slice 9: Operator Checklist

Slice 9 checklist acceptance:

- `docs/admin/pi-ollama-manual-verification.md` includes an operator checklist
  for the optional manual result, optional append-only index, and read-only CLI
  renderer flow;
- the checklist includes `checked_by_operator`, `validate result fixture`,
  optional index validation, and `run read-only CLI renderer`;
- the checklist may observe `assistant_readiness_check.py --pretty`, but must not
  add optional manual result/index/CLI artifacts to readiness required paths;
- the checklist records no local model startup, no token value reading, no Scout
  state writes, and no hardware/provider control;
- the checklist remains documentation/test-only and not part of the assistant
  readiness gate.

Milestone 10.2 Slice 10: Cross-Surface Runbook Consolidation

Slice 10 consolidation acceptance:

- `docs/admin/cross-surface-ai-assistant-runbook.md` includes a manual
  Pi/Ollama artifact chain summary;
- the cross-surface runbook points to `docs/admin/pi-ollama-manual-verification.md`,
  `pi_ollama_manual_verification.py`, result fixture, index fixture,
  `pi_ollama_manual_verification_cli.py`, and the operator checklist;
- the cross-surface runbook states the manual chain is not part of the assistant
  readiness gate;
- the cross-surface runbook repeats the key runtime boundaries: no local model
  startup, no Ollama startup, no `/assistant/*` calls, no `/safety/*` mutation,
  no ObservedFact, no Phase 2 Brain write, no IncidentStore write, no outbound,
  no hardware control, and no provider control.

## API Boundary

Proposed endpoint:

```text
POST /assistant/query
```

This endpoint is read-only. It is allowed to use `POST` only to carry a query
body. It must not write application state.

Default behavior:

- endpoint not mounted unless `SCOUT_AI_ASSISTANT_ENABLED=1`;
- provider defaults to `mock`;
- unsupported surface returns a structured error;
- provider failure returns a safe error response and does not affect source
  surface behavior.

Forbidden:

- `PUT`, `PATCH`, `DELETE` for assistant APIs;
- request fields such as `action`, `approve`, `send`, `write_fact`, `mutate`,
  `control_provider`;
- automatic store writes from assistant response.

## UI Boundary

The shared UI should be an assistant drawer/panel that can be embedded in
multiple surfaces.

Required behavior:

- visible surface label, for example `debug assistant` or `pretrip assistant`;
- visible boundary label: `read-only model interpretation`;
- source list or citation chips for the context used;
- no mutation or apply/action buttons in the first milestone;
- response can be copied or inspected, but not applied.

Milestone 10.1 adds live read-only query controls. These controls may include a
question text area, suggested question buttons, and an `Ask read-only assistant`
submit button. They must only call `POST /assistant/query` and must never use
action-like fields such as `approve`, `send`, `write_fact`, `mutate`, or
`control_provider`.

Initial UI order:

1. Debug surface, because Phase 3.5 already has selected timeline context.
2. Pre-trip planning surface, because candidate/review/source state benefits
   from explanation.
3. After-action admin surface.

## Prompt Boundary

The system prompt must include:

- Scout is a wilderness safety system.
- Phase 1 deterministic safety decisions are authoritative.
- The assistant explains state and evidence only.
- The assistant must not invent facts or claim actions happened.
- The assistant must cite source refs from the provided context.
- The assistant must label uncertain answers and missing context.
- The assistant must refuse requests to mutate runtime, Brain, review state,
  outbound transport, or hardware.

Surface prompts may add narrower constraints, but must not loosen the global
boundary.

## Milestone Slices

### Slice 1: Spec And Contract

Files:

- `docs/specs/scout-cross-surface-ai-assistant.md`
- assistant Pydantic request/response models;
- contract tests.

Acceptance:

- surfaces and constraints are represented in typed models;
- response always includes `model_interpretation=true` and `read_only=true`;
- unsupported surfaces fail safely.

### Slice 2: Mock Assistant Provider

Files:

- `assistant_provider.py`
- `tests/test_assistant_provider.py`

Acceptance:

- deterministic mock answers for debug/admin/pretrip/hardware readiness;
- no network calls;
- no store writes;
- source refs are echoed in the response.

### Slice 3: Context Adapter Foundation

Files:

- `debug_assistant_context.py`
- `admin_assistant_context.py`
- `pretrip_assistant_context.py`
- `tests/test_*assistant_context.py`

Acceptance:

- each adapter returns bounded read-only context;
- adapters do not import live safety mutation paths;
- pretrip adapter does not write review decisions or `ObservedFact`.

### Slice 4: Read-Only Assistant API

Files:

- `assistant_api.py`
- `server.py`
- `tests/test_assistant_api.py`

Acceptance:

- `/assistant/query` is mounted only when opt-in is enabled;
- default provider is mock;
- no mutation methods exist;
- provider failure is isolated.

### Slice 5: Shared Assistant UI Shell

Files:

- shared static UI script or per-page embedded shell, following current admin
  static HTML conventions;
- debug and pretrip integration tests.

Acceptance:

- drawer/panel can be embedded in `/admin/debug` and `/admin/pretrip`;
- it shows surface, boundary, answer, limitations, and sources;
- it has no action controls.
- debug timeline selection updates three suggested assistant questions, including
  a checkpoint/level explanation prompt such as `Why did CP2 become an L2
  event?`.

### Slice 6: Pydantic AI Opt-In Provider

Files:

- `assistant_pydantic_provider.py`
- prompt fixtures;
- provider tests with mocked model execution.

Acceptance:

- enabled only by `SCOUT_AI_ASSISTANT_ENABLED=1` and
  `SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai`;
- timeout and context budget are enforced;
- prompt injection attempts cannot loosen boundaries;
- response remains `ModelInterpretation`/debug explanation only.

### Slice 7: Acceptance Gate And Runbook

Files:

- optional `assistant_readiness_check.py`;
- docs/admin assistant runbook.

Acceptance:

- focused tests pass;
- no Phase 1 safety mutation;
- no `ObservedFact` writes from assistant output;
- no outbound sends;
- mock provider works without network;
- Pydantic AI provider remains disabled by default.

### Slice 8: Milestone 10.1 Live Assistant UI Query

Files:

- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase4-pretrip-planning.html`
- `tests/test_assistant_page.py`

Acceptance:

- debug assistant suggestions are clickable and query the selected timeline
  context through `POST /assistant/query`;
- pretrip assistant can query the current project and selected artifact through
  `POST /assistant/query`;
- UI renders assistant answer, limitations, sources, loading, and safe failure
  states;
- query body contains only read-only fields: `surface`, `question`,
  `context_ref`, `selected_event_id`, `selected_artifact_id`, and `project_id`;
- no UI control accepts/rejects candidates, writes facts, sends outbound,
  changes Phase 1/2 state, or controls hardware.

### Slice 9: Selected Debug Event Detail Context

Files:

- `assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`
- `tests/test_assistant_pydantic_provider.py`

Acceptance:

- debug assistant context includes the selected timeline event's compact
  `kind`, `summary`, and `payload` in the assistant context source;
- Pydantic prompt construction receives that selected event detail through
  `AssistantSourceRef.context_summary`;
- no runtime event log, Phase 1 decision, Phase 2 Brain, IncidentStore,
  outbound transport, review decision, or hardware state is mutated.

### Slice 10: Selected Pretrip Evidence Detail Context

Files:

- `assistant_context.py`
- `pretrip_assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`
- `tests/test_assistant_pydantic_provider.py`

Acceptance:

- pretrip assistant context includes the selected planning evidence's compact
  `source_id`, `evidence_type`, `category`, `priority`, `candidate_ref`,
  `review_focus`, and `map_target_ids` in the assistant context source;
- Pydantic prompt construction receives that selected evidence detail through
  `AssistantSourceRef.context_summary`;
- the selected evidence remains explanatory only: it cannot accept/reject
  candidates, write review state, compile runtime handoff, write Brain facts, or
  approve departure.

### Slice 11: Context-Aware Suggested Questions

Files:

- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase4-pretrip-planning.html`
- `tests/test_assistant_page.py`

Acceptance:

- debug assistant suggestions update from the selected timeline event and remain
  deterministic UI text, not model-generated commands;
- pretrip assistant suggestions update from the selected planning evidence and
  remain deterministic UI text;
- suggested question buttons only call the existing read-only
  `POST /assistant/query` path;
- no suggested question button accepts/rejects candidates, sends outbound,
  writes facts, mutates providers, or opens runtime handoff.

### Slice 12: Selected After-Action Admin Evidence Detail Context

Files:

- `admin_assistant_context.py`
- `assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`
- `tests/test_assistant_pydantic_provider.py`

Acceptance:

- admin after-action assistant context includes the selected evidence's compact
  `source_id`, `evidence_type`, `label`, and `reason` when available;
- Pydantic prompt construction receives that selected evidence detail through
  `AssistantSourceRef.context_summary`;
- the selected after-action evidence remains historical and read-only: no
  IncidentStore, Brain, review, outbound, or Phase 1 state is mutated.

### Slice 13: Assistant Provider Status Surface

Files:

- `assistant_api.py`
- `server.py`
- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase4-pretrip-planning.html`
- `tests/test_assistant_api.py`
- `tests/test_assistant_page.py`

Acceptance:

- `GET /assistant/status` is available only when the assistant API is mounted;
- provider status reports read-only metadata such as provider class, startup
  connection status, config-loaded state, cloud-only state, and context budget;
- token values, API keys, and secret payloads are never returned or rendered;
- UI displays provider status as operational context only and offers no provider
  controls.

### Slice 14: Assistant Context Transparency Panel

Files:

- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase4-pretrip-planning.html`
- `tests/test_assistant_page.py`

Acceptance:

- assistant UI renders a context panel showing surface, selected context refs,
  source count, and selected source summaries from the last response;
- context transparency uses response/source refs already returned by
  `/assistant/query`; it does not fetch raw stores or secrets;
- failed assistant queries still show the intended selected context ref while
  preserving safe-failure wording.

### Slice 15: Shared Assistant UI Module

Files:

- `docs/admin/scout-assistant-ui.js`
- `admin_api.py`
- `debug_api.py`
- `docs/admin/phase-3-5-runtime-debug.html`
- `docs/admin/phase4-pretrip-planning.html`
- `tests/test_assistant_page.py`

Acceptance:

- common assistant fetch, POST query, provider-status rendering, source-list
  rendering, and prompt button binding live in a shared static admin module;
- pages still send only read-only query fields to `POST /assistant/query`;
- the shared module does not expose token values and does not add action
  controls.

### Slice 16: Admin After-Action Live Assistant UI

Files:

- `docs/admin/phase1-after-action.html`
- `tests/test_assistant_page.py`
- `tests/test_admin_after_action.py`

Acceptance:

- `/admin` after-action evidence selection can feed `surface="admin"`,
  `context_ref`, and selected evidence id into the read-only assistant query;
- the UI renders answer, limitations, sources, provider status, suggested
  questions, and context transparency;
- selected after-action evidence remains historical and immutable: no
  IncidentStore, Brain, Phase 1, outbound, review, or hardware state is changed.

### Slice 17: Hardware Readiness Fixture-Backed Context

Files:

- `tests/fixtures/hardware/readiness_context.json`
- `hardware_readiness_admin_view.py`
- `assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`

Acceptance:

- hardware readiness has a repo fixture for provider health, sample replay,
  runtime debug events, and mock transport queue;
- server-side assistant context can answer `surface="hardware_readiness"` from
  bounded fixture-backed context;
- no hardware provider, Pi/Docker deployment, event bus, accelerator, real SOS,
  SMS, satellite, or outbound transport is opened.

### Slice 18: Hardware Readiness Read-Only UI

Files:

- `hardware_readiness_api.py`
- `server.py`
- `docs/admin/phase-3-6-hardware-readiness.html`
- `tests/test_hardware_readiness_api.py`
- `tests/test_assistant_page.py`

Acceptance:

- `/admin/hardware-readiness` serves a read-only fixture-backed hardware
  readiness surface;
- `/admin/hardware-readiness/context` is GET-only and returns read-only
  provider/replay/mock-queue context;
- the assistant UI uses the shared module and offers no deploy, provider
  control, hardware control, or transport controls.

### Slice 19: Boundary Red-Team Tests

Files:

- `assistant_provider.py`
- `assistant_pydantic_provider.py`
- `tests/test_assistant_provider.py`
- `tests/test_assistant_pydantic_provider.py`

Acceptance:

- mock and Pydantic AI providers constrain prompt-injection and mutation intent
  such as accepting candidates, writing ObservedFact/Brain, calling
  `/safety/*`, sending SOS/SMS/satellite, controlling providers, or starting
  deployment;
- constrained answers remain `read_only=true` and
  `model_interpretation=true`;
- every boundary flag for Phase 1, Phase 2, IncidentStore, review, outbound,
  SOS/SMS/satellite, and hardware remains false.

### Slice 20: Assistant Observability Without State Writes

Files:

- `assistant_models.py`
- `assistant_api.py`
- `docs/admin/scout-assistant-ui.js`
- `tests/test_assistant_models.py`
- `tests/test_assistant_api.py`
- `tests/test_assistant_page.py`

Acceptance:

- `/assistant/query` responses may include `AssistantObservability`, a
  non-authoritative metadata object for provider class, source count, selected
  source count, context size, latency class, and safe-failure state;
- observability never includes token values, API keys, raw stores, writeback
  instructions, runtime commands, review decisions, outbound send requests, or
  hardware control requests;
- assistant UIs may display observability in the context panel, but no Scout
  runtime, Brain, review, IncidentStore, outbound, or hardware state is written.

### Slice 21: After-Action UI Selection Alias Context

Files:

- `admin_assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`

Acceptance:

- `/admin` after-action UI-only ids such as `route`, `map_corridors`,
  `map_hazards`, and `map_pois` resolve to compact read-only evidence
  summaries for assistant context;
- mission segment ids such as `seg_01` resolve to compact segment metadata
  without embedding raw samples or geometry;
- alias resolution is only a context projection and does not rewrite
  after-action packages, IncidentStore records, Brain data, Phase 1 decisions,
  review state, outbound transport, or hardware state.

### Slice 22: Hardware Readiness Assistant Runbook

Files:

- `docs/admin/hardware-readiness-assistant-runbook.md`
- `tests/test_hardware_readiness_runbook.py`
- `assistant_readiness_check.py`

Acceptance:

- hardware readiness assistant operation is documented as
  fixture-backed/read-only for `/admin/hardware-readiness` and
  `/admin/hardware-readiness/context`;
- the runbook explicitly blocks Pi/Docker/k3s/MQTT/NATS/Coral/Jetson startup,
  provider/model switching, token value reads, real SOS/SMS/satellite, and
  outbound transport;
- the readiness gate checks the runbook tokens without starting local models,
  hardware, providers, or transports.

### Slice 23: Assistant UI Static Smoke Gate

Files:

- `assistant_ui_smoke_check.py`
- `tests/test_assistant_ui_smoke_check.py`
- `assistant_readiness_check.py`

Acceptance:

- the static smoke gate checks debug, pretrip, after-action admin, and hardware
  readiness assistant shells without requiring a browser;
- every assistant shell must include the shared UI script, `/assistant/query`,
  `/assistant/status`, Context, Limitations, Sources, and the read-only model
  interpretation boundary;
- action-like assistant shell buttons such as accept, approve, reject, send,
  write, mutate, and control fail the smoke gate.

### Slice 24: Map-Layer Source Labels

Files:

- `admin_assistant_context.py`
- `tests/test_assistant_context.py`
- `tests/test_assistant_api.py`

Acceptance:

- after-action map UI aliases `map_corridors`, `map_hazards`, and `map_pois`
  resolve to `map_layer_summary` context with a readable layer label,
  selected layer id, layer evidence type, count, and bounded sample labels;
- map-layer context does not embed raw coordinates, polygons, raw GPX samples,
  or full map geometry;
- the selected map layer remains after-action explanation only and cannot
  mutate IncidentStore, Brain, Phase 1 state, review state, outbound transport,
  or hardware.

### Slice 25: Browser Visual QA

Files:

- `docs/admin/screenshots/assistant-browser-smoke-debug.jpg`
- `docs/admin/screenshots/assistant-browser-smoke-pretrip.jpg`
- `docs/admin/screenshots/assistant-browser-smoke-admin.jpg`
- `docs/admin/screenshots/assistant-browser-smoke-hardware-readiness.jpg`
- `docs/admin/screenshots/assistant-browser-live-debug.jpg`
- `docs/admin/screenshots/assistant-browser-live-pretrip.jpg`
- `docs/admin/screenshots/assistant-browser-live-admin.jpg`
- `docs/admin/screenshots/assistant-browser-live-hardware-readiness.jpg`

Acceptance:

- Browser opens `/admin/debug`, `/admin/pretrip`, `/admin`, and
  `/admin/hardware-readiness` against the local opt-in assistant server;
- each surface has a visible assistant shell with
  `data-assistant-boundary="read-only model interpretation"`;
- live query smoke renders answer/context/limitations/sources or an isolated
  safe assistant failure without source-surface mutation;
- no local model listener is started and no assistant shell exposes mutation or
  provider/hardware controls.

### Slice 26: Browser Smoke Runbook

Files:

- `docs/admin/assistant-browser-smoke.md`
- `tests/test_assistant_browser_smoke_doc.py`
- `assistant_readiness_check.py`

Acceptance:

- Browser smoke results, screenshots, environment, and manual recheck steps are
  documented for all assistant surfaces;
- the document records cloud-only assistant config, no token values rendered,
  no local model listener, and all Milestone 10 read-only boundaries;
- readiness checks include the browser smoke document so future assistant UI
  changes do not silently drop the browser QA trail.

## Testing Strategy

Focused tests should cover:

- request/response validation;
- per-surface constraints;
- mock provider deterministic output;
- context adapter bounded projection;
- no forbidden imports in assistant foundation;
- API opt-in mount and method boundary;
- prompt injection resistance for provider layer;
- boundary red-team cases across all surfaces;
- UI has no mutation controls;
- live UI query controls use only the read-only `/assistant/query` body fields.
- observability metadata remains non-authoritative and secret-free.

Verification commands should follow this shape:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_assistant_model_config.py \
  tests/test_assistant_models.py \
  tests/test_assistant_provider.py \
  tests/test_assistant_pydantic_provider.py \
  tests/test_assistant_context.py \
  tests/test_assistant_api.py \
  tests/test_assistant_page.py \
  tests/test_hardware_readiness_api.py \
  tests/test_hardware_readiness_runbook.py \
  tests/test_assistant_ui_smoke_check.py \
  tests/test_assistant_browser_smoke_doc.py \
  tests/test_assistant_readiness_check.py

/Users/alexwang0315/scout-fusion/venv/bin/python assistant_readiness_check.py --pretty

/Users/alexwang0315/scout-fusion/venv/bin/python assistant_ui_smoke_check.py --pretty
```

## Success Criteria

Milestone 10 is complete when:

- admin/debug/pretrip/hardware-readiness surfaces have distinct constraints;
- the assistant can answer data-state questions from bounded context;
- default implementation works with deterministic mock provider;
- Pydantic AI provider is opt-in and failure-isolated;
- no assistant response can mutate Phase 1, Phase 2 Brain, IncidentStore,
  pretrip review state, outbound transport, or hardware;
- model output is never written as `ObservedFact`;
- UI clearly labels assistant answers as read-only model interpretation.
- `AssistantObservability` is available only as read-only operational metadata
  and is never used as Scout state.
- assistant UI shells pass the static smoke gate and remain free of mutation
  controls.
- browser-backed smoke evidence exists for all assistant surfaces.

Milestone 10.1 is complete when:

- `/admin/debug` and `/admin/pretrip` can issue live read-only assistant
  queries when `SCOUT_AI_ASSISTANT_ENABLED=1`;
- selected timeline or selected pretrip evidence is included as context refs;
- answer, limitations, and sources render from the API response;
- API errors are displayed as isolated assistant failures without changing the
  source surface;
- all Milestone 10 guardrails above remain true.

Milestone 10.2 surface expansion is complete when:

- `/admin` after-action and `/admin/hardware-readiness` can use the same
  read-only assistant capability;
- hardware readiness remains fixture-backed and does not start real hardware,
  provider, transport, deployment, or local model runners;
- shared UI helpers reduce duplication without weakening page-specific
  surface constraints;
- red-team mutation prompts are constrained across mock and Pydantic AI
  provider paths.

Milestone 10.2 Slice 1 cloud-to-local failover contract is complete when:

- the assistant spec references `docs/specs/pi5-local-ai-runtime-experiment.md`
  and keeps Pi local inference as low-frequency offline fallback interpretation;
- Mac/dev default remains mock or cloud-only, while Pi field profile fallback
  requires explicit `fallback_to_local_on_error=true`;
- fallback constraints include max local concurrency = 1, short timeout,
  initially 6-10s, no unbounded queue, and discard stale model requests;
- future live fallback responses must expose `model_profile_used`,
  `failover_reason`, and `local_model_name` as provenance without token values;
- no local model listener is started by readiness checks, and no provider,
  hardware, transport, deployment, or Phase 1 safety behavior changes in this
  slice.

Milestone 10.2 Slice 2 provider failover hardening is complete when:

- mocked cloud failures fall back to a mocked local runner and add
  `model_profile_used`, `failover_reason`, and `local_model_name` provenance;
- overlapping local fallback requests fail fast instead of building an unbounded
  queue;
- local fallback runner failure returns a safe assistant failure through
  `/assistant/query`;
- the readiness gate checks the hardening tokens without starting local model,
  hardware, transport, or deployment services.

Milestone 10.2 Slice 12 fixed-schema offline fallback provider contract is
complete when:

- `ScoutOfflineFallbackInterpretation` validates local fallback output as a
  bounded JSON model interpretation rather than free-form safety advice;
- the local fallback prompt names `scout.offline_fallback.v1` and
  `scout.offline_fallback.fixed_schema.v1`;
- Pydantic provider fallback can enforce the schema and expose
  `fixed_schema_offline_fallback_contract` provenance;
- invalid local fallback schema output becomes a safe provider failure, not a
  safety/runtime action;
- verification uses mocked runners only and does not start Pi, Ollama, local
  model listeners, transport, or hardware/provider services.

Milestone 10.2 Slice 13 mocked offline fallback adapter/UI formatting is
complete when:

- `ScoutAssistantResponse` can carry an `offline_fallback` structured summary
  for fixed-schema local fallback results;
- `PydanticAIAssistantProvider` attaches the parsed local fallback
  interpretation to the response when schema enforcement succeeds;
- shared assistant UI helpers expose `offlineFallbackItems` and
  `renderOfflineFallback` so pages can render schema output without action
  buttons;
- the payload preserves `read_only=true`, `model_interpretation=true`, and
  `safety_authority=false`;
- verification uses mocked runners only and does not start Pi, Ollama, local
  model listeners, transport, or hardware/provider services.

Milestone 10.2 Slice 14 assistant shell offline fallback panels are complete
when:

- debug, pretrip, admin after-action, and hardware readiness assistant shells
  each include an `Offline fallback` read-only panel;
- each shell renders `offline_fallback` through the shared
  `renderOfflineFallback` helper after successful `/assistant/query`;
- failed assistant queries reset the panel to the safe no-schema placeholder;
- the static UI smoke gate requires the `Offline fallback` shell token across
  all assistant surfaces;
- verification remains static/browser-free and does not start Pi, Ollama, local
  model listeners, transport, or hardware/provider services.

Milestone 10.2 Slice 3 Pi field profile status/runbook is complete when:

- `/assistant/status` reports runtime profile, local fallback mode, manual
  verification requirement, and max fallback concurrency without exposing token
  values;
- `SCOUT_RUNTIME_PROFILE=pi-field` is the only status mode that labels local
  fallback as `pi_field_manual_opt_in`;
- Mac/dev fallback config is visible as `configured_not_pi_field`, not silently
  treated as a Pi field profile;
- status fields explicitly show `readiness_starts_local_model=false`,
  `local_model_listener_required_for_readiness=false`, and
  `status_model_switch_allowed=false`;
- manual Pi/Ollama verification remains in the hardware prototype track and is
  not part of the assistant readiness gate.

Milestone 10.2 Slice 4 manual Pi/Ollama verification artifact is complete when:

- `docs/admin/pi-ollama-manual-verification.md` describes a manual-only
  hardware prototype artifact and is not added to the assistant readiness
  required-path list;
- the artifact includes `manual_only_pi_ollama_verification`,
  `operator_observed_latency_ms`, and status/boundary fields for local fallback
  observation;
- the artifact blocks `/safety/*` mutation, Phase 1 safety changes,
  ObservedFact writes, Phase 2 Brain writes, IncidentStore writes, pretrip
  review changes, outbound send, and hardware/provider control;
- focused doc tests verify the artifact without starting Pi, Ollama, local model
  listeners, hardware services, transport, or model provider switches.

Milestone 10.2 Slice 5 manual verification schema is complete when:

- `pi_ollama_manual_verification.py` loads the example fixture and rejects
  secret-like values, mutation boundary changes, readiness-started local model
  claims, and status provider-switch claims;
- `tests/fixtures/hardware/pi_ollama_manual_verification.example.json` stays
  small, optional, secret-free, and outside `assistant_readiness_check.py`
  required paths;
- focused tests cover the schema, example fixture, docs, and offline/no-mutation
  source boundary without starting Pi, Ollama, local model listeners, hardware
  services, transport, or model provider switches.

Milestone 10.2 Slice 6 manual verification summary formatter is complete when:

- `format_pi_ollama_manual_verification_summary` renders the optional validated
  fixture as a concise human-readable report;
- the report includes local fallback status, latency, read-only/model
  interpretation flags, and all required non-mutation flags;
- the report excludes config paths and secret-related references;
- focused tests verify the formatter, docs, and offline/no-mutation source
  boundary without starting Pi, Ollama, local model listeners, hardware
  services, transport, or model provider switches.

Milestone 10.2 Slice 7 optional manual verification index is complete when:

- `PiOllamaManualVerificationIndex` loads the example index and rejects raw
  model output, absolute fixture paths, secret-like values, and mutation
  boundary claims;
- the example index stays small, optional, secret-free, and outside
  `assistant_readiness_check.py` required paths;
- the index summary reports fixture refs and boundary flags without embedding
  raw model output or secret-bearing fields;
- focused tests verify the index, docs, and offline/no-mutation source boundary
  without starting Pi, Ollama, local model listeners, hardware services,
  transport, or model provider switches.

Milestone 10.2 Slice 8 read-only CLI renderer is complete when:

- the CLI prints result and index summaries for the optional example fixtures;
- invalid combined `--result` and `--index` usage exits non-zero through
  argparse;
- focused tests verify the CLI source has no network/API/safety/runtime write
  path and the CLI is outside `assistant_readiness_check.py` required paths;
- verification does not start Pi, Ollama, local model listeners, hardware
  services, transport, or model provider switches.

Milestone 10.2 Slice 9 operator checklist is complete when:

- the runbook has an operator checklist that ties together result fixture
  validation, optional index validation, and the CLI renderer;
- focused tests verify the checklist text, phase/runtime boundaries, and
  readiness non-coupling;
- verification remains documentation/test-only and does not start Pi, Ollama,
  local model listeners, hardware services, transport, or model provider
  switches.

Milestone 10.2 Slice 10 cross-surface runbook consolidation is complete when:

- the cross-surface runbook summarizes the manual Pi/Ollama artifact chain in
  one place;
- focused tests verify the runbook links the result schema, optional fixtures,
  CLI renderer, and operator checklist while preserving assistant guardrails;
- verification remains documentation/test-only and does not start Pi, Ollama,
  local model listeners, hardware services, transport, or model provider
  switches.

Milestone 10.2 Slice 11 hardware experiment assets are complete when:

- `docker-compose.pi.ai.yml` defines the optional `scout-ollama` service under
  the `ai-experimental` Compose profile;
- `tools/pi_ollama_stress.py` is a manual stress probe for an already-running
  Ollama listener and does not call Scout APIs;
- the assets are not part of the assistant readiness gate;
- verification preserves read-only model interpretation, 不啟動本地模型 from
  readiness checks, 不呼叫 `/safety/*` mutation, no Scout state writes, no
  outbound send, and no hardware/provider control.

After Milestone 10.2 Slice 11, the hardware experiment assets remain optional
operator-run evidence and must not be promoted into the assistant readiness
gate without a separate spec decision.

## Resolved Implementation Choices

- The first UI shell was embedded per page to match the current static admin
  convention. Reusable fetch/status/list/prompt helpers now live in
  `docs/admin/scout-assistant-ui.js`, while each surface still owns its
  surface-specific payload and constraints.
- The API route is the global read-only query endpoint `POST /assistant/query`.
- The Pydantic AI provider uses a separate assistant provider path from
  `/navigate`, with its own prompt boundary and external cloud/local model
  configuration.
- Debug, pretrip, admin after-action, and hardware readiness are now UI
  surfaces. Hardware readiness remains fixture-backed and read-only.
- After-action UI selection aliases are resolved as compact read-only context,
  not as historical package edits.
- Hardware readiness has a Chinese-first assistant runbook and is covered by
  the readiness gate.
- Assistant UI smoke checks are browser-free static checks intended to catch
  missing shell tokens and accidental action buttons before visual QA.
- Map-layer assistant selection aliases now return readable layer labels and
  bounded sample labels without raw map geometry.
- Browser visual QA has been captured in `docs/admin/assistant-browser-smoke.md`
  with screenshots for initial page and live query states.

## Next Slice Candidates

After Milestone 10.2 Slice 14, the next step is either browser visual QA for
the offline fallback panels or recording a longer Pi/Ollama soak test. Both
should remain outside Phase 1 safety authority unless explicitly promoted by a
new spec decision.
