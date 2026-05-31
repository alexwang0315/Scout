from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from pretrip_models import (
    CandidateReviewState,
    PaceMultiplierBasis,
    PreTripPackage,
    PreTripPlanningReference,
    PreTripProvenance,
    PreTripRetreatRouteCandidate,
    PreTripRouteGuideTimingCandidate,
    PreTripArtifactKind,
)
from pretrip_after_action_candidates import build_scout_260512_after_action_next_plan_candidates
from pretrip_contour_interpretation import (
    ContourInterpretationCandidate,
    ContourInterpretationCandidateSet,
    ContourSourceRefs,
    ContourTargetRefs,
)
from pretrip_geojson_import import import_pretrip_geojson_candidates
from pretrip_brain_seed import export_chilai_pretrip_brain_seed
from pretrip_eta_plan import build_chilai_day1_eta_plan
from pretrip_mission_compiler import compile_pretrip_mission_graph
from pretrip_review_models import (
    PreTripHumanReview,
    PreTripHumanReviewLog,
    source_candidate_snapshot_hash,
)
from pretrip_review_resolver import resolve_pretrip_reviewed_package
from pretrip_review_queue import build_chilai_review_queue_manifest
from pretrip_remote_summary import build_remote_contact_summary
from pretrip_resource_plan import build_chilai_resource_plan
from pretrip_readiness import evaluate_pretrip_readiness, load_skill_config_manifest
from pretrip_plan_validation import build_chilai_plan_validation_report
from pretrip_route_comparison import DEFAULT_SIMILAR_GPX, build_chilai_route_comparison
from pretrip_runtime_handoff_metadata import build_chilai_runtime_handoff_metadata
from pretrip_runtime_audit import build_chilai_runtime_audit_manifest
from pretrip_segment_policy import build_chilai_segment_policy_candidates
from pretrip_source_ingest import build_pretrip_package, write_json
from pretrip_skill_audit import build_pretrip_skill_audit_bundle
from pretrip_skill_manifest_catalog import build_chilai_skill_manifest_catalog
from pretrip_terrain_summary import summarize_segment_terrain_metadata
from pretrip_timing_calibration import generate_timing_measurement_candidates
from pretrip_poi_readiness import evaluate_poi_readiness_candidates
from pretrip_departure_bundle import build_chilai_departure_bundle
from pretrip_weather_daylight import (
    DaylightEvidenceWindow,
    PreTripWeatherDaylightEvidence,
    WeatherDaylightSourceRef,
    WeatherDaylightThresholdPolicy,
    WeatherDaylightValidation,
    WeatherWindowSummary,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_GPX = Path("/Users/alexwang0315/downloads/奇萊南華-能高越嶺步道Day1.gpx")
DEFAULT_IMAGE = Path("/Users/alexwang0315/downloads/G11_hiking.jpg")
DEFAULT_DTM_DIRS = [
    ROOT / "catographydata" / "DTM" / "分幅_南投縣20MDEM(2025)",
    ROOT / "catographydata" / "DTM" / "分幅_花蓮縣20MDEM(2025)",
]
DEFAULT_OUTPUT_DIR = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Chilai-Nanhua Day1 pre-trip metadata fixture.")
    parser.add_argument("--gpx", type=Path, default=DEFAULT_GPX)
    parser.add_argument("--similar-gpx", type=Path, default=DEFAULT_SIMILAR_GPX)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--dtm-dir", type=Path, action="append", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    dtm_dirs = args.dtm_dir if args.dtm_dir is not None else DEFAULT_DTM_DIRS
    package = build_pretrip_package(
        package_id="pretrip.chilai_nanhua_day1.v0",
        project_id="chilai_nanhua_day1",
        version="0.1.0",
        gpx_path=args.gpx,
        image_path=args.image,
        dtm_dirs=dtm_dirs,
        planning_references=_planning_references(),
        retreat_route_candidates=_retreat_route_candidates(),
        route_guide_timing_candidates=_route_guide_timing_candidates(),
    )
    if package.retreat_route_candidates and package.checkpoint_candidates:
        finish_index = package.checkpoint_candidates[-1].route_point_index
        for candidate in package.retreat_route_candidates:
            if candidate.route_point_end_index is None:
                candidate.route_point_end_index = finish_index
            if candidate.distance_m == 0.0:
                candidate.distance_m = package.route_summary.distance_m

    output_dir = args.output_dir
    write_json(output_dir / "outputs" / "pretrip_package.json", package.model_dump(mode="json"))
    write_json(output_dir / "normalized" / "routes" / "route_summary.json", package.route_summary.model_dump(mode="json"))
    route_comparison = build_chilai_route_comparison(
        primary_gpx_path=args.gpx,
        similar_gpx_path=args.similar_gpx,
    )
    write_json(output_dir / "outputs" / "route_comparison.json", route_comparison)
    write_json(
        output_dir / "candidates" / "checkpoints.json",
        [candidate.model_dump(mode="json") for candidate in package.checkpoint_candidates],
    )
    write_json(
        output_dir / "candidates" / "segments.json",
        [candidate.model_dump(mode="json") for candidate in package.segment_candidates],
    )
    write_json(
        output_dir / "candidates" / "retreat_routes.json",
        [candidate.model_dump(mode="json") for candidate in package.retreat_route_candidates],
    )
    write_json(
        output_dir / "candidates" / "planning_references.json",
        [reference.model_dump(mode="json") for reference in package.planning_references],
    )
    write_json(
        output_dir / "candidates" / "route_guide_timing.json",
        [candidate.model_dump(mode="json") for candidate in package.route_guide_timing_candidates],
    )
    map_context = _map_context_geojson()
    write_json(output_dir / "normalized" / "map" / "map_context.geojson", map_context)
    map_candidates = import_pretrip_geojson_candidates(
        map_context,
        uri="tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/map_context.geojson",
        source_ref="map_context.chilai_nanhua_day1.manual",
    )
    write_json(output_dir / "candidates" / "map_candidates.json", map_candidates.model_dump(mode="json"))
    poi_readiness_candidates = evaluate_poi_readiness_candidates(
        package,
        map_candidates.model_dump(mode="json"),
    )
    write_json(
        output_dir / "outputs" / "poi_readiness_candidates.json",
        poi_readiness_candidates.model_dump(mode="json"),
    )
    if package.dtm_coverage_summary is not None:
        write_json(
            output_dir / "normalized" / "terrain" / "dtm_coverage_summary.json",
            package.dtm_coverage_summary.model_dump(mode="json"),
        )
        terrain_summary = summarize_segment_terrain_metadata(
            segment_candidates=package.segment_candidates,
            dtm_coverage_summary=package.dtm_coverage_summary,
            summary_id="terrain_summary.chilai_nanhua_day1.20m",
        )
        write_json(
            output_dir / "normalized" / "terrain" / "segment_dtm_coverage.json",
            terrain_summary.model_dump(mode="json"),
        )
    skill_config_manifest_ref = "candidates/skill_config_manifest.json"
    skill_config_manifest_path = output_dir / skill_config_manifest_ref
    readiness_payload = {"status": "unknown", "findings": []}
    if skill_config_manifest_path.exists():
        readiness_report = evaluate_pretrip_readiness(
            {
                "route_id": package.project_id,
                "route_days": 2,
                "route_kind": "traverse",
                "distance_m": package.route_summary.distance_m,
                "retreat_routes": [
                    candidate.model_dump(mode="json") for candidate in package.retreat_route_candidates
                ],
            },
            skill_config_manifest=load_skill_config_manifest(skill_config_manifest_path),
        )
        readiness_payload = asdict(readiness_report)
        write_json(output_dir / "outputs" / "readiness_report.json", readiness_payload)
    compiled_mission_graph = compile_pretrip_mission_graph(package, allow_unreviewed=True)
    write_json(
        output_dir / "outputs" / "compiled_mission_graph.candidate.json",
        compiled_mission_graph.model_dump(mode="json"),
    )
    review_log = _review_log(package, map_candidates.model_dump(mode="json"))
    write_json(output_dir / "reviews" / "human_reviews.json", review_log.model_dump(mode="json"))
    reviewed_package = resolve_pretrip_reviewed_package(package, list(review_log.reviews))
    reviewed_package = reviewed_package.model_copy(update={"status": "reviewed"})
    write_json(output_dir / "outputs" / "pretrip_package.reviewed.json", reviewed_package.model_dump(mode="json"))
    reviewed_mission_graph = compile_pretrip_mission_graph(reviewed_package)
    write_json(
        output_dir / "outputs" / "compiled_mission_graph.reviewed.json",
        reviewed_mission_graph.model_dump(mode="json"),
    )
    timing_measurements = generate_timing_measurement_candidates(package.route_guide_timing_candidates)
    write_json(
        output_dir / "outputs" / "timing_measurements.json",
        [measurement.model_dump(mode="json") for measurement in timing_measurements],
    )
    segment_policy_candidates = build_chilai_segment_policy_candidates(package)
    write_json(
        output_dir / "outputs" / "segment_policy_candidates.json",
        segment_policy_candidates.model_dump(mode="json"),
    )
    eta_plan = build_chilai_day1_eta_plan(
        package,
        start_offset_minutes=60,
        day1_target_node_name="天池山莊",
        turn_back_checkpoint_node_name="雲海保線所",
    )
    write_json(output_dir / "outputs" / "planned_eta.json", eta_plan.model_dump(mode="json"))
    weather_daylight_evidence = _weather_daylight_evidence(package, eta_plan)
    write_json(
        output_dir / "outputs" / "weather_daylight_evidence.json",
        weather_daylight_evidence.model_dump(mode="json"),
    )
    contour_interpretation_candidates = _contour_interpretation_candidates(package)
    write_json(
        output_dir / "outputs" / "contour_interpretation_candidates.json",
        contour_interpretation_candidates.model_dump(mode="json"),
    )
    project_payload = {
            "project_id": package.project_id,
            "package_ref": "outputs/pretrip_package.json",
            "route_summary_ref": "normalized/routes/route_summary.json",
            "route_comparison_ref": "outputs/route_comparison.json",
            "dtm_coverage_summary_ref": "normalized/terrain/dtm_coverage_summary.json",
            "segment_dtm_coverage_ref": "normalized/terrain/segment_dtm_coverage.json",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "retreat_routes_ref": "candidates/retreat_routes.json",
            "map_context_ref": "normalized/map/map_context.geojson",
            "map_candidates_ref": "candidates/map_candidates.json",
            "planning_references_ref": "candidates/planning_references.json",
            "route_guide_timing_ref": "candidates/route_guide_timing.json",
            "skill_config_manifest_ref": skill_config_manifest_ref,
            "readiness_report_ref": "outputs/readiness_report.json",
            "human_reviews_ref": "reviews/human_reviews.json",
            "reviewed_package_ref": "outputs/pretrip_package.reviewed.json",
            "compiled_mission_graph_candidate_ref": "outputs/compiled_mission_graph.candidate.json",
            "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
            "timing_measurements_ref": "outputs/timing_measurements.json",
            "planned_eta_ref": "outputs/planned_eta.json",
            "brain_seed_nodes_ref": "outputs/brain_seed_nodes.json",
            "planning_skill_audit_ref": "outputs/planning_skill_audit.json",
            "planning_skill_manifest_catalog_ref": "outputs/planning_skill_manifest_catalog.json",
            "poi_readiness_candidates_ref": "outputs/poi_readiness_candidates.json",
            "segment_policy_candidates_ref": "outputs/segment_policy_candidates.json",
            "plan_validation_candidates_ref": "outputs/plan_validation_candidates.json",
            "runtime_audit_manifest_ref": "outputs/runtime_audit_manifest.json",
            "runtime_handoff_metadata_ref": "outputs/runtime_handoff_metadata.candidate.json",
            "after_action_next_plan_candidates_ref": "outputs/after_action_next_plan_candidates.json",
            "review_queue_manifest_ref": "outputs/review_queue_manifest.json",
            "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
            "contour_interpretation_candidates_ref": "outputs/contour_interpretation_candidates.json",
            "remote_contact_summary_ref": "outputs/remote_contact_summary.json",
            "resource_plan_ref": "outputs/resource_plan.json",
            "departure_bundle_manifest_ref": "outputs/departure_bundle_manifest.json",
            "source_artifact_count": len(package.source_artifacts),
            "planning_reference_count": len(package.planning_references),
            "checkpoint_candidate_count": len(package.checkpoint_candidates),
            "segment_candidate_count": len(package.segment_candidates),
            "retreat_route_candidate_count": len(package.retreat_route_candidates),
            "map_corridor_candidate_count": len(map_candidates.corridor_candidates),
            "map_poi_candidate_count": len(map_candidates.poi_candidates),
            "map_hazard_candidate_count": len(map_candidates.hazard_candidates),
            "human_review_count": len(review_log.reviews),
            "route_guide_timing_candidate_count": len(package.route_guide_timing_candidates),
            "route_comparison_count": 1,
            "timing_measurement_count": len(timing_measurements),
            "planned_eta_estimate_count": len(eta_plan.estimates),
            "brain_seed_node_count": 0,
            "dtm_candidate_tile_count": len(package.dtm_coverage_summary.candidate_tiles)
            if package.dtm_coverage_summary
            else 0,
            "planning_skill_run_count": 5,
            "planning_skill_manifest_count": 0,
            "poi_readiness_finding_candidate_count": len(poi_readiness_candidates.findings),
            "segment_policy_candidate_count": len(segment_policy_candidates.candidates),
            "plan_validation_finding_candidate_count": 0,
            "runtime_audit_axis_count": 0,
            "runtime_handoff_route_ref_count": 0,
            "after_action_next_plan_candidate_count": 0,
            "review_queue_item_count": 0,
            "departure_bundle_required_ref_count": 0,
            "weather_daylight_evidence_count": 1,
            "contour_interpretation_candidate_count": len(
                contour_interpretation_candidates.candidates
            ),
            "notes": [
                "Fixture stores only source metadata, route summary, and DTM tile coverage summary.",
                "Large GPX/photo/DTM source files remain outside repo fixtures.",
                "Compiled MissionGraph fixture is candidate-only and generated with allow_unreviewed=True.",
                "Reviewed MissionGraph fixture is generated from append-only human reviews without allow_unreviewed.",
                "Similar GPX route comparison is metadata-only, comparison-only, and not compiled into MissionGraph.",
                "POI readiness output is candidate-only and does not mutate hard readiness status.",
                "Segment policy output is candidate-only and does not mutate compiled MissionGraph defaults.",
                "Plan validation output is candidate-only and does not mutate hard readiness status.",
                "Runtime audit manifest is candidate-only and performs no live runtime comparison.",
                "Runtime handoff metadata is candidate-only and does not mutate Phase 1 runtime.",
                "After-action next-plan candidates reference previous field evidence without mutating it.",
                "Review queue manifest summarizes pending candidate review work without recording decisions.",
                "Weather/daylight evidence is candidate-only placeholder metadata with no external API call.",
                "Contour interpretation candidates are metadata-only prompts, not ObservedFact records.",
                "Resource plan is redacted candidate context and does not mutate hard readiness status.",
                "Planning skill manifest catalog pins candidate-only write boundaries without embedding source payloads.",
                "Departure bundle manifest is a frozen candidate handoff and is not real departure approval.",
            ],
    }
    skill_audit = build_pretrip_skill_audit_bundle(
        project_payload,
        project_ref="project.json",
        mission_id=reviewed_mission_graph.mission_id,
    )
    project_payload["planning_skill_run_count"] = len(skill_audit.records)
    write_json(
        output_dir / "outputs" / "planning_skill_audit.json",
        skill_audit.model_dump(mode="json"),
    )
    remote_contact_summary = build_remote_contact_summary(
        reviewed_package,
        eta_plan,
        readiness_payload,
        project_refs=project_payload,
    )
    write_json(
        output_dir / "outputs" / "remote_contact_summary.json",
        remote_contact_summary.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    resource_plan = build_chilai_resource_plan(output_dir)
    project_payload["resource_plan_device_count"] = len(resource_plan.devices)
    project_payload["resource_plan_equipment_count"] = len(resource_plan.equipment)
    write_json(
        output_dir / "outputs" / "resource_plan.json",
        resource_plan.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    plan_validation = build_chilai_plan_validation_report(output_dir)
    project_payload["plan_validation_finding_candidate_count"] = len(plan_validation.findings)
    write_json(
        output_dir / "outputs" / "plan_validation_candidates.json",
        plan_validation.model_dump(mode="json"),
    )
    runtime_audit = build_chilai_runtime_audit_manifest(output_dir)
    project_payload["runtime_audit_axis_count"] = len(runtime_audit.axes)
    write_json(
        output_dir / "outputs" / "runtime_audit_manifest.json",
        runtime_audit.model_dump(mode="json"),
    )
    after_action_candidates = build_scout_260512_after_action_next_plan_candidates(
        ROOT,
        project_id=package.project_id,
    )
    project_payload["after_action_next_plan_candidate_count"] = len(
        after_action_candidates.candidates
    )
    write_json(
        output_dir / "outputs" / "after_action_next_plan_candidates.json",
        after_action_candidates.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    runtime_handoff_metadata = build_chilai_runtime_handoff_metadata(output_dir)
    project_payload["runtime_handoff_route_ref_count"] = (
        runtime_handoff_metadata.counts.route_ref_count
    )
    write_json(
        output_dir / "outputs" / "runtime_handoff_metadata.candidate.json",
        runtime_handoff_metadata.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    brain_seed = export_chilai_pretrip_brain_seed(
        output_dir,
        reviewed=True,
        mission_id=reviewed_mission_graph.mission_id,
        package_uri="outputs/pretrip_package.reviewed.json",
        review_log_uri="reviews/human_reviews.json",
    )
    project_payload["brain_seed_node_count"] = len(brain_seed.nodes)
    write_json(output_dir / "outputs" / "brain_seed_nodes.json", brain_seed.model_dump())
    write_json(output_dir / "project.json", project_payload)
    skill_manifest_catalog = build_chilai_skill_manifest_catalog(output_dir)
    project_payload["planning_skill_manifest_count"] = len(skill_manifest_catalog.manifests)
    write_json(
        output_dir / "outputs" / "planning_skill_manifest_catalog.json",
        skill_manifest_catalog.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    departure_bundle = build_chilai_departure_bundle(output_dir)
    project_payload["departure_bundle_required_ref_count"] = (
        departure_bundle.counts.required_ref_count
    )
    write_json(
        output_dir / "outputs" / "departure_bundle_manifest.json",
        departure_bundle.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)
    review_queue_manifest = build_chilai_review_queue_manifest(output_dir)
    project_payload["review_queue_item_count"] = review_queue_manifest.counts.item_count
    write_json(
        output_dir / "outputs" / "review_queue_manifest.json",
        review_queue_manifest.model_dump(mode="json"),
    )
    write_json(output_dir / "project.json", project_payload)


def _weather_daylight_evidence(package: PreTripPackage, eta_plan) -> PreTripWeatherDaylightEvidence:
    assumption = eta_plan.assumption
    evidence_date = assumption.planned_start_time[:10]
    return PreTripWeatherDaylightEvidence(
        evidence_id=f"weather_daylight.{package.project_id}.{evidence_date}.v0",
        project_id=package.project_id,
        date=evidence_date,
        timezone="Asia/Taipei",
        location_name="奇萊南華-能高越嶺步道Day1 corridor",
        route_ref="normalized/routes/route_summary.json",
        bbox_wgs84=package.route_summary.bbox_wgs84,
        daylight=DaylightEvidenceWindow(
            date=evidence_date,
            timezone="Asia/Taipei",
            notes=(
                "Placeholder only. Human review must replace or verify sunrise, "
                "sunset, and twilight fields before use in go/no-go planning."
            ),
        ),
        weather_window=WeatherWindowSummary(
            window_start=assumption.planned_start_time,
            window_end=assumption.target_eta,
            summary="Weather not evaluated in this candidate fixture.",
            hazard_notes=[
                "Weather window not populated from an authoritative source.",
                "Mountain weather can change quickly; this placeholder requires human review.",
            ],
            notes=(
                "Placeholder only. Human reviewer should provide source-backed forecast "
                "window before go/no-go use."
            ),
        ),
        threshold_policy=WeatherDaylightThresholdPolicy(
            rainfall={"source_refs": ["cwa.weather_warning_thresholds"]},
            dense_fog={"source_refs": ["cwa.weather_warning_thresholds"]},
            strong_wind={"source_refs": ["cwa.weather_warning_thresholds"]},
        ),
        source_refs=[
            "outputs/planned_eta.json",
            "normalized/routes/route_summary.json",
            "cwa.weather_warning_thresholds",
        ],
        source_details=[
            WeatherDaylightSourceRef(
                source_ref="outputs/planned_eta.json",
                title="Chilai Day 1 planned ETA fixture",
                uri="outputs/planned_eta.json",
                notes="Route/date context only; not a weather or daylight authority.",
            ),
            WeatherDaylightSourceRef(
                source_ref="normalized/routes/route_summary.json",
                title="Chilai Day 1 route summary fixture",
                uri="normalized/routes/route_summary.json",
                notes="Route corridor bbox only.",
            ),
        ],
        validation=WeatherDaylightValidation(
            notes=[
                "Manual weather/daylight evidence has not been reviewed.",
                "Do not use for authoritative dark-arrival or weather-risk decisions until reviewed.",
            ]
        ),
        notes=[
            "Candidate-only fixture for Phase 4 Pre-Trip Planning Admin.",
            "No external weather or daylight API was called.",
            "Use planned ETA context from outputs/planned_eta.json; weather and sun-window fields remain manual placeholders.",
        ],
    )


def _contour_interpretation_candidates(package: PreTripPackage) -> ContourInterpretationCandidateSet:
    source_refs = ContourSourceRefs(
        image_artifact_ref="artifact.photo.g11_hiking",
        dtm_coverage_summary_ref="dtm_coverage.chilai_nanhua_day1.20m",
        segment_dtm_coverage_ref="terrain_summary.chilai_nanhua_day1.20m",
    )
    return ContourInterpretationCandidateSet(
        artifact_id="contour_interpretation.chilai_nanhua_day1.v0",
        project_id=package.project_id,
        route_artifact_ref="artifact.gpx.chilai_nanhua_day1",
        source_artifact_refs=[
            "artifact.photo.g11_hiking",
            "dtm_coverage.chilai_nanhua_day1.20m",
            "terrain_summary.chilai_nanhua_day1.20m",
        ],
        notes=(
            "Candidate-only metadata for manual or AI-assisted contour interpretation. "
            "The raw G11_hiking image is referenced by artifact id only and is not embedded."
        ),
        candidates=[
            ContourInterpretationCandidate(
                candidate_id="contour.g11.seg_001_003",
                interpretation_mode="manual",
                source_artifact_refs=source_refs,
                target_refs=ContourTargetRefs(
                    route_artifact_ref="artifact.gpx.chilai_nanhua_day1",
                    segment_candidate_refs=["seg.001", "seg.002", "seg.003"],
                    checkpoint_candidate_refs=["cp.start", "cp.003"],
                ),
                contour_density_notes=[
                    "Manual candidate notes that the first route portion should be reviewed for close contour spacing against DTM segment coverage.",
                    "No contour lines were extracted or counted by software in this fixture.",
                ],
                terrain_shape_notes=[
                    "Review whether the image-map suggests a convex climb or spur transition before relying on ETA assumptions.",
                    "Treat this as an interpretation prompt only; DTM metadata remains the baseline for deterministic terrain coverage.",
                ],
                confidence="low",
                notes=(
                    "Metadata-only candidate linked to the G11_hiking image-map and DTM "
                    "baseline refs; not compiled into runtime safety facts."
                ),
            ),
            ContourInterpretationCandidate(
                candidate_id="contour.g11.seg_006_008",
                interpretation_mode="ai_assisted",
                source_artifact_refs=source_refs,
                target_refs=ContourTargetRefs(
                    route_artifact_ref="artifact.gpx.chilai_nanhua_day1",
                    segment_candidate_refs=["seg.006", "seg.007", "seg.008"],
                    checkpoint_candidate_refs=["cp.005", "cp.008"],
                ),
                contour_density_notes=[
                    "Potential denser-contour area should be checked by a human against the image-map and segment DTM coverage.",
                    "No OCR, image processing, or AI extraction result is stored here.",
                ],
                terrain_shape_notes=[
                    "Candidate review should compare whether the image-map implies ridge-side traversal versus direct ascent.",
                    "Any accepted terrain meaning must remain human-reviewed before downstream use.",
                ],
                notes=(
                    "AI-assisted is allowed only as a candidate source label; this fixture "
                    "stores no model output payload or observed fact."
                ),
            ),
        ],
    )


def _retreat_route_candidates() -> list[PreTripRetreatRouteCandidate]:
    provenance = PreTripProvenance(
        source_ref="artifact.gpx.chilai_nanhua_day1",
        source_kind=PreTripArtifactKind.GPX,
        uri=DEFAULT_GPX.as_posix(),
        method="manual_route_planning_assumption",
        notes=(
            "User clarified this route effectively retreats by reversing the primary route "
            "back to the entry point after entering deep mountain terrain."
        ),
    )
    return [
        PreTripRetreatRouteCandidate(
            candidate_id="retreat.chilai_nanhua_day1.return_to_entry",
            label="Return to entry via reversed primary route",
            source_refs=["artifact.gpx.chilai_nanhua_day1"],
            provenance=[provenance],
            review_state=CandidateReviewState.ACCEPTED,
            confidence="high",
            notes=(
                "Configured as both retreat and alternate route for readiness because practical "
                "off-route evacuation options are limited after entering the deep mountain section."
            ),
            entry_checkpoint_candidate_id="cp.start",
            trigger_checkpoint_candidate_id="cp.finish",
            route_point_start_index=0,
            route_point_end_index=None,
            reversed_from_primary_route=True,
            expected_use="both",
            human_review_required=False,
        )
    ]


def _map_context_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "properties": {
            "source": "manual_pretrip_fixture",
            "source_version": "0.1.0",
            "confidence": 0.6,
            "last_verified_at": "2026-05-14",
            "known_staleness_risk": "medium",
            "license_note": "local fixture metadata only",
            "notes": "Small Phase 4 GeoJSON candidate fixture; not an external crawler output.",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": "chilai_nanhua_primary_corridor",
                    "feature_type": "approved_corridor",
                    "name": "Chilai-Nanhua Day1 primary corridor candidate",
                    "corridor_half_width_m": 30,
                    "route_level": "mountain_trail_candidate",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [121.21036249036372, 24.0532973],
                        [121.2455, 24.0512],
                        [121.28079717511966, 24.045320698458436],
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": "trailhead_entry",
                    "feature_type": "trailhead",
                    "poi_type": "trailhead",
                    "name": "Entry / retreat return point",
                    "confidence": 0.75,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [121.21036249036372, 24.0532973],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "id": "deep_mountain_no_easy_exit",
                    "feature_type": "terrain_constraint",
                    "hazard_type": "limited_retreat_options",
                    "name": "Deep mountain section with limited retreat options",
                    "l2_duration_s": 60,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [121.238, 24.058],
                            [121.282, 24.058],
                            [121.282, 24.042],
                            [121.238, 24.042],
                            [121.238, 24.058],
                        ]
                    ],
                },
            },
        ],
    }


def _review_log(package, map_candidates: dict) -> PreTripHumanReviewLog:
    reviews: list[PreTripHumanReview] = []

    for candidate in package.checkpoint_candidates:
        reviews.append(
            _review(
                reviewed_ref=candidate.candidate_id,
                reviewed_ref_kind="checkpoint",
                decision="accepted",
                source_candidate=candidate,
                notes="Accepted for first reviewed MissionGraph compile fixture.",
            )
        )
    for candidate in package.segment_candidates:
        reviews.append(
            _review(
                reviewed_ref=candidate.candidate_id,
                reviewed_ref_kind="segment",
                decision="accepted",
                source_candidate=candidate,
                notes="Accepted as deterministic GPX-derived segment candidate for reviewed compile fixture.",
            )
        )
    for candidate in package.retreat_route_candidates:
        reviews.append(
            _review(
                reviewed_ref=candidate.candidate_id,
                reviewed_ref_kind="retreat_route",
                decision="accepted",
                source_candidate=candidate,
                notes="Accepted user clarification: practical retreat/alternate is returning to entry by reverse route.",
            )
        )

    for collection_name in ("corridor_candidates", "poi_candidates", "hazard_candidates"):
        for candidate in map_candidates.get(collection_name, []):
            reviews.append(
                _review(
                    reviewed_ref=candidate["candidate_id"],
                    reviewed_ref_kind="map_candidate",
                    decision="noted",
                    source_candidate=candidate,
                    notes="Map candidate retained for planning context; not compiled into Phase 1 MissionGraph in this slice.",
                )
            )

    for candidate in package.route_guide_timing_candidates:
        reviews.append(
            _review(
                reviewed_ref=candidate.candidate_id,
                reviewed_ref_kind="route_guide_timing",
                decision="noted",
                source_candidate=candidate,
                notes="Timing assumption captured from user-provided OCR; ETA calibration remains a later slice.",
            )
        )

    for reference in package.planning_references:
        reviews.append(
            _review(
                reviewed_ref=reference.reference_id,
                reviewed_ref_kind="planning_reference",
                decision="noted",
                source_candidate=reference,
                notes="Planning reference retained as Artifact/ModelInterpretation context, not ObservedFact.",
            )
        )

    return PreTripHumanReviewLog(
        log_id="review_log.chilai_nanhua_day1.v0",
        reviews=tuple(reviews),
    )


def _review(
    *,
    reviewed_ref: str,
    reviewed_ref_kind: str,
    decision: str,
    source_candidate,
    notes: str,
) -> PreTripHumanReview:
    return PreTripHumanReview(
        review_id=f"review.chilai_nanhua_day1.{reviewed_ref}",
        reviewer_id="person.trip_leader",
        reviewed_ref=reviewed_ref,
        reviewed_ref_kind=reviewed_ref_kind,
        reviewed_at="2026-05-14T16:00:00+08:00",
        decision=decision,
        notes=notes,
        source_candidate_snapshot_hash=source_candidate_snapshot_hash(source_candidate),
    )


def _planning_references() -> list[PreTripPlanningReference]:
    return [
        PreTripPlanningReference(
            reference_id="planning_ref.joyhike.main_site",
            title="Joyhike main site",
            uri="https://joyhike.com/",
            reference_type="reference_product",
            scout_meaning=(
                "Reference product precedent for Taiwan hiking planning primitives; "
                "not the controlling Scout data source."
            ),
            artifact_treatment=["Artifact", "ModelInterpretation", "HumanReview", "DerivedMeasurement"],
            supported_primitives=[
                "route_nodes",
                "segment_distance",
                "elevation_gain_loss",
                "daily_ascent_descent",
                "estimated_walking_time",
                "rest_time",
                "weather",
                "permit_hut_logistics",
                "group_coordination",
            ],
            notes="Registered as implementation context only; no crawler or dynamic app extraction in this slice.",
        ),
        PreTripPlanningReference(
            reference_id="planning_ref.joyhike.route_planning_model",
            title="Joyhike blog route planning model",
            uri="https://blog.joyhike.com/2022/05/trailslevel.html",
            reference_type="route_planning_method",
            scout_meaning="Reference model for planning primitives and route difficulty context.",
            artifact_treatment=["Artifact", "ModelInterpretation", "HumanReview", "DerivedMeasurement"],
            supported_primitives=[
                "route_nodes",
                "segment_distance",
                "elevation_gain_loss",
                "estimated_walking_time",
                "rest_time",
                "weather",
            ],
            notes="Planning reference only; accepted assumptions require human review.",
        ),
        PreTripPlanningReference(
            reference_id="planning_ref.ptt.sunriver_timing",
            title="PTT Hiking 上河時間與步程計算",
            uri="https://www.ptt.cc/bbs/Hiking/M.1696430399.A.151.html",
            reference_type="community_timing_evidence",
            scout_meaning="Community evidence for route-guide timing and fitness calibration assumptions.",
            artifact_treatment=["Artifact", "ModelInterpretation", "HumanReview", "DerivedMeasurement"],
            supported_primitives=[
                "route_guide_segment_time_minutes",
                "personal_route_guide_multiplier",
                "team_route_guide_multiplier",
                "pace_multiplier_basis",
                "fixed_rest_minutes",
                "conservative_long_day_adjustment",
                "eta_at_checkpoint",
                "eta_at_camp_or_overnight_point",
                "dark_arrival_margin_minutes",
                "planned_vs_actual_calibration_refs",
            ],
            notes="Not an ObservedFact; calculations become DerivedMeasurement only after assumptions are explicit.",
        ),
    ]


def _route_guide_timing_candidates() -> list[PreTripRouteGuideTimingCandidate]:
    provenance = PreTripProvenance(
        source_ref="artifact.photo.g11_hiking",
        source_kind=PreTripArtifactKind.PHOTO,
        uri=DEFAULT_IMAGE.as_posix(),
        method="user_provided_ocr_transcription",
        notes="User-provided OCR text from G11 能高越嶺步程示意圖; no automated image extraction in this slice.",
    )
    candidates = [
        PreTripRouteGuideTimingCandidate(
            candidate_id="timing_assumption.chilai_nanhua_day1.schema",
            label="Route-guide timing and fitness calibration assumption schema",
            source_refs=["planning_ref.ptt.sunriver_timing"],
            provenance=[
                PreTripProvenance(
                    source_ref="planning_ref.ptt.sunriver_timing",
                    source_kind=PreTripArtifactKind.PLANNING_REFERENCES,
                    uri="https://www.ptt.cc/bbs/Hiking/M.1696430399.A.151.html",
                    method="manual_schema_registration",
                    notes="Schema placeholder only; no article scraping or AI extraction in this slice.",
                )
            ],
            review_state=CandidateReviewState.NEEDS_REVIEW,
            confidence="unknown",
            notes=(
                "Optional fields reserved for reviewed guide-time and pace multiplier assumptions; "
                "ETA calculation is intentionally deferred."
            ),
            segment_candidate_id=None,
            route_branch=None,
            from_node_name=None,
            to_node_name=None,
            movement_label=None,
            route_guide_segment_time_minutes=None,
            route_guide_return_time_minutes=None,
            route_guide_ascent_time_minutes=None,
            route_guide_descent_time_minutes=None,
            personal_route_guide_multiplier=None,
            team_route_guide_multiplier=None,
            pace_multiplier_basis=PaceMultiplierBasis.MIXED_UNKNOWN,
            fixed_rest_minutes=0,
            conservative_long_day_adjustment=1.0,
            eta_at_checkpoint=None,
            eta_at_camp_or_overnight_point=None,
            dark_arrival_margin_minutes=None,
            planned_vs_actual_calibration_refs=[],
            vehicle_or_shuttle_likely=False,
            vehicle_access_note=None,
            readiness_eta_policy="total_elapsed_time_including_normal_rest",
        )
    ]
    for index, entry in enumerate(_g11_route_guide_entries(), start=1):
        candidates.append(
            PreTripRouteGuideTimingCandidate(
                candidate_id=f"timing.g11_nenggao.{index:03d}",
                label=f"{entry['from_node_name']} -> {entry['to_node_name']}",
                source_refs=["artifact.photo.g11_hiking"],
                provenance=[provenance],
                review_state=CandidateReviewState.NEEDS_REVIEW,
                confidence="medium",
                notes=(
                    "User-provided route-guide timing transcription. Timing is for planning calibration only "
                    "until reviewed against the route plan."
                ),
                segment_candidate_id=None,
                route_branch=entry["route_branch"],
                from_node_name=entry["from_node_name"],
                to_node_name=entry["to_node_name"],
                movement_label=entry.get("movement_label"),
                route_guide_segment_time_minutes=entry.get("route_guide_segment_time_minutes"),
                route_guide_return_time_minutes=entry.get("route_guide_return_time_minutes"),
                route_guide_ascent_time_minutes=entry.get("route_guide_ascent_time_minutes"),
                route_guide_descent_time_minutes=entry.get("route_guide_descent_time_minutes"),
                pace_multiplier_basis=PaceMultiplierBasis.MIXED_UNKNOWN,
                fixed_rest_minutes=0,
                conservative_long_day_adjustment=1.0,
                vehicle_or_shuttle_likely=entry.get("vehicle_or_shuttle_likely", False),
                vehicle_access_note=entry.get("vehicle_access_note"),
                readiness_eta_policy="total_elapsed_time_including_normal_rest",
            )
        )
    return candidates


def _g11_route_guide_entries() -> list[dict]:
    vehicle_note = "OCR note: segment has vehicle icon or likely road/shuttle access."
    return [
        {
            "route_branch": "main",
            "from_node_name": "霧社",
            "to_node_name": "廬山部落",
            "route_guide_segment_time_minutes": 30,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "main",
            "from_node_name": "廬山部落",
            "to_node_name": "屯原登山口",
            "route_guide_segment_time_minutes": 30,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "main",
            "from_node_name": "屯原登山口",
            "to_node_name": "雲海保線所",
            "route_guide_segment_time_minutes": 120,
            "route_guide_return_time_minutes": 100,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "雲海保線所",
            "to_node_name": "天池山莊",
            "route_guide_segment_time_minutes": 210,
            "route_guide_return_time_minutes": 180,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "天池山莊",
            "to_node_name": "縣界埡口",
            "route_guide_segment_time_minutes": 50,
            "route_guide_return_time_minutes": 55,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "縣界埡口",
            "to_node_name": "檜林保線所",
            "route_guide_segment_time_minutes": 120,
            "route_guide_return_time_minutes": 240,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "檜林保線所",
            "to_node_name": "五甲崩山",
            "route_guide_segment_time_minutes": 140,
            "route_guide_return_time_minutes": 170,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "五甲崩山",
            "to_node_name": "奇萊保線所",
            "route_guide_segment_time_minutes": 180,
            "route_guide_return_time_minutes": 260,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "main",
            "from_node_name": "奇萊保線所",
            "to_node_name": "銅門",
            "route_guide_segment_time_minutes": 120,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "main",
            "from_node_name": "銅門",
            "to_node_name": "仁壽橋",
            "route_guide_segment_time_minutes": 5,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "main",
            "from_node_name": "仁壽橋",
            "to_node_name": "花蓮",
            "route_guide_segment_time_minutes": 30,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "main",
            "from_node_name": "花蓮",
            "to_node_name": "鯉魚潭",
            "route_guide_segment_time_minutes": 10,
            "vehicle_or_shuttle_likely": True,
            "vehicle_access_note": vehicle_note,
        },
        {
            "route_branch": "branch_chilai_south_peak",
            "from_node_name": "天池山莊",
            "to_node_name": "天池岔路口",
            "route_guide_ascent_time_minutes": 60,
            "route_guide_descent_time_minutes": 40,
            "movement_label": "上行/下行",
        },
        {
            "route_branch": "branch_chilai_south_peak",
            "from_node_name": "天池岔路口",
            "to_node_name": "南峰登山口",
            "route_guide_ascent_time_minutes": 20,
            "route_guide_descent_time_minutes": 15,
            "movement_label": "上行/下行",
        },
        {
            "route_branch": "branch_chilai_south_peak",
            "from_node_name": "南峰登山口",
            "to_node_name": "奇萊主山南峰",
            "route_guide_segment_time_minutes": 40,
            "route_guide_return_time_minutes": 60,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "branch_nanhua",
            "from_node_name": "天池岔路口",
            "to_node_name": "南華山",
            "route_guide_segment_time_minutes": 40,
            "route_guide_return_time_minutes": 30,
            "movement_label": "去程/回程",
        },
        {
            "route_branch": "branch_nenggao_main_peak",
            "from_node_name": "縣界埡口",
            "to_node_name": "卡賀爾山",
            "route_guide_ascent_time_minutes": 140,
            "route_guide_descent_time_minutes": 170,
            "movement_label": "上行/下行",
        },
        {
            "route_branch": "branch_nenggao_main_peak",
            "from_node_name": "縣界埡口",
            "to_node_name": "能高主峰",
            "route_guide_ascent_time_minutes": 140,
            "route_guide_descent_time_minutes": 160,
            "movement_label": "上行/下行",
        },
    ]


if __name__ == "__main__":
    main()
