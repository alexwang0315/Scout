# Scout AI OS Hardware Smoke Profile

This profile is the first Scout-hardware landing path for the Scout AI OS MVP.
It verifies the new AI OS layer on a Scout host without granting model output,
generated code, external notifications, or UI operations any new runtime safety
authority.

## Default Command

```bash
./venv/bin/python -m pip install -e .
./venv/bin/scout-ai-os-hardware-smoke --repo-root /Users/alexwang0315/scout-fusion
```

The default run forces the local Pydantic AI `FunctionModel`, even if
`SCOUT_AI_OS_MODEL` is present in `.env`. This prevents a hardware smoke from
accidentally consuming OpenRouter quota.

To opt in to an external model smoke:

```bash
./venv/bin/scout-ai-os-hardware-smoke \
  --repo-root /Users/alexwang0315/scout-fusion \
  --allow-external-model \
  --model glm-5.2
```

If the required credential is missing, the report marks the model check as
`blocked` and reports only the missing environment variable name.

## Evidence JSON

Real mobile, wearable, or hardware probe output can be attached as evidence:

```bash
./venv/bin/scout-ai-os-hardware-smoke \
  --repo-root /Users/alexwang0315/scout-fusion \
  --evidence-json /path/to/hardware-evidence.json
```

The evidence must include boundary metadata. Any `true` value for hardware
control, outbound send, Phase 1 L0-L4 mutation, `/safety/*` mutation, runtime
ingest, or provider-values-as-Scout-truth blocks the evidence check.

Evidence JSON can be produced from a real mobile, wearable, or hardware probe
sample. The default input is a Scout sample JSON object, and the producer also
supports Sensor Logger JSON/CSV, NMEA GNSS text, and Scout host-probe JSON:

```bash
./venv/bin/scout-ai-os-hardware-evidence \
  --source sensor_logger_pro_mqtt \
  --source-device-id iphone-test-device \
  --source-format sensor-logger-json \
  --sample-json /path/to/sample.json \
  --evidence-dir /path/to/evidence-dir
```

The producer writes a `scout_hardware_evidence.v0` artifact with
`advisory_only=true`, `not_safety_truth=true`, and all runtime/safety mutation
flags set to `false`. When `--evidence-dir` is used, it also writes a
`scout_hardware_evidence_directory.v0` index for audit/replay.

## What This Profile Verifies

- Scout AI OS modules import on the hardware host.
- FastAPI routes, capability registry, runtime scheduler status, and boundary
  router smoke pass.
- Pydantic AI local smoke works without network.
- Optional external model config is redacted and blocks cleanly when credentials
  are missing.
- Session-local UI operation requests produce a `scout_ui_action_plan.v0`
  artifact without applying browser, hardware, or runtime effects.
- Generated capability build approval remains metadata-only.
- External notification intent can be recorded through a dry-run provider with
  `sent=false`.
- Low-risk external notification can use a live-send provider path only after
  operator confirmation, recipient allowlisting, rate-limit/audit tracking, and
  priority gating. The smoke uses memory transport plus a fake-network Telegram
  Bot API adapter proof, and reports `live_network_verified=false`.
- The generated package sandbox gate rejects disallowed network patterns before
  execution.
- Generated runtime install lifecycle computes an artifact hash, requires a
  safe isolation profile and operator approval, and verifies install/revoke/
  rollback records. It also runs an isolated proof-only `run(payload)` dispatch
  while keeping active runtime dispatch disabled.
- External model calls are wrapped by the model SLA gateway for timeout,
  budget preflight, retry telemetry, provider health/circuit breaker, and local
  fallback enforcement.

## Remaining Deliberate Boundaries

The profile still keeps these as not enabled:

- direct promotion of mobile/wearable/provider values into Phase 1 L0-L4 safety
- direct live network notification proof; and
- active generated runtime dispatch from installed generated code.

Those boundaries require explicit promotion. In particular, generated runtime
install records are not wired into the action executor, the generated dispatch
proof is isolated and proof-only, and notification smoke does not send to a real
external network endpoint.
