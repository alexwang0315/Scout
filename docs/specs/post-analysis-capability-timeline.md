# Spec: Post-Analysis Capability Timeline

## Objective

Build a post-analysis（行後分析） feature that turns a completed Scout route into
a **Capability Timeline**（能力時間軸） similar in spirit to a Sunriver-style
route-time diagram（上河式步程圖）, but grounded in the user's actual completed
track and Scout evidence.

The full product loop is defined in
`docs/specs/scout-closed-loop-operating-cycle.md`. This spec owns the
completed-trip analysis portion of that loop: user recorded track ingestion,
moving/rest/elapsed timeline generation, privacy capsule output, and evidence
handoff to Energy Reserve and future pretrip planning.

User-facing guides（一般使用者說明）:
`docs/admin/post-analysis-capability-timeline-user-guide.html`
and `docs/admin/post-analysis-capability-timeline-user-guide.md`

The feature should show two time concepts for each checkpoint-to-checkpoint
segment:

- **elapsed time**（總時間；含休息）: wall-clock time between two checkpoints.
- **moving time**（移動時間；扣除休息）: elapsed time minus detected rest periods.

Moving time is the primary input for **personal climbing capability**（個人登山能力）.
Elapsed time and rest time remain visible as context. This lets a user understand
their real field rhythm, compare it with route-guide times, and optionally share
a coarse **Capability Capsule**（能力膠囊） for finding partners with similar
fitness without exposing raw GPX or exact timestamps.

The visual reference for the first UI slice is:

```text
/Users/alexwang0315/Downloads/G11_hiking.jpg
```

That image is a design reference only. Scout should not copy its graphics or
treat guidebook route times as user capability.

## Assumptions

1. This feature runs only after a safe return, in post-analysis. It is not a
   pretrip estimator and not a Phase 1 runtime safety decision.
2. The actual walked evidence exists after the climb as a completed trip
   recording set, not necessarily as one GPX file. It may include Scout runtime
   capture, one or more user-imported GPX files recorded during that trip, and
   optional teammate/participant GPX files.
3. The completed track can be matched to reviewed checkpoints and segments from
   the pretrip project or the final MissionGraph.
4. The first implementation can use deterministic rest detection rules before
   adding model-assisted classification.
5. Any sharing feature is opt-in and exports coarse capability summaries, not
   raw route traces.
6. Public/reference/golden GPX files used during pretrip planning are not
   capability evidence. They may define route geometry, checkpoints, or guide
   comparisons, but they must not be treated as the user's completed capability.

## Role in Scout Phases

### Phase 1 Runtime Boundary

Phase 1 owns live safety behavior. Capability Timeline must not:

- call `/safety/*`;
- alter L0-L4 safety state;
- rewrite incident packages;
- mutate completed MissionGraph evidence;
- become runtime safety truth.

It may read sealed route observations, checkpoint arrivals, segment capsules,
and after-action evidence.

### Post-Analysis Boundary

Post-analysis owns the completed-run interpretation:

```text
Scout completed trip record
  -> user recorded GPX or Scout runtime track
  -> optional IMU/PDR logs and sealed route observations
  -> checkpoint/segment matching
  -> rest detection
  -> moving-time measurement
  -> capability timeline artifact
  -> optional privacy-preserving share capsule
```

### Generation Timing and Source Boundary

Capability Timeline generation is tied to a completed trip workspace, not to
pretrip route import.

Primary production source:

- Scout-internal completed trip record;
- completed trip recording set containing one or more user-recorded GPX files
  captured during the trip, or a Scout runtime track exported after the trip;
- checkpoint hits, segment capsules, route observations, and optional IMU/PDR
  logs stored with that completed trip.

Supporting sources:

- reviewed checkpoints and segments from the pretrip project or final
  MissionGraph;
- route-guide time entries for comparison only;
- terrain/risk context as post-analysis evidence context only.

Non-sources for capability measurement:

- public/downloaded reference GPX used during pretrip planning;
- golden route GPX used to define the intended route;
- OSM/Overpass geometry;
- route-guide timing tables;
- MCP/CP candidate geometry.

### Completed Trip Recording Set

A long completed climb may not produce one clean GPX. Scout must treat
completed-trip input as a `CompletedTripRecordingSet`:

```text
completed_trip_workspace/recorded/
  manifest.json
  primary_user/
    watch_day1_part1.gpx
    watch_day1_part2.gpx
    phone_day2.gpx
  participants/
    user_alex.gpx
    teammate_a.gpx
    teammate_b.gpx
  scout_runtime/
    runtime_track.jsonl
    imu_pdr_summary.json
```

The manifest should record:

- trip id, source device, participant id, participant role, and recording role;
- GPX path, sha256, point count, trk/trkseg count, time span, and bounds;
- whether the file is `primary_self`, `self_backup`, `teammate_context`,
  `scout_runtime_primary`, or `unknown`;
- privacy level and whether exact timestamps/raw coordinates may be used
  locally;
- per-file data-quality flags: gaps, overlaps, impossible jumps, duplicated
  timestamps, missing elevation, missing time, and day-boundary/resume markers.

Post-analysis must first resolve a `primary capability track` before computing
Capability Timeline. The primary track may be:

- Scout runtime track, if available and marked primary;
- the user's own GPX files merged by time and route continuity;
- a selected participant GPX if the operator explicitly chooses that
  participant as the capability subject.

Other GPX files in the same completed trip remain supporting evidence. They may
help explain team pacing, waiting, route ambiguity, group separation, or
communication/team-care events, but they must not silently contaminate the
primary user's capability score.

Active view policy:

- `/admin` may keep the first alpha UI simple: one active GPX, merged primary
  track, or selected participant is analyzed and displayed at a time.
- This active selection is a lens over the completed trip recording set. It is
  not a storage limit.
- Selecting a GPX for Capability Timeline may copy or point to it as
  `latest_completed_trip.gpx` for compatibility, but the original recording set
  and all participant/source files must remain in the completed trip workspace.
- Switching the active GPX/subject should update the active post-analysis
  artifacts without deleting other files from the trip.
- Alpha admin reads completed GPX files from:
  `SCOUT_DATA_ROOT/post_analysis/completed_trips/chilai_nanhua_day1/recorded/`.
  If this directory is empty, it may fall back to
  `SCOUT_DATA_ROOT/post_analysis/inbox/*.gpx` for compatibility.
- `/admin/post-analysis/completed-trip-recordings` lists the recording set and
  per-file provenance. `/admin/post-analysis/completed-trip-recordings/{id}/select`
  sets one active GPX, writes compatibility artifacts under
  `SCOUT_DATA_ROOT/post_analysis/inbox/latest_completed_trip.gpx`, builds the
  Capability Timeline, and preserves the rest of the recording set.
- Fixture scenarios remain demo material. They may be copied into the recording
  set for alpha validation, but production post-analysis should treat them as
  ordinary completed GPX recordings once they are in Scout storage.

Merging rules:

- preserve GPX `trk` and `trkseg` boundaries as provenance;
- do not draw or analyze artificial straight lines across device-off gaps;
- mark large gaps as `resume_segment` or `recording_gap`, not as walked
  distance;
- when files overlap in time, keep the selected primary source and annotate the
  conflict instead of averaging users together;
- allow the operator to choose the capability subject when multiple user GPX
  files exist;
- keep teammate tracks out of Energy Reserve baseline updates unless that
  teammate is the selected subject.

When a completed trip workspace is opened, Scout should inspect whether the
workspace contains a user recorded GPX or Scout runtime track plus matching
checkpoint/segment definitions:

- if no completed track exists: show `Capability Timeline: no completed user
  track`;
- if the completed track exists and no artifact exists: show `ready to
  generate`;
- if the completed track, IMU/PDR logs, checkpoint definitions, or segment
  evidence are newer than the artifact: show `stale, refresh recommended`;
- if the artifact exists and is current: show it as read-only post-analysis
  evidence.

Generation may be operator-triggered from `/admin` or automatically queued as a
clearly logged post-analysis job after trip close. It must not run silently from
a pretrip importer. It must not be generated from public/reference/golden GPX
unless the fixture or test explicitly labels that GPX as a stand-in completed
track.

### Phase 4 Feedback Loop

Capability results may seed Energy Reserve and future pretrip planning, but
only as reviewed planning evidence:

```text
completed user track
  -> capability timeline
  -> Energy Reserve / Energy Limit feedback
  -> updated personal endurance baseline or limit candidate
  -> future pretrip pacing reference
  -> proposed rest/check-in/energy-aware CP candidates
  -> human review
  -> planning ETA calibration
```

The Energy Reserve link is one-way and evidence-only:

- Capability Timeline can update or adjust the user's baseline-relative
  endurance profile after a completed trip.
- Energy Limit can describe the conservative planning constraints inferred from
  that profile, such as shorter segment targets, earlier turnaround gates, or
  denser rest/check-in points for the next plan.
- Energy Reserve can explain whether the completed trip was easier/harder than
  expected, where fatigue/rest patterns emerged, and whether the next plan
  should include denser rest/check-in points.
- The next pretrip workspace may use this as a source for proposed CP
  adjustments such as rest-area candidates, earlier turnaround check gates,
  additional water/camp stop emphasis, or wider spacing relaxation for users
  whose baseline supports it.

They must not automatically approve a route, recruit partners, guarantee team
safety, or directly rewrite future MissionGraph checkpoints. Any CP or ETA
change remains candidate-only until reviewed.

## Core Concepts

### Capability Timeline（能力時間軸）

A route graph made from completed checkpoint-to-checkpoint segments. Each edge
shows:

- moving time;
- elapsed time;
- rest time;
- distance;
- ascent/descent;
- terrain/risk context when available;
- source evidence and confidence.

For out-and-back or bidirectional sections, the graph can show both directions:

```text
A <── return moving / return elapsed ── B
A ── outbound moving / outbound elapsed ──> B
```

For traverse routes, the graph remains one-way unless the user has actual return
track evidence.

### Rest Interval（休息區間）

A time window where the user is effectively stopped. First-slice deterministic
rule:

```text
speed <= rest_speed_threshold
and distance spread <= rest_radius_m
and duration >= min_rest_duration_s
```

Suggested defaults:

- `rest_speed_threshold`: 0.5 km/h
- `rest_radius_m`: 20 m
- `min_rest_duration_s`: 180 s

The rule must be configurable because forest GPS drift, switchbacks, photo
stops, waiting for teammates, and shelter pauses differ by route.

### Moving Time（移動時間）

For one segment:

```text
moving_time = elapsed_time - rest_time
```

Moving time is a better capability signal than elapsed time because rest time is
affected by meal breaks, weather, photography, water filtering, team waiting,
and safety checks.

### Segment Terrain Profile（區段地形剖面圖）

Each checkpoint-to-checkpoint edge should be able to carry a small terrain
profile preview. The profile is a compact post-analysis evidence view, not a
runtime safety truth. It answers:

```text
How steep, sustained, and exposed was this segment compared with the time spent?
```

The first implementation can generate a small SVG sparkline per segment:

- x-axis: distance along the segment;
- y-axis: elevation in meters;
- background bands: slope class or route risk bucket when available;
- annotations: major climbs, descents, rests, daylight/night portions, and weak
  data sections;
- source: completed user track elevation when reliable, otherwise DEM/DTM
  sampled along the completed track or reviewed route corridor.

The profile should be stored as a generated artifact reference plus a small
decimated sample summary. Do not embed raw DEM/DTM rasters or full-resolution
GPX samples in the shareable timeline artifact.

### Capability Capsule（能力膠囊）

A privacy-preserving share artifact. It should describe the user's performance
at a coarse route-family level without publishing raw GPX, exact timestamps, or
home/work travel patterns.

Example:

```json
{
  "artifact_kind": "post_analysis_capability_capsule",
  "route_family": "nenggao_andongjun",
  "source_scope": "completed_run_summary_only",
  "raw_track_shared": false,
  "exact_timestamps_shared": false,
  "moving_time_min": 510,
  "elapsed_time_min": 650,
  "rest_time_min": 140,
  "distance_km": 14.6,
  "ascent_m": 1320,
  "descent_m": 480,
  "ascent_m_per_hour_moving": 280,
  "terrain_adjusted_level": "moderate_fast",
  "confidence": "medium",
  "limitations": [
    "weather and pack weight not fully normalized",
    "rest detection is rule-based"
  ]
}
```

## Data Model

### Capability Timeline Artifact

```json
{
  "artifact_kind": "post_analysis_capability_timeline",
  "artifact_version": "capability_timeline.v1",
  "case_id": "chilai_nanhua_day1_post_analysis",
  "route_family": "nenggao_andongjun",
  "source_track": {
    "source_id": "actual_walked_track",
    "source_path": "inbox/post_analysis/user_track.gpx",
    "sha256": "..."
  },
  "rest_detection_policy": {
    "rule_version": "rest_detection.v1",
    "rest_speed_threshold_kmh": 0.5,
    "rest_radius_m": 20,
    "min_rest_duration_s": 180
  },
  "nodes": [
    {
      "node_id": "cp.yunhai",
      "label": "雲海保線所",
      "lat": 23.97,
      "lon": 121.22,
      "source_refs": ["mission.checkpoint.cp.yunhai"]
    }
  ],
  "edges": [
    {
      "edge_id": "cp.yunhai_to_cp.tianchi",
      "from_node_id": "cp.yunhai",
      "to_node_id": "cp.tianchi",
      "direction": "outbound",
      "distance_m": 5400,
      "ascent_m": 820,
      "descent_m": 60,
      "elapsed_time_s": 12600,
      "moving_time_s": 10800,
      "rest_time_s": 1800,
      "rest_intervals": ["rest.001", "rest.002"],
      "terrain_profile": {
        "source": "dem_dtm+completed_track",
        "sample_distance_m": 20,
        "profile_svg_ref": "outputs/terrain_profiles/cp.yunhai_to_cp.tianchi.svg",
        "samples": [
          {
            "offset_m": 0,
            "elevation_m": 2200,
            "slope_deg": 4.2,
            "risk_score": 0.18
          },
          {
            "offset_m": 20,
            "elevation_m": 2204,
            "slope_deg": 9.5,
            "risk_score": 0.21
          }
        ],
        "summary": {
          "min_elevation_m": 2200,
          "max_elevation_m": 2920,
          "ascent_m": 820,
          "descent_m": 60,
          "slope_band_counts": {
            "0_10": 12,
            "10_20": 80,
          "20_30": 40,
          "30_40": 12,
          "40_50": 2,
          "50_plus": 0
        },
          "terrain_difficulty_band": "strained"
        }
      },
      "confidence": "medium",
      "source_refs": ["segment_capsule.seg.012", "track_slice.012"]
    }
  ],
  "rest_intervals": [
    {
      "rest_id": "rest.001",
      "start_time": "2026-05-01T03:12:00Z",
      "end_time": "2026-05-01T03:22:00Z",
      "duration_s": 600,
      "lat": 23.98,
      "lon": 121.23,
      "classification": "detected_rest",
      "confidence": "medium"
    }
  ],
  "summary": {
    "elapsed_time_s": 39000,
    "moving_time_s": 30600,
    "rest_time_s": 8400,
    "moving_ratio": 0.785,
    "ascent_m_per_hour_moving": 280
  },
  "boundary": {
    "post_analysis_only": true,
    "phase1_runtime_mutation_allowed": false,
    "raw_track_shared_by_default": false
  }
}
```

### Route-Time Comparison Artifact

Scout can compare the user's moving time against guidebook/reference times, but
the comparison is informational:

```json
{
  "artifact_kind": "post_analysis_route_time_comparison",
  "route_time_source": "G11_hiking_reference_manual_entry",
  "comparison_basis": "moving_time",
  "segments": [
    {
      "edge_id": "cp.yunhai_to_cp.tianchi",
      "guide_time_min": 210,
      "user_moving_time_min": 180,
      "user_elapsed_time_min": 210,
      "delta_vs_guide_moving_min": -30
    }
  ]
}
```

## UI Requirements

### After-Action Admin Surface

The `/admin` after-action page should add a post-analysis tab or panel:

- `Capability Timeline`（能力時間軸）
- `Rest intervals`（休息區間）
- `Share capsule`（分享能力膠囊）

The first visual can be SVG:

```text
[CP A] -- 180m moving / 210m total -- [CP B]
              rest 30m
              ╭───╮
     terrain: ╯   ╰─
```

For bidirectional evidence:

```text
[CP A] == out 180m / 210m == [CP B]
[CP A] == back 160m / 190m == [CP B]
```

Color semantics:

- green/neutral: completed segment with high confidence;
- yellow: rest detection uncertain;
- red/orange: segment had safety incident, weak GPS, or missing evidence;
- gray: reference-only or unmatched guidebook time.

### Detail Pane

Selecting an edge should show:

- segment labels;
- distance/ascent/descent;
- small terrain profile with elevation, slope/risk background, and rest markers;
- moving/elapsed/rest time;
- rest intervals;
- raw source refs;
- confidence and limitations;
- comparison with route-guide/reference time if available.

Profile interactions:

- single-click profile: keep the edge selected;
- double-click segment/timeline card: focus the map to the segment route extent;
- hover/tap sample: show offset, elevation, slope band, and evidence source;
- profile rendering must remain read-only post-analysis evidence.

### Share Preview

Before export, show exactly what will be shared:

- included: route family, coarse total distance/ascent, moving-time capability,
  limitations, confidence;
- excluded by default: raw GPX, exact timestamps, exact coordinates, incident
  package details, private notes.

## Analyzer Requirements

### Inputs

- completed trip record containing a user recorded GPX or Scout runtime track;
- checkpoint/segment definitions from the reviewed pretrip project or final
  MissionGraph;
- optional IMU/PDR logs for confidence, gap, and motion interpretation;
- optional segment capsules and checkpoint arrival evidence;
- optional terrain/risk outputs as post-analysis context;
- optional route-guide time entries;
- optional user metadata if explicitly supplied:
  - pack weight;
  - weather;
  - team size;
  - snow/mud/night condition;
  - self-rated fatigue.

### Processing Steps

1. Resolve completed trip workspace and build the `CompletedTripRecordingSet`
   inventory.
2. Select or derive the primary capability subject and primary completed-track
   source from Scout runtime track or the user's own GPX files.
3. Reject public/reference/golden pretrip GPX as capability source unless it is
   explicitly marked fixture-only stand-in completed evidence.
4. Preserve source-file, track, and track-segment provenance while normalizing
   the primary completed track.
5. Mark recording gaps, resume segments, and overlapping participant tracks
   before slicing.
6. Match track points to checkpoint arrivals.
7. Slice track into checkpoint-to-checkpoint segments.
8. Detect rest intervals.
9. Use IMU/PDR and sealed route observations, when present, to annotate
   confidence and data-quality limitations.
10. Compute elapsed/moving/rest time per segment.
11. Sample terrain per segment from completed-track elevation, DEM/DTM, or a
   reviewed route-corridor terrain artifact.
12. Generate compact terrain profile artifacts and attach profile refs to
    segment edges.
13. Compute capability metrics for the selected subject only.
14. Compare against guide/reference times if available.
15. Produce timeline, recording-set provenance, and share capsule artifacts.

### Confidence Rules

Lower confidence when:

- GPS gaps exist;
- checkpoint matching is ambiguous;
- a segment has fewer than required track points;
- rest intervals overlap weak GPS drift;
- actual route deviates heavily from planned/reference route;
- timestamps are missing or suspicious.

## Capability Metrics

First slice:

- total moving time;
- total elapsed time;
- total rest time;
- moving ratio;
- moving pace min/km;
- ascent meters per moving hour;
- descent meters per moving hour;
- segment terrain profile difficulty band;
- segment-level slowest/fastest relative deltas.

Later slices:

- terrain-adjusted effort score;
- risk-adjusted speed;
- elevation-band performance;
- daylight-constrained terrain-time budget;
- fatigue decay after N hours;
- team waiting detection;
- model-assisted rest classification.

## Privacy and Sharing Boundaries

Always:

- export capability capsule only after explicit user action;
- default to no raw GPX sharing;
- include limitations and confidence;
- keep exact timestamps private by default;
- treat capability as a context signal, not a ranking.

Ask first:

- publishing to a community server;
- attaching the capsule to a public profile;
- sharing route-family names that reveal sensitive plans;
- exporting raw GPX or exact checkpoint times.

Never:

- expose home/work travel traces;
- share incident details without explicit consent;
- use a single route to label a person permanently;
- present capability matching as a safety guarantee;
- feed shared capability directly into Phase 1 runtime safety truth.

## Commands

Proposed CLI:

```bash
python -m post_analysis_capability \
  --case-id chilai_nanhua_day1_post_analysis \
  --completed-track-gpx /data/scout/post-analysis/inbox/user_track.gpx \
  --pretrip-project-root /data/scout/pretrip/workspaces/chilai_nanhua_day1 \
  --output-dir /data/scout/post-analysis/chilai_nanhua_day1/outputs \
  --rest-speed-threshold-kmh 0.5 \
  --rest-radius-m 20 \
  --min-rest-duration-s 180
```

Current fixture-backed completed-track stand-in:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./venv/bin/python -m post_analysis_capability \
  --case-id chilai_nanhua_day1_post_analysis \
  --route-family nenggao_andongjun \
  --completed-track-gpx tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/completed_track.gpx \
  --checkpoint-definitions tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/checkpoints.json \
  --route-time-entries tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/route_time_entries.json \
  --output-dir tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/outputs
```

The current fixture is rebuilt from the user-provided
`/Users/alexwang0315/Downloads/twmap-gpx-yunhai/能高安東軍.gpx.gpx` completed
golden GPX. It keeps a cleaned completed track in the fixture and records the
non-monotonic timestamp fragment cleanup in
`tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/gpx_cleaning_report.json`.
This is post-analysis evidence only and remains outside Phase 1 runtime safety
truth.

This fixture is allowed only because it is explicitly labeled and treated as a
stand-in completed track for tests. The production generator must prefer Scout's
completed trip workspace and user recorded GPX/runtime track, not pretrip
reference GPX or public route downloads.

Completed-trip scenario fixtures:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/generate_completed_trip_gpx_scenarios.py
```

The generator reads the current historical GPX corpus plus golden route from
`/Users/alexwang0315/Downloads/twmap-gpx-yunhai` and writes fixture-only
completed-trip GPX files under
`tests/fixtures/post_analysis/chilai_nanhua_day1_completed_trip_scenarios/`.
The generated manifest and GPX metadata must keep
`fixture_only=true`, `post_analysis_only=true`, and
`runtime_safety_truth=false`.

The scenario set covers:

- `completed_halfway_return.gpx`: abandoned route with same-corridor return.
- `completed_novel_overlap_chain.gpx`: a synthetic route assembled from
  overlapping historical GPX sources without relying on one precedent GPX.
- `completed_delayed_emergency_camp.gpx`: normal route completion after an
  unplanned overnight camp caused by delay.
- `completed_weather_camp_hold.gpx`: multi-day weather hold at camp before
  continuing.
- `completed_normal_golden.gpx`: normal completion of the selected golden
  route with planned camps.

Each scenario is retimed with a fixture fitness profile instead of inheriting
the source GPX timestamps. The timing model records a flat-speed baseline,
ascent/descent time penalties, progress-band speed multipliers, and per-band
moving/rest duration in the generated manifest. This allows Capability Timeline
and Scout Energy Reserve tests to compare different post-analysis fitness
states while still using deterministic fixture input.

Scenario waypoint notes may embed `SCOUT_NOTE_JSON` records in GPX `cmt` and
`extensions/scout_note`. These records are not instructions to execute. They are
completed-trip evidence of what Scout had already recorded at that waypoint:
Ln state results, warning records, skill outcomes, voice cue records, outbound
draft records, provider status records, and Pydantic AI prompts/results. Admin
may replay/render them as `completed_trip_scout_reaction_replay` evidence, but
loading a scenario must not call `/safety/*`, mutate Ln state, run a skill, call
a model, play TTS, send outbound messages, or write Brain facts.

The `/admin` after-action surface may expose these fixtures through an
operator-triggered completed-trip scenario selector. The selector displays the
scenario name and scenario content from the manifest/GPX metadata, copies the
chosen GPX into Scout's post-analysis inbox as the latest completed trip, and
builds Capability Timeline artifacts under Scout data storage. This flow is
only a post-analysis fixture driver: it does not call `/safety/*`, does not
mutate Phase 1 runtime state, and does not write Phase 2 Brain facts.

These fixtures are valid inputs for Capability Timeline regression and admin
post-analysis smoke. They are not a substitute for Scout's production
completed-trip source of truth, which remains the completed user track imported
from Scout's trip workspace.

Proposed tests:

```bash
./venv/bin/python -m pytest tests/test_post_analysis_capability_timeline.py
./venv/bin/python -m pytest tests/test_admin_after_action.py
```

Browser verification:

```bash
SCOUT_DATA_ROOT=/tmp/scout-fusion-data \
SCOUT_PRETRIP_WORKSPACE_ROOT=/tmp/scout-fusion-pretrip-workspaces \
SCOUT_DEBUG_API_ENABLED=1 \
SCOUT_RUNTIME_PROFILE=local-alpha-workspace \
./venv/bin/python -m uvicorn phase4_admin_runtime:create_phase4_admin_runtime_app \
  --factory --host 127.0.0.1 --port 9099
```

Then open:

```text
http://127.0.0.1:9099/admin
```

## Project Structure

Planned files:

```text
post_analysis_capability.py
  CLI and orchestration for capability timeline generation.

post_analysis_capability_models.py
  Pydantic models for timeline, rest intervals, route-time comparison, and
  share capsules.

post_analysis_rest_detection.py
  Deterministic rest interval detection.

post_analysis_route_slicing.py
  Completed-track to checkpoint/segment slicing.

admin_after_action.py
  Read-only projection of capability artifacts into /admin.

docs/admin/phase1-after-action.html
  Capability Timeline panel.

tests/test_post_analysis_capability_timeline.py
  Fixture-backed analyzer tests.

tests/fixtures/post_analysis/
  Small synthetic GPX and expected capability artifacts.
```

## Implementation Plan

### Slice 1: Spec and Fixture Contract

- Add this spec.
- Define minimal synthetic completed GPX fixture with timestamps and rests.
- Define expected `capability_timeline.json`.
- Acceptance:
  - spec is linked from after-action/pretrip docs;
  - fixture shape is small and deterministic.

### Slice 2: Rest Detection and Route Slicing

- Implement deterministic rest detection.
- Match points to checkpoints and slice route into segments.
- Acceptance:
  - rest intervals are detected from synthetic GPX;
  - moving time excludes rest;
  - missing/incomplete timestamps lower confidence, not crash.

### Slice 3: Capability Artifacts

- Emit `capability_timeline.json`.
- Emit `capability_capsule.json`.
- Emit optional CSV summary.
- Acceptance:
  - artifacts include source refs, hashes, policy version, and boundary flags;
  - no raw GPX XML is embedded.

### Slice 4: After-Action Admin Projection

- Load capability artifacts in `admin_after_action.py`.
- Surface them in `/admin` as read-only post-analysis evidence.
- Acceptance:
  - selected timeline edges show source refs and confidence;
  - no mutation endpoints are added.

### Slice 5: SVG Timeline UI

- Add a Sunriver-style timeline panel to `/admin`.
- Show moving/elapsed/rest time per edge.
- Acceptance:
  - browser smoke shows graph, detail selection, and no console errors;
  - UI labels distinguish moving time from elapsed time.

### Slice 6: Share Capsule Preview

- Add read-only preview and export command for capability capsule.
- Acceptance:
  - export requires explicit confirmation;
  - raw GPX and exact timestamps are excluded by default;
  - limitations are visible.

## Testing Strategy

Fixture-backed tests only. No live network.

Test cases:

- clean synthetic route with one rest interval;
- segment with no rest;
- stopped GPS drift inside rest radius;
- slow walking that should not be classified as rest because the radius grows;
- missing timestamp lowers confidence;
- checkpoint match ambiguity lowers confidence;
- share capsule excludes raw GPX and exact timestamps.

Browser tests:

- `/admin` loads Capability Timeline panel;
- selecting a segment updates detail pane;
- share preview displays excluded fields;
- existing map/evidence selection still works.

## Boundaries

Always:

- keep outputs post-analysis only;
- include provenance and rest detection policy;
- show both elapsed and moving time;
- make moving time the capability basis;
- expose rest time as context, not a penalty.

Ask first:

- model-assisted rest classification;
- public sharing or account/profile integration;
- importing third-party guidebook times beyond manually entered fixtures;
- adding a new frontend visualization library.

Never:

- use capability as a live safety decision;
- publish raw GPX by default;
- rank users without consent;
- hide uncertainty;
- treat one completed route as a permanent fitness label.

## Success Criteria

- A completed track can produce a route graph with per-segment elapsed, moving,
  and rest time.
- The graph can display outbound and return timings when both directions exist.
- Moving time is available as a capability metric and share capsule input.
- The share capsule preserves privacy by default.
- `/admin` can render the timeline as read-only post-analysis evidence.
- Focused tests pass without network.

## Open Questions

- Should rest detection default to 3 minutes or 5 minutes for mountain routes?
- Should very slow scrambling be separated from rest by terrain/risk context?
- Should pack weight and weather be manual metadata in the first slice?
- Should sharing be route-family based only, or allow named route segments?
- How should Scout represent team waiting separately from personal rest?
