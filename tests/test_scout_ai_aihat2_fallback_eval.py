from __future__ import annotations

import json

from tools.scout_ai_aihat2_fallback_eval import (
    assess_aihat_answer_quality,
    build_prompt,
    call_hailo_model,
)


def test_aihat2_eval_prompt_does_not_instruct_template_copy() -> None:
    prompt = build_prompt(
        question="哪些地方下雨後會變危險？",
        qeval={"id": "field-001", "category": "terrain_risk"},
        total_info=None,
        tool_results=[],
        missing_tools=[],
        missing_evidence=[],
        context={
            "deterministic_answer_hint": (
                "雨後需優先人工複核的最高候選風險點在最近 CP 213 約 190 m；"
                "GPX 累積約 106.27 km；score=99.58；bucket=extreme。"
            )
        },
    )

    assert "幾乎照抄" not in prompt
    assert "不得整段照抄" in prompt
    assert "Scout 工具摘要" in prompt


def test_aihat2_eval_prompt_uses_plain_text_tool_evidence() -> None:
    prompt = build_prompt(
        question="route summary 的距離是多少？",
        qeval={"id": "workspace-001", "category": "route_structure"},
        total_info=None,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_route_structure.v0",
                "status": "completed",
                "summary": {"distance_km": 112.258, "point_count": 7052},
                "records": [{"source_path": "normalized/routes/route_summary.json"}],
            }
        ],
        missing_tools=[],
        missing_evidence=[],
        context={"deterministic_answer_hint": None},
    )

    assert "Scout 短上下文 JSON" not in prompt
    assert "distance_km=112.258" in prompt
    assert "point_count=7052" in prompt
    assert '"distance_km"' not in prompt


def test_aihat2_eval_quality_fails_template_copy_of_deterministic_hint() -> None:
    hint = (
        "雨後需優先人工複核的最高候選風險點在最近 CP 213 約 190 m；"
        "GPX 累積約 106.27 km；座標 23.9349004,121.2072142；"
        "score=99.58；bucket=extreme。"
    )

    quality = assess_aihat_answer_quality(
        f"結論：{hint}",
        missing_tools=[],
        missing_evidence=[],
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
                "records": [
                    {
                        "readable_location": "最近 CP 213 約 190 m",
                        "score": 99.58,
                        "risk_bucket": "extreme",
                    }
                ],
            }
        ],
        deterministic_answer_hint=hint,
    )

    assert quality["classification"] == "quality_fail"
    assert "template_copy_of_deterministic_hint" in quality["failure_reasons"]


def test_aihat2_eval_normalizes_hailo_chat_control_characters(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "model": "qwen3:1.7b",
                    "done": True,
                    "message": {"content": "結論：測試完成"},
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        captured["content"] = payload["messages"][0]["content"]
        return FakeResponse()

    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        fake_urlopen,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="第一行\n第二行\t第三行\x7f" + ("甲" * 5000),
        timeout_seconds=10,
    )

    assert captured["content"].startswith("第一行 第二行 第三行")
    assert captured["content"].count("甲") == 5000
    assert len(captured["content"].encode("utf-8")) > 3600
    assert answer == "結論：測試完成"
    assert metadata["model"] == "qwen3:1.7b"
