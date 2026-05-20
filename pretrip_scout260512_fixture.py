from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pretrip_candidate_generation import generate_pretrip_candidates_from_gpx
from pretrip_models import (
    CandidateReviewState,
    PreTripArtifactKind,
    PreTripPackage,
    PreTripPlanningReference,
    PreTripProvenance,
    PreTripRetreatRouteCandidate,
    PreTripSourceArtifact,
)
from pretrip_source_ingest import summarize_gpx, write_json


PROJECT_ID = "scout_260512_field_regression"
PACKAGE_ID = "pretrip.scout_260512_field_regression.v0"
FIXTURE_KIND = "field-data-to-fixtures-regression"
DEFAULT_PROJECT_ROOT = (
    Path("tests")
    / "fixtures"
    / "pretrip"
    / "projects"
    / "scout_260512_field_regression"
)

FIELD_CASE_REF = "tests/fixtures/field_cases/scout_260512_golden.json"
FIELD_ROUTE_REF = "tests/fixtures/routes/scout_260512_field_route.gpx"
FIELD_MAP_REF = "tests/fixtures/maps/scout_260512_overpass_map_context.geojson"
FIELD_MAP_QUERY_REF = "tests/fixtures/maps/scout_260512_overpass_query.ql"
FIELD_MISSION_REF = "tests/fixtures/mission_graph/scout_260512_field_mission.json"
FIELD_ROUTE_PROGRESS_REF = "tests/fixtures/route_progress/scout_260512_field_config.json"


def build_scout_260512_pretrip_fixture(repo_root: Path | str = Path(".")) -> dict[str, Any]:
    root = Path(repo_root)
    field_case = _load_json(root / FIELD_CASE_REF)
    route_summary = summarize_gpx(
        root / FIELD_ROUTE_REF,
        "artifact.route.scout_260512_field_route_gpx",
    )
    candidate_result = generate_pretrip_candidates_from_gpx(
        root / FIELD_ROUTE_REF,
        checkpoint_spacing_m=1_000.0,
        source_ref=route_summary.artifact_id,
    )
    checkpoints = [
        candidate.model_copy(
            update={
                "provenance": [_route_candidate_provenance(route_summary.artifact_id)],
                "review_state": CandidateReviewState.NEEDS_REVIEW,
                "notes": (
                    "Field-data regression candidate generated from the existing "
                    "scout_260512 route fixture; human review required before any "
                    "future mission compile."
                ),
            }
        )
        for candidate in candidate_result.checkpoint_candidates
    ]
    segments = [
        candidate.model_copy(
            update={
                "provenance": [_route_candidate_provenance(route_summary.artifact_id)],
                "review_state": CandidateReviewState.NEEDS_REVIEW,
                "notes": (
                    "Field-data regression segment placeholder; not a primary "
                    "mountain calibration segment."
                ),
            }
        )
        for candidate in candidate_result.segment_candidates
    ]
    source_artifacts = _source_artifacts(field_case, route_summary.artifact_id)
    package = PreTripPackage(
        package_id=PACKAGE_ID,
        project_id=PROJECT_ID,
        version="0.1.0",
        status="candidate",
        route_summary=route_summary,
        source_artifacts=source_artifacts,
        planning_references=_planning_references(),
        checkpoint_candidates=checkpoints,
        segment_candidates=segments,
        retreat_route_candidates=_retreat_routes(route_summary.artifact_id),
        readiness_notes=[
            "scout_260512 is explicitly a field-data-to-fixtures regression case.",
            "This package is not the primary mountain calibration project.",
            "Fixture outputs contain metadata and reference summaries only; raw Apple Watch payloads are not embedded.",
            "Candidate CP/segment/POI/hazard placeholders require human review before any future compilation.",
        ],
    )
    map_summary = _map_summary(field_case)
    map_candidates = _map_candidate_placeholders(field_case)
    project = _project_index(
        package=package,
        field_case=field_case,
        map_summary=map_summary,
        map_candidates=map_candidates,
    )
    return {
        "project": project,
        "route_summary": route_summary.model_dump(mode="json"),
        "map_summary": map_summary,
        "package": package.model_dump(mode="json"),
        "checkpoints": [candidate.model_dump(mode="json") for candidate in checkpoints],
        "segments": [candidate.model_dump(mode="json") for candidate in segments],
        "map_candidates": map_candidates,
    }


def write_scout_260512_pretrip_fixture(
    repo_root: Path | str = Path("."),
    *,
    project_root: Path | str = DEFAULT_PROJECT_ROOT,
) -> dict[str, Any]:
    root = Path(repo_root)
    fixture = build_scout_260512_pretrip_fixture(root)
    target = root / project_root

    outputs = {
        "project.json": fixture["project"],
        "normalized/routes/route_summary.json": fixture["route_summary"],
        "normalized/map/map_summary.json": fixture["map_summary"],
        "outputs/pretrip_package.json": fixture["package"],
        "candidates/checkpoints.json": fixture["checkpoints"],
        "candidates/segments.json": fixture["segments"],
        "candidates/map_candidates.json": fixture["map_candidates"],
    }
    for relative_path, payload in outputs.items():
        write_json(target / relative_path, payload)
    return fixture


def load_scout_260512_pretrip_fixture(
    project_root: Path | str = DEFAULT_PROJECT_ROOT,
) -> dict[str, Any]:
    root = Path(project_root)
    return {
        "project": _load_json(root / "project.json"),
        "route_summary": _load_json(root / "normalized" / "routes" / "route_summary.json"),
        "map_summary": _load_json(root / "normalized" / "map" / "map_summary.json"),
        "package": _load_json(root / "outputs" / "pretrip_package.json"),
        "checkpoints": _load_json(root / "candidates" / "checkpoints.json"),
        "segments": _load_json(root / "candidates" / "segments.json"),
        "map_candidates": _load_json(root / "candidates" / "map_candidates.json"),
    }


def _source_artifacts(field_case: dict[str, Any], route_artifact_id: str) -> list[PreTripSourceArtifact]:
    source_version = field_case["map_context_summary"]["source_version"]
    return [
        _source_artifact(
            artifact_id="artifact.field_case.scout_260512_golden",
            kind=PreTripArtifactKind.OTHER,
            uri=FIELD_CASE_REF,
            source_ref="scout_260512_field_golden",
            method="pretrip-fixture-builder.field_case_manifest_ref",
            metadata={
                "case_id": field_case["case_id"],
                "description": field_case["description"],
                "raw_payload_embedded": False,
                "source_file_count": len(field_case.get("source_files", [])),
            },
        ),
        _source_artifact(
            artifact_id=route_artifact_id,
            kind=PreTripArtifactKind.GPX,
            uri=FIELD_ROUTE_REF,
            media_type="application/gpx+xml",
            source_ref="scout_260512_field_route",
            method="pretrip-fixture-builder.route_summary_ref",
            metadata={"raw_payload_embedded": False, "summary_ref": "normalized/routes/route_summary.json"},
        ),
        _source_artifact(
            artifact_id="artifact.map.scout_260512_overpass_summary",
            kind=PreTripArtifactKind.OTHER,
            uri=FIELD_MAP_REF,
            media_type="application/geo+json",
            source_ref="scout_260512_overpass_map_context",
            method="pretrip-fixture-builder.map_summary_ref",
            metadata={
                "raw_payload_embedded": False,
                "summary_ref": "normalized/map/map_summary.json",
                "source_version": source_version,
            },
        ),
    ]


def _source_artifact(
    *,
    artifact_id: str,
    kind: PreTripArtifactKind,
    uri: str,
    source_ref: str,
    method: str,
    metadata: dict[str, Any],
    media_type: str | None = "application/json",
) -> PreTripSourceArtifact:
    return PreTripSourceArtifact(
        artifact_id=artifact_id,
        kind=kind,
        uri=uri,
        media_type=media_type,
        sha256=None,
        size_bytes=None,
        provenance=PreTripProvenance(
            source_ref=source_ref,
            source_kind=kind,
            uri=uri,
            method=method,
            notes="Reference-only source artifact for a Phase 4 regression fixture.",
        ),
        metadata=metadata,
    )


def _planning_references() -> list[PreTripPlanningReference]:
    return [
        PreTripPlanningReference(
            reference_id="planning_ref.scout_260512.fixture_boundary",
            title="Scout 260512 field-data regression boundary",
            uri="docs/specs/pre-trip-planning-admin.md",
            reference_type="route_planning_method",
            scout_meaning=(
                "Use scout_260512 to verify field evidence can be summarized into "
                "pre-trip fixture references without making it the primary mountain calibration."
            ),
            artifact_treatment=["Artifact", "DerivedMeasurement", "ModelInterpretation"],
            supported_primitives=["source_refs", "route_summary", "map_summary", "candidate_placeholders"],
            notes="Regression-only; not a live Phase 1 runtime input.",
        )
    ]


def _retreat_routes(route_artifact_id: str) -> list[PreTripRetreatRouteCandidate]:
    return [
        PreTripRetreatRouteCandidate(
            candidate_id="retreat.scout_260512.return_to_start.placeholder",
            label="Return along field route to start placeholder",
            source_refs=[route_artifact_id],
            provenance=[
                PreTripProvenance(
                    source_ref=route_artifact_id,
                    source_kind=PreTripArtifactKind.GPX,
                    uri=FIELD_ROUTE_REF,
                    method="pretrip-fixture-builder.retreat_placeholder",
                    notes="Placeholder only; human review required before planning use.",
                )
            ],
            review_state=CandidateReviewState.NEEDS_REVIEW,
            confidence="low",
            notes="Generated as a regression placeholder, not a mountain route recommendation.",
            entry_checkpoint_candidate_id="cp.start",
            trigger_checkpoint_candidate_id="cp.finish",
            reversed_from_primary_route=True,
            expected_use="retreat",
            human_review_required=True,
        )
    ]


def _route_candidate_provenance(route_artifact_id: str) -> PreTripProvenance:
    return PreTripProvenance(
        source_ref=route_artifact_id,
        source_kind=PreTripArtifactKind.GPX,
        uri=FIELD_ROUTE_REF,
        method="pretrip_candidate_generation.generate_pretrip_candidates_from_gpx",
        notes="Deterministic distance-spaced checkpoint and adjacent segment candidate generation.",
    )


def _map_summary(field_case: dict[str, Any]) -> dict[str, Any]:
    summary = field_case["map_context_summary"]
    return {
        "summary_id": "map_summary.scout_260512_overpass.v0",
        "source_ref": "artifact.map.scout_260512_overpass_summary",
        "map_context_ref": FIELD_MAP_REF,
        "overpass_query_ref": FIELD_MAP_QUERY_REF,
        "bbox": field_case["bbox"],
        "source": summary["source"],
        "source_version": summary["source_version"],
        "confidence": summary["confidence"],
        "known_staleness_risk": summary["known_staleness_risk"],
        "corridor_count": summary["corridors"],
        "poi_count": summary["pois"],
        "hazard_count": summary["hazards"],
        "route_level_counts": summary["route_level_counts"],
        "raw_payload_embedded": False,
        "notes": [
            "Summary is derived from the existing Overpass map fixture.",
            "GeoJSON features are not embedded in the pre-trip regression outputs.",
        ],
    }


def _map_candidate_placeholders(field_case: dict[str, Any]) -> dict[str, Any]:
    bbox = field_case["bbox"]
    mid_lat = round((bbox["south"] + bbox["north"]) / 2, 6)
    mid_lon = round((bbox["west"] + bbox["east"]) / 2, 6)
    return {
        "artifact_kind": "scout_260512_pretrip_map_candidate_placeholders",
        "project_id": PROJECT_ID,
        "status": "candidate_only",
        "source_refs": [
            "artifact.field_case.scout_260512_golden",
            "artifact.map.scout_260512_overpass_summary",
        ],
        "raw_payloads_embedded": False,
        "corridor_candidates": [
            {
                "candidate_id": "map.corridor.scout_260512.field_bbox.placeholder",
                "label": "Scout 260512 field route corridor placeholder",
                "review_state": "needs_review",
                "review_required": True,
                "source_refs": ["artifact.map.scout_260512_overpass_summary"],
                "summary": {
                    "bbox": bbox,
                    "corridor_count": field_case["map_context_summary"]["corridors"],
                    "route_level_counts": field_case["map_context_summary"]["route_level_counts"],
                },
                "notes": "Placeholder summarizes existing map coverage; does not embed GeoJSON features.",
            }
        ],
        "poi_candidates": [
            {
                "candidate_id": "map.poi.scout_260512.field_midpoint.placeholder",
                "label": "Field midpoint POI placeholder",
                "review_state": "needs_review",
                "review_required": True,
                "source_refs": ["artifact.field_case.scout_260512_golden"],
                "coordinate": {"lat": mid_lat, "lon": mid_lon},
                "poi_type": "field_regression_anchor",
                "notes": "Synthetic placeholder for fixture regression only.",
            }
        ],
        "hazard_candidates": [
            {
                "candidate_id": "map.hazard.scout_260512.weak_gps_review.placeholder",
                "label": "Weak GPS review placeholder",
                "review_state": "needs_review",
                "review_required": True,
                "source_refs": ["artifact.field_case.scout_260512_golden"],
                "hazard_type": "field_data_quality_review",
                "notes": "Represents a review prompt from field evidence, not a live hazard assertion.",
            }
        ],
    }


def _project_index(
    *,
    package: PreTripPackage,
    field_case: dict[str, Any],
    map_summary: dict[str, Any],
    map_candidates: dict[str, Any],
) -> dict[str, Any]:
    return {
        "project_id": PROJECT_ID,
        "package_ref": "outputs/pretrip_package.json",
        "route_summary_ref": "normalized/routes/route_summary.json",
        "map_summary_ref": "normalized/map/map_summary.json",
        "checkpoint_candidates_ref": "candidates/checkpoints.json",
        "segment_candidates_ref": "candidates/segments.json",
        "map_candidates_ref": "candidates/map_candidates.json",
        "fixture_kind": FIXTURE_KIND,
        "source_case_id": field_case["case_id"],
        "source_refs": [
            FIELD_CASE_REF,
            FIELD_ROUTE_REF,
            FIELD_MAP_REF,
            FIELD_MAP_QUERY_REF,
            FIELD_MISSION_REF,
            FIELD_ROUTE_PROGRESS_REF,
        ],
        "route_summary_artifact_id": package.route_summary.artifact_id,
        "map_summary_id": map_summary["summary_id"],
        "checkpoint_candidate_count": len(package.checkpoint_candidates),
        "segment_candidate_count": len(package.segment_candidates),
        "poi_candidate_count": len(map_candidates["poi_candidates"]),
        "hazard_candidate_count": len(map_candidates["hazard_candidates"]),
        "source_artifact_count": len(package.source_artifacts),
        "field_data_to_fixtures_regression": True,
        "primary_mountain_calibration": False,
        "mountain_calibration_project_id": "chilai_nanhua_day1",
        "compiled_into_mountain_calibration": False,
        "compiled_mission_graph_ref": None,
        "phase1_live_runtime_touched": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Scout 260512 remains a field-data-to-fixtures regression case.",
            "Chilai-Nanhua Day 1 remains the primary mountain calibration fixture.",
            "No raw Apple Watch, GPX, or map payloads are copied into this project directory.",
        ],
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    write_scout_260512_pretrip_fixture()
