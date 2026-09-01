# Scout AI Live Edge Runtime Qualification

```yaml
experiment_id: SCOUT-AI-EXP-LIVE-EDGE-QUAL-20260901
hypothesis: >
  The checked-in Scout Model Gateway classifications can be verified on the
  Raspberry Pi without granting any model, PraisonAI agent, or QGIS workflow
  authoritative runtime access.
scope:
  - Raspberry Pi 5 CPU Ollama and Hailo AI HAT+ 2 live model probes.
  - Running PraisonAI background-job cancellation and restart inspection.
  - Intel Mac and Raspberry Pi MAX host preflight.
  - Candidate-only QGIS terrain-context processing and render inspection.
  - No production routing, mission, route, permission, safety, notification,
    emergency, or device mutation.
decision: ACCEPT_PARTIAL
candidate_only: true
runtime_safety_truth: false
```

## Decision Matrix

| Surface | Live result | Decision |
| --- | --- | --- |
| Pi CPU Ollama `qwen3:1.7b` | Chat, typed output, native read-tool call, Praison MCP, and authority gate passed | `ACCEPT_EXPERIMENTAL_BACKGROUND` |
| Hailo `qwen3:1.7b` | Chat and small typed output passed; native tool calling and Praison MCP failed | Keep `CHAT + SMALL_TYPED_OUTPUT`; reject specialist/tool workload |
| Praison background queue | Running specialist job cancelled, persisted, restored, and discarded | `ACCEPT_EXPERIMENTAL` |
| MAX on Intel Mac | Intel macOS host is incompatible; no MAX request executed | `MORE_EVIDENCE_REQUIRED` on an Apple Silicon or supported Linux GPU host |
| MAX on Raspberry Pi 5 | Cortex-A76 and observable RAM fail current MAX host requirements; no MAX request executed | `HOST_INCOMPATIBLE`, not an architecture failure |
| QGIS processing | Live 20 m DEM slope workflow completed with candidate-only artifacts | `PASS` for deterministic processing |
| QGIS visual evidence | Tiny 113x45 render exposed a false-positive gate; minimum-size gate now rejects it. Isolated rerun produced 500x346 | Technical gate `PASS`; human terrain legibility remains `CONTINUE_RESEARCH` |

## Live Measurements

### Raspberry Pi CPU Ollama

- Basic chat: 7,865 ms, one request.
- Typed output: 8,079 ms, one request.
- Native read-only tool calling: 26,692 ms, two requests, one tool call.
- Praison MCP terrain slice: 90,356 ms, one model request and three read-only
  tools: `dem.read`, `qgis.processing.slope`, and `route.read`.
- Total: 133,373 ms, five model requests, four tool calls.
- Report hash:
  `62caca6504eb26981d73f8dd84cf80863ae378ac2a4eadd473bfa9d1790bcd8e`.
- A short-lived tool-calling attestation was issued for this exact report. It
  does not grant runtime or safety authority.

### Hailo AI HAT+ 2

- Basic chat: 9,711 ms.
- Small typed output: 4,972 ms.
- Native tool calling: failed after 2,505 ms because no exact tool call was made.
- Praison MCP: failed/degraded after 240,013 ms with `ModelHTTPError` after
  three model requests and two read-only tool calls.
- Total: 257,615 ms. Authority validation still passed, and the failed
  specialist output was retained only as explicit candidate uncertainty.
- Report hash:
  `5cc29b8bded2a9aa0eb651368a368a9c809b4ac152079ba28bff3235407110ef`.

The Hailo evidence supports the narrow Gateway capability declaration. It does
not support native tools, long Praison workflows, or an attestation for those
capabilities.

### Background Cancellation

- Cancellation was requested after `specialist:terrain:running`.
- The provider-bound operation reached `cancelled` after 56.509011 seconds.
- The persisted terminal job has no response.
- Reloading the queue and requesting the result raises
  `BackgroundIntelligenceJobCancelled`; partial output is not recoverable.
- Post-run Pi state was 50.5 C, `throttled=0x0`, with both local model services
  still reachable.

### MAX Preflight

The Intel Mac reports Darwin `x86_64`, macOS 13.7.8, and 8 GiB RAM. Current MAX
packages require Apple Silicon and macOS 15 or later. The Raspberry Pi reports
Linux `aarch64`, Cortex-A76, and 8,454,602,752 observable bytes; current MAX ARM
qualification requires verified Neoverse N1 or newer and at least 8 GiB of
observable memory. Both preflights made zero model requests and preserved the
candidate-only boundary.

The Linux CPU parser now ignores numeric `/proc/cpuinfo` processor indices and
falls back to structured `lscpu --json`, so Pi evidence records `Cortex-A76`
instead of `0` or an unknown model.

### QGIS

The live `terrain_context_preview.v1` workflow completed DEM clipping, slope
processing, route rendering, provenance, and candidate-only artifact creation.
The first cropped render was only 113x45 and was visually unusable even though
the old content-pixel threshold passed it. The quality gate now additionally
requires a 320x180 render. The original image is rejected deterministically;
an isolated live rerun produced a 500x346 render and passed the technical gate.

The rerun still requires human review before its slope visualization can be
treated as sufficient explanatory evidence. It cannot establish trail
existence, route safety, passability, or operational truth.

## Qualification Evidence

- `artifacts/scout-ai-nextgen/model-runtime-qualification-pi-cpu-qwen3-1.7b-live-20260901.json`
- `artifacts/scout-ai-nextgen/model-runtime-attestation-pi-cpu-qwen3-1.7b-live-20260901.json`
- `artifacts/scout-ai-nextgen/model-runtime-qualification-hailo-qwen3-1.7b-pi-live-20260901.json`
- `artifacts/scout-ai-nextgen/praison-background-cancel-pi-live-20260901.json`
- `artifacts/scout-ai-nextgen/max-runtime-preflight-intel-mac-live-20260901.json`
- `artifacts/scout-ai-nextgen/max-runtime-preflight-pi-live-final-20260901.json`
- `artifacts/scout-ai-nextgen/live-qgis-20260901/`
- `artifacts/scout-ai-nextgen/live-qgis-min-render-gate-20260901/`

## Remaining External Gate

MAX chat, structured output, tool calling, latency, and memory qualification
remain unrun because neither available host satisfies the current runtime
requirements. This is the only hardware-dependent item in this experiment. It
must be resumed on a supported Apple Silicon or Linux GPU host; it must not be
simulated by relabeling Hailo or Pi CPU Ollama as MAX.

## Rollback

Remove the MAX CPU-model parsing fix, the minimum QGIS render dimensions, and
this experiment evidence. The existing model runtime routing, QGIS processing,
Praison queue, and all authoritative Scout paths remain unchanged.
