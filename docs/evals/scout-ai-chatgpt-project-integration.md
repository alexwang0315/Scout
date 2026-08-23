# Scout AI ChatGPT Project Integration Trace

```yaml
integration_id: SCOUT-AI-CHATGPT-PROJECT-001
source_project: Scout
source_conversation: "比較 PraisonAI 與 Pydantic AI"
source_conversation_id: 6a882b42-e744-83e8-a631-65ec64cb8585
source_mirror: /Users/alexwang0315/.codex/.chatgpt-projects/g-p-6a05a2b9d4408191b2e408e064992646
target_repository: /Users/alexwang0315/scout-fusion
integration_status: WORKING_PROTOTYPE
production_status: NOT_REQUESTED
verified_at: 2026-08-22
```

## Integration Meaning

The ChatGPT Project supplies the architecture intent. The executable integration
lives in this repository; the local project mirror is not a runtime dependency.
Its synchronized `sources/` directory was empty during this integration and
remains untouched because project sources are read-only reference material.

The accepted design statement is:

> Pydantic AI decides what is valid and what may happen. PraisonAI decides which
> specialists should investigate a candidate question and how they collaborate.

## Requirement Trace

| Project requirement | Scout implementation | Executable evidence | Status |
|---|---|---|---|
| Pydantic-owned typed control boundary | `src/scout/nextgen/intelligence_gateway.py` | `tests/test_scout_ai_nextgen_contracts.py` | Demonstrated |
| PraisonAI isolated behind MCP | `src/scout/nextgen/intelligence_mcp.py`, `intelligence_mcp_server.py` | `tests/test_scout_ai_praison_mcp_slice.py` | Demonstrated |
| Terrain, QGIS, and Research specialists | `src/scout/nextgen/praison_service.py` | Real `PraisonAI AgentTeam` direct and subprocess tests | Demonstrated |
| One shared resident model | `src/scout/nextgen/model_gateway.py`, `model_scheduler.py` | Three specialist calls share one task-bound gateway session | Demonstrated |
| Provider-blind model serving | `src/scout/nextgen/openai_compatible_backend.py` | OpenAI-compatible HTTP replay through PraisonAI and MCP | Demonstrated |
| Hailo, MAX, and cloud remain sibling runtime choices | `src/scout/nextgen/model_runtime.py` | Router contract and qualification tests | Contract demonstrated |
| Production assistant remains unchanged | `src/scout/nextgen/runtime_shadow.py` | Shadow trace reports `execution_changed=false` | Demonstrated |
| Candidate-only authority | Pydantic request, response, provenance, and execution schemas | Malformed, stale, expired, over-budget, and escalation rejection tests | Demonstrated |

## Preserved Invariants

- Every accepted intelligence result has `candidate_only=true`.
- Every accepted intelligence result has `runtime_safety_truth=false`.
- PraisonAI has no mission, baseline, permission, safety, emergency,
  notification, route, device, or hardware write capability.
- Model provider selection and request accounting remain Scout-owned.
- Stale bindings, invalid output, denied capabilities, timeout, unavailable
  runtimes, and model failures fail closed without authoritative mutation.
- Logical specialist parallelism is serialized through local model concurrency
  of one for this edge-oriented slice.

## Verification

The focused suite was run in an isolated Python 3.13 environment with
`pydantic-ai-slim==2.33.0` and `praisonaiagents==1.7.0`:

```text
63 passed, 1 warning in 83.74s
```

The exercised path included real PraisonAI lifecycle code, MCP subprocess
transport, one shared Pydantic AI model gateway, HTTP protocol replay, request
budgets, cancellation, timeout, stale binding, malformed output, and authority
escalation rejection. The warning was a Pydantic Graph event-loop deprecation
warning and did not affect test outcomes.

## Deliberately Outside This Integration

- No production assistant provider was replaced or rerouted.
- No real MAX, Hailo, Ollama, cloud model, or model-quality claim was made.
- The QGIS specialist consumed controlled evidence; it did not invoke QGIS MCP.
- No candidate was promoted into route, mission, permission, or safety truth.
- No Raspberry Pi thermal, memory, latency, or energy qualification was run.

Those are later capability or productization gates, not evidence missing from
the ChatGPT Project architecture-to-prototype integration completed here.
