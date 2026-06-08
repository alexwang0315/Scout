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
  --model gpt-4o-mini
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
- The generated package sandbox gate rejects disallowed network patterns before
  execution.

## Deliberate Blocked Gates

The profile intentionally reports these as not ready:

- generated capability runtime code installation outside sandbox metadata;
- live external notification transports;
- live external-model timeout, budget, and fallback SLA enforcement;
- direct promotion of mobile/wearable/provider values into Phase 1 L0-L4 safety
  truth.

Those gates require OS-level or container-grade sandbox isolation, artifact
hashing, rollback/revoke, operator confirmation, rate limiting, audit replay,
and a dedicated external-model call wrapper before they can be promoted.
