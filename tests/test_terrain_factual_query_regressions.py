from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_ai_tool_executor import execute_scout_ai_tool
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID, search_project_terrain_scores


@pytest.fixture
def terrain_workspace(tmp_path: Path) -> Path:
    project = {
        "project_id": "terrain-intent-fixture",
        "terrain_route_samples_ref": "terrain.geojson",
        "segment_candidates_ref": "segments.json",
        "segment_dtm_coverage_ref": "coverage.json",
    }
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [121.0, 24.0]},
            "properties": {
                "sample_id": "terrain.a",
                "distance_m": 600,
                "teii_20m": 23,
                "slope_degrees": 12,
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [121.01, 24.01]},
            "properties": {
                "sample_id": "terrain.b",
                "distance_m": 2200,
                "teii_20m": 94,
                "slope_degrees": 48,
            },
        },
    ]
    segments = [
        {
            "candidate_id": "seg.a",
            "from_candidate_id": "cp.a",
            "to_candidate_id": "cp.b",
            "distance_m": 1800,
        },
        {
            "candidate_id": "seg.b",
            "from_candidate_id": "cp.b",
            "to_candidate_id": "cp.c",
            "distance_m": 900,
        },
    ]
    coverage = {
        "segment_count": len(segments),
        "segment_metadata": [
            {"segment_candidate_id": "seg.a", "candidate_tiles": ["tile.a"]},
            {"segment_candidate_id": "seg.b", "candidate_tiles": []},
        ],
    }
    for filename, payload in (
        ("project.json", project),
        ("terrain.geojson", {"type": "FeatureCollection", "features": features}),
        ("segments.json", segments),
        ("coverage.json", coverage),
    ):
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


FACT_QUERIES = [
    "terrain samples 的來源檔案與欄位有哪些？",
    "How many terrain records are in each category?",
    "terrain segments 的 TEII sample 各有多少筆？",
    "地形候選的各類別數量是多少？",
    "地圖里程與 GPX 累積距離有何差別，terrain score 使用哪個單位？",
    "MCP 最近 CP 的距離、支援半徑與座標可信度各是多少？",
    "列出 terrain 資料的 source_ref 和 CRS。",
    "What does the NO_GO category mean in the terrain catalog?",
    "不要判斷地形是否安全，只列出 terrain 記錄數。",
    'Count terrain records tagged "can I proceed".',
    "terrain.csv 有幾筆資料？",
    "What fields does terrain_score contain?",
    "terrain score metadata at 2 km",
]


@pytest.mark.parametrize("question", FACT_QUERIES)
def test_factual_query_retains_evidence_without_decision(
    terrain_workspace: Path, question: str
) -> None:
    reference = search_project_terrain_scores(
        terrain_workspace, query=question, metric="teii"
    )
    raw = json.loads((terrain_workspace / "terrain.geojson").read_text())
    assert reference["result_count"] > 0
    assert reference["searched_sample_count"] == len(raw["features"])
    assert reference["results"][0]["score"] == max(
        row["properties"]["teii_20m"] for row in raw["features"]
    )
    assert "terrain.geojson" in reference["source_refs"]
    assert reference["summaries"]["teii_20m"]["count"] == len(raw["features"])
    assert reference["highest_metric_segment"]["segment_candidate_id"] == "seg.b"
    assert reference["decision"] is None
    assert reference["decision_output"] == {}
    assert reference["terrain_decision"]["decision"] is None
    assert reference["terrain_decision"]["decision_output"] == {}
    assert reference["terrain_decision"]["next_action"] is None
    assert reference["decision_applicable"] is False
    assert reference["answerability"] == "terrain_score_evidence_available"
    assert not reference["field_answer"]
    assert reference["field_answer_priority"] < 100
    assert reference["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize(
    "question",
    [
        "這段地形是否安全？",
        "這裡可以繼續走嗎？",
        "我應該停止前進嗎？",
        "Can I proceed across this terrain?",
        "Should I stop here?",
        "Is this terrain safe?",
        "Is it safe to cross this terrain?",
        "列出地形資料，並判斷我現在是否可以通過。",
        "Count terrain samples, then tell me whether I should continue.",
        "Count terrain records but don't forget to tell me whether I should stop.",
        "地形資料顯示高分，我可不可以走？",
        "I need a terrain go/no-go decision.",
    ],
)
def test_real_decision_queries_preserve_hazard_policy(
    terrain_workspace: Path, question: str
) -> None:
    result = search_project_terrain_scores(
        terrain_workspace, query=question, metric="teii"
    )
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["terrain_decision"]["next_action"]
    assert result["answerability"] == "terrain_score_decision_available"
    assert result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["hardware_control_allowed"] is False


def test_low_score_factual_lookup_does_not_grant_go(terrain_workspace: Path) -> None:
    payload = json.loads((terrain_workspace / "terrain.geojson").read_text())
    payload["features"] = payload["features"][:1]
    (terrain_workspace / "terrain.geojson").write_text(json.dumps(payload))

    factual = search_project_terrain_scores(terrain_workspace, query="terrain 資料共有幾筆？")
    decision = search_project_terrain_scores(terrain_workspace, query="Can I proceed?")
    assert factual["results"] == decision["results"]
    assert factual["summaries"] == decision["summaries"]
    assert factual["decision"] is None
    assert factual["decision_output"] == {}
    assert decision["decision"] == "GO"
    assert decision["boundary"]["runtime_safety_truth"] is False


def test_empty_factual_lookup_does_not_invent_delay(terrain_workspace: Path) -> None:
    (terrain_workspace / "terrain.geojson").write_text(json.dumps({"features": []}))
    factual = search_project_terrain_scores(terrain_workspace, query="terrain 記錄數是多少？")
    decision = search_project_terrain_scores(terrain_workspace, query="Is the terrain safe?")

    assert factual["decision"] is None
    assert factual["decision_output"] == {}
    assert factual["missing_fields"] == ["terrain_score_results"]
    assert not factual["field_answer"]
    assert decision["decision"] == "DELAY"
    assert decision["decision_output"]["allowed"] is False


def test_supported_coverage_fact_keeps_answer_not_decision(terrain_workspace: Path) -> None:
    result = search_project_terrain_scores(
        terrain_workspace, query="DTM coverage 有效覆蓋率與缺口是多少？"
    )
    assert "1/2" in result["field_answer"]
    assert "seg.b" in result["field_answer"]
    assert result["field_answer_source_ref"] == "coverage.json"
    assert result["field_answer_priority"] == 100
    assert result["decision"] is None
    assert result["decision_output"] == {}


def test_actual_executor_preserves_factual_contract(terrain_workspace: Path) -> None:
    question = "請提供 terrain 類別數量與來源欄位。"
    result = execute_scout_ai_tool(
        {"tool_id": TERRAIN_SCORE_TOOL_ID, "project_root": str(terrain_workspace), "query": question}
    )
    assert result.status == "completed"
    assert result.payload["query"] == question
    assert result.payload["results"]
    assert result.payload["source_refs"]
    assert result.payload["decision"] is None
    assert result.payload["decision_output"] == {}
    assert result.boundary.runtime_safety_truth is False
