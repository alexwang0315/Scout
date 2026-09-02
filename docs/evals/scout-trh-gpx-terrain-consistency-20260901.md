# Scout TRH GPX Terrain Consistency Receipt

Date: 2026-09-01

Status: `WORKING PROTOTYPE`

Assessment: `PARTIALLY_CONSISTENT`

Semantics: `terrain_consistency_not_gpx_validity`

## Boundary

```text
authority=candidate_only
source_type=known_gpx
candidate_only=true
runtime_safety_truth=false
operational=false
safe_or_walkable=not_determined
known_gpx_mutated=false
```

This receipt does not verify a trail, passage, safety, legal access, or GPX
validity. It does not recommend a route and does not modify the GPX.

## Inputs

- Workspace: `dongqing_batongguan_historic_trail_qgisGrass_clean_20260828`
- Candidate: `R1`
- Corridor: `top_10_percent_corridor`
- GPX SHA-256: `5f0ff2993d561d8f3c5b108db215d312d85d703e51e1fd93743940768df916db`
- Hypothesis SHA-256: `e0b3610b5ed8b3907378cc44d41b9aec04946062d68fd2a7e9f96dca0322509a`
- Corridor raster SHA-256: `9eff498a7f0e88dea299e974309610457920e17e2709ec7a1e00e2c579d3f8dd`
- Slope raster SHA-256: `f1c94c6b2d092aacfa8dc885a82ca755fe5bcb21f42ded2eb20e20f83757d696`
- Sampler: `gdal_location_info.v0_1`
- Analysis ID: `gpx-terrain-55a6eb8ff261c60f`

## Result

| Evidence | Result |
|---|---:|
| GPX segment points | 5,768 |
| Deterministic samples | 400 |
| Outside selected corridor | 2 / 400 (0.5%) |
| Extreme DEM slope cells | 95 / 398 (23.869%) |
| More than 100 m from the selected model trace | 374 / 400 (93.5%) |
| Median trace deviation | 1,790.870 m |
| Maximum trace deviation | 4,769.361 m |
| Outside analysis extent | 2 / 400 |
| Map anomaly samples | 377 |
| Drainage evidence | `UNKNOWN` |
| TEII evidence | `UNKNOWN` |

The high trace-deviation fraction compares the known GPX with one minimum-cost
model trace. It does not imply that the GPX is wrong or that the model trace is
an existing trail.

Possible explanations remain: GPS drift, DEM error, an engineered or official
trail, rope, bridge, tunnel, old or historical route, landslide, and data
mismatch. Current vegetation, microterrain, recent ground condition, water
state, legal access, and engineered features remain unknown.

## Verification

- 254 focused Scout AI/tool/planner/guidance/terrain tests passed.
- 16 direct terrain-consistency and Admin API tests passed.
- 137 Dashboard static/contract tests passed.
- Dashboard inline JavaScript parsed successfully in Node.
- Real Admin API replay returned HTTP 200 and preserved candidate-only headers.
- In-app browser showed the selected full-route artifact as
  `PARTIALLY_CONSISTENT`; MapLibre 2D remained ready, and the 3D canvas and
  Rudy+TW attribution remained present.
