# Spec: Scout Body Battery And Companion Match

## Status

Alpha slice implemented for fixture-backed wearable summary import, 7/28/90-day
baseline building, provider-value preservation, companion capability capsules,
companion match review artifacts, post-analysis feedback, and the read-only
pretrip/admin projection.

Implemented adapter scope: sanitized Apple Health and Garmin summary envelopes,
plus GPX/FIT/TCX file-derived summary envelopes, can normalize into the
provider-neutral `WearableActivitySummary` contract without storing raw health
payloads, raw tracks, exact timestamps, or home/work traces.

Implemented raw-file parser scope: local Apple Health export XML and Garmin
Connect JSON exports can be summarized one activity at a time or as deterministic
local batches, provider export directories/zips can be inspected into
privacy-preserving manifests, multiple supported Garmin activity JSON members in
one archive can be summarized together, Garmin FIT archive members can be parsed
directly from archive bytes without extraction, FIT session-summary files
and FIT lap-summary files without track points can fall back to sanitized
duration/distance/ascent/HR summary fields, and local GPX, TCX, and minimal FIT
files can be summarized into sanitized import envelopes without committing or
embedding raw health payloads, raw tracks, coordinates, exact timestamps, or
source payloads. Tests generate raw Apple Health XML, Garmin JSON, zip archives,
and GPX/TCX/FIT content in temporary directories rather than committing raw
health/track files.

Implemented Health Auto Export archive scope: Apple-compatible provider archive
inspection also recognizes `HealthAutoExport-*.json` members inside local ZIP
archives. The local parser expands `data.workouts` into sanitized Apple Health
summary envelopes, infers walking/running/cross-training activity types from
workout names, preserves route GPX and detailed `heartRateData` as local source
material only, and emits no raw health payload, raw route geometry, exact
timestamps, or source samples. Health Auto Export `physical_effort` / workout
`intensity` values are treated as source-value candidates for future calibration
and are not promoted into Scout Energy Reserve truth in this slice.

Implemented provider API contract scope: offline Garmin Health API and Apple
HealthKit-style fixture transports can summarize account-authorized response
fixtures into sanitized imports only after explicit consent. They record
redacted authorization metadata, never expose token values, and perform no live
provider API or network call.

Implemented baseline/match policy scope: local route-family profiles are emitted
when at least two activities classify into the same route family, and public
companion-match display requires at least three local query activities. Lower
history counts may still produce review-only artifacts.

Implemented local companion pool scope: privacy-preserving companion capability
capsules can be added to a local-only consent pool only after explicit consent,
matched locally, withdrawn locally, and packaged for manual local exchange.
Raw tracks, raw health payloads, exact timestamps, route-family names, and
remote upload remain excluded.

Implemented community publish dry-run scope: explicit-consent local pool entries
can be projected into a community publish dry-run artifact without private owner
refs, local consent metadata, route-family names, remote upload, or network
transport. This is a preflight contract, not a remote community service.

Implemented lifecycle scope: local admin APIs can export a coarse energy/capsule
bundle only with explicit local consent, and can delete generated baseline,
explanation, capsule, refresh, and export artifacts without deleting activity
summaries or source files.

Implemented Daily/Home scope: local admin API can write a
`scout_wearable_daily_energy_overview` artifact with current reserve band,
7/28/90-day trend, recent-load explanation, and a non-medical next-day soft cue.
It can also derive a local mobile-style `scout_wearable_daily_home_preview`
JSON artifact plus static HTML preview through
`POST /admin/wearables/daily-home-preview` and
`GET /admin/wearables/daily-home-preview`. This remains a local preview surface,
not a networked production consumer mobile app integration.

Implemented mobile handoff scope: local Daily/Home preview and optional
companion match review artifacts can be packaged into
`scout_mobile_energy_companion_handoff` through
`POST /admin/wearables/mobile-handoff` or `python -m scout_mobile_handoff build`.
The package is local-only, performs no network sync, carries no mobile runtime
authority, and cannot mutate Phase 1 safety state.

Implemented field cue scope: sanitized local wearable observations can be
combined with the personal baseline to produce deterministic
`scout_energy_field_advisory_cue` artifacts and local voice cues. This is a
fixture-backed contract, not live provider streaming.

Implemented stream-admission scope: local fixture-batch wearable stream
admission can dry-run sanitized observations into field cue artifacts while
rejecting network fetch, remote provider APIs, and runtime ingest.

Implemented live-frame fixture normalization scope: local Apple/Garmin
live-like frame fixtures can be normalized into sanitized
`scout_wearable_field_observation` artifacts for the existing stream-admission
dry-run path. Exact timestamps, token refs, raw frame/sample arrays, provider
payload fields, network calls, and runtime ingest remain excluded from output.

Implemented live provider transport preflight scope: account-authorized
Apple/Garmin live transport can be checked through a local
`scout_wearable_provider_live_transport_preflight` artifact before any real
transport is built. The preflight validates explicit consent, provider,
coarse scopes, token/account/device ref hashes, and requested capability flags,
while recording `network_request_performed=false`,
`real_provider_api_called=false`, and `runtime_ingest_performed=false`.
The same artifact can be created from the local admin wearable surface through
`POST /admin/wearables/provider-live-preflight`.

Implemented live provider request-plan scope: a validated preflight artifact can
be converted into a local
`scout_wearable_provider_live_transport_request_plan` artifact. The plan lists
provider-specific request descriptors for approved capabilities and a date-only
query window, but binds no executor, exposes no request body, commits no raw
response payload, and performs no network call or runtime ingest.
The same artifact can be created from the local admin wearable surface through
`POST /admin/wearables/provider-live-request-plan`.

Implemented live provider executor-registration scope: a validated preflight
artifact can register local executor metadata in a
`scout_wearable_provider_live_executor_registration` artifact. The artifact
stores only executor kind, supported capabilities, and an executor-ref sha256
digest. It does not load credentials, bind an executor to a request plan, open
network transport, call a provider API, or ingest runtime data.

Implemented live provider executor-readiness scope: a validated request-plan
artifact can be reviewed through a local
`scout_wearable_provider_live_executor_readiness` artifact. This is a gate for a
future live executor, not an executor itself. It confirms request-plan
prerequisites and records explicit blockers:
`live_provider_executor_not_registered` and
`network_execution_disabled_by_local_contract`, while preserving
`network_request_performed=false`, `real_provider_api_called=false`, and
`runtime_ingest_performed=false`.

Implemented live provider executor handoff-package scope: a request-plan
artifact plus executor-registration artifact can be bundled into a
`scout_wearable_provider_live_executor_handoff_package` artifact. This is the
local descriptor package a future real executor would consume, but it contains
only request descriptor hashes, coarse endpoint refs, query-window dates,
executor metadata digests, readiness blockers, and boundary flags. It includes
no credentials, request bodies, provider responses, network transport, or
runtime ingest.

Implemented live provider executor handoff outbox-index scope: a local
directory can be indexed for external-executor handoff packages. The index
verifies handoff safety plus request-plan and executor-registration sha256 refs,
marks eligible packages for future external executor pickup, and records
rejected JSON files without exposing credentials, request bodies, provider
responses, or opening network transport.

Implemented live provider executor handoff pickup-manifest scope: a local
outbox-index artifact can select one eligible handoff package and record a
pickup manifest for external executor review. The selected handoff file sha256
is rechecked, external execution remains unauthorized, and network execution
remains disabled by local contract.

Implemented live provider executor pickup-response-manifest scope: a local
pickup manifest plus a local response payload reference can write the existing
`scout_wearable_provider_live_executor_response_manifest` artifact with
pickup-manifest provenance. The response payload remains path-and-sha referenced
only; Scout still performs no provider call, network sync, remote upload, or
runtime ingest.

Implemented live provider executor pickup-response consumption scope: a local
pickup-bound executor response manifest can be consumed through the existing
sanitized response admission, materialization, sync-package, and Energy Reserve
artifact path while preserving pickup-manifest provenance. The pipeline rechecks
the pickup manifest path/hash and still performs no provider call, network sync,
remote upload, runtime ingest, or `/safety/*` mutation.

Implemented live provider executor pickup-response consumption receipt scope:
a local pickup-response consumption artifact can be recorded into a receipt
artifact that references local artifact paths and sha256 values only. The
receipt records the local endpoint status for the pickup lifecycle without
moving outbox/inbox files, uploading data, calling provider APIs, or promoting
Energy Reserve output into runtime safety truth.

Implemented live provider executor pickup-status snapshot scope: a local pickup
manifest plus optional response-manifest, pickup-consumption, and pickup-receipt
evidence can be summarized into a status snapshot (`awaiting_executor_response`,
`response_manifest_recorded`, `consumed_without_receipt`, or
`receipt_recorded`). The snapshot is local audit evidence only and does not
move files, upload data, call provider APIs, or promote Energy Reserve output
into runtime safety truth.

Implemented live provider executor lifecycle-audit scope: a local pickup-status
snapshot plus optional response-inbox status snapshot can be summarized into a
single audit artifact. The audit reports whether local pickup evidence and
local inbox evidence are complete, but it is still operator evidence only; it
does not execute providers, move files, upload data, or promote anything into
runtime safety truth.

Implemented live provider executor production-readiness gate scope: a local
lifecycle-audit artifact can be converted into a machine-checkable gate that
keeps `production_provider_execution_ready=false` and lists concrete blockers
for real Apple/Garmin execution. The gate is intentionally conservative: local
evidence completeness is not treated as live-provider authorization, and the
gate performs no credential loading, network call, remote upload, runtime
ingest, or `/safety/*` mutation.

Implemented live provider handoff fixture-replay scope: an executor handoff
package can be consumed by a local fixture replay after the package's
request-plan and executor-registration digests are checked against the current
local artifacts. This validates the future executor entry package without
credentials, request bodies, network transport, provider calls, or runtime
ingest.

Implemented live provider executor response-manifest scope: a local external
executor output can be represented as a response manifest that references a
response payload by path and sha256, ties it back to the validated handoff
package, and admits it into the sanitized-import path. This is a local contract
for future executor handoff output; it embeds no raw response and performs no
network request, provider API call, remote upload, or runtime ingest.

Implemented live provider executor response inbox scope: a local inbox
directory can be indexed for external-executor response manifest artifacts. The
index verifies manifest safety plus handoff and response-payload sha256 refs,
marks eligible manifests for later consumption, and records rejected JSON files
without embedding raw response payloads or opening network transport.

Implemented live provider executor response inbox consumption scope: a local
inbox-index artifact can select an eligible executor response manifest and
consume it through response admission, materialization, local sync-package
generation, and Energy Reserve artifact generation. The selected manifest file
sha256 is rechecked before consumption, and no network/provider/runtime path is
opened.

Implemented live provider executor response inbox batch-consumption scope: a
local inbox-index artifact can consume every eligible executor response manifest
into separate local output subdirectories and write one batch summary. Every
manifest file sha256 is rechecked before consumption, and the inbox itself is
not mutated, deleted, moved, uploaded, or synced.

Implemented live provider executor response inbox batch-receipt scope: a local
batch-consumption artifact can be recorded into a receipt artifact that
references the batch, inbox index, consumed manifest file hashes, per-manifest
consumption artifacts, and Energy Reserve output paths. It is local-only and
does not mutate, move, delete, upload, or sync inbox files.

Implemented live provider executor response inbox status-snapshot scope: a
local inbox index plus optional batch-consumption and receipt artifacts can be
summarized into manifest-level operator status (`eligible_pending`,
`consumed_without_receipt`, `receipt_recorded`, or `rejected_by_precheck`).
This is local evidence only, not runtime safety truth, and it does not mutate,
move, delete, upload, or sync inbox files.

Implemented live provider executor response consumption scope: a local executor
response manifest can be consumed end-to-end through response admission,
materialization, local sync-package generation, and Energy Reserve artifacts.
This is the Scout-side local drop/consume contract for a future external
executor; it does not fetch provider data, perform network sync, upload remote
state, or mutate runtime safety.

Implemented live provider executor fixture-replay scope: a registered local
executor metadata artifact plus a request-plan artifact can produce a
`scout_wearable_provider_live_executor_fixture_replay` artifact from a local
response fixture. This models the future executor output boundary before
admission, but references the fixture only by path and sha256, embeds no raw
response, and performs no network request, provider API call, remote upload, or
runtime ingest.

Implemented live provider replay-admission scope: an executor fixture-replay
artifact can be admitted into the existing sanitized-import path. This makes
the response-admission boundary consume the future executor output artifact
rather than a raw response fixture directly, while still checking fixture sha256
and preserving no network request, provider API call, remote upload, or runtime
ingest.

Implemented live provider executor-rehearsal scope: a registered local executor
metadata artifact plus a request-plan artifact can run a deterministic local
rehearsal from fixture replay through replay-admission, materialization,
sync-package, and Energy Reserve artifact generation. This proves the future executor
orchestration shape while still using only local fixtures and preserving
`network_request_performed=false`, `real_provider_api_called=false`,
`network_sync_performed=false`, and `runtime_ingest_performed=false`.

Implemented live provider response-admission scope: a local provider response
fixture can be admitted only through a validated request-plan artifact, then
sanitized by the existing provider API fixture importer. Admission writes
sanitized imports plus a `scout_wearable_provider_live_transport_response_admission`
artifact, while still performing no network call, live provider API call, or
runtime ingest.

Implemented live provider materialization scope: admitted sanitized imports can
be normalized into provider-neutral `WearableActivitySummary` artifacts through a
`scout_wearable_provider_live_transport_materialization` artifact. This closes
the local path from response admission to Energy Reserve inputs without binding
a live executor or performing runtime ingest.

Implemented live provider local sync-package scope: a materialization artifact
can be wrapped into a validated
`scout_wearable_provider_live_transport_sync_package` manifest. The package
contains only normalized summary references, validation summaries, source
digests, data-quality/privacy/boundary fields, and explicit
`network_sync_performed=false`, `remote_upload_allowed=false`,
`remote_upload_performed=false`, and `runtime_ingest_performed=false` flags.
It is a local handoff package for later account-authorized executor/sync work,
not a network transport or runtime ingest path.

Implemented provider sync-package to Energy Reserve scope: a local
`scout_wearable_provider_live_transport_sync_package` can now be consumed as the
handoff input for Energy Reserve, explanation, and companion capsule artifact
generation. This closes the local provider-to-reserve pipeline while preserving
the package boundary: no remote upload, network sync, live provider call,
runtime ingest, medical diagnosis, or Phase 1 safety truth.

Still deferred: actual live account-authorized Apple/Garmin provider API
requests and sync; production provider archive mapping beyond the local
manifest/multi-Garmin-JSON/FIT-member slice, real remote/community pool
service, broader production FIT coverage beyond the local minimal parser, live
wearable streaming, networked production consumer mobile app integration, and
any medical or Phase 1 safety interpretation.

This spec defines two related but separate capabilities:

- `Scout Energy Reserve`（Scout 體能儲備）: a personal, baseline-relative body
  battery proxy for daily training, post-analysis, and field advisory cues.
- `Scout Step Ease / Exertion Snapshot`（下一步輕鬆度 / 當下耗力快照）:
  a short-window field signal that asks whether the next step is becoming harder
  than expected for this person, route segment, and environment.
- `Scout Composure Reserve`（冷靜行動儲備）: a non-medical decision-margin proxy
  that combines physical load, navigation uncertainty, environment pressure, and
  plan-node drift before panic or poor decisions have a chance to compound.
- `Companion Capability Match`（同行能力匹配）: an opt-in matching score that helps
  users find hiking partners with similar route rhythm, endurance, rest habits,
  and body-load profile.

The full product loop is defined in
`docs/specs/scout-closed-loop-operating-cycle.md`. This spec owns the energy and
capability feedback portion of that loop: wearable/activity baseline,
Capability Timeline consumption, post-analysis Energy Reserve / Energy Limit
feedback, and candidate-only influence on future pretrip CP/rest/check-in
suggestions.

The feature is not a medical product, not a diagnosis engine, and not Phase 1
runtime safety truth. It uses wearable and route evidence to support awareness,
planning, and partner matching.

## Objective

Scout should help users understand and compare outdoor endurance in the same
practical spirit as Sunriver-style route-time comparison（上河時間比值）, but
without depending on guidebook times that only exist for a subset of major
routes.

The core product idea:

```text
historical wearable activity
  + completed Scout routes
  + Capability Timeline moving/rest/elapsed time
  + route effort normalization
  -> personal energy and endurance baseline
  -> on-trip step-ease and composure snapshots
  -> privacy-preserving companion match score
  -> advisory field rest cues
```

Success means a user can:

- import Apple Watch, Garmin, GPX/FIT/TCX, or Scout runtime activity history;
- build a personal baseline from their own routes and daily training;
- compare new route performance against their own baseline and route effort;
- see short-window exertion and decision-margin cues when the next step becomes
  harder than expected;
- share a coarse capability profile without raw GPX or exact timestamps;
- find companion candidates with similar walking, climbing, descending, rest,
  and fatigue-decay patterns;
- identify group pace pressure when a stronger companion rhythm pushes the user
  above sustainable effort and creates later rest-cost delay;
- receive field rest cues when live wearable signals drift below personal
  baseline expectations.

## Product Rationale

Taiwan hikers often compare themselves with Sunriver-style guide times because
the published time is a common reference. A simple ratio such as `1.2x guide
time` is useful socially: people can find hiking partners with similar pacing
and reduce team-safety friction from mismatched ability.

The gap is that many small mountains, day hikes, local trails, and casual routes
do not have published Sunriver-style timing. These routes are the largest daily
use case for Scout. Scout can fill the gap by deriving comparable route-effort
baselines and personal capability profiles from completed tracks.

This creates daily-use retention:

- after every walk, hike, run, or climb, Scout updates the baseline;
- before a trip, Scout can show whether the plan exceeds recent baseline;
- after a trip, Scout explains where fatigue appeared;
- when joining others, users can compare coarse capability without exposing raw
  private traces.

Companion mismatch can also appear during a trip. If the user is trying to
follow companions with clearly higher capability, Scout should treat the cause
as `companion_pace_pressure`, not as a personal failure or diagnosis. A window
with high heart-rate pressure and collapsed movement efficiency can become a
rest cue; if the user keeps moving because of group pressure and later needs
large rests, Scout should hand evidence to companion match, pace, and delay
composition.
The runtime evidence artifact for this first detector is
`scout_companion_pace_pressure_evidence`. The first runtime composer that joins
this evidence with physiologic rest directives and pace/delay handoff is
`scout_route_pressure_composer_result`.
Walking and hiking runtime baselines should use
`scout_walking_hiking_baseline` so companion comparison does not silently reuse
running-oriented cardio baselines for field pacing.

The field-use rationale is sharper than general wellness: many accidents open a
window when the next step becomes difficult and the user starts losing calm
judgment. The cause can be physical fatigue, route confusion, poor weather,
fading daylight, team separation, or simple under-preparation. Scout should
therefore model not only body reserve over days, but also the immediate
"can I still take the next step calmly?" margin.

## Theory Foundation

### 1. Route-Time Ratio As A Social Heuristic

Sunriver-style route-time comparison works because it reduces a complex route
to a shared reference time. Scout should preserve the social value but avoid
treating guide time as objective truth.

Scout replacement:

```text
Scout Capability Ratio
  = user moving time / Scout route-effort baseline time
```

When a guide time exists, Scout may also show:

```text
Guide Time Ratio
  = user moving time / guidebook or manually entered reference time
```

Both ratios are context signals. They are not safety guarantees.

### 2. External Load: Route Effort

Route difficulty must be normalized before comparing two different hikes.
Distance alone is insufficient. The first route-effort model should combine:

- distance;
- ascent and descent;
- slope distribution;
- altitude band;
- terrain/risk layer;
- surface or trail class when available;
- stop/rest-adjusted moving time from post-analysis.

Naismith-style rules and Tobler-style hiking functions support the idea that
grade and ascent materially affect expected walking speed. Newer data-driven
hiking-speed work shows that slope-based formulas remain useful baselines but
need calibration to observed tracks and local conditions.

Scout should therefore treat route-effort baseline as a configurable model:

```text
route_effort_units =
  distance_weight * horizontal_distance
  + ascent_weight * ascent_m
  + descent_weight * descent_m
  + slope_cost(slope_distribution)
  + terrain_cost(terrain_class, risk_bucket)
```

The exact weights are not universal. They should be versioned, fixture-backed,
and later personalized from completed Scout tracks.

### 3. Internal Load: Heart Rate, Duration, RPE

Wearable heart rate can support internal load estimates, but Scout must treat
consumer devices as noisy context rather than medical-grade measurement.

Training load concepts useful to Scout:

- TRIMP（Training Impulse）combines duration with heart-rate reserve or heart
  rate intensity weighting.
- session-RPE（自覺用力程度）uses duration times a user-rated effort score and
  remains useful when heart-rate data is missing or unreliable.
- heart-rate drift can indicate that the same pace/grade is costing more
  internal effort later in the activity.

Scout first slice should support:

```text
internal_load_estimate =
  duration_component
  + heart_rate_zone_minutes
  + optional_trimp_like_score
  + optional_session_rpe_score
```

The output must include data-quality flags, device source, missingness, and
confidence.

### 4. Recovery And Readiness: HRV, Sleep, Stress, Activity

Garmin Body Battery-like products combine activity, stress, sleep, HRV, and
movement into a proprietary 0-100 reserve number. Scout should not copy or
reverse-engineer that algorithm.

Scout should instead model a transparent proxy:

```text
Scout Energy Reserve Proxy
  = personal baseline
  - recent load deviation
  - recovery debt
  - live exertion drift
  + recent recovery evidence
```

Inputs can include:

- resting heart rate trend;
- HRV trend when available;
- sleep duration/quality when imported;
- activity load in the last 7/28/90 days;
- body battery or stress values if a device already exposes them;
- completed-route fatigue decay;
- manual user check-in.

The important rule is baseline-relative comparison:

```text
today against this user's normal range
this route segment against this user's historical route-effort profile
this live climb against this user's expected fatigue curve
```

### 5. Step Ease And Composure Load

Long-term body reserve may take weeks or months to personalize. Field usefulness
requires a faster signal. Scout should model a short-window `Step Ease` score
from the current trip, using the first stable minutes of a route and reviewed
pretrip expectations as temporary baselines when personal history is sparse.

Step Ease asks:

```text
Is the next step becoming harder than expected right now?
```

It should compare expected effort for the segment against observed effort:

```text
observed_exertion_now =
  heart_rate_drift
  + pace_decay_for_same_grade
  + cadence_decay
  + micro_stop_frequency
  + movement_instability

expected_segment_effort =
  route_grade
  + ascent/descent
  + terrain/risk context
  + planned pace/rest envelope
  + weather/daylight pressure
```

Scout should then derive a decision-margin cue:

```text
Composure Load =
  physical_load
  + navigation_load
  + environmental_load
  + decision_load
```

Where:

- `physical_load` covers heart-rate drift, pace decay, cadence decay, late-route
  fatigue, and rest debt;
- `navigation_load` covers route deviation, repeated backtracking, low map/GPS
  confidence, and unresolved next-CP ambiguity;
- `environmental_load` covers daylight loss, weather degradation, temperature,
  terrain exposure, and communication weakness;
- `decision_load` covers missed plan-node check-ins, ETA drift, team separation,
  manual discomfort check-ins, and repeated hesitation.

This is not a panic detector. Scout must avoid diagnosing emotion. The goal is
to surface a calm action cue before the user enters a fragile decision state:

```text
Stop briefly. Confirm current position, next checkpoint, daylight, weather, and
retreat options before continuing.
```

### 6. Wearable Data Accuracy Limits

Consumer wearable data is useful for trends, but device error varies by metric,
movement pattern, skin contact, sensor generation, physiology, and activity
type. Heart rate is generally more usable than energy expenditure or sleep-stage
classification, but even heart rate should carry uncertainty.

Scout must:

- keep raw wearable data source refs;
- avoid medical diagnosis;
- never issue a hard safety decision from a wearable value alone;
- downgrade confidence when device data is sparse, stale, or inconsistent;
- let users override or annotate how they felt.

### 7. Companion Matching As Similarity, Not Ranking

Companion matching should compare normalized capability vectors, not total
finish time. Two users can be compatible even if they have never walked the same
route.

Example vector:

```json
{
  "route_effort_adjusted_moving_pace": 1.08,
  "ascent_endurance_index": 0.92,
  "descent_conservatism_index": 1.21,
  "rest_frequency_per_hour": 0.44,
  "median_rest_duration_min": 8.5,
  "late_activity_fatigue_decay": 0.18,
  "heart_rate_load_per_effort_unit": 1.11,
  "recovery_next_day_delta": 0.74
}
```

The first matching score can use weighted normalized distance:

```text
distance = sqrt(sum(weight_i * confidence_i * (feature_i_a - feature_i_b)^2))
match_score = round(100 * exp(-distance))
```

The score should be presented as "rhythm similarity" or "route compatibility",
not as "better/worse fitness".

## Relationship To Existing Specs

- `docs/specs/post-analysis-capability-timeline.md` owns completed-route moving
  time, elapsed time, rest time, and share capsule outputs. This spec consumes
  those outputs.
- `docs/specs/pre-trip-planning-admin.md` owns future route planning and review.
  Companion match outputs may seed pretrip pacing assumptions only after human
  review.
- `docs/specs/phase-4-5-departure-runtime-handoff.md` owns departure gate and
  runtime handoff. Body/energy cues do not approve departure.
- `docs/specs/scout-voice-cue-layer.md` owns local voice cue delivery. Field
  fatigue cues reuse that boundary.
- `docs/specs/phase-4-6-real-device-continuous-stream.md` owns real mobile or
  Apple Watch stream admission when live wearable data is used.

## Phase Boundary

### Daily And Post-Analysis Boundary

Daily activity and completed route data can update baseline artifacts:

```text
wearable import
  + completed user track
  + post-analysis capability timeline
  -> normalized activity history
  -> personal baseline profile
  -> energy reserve trend
  -> energy limit candidate
  -> companion capability vector
```

These artifacts are user-private by default.

### Capability Timeline To Energy Reserve Feedback Loop

`docs/specs/post-analysis-capability-timeline.md` produces completed-trip
moving/rest/elapsed evidence from a user recorded GPX or Scout runtime track.
Energy Reserve consumes that evidence after the trip is closed; it does not
consume pretrip reference GPX or public route downloads as capability evidence.

The intended flow is:

```text
completed trip workspace
  -> user recorded GPX / Scout runtime track
  -> Capability Timeline
  -> post_analysis_energy_reserve_feedback
  -> updated personal endurance baseline candidate
  -> energy limit candidate
  -> next pretrip energy reserve projection
  -> proposed energy-aware CP/rest/check-in candidates
  -> human/AI review
```

The Energy Reserve update should compare each completed route against the user's
baseline, route-effort profile, and available wearable summaries:

- actual moving time vs. expected moving time;
- actual rest frequency/duration vs. expected rest pattern;
- late-route fatigue decay;
- ascent/descent load per moving hour;
- wearable load and recovery context when available;
- data-quality limits from GPS gaps, IMU/PDR gaps, sparse wearable data, or
  missing user check-ins.

Outputs remain local post-analysis evidence:

- `post_analysis_energy_reserve_feedback`: explains whether the previous
  projection over/under-estimated fatigue and where reserve dropped.
- `scout_energy_reserve_baseline_update_candidate`: proposes baseline updates
  from completed trip evidence, with confidence and limitations.
- `scout_energy_limit_candidate`: proposes conservative planning constraints
  such as shorter segment targets, earlier turnaround gates, denser rest/check
  nodes, or larger ETA/rest buffers for the next pretrip workspace.
- `pretrip_energy_reserve_projection`: reads the updated baseline candidate only
  after review or explicit local acceptance.
- `energy_aware_cp_adjustment_candidates`: optional next-trip planning
  candidates for rest/check-in CPs, turnaround gates, camp/water emphasis, or
  CP-density changes.

Energy-aware CP adjustments are not checkpoint truth. They may influence the
next pretrip proposed CP set, but only as candidate evidence with source refs to
Capability Timeline and Energy Reserve artifacts. They must not directly mutate
the reviewed MissionGraph, mark checkpoints reached, or become Phase 1 runtime
safety truth.

### Pretrip Boundary

Pretrip can read a coarse baseline:

```text
capability vector
  + Energy Reserve baseline/projection
  -> route feasibility context
  -> pacing recommendation
  -> energy-aware CP/rest/check-in candidates
  -> companion compatibility
  -> human review
```

It must not automatically reject a route, approve a team, or insert CPs into a
departure package without review.

### Runtime Boundary

Runtime can read live wearable signals for advisory cues:

```text
live wearable observation
  + current route-effort segment
  + personal baseline
  + navigation/environment/plan-node context
  -> exertion snapshot
  -> composure snapshot
  -> advisory fatigue or decision-margin cue
  -> voice/UI suggestion
```

It must not:

- call `/safety/*`;
- mutate L0-L4 safety state;
- mark a checkpoint reached;
- alter MissionGraph progress;
- trigger SOS or outbound messages without explicit operator/SOS flow.

When composure margin degrades, the default runtime cue should be conservative
and action-oriented, not alarming:

```text
Pause. Check where you are, confirm the next checkpoint, and decide whether to
continue, rest, or retreat.
```

## Core Concepts

### Scout Energy Reserve（Scout 體能儲備）

A transparent, Scout-owned body battery proxy. It is a trend score, not a
clinical measurement.

Key properties:

- user-relative;
- device-source aware;
- confidence-scored;
- explainable;
- reversible from source refs;
- never treated as medical advice.

Suggested output bands:

| Band | Meaning | Product behavior |
| --- | --- | --- |
| `normal` | within user's recent baseline | no alert |
| `watch` | mildly below baseline or load rising | quiet advisory |
| `rest_suggested` | sustained drift below expected range | suggest rest/slowdown |
| `stop_and_check` | large deviation plus user discomfort or multiple weak signals | ask user to check condition |

`stop_and_check` is still not Phase 1 safety truth.

### Scout Step Ease（下一步輕鬆度）

A short-window exertion signal for on-trip use. Step Ease is designed for cold
start and sparse-history situations where a complete Energy Reserve baseline does
not yet exist.

Suggested output:

| Band | Meaning | Product behavior |
| --- | --- | --- |
| `easy` | next step remains easier than expected | no cue |
| `normal` | effort is within the expected envelope | quiet status only |
| `strained` | effort is rising for the same route context | suggest slower pace |
| `rest_suggested` | sustained effort drift or repeated micro-stops | suggest rest |
| `manual_check` | high effort drift plus weak context signals | ask for self check |

Inputs may include:

- heart-rate drift for similar grade/pace;
- pace decay under similar slope;
- cadence or step-length decay when available;
- micro-stop frequency;
- movement instability from IMU/PDR when available;
- terrain and weather context;
- user-reported RPE or discomfort.

Step Ease must be computed from a short window, preserve data-quality notes, and
never become a checkpoint arrival or safety truth signal.

### Scout Composure Reserve（冷靜行動儲備）

A non-medical decision-margin proxy. Composure Reserve explains why the user may
need to pause before continuing, even when no single health value is extreme.

Suggested output bands:

| Band | Meaning | Product behavior |
| --- | --- | --- |
| `steady` | decision margin is intact | no cue |
| `watch` | one load source is rising | keep next CP and retreat option visible |
| `fragile` | multiple load sources are rising | pause-and-verify cue |
| `stop_and_plan` | physical/navigation/environment pressure is compounded | require manual acknowledgement |

It should combine:

- Step Ease / physical load;
- navigation uncertainty;
- weather and daylight pressure;
- plan-node and ETA drift;
- communication weakness;
- team-care context when available.

Composure Reserve is not a panic detector, diagnosis, or automatic SOS trigger.
It exists to preserve calm action before poor decisions compound.

### Personal Endurance Baseline（個人耐受基線）

A rolling profile from historical routes and wearable activity. It should be
time-windowed:

- 7-day acute load;
- 28-day recent baseline;
- 90-day stable baseline;
- route-family-specific baseline when enough data exists.

Alpha policy:

- route-family profiles are local-only baseline context;
- first supported route families are deterministic coarse buckets such as
  `local_walk`, `light_outdoor_activity`, `local_day_hike`, and
  `mountain_hike`;
- a route-family profile is emitted only when at least two local activities fit
  that family;
- route-family names are not shared publicly without explicit consent.

### Route-Effort Baseline（路線耗能基準）

The estimated effort of a route or segment independent of a specific user's
fitness. First implementation can be deterministic. Later versions can be
calibrated from anonymized or user-local history.

### Capability Vector（能力向量）

A privacy-preserving feature vector derived from completed routes and wearable
history. It is the unit used for companion matching.

### Companion Capability Match（同行能力匹配）

An opt-in comparison between two coarse capability vectors. It returns:

- score;
- explanation;
- compatible route types;
- mismatch warnings;
- confidence and missing-data notes.

It should not expose raw route history by default.

## Data Sources

### Supported User Device Scenarios

Scout must not make specialized hardware or Apple/Garmin ownership a prerequisite
for trying the product. The Energy Reserve, Step Ease, and Composure Reserve path
must support three entry scenarios:

1. `scout_ecosystem_device`
   - The user wears or carries hardware/software that can run Scout-compatible
     capture or bridge software.
   - Expected data: live or near-live wearable observations, route progress,
     PDR/IMU/GPS, plan-node check-ins, and optional user check-ins.
   - Product value: strongest on-trip Step Ease and Composure Reserve support.

2. `compatible_wearable_or_app_bridge`
   - The user uses Apple Watch, Garmin, Strava, Nike Run Club, or another device
     or app that can expose activity data through HealthKit, Garmin exports,
     FIT/TCX/GPX, or a Scout bridge.
   - Expected data: workouts, heart-rate summaries, distance, elevation, routes,
     effort/RPE where available, and historical activity windows.
   - Product value: strong Energy Reserve baseline and post-analysis calibration;
     on-trip usefulness depends on whether live bridge data is available.

3. `gpx_only_device`
   - The user has a non-Scout-compatible device, app, or public/history source
     that can produce GPX only.
   - Expected data: completed route geometry, timestamps when available, moving
     time, pause/rest evidence, and DEM/risk-derived terrain context.
   - Product value: cold-start terrain-time baseline, Capability Timeline, and
     next-pretrip energy-aware candidates without a wearable dependency.

GPX-only users should still receive useful Scout planning and post-analysis
feedback. Wearable data improves confidence; it must not become an adoption gate.

### Historical Import

Supported input categories:

- Apple HealthKit workout and heart-rate exports;
- Garmin Connect export or Garmin Health API where available;
- FIT/TCX/GPX files;
- Scout completed route and Capability Timeline artifacts;
- manual self-rated exertion and fatigue check-ins.

Alpha adapter boundary: raw provider files are not committed.
`scout_wearable_adapters.py` accepts sanitized summary envelopes or
file-derived summary envelopes and writes only provider-neutral activity
summaries.

Alpha raw-file boundary: `scout_wearable_raw_importers.py` can summarize local
Apple Health export XML and Garmin Connect JSON exports as single activities or
as deterministic local batches, can discover provider export files inside local
directories/zips, and can summarize GPX/FIT/TCX files into sanitized envelopes.
The raw source is never embedded in outputs or extracted into the workspace.
Exact timestamps are used only transiently to derive `activity_date`, relative
duration, and heart-rate summary windows. Garmin Body Battery and stress values
remain provider source values only.

### Two Apple Ingestion Modes

Scout should support both Apple activity data paths, but they have different
product roles:

1. `manual_apple_health_export_importer`
   - Role: development tool, lab tool, and one-time historical import path.
   - Input: user-provided Apple Health export archive, workout route files, or
     locally extracted HealthKit-style summaries.
   - Use case: bootstrap early baselines, validate parsers, reproduce field
     cases, and support users who want offline/manual data ownership.
   - Boundary: no background sync, no Apple account binding, no runtime coupling,
     no raw Health export content embedded in Scout artifacts.

2. `scout_ios_healthkit_bridge`
   - Role: Scout ecosystem component.
   - Input: HealthKit data read through a Scout iOS companion app after explicit
     user authorization.
   - Use case: ongoing daily/training activity sync, completed workout ingestion,
     workout route handoff, Step Ease calibration, and Energy Reserve baseline
     updates.
   - Boundary: user-consented, least-scope HealthKit reads; summarized payloads
     only; no Scout hardware direct pull from Apple cloud; no provider-derived
     value is promoted into Scout truth without review/provenance.

The manual importer is acceptable for alpha development and operator review. The
HealthKit bridge is the product path for the Scout ecosystem and should be
designed as a first-class companion-app integration rather than as a parser-only
utility.

### Live Field Input

Potential live inputs:

- heart rate;
- HRV only if device and API support reliable near-real-time access;
- pace/speed;
- cadence, step length, or pedometer deltas when available;
- movement/stopped state;
- route progress;
- altitude trend;
- route deviation and next-checkpoint ambiguity;
- weather, daylight, and communication-pressure context;
- user check-in;
- device-provided stress/body battery if available.

Live stream is optional for the first alpha. The first slice can be import-only.

### Data Quality Metadata

Every record should preserve:

- provider;
- device model if known;
- sample cadence;
- timestamp coverage;
- missing interval summary;
- sensor quality flags when available;
- import path and sha256;
- privacy scope.

## Data Model

### Activity Summary

The implemented alpha fixture contract uses `activity_date` instead of exact
`started_at` timestamps so committed fixtures and shared artifacts do not expose
precise private timelines.

```json
{
  "artifact_kind": "scout_wearable_activity_summary",
  "artifact_version": "wearable_activity_summary.v1",
  "source_provider": "apple_health_export",
  "source_path": "imports/apple_health/workout_2026_05_01.json",
  "sha256": "...",
  "activity_type": "hiking",
  "activity_date": "2026-05-01",
  "duration_s": 21600,
  "moving_time_s": 18000,
  "distance_m": 12200,
  "ascent_m": 980,
  "heart_rate": {
    "sample_count": 2100,
    "avg_bpm": 132,
    "p90_bpm": 158,
    "zone_minutes": {
      "z1": 42,
      "z2": 110,
      "z3": 96,
      "z4": 28,
      "z5": 0
    }
  },
  "body_energy_provider_values": {
    "garmin_body_battery_start": null,
    "garmin_body_battery_end": null,
    "stress_avg": null
  },
  "data_quality": {
    "heart_rate_confidence": "medium",
    "gps_confidence": "medium",
    "missing_hr_seconds": 420
  },
  "boundary": {
    "medical_diagnosis": false,
    "phase1_runtime_safety_truth": false
  }
}
```

### Energy Baseline Profile

```json
{
  "artifact_kind": "scout_energy_reserve_baseline",
  "artifact_version": "energy_reserve_baseline.v1",
  "user_profile_ref": "local_user.private",
  "baseline_window_days": 90,
  "acute_window_days": 7,
  "activity_count": 38,
  "route_family_profiles": [
    {
      "route_family": "local_day_hike",
      "activity_count": 12,
      "route_effort_units_p50": 120.5,
      "moving_time_per_effort_p50": 1.08,
      "heart_rate_load_per_effort_p50": 0.94,
      "late_activity_fatigue_decay_p50": 0.12,
      "confidence": "medium"
    }
  ],
  "reserve_trend": {
    "current_band": "normal",
    "acute_load_z": 0.4,
    "recovery_debt_z": 0.2,
    "confidence": "medium"
  },
  "privacy": {
    "local_only": true,
    "raw_samples_embedded": false,
    "shareable_by_default": false
  },
  "boundary": {
    "advisory_only": true,
    "medical_diagnosis": false,
    "phase1_runtime_safety_truth": false
  }
}
```

### Exertion And Composure Snapshot

`scout_exertion_snapshot` and `scout_composure_snapshot` are short-window field
artifacts. They may be generated from live stream observations, local replay, or
post-analysis reconstruction. They are advisory context only.

```json
{
  "artifact_kind": "scout_exertion_snapshot",
  "artifact_version": "exertion_snapshot.v1",
  "source_provider": "apple_watch_sensorlog+pretrip_route_context",
  "source_path": "runtime/observations/window_0042+outputs/final_mission_graph.json",
  "sha256": "...",
  "route_segment_ref": "segment_040",
  "window": {
    "duration_s": 300,
    "relative_start_s": 2400,
    "relative_end_s": 2700
  },
  "step_ease_score": 58,
  "step_ease_band": "strained",
  "observed": {
    "heart_rate_bpm_p50": 142,
    "pace_m_per_min": 38.0,
    "cadence_spm": 92,
    "micro_stop_count": 3
  },
  "expected": {
    "heart_rate_bpm_p50": 132,
    "pace_m_per_min": 43.0,
    "segment_effort_band": "uphill_moderate"
  },
  "exertion_factors": {
    "heart_rate_drift_ratio": 0.076,
    "pace_decay_ratio": 0.116,
    "cadence_decay_ratio": 0.05,
    "micro_stop_penalty": 0.12
  },
  "data_quality": {
    "heart_rate_confidence": "medium",
    "gps_confidence": "medium",
    "limitations": [
      "short-window advisory context only"
    ]
  },
  "boundary": {
    "advisory_only": true,
    "medical_diagnosis": false,
    "phase1_runtime_safety_truth": false,
    "safety_api_calls_allowed": false
  }
}
```

```json
{
  "artifact_kind": "scout_composure_snapshot",
  "artifact_version": "composure_snapshot.v1",
  "source_provider": "exertion_snapshot+route_progress+environment_context",
  "source_path": "outputs/exertion/window_0042.json+runtime/debug_state.json",
  "sha256": "...",
  "route_segment_ref": "segment_040",
  "decision_margin_band": "fragile",
  "step_ease_score": 58,
  "loads": {
    "physical_load": "strained",
    "navigation_load": "watch",
    "environmental_load": "watch",
    "decision_load": "fragile"
  },
  "recommended_action": "pause_verify_next_checkpoint_and_retreat_options",
  "cue_text_zh": "先停下來，確認目前位置、下一個檢查點、剩餘日照與撤退選項，再決定是否繼續。",
  "boundary": {
    "advisory_only": true,
    "medical_diagnosis": false,
    "panic_detection": false,
    "phase1_runtime_safety_truth": false,
    "safety_api_calls_allowed": false,
    "outbound_message_allowed": false
  }
}
```

### Companion Match Capsule

```json
{
  "artifact_kind": "scout_companion_capability_capsule",
  "artifact_version": "companion_capability_capsule.v1",
  "owner_display_name": "user-private-alias",
  "source_scope": "coarse_completed_route_summary",
  "raw_track_shared": false,
  "exact_timestamps_shared": false,
  "capability_vector": {
    "route_effort_adjusted_moving_pace": 1.08,
    "ascent_endurance_index": 0.92,
    "descent_conservatism_index": 1.21,
    "rest_frequency_per_hour": 0.44,
    "median_rest_duration_min": 8.5,
    "late_activity_fatigue_decay": 0.18,
    "heart_rate_load_per_effort_unit": 1.11
  },
  "confidence": "medium",
  "limitations": [
    "only three mountain activities in the last 90 days",
    "heart rate source is wrist optical sensor"
  ]
}
```

### Match Result

```json
{
  "artifact_kind": "scout_companion_match_result",
  "artifact_version": "companion_match.v1",
  "query_profile_ref": "local_user.private",
  "candidate_profile_ref": "shared_capsule.abc123",
  "match_score": 84,
  "match_band": "similar_rhythm",
  "explanations": [
    "similar ascent endurance",
    "candidate rests less often but for similar duration",
    "both show conservative descent pace"
  ],
  "mismatch_notes": [
    "candidate has limited multi-day recovery history"
  ],
  "boundary": {
    "safety_guarantee": false,
    "medical_diagnosis": false,
    "requires_user_consent": true
  }
}
```

## Scoring Model

### Scout Energy Reserve Proxy

First-slice transparent formula:

```text
reserve_delta =
  - acute_load_z * w_acute_load
  - recovery_debt_z * w_recovery_debt
  - live_hr_drift_z * w_hr_drift
  - fatigue_decay_z * w_decay
  + recovery_signal_z * w_recovery

reserve_score = clamp(50 + reserve_delta * 10, 0, 100)
```

Output should prefer band and explanation over a false-precise number.

Cold-start policy:

```text
if personal_baseline_history is sparse:
  reserve_score = scout_default_prior_score
  confidence = very_low or low
  baseline_source = scout_default_prior
  update_rate = high initially, then decays as personal evidence accumulates
```

The default prior exists so the product can give conservative planning cues from
day one. It must be labeled as a prior, not as a learned truth.

### Terrain-Time Fitness Proxy

When wearable baseline data is missing, Scout should still estimate a useful
outdoor capability baseline from completed GPX, DEM/DTM, risk score, and
Capability Timeline evidence.

Development assumption:

```text
For hiking support, early physical consumption can be approximated from:
  terrain demand + distance + route risk
compared against:
  observed moving/elapsed time
```

This proxy should split completed tracks into fixed route windows, initially
`100m`:

```text
terrain_time_window:
  distance_2d_m
  ascent_m
  descent_m
  risk_score_mean
  risk_score_p95
  moving_time_s
  elapsed_time_s
  rest_or_pause_s
```

TTM should also carry a daylight constraint. Mountain capability is not only a
terrain/time ratio; the same segment becomes operationally harder when usable
daylight is short. Scout should support two deterministic sampling modes:

```text
daily_daylight_window:
  use actual trip date + route location/timezone
  sample from local sunrise to local sunset

seasonal_daylight_profiles:
  use representative seasonal or monthly daylight windows
  use the shortest relevant daylight profile for conservative pretrip warnings
```

If the trip date is known, prefer the daily sunrise/sunset window. If the trip
date is unknown, sample four seasonal profiles or monthly profiles for the route
location. This is a planning and post-analysis evidence constraint; it must not
be promoted to Phase 1 runtime safety truth.

```text
daylight_window:
  mode: daily_sunrise_sunset | seasonal_profiles
  timezone
  sunrise_local
  sunset_local
  daylight_duration_min
  usable_daylight_margin_min
  sample_basis: trip_date | season | month
```

Flat-window rule:

```text
if ascent_m < 5 and descent_m < 5 within a 100m window:
  treat the window as 2D distance/time evidence
else:
  treat the window as terrain-load evidence
```

Terrain-load evidence:

```text
terrain_load =
  distance_2d_m
  + up_weight * ascent_m
  + down_weight * descent_m
  + risk_weight * risk_score
```

Useful derived envelopes:

```text
uphill_sustainable_envelope =
  ascent_m per 100m window per time bucket

descent_sustainable_envelope =
  descent_m per 100m window per time bucket

terrain_time_ratio =
  observed_moving_time_s / expected_flat_window_time_s

daylight_constrained_time_budget =
  usable_daylight_minutes - planned_elapsed_minutes - required_margin_minutes

daylight_pressure_penalty =
  clamp(required_elapsed_minutes - usable_daylight_minutes, 0, max_penalty)
```

Examples:

```text
100m distance with 20m ascent per unit time
  -> candidate uphill sustainable limit

100m distance with 50m descent per unit time
  -> candidate descent-control sustainable limit
```

Daylight examples:

```text
same terrain_load in summer daylight
  -> normal terrain-time pressure

same terrain_load in winter daylight with a late start
  -> higher daylight pressure and earlier rest/turnaround CP recommendation
```

The product should avoid presenting this as a hard "maximum limit" from a small
sample. Use language such as `sustainable terrain envelope`, `watch threshold`,
or `strained terrain band`.

This proxy is especially important for `gpx_only_device` users. It gives Scout a
way to produce first-pass Energy Limit, Step Ease expectations, rest/check-in CP
candidates, and next-pretrip pacing advice without requiring any wearable.

Suggested artifact:

```json
{
  "artifact_kind": "scout_terrain_time_fitness_proxy",
  "artifact_version": "terrain_time_fitness_proxy.v1",
  "source_provider": "completed_gpx+dem+risk_score+capability_timeline",
  "window_m": 100,
  "flat_window_threshold_m": 5,
  "daylight_constraint": {
    "enabled": true,
    "mode": "daily_sunrise_sunset",
    "sample_basis": "trip_date",
    "timezone": "Asia/Taipei",
    "sunrise_local": "2026-05-12T05:12:00+08:00",
    "sunset_local": "2026-05-12T18:32:00+08:00",
    "usable_daylight_minutes": 740,
    "required_daylight_margin_minutes": 45,
    "seasonal_profiles": []
  },
  "flat_pace_baseline_s_per_100m": 92,
  "uphill_envelope": {
    "watch_ascent_m_per_100m": 12,
    "strained_ascent_m_per_100m": 20
  },
  "descent_envelope": {
    "watch_descent_m_per_100m": 30,
    "strained_descent_m_per_100m": 50
  },
  "risk_adjusted_time_multiplier": 1.18,
  "daylight_adjusted_time_pressure": {
    "band": "watch",
    "remaining_daylight_margin_minutes": 62,
    "turnaround_cp_recommendation_allowed": true
  },
  "confidence": "low",
  "boundary": {
    "advisory_only": true,
    "medical_diagnosis": false,
    "phase1_runtime_safety_truth": false
  }
}
```

### Scout Step Ease / Exertion Score

First-slice transparent formula:

```text
step_ease_score = clamp(
  100
  - hr_drift_penalty
  - pace_decay_penalty
  - cadence_decay_penalty
  - micro_stop_penalty
  - movement_instability_penalty
  - route_context_pressure_penalty,
  0,
  100
)
```

The short-window expected baseline may come from, in priority order:

1. route-family personal baseline for similar grade and effort;
2. earlier stable windows from the same trip;
3. `scout_terrain_time_fitness_proxy` from completed GPX/DEM/risk evidence;
4. reviewed pretrip route-effort expectation;
5. Scout default prior with low confidence.

`Step Ease` should be easier to compute than full Energy Reserve. It is the
alpha field signal for whether the next step is still easy, normal, strained, or
requires a pause.

### Scout Composure Reserve Score

First-slice transparent formula:

```text
composure_load =
  physical_load_weight * physical_load
  + navigation_load_weight * navigation_load
  + environmental_load_weight * environmental_load
  + decision_load_weight * decision_load

composure_score = clamp(100 - composure_load, 0, 100)
```

The output should prioritize band and recommended action over a false-precise
number. A low score does not diagnose panic; it means Scout should help the user
pause, verify facts, and make the next decision calmly.

### Route-Effort-Adjusted Capability

```text
effort_adjusted_moving_pace =
  moving_time_s / route_effort_units
```

Lower is faster for a given route effort. Present it as a ratio against the
user's own baseline or peer capsule median, not as a moral ranking.

### Fatigue Decay

For long routes, split by route progress:

```text
early_effort_pace = moving_time_first_40_percent / effort_first_40_percent
late_effort_pace = moving_time_last_40_percent / effort_last_40_percent
fatigue_decay = late_effort_pace / early_effort_pace - 1
```

Positive values mean the user slowed relative to effort. This is often more
useful than total speed for matching companions.

### Match Score

```text
feature_distance =
  sqrt(sum(weight_i * confidence_i * robust_delta_i^2))

match_score =
  round(100 * exp(-feature_distance))
```

Weights should be route-type aware. For example, ascent endurance matters more
for high-ascent routes; descent conservatism matters more for steep return
routes; rest rhythm matters more for group trips.

Match score is not only "who is faster." Scout should preserve asymmetric risk:
walking with much stronger companions can pressure the weaker member into
over-output, while walking with a much slower group can create delay or
darkness pressure. The first runtime handoff for this is
`external_pressure_flags=["companion_pace_pressure"]`, which routes the evidence
to `companion_match_gate`, `pace_gate`, and `delay_gate`.

## UI Requirements

### Daily / Home Surface

Show:

- current reserve band;
- trend vs 7/28/90-day baseline;
- recent load and recovery explanation;
- next suggested easy/rest/training day as a soft cue;
- no medical language.

Alpha implementation:

- `POST /admin/wearables/daily-energy` writes
  `outputs/daily_energy_overview.json`;
- the overview is local admin evidence only and is not a consumer mobile home
  screen yet;
- soft cues are advisory trend language and never Phase 1 runtime safety truth.

### Post-Analysis Surface

Extend Capability Timeline with:

- energy reserve start/end if available;
- HR load per segment;
- fatigue decay across route progress;
- rest rhythm classification;
- update-baseline preview.

### Pretrip Surface

Show:

- route difficulty vs user's recent baseline;
- estimated reserve demand;
- suggested pacing and rest plan;
- companion match candidates if user opts in.

### Companion Match Surface

For each candidate:

- match score;
- match band;
- why similar;
- where mismatch may matter;
- missing-data confidence;
- privacy scope.

Alpha visibility policy:

- `minimum_activity_count_for_public_match` is 3 local query activities;
- fewer local query activities may still generate review-only artifacts for
  private planning/debug review;
- timeline-derived candidate capsules can be compared, but one-route candidates
  are flagged as review-only evidence;
- `scout_companion_consent_pool` is local-only and requires explicit consent per
  capsule before matching against pool entries;
- pool withdrawal deletes the local pool entry without deleting the source
  capsule or imported activity summaries;
- `scout_companion_pool_exchange_package` supports manual local exchange of
  explicit-consent pool entries without remote upload;
- `scout_companion_community_publish_dry_run` projects eligible public pool
  entries into a dry-run package without private owner refs, local consent
  metadata, raw data, route-family names, network transport, or upload;
- no match score is a safety guarantee.

Use neutral wording:

- good: "similar rhythm", "similar ascent profile", "rests less often";
- avoid: "stronger", "weaker", "unsafe", "unfit".

### Field Cue Surface

Runtime cue examples:

- "You are below your usual reserve trend for this effort. Consider a short
  rest."
- "Heart-rate load is higher than your baseline on similar slope. Slow down and
  check how you feel."
- "Rest rhythm is later than usual for this route effort."
- "This segment is becoming harder than expected. Slow down and keep the next
  checkpoint visible."
- "Pause and verify your current location, next checkpoint, daylight, and retreat
  option before continuing."

Each cue must be logged as advisory evidence only.

## Commands

Implemented alpha normalization command for sanitized provider/file-derived
envelopes:

```bash
python -m scout_energy_reserve \
  normalize \
  --input tests/fixtures/wearables/adapters/apple_health_sanitized_workout.json \
  --input tests/fixtures/wearables/adapters/garmin_connect_sanitized_activity.json \
  --input tests/fixtures/wearables/adapters/gpx_derived_summary.json \
  --output-dir /data/scout/energy/normalized \
  --root /Users/alexwang0315/scout-fusion
```

Implemented alpha raw Apple Health export XML, Garmin Connect JSON, and
GPX/FIT/TCX summarization command:

```bash
python -m scout_energy_reserve \
  summarize-raw \
  --input /data/scout/local/garmin_activity.json \
  --source-format garmin_connect_export \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id local.garmin.activity.001
```

Implemented alpha local export batch summarization command:

```bash
python -m scout_energy_reserve \
  summarize-raw-batch \
  --input /data/scout/local/garmin_activities.json \
  --source-format garmin_connect_export \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id-prefix local.garmin.batch
```

Implemented alpha local provider archive discovery command:

```bash
python -m scout_energy_reserve \
  inspect-provider-archive \
  --input /data/scout/local/garmin-export.zip \
  --source-format garmin_connect_export

python -m scout_energy_reserve \
  summarize-provider-archive \
  --input /data/scout/local/garmin-export.zip \
  --source-format garmin_connect_export \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id-prefix archive.garmin
```

Implemented alpha offline provider API fixture command:

```bash
python -m scout_energy_reserve \
  summarize-provider-api-fixture \
  --input /data/scout/local/garmin-api-response.json \
  --provider garmin_health_api \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id-prefix api.garmin \
  --scope activity:read \
  --explicit-consent

python -m scout_energy_reserve \
  summarize-provider-api-fixture \
  --input /data/scout/local/apple-healthkit-response.json \
  --provider apple_healthkit_api \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id-prefix api.apple \
  --scope HKWorkoutType \
  --scope HKQuantityTypeIdentifierHeartRate \
  --explicit-consent
```

Implemented alpha local live-frame fixture normalization command:

```bash
python -m scout_energy_reserve \
  summarize-live-frame-fixture \
  --input /data/scout/local/apple-live-frame-fixture.json \
  --provider apple_healthkit_live_fixture \
  --output-dir /data/scout/energy/field-observations \
  --stream-id stream.apple.fixture.001 \
  --route-segment-ref segment.local.climb \
  --expected-baseline-bpm 136
```

Implemented alpha live provider transport preflight command:

```bash
python -m scout_energy_reserve \
  provider-live-preflight \
  --provider garmin_health_api_live \
  --output /data/scout/energy/provider-live-preflight.json \
  --account-ref local.garmin.account \
  --device-ref local.garmin.watch \
  --auth-token-ref local-token-ref \
  --scope activity:read \
  --scope heart_rate:read \
  --capability activity_summary_import \
  --capability heart_rate_samples \
  --explicit-consent
```

Implemented alpha live provider request-plan command:

```bash
python -m scout_energy_reserve \
  provider-live-request-plan \
  --preflight /data/scout/energy/provider-live-preflight.json \
  --output /data/scout/energy/provider-live-request-plan.json \
  --window-start-date 2026-05-20 \
  --window-end-date 2026-05-27 \
  --capability activity_summary_import \
  --capability heart_rate_samples
```

Implemented alpha local admin endpoints:

```text
POST /admin/wearables/provider-live-preflight
POST /admin/wearables/provider-live-request-plan
POST /admin/wearables/provider-live-register-executor
POST /admin/wearables/provider-live-executor-readiness
POST /admin/wearables/provider-live-executor-handoff
POST /admin/wearables/provider-live-index-executor-handoff-outbox
POST /admin/wearables/provider-live-executor-handoff-pickup-manifest
POST /admin/wearables/provider-live-handoff-fixture-replay
POST /admin/wearables/provider-live-executor-pickup-response-manifest
POST /admin/wearables/provider-live-consume-executor-pickup-response
POST /admin/wearables/provider-live-executor-pickup-response-consumption-receipt
POST /admin/wearables/provider-live-executor-pickup-status-snapshot
POST /admin/wearables/provider-live-executor-lifecycle-audit
POST /admin/wearables/provider-live-executor-production-readiness-gate
POST /admin/wearables/provider-live-executor-response-manifest
POST /admin/wearables/provider-live-index-executor-response-inbox
POST /admin/wearables/provider-live-executor-response-admit
POST /admin/wearables/provider-live-consume-executor-response
POST /admin/wearables/provider-live-consume-executor-response-inbox
POST /admin/wearables/provider-live-consume-executor-response-inbox-batch
POST /admin/wearables/provider-live-executor-response-inbox-batch-receipt
POST /admin/wearables/provider-live-executor-response-inbox-status-snapshot
POST /admin/wearables/provider-live-fixture-replay
POST /admin/wearables/provider-live-replay-admit
POST /admin/wearables/provider-live-rehearse-executor
POST /admin/wearables/provider-live-response-admit
POST /admin/wearables/provider-live-materialize
POST /admin/wearables/provider-live-sync-package
POST /admin/wearables/provider-live-build-energy
```

Implemented alpha live provider executor-registration command:

```bash
python -m scout_energy_reserve \
  provider-live-register-executor \
  --preflight /data/scout/energy/provider-live-preflight.json \
  --output /data/scout/energy/provider-live-executor-registration.json \
  --executor-kind garmin_health_api_client \
  --executor-ref local.garmin.executor.private \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values
```

Implemented alpha live provider executor-readiness command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-readiness \
  --request-plan /data/scout/energy/provider-live-request-plan.json \
  --output /data/scout/energy/provider-live-executor-readiness.json
```

Implemented alpha live provider executor handoff-package command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-handoff \
  --request-plan /data/scout/energy/provider-live-request-plan.json \
  --executor-registration /data/scout/energy/provider-live-executor-registration.json \
  --output /data/scout/energy/provider-live-executor-handoff.json
```

Implemented alpha live provider executor handoff outbox-index command:

```bash
python -m scout_energy_reserve \
  provider-live-index-executor-handoff-outbox \
  --outbox-dir /data/scout/energy/provider-live-executor-handoff-outbox \
  --output /data/scout/energy/provider-live-executor-handoff-outbox-index.json
```

Implemented alpha live provider executor handoff pickup-manifest command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-handoff-pickup-manifest \
  --outbox-index /data/scout/energy/provider-live-executor-handoff-outbox-index.json \
  --output /data/scout/energy/provider-live-executor-handoff-pickup-manifest.json
```

Implemented alpha live provider executor fixture-replay command:

```bash
python -m scout_energy_reserve \
  provider-live-fixture-replay \
  --request-plan /data/scout/energy/provider-live-request-plan.json \
  --executor-registration /data/scout/energy/provider-live-executor-registration.json \
  --response-fixture /data/scout/local/garmin-api-response.json \
  --output /data/scout/energy/provider-live-fixture-replay.json
```

Implemented alpha live provider handoff fixture-replay command:

```bash
python -m scout_energy_reserve \
  provider-live-handoff-fixture-replay \
  --executor-handoff /data/scout/energy/provider-live-executor-handoff.json \
  --response-fixture /data/scout/local/garmin-api-response.json \
  --output /data/scout/energy/provider-live-handoff-fixture-replay.json
```

Implemented alpha live provider executor pickup response-manifest command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-pickup-response-manifest \
  --pickup-manifest /data/scout/energy/provider-live-executor-handoff-pickup-manifest.json \
  --response-payload /data/scout/local/garmin-api-response.json \
  --output /data/scout/energy/provider-live-executor-pickup-response-manifest.json
```

Implemented alpha live provider executor pickup response-consumption command:

```bash
python -m scout_energy_reserve \
  provider-live-consume-executor-pickup-response \
  --executor-response-manifest /data/scout/energy/provider-live-executor-pickup-response-manifest.json \
  --output-dir /data/scout/energy/provider-live-executor-pickup-response-consumption \
  --activity-id-prefix live.garmin.executor.pickup.response.consumed \
  --capability activity_summary_import \
  --capability heart_rate_samples \
  --reference-date 2026-05-27
```

Implemented alpha live provider executor pickup response-consumption receipt
command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-pickup-response-consumption-receipt \
  --pickup-response-consumption /data/scout/energy/provider-live-executor-pickup-response-consumption/provider_live_executor_pickup_response_consumption.json \
  --output /data/scout/energy/provider-live-executor-pickup-response-consumption-receipt.json
```

Implemented alpha live provider executor pickup-status snapshot command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-pickup-status-snapshot \
  --pickup-manifest /data/scout/energy/provider-live-executor-handoff-pickup-manifest.json \
  --executor-response-manifest /data/scout/energy/provider-live-executor-pickup-response-manifest.json \
  --pickup-response-consumption /data/scout/energy/provider-live-executor-pickup-response-consumption/provider_live_executor_pickup_response_consumption.json \
  --pickup-response-receipt /data/scout/energy/provider-live-executor-pickup-response-consumption-receipt.json \
  --output /data/scout/energy/provider-live-executor-pickup-status-snapshot.json
```

Implemented alpha live provider executor lifecycle-audit command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-lifecycle-audit \
  --pickup-status-snapshot /data/scout/energy/provider-live-executor-pickup-status-snapshot.json \
  --inbox-status-snapshot /data/scout/energy/provider-live-executor-response-inbox-status-snapshot.json \
  --output /data/scout/energy/provider-live-executor-lifecycle-audit.json
```

Implemented alpha live provider executor production-readiness gate command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-production-readiness-gate \
  --lifecycle-audit /data/scout/energy/provider-live-executor-lifecycle-audit.json \
  --output /data/scout/energy/provider-live-executor-production-readiness-gate.json
```

Implemented alpha live provider executor response-manifest command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-response-manifest \
  --executor-handoff /data/scout/energy/provider-live-executor-handoff.json \
  --response-payload /data/scout/local/garmin-api-response.json \
  --output /data/scout/energy/provider-live-executor-response-manifest.json
```

Implemented alpha live provider executor response inbox-index command:

```bash
python -m scout_energy_reserve \
  provider-live-index-executor-response-inbox \
  --inbox-dir /data/scout/energy/executor-response-inbox \
  --output /data/scout/energy/provider-live-executor-response-inbox-index.json
```

Implemented alpha live provider executor response-manifest admission command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-response-admit \
  --executor-response-manifest /data/scout/energy/provider-live-executor-response-manifest.json \
  --output /data/scout/energy/provider-live-executor-response-admission.json \
  --output-dir /data/scout/energy/executor-response-sanitized-imports \
  --activity-id-prefix live.garmin.executor.response.admitted \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values
```

Implemented alpha live provider executor response consumption command:

```bash
python -m scout_energy_reserve \
  provider-live-consume-executor-response \
  --executor-response-manifest /data/scout/energy/provider-live-executor-response-manifest.json \
  --output-dir /data/scout/energy/provider-live-executor-response-consumption \
  --activity-id-prefix live.garmin.executor.response.consumed \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values \
  --reference-date 2026-05-27 \
  --root /data/scout/energy
```

Implemented alpha live provider executor response inbox-consumption command:

```bash
python -m scout_energy_reserve \
  provider-live-consume-executor-response-inbox \
  --inbox-index /data/scout/energy/provider-live-executor-response-inbox-index.json \
  --output-dir /data/scout/energy/provider-live-executor-response-inbox-consumption \
  --activity-id-prefix live.garmin.executor.response.inbox.consumed \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values \
  --reference-date 2026-05-27 \
  --root /data/scout/energy
```

Implemented alpha live provider executor response inbox batch-consumption command:

```bash
python -m scout_energy_reserve \
  provider-live-consume-executor-response-inbox-batch \
  --inbox-index /data/scout/energy/provider-live-executor-response-inbox-index.json \
  --output-dir /data/scout/energy/provider-live-executor-response-inbox-batch \
  --activity-id-prefix live.garmin.executor.response.inbox.batch \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values \
  --reference-date 2026-05-27 \
  --root /data/scout/energy
```

Implemented alpha live provider executor response inbox batch-receipt command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-response-inbox-batch-receipt \
  --batch-consumption /data/scout/energy/provider-live-executor-response-inbox-batch/provider_live_executor_response_inbox_batch_consumption.json \
  --output /data/scout/energy/provider-live-executor-response-inbox-batch-receipt.json
```

Implemented alpha live provider executor response inbox status-snapshot command:

```bash
python -m scout_energy_reserve \
  provider-live-executor-response-inbox-status-snapshot \
  --inbox-index /data/scout/energy/provider-live-executor-response-inbox-index.json \
  --batch-consumption /data/scout/energy/provider-live-executor-response-inbox-batch/provider_live_executor_response_inbox_batch_consumption.json \
  --batch-receipt /data/scout/energy/provider-live-executor-response-inbox-batch-receipt.json \
  --output /data/scout/energy/provider-live-executor-response-inbox-status-snapshot.json
```

Implemented alpha live provider replay-admission command:

```bash
python -m scout_energy_reserve \
  provider-live-replay-admit \
  --fixture-replay /data/scout/energy/provider-live-fixture-replay.json \
  --output /data/scout/energy/provider-live-replay-admission.json \
  --output-dir /data/scout/energy/replay-sanitized-imports \
  --activity-id-prefix live.garmin.replay.admitted \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values
```

Implemented alpha live provider executor-rehearsal command:

```bash
python -m scout_energy_reserve \
  provider-live-rehearse-executor \
  --request-plan /data/scout/energy/provider-live-request-plan.json \
  --executor-registration /data/scout/energy/provider-live-executor-registration.json \
  --response-fixture /data/scout/local/garmin-api-response.json \
  --output-dir /data/scout/energy/provider-live-executor-rehearsal \
  --activity-id-prefix live.garmin.rehearsed \
  --capability activity_summary_import \
  --capability provider_body_energy_source_values \
  --reference-date 2026-05-27 \
  --root /data/scout/energy
```

Implemented alpha live provider response-admission command:

```bash
python -m scout_energy_reserve \
  provider-live-response-admit \
  --request-plan /data/scout/energy/provider-live-request-plan.json \
  --response-fixture /data/scout/local/garmin-api-response.json \
  --output /data/scout/energy/provider-live-response-admission.json \
  --output-dir /data/scout/energy/sanitized-imports \
  --activity-id-prefix live.garmin.admitted \
  --capability activity_summary_import \
  --capability heart_rate_samples
```

Implemented alpha live provider materialization command:

```bash
python -m scout_energy_reserve \
  provider-live-materialize \
  --admission /data/scout/energy/provider-live-response-admission.json \
  --output /data/scout/energy/provider-live-materialization.json \
  --output-dir /data/scout/energy/normalized \
  --root /data/scout/energy
```

Implemented alpha live provider local sync-package command:

```bash
python -m scout_energy_reserve \
  provider-live-sync-package \
  --materialization /data/scout/energy/provider-live-materialization.json \
  --output /data/scout/energy/provider-live-sync-package.json \
  --root /data/scout/energy
```

Implemented alpha provider sync-package Energy Reserve build command:

```bash
python -m scout_energy_reserve \
  provider-live-build-energy \
  --sync-package /data/scout/energy/provider-live-sync-package.json \
  --output-dir /data/scout/energy/provider-sync-energy \
  --reference-date 2026-05-27 \
  --root /data/scout/energy
```

Implemented alpha command for provider-neutral wearable summary fixtures:

```bash
python -m scout_energy_reserve \
  build \
  --activity tests/fixtures/wearables/apple_health_clean_activity.json \
  --activity tests/fixtures/wearables/apple_health_missing_hr_interval.json \
  --activity tests/fixtures/wearables/garmin_body_battery_provider_values.json \
  --output-dir /data/scout/energy/local \
  --reference-date 2026-05-27 \
  --root /Users/alexwang0315/scout-fusion
```

Implemented alpha companion match command:

```bash
python -m scout_companion_match \
  score \
  --query-capsule /data/scout/energy/capsules/me.json \
  --candidate-capsule /data/scout/energy/capsules/candidate.json \
  --candidate-profile-ref shared_capsule.local_candidate \
  --output /data/scout/energy/match-results/candidate.match.json
```

Implemented alpha local companion consent pool commands:

```bash
python -m scout_companion_match \
  pool-build \
  --capsule /data/scout/energy/capsules/candidate.json \
  --public-profile-ref pool.local_candidate \
  --explicit-consent \
  --output /data/scout/energy/pools/local_pool.json

python -m scout_companion_match \
  pool-score \
  --query-capsule /data/scout/energy/capsules/me.json \
  --pool /data/scout/energy/pools/local_pool.json \
  --output /data/scout/energy/match-results/local_pool.match.json

python -m scout_companion_match \
  pool-export-package \
  --pool /data/scout/energy/pools/local_pool.json \
  --public-profile-ref pool.local_candidate \
  --output /data/scout/energy/pools/local_pool.exchange.json

python -m scout_companion_match \
  pool-import-package \
  --package /data/scout/energy/pools/local_pool.exchange.json \
  --output /data/scout/energy/pools/imported_pool.json

python -m scout_companion_match \
  community-publish-dry-run \
  --pool /data/scout/energy/pools/local_pool.json \
  --public-profile-ref pool.local_candidate \
  --community-ref community.taiwan.local_hikes \
  --explicit-community-consent \
  --output /data/scout/energy/pools/community_publish_dry_run.json
```

Implemented alpha local admin lifecycle APIs:

```text
POST /admin/wearables/export-energy
  explicit_consent=true
  include_reserve_summary=false|true

POST /admin/wearables/delete-energy
  include_exports=true

POST /admin/wearables/daily-energy
  reference_date=YYYY-MM-DD

POST /admin/wearables/mobile-handoff
  reference_date=YYYY-MM-DD
  companion_match_review_path=/data/scout/energy/match-results/local.match.json
```

Implemented alpha local mobile handoff command:

```bash
python -m scout_mobile_handoff \
  build \
  --daily-home-preview /data/scout/energy/outputs/daily_home_preview.json \
  --companion-match-review /data/scout/energy/match-results/local.match.json \
  --output /data/scout/mobile/mobile_energy_companion_handoff.json
```

Alpha verification commands:

```bash
./venv/bin/python -m pytest tests/test_scout_energy_reserve.py
./venv/bin/python -m pytest tests/test_scout_companion_match.py
./venv/bin/python -m pytest tests/test_post_analysis_capability_timeline.py
```

## Project Structure

Implemented alpha files:

```text
scout_energy_reserve.py
  CLI and orchestration for fixture-backed wearable summary baseline building.

scout_energy_models.py
  Pydantic models for activity summaries, baseline profiles, reserve trend,
  and field cue evidence.

scout_energy_field_cue.py
  Sanitized local wearable observation to advisory field cue and voice cue
  artifact builder.

scout_wearable_stream_admission.py
  Local fixture-batch stream admission dry-run for sanitized observations.

scout_wearable_live_frames.py
  Local Apple/Garmin live-like frame fixture normalization into sanitized field
  observations for stream-admission dry-runs.

scout_energy_baseline.py
  Rolling baseline, acute/recent/stable window calculations, and confidence.

scout_wearable_adapters.py
  Sanitized Apple/Garmin and GPX/FIT/TCX file-derived summary normalization
  into provider-neutral wearable summaries.

scout_wearable_raw_importers.py
  Local Apple Health export XML, Garmin Connect JSON, and GPX/FIT/TCX raw-file
  single/batch/archive manifest and summarization into sanitized import
  envelopes without embedding raw health payloads, raw tracks, or exact
  timestamps.

scout_wearable_admin.py
  Local inventory import/delete, energy refresh, explicit-consent export, and
  generated-artifact deletion lifecycle helpers, plus local Daily/Home overview
  generation.

scout_wearable_daily_home.py
  Local Daily/Home preview JSON and static HTML renderer derived from the
  wearable daily overview artifact.

scout_mobile_handoff.py
  Local mobile Energy Reserve / Companion Match handoff package builder for
  future app integration without network sync or runtime authority.

scout_companion_match.py
  CLI for local capsule scoring, consent-pool building/scoring, and match review
  artifact writing.

scout_companion_match_models.py
  Capsule vector normalization, match result, review artifact, local consent
  pool, community publish dry-run, and privacy contracts.

post_analysis_energy_feedback.py
  Read-only post-analysis feedback from reserve baseline, explanation, and
  companion capsule artifacts.

pretrip_admin_view.py
  Optional pretrip projection of reviewed baseline context.

docs/admin/phase1-after-action.html
  Post-analysis body reserve and capability match panels.

docs/admin/phase4-pretrip-planning.html
  Read-only route feasibility, companion match preview, and local Daily/Home
  preview control.

tests/test_scout_energy_reserve.py
tests/test_scout_companion_match.py
tests/test_scout_energy_admin_pretrip.py
tests/test_scout_energy_feedback_voice.py
tests/test_scout_wearable_adapters.py
tests/test_scout_wearable_validator.py
tests/fixtures/wearables/
tests/fixtures/wearables/adapters/
```

## Implementation Plan

### Slice 1: Spec And Fixture Contract

- Status: implemented for local fixture-backed alpha.
- Added provider-neutral wearable activity summary fixtures.
- Capability capsule is produced deterministically from fixture summaries.
- Acceptance:
  - fixtures carry privacy and boundary metadata;
  - no raw Apple/Garmin payload is committed.

### Slice 2: Activity Normalization

- Status: implemented for provider-neutral summaries that preserve source path
  and sha256.
- Sanitized provider/file-derived adapter envelopes are implemented for Apple
  Health, Garmin Connect, GPX, FIT, and TCX summary inputs.
- Local Apple Health export XML and Garmin Connect JSON single/batch
  summarizers, local provider archive directory/zip manifest inspection,
  multi-member Garmin activity JSON archive import, Garmin FIT archive member
  import, FIT session-summary and lap-summary fallbacks, plus GPX, TCX, and
  minimal FIT raw-file summarizers, are implemented and emit sanitized envelopes
  for the existing normalization path.
- Remote provider APIs and broader production FIT coverage remain deferred.
- Acceptance:
  - heart-rate missingness and confidence are explicit;
  - provider-specific body battery/stress values are passed through as source
    values, not treated as Scout truth.

### Slice 3: Baseline Builder

- Status: implemented.
- Builds 7/28/90-day personal baseline and emits
  `scout_energy_reserve_baseline`.
- Emits local route-family profiles when a deterministic family has at least two
  activities.
- Acceptance:
  - baseline is user-local by default;
  - reserve bands are explainable;
  - one outlier does not permanently label the user.

### Slice 4: Capability Vector

- Status: implemented for wearable summaries and post-analysis Capability
  Timeline artifacts.
- Acceptance:
  - vector excludes raw GPX and exact timestamps;
  - moving time and rest rhythm are represented separately.

### Slice 5: Companion Match Score

- Status: implemented.
- Emits ranked companion match review artifacts with explanations and
  confidence.
- Public match display is gated by a minimum of three local query activities;
  below that threshold, artifacts remain review-only.
- Local companion consent pool artifacts can be built and scored without remote
  upload.
- Acceptance:
  - score is symmetric when weights are symmetric;
  - missing features lower confidence rather than crashing;
  - language stays neutral.
  - pool entries require explicit consent and support local withdrawal;

### Slice 6: Admin UI Read-Only Projection

- Status: implemented for `/admin/pretrip` wearables controls and optional
  post-analysis sections.
- Acceptance:
  - write endpoints only create local reviewed artifacts under workspace paths;
  - no `/safety/*` calls;
  - privacy exclusions are visible.

### Slice 7: Field Advisory Cue

- Status: implemented for deterministic sanitized observation artifacts and
  voice cue output; live wearable streaming remains deferred.
- Emits `scout_energy_field_advisory_cue` from a
  `scout_wearable_field_observation` plus baseline.
- `scout_wearable_stream_admission.py` can dry-run local fixture-batch stream
  admission into cue artifacts without runtime ingest.
- Acceptance:
  - cues are logged as advisory evidence only;
  - sanitized observations reject exact timestamps and raw payload fields;
  - stream admission rejects network/provider API/runtime ingest modes;
  - user can silence or dismiss;
  - no Phase 1 safety mutation occurs.

### Slice 8: Local Export And Delete Lifecycle

- Status: implemented for local admin APIs.
- `POST /admin/wearables/export-energy` requires explicit local consent before
  writing a coarse `scout_wearable_energy_export_bundle`.
- `POST /admin/wearables/delete-energy` deletes generated outputs while keeping
  imported activity summaries and source files untouched.
- Acceptance:
  - no remote upload or community pool write occurs;
  - raw health payloads, raw tracks, exact timestamps, and route-family names
    are not exported by default;
  - deleting generated artifacts does not delete activity summaries;
  - no `/safety/*` calls or Phase 1 runtime mutation occur.

### Slice 9: Local Daily/Home Overview

- Status: implemented for local admin artifact/API.
- `POST /admin/wearables/daily-energy` writes
  `scout_wearable_daily_energy_overview`.
- Acceptance:
  - includes current reserve band;
  - includes 7/28/90-day trend fields;
  - includes recent load/recovery explanation;
  - includes a next-day soft cue;
  - does not use medical language as product guidance;
  - remains advisory-only and not Phase 1 runtime safety truth.

### Slice 10: Local Daily/Home Preview Surface

- Status: implemented for local admin preview artifact/API.
- `POST /admin/wearables/daily-home-preview` writes
  `scout_wearable_daily_home_preview` plus a static HTML preview.
- `GET /admin/wearables/daily-home-preview` serves the local HTML preview.
- Acceptance:
  - derives only from `scout_wearable_daily_energy_overview`;
  - includes current reserve band, reserve score, 7/28/90 trend cards,
    recent-load explanation, and next-day soft cue;
  - embeds source provider, source path, sha256, data quality, privacy, and
    boundary metadata;
  - exposes no raw heart-rate samples, raw health payloads, raw tracks, exact
    timestamps, or home/work traces;
  - performs no network fetch, remote upload, `/safety/*` call, or Phase 1
    runtime mutation.

### Slice 11: Provider Archive Manifest

- Status: implemented for local Apple/Garmin archive directories/zips.
- `python -m scout_energy_reserve inspect-provider-archive` emits a
  `scout_wearable_provider_archive_manifest` without writing sanitized imports.
- `summarize-provider-archive` can summarize multiple supported Garmin activity
  JSON members plus supported Garmin FIT members from one archive.
- Acceptance:
  - manifest includes source provider, source path, sha256, member sha256,
    data quality, privacy, and boundary metadata;
  - hidden `__MACOSX`/dot members are ignored;
  - wellness/non-activity JSON members are not imported as activity truth;
  - FIT archive members are parsed from archive bytes without extracting raw
    payloads into the workspace;
  - FIT session-summary and lap-summary members without track points can be
    summarized without exposing raw FIT records or exact timestamps;
  - no raw provider records, raw track geometry, exact timestamps, network fetch,
    remote upload, `/safety/*` call, or Phase 1 mutation occurs.

### Slice 12: Offline Provider API Fixture Import

- Status: implemented for Garmin Health API response fixtures and Apple
  HealthKit-style workout response fixtures.
- `python -m scout_energy_reserve summarize-provider-api-fixture` writes
  sanitized import envelopes from a local provider API fixture.
- Acceptance:
  - explicit consent is required before any output is written;
  - authorization metadata includes provider, scopes, network mode, and token
    ref hash, but never exposes token values;
  - network mode is `offline_fixture` and no real provider API call occurs;
  - Apple HealthKit fixture scopes are normalized to coarse read scopes before
    output, so raw HealthKit type identifiers are not shared;
  - output uses the same sanitized import path as local provider exports;
  - raw provider response fields, exact timestamps, raw tracks, remote upload,
    `/safety/*` calls, and Phase 1 mutation remain excluded.

### Slice 13: Local Live-Frame Fixture Normalization

- Status: implemented for Apple HealthKit-style and Garmin-style local live
  frame fixtures.
- `python -m scout_energy_reserve summarize-live-frame-fixture` writes
  sanitized `scout_wearable_field_observation` artifacts from local live-like
  fixture frames for the existing stream-admission dry-run path.
- Acceptance:
  - raw fixture timestamps are used only transiently to derive `offset_s`;
  - output includes source provider, source path, sha256, data quality, privacy,
    and boundary metadata;
  - token refs, raw frame/sample arrays, raw provider field names, exact
    timestamps, and provider body battery/stress source fields are not embedded;
  - no network request, live provider API call, runtime ingest, `/safety/*`
    call, or Phase 1 mutation occurs;
  - generated observations can feed stream-admission dry-run without changing
    Phase 1 safety truth.

### Slice 14: Community Publish Dry-Run Contract

- Status: implemented for local explicit-consent pool entries.
- `python -m scout_companion_match community-publish-dry-run` writes a
  `scout_companion_community_publish_dry_run` artifact for future community
  service preflight review.
- Acceptance:
  - explicit community consent is required before output;
  - only public-profile refs and coarse capability vectors are projected;
  - private owner refs, local consent metadata, route-family names, raw tracks,
    exact timestamps, and raw health payloads are excluded;
  - output records `remote_upload_allowed=false`,
    `remote_upload_performed=false`, and `network_request_performed=false`;
  - no `/safety/*` call, Phase 1 mutation, medical assessment, or fitness
    ranking occurs.

### Slice 15: Local Mobile Handoff Contract

- Status: implemented for local Daily/Home preview plus optional companion match
  review artifacts.
- `python -m scout_mobile_handoff build` and
  `POST /admin/wearables/mobile-handoff` write
  `scout_mobile_energy_companion_handoff`.
- Acceptance:
  - handoff includes current reserve hero, 7/28/90 trend cards, next-day soft
    cue, and optional companion ranked-match summary;
  - source provider, source path, sha256, data quality, privacy, and boundary
    metadata are preserved;
  - output records `network_sync_allowed=false`,
    `network_sync_performed=false`, `mobile_runtime_authority=false`, and
    `phase1_safety_state_authority=false`;
  - raw samples, raw health payloads, raw tracks, exact timestamps, medical
    guidance, `/safety/*` calls, and Phase 1 runtime truth remain excluded.

### Slice 16: Live Provider Transport Preflight Contract

- Status: implemented for local Apple HealthKit and Garmin live transport
  preflight artifacts through CLI and local admin API.
- `python -m scout_energy_reserve provider-live-preflight` writes a
  `scout_wearable_provider_live_transport_preflight` artifact without reading a
  provider response fixture or calling a provider API.
- `POST /admin/wearables/provider-live-preflight` writes the same artifact under
  the local wearable outputs directory.
- Acceptance:
  - explicit consent, account ref, token ref, provider scopes, and requested
    capability flags are required before output is written;
  - account, device, and token refs are represented only by sha256 digests;
  - Apple HealthKit scopes are normalized to coarse read scopes before output,
    so raw HealthKit type identifiers are not shared;
  - capability flags are checked against provider support and available coarse
    scopes;
  - output records `transport_mode=preflight_only`,
    `network_request_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - raw provider payloads, exact timestamps, remote upload, `/safety/*` calls,
    and Phase 1 mutation remain excluded.

### Slice 17: Live Provider Request-Plan Contract

- Status: implemented for local Apple HealthKit and Garmin request-plan
  artifacts built from a validated preflight artifact through CLI and local
  admin API.
- `python -m scout_energy_reserve provider-live-request-plan` writes a
  `scout_wearable_provider_live_transport_request_plan` artifact without
  binding an executor, exposing request bodies, or calling a provider API.
- `POST /admin/wearables/provider-live-request-plan` writes the same artifact
  under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_preflight` artifact is
    required;
  - only capabilities approved by the preflight can be planned;
  - the query window is date-only, not exact timestamp based;
  - provider request descriptors are represented by sha256 hashes plus coarse
    provider endpoint refs;
  - output records `transport_mode=request_plan_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `real_provider_api_called=false`, and `runtime_ingest_performed=false`;
  - raw request bodies, raw provider responses, token/account/device refs,
    exact timestamps, `/safety/*` calls, and Phase 1 mutation remain excluded.

### Slice 17.25: Live Provider Executor Registration Contract

- Status: implemented for local Apple HealthKit and Garmin executor metadata
  registration from a validated preflight artifact.
- `python -m scout_energy_reserve provider-live-register-executor` writes a
  `scout_wearable_provider_live_executor_registration` artifact.
- `POST /admin/wearables/provider-live-register-executor` writes the same
  artifact under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_preflight` artifact is
    required;
  - executor kind must match the provider (`apple_healthkit_local_bridge` for
    Apple HealthKit, `garmin_health_api_client` for Garmin Health API);
  - supported capabilities must be allowed by the preflight;
  - executor refs are represented only by sha256 digest and credential values
    are never loaded or exposed;
  - output records `transport_mode=executor_registration_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.5: Live Provider Executor Readiness Gate

- Status: implemented for local Apple HealthKit and Garmin request-plan
  artifacts, with optional local executor-registration metadata.
- `python -m scout_energy_reserve provider-live-executor-readiness` writes a
  `scout_wearable_provider_live_executor_readiness` artifact from a valid
  request-plan artifact.
- `POST /admin/wearables/provider-live-executor-readiness` writes the same
  artifact under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_request_plan` artifact is
    required;
  - request-plan prerequisites are summarized without exposing request bodies,
    token/account/device refs, or raw response payloads;
  - without registration, output records blockers
    `live_provider_executor_not_registered` and
    `network_execution_disabled_by_local_contract`;
  - with valid local executor registration, output removes the missing-executor
    blocker but still records `ready_for_live_execution=false` and
    `network_execution_disabled_by_local_contract`;
  - output records `transport_mode=executor_readiness_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.55: Live Provider Executor Handoff Package Contract

- Status: implemented for local Apple HealthKit/Garmin request-plan and
  executor-registration artifacts.
- `python -m scout_energy_reserve provider-live-executor-handoff` writes a
  `scout_wearable_provider_live_executor_handoff_package` artifact.
- `POST /admin/wearables/provider-live-executor-handoff` writes the same
  artifact under the local wearable outputs directory.
- Acceptance:
  - valid `scout_wearable_provider_live_transport_request_plan` and
    `scout_wearable_provider_live_executor_registration` artifacts are required;
  - request descriptors include coarse provider endpoint refs and descriptor
    hashes, not request bodies;
  - executor metadata includes only executor kind, supported capabilities, and
    executor-ref sha256;
  - readiness blockers remain explicit and `ready_for_live_execution=false`;
  - output records `transport_mode=executor_handoff_package_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.56: Live Provider Handoff Fixture-Replay Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff-package
  artifacts replayed against local provider response fixtures.
- `python -m scout_energy_reserve provider-live-handoff-fixture-replay` consumes
  a `scout_wearable_provider_live_executor_handoff_package` artifact and writes
  a `scout_wearable_provider_live_executor_fixture_replay` artifact.
- `POST /admin/wearables/provider-live-handoff-fixture-replay` writes the same
  replay artifact under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_handoff_package` artifact is
    required;
  - handoff-package request-plan and executor-registration sha256 values must
    match the current local source artifacts before replay;
  - replay output records the consumed handoff-package sha256 without embedding
    credentials, request bodies, or provider responses;
  - the existing executor-rehearsal path writes a handoff package and consumes
    it for fixture replay before replay admission;
  - output records `transport_mode=executor_fixture_replay_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.57: Live Provider Executor Response-Manifest Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff-package
  artifacts paired with a local executor response payload reference.
- `python -m scout_energy_reserve provider-live-executor-response-manifest`
  writes a `scout_wearable_provider_live_executor_response_manifest` artifact.
- `python -m scout_energy_reserve provider-live-executor-response-admit` admits
  the response manifest into the existing sanitized-import path.
- `POST /admin/wearables/provider-live-executor-response-manifest` and
  `POST /admin/wearables/provider-live-executor-response-admit` expose the same
  local contracts from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_handoff_package` artifact is
    required;
  - handoff-package request-plan and executor-registration sha256 values must
    match the current local source artifacts before manifest creation or
    admission;
  - the response payload is referenced by source path and sha256 only, with
    `raw_response_embedded=false`, `raw_response_committed=false`, and
    `request_body_exposed=false`;
  - admission rechecks the handoff sha256 and response payload sha256 before
    using the existing provider API fixture sanitizer;
  - the existing executor-rehearsal path now writes an executor response
    manifest and admits through that manifest before materialization;
  - output records `transport_mode=executor_response_manifest_only` for the
    manifest and `transport_mode=executor_response_manifest_admission_only` for
    admission, with `request_executor_bound=false`,
    `network_request_performed=false`, `network_sync_performed=false`,
    `remote_upload_allowed=false`, `remote_upload_performed=false`,
    `real_provider_api_called=false`, and `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.575: Live Provider Executor Response Inbox Index Contract

- Status: implemented for local Apple HealthKit/Garmin executor response
  manifest inbox directories.
- `python -m scout_energy_reserve provider-live-index-executor-response-inbox`
  scans a local inbox directory and writes a
  `scout_wearable_provider_live_executor_response_inbox_index` artifact.
- `POST /admin/wearables/provider-live-index-executor-response-inbox` exposes
  the same local index contract from the admin surface.
- Acceptance:
  - the inbox is a local directory of JSON files;
  - response manifest candidates are checked for safe transport/privacy/boundary
    fields, handoff-package sha256 match, and response-payload sha256 match;
  - eligible and rejected JSON files are both represented by source path, file
    sha256, artifact kind, and precheck status only;
  - the index does not consume manifests, sanitize payloads, build energy
    artifacts, or embed raw response payloads;
  - output records `transport_mode=executor_response_inbox_index_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.585: Live Provider Executor Response Inbox Consumption Contract

- Status: implemented for local Apple HealthKit/Garmin executor response inbox
  index artifacts.
- `python -m scout_energy_reserve provider-live-consume-executor-response-inbox`
  selects an eligible manifest from a
  `scout_wearable_provider_live_executor_response_inbox_index` artifact and
  consumes it through response admission, materialization, local sync-package
  generation, and Energy Reserve artifact generation.
- `POST /admin/wearables/provider-live-consume-executor-response-inbox` exposes
  the same local contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_response_inbox_index`
    artifact is required;
  - the selected manifest must be marked `eligible_for_consumption_precheck`;
  - the selected manifest file sha256 is rechecked against the inbox index
    before consumption;
  - output records the selected manifest path/hash plus response-consumption
    artifact summary and Energy Reserve artifact paths;
  - output records `transport_mode=executor_response_inbox_consumption_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.59: Live Provider Executor Response Inbox Batch Consumption Contract

- Status: implemented for local Apple HealthKit/Garmin executor response inbox
  index artifacts.
- `python -m scout_energy_reserve provider-live-consume-executor-response-inbox-batch`
  consumes every eligible manifest in a
  `scout_wearable_provider_live_executor_response_inbox_index` artifact through
  response admission, materialization, local sync-package generation, and Energy
  Reserve artifact generation.
- `POST /admin/wearables/provider-live-consume-executor-response-inbox-batch`
  exposes the same local batch contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_response_inbox_index`
    artifact is required;
  - each selected manifest must be marked
    `eligible_for_consumption_precheck`;
  - each selected manifest file sha256 is rechecked against the inbox index
    before consumption;
  - each manifest is consumed into a separate local output subdirectory keyed by
    manifest file hash prefix;
  - output records the batch summary, consumed manifest count, per-manifest
    consumption paths, and Energy Reserve artifact paths;
  - output records
    `transport_mode=executor_response_inbox_batch_consumption_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.595: Live Provider Executor Response Inbox Batch Receipt Contract

- Status: implemented for local Apple HealthKit/Garmin executor response inbox
  batch-consumption artifacts.
- `python -m scout_energy_reserve provider-live-executor-response-inbox-batch-receipt`
  records a local receipt for a
  `scout_wearable_provider_live_executor_response_inbox_batch_consumption`
  artifact.
- `POST /admin/wearables/provider-live-executor-response-inbox-batch-receipt`
  exposes the same local receipt contract from the admin surface.
- Acceptance:
  - a valid
    `scout_wearable_provider_live_executor_response_inbox_batch_consumption`
    artifact is required;
  - the batch-consumption artifact must preserve local-only transport,
    sanitized privacy, non-medical boundary flags, and at least one consumed
    manifest entry;
  - each referenced consumption artifact is reloaded and checked against the
    batch summary before receipt writing;
  - output records the batch-consumption path/hash, inbox-index path/hash,
    consumed manifest paths/file hashes, per-manifest consumption paths/hashes,
    and baseline/explanation/companion-capsule paths;
  - output records
    `transport_mode=executor_response_inbox_batch_receipt_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - inbox files are not mutated, moved, deleted, uploaded, or synced;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.596: Live Provider Executor Response Inbox Status Snapshot Contract

- Status: implemented for local Apple HealthKit/Garmin executor response inbox
  index, batch-consumption, and batch-receipt artifacts.
- `python -m scout_energy_reserve provider-live-executor-response-inbox-status-snapshot`
  writes a local manifest-level status snapshot for a
  `scout_wearable_provider_live_executor_response_inbox_index` artifact, with
  optional batch-consumption and batch-receipt evidence.
- `POST /admin/wearables/provider-live-executor-response-inbox-status-snapshot`
  exposes the same local snapshot contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_response_inbox_index`
    artifact is required;
  - optional batch-consumption and batch-receipt artifacts must preserve
    local-only transport, sanitized privacy, non-medical boundary flags, and
    matching inbox sha256 refs;
  - when both optional artifacts are provided, the receipt must reference the
    same batch-consumption sha256;
  - output records manifest-level status as one of `eligible_pending`,
    `consumed_without_receipt`, `receipt_recorded`, or
    `rejected_by_precheck`;
  - output records input artifact paths/file hashes, manifest status counts,
    per-manifest source paths, manifest file hashes, response artifact hashes,
    and Energy Reserve output paths when available;
  - output records
    `transport_mode=executor_response_inbox_status_snapshot_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the snapshot is local operator evidence only and is not Phase 1 runtime
    safety truth;
  - inbox files are not mutated, moved, deleted, uploaded, or synced;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.597: Live Provider Executor Handoff Outbox Index Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff package
  outbox directories.
- `python -m scout_energy_reserve provider-live-index-executor-handoff-outbox`
  scans a local outbox directory and writes a
  `scout_wearable_provider_live_executor_handoff_outbox_index` artifact.
- `POST /admin/wearables/provider-live-index-executor-handoff-outbox` exposes
  the same local index contract from the admin surface.
- Acceptance:
  - the outbox is a local directory of JSON files;
  - handoff package candidates are checked for safe transport/privacy/boundary
    fields, request-plan sha256 match, executor-registration sha256 match, and
    deterministic handoff sha256 match against current local sources;
  - eligible and rejected JSON files are represented by source path, file
    sha256, artifact kind, and precheck status only;
  - the index does not bind an executor, expose credentials, generate request
    bodies, fetch provider data, consume responses, build energy artifacts, or
    mutate the outbox;
  - output records `transport_mode=executor_handoff_outbox_index_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.598: Live Provider Executor Handoff Pickup Manifest Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff outbox
  index artifacts.
- `python -m scout_energy_reserve provider-live-executor-handoff-pickup-manifest`
  selects one eligible handoff package from a
  `scout_wearable_provider_live_executor_handoff_outbox_index` artifact and
  writes a `scout_wearable_provider_live_executor_handoff_pickup_manifest`
  artifact.
- `POST /admin/wearables/provider-live-executor-handoff-pickup-manifest`
  exposes the same local pickup-manifest contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_handoff_outbox_index`
    artifact is required;
  - the selected handoff package must be marked
    `eligible_for_executor_pickup_precheck`;
  - the selected handoff package file sha256 and handoff artifact sha256 are
    rechecked before pickup-manifest writing;
  - output records the outbox-index path/hash, selected handoff path/file hash,
    request-plan and executor-registration hashes, request descriptor count,
    readiness blockers, and pickup status;
  - pickup status is `ready_for_external_executor_review` with
    `external_execution_authorized=false` and
    `network_execution_disabled_by_local_contract=true`;
  - output records `transport_mode=executor_handoff_pickup_manifest_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the pickup manifest does not bind an executor, expose credentials, generate
    request bodies, fetch provider data, consume responses, build energy
    artifacts, or mutate the outbox;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.599: Live Provider Executor Pickup Response Manifest Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff pickup
  manifest artifacts.
- `python -m scout_energy_reserve provider-live-executor-pickup-response-manifest`
  writes a `scout_wearable_provider_live_executor_response_manifest` artifact
  from a `scout_wearable_provider_live_executor_handoff_pickup_manifest` plus a
  local response payload path.
- `POST /admin/wearables/provider-live-executor-pickup-response-manifest`
  exposes the same local contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_handoff_pickup_manifest`
    artifact is required;
  - the pickup manifest must have `pickup_status=ready_for_external_executor_review`,
    `external_execution_authorized=false`, and
    `network_execution_disabled_by_local_contract=true`;
  - the selected handoff package file sha256 and handoff artifact sha256 are
    rechecked before response-manifest writing;
  - output keeps the existing
    `scout_wearable_provider_live_executor_response_manifest` artifact kind so
    downstream response admission/consumption paths can reuse the same local
    contract;
  - output adds pickup-manifest provenance, selected handoff metadata, and
    response payload path/hash while preserving `raw_response_embedded=false`,
    `raw_response_committed=false`, and `request_body_exposed=false`;
  - output records `transport_mode=executor_response_manifest_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the response manifest does not bind an executor, expose credentials,
    generate request bodies, fetch provider data, consume responses, build
    energy artifacts, or mutate the outbox;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.600: Live Provider Executor Pickup Response Consumption Contract

- Status: implemented for local Apple HealthKit/Garmin pickup-bound executor
  response manifests consumed through the local Energy Reserve pipeline.
- `python -m scout_energy_reserve provider-live-consume-executor-pickup-response`
  consumes a pickup-bound `scout_wearable_provider_live_executor_response_manifest`
  artifact through response admission, materialization, local sync-package
  generation, and Energy Reserve artifact generation.
- `POST /admin/wearables/provider-live-consume-executor-pickup-response`
  exposes the same local contract from the admin surface.
- Acceptance:
  - a valid pickup-bound `scout_wearable_provider_live_executor_response_manifest`
    artifact is required;
  - the embedded pickup manifest must have
    `pickup_status=ready_for_external_executor_review`,
    `external_execution_authorized=false`, and
    `network_execution_disabled_by_local_contract=true`;
  - the pickup manifest file is reloaded and its sha256 is checked against the
    response manifest before local consumption;
  - response-manifest admission still rechecks handoff and response-payload
    sha256 refs before sanitization;
  - output records pickup-manifest provenance, executor-response manifest
    provenance, response consumption artifact path/hash, baseline path,
    explanation path, and companion capsule path;
  - output records `transport_mode=executor_pickup_response_consumption_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the consumption contract does not bind an executor, expose credentials,
    generate request bodies, fetch provider data, mutate the outbox, remote
    upload, runtime ingest, or call `/safety/*`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.601: Live Provider Executor Pickup Response Consumption Receipt Contract

- Status: implemented for local Apple HealthKit/Garmin pickup-response
  consumption artifacts.
- `python -m scout_energy_reserve provider-live-executor-pickup-response-consumption-receipt`
  writes a local receipt for a
  `scout_wearable_provider_live_executor_pickup_response_consumption` artifact.
- `POST /admin/wearables/provider-live-executor-pickup-response-consumption-receipt`
  exposes the same local receipt contract from the admin surface.
- Acceptance:
  - a valid
    `scout_wearable_provider_live_executor_pickup_response_consumption`
    artifact is required;
  - the pickup manifest file, response manifest file, response-consumption file,
    baseline file, explanation file, and companion capsule file are reloaded or
    checked before receipt writing;
  - output records pickup-consumption path/hash/file hash, pickup-manifest
    provenance, executor-response manifest provenance, response-consumption
    path/hash/file hash, baseline path, explanation path, and companion capsule
    path;
  - output records `receipt_status=locally_recorded`;
  - output records `transport_mode=executor_pickup_response_consumption_receipt_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the receipt does not bind an executor, expose credentials, generate request
    bodies, fetch provider data, mutate outbox/inbox files, remote upload,
    runtime ingest, or call `/safety/*`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.602: Live Provider Executor Pickup Status Snapshot Contract

- Status: implemented for local Apple HealthKit/Garmin executor handoff pickup
  lifecycle artifacts.
- `python -m scout_energy_reserve provider-live-executor-pickup-status-snapshot`
  writes a local status snapshot for a pickup manifest plus optional
  pickup-bound response manifest, pickup response consumption, and pickup
  response receipt.
- `POST /admin/wearables/provider-live-executor-pickup-status-snapshot` exposes
  the same local status contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_handoff_pickup_manifest`
    artifact is required;
  - optional response-manifest evidence must be pickup-bound to the same pickup
    manifest sha256;
  - optional pickup-consumption evidence must reference the same pickup
    manifest and response manifest sha256 values;
  - optional pickup-receipt evidence must reference the same pickup-consumption
    sha256 and have `receipt_status=locally_recorded`;
  - output can report `awaiting_executor_response`,
    `response_manifest_recorded`, `consumed_without_receipt`, or
    `receipt_recorded`;
  - output records pickup-manifest, response-manifest, pickup-consumption, and
    pickup-receipt path/hash/file-hash refs when available;
  - output records `transport_mode=executor_pickup_status_snapshot_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the status snapshot does not bind an executor, expose credentials, generate
    request bodies, fetch provider data, mutate outbox/inbox files, remote
    upload, runtime ingest, or call `/safety/*`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.603: Live Provider Executor Lifecycle Audit Contract

- Status: implemented for local Apple HealthKit/Garmin executor lifecycle
  status artifacts.
- `python -m scout_energy_reserve provider-live-executor-lifecycle-audit`
  writes a local audit artifact from a pickup-status snapshot plus optional
  response-inbox status snapshot.
- `POST /admin/wearables/provider-live-executor-lifecycle-audit` exposes the
  same local audit contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_pickup_status_snapshot`
    artifact is required;
  - optional inbox status evidence must be a valid
    `scout_wearable_provider_live_executor_response_inbox_status_snapshot`
    artifact from the same provider;
  - output records pickup status snapshot path/hash/file hash,
    pickup lifecycle status, and pickup local evidence completeness;
  - output records inbox status snapshot path/hash/file hash and manifest
    status counts when inbox status evidence is provided;
  - output reports `local_evidence_complete` only when pickup evidence is
    complete and every eligible inbox manifest has a recorded receipt;
  - output records `transport_mode=executor_lifecycle_audit_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the audit does not bind an executor, expose credentials, generate request
    bodies, fetch provider data, mutate outbox/inbox files, remote upload,
    runtime ingest, or call `/safety/*`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.604: Live Provider Executor Production Readiness Gate

- Status: implemented for local Apple HealthKit/Garmin executor lifecycle audit
  artifacts.
- `python -m scout_energy_reserve provider-live-executor-production-readiness-gate`
  writes a local production-readiness gate from a
  `scout_wearable_provider_live_executor_lifecycle_audit` artifact.
- `POST /admin/wearables/provider-live-executor-production-readiness-gate`
  exposes the same local gate from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_lifecycle_audit` artifact is
    required;
  - an optional `scout_wearable_provider_live_connector_reference` artifact may
    be provided as a digest-only connector reference;
  - an optional `scout_wearable_provider_live_credential_vault_reference`
    artifact may be provided as a digest-only credential reference;
  - an optional `scout_wearable_provider_live_network_policy_reference` artifact
    may be provided as a digest-only network policy reference;
  - an optional `scout_wearable_provider_live_runtime_ingest_boundary_reference`
    artifact may be provided as a digest-only runtime boundary reference;
  - an optional `scout_wearable_provider_live_phase1_safety_boundary_reference`
    artifact may be provided as a digest-only Phase 1 safety boundary
    reference;
  - the lifecycle audit must remain local-only, non-production, non-runtime,
    non-medical, and non-networked;
  - output records lifecycle-audit path/hash/file hash and local lifecycle
    status, plus connector, credential-vault, network policy, and runtime
    ingest boundary reference path/hash/file hash, plus Phase 1 safety boundary
    reference path/hash/file hash when supplied;
  - output always keeps `production_provider_execution_ready=false`;
  - output records concrete blockers including
    `runtime_ingest_disabled_by_boundary`, and
    `phase1_runtime_safety_truth_mutation_forbidden`;
  - output includes `live_provider_connector_not_implemented` only when no
    valid digest-only connector reference artifact is supplied;
  - output includes `credential_vault_not_integrated` only when no valid
    digest-only credential-vault reference artifact is supplied;
  - output includes `network_execution_disabled_by_local_contract` only when no
    valid digest-only network policy reference artifact is supplied;
  - output records `live_provider_connector_reference_present=true|false`,
    `credential_vault_reference_present=true|false`,
    `network_policy_reference_present=true|false`, and
    `runtime_ingest_boundary_reference_present=true|false`, and
    `phase1_safety_boundary_reference_present=true|false` while still keeping
    `may_load_credentials=false`, `may_open_network_transport=false`,
    `may_runtime_ingest=false`,
    `may_mutate_phase1_runtime_safety_truth=false`, and
    `may_call_safety_api=false`;
  - local evidence completeness is recorded but does not authorize production
    provider execution;
  - output records `transport_mode=executor_production_readiness_gate_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the gate does not bind an executor, expose credentials, generate request
    bodies, fetch provider data, mutate outbox/inbox files, remote upload,
    runtime ingest, or call `/safety/*`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.605: Live Provider Credential Vault Reference Contract

- Status: implemented for local Apple HealthKit/Garmin credential-vault
  reference artifacts.
- `python -m scout_energy_reserve provider-live-credential-vault-reference`
  writes a local credential-vault reference artifact without loading credential
  values or opening network transport.
- `POST /admin/wearables/provider-live-credential-vault-reference` exposes the
  same local artifact from the admin surface.
- Acceptance:
  - provider is limited to `apple_healthkit_live` or `garmin_health_api_live`;
  - explicit consent, vault ref, account ref, token ref, scope list, and
    capability list are required;
  - vault/account/token/device refs are represented only by sha256 digests;
  - output records `credential_values_loaded=false`,
    `credential_values_exposed=false`, `vault_lookup_performed=false`, and
    `vault_write_performed=false`;
  - output records `transport_mode=credential_vault_reference_only`,
    `network_request_performed=false`, `network_sync_performed=false`,
    `remote_upload_allowed=false`, `remote_upload_performed=false`,
    `real_provider_api_called=false`, and `runtime_ingest_performed=false`;
  - the production readiness gate can consume this artifact and mark
    `credential_vault_reference_present=true`, which removes only
    `credential_vault_not_integrated` from blockers;
  - production readiness remains blocked by connector, network, runtime ingest,
    and Phase 1 safety-truth mutation boundaries;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.606: Live Provider Connector Reference Contract

- Status: implemented for local Apple HealthKit/Garmin connector reference
  artifacts.
- `python -m scout_energy_reserve provider-live-connector-reference` writes a
  local connector reference artifact without starting a connector, performing a
  health check, loading credentials, or opening network transport.
- `POST /admin/wearables/provider-live-connector-reference` exposes the same
  local artifact from the admin surface.
- Acceptance:
  - provider is limited to `apple_healthkit_live` or `garmin_health_api_live`;
  - connector kind must match the provider:
    `apple_healthkit_local_bridge_connector` for Apple HealthKit or
    `garmin_health_api_connector` for Garmin Health API;
  - explicit consent, connector ref, connector version, and capability list are
    required;
  - connector refs and optional connector-binary refs are represented only by
    sha256 digests;
  - output records `connector_process_started=false`,
    `connector_health_check_performed=false`,
    `connector_live_request_performed=false`,
    `connector_execution_bound=false`, `credential_values_loaded=false`, and
    `credential_values_exposed=false`;
  - output records `transport_mode=connector_reference_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - the production readiness gate can consume this artifact and mark
    `live_provider_connector_reference_present=true`, which removes only
    `live_provider_connector_not_implemented` from blockers;
  - production readiness remains blocked by network execution, runtime ingest,
    and Phase 1 safety-truth mutation boundaries;
  - credentials, request bodies, raw provider responses, connector refs,
    token/account/device refs, medical diagnosis, Phase 1 runtime safety truth,
    `/safety/*` calls, remote upload, network sync, live provider calls, raw
    tracks, exact timestamps, and runtime ingest remain excluded.

### Slice 17.607: Live Provider Network Policy Reference Contract

- Status: implemented for local Apple HealthKit/Garmin network policy
  reference artifacts.
- `python -m scout_energy_reserve provider-live-network-policy-reference`
  writes a local network policy reference artifact without DNS lookup, socket
  open, TLS handshake, HTTP request, provider API call, remote upload, or
  runtime ingest.
- `POST /admin/wearables/provider-live-network-policy-reference` exposes the
  same local artifact from the admin surface.
- Acceptance:
  - provider is limited to `apple_healthkit_live` or `garmin_health_api_live`;
  - explicit consent, network policy ref, endpoint ref, and capability list are
    required;
  - policy, endpoint, egress-profile, and TLS-profile refs are represented only
    by sha256 digests;
  - output records `dns_lookup_performed=false`,
    `network_socket_opened=false`, `tls_handshake_performed=false`,
    `http_request_performed=false`, `network_request_performed=false`,
    `real_provider_api_called=false`, `remote_upload_performed=false`, and
    `runtime_ingest_performed=false`;
  - output records `transport_mode=network_policy_reference_only`,
    `request_executor_bound=false`, `network_sync_performed=false`,
    `remote_upload_allowed=false`, and `raw_response_committed=false`;
  - the production readiness gate can consume this artifact and mark
    `network_policy_reference_present=true`, which removes only
    `network_execution_disabled_by_local_contract` from blockers;
  - production readiness remains blocked by runtime ingest and Phase 1
    safety-truth mutation boundaries;
  - credentials, request bodies, raw provider responses, network endpoint refs,
    connector refs, token/account/device refs, medical diagnosis, Phase 1
    runtime safety truth, `/safety/*` calls, remote upload, network sync, live
    provider calls, raw tracks, exact timestamps, and runtime ingest remain
    excluded.

### Slice 17.608: Runtime Ingest Boundary Reference Contract

- Status: implemented for local Apple HealthKit/Garmin runtime ingest boundary
  reference artifacts.
- `python -m scout_energy_reserve provider-live-runtime-ingest-boundary-reference`
  writes a local runtime-boundary reference artifact without runtime ingest,
  runtime writes, Phase 1 safety state mutation, Phase 1 runtime safety truth,
  `/safety/*` calls, network calls, provider calls, or medical diagnosis.
- `POST /admin/wearables/provider-live-runtime-ingest-boundary-reference`
  exposes the same local artifact from the admin surface.
- Acceptance:
  - provider is limited to `apple_healthkit_live` or `garmin_health_api_live`;
  - explicit consent, runtime boundary ref, runtime channel ref, and allowed
    artifact kinds are required;
  - runtime boundary and runtime channel refs are represented only by sha256
    digests;
  - output records `handoff_mode=post_analysis_reference_only` or
    `handoff_mode=advisory_energy_reference_only`;
  - output records `runtime_ingest_authorized=false`,
    `runtime_ingest_performed=false`, `runtime_write_performed=false`,
    `phase1_runtime_mutated=false`, `phase1_runtime_safety_truth=false`,
    `phase1_safety_state_mutation_allowed=false`, `safety_api_called=false`,
    and `medical_diagnosis=false`;
  - output records `transport_mode=runtime_ingest_boundary_reference_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `raw_response_committed=false`;
  - the production readiness gate can consume this artifact and mark
    `runtime_ingest_boundary_reference_present=true`, but it does not remove
    `runtime_ingest_disabled_by_boundary` or
    `phase1_runtime_safety_truth_mutation_forbidden`;
  - production readiness remains blocked by runtime ingest and Phase 1
    safety-truth mutation boundaries;
  - credentials, request bodies, raw provider responses, runtime channel refs,
    connector refs, token/account/device refs, medical diagnosis, Phase 1
    runtime safety truth, `/safety/*` calls, remote upload, network sync, live
    provider calls, raw tracks, exact timestamps, and runtime ingest remain
    excluded.

### Slice 17.609: Phase 1 Safety Boundary Reference Contract

- Status: implemented for local Apple HealthKit/Garmin Phase 1 safety boundary
  reference artifacts.
- `python -m scout_energy_reserve provider-live-phase1-safety-boundary-reference`
  writes a local Phase 1 boundary reference artifact without Phase 1 L0-L4
  state mutation, Phase 1 runtime safety truth, `/safety/*` calls, runtime
  ingest, network calls, provider calls, provider truth promotion, or medical
  diagnosis.
- `POST /admin/wearables/provider-live-phase1-safety-boundary-reference`
  exposes the same local artifact from the admin surface.
- Acceptance:
  - provider is limited to `apple_healthkit_live` or
    `garmin_health_api_live`;
  - explicit consent, Phase 1 boundary ref, Phase 1 state ref, advisory channel
    ref, and allowed artifact kinds are required;
  - Phase 1 boundary, Phase 1 state, and advisory channel refs are represented
    only by sha256 digests;
  - output records `handoff_mode=advisory_reference_only`,
    `handoff_mode=post_analysis_reference_only`, or
    `handoff_mode=advisory_energy_reference_only`;
  - output records `advisory_only=true`, `not_safety_truth=true`,
    `phase1_runtime_safety_truth=false`, `phase1_runtime_mutated=false`,
    `phase1_l0_l4_state_mutated=false`,
    `phase1_safety_state_mutation_allowed=false`, `safety_api_called=false`,
    `runtime_ingest_performed=false`,
    `provider_values_are_scout_truth=false`, and
    `medical_diagnosis=false`;
  - output records
    `transport_mode=phase1_safety_boundary_reference_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`,
    `runtime_ingest_performed=false`, and `raw_response_committed=false`;
  - the production readiness gate can consume this artifact and mark
    `phase1_safety_boundary_reference_present=true`, but it does not remove
    `runtime_ingest_disabled_by_boundary` or
    `phase1_runtime_safety_truth_mutation_forbidden`;
  - production readiness remains blocked by runtime ingest and Phase 1
    safety-truth mutation boundaries;
  - credentials, request bodies, raw provider responses, Phase 1 boundary refs,
    Phase 1 state refs, advisory channel refs, connector refs,
    token/account/device refs, medical diagnosis, Phase 1 runtime safety truth,
    `/safety/*` calls, Phase 1 L0-L4 state mutation, provider truth promotion,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.58: Live Provider Executor Response Consumption Contract

- Status: implemented for local Apple HealthKit/Garmin executor response
  manifest artifacts consumed through the local Energy Reserve pipeline.
- `python -m scout_energy_reserve provider-live-consume-executor-response`
  consumes a `scout_wearable_provider_live_executor_response_manifest` artifact
  through response admission, materialization, local sync-package generation,
  and Energy Reserve artifact generation.
- `POST /admin/wearables/provider-live-consume-executor-response` exposes the
  same local contract from the admin surface.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_response_manifest` artifact
    is required;
  - response-manifest admission rechecks the handoff sha256 and response
    payload sha256 before sanitization;
  - the output artifact records admission, materialization, sync-package, and
    Energy Reserve artifact summaries plus artifact paths;
  - output records `transport_mode=executor_response_consumption_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - credentials, request bodies, raw provider responses, token/account/device
    refs, medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

### Slice 17.6: Live Provider Executor Fixture Replay Contract

- Status: implemented for local Apple HealthKit/Garmin request-plan and
  executor-registration artifacts replayed against local provider response
  fixtures.
- `python -m scout_energy_reserve provider-live-fixture-replay` writes a
  `scout_wearable_provider_live_executor_fixture_replay` artifact.
- `POST /admin/wearables/provider-live-fixture-replay` writes the same artifact
  under the local wearable outputs directory.
- Acceptance:
  - valid `scout_wearable_provider_live_transport_request_plan` and
    `scout_wearable_provider_live_executor_registration` artifacts are required;
  - the artifact represents the future executor output boundary before response
    admission;
  - response fixtures are referenced only by source path and sha256, with
    `raw_response_embedded=false` and `request_body_exposed=false`;
  - output records `transport_mode=executor_fixture_replay_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - raw provider responses, credential values, token/account/device refs,
    medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls, remote
    upload, network sync, live provider calls, raw tracks, exact timestamps, and
    runtime ingest remain excluded.

### Slice 17.65: Live Provider Replay Admission Contract

- Status: implemented for local Apple HealthKit/Garmin executor fixture-replay
  artifacts admitted into the sanitized-import path.
- `python -m scout_energy_reserve provider-live-replay-admit` writes a
  `scout_wearable_provider_live_transport_response_admission` artifact from a
  valid fixture-replay artifact.
- `POST /admin/wearables/provider-live-replay-admit` writes the same artifact
  and sanitized imports under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_executor_fixture_replay` artifact is
    required;
  - response fixture sha256 is checked before admission;
  - admission uses the request-plan path and response-fixture reference from the
    replay artifact;
  - output records `transport_mode=executor_replay_admission_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - raw provider responses, credential values, token/account/device refs,
    medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls, remote
    upload, network sync, live provider calls, raw tracks, exact timestamps, and
    runtime ingest remain excluded.

### Slice 17.75: Live Provider Executor Rehearsal Contract

- Status: implemented for local Apple HealthKit/Garmin request-plan and
  executor-registration artifacts rehearsed against local provider response
  fixtures.
- `python -m scout_energy_reserve provider-live-rehearse-executor` runs the
  local rehearsal from registered readiness through fixture replay,
  replay-admission,
  materialization, sync-package, and Energy Reserve artifact generation.
- `POST /admin/wearables/provider-live-rehearse-executor` runs the same
  rehearsal under the local wearable outputs directory.
- Acceptance:
  - valid `scout_wearable_provider_live_transport_request_plan` and
    `scout_wearable_provider_live_executor_registration` artifacts are required;
  - readiness must have local executor registration and must not include the
    missing-executor blocker;
  - the rehearsal uses a local response fixture only, then writes fixture
    replay, replay-admission, materialization, sync-package, baseline,
    explanation, and companion capsule artifacts;
  - output records `transport_mode=executor_rehearsal_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - raw provider responses, credential values, token/account/device refs,
    medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls, remote
    upload, network sync, live provider calls, raw tracks, exact timestamps, and
    runtime ingest remain excluded.

### Slice 18: Live Provider Response-Admission Contract

- Status: implemented for local Apple HealthKit and Garmin response fixtures
  admitted through a validated request-plan artifact.
- `python -m scout_energy_reserve provider-live-response-admit` writes a
  `scout_wearable_provider_live_transport_response_admission` artifact and
  sanitized import envelopes from a local response fixture.
- `POST /admin/wearables/provider-live-response-admit` writes the same artifact
  and sanitized imports under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_request_plan` artifact is
    required;
  - only capabilities present in the request plan can admit a response fixture;
  - response admission requires `activity_summary_import` before writing
    sanitized activity imports;
  - raw provider response fields are sanitized by the existing provider API
    fixture importer and are not embedded in the admission artifact;
  - output records `transport_mode=response_fixture_admission_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `real_provider_api_called=false`, and `runtime_ingest_performed=false`;
  - raw provider responses, token/account/device refs, exact timestamps,
    `/safety/*` calls, and Phase 1 mutation remain excluded.

### Slice 19: Live Provider Materialization Contract

- Status: implemented for local Apple HealthKit and Garmin response admissions
  materialized into provider-neutral wearable activity summaries.
- `python -m scout_energy_reserve provider-live-materialize` writes a
  `scout_wearable_provider_live_transport_materialization` artifact and
  normalized `WearableActivitySummary` files from admitted sanitized imports.
- `POST /admin/wearables/provider-live-materialize` writes the same artifact and
  normalized summaries under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_response_admission` artifact
    is required;
  - only sanitized imports recorded by the admission artifact are normalized;
  - output normalized summaries validate against the provider-neutral wearable
    summary contract;
  - output records `transport_mode=materialization_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `real_provider_api_called=false`, and `runtime_ingest_performed=false`;
  - raw provider responses, raw request bodies, token/account/device refs,
    exact timestamps, `/safety/*` calls, Phase 1 mutation, and runtime ingest
    remain excluded.

### Slice 20: Live Provider Local Sync Package Contract

- Status: implemented for local Apple HealthKit and Garmin materialization
  artifacts wrapped into a provider live sync-package manifest.
- `python -m scout_energy_reserve provider-live-sync-package` writes a
  `scout_wearable_provider_live_transport_sync_package` artifact from an
  existing materialization artifact.
- `POST /admin/wearables/provider-live-sync-package` writes the same package
  under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_materialization` artifact is
    required;
  - every referenced normalized summary is revalidated against the
    provider-neutral wearable activity summary contract;
  - the package contains only summary references, activity/date-level summary
    fields, validation results, data quality, privacy, boundary, and source
    digests;
  - output records `transport_mode=local_sync_package_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - raw provider responses, token/account/device refs, raw tracks, exact
    timestamps, `/safety/*` calls, Phase 1 mutation, remote upload, network
    sync, and runtime ingest remain excluded.

### Slice 21: Provider Sync Package Energy Build Contract

- Status: implemented for local provider sync-package artifacts consumed as the
  input to Energy Reserve, explanation, and companion capsule generation.
- `python -m scout_energy_reserve provider-live-build-energy` builds the same
  local artifacts as the provider-neutral `build` command, using normalized
  summaries referenced by a provider sync package.
- `POST /admin/wearables/provider-live-build-energy` builds the same artifacts
  under the local wearable outputs directory.
- Acceptance:
  - a valid `scout_wearable_provider_live_transport_sync_package` artifact is
    required;
  - every referenced normalized summary must have `valid=true` in the package
    and still load through the provider-neutral wearable activity summary
    contract;
  - output includes baseline, explanation, and companion capsule artifact paths;
  - output records `transport_mode=local_sync_package_energy_build_only`,
    `request_executor_bound=false`, `network_request_performed=false`,
    `network_sync_performed=false`, `remote_upload_allowed=false`,
    `remote_upload_performed=false`, `real_provider_api_called=false`, and
    `runtime_ingest_performed=false`;
  - medical diagnosis, Phase 1 runtime safety truth, `/safety/*` calls,
    remote upload, network sync, live provider calls, raw tracks, exact
    timestamps, and runtime ingest remain excluded.

## Testing Strategy

Fixture-backed tests only for initial slices.

Test cases:

- clean activity import with heart-rate series;
- activity import with missing heart-rate intervals;
- Garmin-like body battery values are preserved as provider source values;
- sanitized Apple Health and Garmin adapter envelopes normalize into
  provider-neutral summaries;
- GPX/FIT/TCX file-derived summary envelopes normalize without storing raw
  route geometry;
- local Apple Health XML, Garmin Connect JSON, and GPX/TCX/FIT raw files can be
  summarized into sanitized envelopes without committing raw fixtures or
  embedding raw records, provider payloads, trackpoints, or timestamps;
- local Health Auto Export JSON/GPX ZIP archives can be inspected and expanded
  into sanitized Apple Health summary envelopes; detailed workout routes,
  `heartRateData`, exact timestamps, and `physical_effort` source values remain
  local source material and are not Scout truth;
- FIT files with session summary but no track points can still produce
  sanitized duration, moving time, distance, ascent/descent, and average HR;
- FIT files with lap summary but no track points or session summary can still
  produce sanitized duration, moving time, distance, ascent/descent, and average
  HR;
- local Apple Health XML and Garmin Connect JSON batch exports can be expanded
  into multiple sanitized envelopes for the existing normalization path;
- local Apple Health and Garmin provider export directories/zips can be
  discovered without extracting raw payloads into the workspace;
- Garmin provider export archives can be inspected into a manifest that maps
  supported activity JSON members, unsupported wellness/non-activity members,
  and supported FIT members without embedding raw payloads;
- supported multi-member Garmin activity JSON/FIT archives can be summarized
  into multiple sanitized envelopes;
- offline Garmin Health API and Apple HealthKit-style response fixtures can be
  imported only with explicit consent, redacted token metadata, no raw HealthKit
  type leakage, and no live provider API call;
- route-family profiles are emitted only after a deterministic family has at
  least two activities;
- baseline with acute load above normal produces `watch` or `rest_suggested`;
- post-analysis capability timeline produces a shareable capability vector;
- two similar vectors produce high match score;
- ascent mismatch lowers score with explanation;
- missing HRV does not block matching;
- companion public display is gated until the query capsule has at least three
  local activities;
- local companion pool entries require explicit consent and remain capsule-only;
- local companion pool matching does not upload or publish entries remotely;
- local companion pool exchange packages are manual/local and preserve the same
  capsule-only privacy boundary;
- local companion community publish dry-run requires explicit community consent,
  projects public entries without private owner refs or consent metadata, and
  performs no network request or upload;
- explicit-consent local export writes only coarse capsule/summary evidence;
- generated energy artifacts can be deleted without deleting imported activity
  summaries;
- local Daily/Home overview artifact includes current band, 7/28/90 trend,
  recent-load explanation, and soft cue;
- local Daily/Home preview renders overview-derived trend cards without raw
  sample sharing, medical guidance, or safety truth;
- local mobile handoff packages Daily/Home and companion match review artifacts
  without network sync, mobile runtime authority, raw sample sharing, medical
  guidance, or safety truth;
- live provider transport preflight requires explicit consent, redacts
  account/device/token refs, normalizes Apple/Garmin scopes to coarse labels,
  checks capability flags, and performs no network request, provider API call,
  or runtime ingest;
- live provider request-plan accepts only preflight-approved capabilities,
  produces date-only provider request descriptors, and performs no network
  request, provider API call, runtime ingest, or raw request/response sharing;
- live provider executor-registration stores local executor metadata and
  supported capabilities without loading credentials, binding executors,
  opening network transport, or calling provider APIs;
- live provider executor-readiness reviews request-plan prerequisites and
  records explicit blockers before any future live executor is registered,
  without network/provider/runtime effects;
- live provider executor handoff-package bundles request descriptors and
  executor metadata digests for a future executor without credentials, request
  bodies, provider responses, or network/provider/runtime effects;
- live provider executor fixture-replay writes the future executor output
  boundary from a local response fixture without embedding raw payloads or
  opening network/provider/runtime effects;
- live provider replay-admission consumes executor fixture-replay artifacts into
  sanitized imports without opening network/provider/runtime effects;
- live provider executor-rehearsal runs the registered local pipeline from
  response fixture to Energy Reserve artifacts without network/provider/runtime
  effects;
- local admin endpoints can create preflight and request-plan artifacts without
  exposing token/account/device refs or performing network/provider/runtime
  effects;
- live provider response-admission accepts only request-plan-approved
  capabilities and sanitizes local provider response fixtures without raw
  response sharing, network request, provider API call, or runtime ingest;
- live provider materialization converts admitted sanitized imports into valid
  provider-neutral wearable summaries without opening runtime ingest or live
  transport;
- live provider local sync-package wraps materialized normalized summaries into
  a validated local handoff manifest without remote upload, network sync, live
  transport, runtime ingest, or safety-state mutation;
- provider sync-package Energy Reserve build produces baseline, explanation,
  and companion capsule artifacts from the local package without remote upload,
  network sync, live transport, runtime ingest, or safety-state mutation;
- sanitized field observations produce advisory-only field cue and voice cue
  artifacts;
- local stream-admission dry-run can batch sanitized observations into cue
  artifacts without network or runtime ingest;
- local Apple/Garmin live-like frame fixtures can be normalized into sanitized
  field observations and then admitted through stream dry-run without raw
  timestamp, token, provider-field, network, runtime, or safety-state leakage;
- privacy capsule excludes raw GPX, exact timestamps, and raw health samples.

Browser tests later:

- `/admin` renders reserve trend and capability vector preview;
- `/admin/pretrip` renders companion match preview when enabled;
- field cue log appears in `/admin/debug` as advisory-only evidence.

## Privacy And Consent

Always:

- store raw wearable imports locally by default;
- share only coarse capsules unless user explicitly exports more;
- include confidence and limitations;
- let users delete generated baseline, capsule, refresh, and export artifacts;
- separate identity from capability vector.

Ask first:

- public profile publishing;
- matching against a remote/community pool;
- sharing route-family names;
- sharing exact segment times;
- importing provider health APIs that require account authorization.

Never:

- share raw GPX by default;
- share exact timestamps by default;
- expose home/work routines;
- infer medical conditions;
- rank users publicly without consent;
- use body reserve as Phase 1 safety truth.

## Boundaries

Always:

- treat reserve and match as advisory planning/post-analysis evidence;
- preserve source refs and device/provider metadata;
- use personal baseline before population threshold;
- expose uncertainty and data gaps.

Ask first:

- model-assisted fatigue classification;
- account-based social matching;
- live wearable streaming on Scout hardware;
- cloud sync;
- specialist/medical review workflow.

Never:

- make medical recommendations;
- diagnose fatigue, illness, arrhythmia, dehydration, hypoxia, or overtraining;
- call `/safety/*`;
- mutate L0-L4 safety state;
- guarantee team safety from companion match score.

## Success Criteria

- Scout can import wearable activity summaries into a provider-neutral schema.
- Scout can summarize local Apple Health export XML, Garmin Connect JSON, and
  GPX/FIT/TCX files into sanitized wearable import envelopes without storing raw
  health payloads or raw tracks.
- Scout can summarize minimal FIT session-summary files without track points
  into sanitized import envelopes.
- Scout can summarize minimal FIT lap-summary files without track points or
  session summaries into sanitized import envelopes.
- Scout can expand local Apple Health XML and Garmin Connect JSON export batches
  into multiple sanitized envelopes without storing raw health payloads or raw
  tracks.
- Scout can expand local Health Auto Export JSON/GPX ZIP archives into
  sanitized Apple Health summary envelopes without embedding raw route geometry,
  detailed heart-rate samples, exact timestamps, or provider source payloads.
- Scout can discover local Apple Health and Garmin provider export
  directories/zips and summarize supported members without extracting raw
  payloads into the workspace.
- Scout can inspect provider archives into a privacy-preserving manifest before
  import, and can import multiple supported Garmin activity JSON/FIT members
  from one archive.
- Scout can exercise the account-authorized provider API import contract through
  offline Garmin Health and Apple HealthKit-style fixture transports without
  exposing token values or calling a live provider API.
- Scout can write a local live provider transport preflight artifact for Apple
  HealthKit or Garmin before any actual live transport exists, without exposing
  token/account/device refs or performing network/runtime ingest.
- Scout can derive a local live provider request-plan artifact from that
  preflight without binding a request executor, exposing request bodies, calling
  a live provider API, or ingesting runtime data.
- Scout can register local live provider executor metadata without loading
  credentials, binding executors to request plans, or opening network transport.
- Scout can generate a live provider executor-readiness artifact that keeps live
  execution blocked until an explicit future executor is registered.
- Scout can build a local executor handoff package for a future live executor
  without including credentials, request bodies, or provider responses.
- Scout can write a local provider executor fixture-replay artifact that
  represents the future executor output boundary without embedding raw response
  payloads or opening live transport.
- Scout can admit executor fixture-replay artifacts into sanitized imports
  without consuming raw provider responses directly.
- Scout can rehearse the registered local provider executor pipeline from
  response fixture to Energy Reserve artifacts without opening live transport.
- Scout can create the same preflight and request-plan artifacts from local
  admin wearable endpoints without opening live transport.
- Scout can admit local provider response fixtures through a validated request
  plan and produce sanitized imports without binding a request executor or
  opening live transport.
- Scout can materialize admitted sanitized imports into provider-neutral
  wearable summaries without treating them as runtime safety truth.
- Scout can package materialized provider summaries into a local validated
  sync-package manifest without remote upload, network sync, or runtime ingest.
- Scout can build Energy Reserve, explanation, and companion capsule artifacts
  directly from the local provider sync package without remote upload, network
  sync, or runtime ingest.
- Scout can build a local 7/28/90-day energy reserve baseline.
- Scout can convert completed-route Capability Timeline artifacts into a
  privacy-preserving capability vector.
- Scout can score companion similarity across different route histories.
- Scout can build and score a local explicit-consent companion pool using only
  privacy-preserving capability capsules.
- Scout can export/import a manual local companion pool exchange package without
  remote upload or raw data sharing.
- Scout can build a community publish dry-run package from eligible
  explicit-consent pool entries without private owner refs, network transport,
  remote upload, or raw data sharing.
- Match results explain both similarity and mismatch.
- Field cues remain advisory-only and are never Phase 1 safety truth.
- Scout can build deterministic field advisory cue artifacts from sanitized
  local wearable observations without live provider streaming.
- Scout can dry-run wearable stream admission locally before any live provider
  transport is allowed.
- Scout can normalize local Apple/Garmin live-like frame fixtures into sanitized
  field observations for stream-admission dry-run without live provider
  streaming.
- Scout can export coarse local energy/capsule bundles only after explicit local
  consent.
- Scout can delete generated energy artifacts without deleting imported activity
  summaries.
- Scout can build a local Daily/Home overview artifact without live provider
  data or medical language.
- Scout can render a local Daily/Home preview HTML artifact without live
  provider data, medical guidance, raw sample sharing, or Phase 1 safety truth.
- Scout can build a local mobile Energy Reserve / Companion Match handoff
  artifact without network sync, mobile runtime authority, raw sample sharing,
  medical guidance, or Phase 1 safety truth.

## Alpha Slice Evidence

Verified locally on 2026-05-28 with fixture-backed tests only:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_adapters.py -q`
  passed with 6 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_raw_importers.py -q`
  passed with 25 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_energy_reserve.py -q`
  passed with 6 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_companion_match.py -q`
  passed with 14 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_energy_feedback_voice.py -q`
  passed with 4 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_stream_admission.py -q`
  passed with 2 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_live_frames.py -q`
  passed with 4 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_provider_transport.py -q`
  passed with 18 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_energy_admin_pretrip.py -q`
  passed with 10 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_daily_home.py -q`
  passed with 2 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_mobile_handoff.py -q`
  passed with 3 tests.
- Related regression set passed with 126 tests across wearable provider
  transport, wearable adapters, raw importers, energy reserve, companion match,
  pretrip admin, energy feedback voice, wearable validator, admin page, mobile
  handoff, and hardware admin preview coverage.
- Browser smoke rendered `/tmp/scout-daily-home-preview/admin/wearables/outputs/daily_home_preview.html`
  at 390x844 with `Scout Daily`, reserve band, and 3 trend cards visible.
- Boundary grep over the energy/companion Python files found no `/safety/` calls
  and no medical diagnosis or Phase 1 runtime safety truth flags set to true.

## Source Notes

The first implementation should use these as design inputs, not as proof that
Scout can diagnose readiness:

- HRV standards: https://pubmed.ncbi.nlm.nih.gov/8737210/
- Banister-style TRIMP overview: https://www.trainingimpulse.com/banisters-trimp-0
- Session-RPE review: https://pmc.ncbi.nlm.nih.gov/articles/PMC5673663/
- Garmin Body Battery device manual: https://www8.garmin.com/manuals/webhelp/venu/EN-US/GUID-87E1392B-2C55-40B7-A1FF-3AB9252DA0A0.html
- Garmin stress support: https://support.garmin.com/en-US/?faq=WT9BmhjacO4ZpxbCc0EKn9
- Apple HealthKit overview: https://developer.apple.com/documentation/healthkit
- Apple HealthKit workout container: https://developer.apple.com/documentation/healthkit/hkworkout
- Apple HealthKit workout effort relationship: https://developer.apple.com/documentation/healthkit/hkworkouteffortrelationship
- Apple Watch training load support: https://support.apple.com/guide/watch/apde4c07a6cf/watchos
- Apple HealthKit heart-rate data type: https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/heartrate
- Apple Watch measurement accuracy review: https://www.nature.com/articles/s41746-025-02238-1
- Wearable reliability and validity review: https://pmc.ncbi.nlm.nih.gov/articles/PMC7509623/
- Hiking-speed model comparison: https://pmc.ncbi.nlm.nih.gov/articles/PMC10727444/

## Open Questions

- Should the alpha `minimum_activity_count_for_public_match=3` become
  route-family-specific once there is more local history?
- What remote/community pool service design should build on top of the local
  explicit-consent pool contract?
- Should Garmin Body Battery be imported as provider value only, or should Scout
  display it beside Scout Energy Reserve?
- Which first wearable fixture should be used: Apple Health export, Garmin FIT,
  Garmin Health summary JSON, or existing Apple Watch SensorLog?
- Should body reserve influence pretrip readiness as an advisory warning only,
  or remain purely post-analysis until enough validation exists?
- Should `Step Ease` use a 0-100 score, a 1-10 exertion score, or both with one
  hidden behind the other in UI?
- What is the alpha threshold for promoting a composure snapshot into an OLED or
  voice cue without creating alarm fatigue?
