from __future__ import annotations

import json
import shutil
from pathlib import Path

from tools.scout_ai_route_context_briefing_variants import (
    ARTIFACT_KIND,
    PLAN_KIND,
    PLAN_VERSION,
    analyze_html,
    generate_route_context_briefing_variants,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
SKILL_PATH = REPO_ROOT / "skills" / "scout" / "route-context-intelligence.yaml"


class FakeVariantRunner:
    model_name = "nvidia:z-ai/glm-5.2"

    def __init__(self) -> None:
        self.last_prompt: str | None = None
        self.last_response: str | None = None
        self.last_usage = {
            "provider_reported": True,
            "input_tokens": 1234,
            "output_tokens": 567,
            "total_tokens": 1801,
            "requests": 1,
            "tool_calls": 0,
            "details": {},
        }

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        self.last_prompt = prompt
        self.last_response = json.dumps(_valid_plan(), ensure_ascii=False)
        return self.last_response


def test_route_context_variant_generation_records_prompt_response_usage(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT, project_root)
    baseline = project_root / "outputs" / "briefings" / "route_context_briefing.html"
    output_dir = project_root / "outputs" / "briefings" / "route_context_variants_ai_once"
    runner = FakeVariantRunner()

    result = generate_route_context_briefing_variants(
        project_root=project_root,
        baseline_html=baseline,
        skill_path=SKILL_PATH,
        output_dir=output_dir,
        runner=runner,
        timeout_seconds=30,
        generated_at="2026-07-05T08:00:00Z",
    )

    assert result["artifact_kind"] == ARTIFACT_KIND
    assert result["status"] == "completed"
    assert result["model"] == "nvidia:z-ai/glm-5.2"
    assert len(result["variant_refs"]) == 5
    assert all((output_dir / ref).is_file() for ref in result["variant_refs"])

    model_plan = json.loads(
        (output_dir / "scout_ai_route_context_variant_model_plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert model_plan["token_usage"]["provider_reported"] is True
    assert model_plan["token_usage"]["input_tokens"] == 1234
    assert model_plan["token_usage"]["output_tokens"] == 567
    assert model_plan["token_usage"]["total_tokens"] == 1801
    assert "Generate exactly five complete route-content briefing variant specs" in model_plan[
        "prompt_content"
    ]
    assert model_plan["response_content"] == runner.last_response
    assert model_plan["boundary"]["raw_prompt_embedded"] is True
    assert model_plan["boundary"]["raw_response_embedded"] is True
    assert model_plan["boundary"]["api_key_embedded"] is False
    assert model_plan["parsed_plan"]["one_model_call_complete"] is True
    assert model_plan["parsed_plan"]["no_codex_posthoc_supplement"] is True

    comparison = json.loads(
        (output_dir / "route_context_variant_comparison.json").read_text(
            encoding="utf-8"
        )
    )
    assert comparison["one_model_call_complete"] is True
    assert comparison["no_codex_posthoc_supplement"] is True
    assert len(comparison["variants"]) == 5
    assert all(item["generated_by_single_model_plan"] for item in comparison["variants"])
    assert all(item["codex_posthoc_supplement"] is False for item in comparison["variants"])
    assert all(item["passes_unrelated_terms_gate"] for item in comparison["variants"])
    assert all(item["passes_bad_image_gate"] for item in comparison["variants"])

    first_variant = analyze_html(output_dir / result["variant_refs"][0], slug="first")
    assert first_variant["images"] > 0
    assert not first_variant["unrelated_terms"]
    assert not first_variant["bad_image_refs"]


def _valid_plan() -> dict[str, object]:
    return {
        "artifact_kind": PLAN_KIND,
        "schema_version": PLAN_VERSION,
        "skill_id": "route-context-intelligence",
        "one_model_call_complete": True,
        "no_codex_posthoc_supplement": True,
        "variants": [_variant(index) for index in range(1, 6)],
    }


def _variant(index: int) -> dict[str, object]:
    slugs = [
        "editorial-atlas",
        "expedition-command-wall",
        "field-notebook",
        "topographic-magazine",
        "night-navigation",
    ]
    tones = [
        "山岳雜誌長篇",
        "隊伍作戰牆",
        "領隊野帳",
        "等高線地誌",
        "夜航黑板",
    ]
    return {
        "slug": slugs[index - 1],
        "title": f"{tones[index - 1]}：奇萊南華路線脈絡",
        "subtitle": "從林道、保線所、天池山莊到光被八表的行前閱讀",
        "tone": tones[index - 1],
        "concept": f"{tones[index - 1]}視角",
        "editorial_thesis": "這份版本把沿途地形、自然、文化與短停觀察拆成隊伍出發前能討論的段落。",
        "hero_caption": "能高越嶺道高山景觀與稜線展望。",
        "nav_labels": ["總覽", "照片", "比例", "章節", "觀察", "來源"],
        "layer_headlines": {
            "historical": "保線與舊路痕跡是理解路線節奏的背景。",
            "cultural": "地名與通行記憶提供隊伍講述路線的入口。",
            "natural": "林相、水線與雲霧讓路線不只是距離。",
            "terrain": "崩壁、啞口與稜線轉換決定閱讀重點。",
            "seasonal": "雲海、低溫與午後變化要放進行前討論。",
            "observation": "短停題目用來提問，不是現地停留授權。",
        },
        "chapter_titles": [f"第{i}章：路段閱讀 {index}-{i}" for i in range(1, 9)],
        "observation_prompts": [
            f"觀察題 {index}-{i}：把眼前路段和下一個中繼點連起來。"
            for i in range(1, 11)
        ],
        "point_angles": [
            {
                "label": f"路線點 {i}",
                "angle": f"從隊伍節奏看這個點的地形與視野轉換 {i}。",
                "question": f"隊伍在這裡應該先確認哪個方向線索 {i}？",
                "route_reading": f"這個點可作為路段脈絡討論，不直接推論現地決策 {i}。",
            }
            for i in range(1, 19)
        ],
        "chart_titles": [f"圖表 {index}-{i}" for i in range(1, 7)],
        "source_storyline": "官方路線圖、行程點與路線影像先分開看，再合併成行前討論順序。",
        "leader_review_focus": "領隊先確認路段照片、短停提問與資料來源是否能支撐隊伍說明。",
        "closing_note": "把這份版本當作行前閱讀，不把它當成現地停留或安全決策。",
    }
