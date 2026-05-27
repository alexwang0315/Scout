# Spec: Scout Agent Tools CLI

## Status

Draft for the next alpha branch, with first local implementation slices now
tracked in this checkout.

This spec defines the next layer after the current read-only cross-surface
assistant: a privileged local Scout agent that can use registered Scout
resources through deterministic CLI tools.

Chinese annotation / 中文註釋: `Scout Agent Resource Runtime`（Scout 代理資源執行層）
is not a generic chatbot, and it is not a web-search assistant. It is a local
agent layer running on Scout hardware or a trusted Scout workstation, using the
trip's local package, maps, route evidence, hardware state, and operator/user
intent.

Current alpha implementation snapshot:

- user-facing facade: `python -m scout_cli ...`;
- registered tool runner: `python -m scout_agent_cli tools ...`;
- builtin deterministic tools: `python -m scout_agent_builtin_tools ...`;
- registered manifests: JSON files under `tools/scout_agent_tool_manifests/`;
- current manifest count: 39, including local evidence, release/readiness
  checks, CP proposal/reviewed
  delta, pretrip import/layer preparation/workspace edit, risk diagnostics,
  map preparation wrappers, spatial imprint tools, hardware readiness summary,
  review decision append,
  advisory shelter direction, runtime dry-run/preflight, voice preview/mock
  receipts, outbound mock receipts, reviewed-candidate package addendum,
  metadata-only runtime handoff, runtime export, and mock-only SOS playbook run.

## Objective

Build a stable CLI/tool interface that lets Pydantic AI use Scout resources
directly:

- read local trip evidence without live network search;
- query maps, terrain, weather cache, historical tracks, route notes, and
  reviewed planning artifacts;
- propose or apply checkpoint changes through deterministic workspace/package
  tools;
- generate risk diagnostics and route-aligned heat maps;
- append notes and action traces to the flight-recorder loop;
- preview or send TTS/outbound messages through explicit action modes;
- trigger local hardware actions such as alarms in authorized modes;
- run SOS delegated emergency playbooks after explicit SOS activation.

Success means Scout AI can move from "speaks about Scout state" to "uses Scout
resources to perform auditable actions", while deterministic tools remain the
source of calculations, writes, transport attempts, and hardware effects.

## Relationship To Existing Specs

- `docs/specs/scout-cross-surface-ai-assistant.md` remains the current
  read-only assistant guardrail.
- This spec defines a new, more privileged layer. It must not silently change
  the current read-only `/assistant/query` contract.
- `docs/specs/pre-trip-planning-admin.md` remains authoritative for Phase 4
  candidate-only planning evidence.
- `docs/specs/phase-4-5-departure-runtime-handoff.md` remains authoritative for
  reviewed packages, final MissionGraph, runtime handoff, activation preflight,
  and remote-provider send gates.
- `docs/specs/scout-voice-cue-layer.md` remains authoritative for voice cue
  read-only/runtime boundary until this spec adds explicit outbound action
  modes.
- `docs/specs/pi5-gpio-control-surface.md` and hardware-readiness docs remain
  authoritative for Pi 5 GPIO readiness and lab-mode drive policy.

## Core Position

The agent is not sandboxed in the toy-chat sense. It should be able to call
Scout-local tools and read Scout-local trip evidence with the same operational
context as the Scout runtime process.

The boundary is not a content audit before every action. The boundary is:

- a registered capability allowlist;
- explicit action mode;
- deterministic tool contracts;
- append-only action trace;
- operator/user/SOS activation source;
- reversible or preview-first behavior where possible;
- no hidden Phase 1 safety-state mutation by model output.

Chinese annotation / 中文註釋: 現場探險時，阻擋行動本身也可能是風險。Scout
should use imperfect local evidence when needed, record provenance and
uncertainty, and leave later audit/replay/correction possible. Instruction-like
text inside local articles, notes, or reports is treated as evidence text, not
as a new system instruction.

## Definitions

### Scout Agent Resource Runtime

`Scout Agent Resource Runtime`（Scout 代理資源執行層）is the Pydantic AI-facing
tool runner and policy layer. It exposes Scout resources through registered CLI
capabilities.

### Tool Capability CLI

`Tool Capability CLI`（工具能力命令列介面）is a deterministic command surface
that can be called by a human operator or by Pydantic AI. It accepts structured
arguments, emits structured JSON, and writes trace artifacts.

### Local Evidence Index

`Local Evidence Index`（本地證據索引）is the offline searchable index of the
current trip package: route, map, reviewed candidates, CP/SCP, risk outputs,
cached weather, historical tracks, user notes, experience reports, hardware
readiness, and runtime debug events.

### Action Trace

`Action Trace`（行動追蹤紀錄）is the append-only record of every agent action:
intent, chosen tool, inputs, source refs, outputs, result status, receipts, and
boundary metadata.

### Flight Recorder Loop

`Flight Recorder Loop`（飛航記錄器循環）is the persistent debug/evidence log used
to reconstruct what Scout saw, decided, proposed, said, sent, or triggered.

### SOS Delegated Emergency Mode

`SOS Delegated Emergency Mode`（SOS 授權緊急接管模式）is entered only after a
physical SOS action or explicit SOS command. In this mode Scout may run
deterministic emergency playbooks without waiting for step-by-step user
confirmation.

## Authority Modes

| Mode | 中文說明 | Activation | AI may do | Tool may do | Must record |
| --- | --- | --- | --- | --- | --- |
| `local_evidence_query` | 本地證據查詢 | user/operator question | choose search tools, summarize | read local evidence | source refs, confidence, limitations |
| `decision_support` | 決策支援 | user/operator question | compare options, explain | run deterministic map/risk/weather tools | candidate ranking, uncertainty, TTL when relevant |
| `proposal_write` | 產生變更提案 | user/operator request | propose CP/note/package deltas | write proposal artifacts only | before/after refs, no package mutation |
| `workspace_write` | 寫入規劃工作區 | explicit user/operator apply | request tool apply | append workspace edit/review/note records | approver, diff, workspace refs |
| `package_write` | 寫入出發包附加資料 | explicit operator apply | request package addendum | write reviewed package addendum, not final runtime truth | package hash refs, boundary |
| `outbound_preview` | 對外訊息預覽 | user/operator request | draft text/TTS | render preview artifact | preview text/audio sha256 |
| `outbound_send` | 對外訊息送出 | explicit operator/user send | request send | send through reviewed transport tool | delivery receipt/failure |
| `hardware_action` | 硬體動作 | explicit operator/user action | request action | trigger registered local hardware action | GPIO/alarm/device result |
| `operator_triggered_tool` | 操作者觸發工具 | explicit operator command | summarize/prepare | run bounded runtime/admin tool | command result, refs, effects |
| `ephemeral_safety_action` | 臨時安全行動 | user asks for immediate help | parse intent, explain result | rank candidates, create short-lived advice | TTL, context, ranking |
| `sos_delegated_emergency` | SOS 授權緊急接管 | physical SOS or explicit SOS | summarize/prioritize | run deterministic SOS playbook, retry sends, alarm | playbook steps, receipts |
| `runtime_safety_mutation` | runtime 安全狀態改變 | closed in this spec | not allowed | not allowed | rejected request |

## Non-Goals

This spec does not:

- let the model freely run shell commands;
- replace Phase 1 deterministic safety rules;
- make model output a Phase 1 safety-state transition;
- call live `/safety/*` mutation endpoints from the agent;
- make pretrip candidate evidence runtime truth without the existing review and
  handoff chain;
- require live network search for local trip decisions;
- block urgent action on a full policy/information audit.

## CLI Architecture

The long-term user-facing command should be a single `scout` CLI with command
groups. Existing standalone scripts can be wrapped incrementally.

Until packaging is added, the alpha entrypoint is `python -m scout_cli` because
the repository already has a `scout/` directory and should not add a same-name
top-level executable file in-place.

```text
scout tools list --json
scout tools describe <tool-id> --json
scout tools run <tool-id> --input request.json --trace-log runtime-debug.jsonl

scout kb build --trip-root departure_package/ --out outputs/kb/index.json
scout kb query --trip-root departure_package/ --query "附近有可避雨的位置嗎" --json

scout pretrip import-gpx --project-id chilai_nanhua_day1 --golden-route-gpx route.gpx --workspace-root /data/scout/pretrip
scout pretrip prepare-layers --project-root /data/scout/pretrip/chilai_nanhua_day1 --layers osm,terrain,risk-score,risk-ribbon

scout risk overpass-route-profile --dtm-coverage dtm.json --overpass overpass.geojson --reference-gpx route.gpx --out route_risk.geojson
scout risk attribution --workspace /data/scout/pretrip/chilai_nanhua_day1 --json
scout risk heatmap --workspace /data/scout/pretrip/chilai_nanhua_day1 --json

scout cp propose-add --project-root ... --candidate candidate.json --trace-log ...
scout cp propose-delete --project-root ... --candidate-ref cp_042 --reason duplicate --trace-log ...
scout cp apply-reviewed-delta --project-root ... --delta proposal.json --operator-approved-by alex --trace-log ...

scout note append-flight-recorder --kind user_report --text "..." --source user --trace-log runtime-debug.jsonl

scout voice preview --text "請往西北方向移動約 180 公尺" --out preview.wav --json
scout voice send --request voice_request.json --authorize-manual-send --json

scout hardware alarm-start --pattern sos --duration-seconds 30 --authorize-user-triggered --json
scout hardware alarm-stop --authorize-user-triggered --json

scout safety-action shelter-direction --trip-root departure_package/ --position position.json --weather weather.json --dry-run --json
scout sos playbook-run --sos-event sos_event.json --debug-log-path runtime-debug.jsonl --voice-log-path voice.jsonl --authorized-by sos.manual.button --json
```

The first implementation does not need every command. It should establish the
contract and wrap the highest-value existing Python units first.

## Common CLI Contract

Every agent-callable tool should support:

```text
--json
--trace-log PATH
--agent-run-id ID
--action-id ID
--dry-run
--output PATH
```

Commands that can write, send, or trigger hardware should also support one of:

```text
--operator-approved-by ALIAS
--authorize-user-triggered
--authorize-manual-send
--authorize-sos-delegated
```

Recommended exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | completed |
| `1` | unexpected tool failure |
| `2` | blocked by missing artifact, validation, or authorization |
| `3` | partial completion with recorded degradation |
| `4` | stale request rejected by TTL or context mismatch |

## Result Envelope

All agent-callable CLI tools should return a JSON envelope:

```json
{
  "artifact_kind": "scout_agent_tool_result",
  "tool_id": "scout.pretrip.import_gpx",
  "tool_version": "0.1.0",
  "action_id": "agent_action.20260526.000001",
  "agent_run_id": "agent_run.local.20260526T120000Z",
  "status": "completed",
  "mode": "workspace_write",
  "started_at": "2026-05-26T12:00:00+08:00",
  "ended_at": "2026-05-26T12:00:02+08:00",
  "inputs": {
    "input_refs": ["project.json", "route.gpx"],
    "redacted": false
  },
  "outputs": {
    "artifact_refs": ["outputs/import_manifest.json"]
  },
  "effects": {
    "workspace_write_count": 1,
    "package_write_count": 0,
    "outbound_send_count": 0,
    "hardware_action_count": 0,
    "phase1_safety_mutation_count": 0
  },
  "boundary": {
    "runtime_safety_truth": false,
    "autonomous_mutation": false,
    "operator_or_user_triggered": true,
    "live_safety_api_calls_allowed": false
  },
  "source_refs": [
    {
      "source_id": "route.gpx",
      "source_path": "/data/scout/pretrip/chilai_nanhua_day1/inbox/route.gpx",
      "sha256": "..."
    }
  ],
  "warnings": [],
  "receipt_refs": []
}
```

## Tool Manifest Contract

The Pydantic AI tool registry should not infer capabilities from filenames.
Each callable tool needs a manifest:

```yaml
id: scout.pretrip.import_gpx
version: 0.1.0
command:
  argv:
    - python
    - -m
    - pretrip_import
mode: workspace_write
description: Import local GPX evidence into a pretrip workspace.
input_schema_ref: schemas/scout.pretrip.import_gpx.request.json
output_schema_ref: schemas/scout.agent_tool_result.json
allowed_reads:
  - local.gpx
  - pretrip.workspace.template
allowed_writes:
  - pretrip.workspace.normalized
  - pretrip.workspace.candidates
  - pretrip.workspace.outputs
forbidden_writes:
  - phase1.runtime
  - phase2.brain.observed_facts
  - live.safety_api
requires_authorization:
  kind: user_or_operator
trace:
  required: true
  event_kind: agent_tool_invocation
```

## Pydantic AI Integration

The Pydantic AI layer should receive a compact tool list from the registry:

- tool id;
- human-readable purpose;
- required inputs;
- action mode;
- whether dry-run is available;
- whether authorization is required;
- expected JSON result fields.

It should not receive raw secrets, raw GPX payloads, raw DTM files, or arbitrary
shell access as context. It may request a tool invocation, and the tool runner
executes the registered command with Scout process privileges.

The model's responsibilities:

- parse user/operator intent;
- choose relevant local evidence and tools;
- ask for missing context when needed;
- propose an action plan;
- explain deterministic tool outputs in human language;
- produce TTS/message drafts when requested.

The deterministic tool runner's responsibilities:

- validate inputs at the CLI boundary;
- perform map/risk/route/hardware/transport work;
- write artifacts;
- append action traces;
- enforce mode/authorization gates;
- emit structured success/failure results.

## Model Provider Profiles

Scout Agent planning uses the existing assistant model profile contract instead
of embedding model credentials in tool calls.

Chinese annotation / 中文註釋: `Model Provider Profile`（模型提供者設定檔）is the
operator-managed record that selects a cloud or local model runner for turning
user/operator intent into a `scout_agent_tool_plan`. It is not itself a Scout
tool and it must not bypass the registered tool manifest boundary.

Current alpha contract:

- `assistant_model_config.py` defines `cloud_model`, `local_model`,
  `active_profile`, timeout, context budget, and local fallback behavior.
- `assistant_pydantic_provider.py` owns the Pydantic AI/OpenAI-compatible
  runner, including optional `base_url` for local OpenAI-compatible servers.
- `scout_agent_runtime.py` reuses that profile config for agent planning and
  then executes only registered `scout_agent_tool_manifests`.
- Cloud profile secrets are referenced by environment variable or operator
  token id; raw token values must not appear in prompts, traces, tool results,
  `/admin/debug`, or readiness output.
- Local fallback may be used when the cloud runner fails, but fallback output is
  still only a proposed tool plan. Deterministic Scout tools remain responsible
  for all reads, writes, map/risk computation, voice/outbound receipts, and
  hardware effects.

Provider statuses should expose:

- active profile;
- cloud/local model names;
- last runner profile;
- failover count and reason;
- token env var names only, never values;
- boundary flags showing `live_safety_api_calls_allowed=false` and
  `model_output_is_runtime_truth=false`.

## Local Evidence Query Flow

Example: "目前氣候不好，我需要隱蔽，幫我指出方向."

```text
user request
  -> intent: shelter_direction
  -> kb query: current route, reviewed CP/SCP, shelters, terrain, weather cache
  -> deterministic ranking: distance, bearing, exposure, route corridor, confidence
  -> decision brief: target, direction, alternatives, uncertainty, TTL
  -> optional voice preview/send
  -> action trace
```

Required output fields:

- recommended target id;
- bearing degrees and relative direction;
- distance and estimated time;
- confidence;
- uncertainty reasons;
- alternatives;
- evidence source refs;
- TTL;
- text/TTS preview;
- `runtime_safety_truth=false` unless a future explicit Phase 1 contract says
  otherwise.

## CP Mutation Flow

AI may help add/delete CPs, but the CP operation must be represented as a
traceable delta:

```text
agent intent
  -> cp.propose_add or cp.propose_delete
  -> deterministic validation
  -> proposal artifact
  -> operator/user approval when applying
  -> workspace edit or package addendum
  -> trace
```

Hard delete is not the default. Prefer reversible operations:

- `propose_add`;
- `propose_delete`;
- `propose_merge`;
- `mark_duplicate`;
- `mark_untrusted`;
- `apply_reviewed_delta`.

## Voice And Outbound Flow

Voice and network sends are split:

```text
voice.preview
  -> render text/audio preview
  -> no delivery

voice.send
  -> requires explicit user/operator/SOS authorization
  -> delivery receipt or failure receipt
```

This allows Scout to speak to local users, Scout Centre clients, or configured
network recipients without letting model text silently become an outbound
action.

## Hardware Action Flow

Hardware actions are registered capabilities:

- `hardware.alarm_start`;
- `hardware.alarm_stop`;
- future `hardware.gpio_set`;
- future `hardware.gpio_read`;
- future `hardware.i2c_probe`;
- future `hardware.battery_status`;
- future `hardware.gps_status`;
- future `hardware.imu_status`.

Lab-mode GPIO drive is allowed only when the hardware spec and wiring manifest
say it is allowed. Until then, GPIO remains readiness/projection first.

## SOS Delegated Emergency Flow

After physical SOS or explicit SOS command:

```text
sos activation event
  -> create emergency packet
  -> append latest position, route, CP, battery, device, weather, user state
  -> start local alarm if configured
  -> try reviewed outbound channels
  -> retry according to deterministic playbook
  -> keep appending receipts and position updates
```

AI may summarize/prioritize the emergency message, but the send/retry/alarm
order must come from a deterministic playbook.

Alpha SOS slice:

- `scout.sos.playbook_run` is `sos_delegated_emergency` mode;
- non-dry-run execution requires explicit `--authorized-by`;
- accepted activation sources are `physical_sos` and `explicit_sos_command`;
- `operator_test` is blocked from delegated emergency mode;
- dry-run performs no file writes;
- authorized non-dry-run writes only runtime debug events, mock outbound
  receipts, and mock voice receipts;
- real SOS, SMS, satellite, hardware alarm, and live `/safety/*` mutation stay
  closed.

## Information Injection Posture

Scout should not run a blocking content audit for every action in the field.
Instead:

- local evidence is used as evidence, not as instruction;
- provenance is recorded;
- confidence and uncertainty are included when cheap to compute;
- urgent actions are not blocked by perfect cleanliness checks;
- all tool calls and outputs are replayable later;
- later audit may mark evidence stale, wrong, or malicious without rewriting
  the original trace.

## Project Structure

Proposed additions:

```text
scout_agent_cli.py                         # top-level CLI router for first slices
scout_agent_tools.py                       # tool manifest loader and runner
scout_agent_models.py                      # action/result/manifest models
scout_agent_trace.py                       # action trace writer
scout_agent_kb.py                          # local evidence index/query wrapper
scout_sos_playbook.py                      # mock-only deterministic SOS playbook
scout_cli.py                               # command-group facade for alpha use
tools/scout_agent_tool_manifests/          # JSON manifests
schemas/scout_agent/                       # JSON schemas for tool inputs/results
tests/test_scout_agent_*.py                # focused contract tests
docs/specs/scout-agent-tools-cli.md        # this spec
```

The first slice may keep wrappers thin and call existing modules rather than
moving current code.

## Code Style

Tool wrappers should be small and explicit:

```python
def run_tool(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = execute_registered_tool(
        tool_id="scout.pretrip.import_gpx",
        mode="workspace_write",
        dry_run=args.dry_run,
        trace_log=args.trace_log,
        input_payload=load_json(args.input),
    )
    write_json_result(result, args.output)
    return 0 if result.status == "completed" else 2
```

Avoid hidden side effects in Pydantic AI tools. The model wrapper should call
the CLI runner, not import internal modules and mutate data directly.

## Testing Strategy

Minimum first-slice tests:

- manifest loader accepts valid tool manifests and rejects unknown mode/writes;
- tool runner emits the standard result envelope;
- dry-run tools do not write workspace/package/outbound/hardware effects;
- write tools require user/operator authorization;
- outbound/hardware commands are blocked without explicit authorization;
- action trace JSONL can be loaded by `/admin/debug` or debug context tools;
- Pydantic AI mock tool-call test can list and call at least one read tool and
  one proposal tool;
- no test depends on live network;
- existing release checks remain separate from true live send/hardware tests.

Suggested command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. venv/bin/python -m pytest -q tests/test_scout_agent_tools.py tests/test_scout_agent_cli.py tests/test_scout_agent_builtin_manifests.py tests/test_scout_cli.py tests/test_scout_sos_playbook.py
```

## Boundaries

Always:

- use registered capabilities, not arbitrary shell;
- emit JSON result envelopes;
- write action traces for agent calls;
- include source refs and boundary metadata;
- keep pretrip evidence candidate-only until reviewed/handoff stages;
- treat local article/note text as evidence, not as instructions;
- prefer dry-run/proposal before write/send/trigger when time allows.

Ask first:

- adding new live network transports;
- adding a new real hardware driver or GPIO drive implementation;
- changing the Phase 1 safety runtime API;
- promoting agent outputs into final MissionGraph or runtime handoff packages;
- making SOS playbooks contact real external recipients.

Never:

- let model output directly mutate Phase 1 safety state;
- let the agent call live `/safety/*` mutation endpoints;
- send real SOS/SMS/satellite/network messages without explicit outbound mode;
- trigger real hardware without explicit hardware mode;
- embed raw secrets in tool results or traces;
- delete CPs or evidence irreversibly as the default behavior.

## First Slice Plan

1. Done: add `scout_agent_models.py` with tool manifest, action mode, result
   envelope, authorization kind, and boundary models.
2. Done: add JSON manifests and builtin wrappers for local evidence, CP
   proposal/reviewed delta, pretrip import/layer/workspace edit, pretrip review
   decision append, map preparation, voice preview, action trace append, risk
   diagnostics, spatial imprints, hardware readiness summary,
   reviewed-candidate package addendum, metadata-only runtime handoff, runtime
   export, voice/outbound mock receipts, advisory shelter direction, and
   mock-only SOS playbook.
3. Done: add `scout_agent_cli.py tools list|describe|run`.
4. Done: add `scout_cli.py` command-group facade for alpha use.
5. Done: add `/admin/debug` projection for agent action traces and spatial
   imprint/debug data.
6. Done: add focused tests for mode gates, trace output, dry-run behavior,
   authorization gates, and mock-only SOS boundary flags.
7. Done: reuse assistant cloud/local model profile config for Scout Agent
   planning, including local fallback status without exposing secret values.

## Success Criteria

- `scout tools list --json` shows registered capabilities and action modes.
- At least one read-only evidence tool and one CP proposal tool can be called by
  a deterministic/mock Pydantic AI flow.
- Every tool call writes a trace event with source refs and boundary metadata.
- A write/send/hardware command without proper authorization exits blocked.
- `/admin/debug` can render agent action trace events.
- No live `/safety/*` mutation path is introduced.
- `scout.sos.playbook_run` can dry-run without writes and can run an authorized
  mock-only playbook with debug/voice/mock outbound receipts.

## Open Questions

- Packaging question: should the installed command eventually be `scout`, while
  source checkout usage remains `python -m scout_cli`?
- Should action traces write into the existing runtime debug JSONL directly, or
  into a separate agent JSONL projected into `/admin/debug`?
- Which real SOS/outbound channels, if any, are allowed in alpha hardware field
  testing after the mock-only playbook passes lab review?
- Should `voice.send` initially use only mock transport, local speaker, or one
  reviewed network destination?
- What is the first stable local evidence index format: SQLite, JSONL, or a
  file-manifest plus simple search?
