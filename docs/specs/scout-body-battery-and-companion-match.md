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

Still deferred: live account-authorized Apple/Garmin provider API transport,
production provider archive mapping beyond the local
manifest/multi-Garmin-JSON/FIT-member slice, real remote/community pool
service, broader production FIT coverage beyond the local minimal parser, live
wearable streaming, networked production consumer mobile app integration, and
any medical or Phase 1 safety interpretation.

This spec defines two related but separate capabilities:

- `Scout Energy Reserve`（Scout 體能儲備）: a personal, baseline-relative body
  battery proxy for daily training, post-analysis, and field advisory cues.
- `Companion Capability Match`（同行能力匹配）: an opt-in matching score that helps
  users find hiking partners with similar route rhythm, endurance, rest habits,
  and body-load profile.

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
  -> privacy-preserving companion match score
  -> advisory field rest cues
```

Success means a user can:

- import Apple Watch, Garmin, GPX/FIT/TCX, or Scout runtime activity history;
- build a personal baseline from their own routes and daily training;
- compare new route performance against their own baseline and route effort;
- share a coarse capability profile without raw GPX or exact timestamps;
- find companion candidates with similar walking, climbing, descending, rest,
  and fatigue-decay patterns;
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

### 5. Wearable Data Accuracy Limits

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

### 6. Companion Matching As Similarity, Not Ranking

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
  -> normalized activity history
  -> personal baseline profile
  -> energy reserve trend
  -> companion capability vector
```

These artifacts are user-private by default.

### Pretrip Boundary

Pretrip can read a coarse baseline:

```text
capability vector
  -> route feasibility context
  -> pacing recommendation
  -> companion compatibility
  -> human review
```

It must not automatically reject a route or approve a team.

### Runtime Boundary

Runtime can read live wearable signals for advisory cues:

```text
live wearable observation
  + current route-effort segment
  + personal baseline
  -> advisory fatigue cue
  -> voice/UI suggestion
```

It must not:

- call `/safety/*`;
- mutate L0-L4 safety state;
- mark a checkpoint reached;
- alter MissionGraph progress;
- trigger SOS or outbound messages without explicit operator/SOS flow.

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

### Live Field Input

Potential live inputs:

- heart rate;
- HRV only if device and API support reliable near-real-time access;
- pace/speed;
- movement/stopped state;
- route progress;
- altitude trend;
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
- Scout can discover local Apple Health and Garmin provider export
  directories/zips and summarize supported members without extracting raw
  payloads into the workspace.
- Scout can inspect provider archives into a privacy-preserving manifest before
  import, and can import multiple supported Garmin activity JSON/FIT members
  from one archive.
- Scout can exercise the account-authorized provider API import contract through
  offline Garmin Health and Apple HealthKit-style fixture transports without
  exposing token values or calling a live provider API.
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
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_energy_admin_pretrip.py -q`
  passed with 9 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_wearable_daily_home.py -q`
  passed with 2 tests.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m pytest tests/test_scout_mobile_handoff.py -q`
  passed with 3 tests.
- Related regression set passed with 107 tests across wearable adapters, raw importers, energy reserve, companion
  match, pretrip admin, energy feedback voice, wearable validator, admin page,
  and hardware admin preview coverage.
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
