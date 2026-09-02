# Scout Terrain Route Host Parity Receipt (2026-09-01)

## Scope

This receipt verifies that the candidate-only Terrain Route Hypothesis workflow
can execute on both the macOS development host and the Scout aarch64 host. It
does not verify a trail, passage, field safety, legal access, or operational
navigation authority.

Boundary:

- `authority: candidate_only`
- `runtime_safety_truth: false`
- `operational: false`
- `safe_or_walkable: not_determined`

## Fixed input contract

- DEM source SHA-256: `e6a4c3c6aa279d9cc82246f39bd94c04082cac0f1d7eeea34f732875917ffe62`
- terrain parent manifest SHA-256: `11034c4d12a986b0073cdf4672d9a65cb01e2b6db34b8096fa2b4a1e3b34eff8`
- input contract SHA-256: `8c4991fb38674ebd73191c3a7f0c52eb8581b5a092435c1ae70c402b194a42ca`
- DEM resolution: 20 m
- A: `121.056555, 23.460559`
- B: `121.041062, 23.476547`
- analysis margin: 1000 m
- cost model: `terrain_routing_cost.v0_2`
- algorithm: `terrain_route_hypothesis.v0_3`

## Hosts and runtime

| Host | Architecture | QGIS | GRASS | Duration | Artifacts |
|---|---|---|---|---:|---:|
| Mac | x86_64 | 3.44.13-Solothurn | 8.5.0 | 59.722 s | 21 |
| Scout test container | aarch64 | 3.44.13-Solothurn | 8.4.1 | 29.747 s | 21 |

The Scout run used the isolated `scout-fusion/pi-gis-worker:v0.1` image. It did
not restart or modify the live Scout Admin container.

## Result

Machine status: `passed_with_engine_variance`.

- R1, R2, and R3 vertex counts matched at 95, 93, and 89.
- Each path comparison had Hausdorff distance about `3.93e-10 m`.
- Route cost, distance, elevation, slope, and pressure metric differences were
  zero or floating-point tail values below `1e-6`.
- Corridor cell-count relative differences were about 1.08 to 1.10 percent.
- Corridor threshold relative differences were about 1.13 to 2.07 percent.
- All corridor differences stayed within the declared 3 percent parity bound.

The corridor difference is retained as engine-version evidence. It is not
hidden or converted into a safety confidence. Exact GRASS 8.5.0 versus 8.4.1
parity remains unknown until the runtimes are aligned and rerun.

## Provenance semantics

The source DEM content hash is now distinct from the bounded analysis-raster
byte hash. The source hash identifies the authoritative input. The analysis
raster hash may differ across GDAL/GRASS builds because file metadata and
quantile implementation details can vary even when model geometry agrees.

Cache and receipt identities exclude host-specific file paths and evidence-path
strings. They retain DEM content hashes, parent-manifest hash, resolution
semantics, endpoints, margin, cost configuration, and optional guidance review
hash.

## Evidence files

- `scout-terrain-route-mac-receipt-20260901.json`
- `scout-terrain-route-scout-receipt-20260901.json`
- `scout-terrain-route-host-parity-20260901.json`

## Remaining unknowns

- exact engine-version parity
- field conditions
- vegetation
- microterrain below the 20 m DEM grid
- recent landslides
- legal access
- engineered trail, bridge, rope, stair, or tunnel features
- real R4 output until a human confirms explicit map-point anchors
