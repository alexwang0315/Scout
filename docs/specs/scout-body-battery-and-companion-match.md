# Spec: Scout Body Battery And Companion Match

## Status

Draft for the next alpha branch.

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

```json
{
  "artifact_kind": "scout_wearable_activity_summary",
  "artifact_version": "wearable_activity_summary.v1",
  "source_provider": "apple_health_export",
  "source_path": "imports/apple_health/workout_2026_05_01.json",
  "sha256": "...",
  "activity_type": "hiking",
  "started_at": "2026-05-01T00:10:00Z",
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
      "route_effort_units_p50": 120.5,
      "moving_time_per_effort_p50": 1.08,
      "heart_rate_load_per_effort_p50": 0.94,
      "late_activity_fatigue_decay_p50": 0.12
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

Proposed import command:

```bash
python -m scout_energy_reserve \
  import-activities \
  --input-dir /data/scout/wearables/imports \
  --output-dir /data/scout/energy/normalized \
  --provider apple_health_export
```

Proposed baseline command:

```bash
python -m scout_energy_reserve \
  build-baseline \
  --activity-dir /data/scout/energy/normalized \
  --capability-timeline-dir /data/scout/post-analysis \
  --output /data/scout/energy/baseline.json \
  --baseline-window-days 90 \
  --acute-window-days 7
```

Proposed companion match command:

```bash
python -m scout_companion_match \
  score \
  --query-capsule /data/scout/energy/capsules/me.json \
  --candidate-capsule /data/scout/energy/capsules/candidate.json \
  --output /data/scout/energy/match-results/candidate.match.json
```

Proposed tests:

```bash
./venv/bin/python -m pytest tests/test_scout_energy_reserve.py
./venv/bin/python -m pytest tests/test_scout_companion_match.py
./venv/bin/python -m pytest tests/test_post_analysis_capability_timeline.py
```

## Project Structure

Planned files:

```text
scout_energy_reserve.py
  CLI and orchestration for wearable import and baseline building.

scout_energy_models.py
  Pydantic models for activity summaries, baseline profiles, reserve trend,
  and field cue evidence.

scout_energy_baseline.py
  Rolling baseline, acute/recent/stable window calculations, and confidence.

scout_companion_match.py
  Capsule vector normalization and companion similarity scoring.

scout_companion_match_models.py
  Capsule, match request, match result, and privacy contracts.

admin_after_action.py
  Read-only projection of reserve and match summaries into post-analysis.

pretrip_admin_view.py
  Optional pretrip projection of reviewed baseline context.

docs/admin/phase1-after-action.html
  Post-analysis body reserve and capability match panels.

docs/admin/phase4-pretrip-planning.html
  Read-only route feasibility and companion match preview.

tests/test_scout_energy_reserve.py
tests/test_scout_companion_match.py
tests/fixtures/wearables/
```

## Implementation Plan

### Slice 1: Spec And Fixture Contract

- Add this spec.
- Define minimal wearable activity summary fixture.
- Define minimal capability capsule fixture.
- Acceptance:
  - fixtures carry privacy and boundary metadata;
  - no raw Apple/Garmin payload is committed.

### Slice 2: Activity Normalization

- Normalize fixture-backed Apple Health/Garmin-like summaries into Scout
  activity summaries.
- Acceptance:
  - heart-rate missingness and confidence are explicit;
  - provider-specific body battery/stress values are passed through as source
    values, not treated as Scout truth.

### Slice 3: Baseline Builder

- Build 7/28/90-day personal baseline.
- Emit `scout_energy_reserve_baseline`.
- Acceptance:
  - baseline is user-local by default;
  - reserve bands are explainable;
  - one outlier does not permanently label the user.

### Slice 4: Capability Vector

- Convert Capability Timeline outputs into companion capability vectors.
- Acceptance:
  - vector excludes raw GPX and exact timestamps;
  - moving time and rest rhythm are represented separately.

### Slice 5: Companion Match Score

- Implement weighted similarity scoring.
- Emit match result with explanation and confidence.
- Acceptance:
  - score is symmetric when weights are symmetric;
  - missing features lower confidence rather than crashing;
  - language stays neutral.

### Slice 6: Admin UI Read-Only Projection

- Show post-analysis reserve trend and match capsule preview.
- Add optional pretrip companion match preview.
- Acceptance:
  - no write endpoints are added;
  - no `/safety/*` calls;
  - privacy exclusions are visible.

### Slice 7: Field Advisory Cue

- Use live wearable observations and route progress to emit advisory fatigue
  cues.
- Acceptance:
  - cues are logged as advisory evidence only;
  - user can silence or dismiss;
  - no Phase 1 safety mutation occurs.

## Testing Strategy

Fixture-backed tests only for initial slices.

Test cases:

- clean activity import with heart-rate series;
- activity import with missing heart-rate intervals;
- Garmin-like body battery values are preserved as provider source values;
- baseline with acute load above normal produces `watch` or `rest_suggested`;
- post-analysis capability timeline produces a shareable capability vector;
- two similar vectors produce high match score;
- ascent mismatch lowers score with explanation;
- missing HRV does not block matching;
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
- let users delete baseline and capsules;
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
- Scout can build a local 7/28/90-day energy reserve baseline.
- Scout can convert completed-route Capability Timeline artifacts into a
  privacy-preserving capability vector.
- Scout can score companion similarity across different route histories.
- Match results explain both similarity and mismatch.
- Field cues remain advisory-only and are never Phase 1 safety truth.

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

- What is the minimum activity count before Scout should show companion match?
- Should matching be local-only first, or should a community pool be designed
  immediately with consent and privacy controls?
- Should Garmin Body Battery be imported as provider value only, or should Scout
  display it beside Scout Energy Reserve?
- Which first wearable fixture should be used: Apple Health export, Garmin FIT,
  Garmin Health summary JSON, or existing Apple Watch SensorLog?
- Should body reserve influence pretrip readiness as an advisory warning only,
  or remain purely post-analysis until enough validation exists?
