# Phase 2 Cleanup Review

Scope: read-only review of current Phase 2 modules and focused tests. Phase 1
safety runtime files were not reviewed for changes and should remain untouched.

No blocking Phase 1 safety-runtime issue was found in the reviewed Phase 2
surfaces. The items below are cleanup and hardening findings for follow-up
slices before Phase 2 grows more modules.

## Completed Since Initial Review

The following Phase 2 cleanup and release-readiness slices are now recorded as
complete in the release docs:

- Release notes were added for the Phase 2 v0.1 file-based Brain, artifact
  refs, writeback limits, append-only `ModelInterpretation`, and mock/runtime
  gate scope.
- The forest traverse fixture replay probe was added as the second synthetic
  team-replay fixture, keeping beacon and case-replay claims bounded.
- Fixture-referenced skill manifest coverage was added so fixture skill refs
  must resolve to versioned `skills/scout/*.yaml` manifests.
- Docs validation was refreshed for the release notes, checklist, implementation
  plan, and forbidden local-only paths such as `PdrSample`, `trajectory_map`,
  and `install_skills`.
- The release checklist records the completed focused Phase 2 target set and
  the latest full repository regression result. This review does not change
  those validation numbers.
- Artifact naming enforcement is complete and covered in the current focused
  target set. The docs now treat artifact ID convention wording as release
  scope rather than a remaining cleanup slice.
- Test-hardening is complete for the current Phase 2 release surface: one
  compact demo golden remains, and lower-level coverage now emphasizes behavior
  boundaries over incidental fixture counts and ordered lists.
- Manual-write-policy verification is complete for this release docs refresh.
  The current focused target set covers the explicit write-policy boundary and
  this docs pass does not claim any additional runtime behavior.
- Reference classifier cleanup is complete for the current Phase 2 release
  surface: shared reference classification now distinguishes artifact,
  Brain-node, external, and unknown refs, with focused coverage in
  `tests/test_phase2_refs.py`.
- This release-doc consistency slice records the classifier result, keeps the
  focused validation result unchanged, and keeps local-only dirty exclusions
  explicit.
- Demo-boundary cleanup is now complete for ridge/forest fixture defaults and
  explicit option-replay refs.

## Findings

### P1: Strict Brain reference validation only covers a narrow artifact subset

`BrainFileStore.validate_artifact_refs()` only checks `BrainNode.artifact_refs`
and `Route.source_artifact_refs` in `phase2_brain_store.py` functions
`validate_artifact_refs()` and `_artifact_refs_for()`. The team replay loader
duplicates that same narrow shape in
`phase2_team_replay_store.py` functions `_validate_explicit_artifact_refs()` and
`_explicit_artifact_refs_for()`. Tests currently encode the limitation in
`tests/test_phase2_team_replay_store.py::test_strict_refs_check_only_explicit_artifact_fields`.

This is risky because Phase 2 reference-bearing fields are broader than those
two fields:

- `ObservedFact.evidence`
- `DerivedMeasurement.derived_from`
- `TeamSeparationEvent.evidence_refs`
- `SignalBearingMeasurement.evidence_refs`
- `DecisionOptionSet.input_refs`
- `SkillRunRecord.input_refs` and `output_refs`

The fixture already demonstrates mixed Brain-node and artifact refs in those
fields, for example
`tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json`
uses `measurement.lin_position_freshness.20260513T101200.derived_from` for an
artifact ref and skill-run input refs for both Brain nodes and artifacts.

Suggested cleanup: create one reference-introspection helper that classifies
refs as `artifact`, `brain_node`, or `external`, then make strict validation
explicit about which classes it validates. Keep the current permissive behavior
behind a clearly named mode if fixtures still need mixed refs.

### P1: Demo/default constants make reusable Phase 2 services fixture-coupled

Several reusable functions default to the single ridge-loop fixture IDs and
paths:

- `phase2_case_replay_integration.py` constants `DEFAULT_REMOTE_STATUS_REF`,
  `DEFAULT_OPTION_SET_REF`, `DEFAULT_SEPARATION_EVENT_REF`, and
  `DEFAULT_SKILL_RUN_REFS`
- `phase2_admin_preview.py::build_phase2_admin_preview()`, which imports those
  defaults and also requires `option_sets[0]` for case replay construction
- `phase2_option_replay.py` helpers `_mission()`, `_route()`, `_remote_status()`,
  and `_load_fixture_option_set()`, which hard-code ridge-loop IDs
- `phase2_remote_status_replay.py::TEAM_REPLAY_FIXTURE_PATH` and
  `phase2_team_replay_store.py::DEFAULT_TEAM_REPLAY_FIXTURE_PATH`, which point
  at the same fixture through separate constants

This is acceptable for the v0.1 demo, but it becomes risky coupling if admin
preview, option replay, or case replay are treated as general Phase 2 APIs. A
second Phase 2 fixture could silently exercise the wrong mission, route, remote
status, or option-set IDs.

Suggested cleanup: split demo adapters from reusable builders. Keep ridge-loop
defaults in a `phase2_demo_defaults.py` or fixture-specific module, and require
general APIs to receive mission/case refs explicitly.

### P2: Naming around remote status artifacts is inconsistent

There are two naming schemes for remote-status JSON artifacts:

- Fixture artifact: `artifact.remote_status_json.20260513T100800` in
  `tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json`
- Persisted artifact: `artifact.remote_status.ridge_loop_20260513T100800` from
  `remote_status_store.py::_artifact_id_for()`

The manifest code also distinguishes `remote_status_json_artifacts` by
`ArtifactKind.REMOTE_STATUS_JSON` in `phase2_artifact_manifest.py`, while the
persisted manifest artifact uses `ArtifactKind.OTHER` and metadata role
`phase2_artifact_manifest` in `phase2_artifact_manifest_store.py`.

The distinction may be intentional, but the names mix artifact kind, persisted
origin, and node ID shape. Tests such as
`tests/test_phase2_artifact_manifest.py::test_includes_artifact_uri_and_sha256_when_present`
and `tests/test_phase2_team_replay_demo.py` assert both schemes directly, which
will make later renames expensive.

Suggested cleanup: document and enforce an artifact ID convention. For example,
use metadata to express fixture-vs-generated origin, while IDs consistently use
`artifact.remote_status_json.<mission_or_timestamp>`.

### P2: Duplicate helper patterns are spreading across Phase 2 modules

The same local helper concepts are implemented in multiple places:

- `_load_required()` in `phase2_case_replay_integration.py` and
  `phase2_admin_preview.py`
- `_nodes_of_type()` in `phase2_artifact_manifest.py` and
  `phase2_team_replay_demo.py`
- `_id_token()` in `remote_status_store.py` and `skill_runtime.py`
- `_dedupe()` or `_dedupe_refs()` in `phase2_admin_preview.py`,
  `phase2_option_replay.py`, and `team_cohesion.py`
- artifact-ref extraction in `phase2_brain_store.py` and
  `phase2_team_replay_store.py`

None of these are blocking by themselves, but Phase 2 is adding modules fast and
these helpers encode correctness rules. Divergence would be easy, especially
for ID normalization and reference validation.

Suggested cleanup: create a small `phase2_refs.py` or `phase2_store_utils.py`
for typed loading, ref classification, ID tokenization, and stable dedupe.
Keep domain-specific code in the existing modules.

### P2: Tests over-specify fixture internals instead of behavior boundaries

Several tests assert exact counts, exact fixture IDs, and exact ordered lists
that are incidental to the ridge-loop fixture:

- `tests/test_phase2_artifact_manifest.py::test_builds_deterministic_manifest_from_brain_store_root`
  asserts exact node counts such as `total_nodes == 37`
- `tests/test_phase2_artifact_manifest.py::test_indexes_remote_status_options_skill_runs_and_case_refs`
  asserts the entire manifest case-ref entry
- `tests/test_phase2_admin_preview.py::test_builds_read_only_preview_from_persisted_phase2_brain_data`
  asserts exact option labels and artifact-ref tuples
- `tests/test_phase2_team_replay_demo_golden.py::test_demo_summary_matches_golden_fixture`
  uses a full summary golden

These are useful release snapshots, but brittle as the fixture evolves. They
will flag legitimate fixture expansion as regressions and may push future work
toward editing tests instead of preserving behavior contracts.

Suggested cleanup: keep one golden release snapshot, then convert lower-level
tests to behavior assertions: required sections exist, generated refs resolve,
admin preview is read-only, manifest rebuilds from files, and Phase 2 outputs
do not claim exact beacon position or guaranteed case outcomes.

### P3: Option replay mutates a Pydantic model with an undeclared write policy

`phase2_option_replay.py::_explicitly_ingest_option_set()` uses
`object.__setattr__(option_set, "write_policy", BrainWritePolicy.MANUAL)` before
calling `ingest_brain_node()`. `DecisionOptionSet` does not declare
`write_policy` in `phase2_brain_models.py`, while `phase2_writeback_policy.py`
allows explicit writes through `getattr(node, "write_policy", None)`.

This works as a narrow escape hatch, but it bypasses the model schema and the
extra-field policy. The persisted JSON may not make the write policy visible
because the field is not part of the Pydantic model.

Suggested cleanup: either add an explicit write-policy field to node types that
can be manually persisted, or introduce an ingest-side override object so manual
write permission is not smuggled through model mutation.

## Remaining Phase 2 Sub-Agent Slices

Parallelizable after this docs refresh:

- Release-doc consistency slice: keep release notes, implementation plan, and
  checklist wording aligned after final verification; do not update validation
  numbers unless the matching tests are rerun.

Sequential or coordination-required:

- Reference classifier slice: complete for the current release-doc scope.
  Follow-up work may still broaden validation policy, but docs should no longer
  list the shared classifier itself as an open cleanup item.
- Demo boundary slice: complete for the current Phase 2 v0.1 scope. Ridge-loop
  and forest fixture defaults are centralized, and option replay accepts explicit
  refs without silently scanning for ridge defaults.

## Read-Only Validation Used

Commands used for the original review were limited to `rg`, `find`, `sed`,
`nl`, `test -f`, and `git status --short`. This Slice C refresh is docs-only;
no tests or runtime commands were executed for this edit, and no Phase 1 safety
runtime files were modified.
