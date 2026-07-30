from __future__ import annotations

import json
from pathlib import Path

import pytest

from assistant_models import AssistantSurface, ScoutAssistantQuery
from tools import scout_ai_aihat2_fallback_eval as eval_module
from tools.scout_ai_aihat2_fallback_eval import (
    _compact_aihat_context,
    _ensure_synthetic_route_weather_package,
    assess_aihat_answer_quality,
    build_total_info,
    build_prompt,
    call_hailo_model,
    call_hailo_model_via_pydantic_ai,
    require_ai_hat_runtime,
    run_tools,
)
from scout_weather_window_tool import assess_scout_weather_window


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


def test_ups_hat_e_status_reports_read_only_i2c_sample(tmp_path: Path) -> None:
    bus = tmp_path / "i2c-1"
    bus.touch()

    status = eval_module._ups_hat_e_status(
        bus=bus,
        reader=lambda **_kwargs: {
            "battery": {"percent": 87, "voltage_mv": 16240},
            "cell_voltage_mv": [4060, 4061, 4059, 4060],
            "low_cell_threshold_mv": 3150,
            "low_cell_voltage_present": False,
            "power_state": "discharging",
            "vbus": {"voltage_mv": 0, "current_ma": 0, "power_mw": 0},
        },
    )

    assert status["available"] is True
    assert status["read_only"] is True
    assert status["power_control_write_allowed"] is False
    assert status["battery"]["percent"] == 87
    assert status["cell_voltage_mv"] == [4060, 4061, 4059, 4060]


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
    captured: dict[str, object] = {}

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
        captured["think"] = payload.get("think")
        captured["stream"] = payload.get("stream")
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
    assert captured["think"] is False
    assert captured["stream"] is True
    assert len(captured["content"].encode("utf-8")) > 3600
    assert answer == "結論：測試完成"
    assert metadata["model"] == "qwen3:1.7b"


def test_aihat2_eval_stream_stops_after_complete_short_answer(monkeypatch) -> None:
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "D=null\nA=稜線啞口觀景點約在 8.2 km。"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "這段不應再被讀取。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert answer == "D=null\nA=稜線啞口觀景點約在 8.2 km。"
    assert response.read_count == 1
    assert metadata["streaming"] is True
    assert metadata["semantic_completion"] is True


def test_aihat2_eval_stream_does_not_stop_on_decimal_point(monkeypatch) -> None:
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "D=null\nA=里程約 8."},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "2 km。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert answer == "D=null\nA=里程約 8.2 km。"
    assert response.read_count == 2
    assert metadata["semantic_completion"] is True


def test_aihat2_eval_stream_does_not_stop_on_question_echo(monkeypatch) -> None:
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "D=CHANGE_PLAN\nA=今天適合照原計畫出發嗎？"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "不適合；有強風與低能見度，先改變計畫。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert "強風與低能見度" in answer
    assert response.read_count == 2
    assert metadata["semantic_completion"] is True


def test_aihat2_eval_stream_stops_after_complete_answer_with_invalid_decision(
    monkeypatch,
) -> None:
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {
                "content": (
                    "D=Route context candidate。"
                    "A=稜線啞口觀景點可觀察稜線、鞍部與谷線的關係。"
                )
            },
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "A=不應再重複這一句。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert "不應再重複" not in answer
    assert response.read_count == 1
    assert metadata["semantic_completion"] is True
    assert metadata["semantic_stop"] == "short_answer_complete"


def test_aihat2_eval_stream_stops_and_trims_repeated_clause(monkeypatch) -> None:
    repeated_clause = "在這些區域中，歷史與地形的交點被視為重要觀察點"
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {
                "content": (
                    "D=GO\nA=沿途脈絡先連結舊林道與自然環境；"
                    f"{repeated_clause}；"
                )
            },
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": f"{repeated_clause}；"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "這一段不應再被讀取。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert answer.count(repeated_clause) == 1
    assert "不應再被讀取" not in answer
    assert response.read_count == 2
    assert metadata["semantic_completion"] is True
    assert metadata["semantic_stop"] == "repeated_clause"


def test_aihat2_eval_stream_stops_and_trims_repeated_tool_id(monkeypatch) -> None:
    repeated_tool = "scout.ai.weather_window.assess.v0"
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {
                "content": (
                    "D=DELAY\nA=先重新取得 GNSS 定位並人工確認周邊；"
                    "工具:scout.ai.live_navigation_state.assess.v0,"
                    f"{repeated_tool},"
                )
            },
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": f"{repeated_tool},"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "這一段不應再被讀取。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert answer.count(repeated_tool) == 1
    assert "不應再被讀取" not in answer
    assert response.read_count == 2
    assert metadata["semantic_completion"] is True
    assert metadata["semantic_stop"] == "repeated_tool_id"


@pytest.mark.parametrize(
    "prefix",
    [
        "D=沿途地名與地形的關聯如下：",
        "D=GO\nA=秋冬林相與視野的差異是，",
    ],
)
def test_aihat2_eval_stream_stops_on_format_independent_repeated_fragment(
    monkeypatch,
    prefix: str,
) -> None:
    repeated_fragment = "視野會因樹木層次與枝葉覆蓋而變得更為模糊"
    chunks = [
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": f"{prefix}{repeated_fragment}，"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": f"{repeated_fragment}，"},
        },
        {
            "model": "qwen3:1.7b",
            "done": False,
            "message": {"content": "這一段不應再被讀取。"},
        },
    ]

    class FakeStreamingResponse:
        def __init__(self) -> None:
            self.read_count = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def readline(self) -> bytes:
            if self.read_count >= len(chunks):
                return b""
            payload = chunks[self.read_count]
            self.read_count += 1
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode()

    response = FakeStreamingResponse()
    monkeypatch.setattr(
        "tools.scout_ai_aihat2_fallback_eval.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    answer, metadata = call_hailo_model(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="請直接短答",
        timeout_seconds=10,
        structured_json=False,
    )

    assert answer.count(repeated_fragment) == 1
    assert "不應再被讀取" not in answer
    assert response.read_count == 2
    assert metadata["semantic_completion"] is True
    assert metadata["semantic_stop"] == "repeated_fragment"


def test_aihat2_eval_can_route_hailo_through_pydantic_ai_v2() -> None:
    def fake_hailo_call(**kwargs):
        assert kwargs["model"] == "qwen3:1.7b"
        assert kwargs["structured_json"] is True
        return '{"a":"grounded"}', {"model": "qwen3:1.7b", "eval_count": 4}

    answer, metadata = call_hailo_model_via_pydantic_ai(
        endpoint="http://127.0.0.1:8000/api/chat",
        model="qwen3:1.7b",
        prompt="answer from evidence",
        timeout_seconds=10,
        structured_json=True,
        hailo_call=fake_hailo_call,
    )

    assert answer == '{"a":"grounded"}'
    assert metadata["pydantic_ai"]["used"] is True
    assert metadata["pydantic_ai"]["runtime_version"].startswith("2.")
    assert metadata["pydantic_ai"]["requests"] == 1


@pytest.mark.parametrize(
    ("variant_id", "expected_decision", "expected_risk"),
    [
        ("severe_fresh_route_intersecting", "CHANGE_PLAN", 0.82),
        ("benign_fresh_route_intersecting", "GO", 0.15),
        ("stale_unknown_weather", "DELAY", None),
    ],
)
def test_aihat2_synthetic_weather_drives_expected_weather_decision(
    tmp_path: Path,
    variant_id: str,
    expected_decision: str,
    expected_risk: float | None,
) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({"project_id": "synthetic-weather"}),
        encoding="utf-8",
    )
    snapshot = {
        "scenario_id": f"scenario.{variant_id}",
        "observed_at": "2026-07-20T08:00:00+08:00",
        "route_progress_m": 1000,
    }
    weather_ref = _ensure_synthetic_route_weather_package(
        tmp_path,
        live_navigation_snapshot=snapshot,
        scenario_overlay={"variant_id": variant_id},
    )

    result = assess_scout_weather_window(
        tmp_path,
        query="依目前天氣，今天適合照原計畫出發嗎？",
        route_weather_package_path=weather_ref,
        reference_time=snapshot["observed_at"],
    )

    assert result["decision"] == expected_decision
    segment = result["results"][0]
    assert segment.get("weather_risk") == expected_risk
    assert result["external_api_calls_made"] is False


def test_aihat2_eval_accepts_pcie_attestation_without_legacy_device_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_command(
        command: list[str],
        timeout_seconds: float = 5.0,
    ) -> dict[str, object]:
        del timeout_seconds
        if command == ["hailortcli", "scan"]:
            return {
                "returncode": 0,
                "stdout": "Hailo Devices:\n[-] Device: pci/0001:01:00.0",
            }
        return {"returncode": 1, "stdout": ""}

    monkeypatch.setattr(eval_module, "run_command", fake_run_command)
    monkeypatch.setattr(
        eval_module,
        "_hailo_tags",
        lambda: {
            "models": [
                {
                    "name": "qwen3:1.7b",
                    "format": "hef",
                    "parameter_size": "1.7B",
                }
            ]
        },
    )

    require_ai_hat_runtime("http://127.0.0.1:8000/api/chat")


def test_aihat2_eval_uses_same_scenario_for_total_info_tool_and_compact_evidence(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "scenario-project"}),
        encoding="utf-8",
    )
    snapshot = {
        "scenario_id": "six600.PER-095.rank-5",
        "observed_at": "2026-07-16T08:00:00+08:00",
        "lat": 24.048743595,
        "lon": 121.260414740,
        "elevation_m": 2688.75,
        "source": "six_forces_scenario:synthetic_replay",
        "hdop": 0.9,
        "horizontal_accuracy_m": 5,
        "fix_quality": "synthetic_route_interpolation",
        "satellite_count": 12,
        "max_cno_dbhz": 38,
        "heading_deg": 71.457861,
        "course_deg": 71.457861,
        "speed_mps": 0.8,
        "nearest_route_distance_m": 0,
        "route_progress_m": 53250,
        "nearest_cp_id": "cp.106",
        "travel_direction": "increasing_route_progress",
        "distance_to_boss_along_route_m": 500,
        "boss_point_id": "boss.005",
        "boss_rank": 5,
        "ins_dr_source": "scenario_route_interpolation",
        "confidence": 0.95,
        "uncertainty_m": 5,
        "last_anchor_at": "2026-07-16T08:00:00+08:00",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="這裡適合做臨時避風停留，還是需要繼續移動？",
        project_id="scenario-project",
        live_navigation_snapshot=snapshot,
    )

    total_info = build_total_info(
        project_root,
        query,
        reference_time=snapshot["observed_at"],
    )
    tool_results, missing_tools, missing_evidence = run_tools(
        query=query,
        project_root=project_root,
        tool_ids=["scout.ai.live_navigation_state.assess.v0"],
        max_tools=10,
        synthetic_field_context=True,
        live_navigation_snapshot=snapshot,
    )
    compact = _compact_aihat_context(
        qeval={"id": "PER-095", "category": "contextual_permission"},
        total_info=total_info,
        tool_results=tool_results,
        missing_tools=missing_tools,
        missing_evidence=missing_evidence,
    )

    total_location = total_info["location_context"]["live_navigation_snapshot"]
    tool_location = tool_results[0]["provided_fields"]
    compact_location = compact["total_info"]["location"]
    for field in ("scenario_id", "lat", "lon", "route_progress_m"):
        assert total_location[field] == snapshot[field]
        assert tool_location[field] == snapshot[field]
        assert compact_location[field] == snapshot[field]
        assert tool_results[0]["scenario_context"][field] == snapshot[field]
