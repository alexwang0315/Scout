"""Match genuine historical passages and join native DEM samples to Planned IDs."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from scout_planned_analysis_inputs import BOUNDARY, distance_m, items, read_json, safe_path, write_json
from scout_planned_route_models import PlannedRouteConflict


def match_planned_historical_passages(owner: Path, root: Path, inputs: dict, bundle: dict,
                                      source_report: list[dict]) -> dict:
    from pretrip_gpx_corpus import gpx_provenance_role
    from pretrip_reference_segment_timing import ReferenceSegmentSpec, build_reference_segment_timing

    sources, seen = [], set()
    for ref, expected in sorted(bundle["manifest"].get("source_hashes", {}).items()):
        if Path(ref).suffix.lower() != ".gpx":
            continue
        path = safe_path(owner, ref)
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != expected:
            raise PlannedRouteConflict("analysis_input_changed", "A bound historical GPX changed before passage matching.")
        if sha in seen:
            continue
        seen.add(sha)
        role = gpx_provenance_role(path)
        target_ref = f"inputs/historical/{sha}.gpx"
        target = safe_path(root, target_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        source_id = f"historical.{sha[:20]}"
        sources.append({"source_id": source_id, "sha256": sha, "original_path": str(target),
                        "original_filename": path.name, "gpx_provenance_role": role,
                        "role": "planned_gpx_reference" if role == "planned" else "historical_reference",
                        "historical_gpx_is_actual_user_track": False, "source_ref": ref})
        source_report.append({"scope": "owner", "ref": ref, "sha256": sha, "input_ref": target_ref,
                              "source_id": source_id, "role": "historical_reference" if role != "planned" else "excluded_planned_source"})
    index_ref = "inputs/historical/source_index.json"
    write_json(root, index_ref, {"project_id": inputs["subject_binding"]["project_id"], "sources": sources, **BOUNDARY})
    nodes = {n["candidate_id"]: n for n in inputs["graph"]["nodes"]}
    edges = [e for e in inputs["graph"]["edges"] if e["distance_m"] > .01]
    specs = tuple(ReferenceSegmentSpec(e["candidate_id"], e["from_candidate_id"], e["to_candidate_id"],
                 nodes[e["from_candidate_id"]]["label"], nodes[e["to_candidate_id"]]["label"],
                 max(120, e["distance_m"] / 1000 * 180),
                 (max(.001, e["distance_m"] / 1000 * .55), max(.03, e["distance_m"] / 1000 * 1.65))) for e in edges)
    radius = min(50, max(1, min((e["distance_m"] for e in edges), default=200) / 4))
    result = build_reference_segment_timing(root, source_index_ref=index_ref, target_segments=specs,
        target_checkpoint_coordinates={key: (n["lat"], n["lon"]) for key, n in nodes.items()},
        target_checkpoint_match_radius_m=radius)
    edge_by_id = {e["candidate_id"]: e for e in edges}
    for segment in result["segments"]:
        edge = edge_by_id[segment["segment_id"]]
        segment.update(from_point_index=edge["start_point_index"], to_point_index=edge["end_point_index"],
                       from_m=edge["from_m"], to_m=edge["to_m"], planned_duration_minutes=edge["expected_duration_minutes"],
                       time_role="historical_observation_compared_with_planned_estimate")
    matched = [s["segment_id"] for s in result["segments"] if s["sample_count"]]
    unmatched = [s["segment_id"] for s in result["segments"] if not s["sample_count"]]
    result.update(input_binding=inputs["subject_binding"], matched_segment_ids=matched, unmatched_segment_ids=unmatched,
                  source_bindings=[{k: s[k] for k in ("source_id", "source_ref", "sha256", "gpx_provenance_role")} for s in sources],
                  coverage={"target_segment_count": len(edges), "matched_segment_count": len(matched),
                            "unmatched_segment_count": len(unmatched), "gap_edge_count": len(inputs["gaps"])},
                  historical_observations_created=False, **BOUNDARY)
    write_json(root, "outputs/planned_reference_segment_timing.json", result)
    return result


def join_planned_terrain(run_root: Path, root: Path, inputs: dict, preparation: dict,
                         source_report: list[dict]) -> dict:
    from navigation_terrain_dem import project_route_sample_points_twd97

    axis = inputs["route_axis"]
    values, conflicts, reports = {}, set(), []
    for part in preparation.get("terrain_parts", []):
        if part.get("status") != "completed":
            continue
        if part.get("processor") != "qgis_processing_grass":
            raise PlannedRouteConflict("invalid_analysis_producer", "Planned terrain samples require the completed QGIS/GRASS producer.")
        ref = part.get("output_refs", {}).get("terrain_samples_ref")
        expected = part.get("source_hashes", {}).get(ref)
        if not ref or not expected:
            continue
        path = safe_path(run_root, ref)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise PlannedRouteConflict("analysis_input_changed", "Prepared terrain samples changed before projection.")
        payload = read_json(run_root, ref)
        if payload.get("candidate_only") is not True or payload.get("runtime_safety_truth") is not False:
            raise PlannedRouteConflict("invalid_analysis_authority", "Terrain samples do not retain candidate-only authority.")
        source_report.append({"scope": "run", "ref": ref, "sha256": expected, "role": "planned_native_dem_samples"})
        allowed = set(part.get("planned_point_indices", []))
        supported = 0
        for sample in items(payload, "points"):
            index, elevation = sample.get("planned_point_index"), sample.get("elevation_m")
            if not isinstance(index, int) or index not in allowed or not 0 <= index < len(axis):
                raise PlannedRouteConflict("invalid_analysis_mapping", "A terrain sample is outside its bound Planned point mapping.")
            if distance_m(sample, axis[index]) > .05:
                raise PlannedRouteConflict("invalid_analysis_mapping", "A terrain sample coordinate differs from the canonical Planned point.")
            if elevation is None:
                continue
            if not isinstance(elevation, (int, float)) or not math.isfinite(elevation):
                raise PlannedRouteConflict("invalid_analysis_mapping", "A terrain elevation is non-finite.")
            if index in values and abs(values[index] - elevation) > .01:
                conflicts.add(index)
                continue
            values[index] = float(elevation)
            supported += 1
        reports.append({"part_index": part.get("part_index"), "chunk_index": part.get("chunk_index"),
                        "samples_ref": ref, "samples_sha256": expected, "supported_point_count": supported,
                        "dem_ref": payload.get("dem_ref"), "dem_sha256": payload.get("dem_sha256"),
                        "resolution_m": payload.get("resolution_m"), "sampling_method": payload.get("sampling_method")})
    for index in conflicts:
        values.pop(index, None)
    points = [{"id": f"planned.terrain.{i:06d}", "planned_point_index": i, "lat": p["lat"], "lon": p["lon"],
               "distance_m": p["route_order_m"], "elevation_m": values.get(i), "break_before": p.get("break_before"), **BOUNDARY}
              for i, p in enumerate(axis)]
    # Use the existing deterministic Navigation coordinate projector while
    # retaining every canonical visit ID; its duplicate suppression is exposed.
    projected = project_route_sample_points_twd97(points)
    cp_values = [{"candidate_id": cp["candidate_id"], "planned_point_index": cp["point_index"],
                  "route_distance_m": cp["route_distance_m"], "terrain_elevation_m": values.get(cp["point_index"]),
                  "status": "sampled" if cp["point_index"] in values else "nodata"} for cp in inputs["graph"]["nodes"]]
    segments, features = [], []
    for edge in inputs["graph"]["edges"]:
        indices = list(range(edge["start_point_index"], edge["end_point_index"] + 1))
        supported = [i for i in indices if i in values]
        slopes, gain, loss = [], 0.0, 0.0
        for a, b in zip(indices, indices[1:]):
            if a not in values or b not in values or axis[b].get("break_before"):
                continue
            horizontal = distance_m(axis[a], axis[b])
            change = values[b] - values[a]
            gain += max(0, change)
            loss += max(0, -change)
            if horizontal > .01:
                slopes.append(math.degrees(math.atan2(change, horizontal)))
        complete = len(supported) == len(indices)
        item = {"segment_id": edge["candidate_id"], "from_cp_id": edge["from_candidate_id"], "to_cp_id": edge["to_candidate_id"],
                "from_m": edge["from_m"], "to_m": edge["to_m"], "point_count": len(indices), "sampled_point_count": len(supported),
                "coverage_status": "verified" if complete else "partial", "elevation_gain_m": round(gain, 3) if complete else None,
                "elevation_loss_m": round(loss, 3) if complete else None,
                "max_abs_longitudinal_grade_degrees": round(max(map(abs, slopes)), 3) if slopes else None,
                "terrain_slope_or_walkability_inferred": False, **BOUNDARY}
        segments.append(item)
        features.append({"type": "Feature", "properties": item,
                         "geometry": {"type": "LineString", "coordinates": [[axis[i]["lon"], axis[i]["lat"]] for i in indices]}})
    missing_indices = sorted(set(range(len(axis))) - values.keys())
    result = {"artifact_kind": "planned_route_terrain_analysis", "input_binding": inputs["subject_binding"],
              "status": "ready" if not missing_indices else "partial", "points": points, "projected_points_twd97": projected,
              "checkpoints": cp_values, "segments": segments, "route_geojson": {"type": "FeatureCollection", "features": features},
              "source_parts": reports, "coverage": {"point_count": len(axis), "sampled_point_count": len(values),
                  "unsupported_point_indices": missing_indices, "conflicting_point_indices": sorted(conflicts),
                  "segment_count": len(segments), "fully_sampled_segment_count": sum(s["coverage_status"] == "verified" for s in segments)},
              "method": "native_QGIS_DEM_samples_joined_by_canonical_Planned_point_ID_then_CP_edge_statistics",
              "gap_connectors_created": False, **BOUNDARY}
    write_json(root, "outputs/planned_route_terrain_analysis.json", result)
    project = read_json(root, "project.json")
    for key, ref, payload in (
        ("dtm_coverage_summary_ref", "normalized/terrain/dtm_coverage_summary.json", result["coverage"]),
        ("segment_dtm_coverage_ref", "normalized/terrain/segment_dtm_coverage.json", {"segments": segments, **BOUNDARY}),
        ("terrain_route_samples_ref", "outputs/planned_terrain_samples.geojson", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": p, "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}} for p in points]}),
    ):
        if values:
            write_json(root, ref, payload)
            project[key] = ref
    maps = preparation.get("map_sources") or {}
    if isinstance(maps, dict) and maps.get("catalog_ref"):
        ref = maps["catalog_ref"]
        raw = read_json(run_root, ref)
        expected = maps.get("source_hashes", {}).get(ref)
        if expected and hashlib.sha256(safe_path(run_root, ref).read_bytes()).hexdigest() != expected:
            raise PlannedRouteConflict("analysis_input_changed", "Prepared map catalog changed during analysis.")
        map_features = []
        for source in raw.get("sources", []):
            for part in source.get("parts", []):
                if len(part) >= 2:
                    map_features.append({"type": "Feature", "properties": {"source_id": source.get("source_id"), **BOUNDARY},
                        "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in part]}})
        write_json(root, "inputs/planned_map_context.geojson", {"type": "FeatureCollection", "features": map_features, **BOUNDARY})
        project["map_context_ref"] = "inputs/planned_map_context.geojson"
        if expected:
            source_report.append({"scope": "run", "ref": ref, "sha256": expected, "role": "planned_map_catalog"})
    write_json(root, "project.json", project)
    return result
