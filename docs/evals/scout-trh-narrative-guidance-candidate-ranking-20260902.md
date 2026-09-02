# Scout TRH Narrative Guidance Candidate Ranking Evidence

Date: 2026-09-02

Project: `dongqing_batongguan_historic_trail_qgisGrass_clean_20260828`

## Boundary

- `authority=candidate_only`
- `source_type=historical_route` for the narrative guidance input
- `runtime_safety_truth=false`
- `guided_execution_ready=false`
- No DEM candidate was promoted to an observed, official, verified, passable,
  safe, recommended, or legally accessible route.

## Input binding

The Dashboard catalog option `iroko-1148-to-station` supplied the previously
hash-validated local endpoints:

- A: `121.25622601185889, 23.3445199857792`
- B: `121.23041872103398, 23.352571034657494`
- Analysis margin: `1000 m`
- DEM resolution: `20 m`
- Elevation sampler: `gdal_location_info.v0_1`
- Reference hypothesis: `iroko-1148-to-station`
- Reference band: `top_5_percent_corridor`
- Candidate rank semantics:
  `typed_landform_elevation_then_candidate_corridor_overlap_then_narrative_sequence_proximity`
- Corridor rank semantics:
  `candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation`

Re-resolution cleared every prior review ref/hash and retained
`guided_execution_ready=false`.

## Result

DEM sampling completed and produced three ridge-local-minimum saddle proxies in
the bounded A/B search extent. The resolver then verified the project catalog,
completed hypothesis artifact, cache key, matching endpoints, parent-source hash
chain, and source corridor GeoTIFF before sampling its `1=inside`,
`255=NoData/outside` mask. It collected 1,595 bounded samples across 203 DEM
features: 78 samples were inside and 18 features had non-zero overlap.

| Constraint | Typed meaning | Result |
|---|---|---|
| `G1` | Historical 1148 saddle candidate | One candidate: `1144.57 m`, zero 5% corridor overlap, retained for review |
| `G6` | Ridge turn near H820 | Five candidates retained; elevation difference remains the primary typed rank, and individual overlap is preserved |
| `G7` | Drainage crossing after descent | 131 candidates retained; top-five overlap fractions were 100%, 83%, 50%, 46%, and 38% |
| `G11` | Terminal Iroko ridge | 32 candidates retained; top-five overlap fractions were 100%, 100%, 100%, 55%, and 40% |

The Dashboard displays up to five rank markers for orientation. These markers
are not selectable execution anchors. A human must explicitly activate a
constraint's map-anchor mode and place a WGS84 Point before review can become
R4-eligible.

Corridor overlap does not filter the candidate set, select an anchor, confirm
the historical narrative, or establish a trail. It only compares each terrain
feature with one selected model corridor to improve review ordering after typed
landform and elevation semantics.

## Verification

- Synthetic sampler tests prove DEM elevation enrichment and saddle-proxy
  derivation without a real GRASS/GDAL installation.
- A sampling failure leaves the workspace at `interpreted` with no partial
  feature index, resolution, or review artifact.
- Re-resolving after a completed review clears the review binding and execution
  gate.
- Tampering with the referenced corridor raster fails before any feature index,
  resolution, or review artifact is written.
- Synthetic overlap tests retain zero-overlap alternatives and prove that
  overlap may alter review order without populating `selected_feature_ids`.
- Navigation projection now includes hash-validated hypothesis endpoints so the
  Dashboard can reuse the selected local A/B.
- Inline Dashboard JavaScript parses successfully and the live browser showed
  the local A/B, completed sampler status, corridor provenance, ranked
  `G1`/`G6`/`G7`/`G11` previews, disabled review, and disabled R4 execution.
- The expanded focused regression suite completed with `520 passed`; Ruff and
  diff whitespace checks passed.
- The local `1148 鞍 → 異祿閣駐在所` option rendered in both 2D and 3D with one
  MapLibre canvas and no `MAPLIBRE TILE / WEBGL ERROR` banner. The 20 m DEM,
  Rudy+TW context, candidate path, corridor, A/B, and narrative rank markers
  remained visible.

## Remaining UNKNOWN

The candidate ranking does not determine the historical point locations. The
G1 elevation match and zero selected-corridor overlap are contradictory review
evidence, not grounds to accept or reject the point. The ridge-local-minimum
proxy does not verify the named 1148 saddle. Vegetation, microterrain, current
water, recent landslide, engineered trail structures, legal access, and
present-day passage remain UNKNOWN.
