from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PHASE4_FOCUSED_SUITE_COMMAND = (
    "/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest "
    "tests/test_pretrip_source_ingest.py "
    "tests/test_pretrip_candidate_generation.py "
    "tests/test_pretrip_geojson_import.py "
    "tests/test_pretrip_map_compiler.py "
    "tests/test_pretrip_terrain_summary.py "
    "tests/test_pretrip_timing_calibration.py "
    "tests/test_pretrip_eta_plan.py "
    "tests/test_pretrip_skill_audit.py "
    "tests/test_pretrip_skill_manifest_catalog.py "
    "tests/test_pretrip_readiness.py "
    "tests/test_pretrip_review_models.py "
    "tests/test_pretrip_review_resolver.py "
    "tests/test_pretrip_review_integration.py "
    "tests/test_pretrip_review_queue.py "
    "tests/test_pretrip_mission_compiler.py "
    "tests/test_pretrip_brain_seed.py "
    "tests/test_pretrip_brain_seed_store.py "
    "tests/test_pretrip_artifact_manifest.py "
    "tests/test_pretrip_remote_summary.py "
    "tests/test_pretrip_route_comparison.py "
    "tests/test_pretrip_poi_readiness.py "
    "tests/test_pretrip_segment_policy.py "
    "tests/test_pretrip_plan_validation.py "
    "tests/test_pretrip_runtime_audit.py "
    "tests/test_pretrip_runtime_handoff_metadata.py "
    "tests/test_pretrip_review_profiles.py "
    "tests/test_pretrip_departure_gate.py "
    "tests/test_pretrip_departure_gate_resolution.py "
    "tests/test_pretrip_final_mission_graph.py "
    "tests/test_pretrip_runtime_handoff.py "
    "tests/test_pretrip_runtime_export.py "
    "tests/test_pretrip_runtime_artifact_resolution.py "
    "tests/test_pretrip_runtime_activation_preflight.py "
    "tests/test_pretrip_runtime_activation_request.py "
    "tests/test_runtime_load_dry_run.py "
    "tests/test_runtime_activation_loader.py "
    "tests/test_runtime_stream_policy.py "
    "tests/test_runtime_observation_envelope.py "
    "tests/test_runtime_input_admission.py "
    "tests/test_safety_observation_admission_api.py "
    "tests/test_server_safety_observation_admission_config.py "
    "tests/test_runtime_stream_transport_api.py "
    "tests/test_runtime_stream_telemetry.py "
    "tests/test_runtime_stream_controls.py "
    "tests/test_runtime_incident_bridge_opt_in.py "
    "tests/test_runtime_incident_bridge_enablement.py "
    "tests/test_runtime_incident_bridge_delivery_ack.py "
    "tests/test_runtime_remote_provider_policy.py "
    "tests/test_runtime_remote_provider_config_preflight.py "
    "tests/test_runtime_remote_provider_payload_composer.py "
    "tests/test_runtime_remote_provider_send_queue.py "
    "tests/test_runtime_remote_provider_live_adapter.py "
    "tests/test_runtime_remote_provider_live_send_cli.py "
    "tests/test_runtime_remote_provider_demo_harness.py "
    "tests/test_runtime_remote_provider_demo_bundle.py "
    "tests/test_runtime_remote_provider_external_demo_bundle.py "
    "tests/test_pretrip_after_action_candidates.py "
    "tests/test_pretrip_resource_plan.py "
    "tests/test_pretrip_weather_daylight.py "
    "tests/test_pretrip_contour_interpretation.py "
    "tests/test_pretrip_departure_bundle.py "
    "tests/test_pretrip_scout260512_fixture.py "
    "tests/test_pretrip_project_matrix.py "
    "tests/test_pretrip_source_registry.py "
    "tests/test_pretrip_implementation_status.py "
    "tests/test_pretrip_decision_register.py "
    "tests/test_pretrip_fixture_hygiene.py "
    "tests/test_admin_map_layers.py "
    "tests/test_admin_local_raster_source.py "
    "tests/test_admin_local_raster_tiles.py "
    "tests/test_admin_basemap_tiles.py "
    "tests/test_admin_tile_cache_builder.py "
    "tests/test_admin_tile_proxy.py "
    "tests/test_admin_weather_overlay.py "
    "tests/test_pretrip_admin_view.py "
    "tests/test_pretrip_admin_page.py "
    "tests/test_pretrip_admin_api.py "
    "tests/test_admin_after_action.py "
    "tests/test_pretrip_review_draft.py "
    "tests/test_pretrip_review_draft_fixture.py "
    "tests/test_pretrip_review_decision_log.py "
    "tests/test_pretrip_review_decision_apply.py "
    "tests/test_pretrip_review_decision_apply_store.py "
    "tests/test_pretrip_review_decision_store.py "
    "tests/test_pretrip_workspace_project.py "
    "tests/test_pretrip_external_import_queue.py "
    "tests/test_pretrip_expert_contribution.py "
    "tests/test_pretrip_expert_contribution_apply_plan.py "
    "tests/test_pretrip_route_note_candidates.py "
    "tests/test_pretrip_route_note_ln_proposals.py "
    "tests/test_pretrip_route_note_review_options.py "
    "tests/test_pretrip_route_note_reviewed_assumptions.py "
    "tests/test_phase4_pretrip_release_check.py"
)
PHASE4_RELEASE_CHECK_COMMAND = (
    "/Users/alexwang0315/scout-fusion/venv/bin/python phase4_pretrip_release_check.py"
)


@dataclass(frozen=True)
class PreTripImplementationStatusManifest:
    manifest_id: str
    phase: str
    schema_version: str
    boundary: dict[str, Any]
    validation_commands: dict[str, str]
    milestones: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary": self.boundary,
            "manifest_id": self.manifest_id,
            "milestones": self.milestones,
            "phase": self.phase,
            "schema_version": self.schema_version,
            "validation_commands": self.validation_commands,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_pretrip_implementation_status_manifest() -> PreTripImplementationStatusManifest:
    return PreTripImplementationStatusManifest(
        manifest_id="pretrip.implementation_status.phase4.v0",
        phase="phase_4_pretrip_planning",
        schema_version="0.1.0",
        boundary={
            "metadata_only": True,
            "runtime_mutation_allowed": False,
            "runtime_export_write_allowed": True,
            "phase1_live_runtime_touched": False,
            "phase2_bridge_touched": False,
            "ui_scope_included": True,
            "ui_scope": "fixture_backed_read_only_admin_preview",
            "notes": [
                "Reference-only status map for Phase 4 implementation tracking.",
                "Minimal UI slice reads project fixtures through admin preview APIs only.",
            "Phase 4 may write immutable runtime export files after handoff, but does not activate live runtime or call safety APIs.",
            "Symbolic route artifacts are resolved through a separate runtime artifact resolution manifest before activation.",
            "Runtime activation preflight validates exported files and route artifacts but still does not activate a live Phase 1 session.",
            "Runtime activation request records operator intent for Phase 1 loading but still performs no runtime load.",
            "Runtime load dry run validates Phase 1 loader inputs with MissionGraphRuntime indexing but does not create SafetyRuntimeSession.",
            "Actual runtime activation may create a SafetyRuntimeSession in loaded_not_observing state, but still does not process observations, call safety APIs, enable incident bridge, or write Phase 2.",
            "Runtime observing start may process one initial observation from the loaded session, but still does not call safety APIs, enable incident bridge, or write Phase 2.",
            "Runtime observation batch processes bounded local observations after observing starts; it is not a continuous sensor stream, hardware control path, safety API, incident bridge, or Phase 2 writeback.",
            "Runtime stream guard records blocked continuous-stream requests until a future stream protocol is defined.",
            "Runtime stream policy now allows /safety after Phase 4.5 handoff by policy, while this slice still creates no endpoint and keeps incident bridge opt-in guarded.",
            "Runtime observation envelopes add signed summary-only metadata for future HTTP push and WebSocket inputs.",
            "Runtime input admission validates signed envelopes against source policy, sequence, dedupe, cadence, and disconnected-buffer rules before any runtime forward.",
            "The safety observation API can now require signed runtime input admission before forwarding a payload into SafetyRuntimeSession.",
            "The main server can opt in to signed safety observation admission through env or secret-file config, and fails closed when enabled without a usable secret.",
            "Incident bridge opt-in guard can mark remote notification enablement ready, but still sends no notification and enables no bridge.",
            "Incident bridge enablement dry run can queue mock outbound messages after guard approval, but still sends no real notification, enables no bridge, and writes no Phase 2.",
            "Mock delivery acknowledgment can mark mock outbound messages delivered, cancelled, or linked to a rerun result, but it does not represent real recipient delivery or real provider cancellation.",
            "Webhook remote provider policy records the first real-provider contract without creating an adapter or sending network requests.",
            "Remote provider config preflight validates endpoint, auth, and recipient secret refs without loading secret values, creating an adapter, or sending network requests.",
            "Remote provider payload composer creates summary-only payload previews and hashes without network sends, secret loading, bridge enablement, or Phase 2 writes.",
            "Remote provider send intent queue records local queued_not_sent audit intent, but still requires a future adapter and manual send authorization before any live provider send.",
            "Webhook live provider adapter can perform an explicitly authorized POST with env, file, or keychain secret refs, while default behavior remains blocked.",
            "Webhook live send operator CLI reads provider config and send-intent artifacts, defaults to blocked, and only sends when all explicit authorization flags are present.",
            "Runtime lifecycle controls write local pause/resume/end/abort records only; they do not process observations, call safety APIs, enable incident bridge, or write Phase 2.",
            "Admin map surfaces share a metadata-backed layer stack: imagery is bottom, OSM and evidence sit in the middle, and API/weather overlays are top.",
            "Local GeoTIFF raster sources can be represented through small metadata manifests for imagery layers without moving raw rasters into repo fixtures.",
            "Local GeoTIFF raster tile pyramids can be planned and cut into ~/.cache/scout-fusion/raster-tiles for offline imagery preview without external network access.",
            "The pretrip admin map renders local raster imagery tiles under the OSM basemap through the shared layer toggle contract.",
            "Admin map surfaces now render real OpenStreetMap raster tile image elements through a bounded Web Mercator tile contract; tile fetches remain browser/local-proxy behavior, not release-check crawler behavior.",
            "Local OSM tile proxy serves existing local cache files or generated offline fallback tiles, and never downloads tiles into repo fixtures.",
            "Hardware tile cache planning uses ~/.cache/scout-fusion/osm-tiles, a 10 GiB default cap, bbox expansion, and zoom 5-20 range metadata; public OSM bulk prefetch remains blocked.",
            "Weather API overlay remains a summary-only top layer backed by fixture/admin API data unless operator env explicitly enables a live provider secret ref.",
            "External webhook demo bundle can prepare operator-provided secret-ref artifacts, but live external send still requires manual endpoint/token/secret configuration.",
            "The local webhook demo harness and demo bundle builder exercise an explicitly authorized localhost-only provider send without external endpoints, Phase 1 incident bridge enablement, or Phase 2 writeback.",
        ],
        },
        validation_commands={
            "phase4_focused_suite": PHASE4_FOCUSED_SUITE_COMMAND,
            "phase4_release_check": PHASE4_RELEASE_CHECK_COMMAND,
        },
        milestones=list(_MILESTONES),
    )


def load_pretrip_implementation_status_fixture(
    path: Path | str = Path("tests/fixtures/pretrip/implementation_status.json"),
) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    current = build_pretrip_implementation_status_manifest().to_dict()
    fixture_ids = {
        milestone.get("milestone")
        for milestone in fixture.get("milestones", [])
        if isinstance(milestone, dict)
    }
    current_ids = {
        milestone.get("milestone")
        for milestone in current.get("milestones", [])
        if isinstance(milestone, dict)
    }
    if fixture_ids != current_ids:
        return current
    return fixture


def _release_check(
    *check_names: str,
    covered: bool = True,
) -> dict[str, Any]:
    return {
        "covered": covered,
        "check_names": list(check_names),
        "commands": ["phase4_focused_suite", "phase4_release_check"] if covered else [],
    }


_MILESTONES: tuple[dict[str, Any], ...] = (
    {
        "milestone": "0",
        "title": "Spec and Fixture Calibration",
        "implementation_status": "implemented",
        "modules": [
            "generate_pretrip_chilai_fixture.py",
            "pretrip_project_matrix.py",
            "pretrip_scout260512_fixture.py",
            "pretrip_source_registry.py",
        ],
        "tests": [
            "tests/test_pretrip_project_matrix.py",
            "tests/test_pretrip_scout260512_fixture.py",
            "tests/test_pretrip_source_registry.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/project_matrix.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
            "tests/fixtures/pretrip/projects/scout_260512_field_regression/project.json",
            "tests/fixtures/pretrip/source_registry/chilai_nanhua_day1_source_registry.json",
        ],
        "release_check_coverage": _release_check(
            "pretrip_project_matrix",
            "pretrip_source_registry",
            "scout260512_pretrip_regression",
        ),
    },
    {
        "milestone": "1",
        "title": "File-Backed Pre-Trip Package",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_models.py",
            "pretrip_readiness.py",
            "pretrip_review_models.py",
            "pretrip_review_resolver.py",
            "pretrip_source_ingest.py",
        ],
        "tests": [
            "tests/test_pretrip_readiness.py",
            "tests/test_pretrip_review_models.py",
            "tests/test_pretrip_review_resolver.py",
            "tests/test_pretrip_source_ingest.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/pretrip_package.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/pretrip_package.reviewed.json",
            "tests/fixtures/pretrip/projects/scout_260512_field_regression/outputs/pretrip_package.json",
        ],
        "release_check_coverage": _release_check(
            "package_status",
            "readiness",
            "chilai_project_refs",
        ),
    },
    {
        "milestone": "2",
        "title": "GPX and GeoJSON Import Adapter",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_candidate_generation.py",
            "pretrip_geojson_import.py",
            "pretrip_map_compiler.py",
            "pretrip_route_comparison.py",
        ],
        "tests": [
            "tests/test_pretrip_candidate_generation.py",
            "tests/test_pretrip_geojson_import.py",
            "tests/test_pretrip_map_compiler.py",
            "tests/test_pretrip_route_comparison.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/checkpoints.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/map_candidates.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/retreat_routes.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/segments.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/route_comparison.json",
        ],
        "release_check_coverage": _release_check(
            "route_comparison",
            "fixture_boundary",
        ),
    },
    {
        "milestone": "2A",
        "title": "Project Evidence Ingest and AI Skill Contract",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_queue.py",
            "pretrip_skill_audit.py",
            "pretrip_skill_manifest_catalog.py",
            "pretrip_source_registry.py",
        ],
        "tests": [
            "tests/test_pretrip_review_integration.py",
            "tests/test_pretrip_review_queue.py",
            "tests/test_pretrip_skill_audit.py",
            "tests/test_pretrip_skill_manifest_catalog.py",
            "tests/test_pretrip_source_registry.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/planning_skill_audit.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/planning_skill_manifest_catalog.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/review_queue_manifest.json",
        ],
        "release_check_coverage": _release_check(
            "planning_skill_audit",
            "planning_skill_manifest_catalog",
            "review_queue_manifest",
        ),
    },
    {
        "milestone": "3",
        "title": "DEM/DTM and Contour Evidence",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_contour_interpretation.py",
            "pretrip_eta_plan.py",
            "pretrip_terrain_summary.py",
            "pretrip_timing_calibration.py",
            "pretrip_weather_daylight.py",
        ],
        "tests": [
            "tests/test_pretrip_contour_interpretation.py",
            "tests/test_pretrip_eta_plan.py",
            "tests/test_pretrip_terrain_summary.py",
            "tests/test_pretrip_timing_calibration.py",
            "tests/test_pretrip_weather_daylight.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/terrain/dtm_coverage_summary.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/terrain/segment_dtm_coverage.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/contour_interpretation_candidates.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/planned_eta.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/timing_measurements.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/weather_daylight_evidence.json",
        ],
        "release_check_coverage": _release_check(
            "dtm_metadata_only",
            "timing_measurements",
            "planned_eta",
            "weather_daylight_evidence",
            "contour_interpretation_candidates",
        ),
    },
    {
        "milestone": "4",
        "title": "MissionGraph Compiler",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_mission_compiler.py",
            "pretrip_poi_readiness.py",
            "pretrip_segment_policy.py",
        ],
        "tests": [
            "tests/test_pretrip_mission_compiler.py",
            "tests/test_pretrip_poi_readiness.py",
            "tests/test_pretrip_segment_policy.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/compiled_mission_graph.candidate.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/compiled_mission_graph.reviewed.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/poi_readiness_candidates.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/segment_policy_candidates.json",
        ],
        "release_check_coverage": _release_check(
            "mission_graphs",
            "poi_readiness_candidates",
            "segment_policy_candidates",
        ),
    },
    {
        "milestone": "5",
        "title": "Phase 2 Brain Seed Export",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_brain_seed.py",
            "pretrip_brain_seed_store.py",
            "pretrip_runtime_audit.py",
        ],
        "tests": [
            "tests/test_pretrip_brain_seed.py",
            "tests/test_pretrip_brain_seed_store.py",
            "tests/test_pretrip_runtime_audit.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/brain_seed_nodes.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/runtime_audit_manifest.json",
        ],
        "release_check_coverage": _release_check(
            "brain_seed",
            "runtime_audit_manifest",
        ),
    },
    {
        "milestone": "6",
        "title": "Admin Preview and Manifest Surfacing",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_artifact_manifest.py",
            "pretrip_departure_bundle.py",
            "pretrip_plan_validation.py",
            "pretrip_remote_summary.py",
            "pretrip_resource_plan.py",
            "pretrip_runtime_handoff_metadata.py",
        ],
        "tests": [
            "tests/test_pretrip_artifact_manifest.py",
            "tests/test_pretrip_departure_bundle.py",
            "tests/test_pretrip_plan_validation.py",
            "tests/test_pretrip_remote_summary.py",
            "tests/test_pretrip_resource_plan.py",
            "tests/test_pretrip_runtime_handoff_metadata.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/departure_bundle_manifest.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/plan_validation_candidates.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/readiness_report.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/remote_contact_summary.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/resource_plan.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/runtime_handoff_metadata.candidate.json",
        ],
        "release_check_coverage": _release_check(
            "artifact_manifest",
            "departure_bundle_manifest",
            "plan_validation_candidates",
            "remote_contact_summary",
            "resource_plan",
            "runtime_handoff_metadata",
        ),
    },
    {
        "milestone": "6A",
        "title": "After-Action to Next-Plan Candidates",
        "implementation_status": "implemented",
        "modules": ["pretrip_after_action_candidates.py"],
        "tests": ["tests/test_pretrip_after_action_candidates.py"],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/after_action_next_plan_candidates.json",
        ],
        "release_check_coverage": _release_check("after_action_next_plan_candidates"),
    },
    {
        "milestone": "7",
        "title": "Minimal Admin UI",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_admin_view.py",
            "pretrip_review_draft.py",
            "pretrip_review_draft_fixture.py",
            "admin_api.py",
            "docs/admin/phase4-pretrip-planning.html",
        ],
        "tests": [
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_review_draft.py",
            "tests/test_pretrip_review_draft_fixture.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_draft_log.json",
        ],
        "release_check_coverage": _release_check(
            "pretrip_admin_ui",
            "review_draft_log",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Read-only fixture-backed admin preview shell.",
            "Review draft actions are append-only fixture artifacts and do not record decisions.",
            "Review/edit toolbar controls are visible but disabled until a later write-path slice.",
        ],
    },
    {
        "milestone": "8",
        "title": "Fixture-Only Review Decisions and External Import Requests",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_decision_log.py",
            "pretrip_external_import_queue.py",
        ],
        "tests": [
            "tests/test_pretrip_review_decision_log.py",
            "tests/test_pretrip_external_import_queue.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_decision_log.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/external_import_queue.json",
        ],
        "release_check_coverage": _release_check(
            "review_decision_log",
            "external_import_queue",
        ),
        "notes": [
            "Review decision log is append-only and fixture-only; it does not mutate packages, runtime, or Brain state.",
            "External import queue models Joyhike/PTT reference requests without network calls, crawler execution, or raw payload storage.",
        ],
    },
    {
        "milestone": "9",
        "title": "Fixture-Backed Admin Decision Write Contract",
        "implementation_status": "implemented",
        "modules": [
            "admin_api.py",
            "pretrip_review_decision_apply.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_review_decision_apply.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/review_decision_apply_plan.json",
        ],
        "release_check_coverage": _release_check(
            "review_decision_apply_plan",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin review decision POST returns a validated preview record without mutating fixture files.",
            "Decision apply plan records what accepted/corrected/rejected decisions point at while keeping package_candidate_apply_count at zero for non-package candidate refs.",
            "No source artifact, package, MissionGraph, Phase 1 runtime, or Phase 2 Brain write is performed.",
        ],
    },
    {
        "milestone": "10",
        "title": "Append-Only Local Review Decision Store",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_decision_store.py",
        ],
        "tests": [
            "tests/test_pretrip_review_decision_store.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_decision_log.json",
        ],
        "release_check_coverage": _release_check(
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Local workspace helper can append one validated review decision to a supplied log path.",
            "Tests use tmp_path copies so the repo fixture remains unchanged.",
            "Store rejects duplicate decisions and source/package/runtime/Phase 1/Phase 2/MissionGraph mutation flags.",
        ],
    },
    {
        "milestone": "11",
        "title": "Optional Local Workspace Decision Persistence",
        "implementation_status": "implemented",
        "modules": [
            "admin_api.py",
            "pretrip_review_decision_apply.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_review_decision_apply.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_decision_log.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/review_decision_apply_plan.json",
        ],
        "release_check_coverage": _release_check(
            "review_decision_apply_plan",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin POST remains preview-only by default.",
            "Optional persistence requires an injected local workspace root and writes only that workspace review log.",
            "Explicit-path apply-plan generation can reflect workspace-appended decisions without mutating packages, MissionGraph, or runtime state.",
        ],
    },
    {
        "milestone": "12",
        "title": "Workspace Review Decision Apply-Plan Writer",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_decision_apply_store.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_review_decision_apply_store.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/review_decision_apply_plan.json",
        ],
        "release_check_coverage": _release_check(
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Workspace apply-plan writer refreshes only a supplied local workspace apply-plan artifact.",
            "Release check explicitly confirms admin persistence remains preview-by-default, workspace-root gated, local-only, and no-network.",
            "Repo fixtures, package outputs, MissionGraph outputs, Phase 1 runtime, and Phase 2 Brain state remain unchanged.",
        ],
    },
    {
        "milestone": "13",
        "title": "Local Workspace Project and Apply-Plan Admin Endpoint",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_workspace_project.py",
            "admin_api.py",
        ],
        "tests": [
            "tests/test_pretrip_workspace_project.py",
            "tests/test_pretrip_admin_api.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Workspace helper copies only JSON/GeoJSON planning metadata and rejects raw route, photo, DTM, or map files.",
            "Admin apply-plan endpoint regenerates only the configured local workspace apply-plan artifact.",
            "Repo fixtures remain unchanged by default and live runtime writes remain out of scope.",
        ],
    },
    {
        "milestone": "14",
        "title": "Admin-Created Metadata Workspace",
        "implementation_status": "implemented",
        "modules": [
            "admin_api.py",
            "pretrip_workspace_project.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_workspace_project.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_workspace_project_creation_contract",
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin-created workspace copies are local metadata-only project copies.",
            "Workspace helper coverage requires RAW_SOURCE_SUFFIXES and copy_pretrip_project_workspace so raw routes, photos, DTM, maps, and binary sources remain out of the copy path.",
            "Admin integration must use the workspace-copy helper, keep repo fixtures immutable by default, and avoid Phase 1 runtime, Phase 2 Brain writeback, crawler, or network behavior.",
        ],
    },
    {
        "milestone": "15",
        "title": "Local Workspace Admin Write Controls",
        "implementation_status": "implemented",
        "modules": [
            "docs/admin/phase4-pretrip-planning.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_page.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_ui_local_workspace_write_controls",
            "admin_workspace_project_creation_contract",
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin UI write controls are limited to local workspace creation, accepted review-decision append, and apply-plan regeneration.",
            "Release coverage statically scans the admin HTML for expected local-workspace route/function tokens when the UI slice is present.",
            "The controls do not write final PreTripPackage, MissionGraph, Phase 1 runtime state, Phase 2 Brain state, crawler output, external import payloads, or repo fixtures.",
        ],
    },
    {
        "milestone": "16",
        "title": "Local Workspace Reject Review Control",
        "implementation_status": "implemented",
        "modules": [
            "docs/admin/phase4-pretrip-planning.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_page.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_ui_local_workspace_write_controls",
            "admin_workspace_project_creation_contract",
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin UI can append rejected review decisions to a configured local workspace.",
            "Rejected decisions remain append-only review records and do not mutate final packages, MissionGraph fixtures, runtime state, or repo fixtures.",
            "Release coverage requires the reject control/function/payload tokens alongside the existing local workspace write controls.",
        ],
    },
    {
        "milestone": "17",
        "title": "Review Decision Duplicate Candidate Guard",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_decision_store.py",
        ],
        "tests": [
            "tests/test_pretrip_review_decision_store.py",
            "tests/test_pretrip_admin_api.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_decision_log.json",
        ],
        "release_check_coverage": _release_check(
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "The append-only review decision store rejects duplicate candidate_ref values.",
            "This prevents a local workspace from recording conflicting accepted/rejected decisions for the same review candidate before an explicit supersession model exists.",
            "The guard is enforced below the admin API so UI behavior is not the only protection.",
        ],
    },
    {
        "milestone": "18",
        "title": "Local Workspace Corrected Review Control",
        "implementation_status": "implemented",
        "modules": [
            "docs/admin/phase4-pretrip-planning.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_page.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_ui_local_workspace_write_controls",
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin UI can append corrected review decisions with structured correction metadata to a configured local workspace.",
            "Corrected decisions require a correction summary and remain append-only planning review records.",
            "Corrected review controls do not mutate final packages, MissionGraph fixtures, runtime state, Phase 2 Brain state, or repo fixtures.",
        ],
    },
    {
        "milestone": "19",
        "title": "Workspace-Aware Admin View Overlay",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_admin_view.py",
            "admin_api.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_workspace_persistence_contract",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin project GET overlays the configured local workspace project copy when it exists.",
            "The overlay is read-only and lets review decision highlighting reflect local workspace decisions after accepted, corrected, or rejected writes.",
            "Missing workspace projects still fall back to repo fixtures, and no repo fixture, final package, MissionGraph, runtime, or Brain state is mutated.",
        ],
    },
    {
        "milestone": "20",
        "title": "Review Decision Correction Detail Exposure",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_admin_view.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_view.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/reviews/review_decision_log.json",
        ],
        "release_check_coverage": _release_check(
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin view review-decision summaries expose corrected decision summaries and compact correction counts.",
            "Correction detail remains summary-only and does not embed source payloads or mutate planning artifacts.",
        ],
    },
    {
        "milestone": "21",
        "title": "Expert Contribution Memory Seed Candidates",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_expert_contribution.py",
            "pretrip_admin_view.py",
            "pretrip_artifact_manifest.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_expert_contribution.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_artifact_manifest.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/expert_contribution_log.json",
        ],
        "release_check_coverage": _release_check(
            "expert_contribution_log",
            "artifact_manifest",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Admin edits to AI-generated candidate sets and external import requests are represented as expert contribution records.",
            "AI assistance proposes memory seed candidates for accepted expert contributions, but this slice performs no Brain writeback.",
            "Contribution records are intent-only until a later reviewed apply path mutates local workspace candidate sets or import queues.",
        ],
    },
    {
        "milestone": "22",
        "title": "GPX Waypoint Route Note Candidates",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_route_note_candidates.py",
            "pretrip_admin_view.py",
            "pretrip_artifact_manifest.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_route_note_candidates.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_artifact_manifest.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/candidates/route_note_candidates.json",
        ],
        "release_check_coverage": _release_check(
            "route_note_candidates",
            "artifact_manifest",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "GPX waypoint name/cmt/desc fields are extracted as review-gated route note candidates.",
            "Route notes can become future Ln expansion inputs after human review, but this slice performs no runtime warning or Brain writeback.",
            "The fixture stores extracted note metadata only and does not version the raw GPX.",
        ],
    },
    {
        "milestone": "23",
        "title": "Route Note Ln Proposal Candidates",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_route_note_ln_proposals.py",
            "pretrip_review_queue.py",
            "pretrip_admin_view.py",
            "pretrip_artifact_manifest.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_route_note_ln_proposals.py",
            "tests/test_pretrip_review_queue.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_artifact_manifest.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/route_note_ln_proposals.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/review_queue_manifest.json",
        ],
        "release_check_coverage": _release_check(
            "route_note_ln_proposals",
            "review_queue_manifest",
            "artifact_manifest",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Potential Ln signals from route notes are projected into candidate-only hint/warning coverage proposals.",
            "Route-note Ln proposals are queued for admin review and do not activate runtime warnings.",
            "The artifact performs no package mutation, MissionGraph compile, Phase 1 runtime mutation, or Phase 2 Brain writeback.",
        ],
    },
    {
        "milestone": "24",
        "title": "Route Note Review Options",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_route_note_review_options.py",
            "pretrip_admin_view.py",
            "pretrip_artifact_manifest.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_route_note_review_options.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_artifact_manifest.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/route_note_review_options.json",
        ],
        "release_check_coverage": _release_check(
            "route_note_review_options",
            "artifact_manifest",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Route-note Ln proposals expose draft-only admin dispositions: promote hint, promote warning, ignore, or field verify.",
            "No disposition is selected or recorded in this artifact.",
            "The artifact does not call review-decision APIs, mutate packages, compile MissionGraph, or write runtime state.",
        ],
    },
    {
        "milestone": "25",
        "title": "Expert Contribution Workspace Apply Plan",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_expert_contribution_apply_plan.py",
            "pretrip_fixture_hygiene.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_expert_contribution_apply_plan.py",
            "tests/test_pretrip_fixture_hygiene.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/expert_contribution_log.json",
        ],
        "release_check_coverage": _release_check(
            "workspace_only_artifact_boundaries",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Expert contribution apply-plan and apply-result artifacts are generated only inside copied local workspaces.",
            "Repo fixtures must not carry outputs/expert_contribution_apply_plan.json or outputs/expert_contribution_workspace_apply_result.json by default.",
            "Workspace application can mutate only copied workspace candidate/import metadata, not source artifacts, packages, MissionGraph outputs, runtime state, or Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "26",
        "title": "Route Note Reviewed Workspace Assumptions",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_route_note_reviewed_assumptions.py",
            "pretrip_fixture_hygiene.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_route_note_reviewed_assumptions.py",
            "tests/test_pretrip_fixture_hygiene.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/route_note_review_options.json",
        ],
        "release_check_coverage": _release_check(
            "workspace_only_artifact_boundaries",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Reviewed route-note assumptions are written only from copied workspace disposition logs.",
            "Repo fixtures must not carry outputs/route_note_reviewed_assumptions.json by default.",
            "Reviewed assumptions remain planning interpretation candidates and do not activate runtime warnings, mutate packages, compile MissionGraph, or write Phase 2 Brain facts.",
        ],
    },
    {
        "milestone": "4.5",
        "title": "Departure Gate and Runtime Handoff Boundary",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_review_profiles.py",
            "pretrip_departure_gate.py",
            "pretrip_runtime_handoff.py",
        ],
        "tests": [
            "tests/test_pretrip_review_profiles.py",
            "tests/test_pretrip_departure_gate.py",
            "tests/test_pretrip_runtime_handoff.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "PlanningReviewProfile models Quick, Guided, and Expedition review friction as data with Chinese semantic labels.",
            "Departure Gate keeps Reviewed Package separate from explicit departure approval and blocks Final MissionGraph generation unless the gate passes.",
            "RuntimeHandoffManifest is metadata-only and does not call Phase 1 safety APIs, mutate live runtime state, or embed raw payloads.",
        ],
    },
    {
        "milestone": "4.5A",
        "title": "Departure Gate Resolution Path",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_departure_gate_resolution.py",
            "pretrip_departure_gate.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_departure_gate_resolution.py",
            "tests/test_pretrip_departure_gate.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "DepartureGateResolutionLog records warning resolutions as append-only local workspace metadata.",
            "Every unresolved warning must have a reviewer reason before a hold gate can become passed.",
            "Hard blockers cannot be resolved by this path; runtime handoff remains a separate explicit step.",
        ],
    },
    {
        "milestone": "4.5B",
        "title": "Final MissionGraph Generation Gate",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_final_mission_graph.py",
            "pretrip_departure_gate_resolution.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_final_mission_graph.py",
            "tests/test_pretrip_departure_gate_resolution.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "FinalMissionGraphArtifact is generated only from a passed Departure Gate with explicit approval metadata.",
            "The final graph sanitizes raw local route references into artifact tokens before export.",
            "Workspace writer is immutable, copied-workspace only, and still does not perform Runtime Handoff or Phase 1 safety mutation.",
        ],
    },
    {
        "milestone": "4.5C",
        "title": "Final MissionGraph Runtime Handoff Link",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_runtime_handoff.py",
            "pretrip_final_mission_graph.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_runtime_handoff.py",
            "tests/test_pretrip_final_mission_graph.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "RuntimeHandoffManifest can now be built from a passed Departure Gate plus FinalMissionGraphArtifact.",
            "The handoff package hash, MissionGraph version, and MissionGraph hash are taken from the final graph artifact rather than caller-supplied dummy metadata.",
            "The workspace writer creates an immutable copied-workspace metadata manifest only; it still does not call live safety APIs or mutate Phase 1 runtime state.",
        ],
    },
    {
        "milestone": "4.5D",
        "title": "Runtime Export Bundle Write Path",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_runtime_export.py",
            "pretrip_runtime_handoff.py",
            "pretrip_final_mission_graph.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_runtime_export.py",
            "tests/test_pretrip_runtime_handoff.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Phase 4 is allowed to write immutable runtime export files in copied workspaces.",
            "The default export status is exported_not_activated: Phase 1 can load the files later, but no live session is changed by export.",
            "The export bundle writes canonical MissionGraph and RuntimeHandoffManifest inputs, while route artifact refs remain symbolic until the runtime target resolves them.",
        ],
    },
    {
        "milestone": "4.5E",
        "title": "Runtime Artifact Resolution Manifest",
        "implementation_status": "implemented",
        "modules": [
            "runtime_artifact_resolution.py",
            "pretrip_runtime_artifact_resolution.py",
            "pretrip_runtime_export.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_runtime_artifact_resolution.py",
            "tests/test_pretrip_runtime_export.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Final MissionGraph keeps route_source as artifact:gpx:* instead of a raw local path.",
            "The resolver manifest maps that symbolic artifact ref to a runtime-target relative route file path.",
            "Phase 1 loaders use the neutral runtime_artifact_resolution.py helper, while Phase 4 owns manifest generation.",
            "Missing required route artifacts block activation; this slice still performs no route payload copy, live activation, safety API call, or Phase 2 writeback.",
        ],
    },
    {
        "milestone": "4.5F",
        "title": "Runtime Activation Preflight",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_runtime_activation_preflight.py",
            "pretrip_runtime_artifact_resolution.py",
            "runtime_artifact_resolution.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_runtime_activation_preflight.py",
            "tests/test_pretrip_runtime_artifact_resolution.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Preflight validates the runtime export files, runtime handoff manifest, artifact resolver manifest, route artifact hash, and GPX parseability.",
            "Activation-ready means inputs are loadable; it is not live activation approval by itself.",
            "When the repo fixture lacks a raw route artifact, release check expects activation_blocked with zero live activation or safety API calls.",
        ],
    },
    {
        "milestone": "4.5G",
        "title": "Runtime Activation Request",
        "implementation_status": "implemented",
        "modules": [
            "pretrip_runtime_activation_request.py",
            "pretrip_runtime_activation_preflight.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_runtime_activation_request.py",
            "tests/test_pretrip_runtime_activation_preflight.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Activation request is built only from activation_ready preflight output.",
            "Blocked preflight cannot create an activation request.",
            "The request is an auditable Phase 1 load intent artifact and still performs no live session activation, safety API call, or Phase 2 writeback.",
        ],
    },
    {
        "milestone": "4.5H",
        "title": "Runtime Load Dry Run",
        "implementation_status": "implemented",
        "modules": [
            "runtime_load_dry_run.py",
            "runtime_artifact_resolution.py",
            "pretrip_runtime_activation_request.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_load_dry_run.py",
            "tests/test_pretrip_runtime_activation_request.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Dry run rebuilds preflight, validates the activation request, resolves the route artifact, parses GPX, and builds MissionGraphRuntime indexes.",
            "MissionGraphRuntime indexing is allowed only for dry-run validation; SafetyRuntimeSession creation remains blocked.",
            "The dry-run report records duplicate id and segment reference integrity checks with zero live activation, safety API, Phase 1 mutation, and Phase 2 writeback counts.",
        ],
    },
    {
        "milestone": "4.5I",
        "title": "Actual Runtime Activation Loader",
        "implementation_status": "implemented",
        "modules": [
            "runtime_activation_loader.py",
            "runtime_load_dry_run.py",
            "safety_runtime_session.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_activation_loader.py",
            "tests/test_runtime_load_dry_run.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Actual activation reuses dry-run validation and creates SafetyRuntimeSession only after dry_run_passed.",
            "The first activation state is loaded_not_observing: no observe call, no incidents, no safety API call, no incident bridge, and no Phase 2 writeback.",
            "Activation records are written to runtime state, while immutable runtime exports and activation requests are not mutated.",
        ],
    },
    {
        "milestone": "4.5J",
        "title": "Runtime Observing Start",
        "implementation_status": "implemented",
        "modules": [
            "runtime_activation_loader.py",
            "safety_runtime_session.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_activation_loader.py",
            "tests/test_safety_runtime_session.py",
            "tests/test_phase4_pretrip_release_check.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Runtime observing start transitions a loaded_not_observing session into observing by processing one explicit initial observation.",
            "The observing start record stores summary counts and safety state, but not the raw observation payload.",
            "Continuous sensor streams, safety API endpoints, pause/resume/end lifecycle, incident bridge enablement, and Phase 2 writeback remain later slices.",
        ],
    },
    {
        "milestone": "4.5K",
        "title": "Runtime Lifecycle Controls",
        "implementation_status": "implemented",
        "modules": [
            "runtime_activation_loader.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_activation_loader.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Lifecycle controls support pause, resume, end, and abort as local runtime state records.",
            "Pause/resume/end/abort do not process additional observations, call safety APIs, mutate runtime export/request artifacts, enable incident bridge, or write Phase 2.",
            "Ended and aborted states are terminal for this slice; resume is allowed only from paused.",
        ],
    },
    {
        "milestone": "4.5L",
        "title": "Runtime Observation Batch",
        "implementation_status": "implemented",
        "modules": [
            "runtime_activation_loader.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_activation_loader.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Runtime observation batch processes a bounded list of local field observations after observing has started.",
            "The batch record stores summary counts and final safety state only; it does not embed raw observation payloads.",
            "Continuous sensor streams, hardware control, safety APIs, incident bridge enablement, and Phase 2 writeback remain later slices.",
        ],
    },
    {
        "milestone": "4.5M",
        "title": "Runtime Stream Guard",
        "implementation_status": "implemented",
        "modules": [
            "runtime_activation_loader.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_activation_loader.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Runtime stream guard writes blocked stream-request records for observing, paused, and terminal runtime states.",
            "The guard documents that continuous device streams, hardware control, and runtime APIs require a future protocol.",
            "The guard does not process observations, call safety APIs, mutate exports or requests, enable incident bridge, or write Phase 2.",
        ],
    },
    {
        "milestone": "4.5N",
        "title": "Runtime Stream Policy",
        "implementation_status": "implemented",
        "modules": [
            "runtime_stream_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_stream_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_stream_policy",
            "phase45_departure_runtime_handoff",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "The first approved stream sources are Apple Watch and mobile phone using HTTP push or WebSocket transport.",
            "The recommended trust model is device id plus scoped token plus HMAC-SHA256 signature, with timestamp, sequence number, and payload hash.",
            "Disconnected streams queue observations, retry five times, and then keep only the latest point; cadence is capped at 10 Hz with backpressure and rate limiting.",
            "/safety is policy-open only after Phase 4.5 handoff, Final MissionGraph, runtime activation, observing state, and source-policy match.",
            "Incident bridge remains disabled by default behind an explicit opt-in guard.",
        ],
    },
    {
        "milestone": "4.5O",
        "title": "Runtime Observation Envelope",
        "implementation_status": "implemented",
        "modules": [
            "runtime_observation_envelope.py",
            "runtime_stream_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_observation_envelope.py",
            "tests/test_runtime_stream_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_observation_envelope",
            "runtime_stream_policy",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Observation envelopes carry source id, device id, token scope, sequence number, payload hash, and HMAC-SHA256 signature.",
            "Envelope verification rejects tampered payloads or wrong secrets without embedding raw observation data.",
            "The envelope layer does not call /safety, connect device streams, enable incident bridge, or write Phase 2.",
        ],
    },
    {
        "milestone": "4.5P",
        "title": "Runtime Input Admission",
        "implementation_status": "implemented",
        "modules": [
            "runtime_input_admission.py",
            "runtime_observation_envelope.py",
            "runtime_stream_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_input_admission.py",
            "tests/test_runtime_observation_envelope.py",
            "tests/test_runtime_stream_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_input_admission",
            "runtime_observation_envelope",
            "runtime_stream_policy",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "Runtime input admission accepts only signed envelope plus source-policy matches before local admission.",
            "The admission gate rejects tampered payloads, duplicates, and out-of-order sequence numbers.",
            "The gate queues over-10Hz/backpressured or disconnected observations and falls back to latest-point retention after retry exhaustion.",
            "Admission remains local-only: it does not create endpoints, call /safety, forward into SafetyRuntimeSession, enable incident bridge, or write Phase 2.",
        ],
    },
    {
        "milestone": "4.5Q",
        "title": "Safety Observation Admission API",
        "implementation_status": "implemented",
        "modules": [
            "safety_api.py",
            "runtime_input_admission.py",
            "runtime_observation_envelope.py",
            "runtime_stream_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_safety_observation_admission_api.py",
            "tests/test_safety_api.py",
            "tests/test_runtime_input_admission.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "safety_observation_admission_api",
            "runtime_input_admission",
            "runtime_observation_envelope",
            "runtime_stream_policy",
            "focused_phase4_tests",
        ),
        "notes": [
            "When SafetyObservationAdmissionConfig is provided, the safety observations endpoint requires a signed Runtime Observation Envelope.",
            "Only admitted inputs are converted into SensorLog observations and forwarded to the active SafetyRuntimeSession.",
            "Tampered payloads and duplicate dedupe keys are rejected before runtime observation processing.",
            "The legacy unsigned SensorLog ingest path remains available when no admission config is provided.",
        ],
    },
    {
        "milestone": "4.5R",
        "title": "Runtime Incident Bridge Opt-In Guard",
        "implementation_status": "implemented",
        "modules": [
            "runtime_incident_bridge_opt_in.py",
            "runtime_stream_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_incident_bridge_opt_in.py",
            "tests/test_runtime_stream_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_incident_bridge_opt_in",
            "runtime_stream_policy",
            "core_phase4_modules",
            "focused_phase4_tests",
        ),
        "notes": [
            "The bridge guard requires explicit operator opt-in, a remote contact policy, a noise-reduction policy, and observing/paused runtime state.",
            "Ready status means bridge enablement may be considered by a later slice; this guard itself performs no enablement.",
            "The guard sends no remote notification, enables no Phase 1 bridge, writes no Phase 2 Brain state, and embeds no raw payload.",
        ],
    },
    {
        "milestone": "4.5S",
        "title": "Server Safety Admission Config",
        "implementation_status": "implemented",
        "modules": [
            "server.py",
            "server_safety_observation_admission_config.py",
            "safety_api.py",
            "runtime_input_admission.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_server_safety_observation_admission_config.py",
            "tests/test_safety_observation_admission_api.py",
            "tests/test_server_safety_flow.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "server_safety_observation_admission_config",
            "safety_observation_admission_api",
            "focused_phase4_tests",
        ),
        "notes": [
            "Signed safety observation admission is disabled by default in the main server.",
            "Operators can enable it with SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED and provide a secret via env or secret file.",
            "When enabled without a usable secret, the server fails closed by not creating the live SafetyRuntimeSession.",
            "The server passes SafetyObservationAdmissionConfig into the safety router only after config validation succeeds.",
        ],
    },
    {
        "milestone": "4.5T",
        "title": "Runtime Stream Transport API",
        "implementation_status": "implemented",
        "modules": [
            "runtime_stream_transport_api.py",
            "server.py",
            "safety_api.py",
            "runtime_observation_envelope.py",
            "runtime_input_admission.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_stream_transport_api.py",
            "tests/test_server_safety_observation_admission_config.py",
            "tests/test_safety_observation_admission_api.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_stream_transport_api",
            "server_safety_observation_admission_config",
            "safety_observation_admission_api",
            "focused_phase4_tests",
        ),
        "notes": [
            "The HTTP push transport is exposed at POST /runtime/streams/http-push/observations only when signed admission is configured.",
            "The WebSocket transport is exposed at /runtime/streams/websocket/observations only when signed admission is configured.",
            "Both transport surfaces enforce that the signed envelope transport matches the endpoint before runtime observation processing.",
            "The transport API does not enable incident bridge notifications or write Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5U",
        "title": "Runtime Stream Telemetry",
        "implementation_status": "implemented",
        "modules": [
            "runtime_stream_telemetry.py",
            "runtime_stream_transport_api.py",
            "runtime_input_admission.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_stream_telemetry.py",
            "tests/test_runtime_stream_transport_api.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_stream_telemetry",
            "runtime_stream_transport_api",
            "focused_phase4_tests",
        ),
        "notes": [
            "Runtime stream telemetry exposes GET /runtime/streams/status for accepted, rejected, queued, and WebSocket connection state summaries.",
            "Telemetry summarizes RuntimeInputAdmissionState queue/de-dupe counts without embedding raw SensorLog payloads.",
            "Telemetry does not enable incident bridge notifications or write Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5V",
        "title": "Runtime Stream Operator Controls",
        "implementation_status": "implemented",
        "modules": [
            "runtime_stream_controls.py",
            "runtime_stream_transport_api.py",
            "runtime_stream_telemetry.py",
            "runtime_input_admission.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_stream_controls.py",
            "tests/test_runtime_stream_transport_api.py",
            "tests/test_runtime_stream_telemetry.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_stream_controls",
            "runtime_stream_transport_api",
            "runtime_stream_telemetry",
            "focused_phase4_tests",
        ),
        "notes": [
            "Local operator controls expose pause, resume, end, and drain-queue actions under /runtime/streams/control/*.",
            "Paused or ended control state blocks new observations before runtime processing.",
            "Drain queue clears admission queue summaries while preserving de-dupe history.",
            "Controls are local-only and do not control device hardware, enable incident bridge notifications, or write Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5W",
        "title": "Runtime Incident Bridge Enablement Dry Run",
        "implementation_status": "implemented",
        "modules": [
            "runtime_incident_bridge_enablement.py",
            "runtime_incident_bridge_opt_in.py",
            "mock_outbound_transport.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_incident_bridge_enablement.py",
            "tests/test_runtime_incident_bridge_opt_in.py",
            "tests/test_mock_outbound_transport.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_incident_bridge_enablement",
            "runtime_incident_bridge_opt_in",
            "focused_phase4_tests",
        ),
        "notes": [
            "Guard-ready incident bridge enablement can now be exercised as a dry run.",
            "Dry run queues mock outbound remote-status messages for configured recipient refs.",
            "Dry run records zero real remote notification sends, zero Phase 1 bridge enablements, and zero Phase 2 Brain writes.",
        ],
    },
    {
        "milestone": "4.5X",
        "title": "Mock Delivery Acknowledgment and Withdrawal",
        "implementation_status": "implemented",
        "modules": [
            "runtime_incident_bridge_delivery_ack.py",
            "runtime_incident_bridge_enablement.py",
            "mock_outbound_transport.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_incident_bridge_delivery_ack.py",
            "tests/test_runtime_incident_bridge_enablement.py",
            "tests/test_mock_outbound_transport.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_incident_bridge_delivery_ack",
            "runtime_incident_bridge_enablement",
            "focused_phase4_tests",
        ),
        "notes": [
            "Mock delivery acknowledgment can mark mock outbound dry-run messages as mock-delivered.",
            "Mock withdrawal can mark queued mock messages as cancelled with an operator reason.",
            "Rerun acknowledgment records result refs produced by a separate dry-run execution; it does not queue real or provider messages itself.",
            "All paths remain mock-only with zero real remote sends, zero Phase 1 bridge enablements, and zero Phase 2 Brain writes.",
        ],
    },
    {
        "milestone": "4.5Y",
        "title": "Webhook Remote Provider Policy Contract",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_policy.py",
            "runtime_incident_bridge_delivery_ack.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_policy.py",
            "tests/test_runtime_incident_bridge_delivery_ack.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_policy",
            "runtime_incident_bridge_delivery_ack",
            "focused_phase4_tests",
        ),
        "notes": [
            "The first real provider class is webhook_telegram_like, represented as a policy contract only.",
            "The policy allows reviewed remote_status, checkin, and L2/L3 incident_alert messages, while SOS remains blocked.",
            "Recipient refs must be reviewed remote contacts; arbitrary URL, phone, or endpoint input is not accepted.",
            "Cancellation means cancel request or follow-up correction only; true provider recall is not promised.",
            "This slice creates no provider adapter, sends no network request, stores no token or raw endpoint URL, enables no Phase 1 bridge, and writes no Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5Z",
        "title": "Remote Provider Config Preflight",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_config_preflight.py",
            "runtime_remote_provider_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_config_preflight.py",
            "tests/test_runtime_remote_provider_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_config_preflight",
            "runtime_remote_provider_policy",
            "focused_phase4_tests",
        ),
        "notes": [
            "Webhook provider config is represented as endpoint, auth, and reviewed-recipient secret refs only.",
            "Config preflight can report ready when all required refs are available, or blocked when endpoint/auth/recipient refs are missing.",
            "Preflight blocks policy mismatches, SOS message enablement, and unreviewed recipient refs before any provider adapter exists.",
            "This slice loads no secret values, embeds no raw provider URL or delivery target, creates no provider adapter, sends no network request, enables no Phase 1 bridge, and writes no Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5AA",
        "title": "Remote Provider Payload Composer",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_payload_composer.py",
            "runtime_remote_provider_config_preflight.py",
            "runtime_remote_provider_policy.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_payload_composer.py",
            "tests/test_runtime_remote_provider_config_preflight.py",
            "tests/test_runtime_remote_provider_policy.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_payload_composer",
            "runtime_remote_provider_config_preflight",
            "runtime_remote_provider_policy",
            "focused_phase4_tests",
        ),
        "notes": [
            "Payload composer requires policy-compatible message requests and a ready provider config preflight.",
            "It produces summary-only payload previews with reviewed recipient refs, body previews, payload hashes, operator ids, and correlation refs.",
            "Incident alert payloads still require allowed incident levels and a noise-reduction policy ref.",
            "Blocked preflight, SOS, unreviewed recipient refs, and missing noise policy create payload_blocked outputs.",
            "This slice embeds no raw endpoint URL, token, delivery target, or SensorLog payload, sends no network request, enables no Phase 1 bridge, and writes no Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5AB",
        "title": "Remote Provider Send Intent Queue",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_send_queue.py",
            "runtime_remote_provider_payload_composer.py",
            "runtime_remote_provider_config_preflight.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_send_queue.py",
            "tests/test_runtime_remote_provider_payload_composer.py",
            "tests/test_runtime_remote_provider_config_preflight.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_send_queue",
            "runtime_remote_provider_payload_composer",
            "runtime_remote_provider_config_preflight",
            "focused_phase4_tests",
        ),
        "notes": [
            "Send intent queue turns payload_ready_not_sent previews into local queued_not_sent audit records.",
            "Blocked payload previews create send_intent_blocked records and preserve original blocker reasons.",
            "Queued send intent still requires a future provider adapter and manual send authorization before any live network send.",
            "This slice embeds no raw endpoint URL, token, delivery target, or SensorLog payload, sends no network request, creates no provider adapter, enables no Phase 1 bridge, and writes no Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5AC",
        "title": "Webhook Live Provider Adapter",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_live_adapter.py",
            "runtime_remote_provider_send_queue.py",
            "runtime_remote_provider_config_preflight.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_live_adapter.py",
            "tests/test_runtime_remote_provider_send_queue.py",
            "tests/test_runtime_remote_provider_config_preflight.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_live_adapter",
            "runtime_remote_provider_send_queue",
            "runtime_remote_provider_config_preflight",
            "focused_phase4_tests",
        ),
        "notes": [
            "Webhook live adapter supports a real JSON POST path using the Python standard library transport.",
            "Live send stays blocked by default and requires provider_adapter_enabled, live_network_send_enabled, and manual_send_authorization.",
            "Secret refs can resolve from env, file, or keychain; result artifacts record schemes and counts but never serialize secret values, raw endpoint URLs, or delivery target values.",
            "Tests and release checks use injected transport, so validation does not call external networks.",
            "This slice can send through the adapter when explicitly authorized, but still enables no Phase 1 bridge and writes no Phase 2 Brain state.",
        ],
    },
    {
        "milestone": "4.5AD",
        "title": "Webhook Live Send Operator CLI",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_live_send_cli.py",
            "runtime_remote_provider_live_adapter.py",
            "runtime_remote_provider_send_queue.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_live_send_cli.py",
            "tests/test_runtime_remote_provider_live_adapter.py",
            "tests/test_runtime_remote_provider_send_queue.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
            "tests/fixtures/mission_graph/normal_climb_mission.json",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_live_send_cli",
            "runtime_remote_provider_live_adapter",
            "runtime_remote_provider_send_queue",
            "focused_phase4_tests",
        ),
        "notes": [
            "Operator CLI reads provider config and queued send-intent artifact JSON.",
            "Default CLI invocation returns live_send_blocked and does not resolve secrets or call transport.",
            "CLI sends only when --enable-provider-adapter, --enable-live-network-send, and --authorize-manual-send are all present.",
            "Missing config or intent artifacts produce operator_request_blocked before secret resolution or transport.",
            "This slice provides an operator entrypoint for live sends, while still recording summary-only results and enabling no Phase 1 bridge or Phase 2 Brain writeback.",
        ],
    },
    {
        "milestone": "4.5AE",
        "title": "Shared Admin Map Layer Stack",
        "implementation_status": "implemented",
        "modules": [
            "admin_map_layers.py",
            "pretrip_admin_view.py",
            "admin_after_action.py",
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_map_layers.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_admin_after_action.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
        ],
        "release_check_coverage": _release_check(
            "admin_map_layer_stack",
            "pretrip_admin_ui",
            "focused_phase4_tests",
        ),
        "notes": [
            "Shared catalog defines layer ids, Chinese labels, render mode, source kind, and z-index for admin map surfaces.",
            "Layer ordering is fixed as imagery bottom, OSM/base and evidence overlays in the middle, and weather/API overlays on top.",
            "Phase 4 pretrip and Phase 1 after-action admin pages expose matching layer toggles without calling weather APIs.",
            "The OSM layer contract now reserves real raster tile rendering while keeping weather/API overlays explicit and disabled unless data is present.",
        ],
    },
    {
        "milestone": "4.5AF",
        "title": "Real OSM Basemap Renderer",
        "implementation_status": "implemented",
        "modules": [
            "admin_basemap_tiles.py",
            "admin_map_layers.py",
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_basemap_tiles.py",
            "tests/test_admin_map_layers.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_admin_after_action.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
        ],
        "release_check_coverage": _release_check(
            "admin_basemap_renderer",
            "admin_map_layer_stack",
            "focused_phase4_tests",
        ),
        "notes": [
            "Real basemap means OpenStreetMap slippy-tile URLs are converted into bounded SVG image placement metadata.",
            "The renderer uses Web Mercator tile math and max-tile limiting so Chilai-like mountain bbox previews do not explode into unbounded tile requests.",
            "The Python contract performs no network fetch; actual raster tile loading is left to the browser or a future local tile proxy.",
        ],
    },
    {
        "milestone": "4.5AG",
        "title": "Local Webhook Demo Harness",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_demo_harness.py",
            "runtime_remote_provider_live_send_cli.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_demo_harness.py",
            "tests/test_runtime_remote_provider_live_send_cli.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_demo_harness",
            "runtime_remote_provider_live_send_cli",
            "focused_phase4_tests",
        ),
        "notes": [
            "The local harness starts a stdlib localhost webhook capture server for live-demo verification.",
            "It accepts JSON POSTs, records body hashes and provider message refs, and rejects non-POST methods without capture.",
            "It uses no external network client, Phase 1 incident bridge, or Phase 2 Brain writeback path.",
        ],
    },
    {
        "milestone": "4.5AH",
        "title": "Local Webhook Demo Bundle Builder",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_demo_bundle.py",
            "runtime_remote_provider_demo_harness.py",
            "runtime_remote_provider_live_send_cli.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_demo_bundle.py",
            "tests/test_runtime_remote_provider_demo_harness.py",
            "tests/test_runtime_remote_provider_live_send_cli.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_demo_bundle",
            "runtime_remote_provider_demo_harness",
            "runtime_remote_provider_live_send_cli",
            "focused_phase4_tests",
        ),
        "notes": [
            "The bundle builder writes a localhost-only provider config, send intent, payload preview, demo env, operator command, and summary.",
            "The generated bundle can drive the existing live-send CLI into the local webhook harness with explicit authorization flags.",
            "The bundle remains a demo artifact: no external endpoint, Phase 1 incident bridge enablement, Phase 2 writeback, or raw SensorLog payload is included.",
        ],
    },
    {
        "milestone": "4.5AI",
        "title": "Local OSM Tile Cache Proxy",
        "implementation_status": "implemented",
        "modules": [
            "admin_tile_proxy.py",
            "admin_map_layers.py",
            "admin_api.py",
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_tile_proxy.py",
            "tests/test_admin_map_layers.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_admin_after_action.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
        ],
        "release_check_coverage": _release_check(
            "admin_tile_proxy",
            "admin_map_layer_stack",
            "focused_phase4_tests",
        ),
        "notes": [
            "Local tile proxy provides /admin/tiles/osm/{z}/{x}/{y}.png for offline demo mode.",
            "The proxy serves an existing local cache file or a generated SVG fallback tile; it does not fetch public OSM URLs.",
            "Both admin map surfaces can switch to local tile source through URL/localStorage while keeping public OSM as the default browser-loaded basemap.",
        ],
    },
    {
        "milestone": "4.5AJ",
        "title": "Weather API Overlay Renderer",
        "implementation_status": "implemented",
        "modules": [
            "admin_weather_overlay.py",
            "admin_map_layers.py",
            "admin_api.py",
            "docs/admin/phase4-pretrip-planning.html",
            "docs/admin/phase1-after-action.html",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_weather_overlay.py",
            "tests/test_admin_map_layers.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_pretrip_admin_page.py",
            "tests/test_admin_after_action.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/weather_daylight_evidence.json",
            "docs/admin/phase4-pretrip-planning.html",
        ],
        "release_check_coverage": _release_check(
            "admin_weather_overlay",
            "admin_map_layer_stack",
            "pretrip_admin_ui",
            "focused_phase4_tests",
        ),
        "notes": [
            "Pretrip admin fetches a summary-only weather overlay from the local admin API and draws it as the top map layer.",
            "Weather runtime status can become ready only when operator env enables the provider and supplies the configured secret ref.",
            "The overlay embeds no raw weather payloads, no secret values, and performs no live API call in fixture-backed mode.",
        ],
    },
    {
        "milestone": "4.5AK",
        "title": "External Webhook Demo Bundle",
        "implementation_status": "implemented",
        "modules": [
            "runtime_remote_provider_demo_bundle.py",
            "runtime_remote_provider_config_preflight.py",
            "runtime_remote_provider_live_send_cli.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_runtime_remote_provider_external_demo_bundle.py",
            "tests/test_runtime_remote_provider_demo_bundle.py",
            "tests/test_runtime_remote_provider_live_send_cli.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "docs/specs/phase-4-5-departure-runtime-handoff.md",
        ],
        "release_check_coverage": _release_check(
            "runtime_remote_provider_external_demo_bundle",
            "runtime_remote_provider_demo_bundle",
            "focused_phase4_tests",
        ),
        "notes": [
            "External webhook bundle writes provider config, send intent, payload preview, secret-ref manifest, operator command, and summary.",
            "Missing endpoint/token/target secret refs block the bundle from ready state; complete refs mark it ready for manual send only.",
            "The bundle never embeds raw endpoint URLs, token values, Phase 1 bridge controls, Phase 2 writeback, or raw SensorLog payloads.",
        ],
    },
    {
        "milestone": "4.5AL",
        "title": "Hardware Tile Cache Plan Builder",
        "implementation_status": "implemented",
        "modules": [
            "admin_tile_cache_builder.py",
            "admin_tile_proxy.py",
            "admin_basemap_tiles.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_tile_cache_builder.py",
            "tests/test_admin_tile_proxy.py",
            "tests/test_admin_basemap_tiles.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/routes/route_summary.json",
        ],
        "release_check_coverage": _release_check(
            "admin_tile_cache_builder",
            "admin_tile_proxy",
            "focused_phase4_tests",
        ),
        "notes": [
            "The builder creates a Scout hardware tile-cache plan using the Chilai bbox expanded by 50 percent and zoom 5-20.",
            "The default cache root is ~/.cache/scout-fusion/osm-tiles with a 10 GiB capacity limit.",
            "Public tile.openstreetmap.org bulk/offline prefetch is explicitly blocked; real seeding requires a self-hosted or offline-prefetch-permitted tile provider.",
        ],
    },
    {
        "milestone": "4.5AM",
        "title": "Local GeoTIFF Raster Source Manifest",
        "implementation_status": "implemented",
        "modules": [
            "admin_local_raster_source.py",
            "admin_map_layers.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_local_raster_source.py",
            "tests/test_admin_map_layers.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_local_raster_source",
            "admin_map_layer_stack",
            "focused_phase4_tests",
        ),
        "notes": [
            "Manual local GeoTIFF sources are represented as metadata-only manifests with bbox, CRS, size, and hash.",
            "The manifest keeps raw rasters local-cache-only and explicitly blocks repo fixture writeback.",
            "Pretrip imagery layers can point to a local raster manifest before any tile cutting is performed.",
        ],
    },
    {
        "milestone": "4.5AN",
        "title": "Local GeoTIFF Raster Tile Pyramid",
        "implementation_status": "implemented",
        "modules": [
            "admin_local_raster_tiles.py",
            "admin_local_raster_source.py",
            "admin_api.py",
            "admin_map_layers.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_local_raster_tiles.py",
            "tests/test_admin_local_raster_source.py",
            "tests/test_admin_map_layers.py",
            "tests/test_pretrip_admin_api.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_local_raster_tiles",
            "admin_map_layer_stack",
            "pretrip_admin_ui",
            "focused_phase4_tests",
        ),
        "notes": [
            "The tile pyramid planner estimates local PNG imagery tiles for WGS84 GeoTIFF sources under the 10 GiB cache limit.",
            "The cutter writes PNG tiles only to ~/.cache/scout-fusion/raster-tiles or a caller-provided local cache root, never repo fixtures.",
            "The admin API can serve cached imagery PNG tiles or transparent fallback tiles without external network fetches.",
        ],
    },
    {
        "milestone": "4.5AO",
        "title": "Pretrip Raster Imagery Renderer",
        "implementation_status": "implemented",
        "modules": [
            "docs/admin/phase4-pretrip-planning.html",
            "admin_map_layers.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_pretrip_admin_page.py",
            "tests/test_pretrip_admin_view.py",
            "tests/test_admin_map_layers.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
        ],
        "release_check_coverage": _release_check(
            "admin_map_layer_stack",
            "pretrip_admin_ui",
            "focused_phase4_tests",
        ),
        "notes": [
            "The pretrip SVG map now renders local raster imagery <image> tiles before the OSM basemap layer.",
            "The imagery renderer reads the local raster tile URL template from the map layer contract and keeps the layer toggleable.",
            "Missing local imagery tiles resolve through the local transparent fallback endpoint rather than external network fetches.",
        ],
    },
    {
        "milestone": "4.5AP",
        "title": "After-Action Raster Imagery Renderer",
        "implementation_status": "implemented",
        "modules": [
            "docs/admin/phase1-after-action.html",
            "admin_map_layers.py",
            "phase4_pretrip_release_check.py",
        ],
        "tests": [
            "tests/test_admin_after_action.py",
            "tests/test_admin_map_layers.py",
            "tests/test_phase4_pretrip_release_check.py",
            "tests/test_pretrip_implementation_status.py",
        ],
        "fixture_refs": [
            "tests/fixtures/field_cases/scout_260512_field_golden.json",
        ],
        "release_check_coverage": _release_check(
            "admin_map_layer_stack",
            "focused_phase4_tests",
        ),
        "notes": [
            "The after-action SVG map now uses the same local raster imagery tile renderer under the OSM basemap.",
            "The renderer reads the imagery tile URL template from the shared map layer contract and keeps the layer toggleable.",
            "Missing scout_260512 imagery tiles resolve through the local transparent fallback endpoint, keeping raw rasters out of repo fixtures.",
        ],
    },
)
