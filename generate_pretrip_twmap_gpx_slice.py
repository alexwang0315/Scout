from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from generate_pretrip_chilai_fixture import (
    DEFAULT_DTM_DIRS,
    DEFAULT_IMAGE,
    DEFAULT_OUTPUT_DIR,
    _planning_references,
    _retreat_route_candidates,
    _route_guide_timing_candidates,
)
from pretrip_gpx_corpus import (
    TW_MAP_GPX_PRIMARY_FILENAME,
    build_checkpoint_event_candidates,
    build_reference_track_summary,
    build_reference_track_display_geometry,
    build_segment_display_geometry,
    list_reference_gpx_paths,
    write_json,
)
from pretrip_geojson_import import import_pretrip_geojson_candidates
from pretrip_models import PreTripCheckpointCandidate
from pretrip_readiness import evaluate_pretrip_readiness, load_skill_config_manifest
from pretrip_source_ingest import build_pretrip_package
from pretrip_terrain_summary import summarize_segment_terrain_metadata


DEFAULT_CORPUS_DIR = Path("/Users/alexwang0315/Downloads/twmap-gpx-yunhai")


def _build_twmap_map_context(
    *,
    project_id: str,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
) -> dict:
    coordinates = [
        [round(candidate.lon, 7), round(candidate.lat, 7)]
        for candidate in checkpoint_candidates
    ]
    if len(coordinates) < 2:
        raise ValueError("At least two checkpoint candidates are required for map context")

    return {
        "type": "FeatureCollection",
        "properties": {
            "source": "twmap_gpx_corpus_fixture",
            "source_version": "0.1.0",
            "last_verified_at": "2026-05-21",
            "confidence": 0.66,
            "known_staleness_risk": "medium",
            "license_note": "Derived fixture metadata from local TWMap GPX corpus; raw GPX is not copied into repo.",
            "notes": (
                "Map context（地圖脈絡）is a planning candidate display layer derived "
                "from CP coordinates; it is not runtime safety truth（現場安全真相）."
            ),
        },
        "features": [
            {
                "type": "Feature",
                "id": f"{project_id}.twmap_primary_cp_corridor",
                "properties": {
                    "feature_type": "approved_corridor",
                    "name": "Nengao-Andongjun primary CP corridor candidate",
                    "route_level": "planning_candidate",
                    "corridor_half_width_m": 30.0,
                    "source": "twmap_gpx_corpus_fixture",
                    "source_version": "0.1.0",
                    "confidence": 0.66,
                    "known_staleness_risk": "medium",
                    "notes": (
                        "Derived from checkpoint candidate coordinates only; primary GPX "
                        "internal track points remain preserved in the local source file."
                    ),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
            },
            {
                "type": "Feature",
                "id": f"{project_id}.twmap_primary_start",
                "properties": {
                    "feature_type": "poi",
                    "name": "Primary GPX start candidate",
                    "poi_type": "trailhead",
                    "source": "twmap_gpx_corpus_fixture",
                    "source_version": "0.1.0",
                    "confidence": 0.66,
                    "known_staleness_risk": "medium",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": coordinates[0],
                },
            },
            {
                "type": "Feature",
                "id": f"{project_id}.twmap_primary_finish",
                "properties": {
                    "feature_type": "poi",
                    "name": "Primary GPX finish candidate",
                    "poi_type": "trailhead",
                    "source": "twmap_gpx_corpus_fixture",
                    "source_version": "0.1.0",
                    "confidence": 0.66,
                    "known_staleness_risk": "medium",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": coordinates[-1],
                },
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace the Chilai pretrip route slice with the TWMap GPX corpus metadata."
    )
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--primary-filename", default=TW_MAP_GPX_PRIMARY_FILENAME)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--dtm-dir", type=Path, action="append", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    primary_gpx, reference_gpx_paths = list_reference_gpx_paths(
        args.corpus_dir,
        primary_filename=args.primary_filename,
    )
    dtm_dirs = args.dtm_dir if args.dtm_dir is not None else DEFAULT_DTM_DIRS
    package = build_pretrip_package(
        package_id="pretrip.chilai_nanhua_day1.v0",
        project_id="chilai_nanhua_day1",
        version="0.1.0",
        gpx_path=primary_gpx,
        image_path=args.image,
        dtm_dirs=dtm_dirs,
        planning_references=_planning_references(),
        retreat_route_candidates=_retreat_route_candidates(),
        route_guide_timing_candidates=_route_guide_timing_candidates(),
    )
    if package.retreat_route_candidates and package.checkpoint_candidates:
        finish_index = package.checkpoint_candidates[-1].route_point_index
        for candidate in package.retreat_route_candidates:
            candidate.provenance = [
                provenance.model_copy(update={"uri": primary_gpx.resolve().as_posix()})
                for provenance in candidate.provenance
            ]
            if candidate.route_point_end_index is None:
                candidate.route_point_end_index = finish_index
            if candidate.distance_m == 0.0:
                candidate.distance_m = package.route_summary.distance_m

    output_dir = args.output_dir
    write_json(output_dir / "outputs" / "pretrip_package.json", package.model_dump(mode="json"))
    write_json(output_dir / "normalized" / "routes" / "route_summary.json", package.route_summary.model_dump(mode="json"))
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
    if package.dtm_coverage_summary is not None:
        write_json(
            output_dir / "normalized" / "terrain" / "dtm_coverage_summary.json",
            package.dtm_coverage_summary.model_dump(mode="json"),
        )
        terrain_summary = summarize_segment_terrain_metadata(
            segment_candidates=package.segment_candidates,
            dtm_coverage_summary=package.dtm_coverage_summary,
            summary_id=f"terrain_summary.{package.project_id}.twmap_20m_dem",
        )
        write_json(
            output_dir / "normalized" / "terrain" / "segment_dtm_coverage.json",
            terrain_summary.model_dump(mode="json"),
        )

    map_context = _build_twmap_map_context(
        project_id=package.project_id,
        checkpoint_candidates=package.checkpoint_candidates,
    )
    write_json(output_dir / "normalized" / "map" / "map_context.geojson", map_context)
    map_candidates = import_pretrip_geojson_candidates(
        map_context,
        uri=(output_dir / "normalized" / "map" / "map_context.geojson").as_posix(),
        source_ref="normalized/map/map_context.geojson",
    )
    write_json(
        output_dir / "candidates" / "map_candidates.json",
        map_candidates.model_dump(mode="json"),
    )

    reference_tracks = build_reference_track_summary(
        project_id=package.project_id,
        primary_gpx_path=primary_gpx,
        reference_gpx_paths=reference_gpx_paths,
    )
    write_json(output_dir / "outputs" / "reference_tracks.json", reference_tracks)
    checkpoint_events = build_checkpoint_event_candidates(
        project_id=package.project_id,
        route_gpx_path=primary_gpx,
        checkpoint_candidates=package.checkpoint_candidates,
    )
    write_json(output_dir / "outputs" / "checkpoint_events.json", checkpoint_events)
    segment_display_geometry = build_segment_display_geometry(
        project_id=package.project_id,
        route_gpx_path=primary_gpx,
        segment_candidates=package.segment_candidates,
    )
    write_json(output_dir / "outputs" / "segment_display_geometry.json", segment_display_geometry)
    reference_track_display_geometry = build_reference_track_display_geometry(
        project_id=package.project_id,
        primary_gpx_path=primary_gpx,
        reference_gpx_paths=reference_gpx_paths,
    )
    write_json(
        output_dir / "outputs" / "reference_track_display_geometry.json",
        reference_track_display_geometry,
    )

    project_path = output_dir / "project.json"
    project_payload = {}
    if project_path.exists():
        import json

        project_payload = json.loads(project_path.read_text(encoding="utf-8"))
    project_payload.update(
        {
            "project_id": package.project_id,
            "package_ref": "outputs/pretrip_package.json",
            "route_summary_ref": "normalized/routes/route_summary.json",
            "map_context_ref": "normalized/map/map_context.geojson",
            "map_candidates_ref": "candidates/map_candidates.json",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "retreat_routes_ref": "candidates/retreat_routes.json",
            "planning_references_ref": "candidates/planning_references.json",
            "route_guide_timing_ref": "candidates/route_guide_timing.json",
            "reference_tracks_ref": "outputs/reference_tracks.json",
            "reference_track_display_geometry_ref": (
                "outputs/reference_track_display_geometry.json"
            ),
            "checkpoint_events_ref": "outputs/checkpoint_events.json",
            "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
            "source_artifact_count": len(package.source_artifacts),
            "planning_reference_count": len(package.planning_references),
            "checkpoint_candidate_count": len(package.checkpoint_candidates),
            "segment_candidate_count": len(package.segment_candidates),
            "map_corridor_candidate_count": len(map_candidates.corridor_candidates),
            "map_hazard_candidate_count": len(map_candidates.hazard_candidates),
            "map_poi_candidate_count": len(map_candidates.poi_candidates),
            "dtm_candidate_tile_count": (
                len(package.dtm_coverage_summary.candidate_tiles)
                if package.dtm_coverage_summary is not None
                else 0
            ),
            "retreat_route_candidate_count": len(package.retreat_route_candidates),
            "route_guide_timing_candidate_count": len(package.route_guide_timing_candidates),
            "reference_track_count": len(reference_gpx_paths),
            "reference_track_display_geometry_count": (
                reference_track_display_geometry["reference_track_count"]
            ),
            "checkpoint_event_count": checkpoint_events["event_count"],
            "segment_display_geometry_count": segment_display_geometry["segment_count"],
        }
    )
    skill_config_manifest_ref = project_payload.get("skill_config_manifest_ref", "candidates/skill_config_manifest.json")
    skill_config_manifest_path = output_dir / skill_config_manifest_ref
    if skill_config_manifest_path.exists():
        readiness_report = evaluate_pretrip_readiness(
            {
                "route_id": package.project_id,
                "route_days": 5,
                "route_kind": "traverse",
                "distance_m": package.route_summary.distance_m,
                "retreat_routes": [
                    candidate.model_dump(mode="json") for candidate in package.retreat_route_candidates
                ],
            },
            skill_config_manifest=load_skill_config_manifest(skill_config_manifest_path),
        )
        write_json(output_dir / "outputs" / "readiness_report.json", asdict(readiness_report))
        project_payload["readiness_report_ref"] = "outputs/readiness_report.json"
    write_json(project_path, project_payload)


if __name__ == "__main__":
    main()
