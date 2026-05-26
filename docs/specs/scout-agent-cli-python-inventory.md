# Scout Agent CLI Python Inventory

## Status

Initial inventory for the Scout Agent Tools CLI spec.

Method:

```text
rg --files -g '*.py' | rg -v '(^tests/|/tests/)'
rg -l "argparse|typer|if __name__ == ['\"]__main__['\"]" -g '*.py' | rg -v '(^tests/|/tests/)'
```

Snapshot from this checkout:

- Non-test Python units: 274.
- Python units with direct CLI markers: 58.
- Existing Scout skill manifests: 9 under `skills/scout/*.yaml`.

This is a capability inventory, not a final implementation plan. It favors
units that can be safely wrapped for Pydantic AI through registered CLI tools.

## Selection Rules

Expose a Python unit as an agent CLI when:

- it has deterministic inputs and outputs;
- it can emit JSON;
- it can write an action trace;
- it has clear read/write/hardware/outbound effects;
- it can be blocked by mode/authorization when effects are sensitive.

Do not expose a unit directly when:

- it is a FastAPI server or long-running daemon;
- it mutates Phase 1 runtime state directly;
- it requires live network/hardware without an explicit operator mode;
- it is a fixture generator intended only for development;
- it is an internal helper better accessed through a higher-level command.

## Capability Groups

| Group | Purpose | Recommended command prefix |
| --- | --- | --- |
| Tool registry | list/describe/run registered capabilities | `scout tools ...` |
| Local evidence | offline trip evidence search/query | `scout kb ...` |
| Pretrip workspace | import, prepare, edit, review, package | `scout pretrip ...` |
| CP/SCP actions | propose/add/delete/merge/apply CP changes | `scout cp ...` |
| Risk/map analysis | terrain risk, route risk, heat maps | `scout risk ...` |
| Runtime/debug trace | replay, trace append, debug projection | `scout debug ...` |
| Voice/outbound | TTS preview/send, provider send intents | `scout voice ...`, `scout outbound ...` |
| Hardware | readiness, GPIO/alarm/audio/radio probes | `scout hardware ...` |
| Safety actions | shelter direction and other ephemeral actions | `scout safety-action ...` |
| SOS | emergency packet/playbook | `scout sos ...` |

## Existing CLI-Ready Units

These files already have `argparse`, `typer`, or a direct `__main__` entry and
can be wrapped first.

| Existing unit | Current state | Proposed capability | Agent mode |
| --- | --- | --- | --- |
| `pretrip_import.py` | argparse CLI writes pretrip workspace artifacts | `scout pretrip import-gpx` | `workspace_write` |
| `pretrip_layer_preparation.py` | argparse CLI prepares layers and project refs | `scout pretrip prepare-layers` | `workspace_write` |
| `scout-risk-engine/scout_codex_package/src/scout_risk/cli.py` | Typer CLI for DEM, TEII, CP parse, route profile, Overpass profile, risk-score map, risk ribbon | `scout risk ...` wrapper | `decision_support` / `workspace_write` |
| `pretrip_risk_attribution_diagnostic.py` | argparse CLI writes candidate-only risk attribution diagnostic | `scout risk attribution` | `workspace_write` |
| `pretrip_risk_heatmap.py` | argparse CLI writes calibrated heatmap GeoJSON/metadata/PNG | `scout risk heatmap` | `workspace_write` |
| `runtime_debug_replay_demo.py` | argparse CLI replays fixture/runtime debug | `scout debug replay` | `decision_support` |
| `runtime_debug_ui_demo.py` | argparse CLI writes debug UI demo log | `scout debug demo-log` | `decision_support` |
| `phase35_debug_demo_loader.py` | argparse CLI loads Phase 3.5 debug demo events | `scout debug load-demo` | `decision_support` |
| `phase46_live_replay_debug_projector.py` | argparse CLI projects live replay/debug evidence | `scout debug project-live-replay` | `decision_support` |
| `scout_hardware_readiness_live_probe.py` | argparse SSH read-only hardware probe | `scout hardware readiness-probe` | `local_evidence_query` |
| `scout_gpio_control_watcher.py` | argparse fixture GPIO projection only | `scout hardware gpio-projection` | `local_evidence_query` |
| `tools/pi_wifi_scan_smoke.py` | argparse read-only Wi-Fi scan | `scout hardware wifi-scan` | `local_evidence_query` |
| `tools/pi_ble_scan_smoke.py` | argparse read-only BLE scan | `scout hardware ble-scan` | `local_evidence_query` |
| `tools/pi_radio_scan_smoke.py` | argparse Wi-Fi + BLE radio scan | `scout hardware radio-scan` | `local_evidence_query` |
| `tools/pi_voice_tts_smoke.py` | argparse TTS smoke path | `scout voice tts-smoke` | `outbound_preview` / lab |
| `tools/voice_cue_debug_demo.py` | argparse voice cue debug demo | `scout voice debug-demo` | `outbound_preview` |
| `voice_cue_readiness_check.py` | argparse voice cue readiness gate | `scout voice readiness` | `local_evidence_query` |
| `runtime_remote_provider_live_send_cli.py` | argparse reviewed remote provider live send, blocked unless flags present | `scout outbound remote-send` | `outbound_send` |
| `runtime_telegram_provider_live_send_cli.py` | argparse reviewed Telegram send, blocked unless flags present | `scout outbound telegram-send` | `outbound_send` |
| `runtime_stream_signed_sample_client.py` | argparse signed runtime stream sample client | `scout runtime-stream signed-sample` | `operator_triggered_tool` |
| `runtime_stream_replay_payloads.py` | argparse runtime stream replay payload builder | `scout runtime-stream replay-payloads` | `decision_support` |
| `runtime_stream_real_device_harness.py` | argparse real-device harness | `scout runtime-stream real-device-harness` | `operator_triggered_tool` |
| `runtime_stream_real_device_control_drill.py` | argparse real-device control drill | `scout runtime-stream control-drill` | `operator_triggered_tool` |
| `runtime_stream_real_device_policy_drill.py` | argparse real-device policy drill | `scout runtime-stream policy-drill` | `operator_triggered_tool` |
| `admin_local_raster_source.py` | argparse local raster source metadata | `scout map raster-source` | `local_evidence_query` |
| `admin_local_raster_tiles.py` | argparse local raster tiles | `scout map raster-tiles` | `workspace_write` |
| `admin_tile_cache_builder.py` | argparse OSM tile cache plan | `scout map tile-cache-plan` | `workspace_write` |
| `sensorlog_to_gpx.py` | argparse SensorLog to GPX conversion | `scout evidence sensorlog-to-gpx` | `workspace_write` |
| `phase1_replay_demo.py` | argparse Phase 1 replay demo | `scout debug phase1-replay` | `decision_support` |
| `phase2_import_phase1_incident.py` | argparse incident import | `scout phase2 import-incident` | `operator_triggered_tool` |
| `phase2_team_replay_demo.py` | argparse team replay demo | `scout phase2 team-replay` | `decision_support` |
| `live_runtime_enablement_cli.py` | argparse preflight-only live runtime enablement report | `scout runtime live-enable-preflight` | `decision_support` |
| `live_runtime_soak_check.py` | argparse soak checker | `scout runtime soak-check` | `local_evidence_query` |
| `phase4_pretrip_release_check.py` | argparse pretrip alpha release gate | `scout checks pretrip-release` | `local_evidence_query` |
| `phase35_runtime_readiness_check.py` | argparse Phase 3.5 readiness gate | `scout checks runtime-readiness` | `local_evidence_query` |
| `assistant_readiness_check.py` | argparse assistant readiness gate | `scout checks assistant-readiness` | `local_evidence_query` |
| `alpha_device_smoke_check.py` | argparse alpha device smoke | `scout checks alpha-device-smoke` | `local_evidence_query` |
| `local_artifact_hygiene_check.py` | argparse local artifact hygiene | `scout checks artifact-hygiene` | `local_evidence_query` |

Development/fixture CLIs such as `generate_pretrip_chilai_fixture.py`,
`generate_phase1_fixtures.py`, `generate_field_golden_case.py`,
`pretrip_scout260512_fixture.py`, `tools/admin_ui_smoke_app.py`, `server.py`,
and `test_queue_monitoring.py` should stay operator/developer-only unless a
separate manifest marks them safe for agent use.

## Thin CLI Wrappers Needed

These units already have useful pure functions or Pydantic contracts but no
direct CLI. They are strong candidates for small wrappers.

| Existing unit | Useful functions/contracts | Proposed capability | Agent mode |
| --- | --- | --- | --- |
| `pretrip_workspace_edit.py` | `append_pretrip_workspace_edit`, `apply_pretrip_workspace_edit_to_workspace`, `PreTripWorkspaceEditRequest` | `scout cp propose-add`, `scout cp propose-delete`, `scout pretrip workspace-edit` | `proposal_write` / `workspace_write` |
| `pretrip_review_decision_store.py` | `append_review_decision`, `append_review_decisions`, `rebuild_review_decision_log` | `scout pretrip review append-decision(s)` | `workspace_write` |
| `pretrip_review_decision_apply.py` | `build_review_decision_apply_plan_from_paths`, boundary-marked apply plan | `scout pretrip review apply-plan` | `decision_support` |
| `pretrip_departure_reviewed_candidates.py` | `write_departure_reviewed_candidates_for_workspace` | `scout pretrip departure reviewed-candidates` | `package_write` addendum |
| `pretrip_route_note_disposition_store.py` | `append_route_note_disposition`, `build_route_note_disposition_record` | `scout pretrip route-note disposition-append` | `workspace_write` |
| `pretrip_route_note_reviewed_assumptions.py` | `write_route_note_reviewed_assumptions_for_workspace` | `scout pretrip route-note reviewed-assumptions` | `workspace_write` |
| `pretrip_expert_contribution_apply_plan.py` | `write_expert_contribution_apply_plan`, `apply_expert_contributions_to_workspace` | `scout pretrip expert apply-plan`, `scout pretrip expert apply-workspace` | `decision_support` / `workspace_write` |
| `pretrip_review_queue.py` | `build_chilai_review_queue_manifest`, `load_review_queue_manifest` | `scout pretrip review queue-build` | `decision_support` |
| `pretrip_artifact_manifest.py` | `build_pretrip_artifact_manifest` | `scout pretrip artifact-manifest` | `local_evidence_query` |
| `pretrip_source_registry.py` | `write_default_pretrip_source_registry` | `scout pretrip source-registry` | `local_evidence_query` |
| `pretrip_readiness.py` | `evaluate_pretrip_readiness` | `scout pretrip readiness` | `decision_support` |
| `pretrip_decision_register.py` | `load_pretrip_decision_register` | `scout pretrip decision-register` | `local_evidence_query` |
| `pretrip_departure_bundle.py` | `build_chilai_departure_bundle`, `load_departure_bundle` | `scout pretrip departure bundle` | `package_write` |
| `pretrip_runtime_handoff.py` | `write_runtime_handoff_manifest_for_workspace` | `scout pretrip runtime-handoff` | `package_write` |
| `pretrip_runtime_export.py` | `write_runtime_export_bundle_for_workspace` | `scout pretrip runtime-export` | `package_write` |
| `pretrip_runtime_activation_preflight.py` | `build_runtime_activation_preflight_report` | `scout runtime activation-preflight` | `decision_support` |
| `pretrip_runtime_activation_request.py` | `write_runtime_activation_request_for_workspace` | `scout runtime activation-request` | `operator_triggered_tool` |
| `runtime_load_dry_run.py` | `build_runtime_load_dry_run_report` | `scout runtime load-dry-run` | `decision_support` |
| `pretrip_admin_view.py` | `build_pretrip_admin_view`, projection loaders | `scout kb pretrip-view-summary` | `local_evidence_query` |
| `hardware_readiness_admin_view.py` | `load_hardware_readiness_fixture`, `build_hardware_readiness_admin_view` | `scout kb hardware-readiness-summary` | `local_evidence_query` |
| `runtime_debug_log.py` | `FileRuntimeDebugEventLog`, `MemoryRuntimeDebugEventLog` | `scout note append-flight-recorder`, `scout debug trace-tail` | `workspace_write` / `local_evidence_query` |
| `mock_voice_transport.py` | `MockVoiceTransport`, `MockVoiceTransportRecord` | `scout voice mock-queue`, `scout voice mock-transition` | `outbound_preview` |
| `voice_tts_provider.py` | `TTSCommandPlan`, `execute_command_plan` | `scout voice preview`, future `scout voice play-local` | `outbound_preview` / `hardware_action` |
| `voice_cue_policy.py` | `VoiceCuePolicy.choose_next` | `scout voice choose-next` | `decision_support` |
| `mock_outbound_transport.py` | `MockOutboundTransport` | `scout outbound mock-queue`, `scout outbound mock-deliver` | `outbound_preview` |
| `hardware_control_events.py` | `HardwareControlEvent`, `project_hardware_control_event` | `scout hardware event-project` | `local_evidence_query` |
| `skill_registry.py` / `skill_runtime.py` | manifest load/list, `record_mock_skill_run` | `scout skills list`, `scout skills record-run` | `local_evidence_query` / `workspace_write` |

## Existing Skill Manifests

The current `skills/scout/*.yaml` manifests are useful examples for the agent
tool registry because they already model activation gate, allowed reads/writes,
failure policy, control surface, and audit settings.

| Skill id | Type | Activation | Candidate CLI mapping |
| --- | --- | --- | --- |
| `device-capability-check` | check | manual | `scout skills run device-capability-check` |
| `communication-state-check` | check | manual | `scout skills run communication-state-check` |
| `latest-team-position-check` | check | manual | `scout skills run latest-team-position-check` |
| `team-checkin-summary` | summary | operator approved | `scout skills run team-checkin-summary` |
| `checkpoint-delay-analysis` | analysis | operator approved | `scout skills run checkpoint-delay-analysis` |
| `decision-options` | analysis | operator approved | `scout skills run decision-options` |
| `remote-status-json` | artifact | operator approved | `scout skills run remote-status-json` |
| `beacon-trend-mock` | beacon | operator approved | `scout skills run beacon-trend-mock` |
| `team-rendezvous-beacon` | beacon | operator approved | `scout skills run team-rendezvous-beacon` |

## New Capabilities Not Fully Present Yet

These are central to the user's desired Scout Agent behavior, but they need new
composition code rather than a thin wrapper.

| Needed capability | Current building blocks | Gap |
| --- | --- | --- |
| `scout kb build/query` | pretrip/admin/debug context adapters, project refs, source registry, artifact manifest | no unified offline local evidence index yet |
| `scout safety-action shelter-direction` | route/risk/heatmap outputs, reviewed CP/SCP, weather overlay, route matching | no deterministic shelter candidate ranker yet |
| `scout note append-flight-recorder` | `runtime_debug_log.py`, `RuntimeDebugEvent` | no generic agent action event kind or note append CLI yet |
| `scout cp apply-reviewed-delta` | workspace edits, review decisions, departure reviewed candidates | no agent delta schema/result envelope yet |
| `scout voice preview/send` | voice cue models, TTS provider, mock voice transport, provider send CLIs | no unified preview/send manifest with receipts yet |
| `scout hardware alarm-start/stop` | hardware readiness, GPIO projection, voice/smoke tools | no real alarm hardware action implementation yet |
| `scout sos playbook-run` | runtime remote provider policy/send queue, Telegram send CLI, mock outbound, voice cue, runtime debug log | no deterministic emergency playbook orchestrator yet |

## Not Recommended As Direct Agent Tools

Expose these through higher-level wrappers or dry-run/replay commands instead:

- `safety_api.py`, `safety_state_machine.py`, `safety_runtime_session.py`:
  Phase 1 safety authority; do not expose mutation directly.
- `route_progress.py`, `route_matching.py`, `mission_progress.py`:
  core runtime mechanics; expose through replay/dry-run/query tools.
- `server.py`, `admin_api.py`, `debug_api.py`, `hardware_readiness_api.py`:
  web/API surfaces, not Pydantic AI tool subprocesses.
- `agent.py`: current experimental Pydantic AI navigation assistant; should be
  replaced or wrapped by the new registry instead of becoming the registry.
- Fixture generators and release checks: useful for operators and CI, but
  should not be routine autonomous agent tools.

## Recommended First Wrapper Set

The smallest useful set for the next branch:

1. `scout tools list|describe|run`
2. `scout debug trace-tail`
3. `scout note append-flight-recorder`
4. `scout kb pretrip-view-summary`
5. `scout cp propose-add`
6. `scout cp propose-delete`
7. `scout voice preview`
8. `scout risk attribution`
9. `scout risk heatmap`

This set proves Pydantic AI can use Scout resources to read evidence, propose a
critical planning change, generate a voice/action preview, and write an
auditable trace without opening live safety mutation.
