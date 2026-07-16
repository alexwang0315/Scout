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
    assert "沒有 direct slope degrees" in result["field_answer"]
    assert "TEII_20m proxy" in result["field_answer"]


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


def test_search_project_terrain_scores_joins_highest_teii_to_route_segment(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="哪個 terrain segment 的 TEII_20m 最高？",
        limit=3,
    )

    highest = result["highest_metric_segment"]
    assert result["metric"] == "teii"
    assert highest["segment_candidate_id"] == "seg.002"
    assert highest["score"] == 96.0
    assert result["results"][0]["segment_candidate_id"] == "seg.002"
    assert "seg.002" in result["field_answer"]
    assert "TEII_20m=96.0" in result["field_answer"]


def test_search_project_terrain_scores_summarizes_dtm_coverage(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="哪些 route segments 的 DTM coverage 不完整？",
        limit=3,
    )

    coverage = result["dtm_coverage_summary"]
    assert coverage["segment_count"] == 2
    assert coverage["incomplete_segment_count"] == 1
    assert coverage["incomplete_segment_ids"] == ["seg.002"]
    assert "seg.002" in result["field_answer"]
    assert result["field_answer_source_ref"] == (
        "normalized/terrain/segment_dtm_coverage.json"
    )
    assert result["field_answer_priority"] == 100


def test_terrain_score_does_not_override_route_elevation_aggregate(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    result = search_project_terrain_scores(
        workspace,
        query="primary route 的總爬升、總下降與平均坡度資料是否存在？",
        limit=3,
    )

    assert result["field_answer_priority"] == 10


def test_terrain_score_answers_derived_candidate_and_visualization_questions(
    tmp_path: Path,
) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    hazards = search_project_terrain_scores(
        workspace,
        query="terrain risk candidates 中有哪些崩壁、落石或暴露地形候選？",
    )
    landslide = search_project_terrain_scores(
        workspace,
        query="new landslide candidates 在路線哪些位置出現？",
    )
    obscurity = search_project_terrain_scores(
        workspace,
        query="trail obscurity risk 最高的 route segment 是哪一段？",
    )
    wetness = search_project_terrain_scores(
        workspace,
        query="wetness flash flood susceptibility 標示了哪些高候選區？",
    )
    visualization = search_project_terrain_scores(
        workspace,
        query="terrain visualization 目前包含哪些 elevation、slope 與 hillshade layer？",
    )

    assert "terrain.candidate.001" in hazards["field_answer"]
    assert "崩壁、落石與暴露地形" in hazards["field_answer"]
    assert "沒有 new landslide candidate" in landslide["field_answer"]
    assert "seg.002" in obscurity["field_answer"]
    assert "score=0.81" in obscurity["field_answer"]
    assert "2 個高候選區" in wetness["field_answer"]
    assert "濕滑候選 12K" in wetness["field_answer"]
    assert "hillshade、elevation_tint、slope_shading、contours" in visualization[
        "field_answer"
    ]


def test_terrain_score_answers_dtm_rate_and_retreat_join(tmp_path: Path) -> None:
    workspace = _write_terrain_workspace(tmp_path)

    coverage = search_project_terrain_scores(
        workspace,
        query="DTM coverage summary 有效覆蓋率與缺口是多少？",
    )
    retreat = search_project_terrain_scores(
        workspace,
        query="哪些 retreat route 最靠近高 terrain risk segment？",
    )

    assert "1/2（50.0%）" in coverage["field_answer"]
    assert "缺口 1 個" in coverage["field_answer"]
    assert "retreat.fixture.return" in retreat["field_answer"]
    assert "seg.002" in retreat["field_answer"]
    assert "不是 field-verified evacuation route" in retreat["field_answer"]


def _write_terrain_workspace(
    tmp_path: Path,
    *,
    include_direct_slope: bool = True,
) -> Path:
    workspace = tmp_path / "terrain-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "normalized").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "environment" / "derived").mkdir(parents=True)
    (workspace / "normalized" / "terrain").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "terrain_fixture",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "segment_candidates_ref": "candidates/segments.json",
                "segment_dtm_coverage_ref": (
                    "normalized/terrain/segment_dtm_coverage.json"
                ),
                "terrain_route_samples_ref": (
                    "outputs/layers/normalized/terrain_route_samples.geojson"
                ),
                "terrain_risk_candidates_ref": (
                    "outputs/layers/candidates/terrain_risk_candidates.json"
                ),
                "new_landslide_candidates_ref": (
                    "outputs/environment/derived/new_landslide_candidates.geojson"
                ),
                "trail_obscurity_risk_ref": (
                    "outputs/environment/derived/trail_obscurity_risk.geojson"
                ),
                "wetness_flash_flood_susceptibility_ref": (
                    "outputs/environment/derived/wetness_flash_flood_susceptibility.geojson"
                ),
                "terrain_visualization_ref": (
                    "outputs/layers/normalized/terrain_visualization.geojson"
                ),
                "retreat_routes_ref": "candidates/retreat_routes.json",
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
    (workspace / "candidates" / "segments.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "seg.001",
                    "from_candidate_id": "cp.start",
                    "to_candidate_id": "cp.001",
                    "distance_m": 1500.0,
                    "route_point_start_index": 0,
                    "route_point_end_index": 15,
                },
                {
                    "candidate_id": "seg.002",
                    "from_candidate_id": "cp.001",
                    "to_candidate_id": "cp.002",
                    "distance_m": 1000.0,
                    "route_point_start_index": 15,
                    "route_point_end_index": 30,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "retreat_routes.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "retreat.fixture.return",
                    "label": "Return to entry",
                    "route_point_start_index": 0,
                    "route_point_end_index": 30,
                    "reversed_from_primary_route": True,
                    "notes": "not a field-verified evacuation route",
                }
            ]
        ),
        encoding="utf-8",
    )
    (workspace / "normalized" / "terrain" / "segment_dtm_coverage.json").write_text(
        json.dumps(
            {
                "segment_count": 2,
                "notes": "Metadata-only coverage candidates.",
                "segment_metadata": [
                    {
                        "segment_candidate_id": "seg.001",
                        "candidate_tiles": [{"tile_ref": "fixture:001"}],
                    },
                    {
                        "segment_candidate_id": "seg.002",
                        "candidate_tiles": [],
                    },
                ],
            },
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
                        "reason": "崩壁、落石與暴露地形候選，等待人工複核。",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_derived_geojson(
        workspace / "outputs" / "environment" / "derived" / "new_landslide_candidates.geojson",
        features=[],
        summary={"feature_count": 0, "high_count": 0, "max_score": None},
    )
    _write_derived_geojson(
        workspace / "outputs" / "environment" / "derived" / "trail_obscurity_risk.geojson",
        features=[_derived_segment("seg.002", "遮蔽候選 2K", 0.81, "high")],
        summary={"feature_count": 1, "high_count": 1, "max_score": 0.81},
    )
    _write_derived_geojson(
        workspace
        / "outputs"
        / "environment"
        / "derived"
        / "wetness_flash_flood_susceptibility.geojson",
        features=[
            _derived_segment("seg.001", "濕滑候選 12K", 0.8, "high"),
            _derived_segment("seg.002", "溪溝候選 13K", 0.76, "high"),
        ],
        summary={
            "feature_count": 2,
            "high_count": 2,
            "max_score": 0.8,
            "top_labels": ["濕滑候選 12K", "溪溝候選 13K"],
        },
    )
    (
        workspace / "outputs" / "layers" / "normalized" / "terrain_visualization.geojson"
    ).write_text(
        json.dumps(
            {
                "raster_overlays": [
                    {"mode": mode, "source_path": f"outputs/{mode}.png"}
                    for mode in ("hillshade", "elevation_tint", "slope_shading", "contours")
                ]
            }
        ),
        encoding="utf-8",
    )
    return workspace


def _write_derived_geojson(
    path: Path,
    *,
    features: list[dict],
    summary: dict,
) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
                "summary": summary,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _derived_segment(
    segment_id: str,
    label: str,
    score: float,
    bucket: str,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[121.0, 24.0], [121.001, 24.001]],
        },
        "properties": {
            "segment_candidate_id": segment_id,
            "label": label,
            "score": score,
            "risk_bucket": bucket,
        },
    }


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
