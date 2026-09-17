# Scout AI Pi Real-Route Terrain Vertical Slice

```yaml
experiment_id: SCOUT-AI-EXP-PI-REAL-TERRAIN-008
hypothesis: >
  A Raspberry Pi 5 can run the MCP-isolated PraisonAI terrain slice against
  real bound Scout/QGIS evidence using one CPU-resident model, while Pydantic
  contracts preserve candidate authority, explicit uncertainty, provenance,
  least privilege, and stale-result rejection.
current_baseline: >
  Deterministic replay and synthetic terrain cases had proved topology. Native
  Pi CPU qualification had proved chat, typed output, tool calling, Praison MCP,
  and authority checks, but had not analyzed a real Scout route artifact.
proposed_architecture: >
  IntelligenceRequest -> MCP -> Praison deterministic router -> one Terrain
  model specialist -> deterministic normalized QGIS ingestion -> typed
  IntelligenceResponse -> Pydantic Contract Gateway -> candidate evidence.
implementation_scope:
  - Existing Chilai Nanhua Day 1 golden benchmark route, read-only.
  - Existing 20 m corridor DEM and completed QGIS/GRASS terrain_feature_stack.v1.
  - Minimal evidence projection rather than raw route/GeoJSON prompt injection.
  - Raspberry Pi 5 CPU Ollama qwen3:1.7b through loopback only.
  - No Workspace, route, mission, permission, safety, notification, emergency,
    device, QGIS artifact, or production configuration write.
expected_benefit: >
  Prove the actual edge-native candidate trajectory and show that pure terrain
  work does not need a Research model call or a second QGIS model call.
risks:
  - One route and one warm/cold trajectory do not establish p95 latency.
  - QGIS human and visual review remain pending.
  - A 20 m DEM cannot establish microterrain, trail condition, navigability, or safety.
  - CPU latency is suitable only for optional background intelligence.
test_dataset: >
  Chilai Nanhua Day 1 current-golden-20260823 route and QGIS worker run
  qgis-worker-20260823T081730034427Z-ddbc522e65.
decision: ACCEPT
promotion: EXPERIMENTAL_BACKGROUND_ONLY
```

## Bound Evidence

| Evidence | Binding |
| --- | --- |
| Route | GPX SHA-256 `216f129a...9e845`; derived GeoJSON SHA-256 `706d0806...95eee`; sampled length 36505.33 m |
| DEM | SHA-256 `55dc7dae...a74`; 20 m x 20 m prepared corridor DEM |
| QGIS | Manifest SHA-256 `41e711e1...36e3`; route samples SHA-256 `256f1131...da4`; completed 2026-08-23T08:17:55.834385Z |
| Review | Human `pending`; visual `pending`; operational `false` |

The task grant allowed only `route.read`, `dem.read`, and
`qgis.processing.slope`. It denied the standard mission, baseline, permission,
safety, emergency, notification, and device write/effect capabilities.

## Result

| Metric | Observed |
| --- | --- |
| Full qualification | `PASS` |
| MCP transport | `ok` |
| Praison MCP latency | 126177 ms |
| Specialist model latency | 124072 ms |
| Model requests | 1 |
| Model | `edge.pi.ollama.cpu.background / qwen3:1.7b` |
| Model tokens | 1206 input, 190 output |
| Tools | `route.read`, `dem.read`, `qgis.processing.slope` |
| Findings | 4, all evidence-bound and candidate-only |
| Conflicts | 0 |
| Contract result | `accepted_candidate` |
| Candidate output hash | `416fe2b2...60fd` |
| Report hash | `bae7bd88...524d` |

Agent path:

```text
praisonai.orchestrator
  -> praisonai.router.deterministic.v1
  -> terrain
  -> qgis.deterministic
```

Research was not instantiated because there was no typed conflict bound to the
available evidence. QGIS did not consume a model request because the artifact
already exposed normalized `candidate_features` and typed uncertainties.

The accepted candidate reports:

- 24 of 128 route samples had multiscale ridge consensus.
- 74 samples had derived slope at least 30 degrees; 28 at least 40 degrees.
- The maximum sampled derived slope was 49.83 degrees near route distance
  10677.76 m.
- The corridor extraction contained 1114 ridge-line morphology candidates.

These observations do not establish trail existence, hazard, navigability,
safe passage, or route truth. The current workflow has no explicit reviewed
saddle derivative, so saddle presence/location remains typed `UNKNOWN`.

The model proposed one interpretation outside the server-normalized finding
set. Grounding logic discarded it and emitted an auditable uncertainty instead
of silently widening the findings.

## Failure Checks

- Replacing the current Workspace revision/input hash produced
  `STALE_BINDING`, `accepted=false`.
- `candidate_only=true` and `runtime_safety_truth=false` passed at response,
  remote validation, authority check, and report levels.
- No Research Agent, cloud fallback, alternate model, or authoritative action
  appeared in provenance.
- After the run the Pi reported 51.6 C, `throttled=0x0`, 4354 MB available RAM,
  and 128 MB swap used.

## Artifacts

- `artifacts/scout-ai-nextgen/phase3-chilai-nanhua/terrain-vertical-slice-case.json`
- `artifacts/scout-ai-nextgen/phase3-chilai-nanhua/terrain-vertical-slice-evidence.json`
- `artifacts/scout-ai-nextgen/phase3-chilai-nanhua/model-runtime-qualification-pi-native-real-route.json`

## Rollback

Delete the isolated case/evidence/report packet and unregister the experimental
Pi CPU profile. Production Pydantic Agent, route/mission stores, reducers,
permission, safety, emergency, and device behavior require no migration or data
rollback.
