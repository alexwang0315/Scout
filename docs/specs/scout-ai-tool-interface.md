# Scout AI Tool Interface

This interface gives Scout AI a deterministic way to read available tool
contracts and run read-only local evidence tools without depending on prompt-only
knowledge.

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

## Pydantic AI Provider Integration

The Pydantic AI assistant provider keeps the existing `search_scout_*` tool
function names for compatibility with Pydantic AI function registration, but the
tool prompt is generated from `scout_ai_tool_registry`.

Current provider behavior:

- `build_workspace_tool_prompt()` reads the registry and includes executable
  tool ids, implementation status, descriptions, and optional fields.
- `ScoutWorkspaceToolContext.search_scout_route_structure()` and the other
  current deterministic tools execute through `execute_scout_ai_tool()`.
- Legacy `search_scout_workspace_evidence()` remains available for local
  evidence-index fallback, but the newer structured tools should be preferred
  when the question maps to route, MCP, full-text, risk, terrain, or map
  perception evidence.
- Contract-only future tools, such as weather window assessment, are not exposed
  as Pydantic AI functions until they have an executor. They remain visible
  through the registry for missing-evidence explanations.
