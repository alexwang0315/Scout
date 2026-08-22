from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from admin_imagery_sources import imagery_source_for_project
from admin_local_raster_tiles import (
    build_imagery_tile_cache_plan,
    iter_raster_plan_tiles,
    raster_tile_cache_path,
)
from navigation_terrain_projection_store import compile_navigation_terrain_projection
from pretrip_boss_point_synthesis import synthesize_pretrip_boss_points
from pretrip_mileage_tag_alignment import align_pretrip_workspace_mileage_tags
from scout_contextual_permission_workbench import (
    BaselineAuthoringRequest,
    BaselineCandidateSaveRequest,
    ContextualPermissionWorkbench,
    build_reference_workbench_seed,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PROJECT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
READY_PROJECT_ID = "chilai_nanhua_day1"
TERRAIN_REF = "outputs/qualification/terrain_visualization.json"
ROUTE_SAMPLES_REF = "outputs/qualification/terrain_route_samples.geojson"
RISK_CANDIDATES_REF = "outputs/qualification/terrain_risk_candidates.json"
QUALIFICATION_TILE_HALO = 5
QUALIFICATION_GENERATED_AT = "2026-08-06T00:00:00Z"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seed_permission(
    project_root: Path,
    project: dict[str, Any],
    *,
    project_id: str,
    baseline_accepted_by_human: bool = True,
) -> dict[str, Any]:
    seed = build_reference_workbench_seed(project_id)
    if not baseline_accepted_by_human:
        seed = seed.model_copy(
            update={
                "baseline": seed.baseline.model_copy(
                    update={"accepted_by_human": False}
                )
            }
        )
    seed_ref = "outputs/contextual_permission/workbench_seed.json"
    rules_ref = "candidates/contextual_permission_rules.json"
    graph_ref = "outputs/compiled_mission_graph.reviewed.json"
    eta_ref = "outputs/planned_eta.json"

    _write_json(project_root / seed_ref, seed.model_dump(mode="json"))
    _write_json(
        project_root / graph_ref,
        {"mission_id": f"mission.{project_id}.qualification.v1"},
    )
    _write_json(
        project_root / eta_ref,
        {
            "project_id": project_id,
            "plan_id": f"eta.{project_id}.qualification.v1",
            "assumption": {
                "day1_target_node_name": "Reviewed camp",
                "turn_back_checkpoint_node_name": "Reviewed junction",
            },
            "estimates": [],
        },
    )
    _write_json(
        project_root / rules_ref,
        {
            "artifact_kind": "pretrip_contextual_permission_rules",
            "schema_version": "contextual_permission_rules.v2",
            "project_id": project_id,
            "reviewed_baseline_ref": seed.baseline.reviewed_receipt_ref,
            "reviewed_baseline_sha256": seed.baseline.baseline_sha256,
            "reviewed_by_human": True,
            "review_receipt_ref": "reviewed://qualification/contextual-permission/rules-v1",
            "review_receipt_sha256": "a" * 64,
            "plan_node_policies": [
                {
                    "node_id": node.node_id,
                    "mission_day_id": node.mission_day_id,
                    "adjustment_policy": node.adjustment_policy,
                    "minimum_duration_minutes": node.minimum_duration_minutes,
                    "policy_ref": node.source_rule_ref,
                    "policy_sha256": node.source_rule_sha256,
                    "reviewed": True,
                }
                for node in seed.remaining_plan
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    return {
        **project,
        "compiled_mission_graph_reviewed_ref": graph_ref,
        "planned_eta_ref": eta_ref,
        "contextual_permission_rules_ref": rules_ref,
    }


def _seed_historical_stale_permission(
    project_root: Path,
    *,
    project_id: str,
) -> str:
    workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=project_root.parent / ".qualification-seed-store",
        allow_stale_projection=True,
    )
    draft = workbench.generate_baseline_draft(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
        )
    )
    saved = workbench.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="qualification-historical-legacy-save",
            explicit_confirmation=True,
        )
    )
    candidate = json.loads(
        (project_root / saved.version_ref).read_text(encoding="utf-8")
    )
    review_id = "review.qualification-historical-legacy"
    reviewed_ref = (
        f"outputs/mission_baselines/{candidate['baseline_id']}/reviewed/"
        f"{review_id}.json"
    )
    reviewed: dict[str, Any] = {
        "artifact_kind": "reviewed_mission_baseline",
        "schema_version": "reviewedMissionBaseline.v1",
        "review_id": review_id,
        "candidate_ref": saved.version_ref,
        "candidate_sha256": saved.version_sha256,
        "baseline_id": candidate["baseline_id"],
        "version_id": candidate["version_id"],
        "source_mode": candidate["source_mode"],
        "source_sha256": candidate["source_sha256"],
        "days": candidate["days"],
        "proposal_profile": "legacy_sparse",
        "reviewed_day_ids": [],
        "review_scope": "permission_day_end_only",
        "reviewer_alias": "qualification-fixture",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "reviewed_baseline_sha256": "0" * 64,
    }
    reviewed["reviewed_baseline_sha256"] = _canonical_digest(
        {
            key: value
            for key, value in reviewed.items()
            if key != "reviewed_baseline_sha256"
        }
    )
    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
    _write_json(project_root / reviewed_ref, reviewed)

    receipt_ref = f"reviews/mission_baseline_accept_receipts/{review_id}.json"
    receipt: dict[str, Any] = {
        "artifact_kind": "mission_baseline_review_decision",
        "schema_version": "missionBaselineReviewDecision.v1",
        "review_id": review_id,
        "candidate_ref": saved.version_ref,
        "candidate_sha256": saved.version_sha256,
        "reviewed_baseline_ref": reviewed_ref,
        "reviewed_baseline_sha256": reviewed_sha256,
        "reviewer_alias": "qualification-fixture",
        "review_sha256": "0" * 64,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    receipt["review_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "review_sha256"}
    )
    _write_json(project_root / receipt_ref, receipt)

    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "reviewed_mission_baseline_ref": reviewed_ref,
            "reviewed_mission_baseline_sha256": reviewed_sha256,
            "reviewed_mission_baseline_receipt_id": review_id,
        }
    )
    _write_json(project_path, project)
    _write_json(
        project_root
        / "outputs/contextual_permission/stale_after_baseline_acceptance.json",
        {
            "artifact_kind": "contextual_permission_dependency_staleness",
            "schema_version": "contextualPermissionDependencyStaleness.v1",
            "review_id": review_id,
            "reviewed_baseline_sha256": reviewed_sha256,
            "requires_explicit_rebuild": True,
            "active_runtime_session_updated": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    return reviewed_sha256


def _seed_permission_state_project(
    workspace_root: Path,
    *,
    project_id: str,
    state: str,
) -> None:
    project_root = workspace_root / project_id
    project = _seed_permission(
        project_root,
        {
            "project_id": project_id,
            "artifact_kind": "qualification_synthetic_project",
            "qualification_fixture_state": state,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        project_id=project_id,
        baseline_accepted_by_human=state != "degraded",
    )
    _write_json(project_root / "project.json", project)
    if state == "stale":
        _seed_historical_stale_permission(
            project_root,
            project_id=project_id,
        )


def _seed_navigation_sources(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    route_summary = json.loads(
        (project_root / "normalized/routes/route_summary.json").read_text(
            encoding="utf-8"
        )
    )
    source_bbox = route_summary["bbox_wgs84"]
    bbox = {
        "west": float(source_bbox["min_lon"]),
        "south": float(source_bbox["min_lat"]),
        "east": float(source_bbox["max_lon"]),
        "north": float(source_bbox["max_lat"]),
    }
    _write_json(
        project_root / TERRAIN_REF,
        {
            "artifact_kind": "qualification_synthetic_terrain_visualization",
            "counts": {
                "source_dtm_tile_count": 0,
                "contour_marker_count": 0,
                "slope_class_counts": {},
            },
            "dtm_grid": {
                "bbox_wgs84": bbox,
                "crs": "EPSG:4326",
                "cell_resolution_m": None,
                "selected_cell_count": 0,
            },
            "features": [],
            "raster_overlays": [],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    _write_json(
        project_root / ROUTE_SAMPLES_REF,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [bbox["west"], bbox["south"]],
                    },
                    "properties": {
                        "candidate_id": "qualification-route-start",
                        "distance_m": 0,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [bbox["east"], bbox["north"]],
                    },
                    "properties": {
                        "candidate_id": "qualification-route-end",
                        "distance_m": float(route_summary["distance_m"]),
                    },
                },
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    _write_json(
        project_root / RISK_CANDIDATES_REF,
        {
            "candidates": [],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    return {
        **project,
        "terrain_visualization_ref": TERRAIN_REF,
        "terrain_route_samples_ref": ROUTE_SAMPLES_REF,
        "terrain_risk_candidates_ref": RISK_CANDIDATES_REF,
    }


def _seed_ready_evidence(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    """Add bounded, locally derived evidence needed by the ready fixture."""
    _write_json(project_root / "project.json", project)
    synthesize_pretrip_boss_points(
        project_root,
        generated_at=QUALIFICATION_GENERATED_AT,
    )
    align_pretrip_workspace_mileage_tags(
        project_root,
        generated_at=QUALIFICATION_GENERATED_AT,
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    risk_ribbon_ref = str(project["risk_ribbon_ref"])
    risk_ribbon = json.loads(
        (project_root / risk_ribbon_ref).read_text(encoding="utf-8")
    )
    source_features = [
        feature
        for feature in risk_ribbon.get("features", [])
        if isinstance(feature, dict)
        and (feature.get("geometry") or {}).get("type") == "LineString"
        and (feature.get("geometry") or {}).get("coordinates")
    ]
    sample_step = max(1, len(source_features) // 16)
    sampled_features = source_features[::sample_step][:16]
    score_features = []
    for index, feature in enumerate(sampled_features):
        properties = dict(feature.get("properties") or {})
        coordinates = feature["geometry"]["coordinates"][0]
        score_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    **properties,
                    "sample_id": properties.get("from_sample_id")
                    or f"qualification-risk-sample-{index:02d}",
                    "distance_m": properties.get("start_distance_m"),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )

    score_ref = "outputs/qualification/risk_score_points.geojson"
    score_metadata_ref = "outputs/qualification/risk_score_points.metadata.json"
    heatmap_ref = "outputs/qualification/calibrated_risk_heatmap.geojson"
    heatmap_metadata_ref = (
        "outputs/qualification/calibrated_risk_heatmap.metadata.json"
    )
    source_metadata = dict(risk_ribbon.get("metadata") or {})
    _write_json(
        project_root / score_ref,
        {
            "type": "FeatureCollection",
            "features": score_features,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    _write_json(
        project_root / score_metadata_ref,
        {
            **source_metadata,
            "artifact_kind": "qualification_derived_risk_score_points",
            "score_surface_type": "route_aligned_sample_points",
            "source_feature_count": len(source_features),
            "point_count": len(score_features),
            "source_ref": risk_ribbon_ref,
            "synthetic_fixture": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    _write_json(
        project_root / heatmap_ref,
        {
            **risk_ribbon,
            "metadata": {
                **source_metadata,
                "artifact_kind": "qualification_derived_calibrated_risk_heatmap",
                "score_surface_type": "route_aligned_calibrated_heatmap",
                "source_ref": risk_ribbon_ref,
                "synthetic_fixture": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        },
    )
    _write_json(
        project_root / heatmap_metadata_ref,
        {
            **source_metadata,
            "artifact_kind": "qualification_derived_calibrated_risk_heatmap",
            "score_surface_type": "route_aligned_calibrated_heatmap",
            "source_ref": risk_ribbon_ref,
            "synthetic_fixture": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )

    environment_refs = {
        "cwa_weather_evidence_ref": (
            "outputs/environment/cwa/cwa_weather_evidence.json"
        ),
        "cwa_warnings_geojson_ref": "outputs/environment/cwa/warnings.geojson",
        "cwa_observations_geojson_ref": (
            "outputs/environment/cwa/observations.geojson"
        ),
        "cwa_qpf_grid_ref": "outputs/environment/cwa/qpf_grid.geojson",
        "cwa_qpf_corridor_summary_ref": (
            "outputs/environment/cwa/qpf_corridor_summary.json"
        ),
        "soil_moisture_grid_ref": (
            "outputs/environment/gee/soil_moisture_grid.geojson"
        ),
        "smap_l4_corridor_summary_ref": (
            "outputs/environment/gee/smap_l4_corridor_summary.json"
        ),
        "antecedent_rain_grid_ref": (
            "outputs/environment/gee/antecedent_rain_grid.geojson"
        ),
        "gpm_imerg_corridor_summary_ref": (
            "outputs/environment/gee/gpm_imerg_corridor_summary.json"
        ),
    }
    project = {
        **project,
        **environment_refs,
        "risk_score_points_ref": score_ref,
        "risk_score_points_metadata_ref": score_metadata_ref,
        "calibrated_risk_heatmap_ref": heatmap_ref,
        "calibrated_risk_heatmap_metadata_ref": heatmap_metadata_ref,
        "qualification_ready_evidence_seed": {
            "status": "bounded_local_derivation",
            "source_ref": risk_ribbon_ref,
            "synthetic_fixture": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }
    _write_json(project_root / "project.json", project)
    return project


def _seed_route_context_variants(project_root: Path) -> dict[str, Any]:
    output_dir_ref = "outputs/briefings/route_context_variants_ai_once"
    output_dir = project_root / output_dir_ref
    slugs = (
        "magazine-atlas",
        "command-wall",
        "field-notebook",
        "topographic-feature",
        "night-navigation",
    )
    variants = []
    links = []
    for index, slug in enumerate(slugs, start=1):
        relative_ref = f"variant-{index:02d}-{slug}.html"
        title = f"Qualification route variant {index}"
        _write_text(
            output_dir / relative_ref,
            "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
            f"<title>{title}</title><main><h1>{title}</h1>"
            "<p>Synthetic candidate-only fixture. No model or external source "
            "was called; this is not runtime safety truth.</p></main></html>\n",
        )
        links.append(f'<li><a href="{relative_ref}">{title}</a></li>')
        variants.append(
            {
                "slug": slug,
                "tone": "qualification fixture",
                "concept": f"bounded synthetic layout {index}",
                "relative_ref": relative_ref,
                "generated_by_single_model_plan": False,
                "codex_posthoc_supplement": False,
                "passes_richness_gate": None,
                "passes_unrelated_terms_gate": True,
                "passes_bad_image_gate": True,
                "passes_reference_similarity_gate": None,
                "unrelated_terms": [],
                "bad_image_refs": [],
                "synthetic_fixture": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    _write_text(
        output_dir / "index.html",
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<title>Qualification route variants</title><main><h1>Qualification "
        f"route variants</h1><ul>{''.join(links)}</ul></main></html>\n",
    )
    comparison_ref = f"{output_dir_ref}/route_context_variant_comparison.json"
    comparison = {
        "artifact_kind": "qualification_synthetic_route_context_variants",
        "schema_version": "qualificationSyntheticRouteContextVariants.v1",
        "skill_id": "qualification.synthetic.route-context-variants",
        "skill_version": "1",
        "model": "none:bounded-synthetic-fixture",
        "generated_at": QUALIFICATION_GENERATED_AT,
        "synthetic_fixture": True,
        "one_model_call_complete": False,
        "no_codex_posthoc_supplement": True,
        "reference_similarity_gate": {
            "status": "not_applicable_synthetic_fixture"
        },
        "variants": variants,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "external_model_called": False,
            "external_network_called": False,
        },
    }
    _write_json(project_root / comparison_ref, comparison)
    _write_text(
        output_dir / "route_context_variant_comparison.md",
        "# Qualification route variants\n\n"
        "Five bounded synthetic candidate-only layouts. No model or external "
        "source was called; none is runtime safety truth.\n",
    )
    return {
        "output_dir_ref": output_dir_ref,
        "comparison_ref": comparison_ref,
        "variant_count": len(variants),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _tile_coordinates_with_halo(
    tiles: Iterable[dict[str, Any]],
    *,
    halo: int,
) -> set[tuple[int, int, int]]:
    if halo < 0:
        raise ValueError("tile halo must be non-negative")
    coordinates: set[tuple[int, int, int]] = set()
    for tile in tiles:
        zoom = int(tile["z"])
        x = int(tile["x"])
        y = int(tile["y"])
        max_coordinate = (1 << zoom) - 1
        for candidate_x in range(max(0, x - halo), min(max_coordinate, x + halo) + 1):
            for candidate_y in range(
                max(0, y - halo),
                min(max_coordinate, y + halo) + 1,
            ):
                coordinates.add((zoom, candidate_x, candidate_y))
    return coordinates


def _seed_native_tiles(
    project_root: Path,
    project: dict[str, Any],
    projection: dict[str, Any],
    cache_root: Path,
) -> int:
    bbox = projection.get("terrain_surface", {}).get("bbox_wgs84")
    if not isinstance(bbox, dict):
        raise RuntimeError("ready qualification fixture has no Navigation bbox")
    source = imagery_source_for_project(
        {"imagery_source_id": "happyman_rudy_twmap"}
    )
    count = 0
    for zoom in (12, 13, 14, 15):
        plan = build_imagery_tile_cache_plan(
            bbox,
            project_id=READY_PROJECT_ID,
            layer_id="imagery",
            imagery_source=source,
            cache_root=cache_root,
            min_zoom=zoom,
            max_zoom=zoom,
        )
        coordinates = _tile_coordinates_with_halo(
            iter_raster_plan_tiles(plan),
            halo=QUALIFICATION_TILE_HALO,
        )
        for tile_zoom, tile_x, tile_y in sorted(coordinates):
            tile_path = raster_tile_cache_path(
                READY_PROJECT_ID,
                "imagery",
                tile_zoom,
                tile_x,
                tile_y,
                cache_root=cache_root,
            )
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new(
                "RGB",
                (256, 256),
                color=(36 + (zoom - 13) * 12, 66, 49),
            )
            draw = ImageDraw.Draw(image)
            draw.line((0, 220, 256, 36), fill=(222, 205, 145), width=4)
            draw.text(
                (12, 12),
                f"QUAL Z{tile_zoom}/{tile_x}/{tile_y}",
                fill=(244, 245, 228),
            )
            image.save(tile_path, format="PNG")
            count += 1
    return count


def seed_fixture(workspace_root: Path) -> dict[str, Any]:
    workspace_root.mkdir(parents=True, exist_ok=True)
    ready_root = workspace_root / READY_PROJECT_ID
    shutil.copytree(SOURCE_PROJECT, ready_root)
    project_path = ready_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project = _seed_permission(
        ready_root,
        project,
        project_id=READY_PROJECT_ID,
    )
    project = _seed_navigation_sources(ready_root, project)
    cache_root = workspace_root / ".qualification-raster-tiles"
    project = {
        **project,
        "imagery_tile_cache_root": str(cache_root),
        "imagery_tile_cache_source_id": "happyman_rudy_twmap",
        "imagery_tile_cache_min_zoom": 12,
        "imagery_tile_cache_max_zoom": 15,
    }
    _write_json(project_path, project)
    projection = compile_navigation_terrain_projection(
        ready_root,
        project=project,
        project_id=READY_PROJECT_ID,
        compiled_at="2026-08-06T00:00:00Z",
    )
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project = _seed_ready_evidence(ready_root, project)
    variant_seed = _seed_route_context_variants(ready_root)
    tile_count = _seed_native_tiles(ready_root, project, projection, cache_root)

    _seed_permission_state_project(
        workspace_root,
        project_id="qualification_degraded",
        state="degraded",
    )
    _seed_permission_state_project(
        workspace_root,
        project_id="qualification_stale",
        state="stale",
    )

    for project_id in (
        "qualification_partial",
        "qualification_blocked",
        "qualification_zero_evidence",
        "qualification_assistant_enabled",
        "qualification_assistant_disabled",
    ):
        _write_json(
            workspace_root / project_id / "project.json",
            {
                "project_id": project_id,
                "artifact_kind": "qualification_synthetic_project",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        )

    return {
        "schema": "scout.dashboardQualificationSeed.v1",
        "workspace_root": str(workspace_root),
        "ready_project_id": READY_PROJECT_ID,
        "partial_project_id": "qualification_partial",
        "blocked_project_id": "qualification_blocked",
        "native_tile_count": tile_count,
        "route_variant_count": variant_seed["variant_count"],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed bounded Dashboard qualification fixtures.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = seed_fixture(args.workspace_root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
