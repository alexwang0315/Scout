import json
from pathlib import Path

from scout_terrain_score_tool import (
    TERRAIN_SCORE_TOOL_ID,
    search_project_terrain_scores,
)


def test_search_project_terrain_scores_returns_direct_slope_results(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="terrain slope 最高",
        limit=3,
    )

    assert result["tool_id"] == TERRAIN_SCORE_TOOL_ID
    assert result["status"] == "completed"
    assert result["metric"] == "slope"
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["summaries"]["direct_slope_degrees_available"] is True
    assert result["results"][0]["score_field"] == "slope_degrees"
    assert result["results"][0]["score"] == 54.0
    assert result["results"][0]["slope_measurement_status"] == "direct"


def test_search_project_terrain_scores_filters_by_cp_anchor(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="CP001 附近坡度",
        limit=5,
    )

    assert result["filters"]["cp"] == "cp.001"
    assert result["result_count"] >= 1
    assert result["results"][0]["sample_id"] == "terrain.sample.001"
    assert result["results"][0]["anchor_distance_m"] <= 350


def test_search_project_terrain_scores_uses_teii_proxy_when_direct_slope_missing(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path, include_direct_slope=False)

    result = search_project_terrain_scores(
        workspace,
        query="terrain slope 最高",
        limit=2,
    )

    assert result["metric"] == "slope"
    assert result["summaries"]["direct_slope_degrees_available"] is False
    assert result["results"][0]["score_field"] == "teii_20m"
    assert result["results"][0]["slope_measurement_status"] == (
        "proxy_from_teii_no_direct_slope_degrees"
    )
    assert result["results"][0]["score"] == 96.0


def test_search_project_terrain_scores_filters_by_km(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="1 km TEII 地形",
        limit=3,
    )

    assert result["metric"] == "teii"
    assert result["result_count"] == 1
    assert result["results"][0]["distance_km"] == 1.0
    assert result["results"][0]["score_field"] == "teii_20m"


def _write_terrain_workspace(
    tmp_path: Path,
    *,
    include_direct_slope: bool = True,
) -> Path:
    workspace = tmp_path / "terrain-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "normalized").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "candidates").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "terrain_fixture",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "terrain_route_samples_ref": (
                    "outputs/layers/normalized/terrain_route_samples.geojson"
                ),
                "terrain_risk_candidates_ref": (
                    "outputs/layers/candidates/terrain_risk_candidates.json"
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cp.001",
                    "label": "CP 001",
                    "lat": 24.001,
                    "lon": 121.001,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "layers" / "normalized" / "terrain_route_samples.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "artifact_kind": "pretrip_layer_terrain_route_samples",
                "features": [
                    _point(
                        "terrain.sample.000",
                        24.0,
                        121.0,
                        0.0,
                        12.0 if include_direct_slope else None,
                        44.0,
                    ),
                    _point(
                        "terrain.sample.001",
                        24.001,
                        121.001,
                        1000.0,
                        38.0 if include_direct_slope else None,
                        82.0,
                    ),
                    _point(
                        "terrain.sample.002",
                        24.002,
                        121.002,
                        2000.0,
                        54.0 if include_direct_slope else None,
                        96.0,
                    ),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "layers" / "candidates" / "terrain_risk_candidates.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_layer_terrain_risk_candidates",
                "candidates": [
                    {
                        "candidate_id": "terrain.candidate.001",
                        "candidate_kind": "terrain_risk_candidate",
                        "lat": 24.003,
                        "lon": 121.003,
                        "risk_dimensions": {
                            "teii_20m": 90.0,
                            "tri": 88.0,
                            "sri": 10.0,
                            "lec": 85.0,
                            "pretrip_risk": 86.0,
                        },
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return workspace


def _point(
    sample_id: str,
    lat: float,
    lon: float,
    distance_m: float,
    slope_degrees: float | None,
    teii_20m: float,
) -> dict:
    properties = {
        "sample_id": sample_id,
        "route_id": "fixture_route",
        "distance_m": distance_m,
        "elevation_m": 2000.0 + distance_m / 100.0,
        "teii_20m": teii_20m,
        "tri": min(teii_20m + 1.0, 100.0),
        "sri": 5.0,
        "lec": min(teii_20m + 2.0, 100.0),
        "pretrip_risk": min(teii_20m + 3.0, 100.0),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if slope_degrees is not None:
        properties["slope_degrees"] = slope_degrees
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }
