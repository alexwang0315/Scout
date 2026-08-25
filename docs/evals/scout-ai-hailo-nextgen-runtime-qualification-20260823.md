# Scout AI Hailo NextGen Runtime Qualification

```yaml
experiment_id: SCOUT-AI-EXP-HAILO-NEXTGEN-006
hypothesis: >
  A Raspberry Pi 5 AI HAT+2 runtime can serve one resident Hailo model through
  ScoutModelGateway for bounded typed inference and PraisonAI terrain synthesis,
  while deterministic Scout Core retains all authority and tool execution.
baseline: >
  The same fixed terrain corpus passed the OpenAI-compatible replay and a CPU
  Ollama qwen3:1.7b path. MAX behavior qualification is blocked on the Intel Mac,
  while the Pi already exposes a loopback-only Hailo Ollama 5.3 service.
implementation_scope:
  - Experimental OpenAI-compatible Hailo configs only.
  - Explicit request control-character and response timestamp compatibility.
  - Basic chat, small typed output, independent read-only tool calling, and
    diagnostic Praison MCP qualification.
  - Optional compact specialist advisory; server code owns IDs, authority flags,
    evidence normalization, candidate contracts, and final validation.
  - No production routing, Workspace writes, mission mutation, permission,
    notification, emergency, device, or safety effects.
fixed_case: terrain-http-qualification-edge-cpu-v0
decision:
  hailo_basic_chat: ACCEPT_EXPERIMENTAL
  hailo_small_typed_output: ACCEPT_EXPERIMENTAL
  hailo_native_tool_calling: REJECT
  hailo_qwen3_praison_specialist: REJECT
  hailo_qwen2_5_coder_praison_specialist: REJECT
  compact_advisory_contract: CONTINUE_RESEARCH_ON_STRONGER_RUNTIME
  production_promotion: NOT_REQUESTED
```

## Architecture Result

The qualified role split is:

```text
Pydantic AI / Scout Core
  -> deterministic task and capability routing
  -> deterministic read-only tool execution
  -> ScoutModelGateway
       -> Hailo: chat and small typed envelopes
       -> MAX / Mac / cloud: Praison specialist synthesis candidate
  -> Pydantic Contract Gateway
  -> candidate evidence only
```

PraisonAI remains integrated behind MCP, but these two Hailo models are not
qualified as its specialist reasoning backend. Logical agents must not imply
that every agent uses the smallest edge model.

## Live Results

### qwen3:1.7b

- Basic chat passed. Observed latency ranged from 2.38 s to 10.41 s.
- Small typed output passed in one model request at about 5.0 s after the probe
  explicitly requested the complete JSON object.
- Independent tool calling failed: the model returned the completion marker but
  made zero calls to the bounded read-only probe tool.
- Full SpecialistReport synthesis exhausted 10 model requests in 241.98 s.
- Compact advisory synthesis still failed: three requests ended in
  `ModelHTTPError` after 236.31 s of model execution.

### qwen2.5-coder:1.5b

- Basic chat passed at 2.45 s after model warm-up; the initial load run was
  9.99 s.
- Small typed output passed in one request at 4.44 s.
- Independent tool calling failed with zero tool calls.
- Compact advisory synthesis exhausted 10 requests in 183.51 s.

Both failed Praison runs returned explicit degraded/UNKNOWN candidate responses.
The Pydantic Contract Gateway accepted only the candidate boundary; no runtime
state was promoted. No tool capability attestation was created.

## Compatibility Findings

Hailo Ollama 5.3 emits a nanosecond-scale `created` value that the OpenAI SDK
rejects as a Unix timestamp. The experimental transport normalizes its units
before SDK validation. The same service rejects C0/C1 characters in chat
content, so an explicit Hailo-only mode applies the existing Scout replacement
rule before transmission.

The provider accepts JSON Schema request fields but does not consistently enforce
them. Pydantic validation remains mandatory. Prompted output alone was not
sufficient, and neither JSON Schema acceptance nor small typed success is
evidence of native constrained decoding.

## Resource Observation

After qualification, `scout-hailo-ollama.service` remained active with zero
restarts. HAILO10H firmware, HailoRT, PCIe driver, and GenAI model zoo were all
5.3.0. The Pi reported 49.9 C, no throttle flags, about 7.0 GB available RAM,
and about 61.8 MiB host RSS for the service. These observations do not measure
NPU memory or energy and are not production performance attestations.

## Evidence

- `model-runtime-qualification-hailo-qwen3-1.7b-typed-native-explicit-20260823.json`
  (`cf78d74ea9cc99bec8e8764a08add28cc5b61e8479684529308c1092a24609ce`)
- `model-runtime-qualification-hailo-qwen3-1.7b-tool-20260823.json`
  (`09796bc077b203c41cacaaa4a3075ba48a61777af567214751a18ec87175187d`)
- `model-runtime-qualification-hailo-qwen3-1.7b-compact-praison-20260823.json`
  (`b4673690bc436a746007b6307e3aa598f021e01adf15e3ef635554500820fdc2`)
- `model-runtime-qualification-hailo-qwen2.5-coder-1.5b-typed-20260823.json`
  (`6a8a1e23889ce94b640867f3c02c5918c80fc9bd4380faa73373c5bfeb0366c5`)
- `model-runtime-qualification-hailo-qwen2.5-coder-1.5b-compact-praison-20260823.json`
  (`9c44c57073f5df26210bd6e45586f7efde94fd7741dfce2a1d456e9ed23b769c`)
- `hailo-runtime-observation-20260823.json`

## Rollback

Remove the two Hailo runtime configs, Hailo compatibility switches, compact
advisory mode, diagnostic qualification switch, tests, and experiment artifacts.
The existing production Scout runtime and the prior MCP/Praison replay path are
unchanged.
