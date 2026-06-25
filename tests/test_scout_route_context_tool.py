import json
from pathlib import Path

from scout_route_context_tool import (
    ROUTE_CONTEXT_OUTPUT_KIND,
    ROUTE_CONTEXT_TOOL_ID,
    assess_scout_route_context,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_route_context_finds_candidate_viewpoint_and_experience_guidance() -> None:
    result = assess_scout_route_context(
        PROJECT_ROOT,
        query="哪裡適合拍攝或觀察大景?",
        limit=4,
    )

    assert result["tool_id"] == ROUTE_CONTEXT_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "route_context_available"
    assert result["source_status"] == "candidate_only"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["firstLayer"]["decision"] == "可作為候選觀察點。"
    assert "不是停留授權" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["result_count"] >= 1
    assert result["route_context"]["role"] == "Experience Guide"
    assert result["route_context"]["stop_permission_required"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False
    assert "Experience Guide 候選" in result["field_answer"]
    assert "contextual permission" in result["field_answer"]

    labels = {item["label"] for item in result["results"]}
    assert "稜線啞口觀景點" in labels
    viewpoint = next(item for item in result["results"] if item["label"] == "稜線啞口觀景點")
    assert viewpoint["context_kind"] == "viewpoint"
    assert viewpoint["candidate_only"] is True
    assert viewpoint["runtime_safety_truth"] is False
    assert "停留風險預算" in viewpoint["stop_guidance"]


def test_route_context_covers_standard_natural_and_cultural_layers() -> None:
    natural = assess_scout_route_context(
        PROJECT_ROOT,
        query="這段林相變化有什麼可以觀察？",
        limit=4,
    )
    natural_hints = set(natural["filters"]["context_hints"])

    assert natural["answerability"] == "route_context_available"
    assert natural["decision"] == "CONDITIONAL_GO"
    assert natural["route_context"]["role"] == "Experience Guide"
    assert natural["boundary"]["runtime_safety_truth"] is False
    assert "route_context" in natural_hints
    assert "viewpoint" in natural_hints
    assert "Experience Guide 候選" in natural["field_answer"]

    cultural = assess_scout_route_context(
        PROJECT_ROOT,
        query="有哪些原住民族地名或舊社脈絡？",
        limit=4,
    )
    cultural_hints = set(cultural["filters"]["context_hints"])

    assert cultural["answerability"] == "route_context_available"
    assert cultural["decision"] == "CONDITIONAL_GO"
    assert cultural["route_context"]["role"] == "Experience Guide"
    assert cultural["boundary"]["runtime_safety_truth"] is False
    assert {"resource_context", "route_context"}.issubset(cultural_hints)
    assert "Experience Guide 候選" in cultural["field_answer"]


def test_route_context_reads_canonical_route_context_pack_for_briefing_questions() -> None:
    days = assess_scout_route_context(
        PROJECT_ROOT,
        query="奇萊南華建議幾天？",
        limit=4,
    )

    assert days["answerability"] == "route_context_available"
    assert days["route_briefing"]["available"] is True
    assert days["route_briefing"]["candidate_only"] is True
    assert days["route_briefing"]["runtime_safety_truth"] is False
    assert days["route_briefing"]["source_path"].endswith("route_context_pack.json")
    assert "2 天 1 夜" in days["field_answer"]
    assert "3 天 2 夜" in days["field_answer"]
    assert "route_context_pack" in {
        source["source_kind"] for source in days["source_report"]
    }

    stops = assess_scout_route_context(
        PROJECT_ROOT,
        query="哪些點值得停 3 分鐘？",
        limit=4,
    )

    assert stops["answerability"] == "route_context_available"
    assert "候選 3 分鐘觀察點" in stops["field_answer"]
    assert "不是現場停留授權" in stops["field_answer"]


def test_route_context_answers_exact_mileage_anchor_location() -> None:
    result = assess_scout_route_context(
        PROJECT_ROOT,
        query="本次路徑的15K在哪",
        limit=5,
    )

    assert result["answerability"] == "route_context_available"
    assert result["filters"]["requested_mileage_anchors"] == ["15k"]
    assert result["result_count"] == 1
    anchor = result["results"][0]
    assert anchor["candidate_id"] == "route_context.route_note_candidates.workspace_route.15K"
    assert anchor["evidence_type"] == "trail_mileage_k_anchor"
    assert anchor["normalized_mileage_k"] == "15K"
    assert anchor["distance_m"] == 15000.0
    assert anchor["route_mileage_m"] == 15000.0
    assert anchor["lat"] == 24.034234788
    assert anchor["lon"] == 121.280180449
    assert anchor["runtime_safety_truth"] is False
    assert "15K 在本次路徑約 15.0 km 處" in result["field_answer"]
    assert "lat 24.034234788, lon 121.280180449" in result["field_answer"]
    assert "runtime_safety_truth=false" in result["field_answer"]


def test_route_context_reads_standalone_route_mileage_anchor_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "mileage_anchor_fixture",
                "route_context_points_ref": "candidates/route_context_points.json",
                "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "route_context_points.json").write_text(
        json.dumps({"artifact_kind": "empty_route_context", "points": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (workspace / "candidates" / "route_mileage_k_anchors.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_route_mileage_k_anchors",
                "anchors": [
                    {
                        "candidate_id": "route_context.route_note_candidates.workspace_route.15K",
                        "candidate_only": True,
                        "display_label": "15K",
                        "label_role": "trail_mileage_k_anchor",
                        "lat": 24.034234788,
                        "lon": 121.280180449,
                        "mileage_anchor_kind": "trail_mileage_k_anchor",
                        "mileage_k": 15.0,
                        "mileage_m": 15000.0,
                        "normalized_mileage_k": "15K",
                        "review_required": True,
                        "runtime_safety_truth": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = assess_scout_route_context(workspace, query="本次路徑的15K在哪", limit=5)

    assert result["answerability"] == "route_context_available"
    assert result["filters"]["requested_mileage_anchors"] == ["15k"]
    assert result["result_count"] == 1
    anchor = result["results"][0]
    assert anchor["source_path"] == "candidates/route_mileage_k_anchors.json"
    assert anchor["normalized_mileage_k"] == "15K"
    assert anchor["route_mileage_m"] == 15000.0
    assert "15K 在本次路徑約 15.0 km 處" in result["field_answer"]
    assert "runtime_safety_truth=false" in result["field_answer"]


def test_route_context_keeps_risk_context_from_becoming_stop_permission() -> None:
    result = assess_scout_route_context(
        PROJECT_ROOT,
        query="大崩壁值得停下來看嗎?",
        limit=4,
    )

    risk_items = [item for item in result["results"] if item["label"] == "大崩壁"]
    assert risk_items
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議為觀察或拍攝停留。"
    )
    assert risk_items[0]["context_kind"] == "risk_context"
    assert "不建議" in risk_items[0]["stop_guidance"]
    assert result["route_context"]["stop_permission_tool_id"] == (
        "scout.ai.contextual_permission.assess.v0"
    )


def test_route_context_output_kind_constant() -> None:
    assert ROUTE_CONTEXT_OUTPUT_KIND == "scout_ai_route_context_tool_output"
