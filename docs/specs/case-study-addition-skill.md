# Spec: Case Study Addition Skill

## Objective

Build a dedicated Codex skill that turns wilderness incident articles, field reports, rescue writeups, and user-provided case materials into Scout case-study additions without crossing into the active Phase 1 or Phase 2 implementation lines.

The skill exists to preserve the separation between:

- Scout Phase 1 runtime work: route-aware safety black box, mission graph, route progress, incident package, and replay fixtures.
- Scout Phase 2 runtime work: personal safety OS, team replay, remote status, option replay, and admin/read-only evidence surfaces.
- Case-study corpus work: external evidence extraction, design implications, field-case taxonomy, and proposed spec additions.

Success means a future implementation can ingest one or more case sources and produce a reviewable case-study addition package that is evidence-based, source-cited, bounded, and ready for human discussion before any Scout spec or runtime file changes.

## Tech Stack

- Codex skill format: `SKILL.md` plus optional helper scripts and templates.
- Primary output language: Traditional Chinese for Scout discussion artifacts, with stable English identifiers for schema keys.
- First implementation source material: public web URLs and user-pasted text.
- Future source material: local images, OCR transcripts, PDFs, and existing repo field-case fixtures after separate approval.
- Repository target for review artifacts: `docs/case_studies/` or another dedicated case-study directory selected during implementation.
- Repository target for this specification: `docs/specs/case-study-addition-skill.md`.

## Commands

This spec defines the workflow and acceptance criteria only. The implementation commands will be finalized in the task plan after this spec is approved.

Expected verification commands for the future implementation:

```bash
rg -n "case-study|field_case|rescue_message_v1|not_diagnosis" docs/specs docs/case_studies tests
./venv/bin/python -m pytest tests/test_case_study_addition_skill.py -q
```

Expected manual smoke-test shape:

```bash
codex skill run Scout_case-study-addition --source-url "<incident-url>" --output-dir /Users/alexwang0315/scout-fusion/docs/case_studies
codex skill run Scout_case-study-addition --source-text "<pasted-case-material>" --output-dir /Users/alexwang0315/scout-fusion/docs/case_studies
```

The exact invocation may change if the local Codex skill runtime exposes a different interface.

## Project Structure

```text
docs/specs/
  case-study-addition-skill.md          -> this specification

docs/case_studies/
  README.md                             -> future corpus rules and review workflow
  sources/                              -> source index or short source cards, not full copyrighted copies
  drafts/<case_slug>/
    draft.md                            -> generated human-review draft
    sidecar.json                        -> normalized machine-readable extraction
  accepted/                             -> human-approved case-study references

tests/fixtures/case_studies/
  *.txt                                 -> short synthetic or licensed source snippets for tests
  *.json                                -> expected extraction outputs

tests/
  test_case_study_addition_skill.py     -> future workflow/schema tests

~/.codex/skills/Scout_case-study-addition/
  SKILL.md                              -> future reusable Codex skill
  templates/                            -> future output templates
  scripts/                              -> optional helpers for schema validation or markdown generation
```

The case-study corpus must remain separate from `docs/specs/phase-1-trail-black-box.md` and `docs/specs/phase-2-personal-safety-os.md` until a human explicitly approves a spec patch.

The first implementation target is `/Users/alexwang0315/.codex/skills/Scout_case-study-addition/`. The `Scout_` prefix intentionally distinguishes Scout-specific skills from general computer-wide skills, while still making the skill reusable across future Codex sessions.

## Code Style

Case-study additions should use short evidence quotes, source links, and stable schema-like identifiers:

```markdown
## Case: Nanerdan Lost Contact

Source: [健行筆記](https://example.invalid/case)
Evidence quote: "隨後失聯"

### Scout Implication
- Taxonomy: `team_separation_missing_member`
- Proposed spec hook: `rendezvous_plan.missed_hut_checkin`
- Confidence: `reported_fact`
- Boundary: `risk_signal_only`

### Discussion Prompt
Should Scout treat missed hut rendezvous as a team-cohesion event before route deviation is confirmed?
```

Naming conventions:

- Case IDs: lowercase snake case, date or route when available, for example `nanerdan_lost_contact_2025`.
- Taxonomy keys: stable English identifiers, for example `route_blocked_waiting`, `cold_wet_risk`, `injury_at_known_location`.
- Medical and behavioral inference flags must use explicit reliability and boundary labels such as `reported_fact`, `hearsay`, `assumption`, `fictional_test`, `not_diagnosis`, or `requires_human_review`.

## JSON Sidecar Schema v0.1

Each generated draft must include `sidecar.json`. The sidecar is a review and validation artifact, not the final Scout runtime data model.

Initial schema:

```json
{
  "schema_version": "case-study-addition.v0.1",
  "case_id": "nanerdan_lost_contact_2025",
  "case_slug": "nanerdan-lost-contact-2025",
  "status": "draft",
  "created_at": "2026-05-14T00:00:00+08:00",
  "sources": [
    {
      "source_id": "src_001",
      "type": "url",
      "title": "南二段山難當事人自述",
      "url": "https://example.invalid/case",
      "publisher": "健行筆記",
      "published_date": null,
      "accessed_at": "2026-05-14",
      "reliability": "reported_fact"
    }
  ],
  "quotes": [
    {
      "quote_id": "q_001",
      "source_id": "src_001",
      "text": "隨後失聯",
      "reason": "missed rendezvous and lost contact trigger",
      "copyright_check": "short_excerpt"
    }
  ],
  "timeline": [
    {
      "time_ref": "day_2_evening",
      "event": "missed_hut_rendezvous",
      "source_refs": ["q_001"],
      "confidence": "reported_fact"
    }
  ],
  "taxonomy_keys": [
    "team_separation_missing_member",
    "schedule_slip_and_retreat_gate"
  ],
  "scout_implications": [
    {
      "implication_id": "imp_001",
      "phase": "phase_2",
      "hook": "rendezvous_plan.missed_hut_checkin",
      "type": "spec_gap",
      "summary": "Scout should represent planned hut rendezvous as a team-cohesion contract.",
      "source_refs": ["q_001"],
      "confidence": "design_inference"
    }
  ],
  "boundaries": {
    "medical": "not_diagnosis",
    "legal": "no_fault_assignment",
    "rescue": "not_official_sop",
    "phase_change": "requires_human_review"
  },
  "discussion_questions": [
    "Should a missed hut rendezvous open a team-separation event before route deviation is confirmed?"
  ],
  "promotion": {
    "recommended_target": "docs/case_studies/accepted/",
    "phase_1_patch_required": false,
    "phase_2_patch_required": true,
    "fixture_required": false
  }
}
```

Field definitions:

- `schema_version`: sidecar format version so future validation can evolve without breaking older drafts.
- `case_id`: stable machine identifier using lowercase snake case.
- `case_slug`: filesystem-friendly folder name under `docs/case_studies/drafts/`.
- `status`: `draft`, `accepted`, `superseded`, or `rejected`.
- `sources`: provenance records for URLs or pasted text. Each source must include type, title or short description, access date, and reliability label.
- `quotes`: short evidence excerpts tied to a source. These are used for discussion, not full article storage. Each quote must be 100 Unicode characters or fewer, counted with simple character length.
- `timeline`: normalized event sequence. Time can be exact, relative, or unknown, but must not invent precision.
- `taxonomy_keys`: Scout case-study categories used for grouping and retrieval.
- `scout_implications`: proposed design/spec implications. Each implication must name its phase or target surface and distinguish existing support from a true spec gap.
- `boundaries`: explicit guardrails for medical, legal, rescue, and Phase 1/2 promotion risk.
- `discussion_questions`: human-review prompts before any accepted-case or spec promotion.
- `promotion`: suggested next step; this must never apply changes automatically.

Reliability labels:

- `reported_fact`: 事實. Use for statements the source presents as observed or documented facts, such as dates, locations, route names, reported coordinates, official rescue actions, or first-person event claims.
- `hearsay`: 傳聞. Use for claims attributed to other people, comments, community retellings, or unverified secondary reporting.
- `assumption`: 假定. Use for analyst inference, Scout design inference, or a plausible reconstruction that is not directly asserted by the source.
- `fictional_test`: 虛構/測試. Use for synthetic examples, generated fixtures, test snippets, and intentionally fictional scenarios.

`scout_implications.phase` is intentionally free-form in v0.1. The skill should prefer existing values such as `phase_1`, `phase_2`, `field_case_schema`, `admin_ui`, or `future_research`, but validation must not reject new target strings. This keeps the corpus useful when a case points to a new surface that does not yet exist in Scout.

## Scout Mapping Rules

Case-study additions must look for Scout design implications that are easy to miss when the incident is summarized only as "lost", "solo", or "fall".

### Terrain Feature Recognition and Pre-Trip Checkpoints

When a source describes exposed terrain, ridge turns, gullies, cliff bands, scree slopes, slabs, river crossings, scenic viewpoints, photo stops, whiteout-prone terrain, or low-tolerance terrain, the draft must explicitly evaluate whether the case implies a pre-trip planning requirement.

The skill should propose Scout hooks such as:

- `terrain_features.low_tolerance_zone`
- `terrain_features.ridge_turn`
- `terrain_features.scree_or_talus_slope`
- `terrain_features.exposed_pause_zone`
- `terrain_features.scenic_viewpoint`
- `terrain_features.photo_stop_fall_risk`
- `pretrip_checkpoint_plan.required_decision_cp`
- `pretrip_checkpoint_plan.turning_cp`
- `pretrip_checkpoint_plan.no_drift_corridor`

Case-study drafts should ask whether those features should become mandatory `MissionGraph` checkpoints or decision gates. The key rule is that dangerous terrain should be recognized before the trip, not only after the replay shows deviation. Scenic viewpoints and popular photo stops should be treated as planning features when they sit near cliff edges, scree, gullies, exposed ridges, or other low-tolerance terrain, because a user can fall while still near the planned route.

Example Scout implication:

```json
{
  "phase": "phase_1_pretrip_planning",
  "hook": "pretrip_checkpoint_plan.turning_cp",
  "type": "spec_gap",
  "summary": "The route should require a checkpoint at the ridge turn before entering a low-tolerance scree or cliff-adjacent segment.",
  "confidence": "assumption"
}
```

### Historical GPX Corridor Width

Case-study additions must not assume a fixed safe path width such as 5 m for mountain trails. Trail width and usable walking corridors vary by terrain, vegetation, exposure, season, map quality, and GNSS uncertainty.

When the case suggests near-route fall risk or narrow mountain paths, the skill should propose a `historical_gpx_corridor_width` implication:

- collect multiple historical GPX tracks for the same route segment when available;
- fit an empirical corridor from track dispersion, excluding obvious outliers only when the exclusion is documented;
- preserve segment-specific corridor width instead of using one global value;
- separate `observed_track_dispersion_m`, `gnss_uncertainty_m`, `terrain_exposure_buffer_m`, and `safety_decision_margin_m`;
- mark the result as `assumption` or `fictional_test` unless it comes from measured route data.

The case-study output should flag any proposed corridor as a candidate input for a later Phase 1 spec patch, not as an immediate runtime threshold change.

Example Scout implication:

```json
{
  "phase": "phase_1_route_matching",
  "hook": "route_corridor.historical_gpx_fit",
  "type": "spec_gap",
  "summary": "Scout should derive segment-specific tolerated route corridors from historical GPX dispersion instead of assuming a fixed 5 m trail width.",
  "confidence": "assumption"
}
```

### L3+ Precision Navigation Research

Case-study additions involving cliffs, whiteout, ridge turns, narrow paths, or low-tolerance terrain must consider whether normal GPS-only navigation is insufficient. GPS/GNSS should be treated as one sensor, not the sole navigation truth source.

For L3 and higher safety states, the draft should consider a `precision_navigation_mode` implication:

- fuse GNSS/GPS with IMU/PDR when available;
- use route geometry, historical GPX corridor estimates, and terrain features as correction constraints;
- explicitly track drift, heading confidence, and sensor disagreement;
- record when the system cannot determine whether the user is on-route with enough confidence;
- avoid claiming safety-grade precision until research and field validation support it.

The skill should cite research needs rather than inventing performance guarantees. Relevant research themes include GNSS/PDR fusion, map matching, zero-velocity updates, heading correction, and accumulated PDR drift.

Initial research references for future implementation planning:

- Hölzke et al., "Low-complexity online correction and calibration of pedestrian dead reckoning using map matching and GPS" (2019): PDR errors accumulate over time, and map/GPS correction can improve or sometimes degrade accuracy depending on scenario.
- Hsu et al., "Urban Pedestrian Navigation Using Smartphone-Based Dead Reckoning and 3-D Map-Aided GNSS" (IEEE Sensors Journal, 2016): smartphone PDR can be fused with map-aided GNSS through filtering to improve pedestrian positioning in difficult GNSS environments.
- "An Effective GNSS/PDR Fusion Positioning Algorithm on Smartphones for Challenging Scenarios" (Sensors, 2024): smartphone-only GNSS can be unstable in complex environments such as forests, and GNSS/PDR fusion can improve reliability and stability.
- Diaz et al., "Inertial/magnetic sensors based pedestrian dead reckoning by means of multi-sensor fusion" (Information Fusion, 2018): PDR accuracy depends on walking conditions, time, sensor performance, magnetic disturbance, and other factors, with error accumulation as a core limitation.

Example Scout implication:

```json
{
  "phase": "phase_1_navigation_research",
  "hook": "precision_navigation_mode.l3_gnss_imu_pdr_fusion",
  "type": "future_research",
  "summary": "For L3+ low-tolerance terrain, Scout should investigate GNSS + IMU/PDR fusion and route-corridor correction before using precise deviation claims.",
  "confidence": "assumption"
}
```

### Pre-Trip Readiness and Route Workload

Case-study additions may also use non-incident references when they help Scout reason about pre-trip readiness. Training, pacing, nutrition, hydration, sleep, and route workload articles should be treated as policy/reference sources, not as field incidents.

When a source discusses whether a hiker can safely handle a route, the draft should propose Scout hooks such as:

- `pretrip_readiness.fitness_baseline`
- `pretrip_readiness.route_workload`
- `pretrip_readiness.pace_buffer`
- `pretrip_readiness.hydration_margin`
- `pretrip_readiness.nutrition_plan_tested`
- `pretrip_readiness.fatigue_attention_margin`

The skill should separate route workload from medical claims. It may identify readiness warnings such as high mileage, total ascent, pack weight, insufficient pace buffer, untested nutrition, likely hydration margin, poor sleep, or attention decline from fatigue, but it must not diagnose illness or fitness.

RaceON's "百岳練習生" training article is an initial policy/reference source for this class. It supports pre-trip questions such as whether the user's fitness can handle the route, whether the planned pace has enough margin beyond guide time, and whether nutrition/hydration practices have been tested before the major trip.

Example Scout implication:

```json
{
  "phase": "phase_4_pretrip_planning",
  "hook": "pretrip_readiness.fitness_baseline",
  "type": "existing_spec_support",
  "summary": "Scout should compare route workload with user fitness baseline, pace buffer, hydration margin, and tested nutrition before departure.",
  "confidence": "assumption"
}
```

## Testing Strategy

The future implementation should be tested as a document-generation and schema-validation workflow, not as Phase 1 or Phase 2 runtime behavior.

Required test levels:

- Unit tests for extracting a case-study addition from short synthetic source snippets.
- Golden-output tests for taxonomy, source citation, quote-length discipline, and boundary labels.
- Validation tests that generated case-study additions do not directly edit Phase 1/2 specs.
- Validation-script tests for required JSON fields, quote length, source provenance, boundary labels, and forbidden Phase 1/2 edits.
- Negative tests for unsupported source quality, missing URL/provenance, and medical diagnosis overreach.

The test suite must not require live network access. Live browsing can be part of manual research, but committed tests should use local fixtures.

The first implementation must include a local validation script. The script should fail when:

- `sidecar.json` is missing required top-level fields;
- any quote lacks a source reference;
- any quote exceeds 100 Unicode characters counted with simple character length;
- any source lacks provenance;
- medical or rescue implications lack `not_diagnosis`, `risk_signal_only`, `requires_human_review`, or an equivalent boundary label;
- a proposed trail corridor uses a fixed width without documented route evidence or an explicit `fictional_test` label;
- an L3+ precision-navigation implication claims GPS-only precision without naming IMU/PDR fusion, route-corridor correction, or a research-validation boundary;
- generated output attempts to patch Phase 1 or Phase 2 specs directly;
- an implication has no `hook`, target phase, or discussion question.

## Boundaries

- Always: preserve source URL, title, access date, and quote provenance.
- Always: quote only short evidence excerpts and summarize the rest.
- Always: label inference confidence and distinguish source fact from Scout design implication.
- Always: keep generated case-study drafts outside Phase 1/2 specs until human review.
- Always: map each proposed implication to an explicit Scout hook, such as `rescue_message_v1`, `guardian_policy`, `field_actions`, or `cold_wet_risk`.
- Ask first: promoting a draft case study into an accepted case-study reference.
- Ask first: adding a case-study finding into Phase 1 or Phase 2 specs.
- Ask first: creating or modifying runtime fixtures under `tests/fixtures/field_cases/`, `tests/fixtures/phase2/`, or map/route fixture directories.
- Ask first: storing large raw reports, images, SensorLog exports, PDFs, or copyrighted article copies in the repo.
- Never: edit Phase 1 or Phase 2 runtime code as part of case-study addition.
- Never: treat a source article as medical, legal, or rescue authority without labeling it as a source type.
- Never: output a medical diagnosis; use `risk_signal_only` and `requires_human_review`.
- Never: infer fault, blame, or legal responsibility from a case-study source.
- Never: use case-study material to silently change Scout safety thresholds.

## Case Study Addition Workflow

The skill should follow this gated workflow:

1. Source intake
   - First implementation accepts URL and pasted text.
   - OCR transcripts, image-derived text, PDF-derived text, and existing field-case fixtures are future extensions.
   - Record source title, URL/path, publisher, date if available, and access date.
   - Refuse or pause when the source is missing provenance.

2. Evidence extraction
   - Extract a short event timeline.
   - Capture 1-3 short original quotes.
   - Separate direct source facts from analyst interpretation.

3. Scout mapping
   - Map facts to existing or proposed Scout taxonomy keys.
   - Identify whether the issue belongs to Phase 1, Phase 2, field-case schema, admin after-action UI, or future research.
   - Mark the implication as `existing_spec_support`, `spec_gap`, `future_research`, or `out_of_scope`.

4. Boundary review
   - Check quote length and copyright constraints.
   - Check medical, legal, and rescue claims for overreach.
   - Confirm the draft does not modify Phase 1/2 specs directly.

5. Output package
   - Produce a reviewable Markdown draft.
   - Produce a normalized JSON sidecar for tests and later corpus indexing.
   - End with discussion questions for human review.

## Initial Taxonomy Seeds

The first implementation should support the taxonomy surfaced from the current Hiking Biji research pass:

- `lost_after_route_uncertainty`
- `incident_package_for_guardian`
- `schedule_slip_and_retreat_gate`
- `injury_at_known_location`
- `team_separation_missing_member`
- `route_blocked_waiting`
- `condition_deterioration_on_route`
- `rescue_message_v1`
- `field_actions`
- `incident_trigger_taxonomy`
- `cold_wet_risk`
- `on_route_trauma_delayed_rescue`
- `guardian_policy`
- `altitude_symptom_checkin`
- `low_tolerance_terrain`
- `terrain_feature_checkpoint_planning`
- `historical_gpx_corridor_width`
- `near_route_fall_hazard`
- `ridge_turn_missed_or_exposure`
- `descent_attention_risk`
- `exposed_pause_risk`
- `scenic_viewpoint_photo_fall_risk`
- `precision_navigation_l3`
- `gnss_imu_pdr_fusion_research`
- `drone_first_search_handoff`
- `pretrip_fitness_readiness`
- `pace_buffer_required`
- `workload_route_matching`
- `hydration_margin`
- `attention_decline_from_fatigue`
- `nutrition_plan_tested`

These are seeds, not final product APIs. The skill may propose new keys, but each new key must include a short definition and a reason it is not covered by an existing key.

## Success Criteria

- The spec for the case-study addition skill is saved in the repo.
- The spec defines objective, commands, project structure, code style, testing strategy, boundaries, and success criteria.
- The skill workflow keeps case-study additions separate from Phase 1 and Phase 2 implementation tracks.
- The future skill is named `Scout_case-study-addition` and lives under `/Users/alexwang0315/.codex/skills/`.
- Accepted case studies are stored under `docs/case_studies/accepted/` before any Phase 1 or Phase 2 spec patch is proposed.
- The normalized machine-readable sidecar is JSON.
- The first implementation supports URL input and pasted text input.
- Drafts use the expandable folder layout `docs/case_studies/drafts/<case_slug>/draft.md` plus `sidecar.json`.
- The first implementation includes a local validation script for schema, provenance, quote, boundary, and Phase 1/2 isolation checks.
- The workflow requires evidence quotes, source provenance, confidence labels, and human review before spec promotion.
- The workflow explicitly prevents medical diagnosis, blame assignment, and silent safety-threshold changes.
- The workflow requires low-tolerance terrain cases to evaluate pre-trip checkpoint implications, historical-GPX corridor implications, and L3+ precision-navigation research implications when relevant.
- The future implementation can be planned as small tasks without touching more than one track at a time.

## Accepted Decisions

- Skill location: `/Users/alexwang0315/.codex/skills/Scout_case-study-addition/`.
- Skill naming: use the `Scout_` prefix for Scout-specific skills.
- Default output target: `/Users/alexwang0315/scout-fusion/docs/case_studies/`.
- Accepted case-study target: `docs/case_studies/accepted/`.
- Draft layout: `docs/case_studies/drafts/<case_slug>/draft.md` plus `sidecar.json`.
- Phase 1/2 promotion rule: only create a separate spec patch when an accepted case study will change Phase 1 or Phase 2 behavior.
- Normalized sidecar format: JSON.
- First implementation inputs: URL and pasted text.
- First implementation exclusions: no OCR helper, no PDF helper, and no broad browser automation beyond reading a provided URL.
- First implementation validation: required and blocking.
- Reliability labels: `reported_fact`, `hearsay`, `assumption`, and `fictional_test`.
- `scout_implications.phase`: free-form target string.
- Quote validation: each quote must be 100 Unicode characters or fewer, counted with simple character length.

## Remaining Open Questions

- None.
