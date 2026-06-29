from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from pretrip_risk_attribution_diagnostic import (
    DEFAULT_WORKSPACE,
    RISK_ATTRIBUTION_VERSION,
    RISK_DIMENSIONS,
    RouteRiskPoint,
    load_route_risk_points,
    percentile,
    value_stats,
)


HEATMAP_VERSION = "0.1.0"
HEATMAP_SCORE_FIELD = "calibrated_risk_candidate"
HEAT_COLORS = {
    "low": "#2c7bb6",
    "moderate": "#abd9e9",
    "high": "#d6a800",
    "very_high": "#fdae61",
    "extreme": "#d7191c",
}
MAX_ROUTE_BASE_HEATMAP_SEGMENT_M = 80.0


def build_calibrated_risk_heatmap(
    *,
    route_risk_path: Path | str,
    risk_attribution_diagnostic_path: Path | str,
    warning_cp_proposals_path: Path | str | None = None,
) -> dict[str, Any]:
    route_risk_path = Path(route_risk_path)
    diagnostic_path = Path(risk_attribution_diagnostic_path)
    route_points = load_route_risk_points(route_risk_path)
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    formula = diagnostic["factor_analysis"]["formula_candidate"]
    terms = tuple(formula.get("terms", []))
    if formula.get("status") != "candidate_only" or not terms:
        raise ValueError("risk attribution diagnostic has no candidate formula")

    scored_points = [
        scored_route_point(point, terms=terms)
        for point in route_points
    ]
    score_stats = value_stats(point["calibrated_score"] for point in scored_points)
    thresholds = heat_thresholds(
        point["calibrated_score"] for point in scored_points
    )
    point_by_sample_id = {
        point["sample_id"]: point
        for point in scored_points
    }
    features: list[dict[str, Any]] = []
    skipped_pair_count = 0
    for start, end in zip(scored_points, scored_points[1:]):
        if start["route_id"] != end["route_id"]:
            skipped_pair_count += 1
            continue
        if not route_risk_points_can_connect(
            start,
            end,
            max_segment_m=MAX_ROUTE_BASE_HEATMAP_SEGMENT_M,
        ):
            skipped_pair_count += 1
            continue
        score = max(start["calibrated_score"], end["calibrated_score"])
        bucket = heat_bucket(score, thresholds)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [start["lon"], start["lat"]],
                        [end["lon"], end["lat"]],
                    ],
                },
                "properties": {
                    "segment_id": (
                        f"calibrated_heatmap.{start['sample_id']}.{end['sample_id']}"
                    ),
                    "route_id": start["route_id"],
                    "from_sample_id": start["sample_id"],
                    "to_sample_id": end["sample_id"],
                    "start_distance_m": start["distance_m"],
                    "end_distance_m": end["distance_m"],
                    "score_field": HEATMAP_SCORE_FIELD,
                    "rs": round(score, 2),
                    "calibrated_risk_candidate": round(score, 2),
                    "start_calibrated_risk_candidate": round(
                        start["calibrated_score"],
                        2,
                    ),
                    "end_calibrated_risk_candidate": round(
                        end["calibrated_score"],
                        2,
                    ),
                    "relative_bucket": bucket,
                    "risk_bucket": bucket,
                    "relative_heat": relative_heat(score, score_stats),
                    "stroke": HEAT_COLORS[bucket],
                    "style_class": f"risk-heatmap-{bucket}",
                    "formula_expression": formula.get("expression"),
                    "selected_dimensions": formula.get("selected_dimensions", []),
                    "start_factor_values": start["factor_values"],
                    "end_factor_values": end["factor_values"],
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "route_specific_calibration_candidate": True,
                },
            }
        )

    warning_proposals = load_warning_cp_proposals(warning_cp_proposals_path)
    metadata = {
        "artifact_kind": "pretrip_calibrated_risk_heatmap",
        "schema_version": HEATMAP_VERSION,
        "risk_attribution_schema_version": diagnostic.get("schema_version"),
        "status": "candidate_only",
        "source_route_risk_ref": str(route_risk_path),
        "source_risk_attribution_diagnostic_ref": str(diagnostic_path),
        "warning_cp_proposals_ref": str(warning_cp_proposals_path)
        if warning_cp_proposals_path
        else None,
        "score_field": HEATMAP_SCORE_FIELD,
        "score_surface_type": "route_aligned_calibrated_heatmap",
        "formula_candidate": formula,
        "score_stats": score_stats,
        "relative_heat_thresholds": thresholds,
        "source_sample_count": len(scored_points),
        "segment_count": len(features),
        "skipped_pair_count": skipped_pair_count,
        "max_route_base_segment_m": MAX_ROUTE_BASE_HEATMAP_SEGMENT_M,
        "warning_cp_overlay_count": len(warning_proposals),
        "style": {
            bucket: {"stroke": color}
            for bucket, color in HEAT_COLORS.items()
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "interpolated_surface": False,
            "route_aligned_samples_only": True,
            "route_specific_calibration_candidate": True,
            "notes": [
                "Heat map（熱區圖）使用本 workspace 的 factor analysis 公式候選重算，不覆寫正式 route risk。",
                "顏色為本路線相對分位數，用於凸顯本次資料中特別突出的區段。",
            ],
        },
    }
    return {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
        "warning_cp_overlay": warning_cp_overlay_features(
            warning_proposals,
            point_by_sample_id=point_by_sample_id,
        ),
    }


def scored_route_point(
    point: RouteRiskPoint,
    *,
    terms: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    score = 0.0
    factor_values: dict[str, float | None] = {}
    for term in terms:
        dimension = str(term["dimension"])
        value = _optional_float(point.properties.get(dimension))
        factor_values[dimension] = value
        if value is None:
            continue
        score += float(term["normalized_weight"]) * value
    return {
        "route_id": str(point.properties.get("route_id", "")),
        "sample_id": point.sample_id,
        "lat": point.lat,
        "lon": point.lon,
        "distance_m": _optional_float(point.properties.get("distance_m")),
        "calibrated_score": round(score, 6),
        "factor_values": factor_values,
        "risk_dimensions": {
            dimension: _optional_float(point.properties.get(dimension))
            for dimension in RISK_DIMENSIONS
        },
        "route_base_source": point.properties.get("route_base_source"),
        "route_base_feature_id": point.properties.get("route_base_feature_id"),
        "route_base_projection_distance_m": _optional_float(
            point.properties.get("route_base_projection_distance_m")
        ),
    }


def route_risk_points_can_connect(
    start: dict[str, Any],
    end: dict[str, Any],
    *,
    max_segment_m: float,
) -> bool:
    start_source = start.get("route_base_source")
    end_source = end.get("route_base_source")
    if start_source is None and end_source is None:
        return True
    if start_source != "overpass_projection" or end_source != "overpass_projection":
        return False
    return _haversine_m(start["lat"], start["lon"], end["lat"], end["lon"]) <= max_segment_m


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def heat_thresholds(scores: Sequence[float] | Any) -> dict[str, float]:
    values = sorted(float(score) for score in scores)
    if not values:
        raise ValueError("cannot build heat thresholds without scores")
    return {
        "p50": round(percentile(values, 0.50), 2),
        "p75": round(percentile(values, 0.75), 2),
        "p90": round(percentile(values, 0.90), 2),
        "p95": round(percentile(values, 0.95), 2),
    }


def heat_bucket(score: float, thresholds: dict[str, float]) -> str:
    if score >= thresholds["p95"]:
        return "extreme"
    if score >= thresholds["p90"]:
        return "very_high"
    if score >= thresholds["p75"]:
        return "high"
    if score >= thresholds["p50"]:
        return "moderate"
    return "low"


def relative_heat(score: float, score_stats: dict[str, Any]) -> float:
    minimum = score_stats["min"]
    maximum = score_stats["max"]
    if minimum is None or maximum is None or maximum == minimum:
        return 0.0
    return round((score - minimum) / (maximum - minimum), 4)


def load_warning_cp_proposals(path: Path | str | None) -> list[dict[str, Any]]:
    if path is None or not Path(path).exists():
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("proposals", []))


def warning_cp_overlay_features(
    proposals: Sequence[dict[str, Any]],
    *,
    point_by_sample_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for proposal in proposals:
        lat = _optional_float(proposal.get("lat"))
        lon = _optional_float(proposal.get("lon"))
        sample_id = str(proposal.get("source_sample_id") or "")
        point = point_by_sample_id.get(sample_id)
        if point is not None:
            lat = point["lat"]
            lon = point["lon"]
        if lat is None or lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    **proposal,
                    "overlay_kind": "excluded_extreme_warning_cp",
                    "marker": "warning",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    return features


def write_heatmap_geojson(heatmap: dict[str, Any], path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(heatmap, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_heatmap_metadata(heatmap: dict[str, Any], path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(heatmap["metadata"], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def write_heatmap_preview_png(heatmap: dict[str, Any], path: Path | str) -> None:
    import matplotlib.pyplot as plt

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    for feature in heatmap.get("features", []):
        coords = feature["geometry"]["coordinates"]
        xs = [coord[0] for coord in coords]
        ys = [coord[1] for coord in coords]
        properties = feature["properties"]
        bucket = properties["relative_bucket"]
        linewidth = 1.2 + 5.0 * float(properties.get("relative_heat") or 0.0)
        ax.plot(
            xs,
            ys,
            color=HEAT_COLORS[bucket],
            linewidth=linewidth,
            alpha=0.82,
            solid_capstyle="round",
        )
    warning_features = heatmap.get("warning_cp_overlay", [])
    if warning_features:
        ax.scatter(
            [feature["geometry"]["coordinates"][0] for feature in warning_features],
            [feature["geometry"]["coordinates"][1] for feature in warning_features],
            s=18,
            marker="x",
            linewidths=0.9,
            color="#7e22ce",
            alpha=0.75,
            label="excluded extreme warning cp",
        )
    ax.set_title("Scout pretrip calibrated risk heat map", fontsize=11)
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color="#d4d4d8", linewidth=0.35, alpha=0.45)
    legend_handles = [
        plt.Line2D([0], [0], color=color, lw=4, label=bucket.replace("_", " "))
        for bucket, color in HEAT_COLORS.items()
    ]
    if warning_features:
        legend_handles.append(
            plt.Line2D(
                [0],
                [0],
                color="#7e22ce",
                marker="x",
                lw=0,
                label="excluded extreme",
            )
        )
    ax.legend(handles=legend_handles, loc="lower right", fontsize=7, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(destination)
    plt.close(fig)


def update_workspace_project_refs(
    *,
    workspace: Path,
    heatmap_path: Path,
    metadata_path: Path,
    preview_path: Path | None,
    heatmap: dict[str, Any],
) -> None:
    project_path = workspace / "project.json"
    if not project_path.exists():
        return
    project = json.loads(project_path.read_text(encoding="utf-8"))
    updated = dict(project)
    updated["calibrated_risk_heatmap_ref"] = _workspace_ref(workspace, heatmap_path)
    updated["calibrated_risk_heatmap_metadata_ref"] = _workspace_ref(
        workspace,
        metadata_path,
    )
    if preview_path is not None and preview_path.exists():
        updated["calibrated_risk_heatmap_preview_ref"] = _workspace_ref(
            workspace,
            preview_path,
        )
    else:
        updated.pop("calibrated_risk_heatmap_preview_ref", None)
    updated["calibrated_risk_heatmap_segment_count"] = heatmap["metadata"][
        "segment_count"
    ]
    updated["calibrated_risk_heatmap_warning_cp_overlay_count"] = heatmap[
        "metadata"
    ]["warning_cp_overlay_count"]
    project_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _workspace_ref(workspace: Path, path: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def _default_route_risk_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "route_risk.geojson"


def _default_diagnostic_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "risk_attribution_diagnostic.json"


def _default_warning_cp_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "excluded_extreme_warning_cp_proposals.json"


def _default_heatmap_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "calibrated_risk_heatmap.geojson"


def _default_metadata_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "calibrated_risk_heatmap.metadata.json"


def _default_preview_path(workspace: Path) -> Path:
    return workspace / "outputs" / "risk" / "calibrated_risk_heatmap.png"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a workspace-only calibrated route risk heat map."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--route-risk", type=Path)
    parser.add_argument("--diagnostic", type=Path)
    parser.add_argument("--warning-cp", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--metadata-out", type=Path)
    parser.add_argument("--preview-png", type=Path)
    args = parser.parse_args(argv)

    route_risk_path = args.route_risk or _default_route_risk_path(args.workspace)
    diagnostic_path = args.diagnostic or _default_diagnostic_path(args.workspace)
    warning_cp_path = args.warning_cp or _default_warning_cp_path(args.workspace)
    out_path = args.out or _default_heatmap_path(args.workspace)
    metadata_path = args.metadata_out or _default_metadata_path(args.workspace)
    preview_path = args.preview_png or _default_preview_path(args.workspace)

    heatmap = build_calibrated_risk_heatmap(
        route_risk_path=route_risk_path,
        risk_attribution_diagnostic_path=diagnostic_path,
        warning_cp_proposals_path=warning_cp_path,
    )
    write_heatmap_geojson(heatmap, out_path)
    write_heatmap_metadata(heatmap, metadata_path)
    preview_written = False
    try:
        write_heatmap_preview_png(heatmap, preview_path)
        preview_written = True
    except ModuleNotFoundError as exc:
        if exc.name != "matplotlib":
            raise
    update_workspace_project_refs(
        workspace=args.workspace,
        heatmap_path=out_path,
        metadata_path=metadata_path,
        preview_path=preview_path if preview_written else None,
        heatmap=heatmap,
    )
    print(f"wrote calibrated heat map to {out_path}")
    print(f"wrote calibrated heat map metadata to {metadata_path}")
    if preview_written:
        print(f"wrote calibrated heat map preview to {preview_path}")
    else:
        print("skipped calibrated heat map preview; matplotlib is not installed")
    print(
        json.dumps(
            {
                "segment_count": heatmap["metadata"]["segment_count"],
                "warning_cp_overlay_count": heatmap["metadata"][
                    "warning_cp_overlay_count"
                ],
                "score_stats": heatmap["metadata"]["score_stats"],
                "relative_heat_thresholds": heatmap["metadata"][
                    "relative_heat_thresholds"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
