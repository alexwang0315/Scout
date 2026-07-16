# Scout AI Tool Interface

This interface gives Scout AI a deterministic way to read available tool
contracts and run read-only local evidence tools without depending on prompt-only
knowledge.

## Implementation Update 2026-06-30

Scout AI now runs against Pydantic AI v2.10.0 on the Mac and Pi dependency
tracks. Tool execution remains deterministic and read-only by default:

- `pydantic-ai-slim[openai,openrouter]` is pinned to v2.10.0 for Pi admin/live
  runtimes and the local development venv.
- Scout keeps `pydantic_ai.Agent(end_strategy="early")` for typed Scout
  provider calls. This intentionally avoids Pydantic AI v2's default graceful
  continuation from executing extra same-turn tools after Scout has produced a
  typed output.
- NVIDIA-hosted GLM uses `SCOUT_AI_OS_MODEL=z-ai/glm-5.2` and
  `NVIDIA_API_KEY`. Scout routes it to the OpenAI-compatible NVIDIA endpoint
  while preserving `z-ai/glm-5.2` as the outbound model id.
- OpenRouter model strings use the dedicated Pydantic AI OpenRouter provider
  through the `openrouter:<vendor/model>` prefix and `OPENROUTER_API_KEY`.
- Aggressive Construction Mode gives local and cloud models no Scout-defined
  output-token cap by default. `SCOUT_AI_LOCAL_MODEL_MAX_TOKENS`, legacy
  `SCOUT_AI_WORKSPACE_MODEL_MAX_TOKENS`, and
  `SCOUT_AI_CLOUD_MODEL_MAX_TOKENS` are explicit operator/Productization
  overrides, not hidden defaults.
- Direct OpenAI model strings must use `openai-chat:<model>`. If an operator
  supplies `openai:<model>`, Scout normalizes it to `openai-chat:<model>` to
  preserve the existing Chat-Completions-like Scout tool/output contract rather
  than silently switching to the OpenAI Responses API behavior.
- Native WebSearch and WebFetch are enabled by default for external
  provider-backed Scout AI calls. Scout AI is the full-capability entrypoint;
  deterministic tools and provider-native research are supporting capability
  layers. Operators may opt out for lab/CI with
  `SCOUT_AI_OS_NATIVE_RESEARCH=0`, or constrain domains with the native
  research domain env vars.
- Provider-native MCP remains disabled until the matching Pydantic AI optional
  dependency and a Scout-owned connector boundary are added.
- Environment secrets remain server-side. Tool artifacts, admin/debug payloads,
  and logs may report missing credential env names such as `NVIDIA_API_KEY`,
  `OPENROUTER_API_KEY`, or `OPENAI_API_KEY`, but never their values.

Recent workspace tool coverage also includes route-context mileage and raster
OCR evidence:

- `scout.ai.route_context.assess.v0` /
  `pydantic_ai.tool.assess_scout_route_context.v0` resolves route-context
  questions and K/mileage anchors such as "15K 在哪" from
  `route_context_points_ref`, `route_mileage_k_anchors_ref`, and bounded
  `mileage_tag_alignment_ref` slices.
- `pydantic_ai.tool.search_scout_map_perception.v0` now reads normalized raster
  OCR GeoJSON from `raster_label_evidence_ref` in addition to legacy MCP OCR.
- `pydantic_ai.tool.search_scout_evidence_fulltext.v0` indexes route mileage
  anchors, bounded mileage alignment summaries, normalized raster OCR records,
  and raw OCR summaries when `project.json` refs are present.

## Registry Tool

Manifest id:

```text
scout.ai.tool_registry.describe
```

Request:

```json
{
  "include_not_implemented": true,
  "tool_ids": [
    "pydantic_ai.tool.search_scout_risk_scores.v0",
    "scout.ai.weather_window.assess.v0"
  ]
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_tool_registry",
  "artifact_version": "scout_ai_tool_registry.v0",
  "tool_count": 2,
  "ready_current_tool_count": 1,
  "executable_tool_count": 1,
  "contract_only_tool_count": 1,
  "implementation_status_counts": {
    "partial_existing_surface": 1,
    "ready_current_tool": 1
  },
  "tool_ids_by_status": {
    "partial_existing_surface": ["scout.ai.weather_window.assess.v0"],
    "ready_current_tool": ["pydantic_ai.tool.search_scout_risk_scores.v0"]
  },
  "missing_evidence_fields_by_tool": {
    "scout.ai.weather_window.assess.v0": ["provider", "ttl_s"]
  },
  "tools": [
    {
      "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
      "label": "risk score search",
      "implementation_status": "ready_current_tool",
      "description": "Read baseline/calibrated route risk scores.",
      "data_bundles": ["risk_score_layers"],
      "required_fields": ["project_root"],
      "optional_fields": ["surface", "min_score", "cp", "lat", "lon", "radius_m"],
      "workflow_steps": ["resolve project root", "apply query and optional filters"],
      "existing_support": ["scout_risk_score_tool.search_project_risk_scores"],
      "implementation_gap": null,
      "argument_schema": {},
      "output_artifact_kind": "scout_ai_risk_scores_tool_output",
      "aliases": ["scout.ai.risk_scores.search"],
      "boundary": {
        "read_only": true,
        "runtime_safety_truth": false,
        "live_safety_api_calls_allowed": false,
        "phase1_safety_mutation_allowed": false,
        "remote_outbound_send_allowed": false,
        "hardware_control_allowed": false,
        "raw_payloads_embedded": false,
        "model_output_is_runtime_truth": false
      }
    }
  ],
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_safety_mutation_allowed": false,
    "remote_outbound_send_allowed": false,
    "hardware_control_allowed": false,
    "raw_payloads_embedded": false,
    "model_output_is_runtime_truth": false
  }
}
```

Registry summary fields let Scout AI and admin/debug callers inspect tool
readiness without scanning every contract:

- `ready_current_tool_count`: contracts whose implementation status is
  `ready_current_tool`.
- `executable_tool_count`: contracts currently backed by an executor alias.
- `contract_only_tool_count`: registered contracts with no executor alias yet.
- `implementation_status_counts` and `tool_ids_by_status`: bounded readiness
  inventory for planning and eval.
- `missing_evidence_fields_by_tool`: required fields for contract-only tools,
  so the assistant can state missing evidence instead of guessing.

## Context Registry Tool

Manifest id:

```text
scout.ai.context_registry.describe
```

Request:

```json
{
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "include_missing": true
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_context_registry",
  "artifact_version": "scout_ai_context_registry.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "source_count": 9,
  "source_ids_by_domain": {
    "route": ["scout.context.route_structure"],
    "weather": ["scout.context.weather_window"]
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false,
    "raw_payloads_embedded": false
  }
}
```

This tool performs deterministic source discovery from the local pretrip
workspace manifest plus registered tool contracts. It reports which source
domains are available, partial, or missing before the planner selects tools.
It does not fetch network data, embed raw payloads, mutate workspace files,
call `/safety/*`, send outbound packets, or control hardware.

## Workflow Discovery Plan Tool

Manifest id:

```text
scout.ai.workflow_discovery.plan
```

Request:

```json
{
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "project_id": "chilai_nanhua_day1",
  "surface": "pretrip",
  "question": "危險地形在哪些位置?",
  "limit": 3,
  "include_missing_context_sources": true,
  "include_not_implemented_tools": true
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_workflow_discovery_plan",
  "artifact_version": "scout_ai_workflow_discovery_plan.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "selected_tool_ids": [
    "pydantic_ai.tool.search_scout_risk_scores.v0",
    "pydantic_ai.tool.search_scout_terrain_scores.v0"
  ],
  "ready_to_execute_tool_ids": [
    "pydantic_ai.tool.search_scout_risk_scores.v0",
    "pydantic_ai.tool.search_scout_terrain_scores.v0"
  ],
  "contract_gap_tool_ids": [],
  "execution_policy": {
    "deterministic_discovery_only": true,
    "ready_tools_executed": false,
    "model_synthesis_performed": false,
    "workspace_file_write_allowed": false,
    "safety_api_called": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false,
    "ready_tools_executed": false,
    "model_synthesis_performed": false,
    "raw_payloads_embedded": false
  }
}
```

This tool is the first audit checkpoint for a Scout AI question workflow. It
combines context registry source discovery, tool registry readiness, and the
registry-backed planner into a single artifact that an admin/debug UI can show
before any evidence tool execution or model synthesis happens. Ready tools are
listed in the plan, but not executed here. Contract-only tools expose
`missing_fields` and `implementation_gap` through the embedded tool plan.

## Evidence Collection Tool

Manifest id:

```text
scout.ai.evidence_collection.collect
```

Request:

```json
{
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "project_id": "chilai_nanhua_day1",
  "surface": "pretrip",
  "question": "危險地形在哪些位置?",
  "limit": 3,
  "max_result_items_per_tool": 3
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_evidence_collection",
  "artifact_version": "scout_ai_evidence_collection.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "selected_tool_count": 2,
  "executed_tool_count": 2,
  "completed_tool_count": 2,
  "contract_gap_count": 0,
  "evidence_records": [
    {
      "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
      "planned_status": "ready_to_execute",
      "collection_status": "completed",
      "result": {
        "artifact_kind": "scout_ai_tool_result",
        "status": "completed",
        "payload": {
          "artifact_kind": "scout_ai_risk_scores_tool_output",
          "result_count": 3,
          "results_truncated": false
        }
      }
    }
  ],
  "execution_policy": {
    "deterministic_tools_executed": true,
    "ready_tools_executed": true,
    "model_synthesis_performed": false,
    "workspace_file_write_allowed": false,
    "safety_api_called": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false,
    "model_synthesis_performed": false,
    "raw_payloads_embedded": false
  }
}
```

This tool is the second audit checkpoint for a Scout AI question workflow. It
uses the workflow discovery plan to execute only `ready_to_execute` deterministic
tools through the uniform Scout AI tool runner. Contract-only tools are not
executed; they become `contract_gap` evidence records with `missing_fields` and
`implementation_gap`. The artifact is evidence for later answer synthesis, not
an assistant answer by itself.

## Answer Synthesis Tool

Manifest id:

```text
scout.ai.answer_synthesis.synthesize
```

Request:

```json
{
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "project_id": "chilai_nanhua_day1",
  "surface": "pretrip",
  "question": "危險地形在哪些位置?",
  "limit": 3
}
```

The request may also provide an already collected artifact:

```json
{
  "evidence_collection": {
    "artifact_kind": "scout_ai_evidence_collection",
    "artifact_version": "scout_ai_evidence_collection.v0"
  }
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_answer_synthesis",
  "artifact_version": "scout_ai_answer_synthesis.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "answerability": "evidence_available",
  "answer": "Scout AI read-only answer draft: deterministic evidence was collected before synthesis...",
  "evidence_collection_verified": true,
  "completed_source_count": 2,
  "missing_evidence_count": 0,
  "sources": [
    {
      "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
      "collection_status": "completed",
      "result_count": 3,
      "runtime_safety_truth": false
    }
  ],
  "missing_evidence": [],
  "synthesis_policy": {
    "evidence_collection_required": true,
    "evidence_collected_before_synthesis": true,
    "deterministic_fallback_formatter_used": true,
    "answer_synthesis_performed": true,
    "model_provider_used": false,
    "model_synthesis_performed": false,
    "workspace_file_write_allowed": false,
    "safety_api_called": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false,
    "model_provider_used": false,
    "model_synthesis_performed": false,
    "raw_payloads_embedded": false
  }
}
```

This tool is the third audit checkpoint for a Scout AI question workflow. It
requires evidence collection before generating an answer draft. This version
uses deterministic fallback formatting only; later model-backed synthesis must
still take the evidence collection artifact as input and must preserve the same
read-only advisory boundary.

## Full Workflow Runner

Manifest id:

```text
scout.ai.full_workflow.run
```

Request:

```json
{
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "project_id": "chilai_nanhua_day1",
  "surface": "pretrip",
  "question": "危險地形在哪些位置?",
  "limit": 3,
  "max_result_items_per_tool": 3
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_full_workflow",
  "artifact_version": "scout_ai_full_workflow.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "answerability": "evidence_available",
  "workflow_steps": [
    {
      "step_id": "context_registry_and_tool_plan",
      "artifact_kind": "scout_ai_workflow_discovery_plan",
      "status": "completed"
    },
    {
      "step_id": "evidence_collection",
      "artifact_kind": "scout_ai_evidence_collection",
      "status": "completed"
    },
    {
      "step_id": "answer_synthesis",
      "artifact_kind": "scout_ai_answer_synthesis",
      "status": "completed"
    }
  ],
  "selected_tool_count": 2,
  "executed_tool_count": 2,
  "completed_tool_count": 2,
  "contract_gap_count": 0,
  "missing_evidence_count": 0,
  "workflow_policy": {
    "context_registry_discovered": true,
    "tool_plan_created": true,
    "evidence_collection_performed": true,
    "answer_synthesis_performed": true,
    "deterministic_tools_executed": true,
    "model_provider_used": false,
    "model_synthesis_performed": false,
    "workspace_file_write_allowed": false,
    "safety_api_called": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false
  },
  "model_policy": {
    "pydantic_ai_version": "2.1.0",
    "provider_mode": "deterministic_tools_only",
    "external_model_used": false,
    "fallback_used": false,
    "required_credential_env": [],
    "missing_credential_env": []
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false,
    "model_provider_used": false,
    "model_synthesis_performed": false,
    "raw_payloads_embedded": false
  }
}
```

This runner is the single-call admin/debug audit path for a Scout AI question.
It wraps the three lower checkpoints rather than replacing them: workflow
discovery still selects registry-backed tools, evidence collection still runs
only ready deterministic tools, and answer synthesis still formats only after
evidence exists. The runner is read-only and does not call a model provider,
write workspace files, promote candidate evidence to runtime safety truth, call
`/safety/*`, send outbound packets, or control hardware.

## Tool Runner

Manifest id:

```text
scout.ai.tool.run
```

Request:

```json
{
  "tool_id": "scout.ai.risk_scores.search",
  "project_root": "/path/to/pretrip/project",
  "query": "highest baseline risk near CP010",
  "limit": 5,
  "arguments": {
    "surface": "baseline"
  },
  "request_id": "assistant_request.local.001",
  "agent_run_id": "agent_run.local.001"
}
```

Result artifact:

```json
{
  "artifact_kind": "scout_ai_tool_result",
  "artifact_version": "scout_ai_tool_result.v0",
  "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
  "request_id": "assistant_request.local.001",
  "agent_run_id": "agent_run.local.001",
  "status": "completed",
  "implementation_status": "ready_current_tool",
  "output_artifact_kind": "scout_ai_risk_scores_tool_output",
  "payload": {
    "artifact_kind": "scout_ai_risk_scores_tool_output",
    "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
    "status": "completed"
  },
  "missing_fields": [],
  "warnings": [],
  "errors": [],
  "sources": [
    {
      "source_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
      "evidence_type": "scout_ai_tool_contract"
    }
  ],
  "model_policy": {
    "pydantic_ai_version": "2.1.0",
    "provider_mode": "deterministic_tool_runner",
    "external_model_used": false,
    "native_research_enabled": true,
    "native_web_search_enabled": true,
    "native_web_fetch_enabled": true,
    "native_research_requires_approval": false,
    "native_research_candidate_only": true,
    "native_research_runtime_safety_truth": false,
    "provider_native_mcp_enabled": false
  },
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "live_safety_api_calls_allowed": false,
    "phase1_safety_mutation_allowed": false,
    "remote_outbound_send_allowed": false,
    "hardware_control_allowed": false,
    "raw_payloads_embedded": false,
    "model_output_is_runtime_truth": false
  }
}
```

Possible `status` values:

- `completed`: The deterministic tool ran and returned evidence.
- `missing_input`: Required request fields were missing.
- `not_implemented`: A contract exists, but no executor exists yet.
- `failed`: The request was invalid or the executor failed.

Future tools should be registered in the registry before they are executable.
This lets Scout AI explain missing evidence and implementation gaps without
inventing tool behavior.

## Weather / Environment Workspace Tools

Scout AI now separates route-weather reasoning into a decision tool plus two
workspace evidence tools:

| Layer | Tool id | Role |
| --- | --- | --- |
| Decision wrapper | `scout.ai.weather_window.assess.v0` | Route-local weather/daylight/camp/shelter decision framing. |
| Official weather evidence | `scout.ai.cwa_environment.assess.v0` | Prepared Central Weather Administration warnings, observations, QPF, forecast, astronomy, tide/marine, and provenance summaries. |
| Hydrologic background | `scout.ai.gee_environment.assess.v0` | Prepared GEE SMAP/GPM soil moisture, antecedent rain, grid/timeline, and corridor hydrologic summaries. |

Both environment tools are deterministic, read-only Scout workspace readers.
They do not call live CWA, GEE, OpenRouter, OpenAI, browser search, or
Earth Engine during assistant answering. Server-side pretrip preparation may
create the artifacts with credentials, but Scout AI receives only bounded,
redacted, candidate-only artifacts from the workspace.

Common request shape:

```json
{
  "tool_id": "scout.ai.cwa_environment.assess.v0",
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "query": "白牆下這段還適合走嗎？",
  "limit": 6,
  "arguments": {
    "include_features": true,
    "include_timeline": true,
    "stale_after_hours": 12
  }
}
```

`scout.ai.cwa_environment.assess.v0` reads these workspace artifacts when
available:

- `outputs/environment/environment_evidence_package.json`
- `outputs/environment/environment_factor_matrix.json`
- `outputs/environment/go_no_go_review_draft.json`
- `outputs/environment/cwa/cwa_weather_evidence.json`
- `outputs/environment/cwa/warnings.geojson`
- `outputs/environment/cwa/observations.geojson`
- `outputs/environment/cwa/qpf_grid.geojson`
- `outputs/environment/cwa/qpf_route_timeline.json`
- `outputs/environment/cwa/qpf_corridor_summary.json`
- `outputs/environment/cwa/forecast_timeline.json`
- `outputs/environment/cwa/astronomy_timeline.json`
- `outputs/environment/cwa/tide_marine_timeline.json`

`scout.ai.gee_environment.assess.v0` reads these workspace artifacts when
available:

- `outputs/environment/environment_evidence_package.json`
- `outputs/environment/environment_factor_matrix.json`
- `outputs/environment/go_no_go_review_draft.json`
- `outputs/environment/gee/smap_l4_timeseries.json`
- `outputs/environment/gee/smap_l4_corridor_summary.json`
- `outputs/environment/gee/soil_moisture_grid.geojson`
- `outputs/environment/gee/gpm_imerg_raw_summary.json`
- `outputs/environment/gee/gpm_imerg_timeseries.json`
- `outputs/environment/gee/gpm_imerg_corridor_summary.json`
- `outputs/environment/gee/antecedent_rain_grid.geojson`

Both outputs must include:

- `candidate_only: true`
- `runtime_safety_truth: false`
- `human_review_required: true`
- `external_api_calls_made: false`
- `source_report`, `provenance_summary`, `missing_fields`, and `warnings`
- a compact `field_answer` suitable for answer synthesis

## Route Context, Mileage, And Raster OCR Workspace Tools

Scout AI now treats route mileage and raster OCR as first-class workspace
evidence instead of relying on prompt-only interpretation.

| Layer | Tool id | Role |
| --- | --- | --- |
| Route-context assessor | `scout.ai.route_context.assess.v0` / `pydantic_ai.tool.assess_scout_route_context.v0` | Answer route context, observation-point, and K/mileage anchor questions. |
| Raster/map perception | `pydantic_ai.tool.search_scout_map_perception.v0` | Search legacy MCP OCR, normalized raster OCR GeoJSON, contour/map labels, and tile-source refs. |
| Workspace full-text | `pydantic_ai.tool.search_scout_evidence_fulltext.v0` | Index route mileage anchors, bounded mileage tag alignment, OCR labels, route notes, and source snippets. |

Required reads are project-ref driven:

- `route_context_points_ref`
- `route_mileage_k_anchors_ref`
- `mileage_tag_alignment_ref`
- `mileage_tag_alignment_geojson_ref`
- `raster_label_ocr_output_ref`
- `raster_label_evidence_ref`

These tools must keep large artifacts bounded. They may summarize
`outputs/mileage_tag_alignment.json` and raw OCR output, but must not pass full
alignment or raw tile payloads into the model. All returned items remain
candidate-only unless a reviewed package explicitly promotes them.

Planner behavior:

- Natural weather questions select `weather_window` and CWA evidence.
- Rain, stream, rockfall, landslide, wet terrain, and weather-terrain compound
  questions also select GEE evidence.
- Pretrip Go/No-Go questions select route readiness plus weather, CWA, and GEE
  support evidence when the workspace provides it.
- Missing or stale CWA/GEE artifacts are reported as evidence gaps; Scout AI
  must not infer low weather risk from absent environment artifacts.

Boundary:

- These tools are pretrip/admin/debug evidence tools only.
- They must not write candidate review decisions, ObservedFact, Phase 2 Brain
  facts, IncidentStore records, runtime safety truth, or `/safety/*`.
- They must not expose CWA API keys, GEE credentials, raw secrets, or
  unredacted request URLs to the client, logs, or model prompt.

## Assistant Workflow Eval Runner

Manifest id:

```text
scout.ai.assistant_workflow_eval.run
```

Request:

```json
{
  "corpus_path": "docs/specs/scout-ai-200-question-corpus.json",
  "project_root": "tests/fixtures/pretrip/projects/chilai_nanhua_day1",
  "project_id": "chilai_nanhua_day1",
  "case_ids": ["seed-008", "seed-007"],
  "limit": 3
}
```

Output artifact:

```json
{
  "artifact_kind": "scout_ai_assistant_workflow_eval_tool_output",
  "artifact_version": "scout_ai_assistant_workflow_eval_tool_output.v0",
  "status": "completed",
  "project_id": "chilai_nanhua_day1",
  "case_ids": ["seed-008", "seed-007"],
  "report": {
    "artifact_kind": "scout_ai_assistant_workflow_eval_report",
    "artifact_version": "scout_ai_assistant_workflow_eval_report.v0",
    "case_count": 2,
    "passed_count": 2,
    "failed_count": 0
  },
  "markdown": "# Scout AI Assistant Workflow Eval Report\n...",
  "boundary": {
    "read_only": true,
    "runtime_safety_truth": false,
    "safety_api_called": false,
    "phase1_l0_l4_state_mutated": false,
    "outbound_send_performed": false,
    "hardware_control_performed": false,
    "workspace_file_write_allowed": false
  }
}
```

The workflow eval runner intentionally uses a failing provider to prove that
Scout AI can still answer bounded cases from deterministic evidence or return
missing-evidence gaps when model synthesis is unavailable. It does not write
JSON/Markdown files itself; the report and Markdown are returned in the tool
payload so callers can decide where to persist review artifacts.

## Deterministic Workspace Query Tool

Manifest id:

```text
scout.ai.workspace.query.v1
```

This is the progressive follow-up tool after domain discovery. Its request is
a Pydantic discriminated union; Pydantic AI receives the full operation schema
instead of an untyped dictionary. Supported operations are:

```text
inspect exists count distinct filter group_by top_k argmax diff freshness
nearest interval route_forward
```

An artifact selector contains exactly one controlled `source_ref` or
`project_ref_key` and may include a bounded `collection_path`. Fields use a
restricted dotted-name grammar. Predicates are typed comparisons; no JSONPath,
SQL, Python, JavaScript, shell, or model-authored expression is evaluated.

Example:

```json
{
  "operation": "argmax",
  "artifact": {
    "project_ref_key": "segment_candidates_ref",
    "collection_path": "segments"
  },
  "field": "distance_m",
  "fields": [
    "candidate_id",
    "from_candidate_id",
    "to_candidate_id",
    "distance_m"
  ]
}
```

Every response has stable `status` and `answerability` fields, bounded results,
scan/result counts, source refs, limitations, missing fields, next actions,
root cause, safe-retry state, and stop condition. Each record carries:

- execution-scoped `evidence_id`;
- `source_ref`, `source_hash`, `record_id`, and locator;
- bounded projected data and available observation/validity times;
- `candidate_only=true` and `runtime_safety_truth=false`.

`null` and missing are different. An explicit null remains in the result. A
field absent from all selected records produces a warning with
`answerability=missing_required_fields`; already available evidence is still
returned. An empty existing collection produces a grounded zero result.

The service confines resolved files to the project root, rejects traversal and
symlink escape, permits JSON/GeoJSON only, and enforces artifact bytes, scanned
records, returned records, nesting depth, string length, stable ordering, and
diff-path limits. It performs no network or workspace write and never mutates
Phase 1, `/safety/*`, Phase 2 Brain, incident, outbound, or hardware state.

## Pydantic AI Provider Integration

The Pydantic AI assistant provider keeps the existing `search_scout_*` tool
function names for compatibility with Pydantic AI function registration, but the
tool prompt is generated from `scout_ai_tool_registry`.

Current provider behavior:

- `build_workspace_tool_prompt()` reads the registry and includes executable
  tool ids, implementation status, descriptions, and optional fields.
- `ScoutWorkspaceToolContext.search_scout_route_structure()` and the other
  current deterministic tools execute through `execute_scout_ai_tool()`.
- `ScoutWorkspaceToolContext.query_scout_workspace()` accepts the typed
  `WorkspaceQueryRequest` union and executes `scout.ai.workspace.query.v1`
  inside the resolved project root. The model cannot supply a different root.
- `AgentBudgetPolicy` selects the Scout `AgentRunBudget` from question class,
  expected operations, joins, live-state requirements, and selected domains.
  The Pydantic adapter only maps that budget to `UsageLimits`; the Scout ledger
  independently verifies actual request/tool/token usage.
- Every question class has the same executable ceiling: 10 tool calls and 10
  model requests per attempt and per recovery stage, including unknown/new
  classes. Stage, surface, average, p95, and static-fact policies may stop early
  on sufficient evidence or no progress, but may not impose lower capacity.
- Planner, retriever, synthesis, verifier, reviewer, repair, retry, replan,
  browser, and subagent categories also default to at least 10 when separately
  metered.
- Construction Mode leaves token, EvidenceCard, context, cost, answer-time, and
  replay-time ceilings unset. External platform limits create a checkpoint and
  continuation with a fresh 10/10 budget.
- Typed executor statuses `completed`, `success`, and `ok` are successful tool
  outcomes for evaluation and ledger matching. They must not be reclassified
  as transport errors merely because adapters use different success labels.
- Failures follow the finite ladder in `SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`:
  fix tools/evidence/harness with fresh 10/10, switch model with fresh 10/10,
  build the complete Codex review artifact, then register a stable known issue
  with an explicit unblock condition.
- Legacy `search_scout_workspace_evidence()` remains available for local
  evidence-index fallback, but the newer structured tools should be preferred
  when the question maps to route, MCP, full-text, risk, terrain, map
  perception, weather window, CWA environment, or GEE environment evidence.
- `weather_window`, `cwa_environment`, and `gee_environment` are executable
  read-only functions when present in the registry. Contract-only future tools
  remain visible through the registry for missing-evidence explanations, but
  are not exposed as executable Pydantic AI functions until they have an
  executor.
