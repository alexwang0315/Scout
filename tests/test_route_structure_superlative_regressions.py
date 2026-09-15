from __future__ import annotations

import json
from pathlib import Path

import pytest

from scout_workspace_search_tools import search_project_route_structure


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
)


@pytest.mark.parametrize(
    "question",
    [
        "最短的相鄰 CP 路段是哪段？請給兩端及距離，不要重複最長路段。",
        "不要給最長路段，請找距離最短的路段。",
        "不是最長而是最短的 CP 路段，長度是多少？",
        "Which segment is shortest, not longest?",
        "Do not repeat the longest segment; give the shortest segment and its distance.",
    ],
)
def test_shortest_is_selected_from_fixture_not_negated_longest(question: str) -> None:
    segments = json.loads((PROJECT_ROOT / "candidates/segments.json").read_text())
    expected = min(segments, key=lambda row: float(row["distance_m"]))
    longest = max(segments, key=lambda row: float(row["distance_m"]))
    result = search_project_route_structure(PROJECT_ROOT, query=question)

    assert expected["candidate_id"] in result["field_answer"]
    assert (
        result["summaries"]["shortest_segment"]["candidate_id"]
        == expected["candidate_id"]
    )
    assert expected["from_candidate_id"] in result["field_answer"]
    assert expected["to_candidate_id"] in result["field_answer"]
    assert str(float(expected["distance_m"])) in result["field_answer"]
    assert longest["candidate_id"] not in result["field_answer"]
    assert result["field_answer_source_ref"] == "candidates/segments.json"
    assert result["field_answer_priority"] == 100


@pytest.mark.parametrize(
    "question",
    [
        "最短和最長的 CP 路段分別是哪段？",
        "List the shortest and longest route segments.",
    ],
)
def test_both_requested_extrema_are_answered(question: str) -> None:
    segments = json.loads((PROJECT_ROOT / "candidates/segments.json").read_text())
    result = search_project_route_structure(PROJECT_ROOT, query=question)
    for select in (min, max):
        expected = select(segments, key=lambda row: float(row["distance_m"]))
        assert expected["candidate_id"] in result["field_answer"]


@pytest.mark.parametrize(
    "question", ["不要列出最長路段。", "Do not report the longest segment."]
)
def test_only_negated_extremum_does_not_force_answer(question: str) -> None:
    result = search_project_route_structure(PROJECT_ROOT, query=question)
    assert result["field_answer"] is None
    assert result["field_answer_priority"] == 0


def test_extrema_use_different_structured_values_and_preserve_missingness(
    tmp_path: Path,
) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({"segment_candidates_ref": "segments.json"})
    )
    rows = [
        {
            "candidate_id": "seg.a",
            "from_candidate_id": "cp.a",
            "to_candidate_id": "cp.b",
            "distance_m": 82.25,
        },
        {
            "candidate_id": "seg.b",
            "from_candidate_id": "cp.b",
            "to_candidate_id": "cp.c",
            "distance_m": 0,
        },
        {
            "candidate_id": "seg.c",
            "from_candidate_id": "cp.c",
            "to_candidate_id": "cp.d",
            "distance_m": None,
        },
    ]
    (tmp_path / "segments.json").write_text(json.dumps(rows))
    result = search_project_route_structure(
        tmp_path, query="最短和最長的路段各是哪段？"
    )

    assert result["summaries"]["shortest_segment"]["candidate_id"] == "seg.b"
    assert result["summaries"]["shortest_segment"]["distance_m"] == 0
    assert result["summaries"]["longest_segment"]["candidate_id"] == "seg.a"
    assert "seg.a" in result["field_answer"] and "seg.b" in result["field_answer"]
    assert "缺" in result["field_answer"]


def test_no_distances_does_not_invent_shortest(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({"segment_candidates_ref": "segments.json"})
    )
    (tmp_path / "segments.json").write_text(
        json.dumps([{"candidate_id": "seg.unknown"}])
    )
    result = search_project_route_structure(tmp_path, query="哪個路段最短？")
    assert result["summaries"]["shortest_segment"] is None
    assert "缺失" in result["field_answer"]
    assert "seg.unknown" not in result["field_answer"]


@pytest.mark.parametrize(
    "question",
    [
        "歷史時間中，哪一段 P50 最長？它有多少樣本？",
        "Which historical segment has the longest median duration?",
        "Which segment has the shortest walking time?",
        "最短的歷史耗時是哪段？",
        "不要給距離，請給最長的歷史時間。",
    ],
)
def test_duration_superlative_does_not_force_distance_answer(question: str) -> None:
    result = search_project_route_structure(PROJECT_ROOT, query=question)
    assert not result["field_answer"] or "距離最" not in result["field_answer"]


def test_timing_summary_keeps_all_rows_and_quantiles(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({"reference_segment_timing_ref": "timing.json"})
    )
    rows = [
        {
            "segment_id": f"historical.{index}",
            "label": f"Leg {index}",
            "sample_count": 4,
            "source_count": 2,
            "duration_minutes": {
                "min": 0,
                "p25": 7.5,
                "p50": 12.5,
                "p75": 20,
                "max": 25,
            },
        }
        for index in range(15)
    ]
    rows[-1]["duration_minutes"]["p25"] = None
    (tmp_path / "timing.json").write_text(json.dumps({"segments": rows}))
    result = search_project_route_structure(
        tmp_path, query="歷史時間各個分位數是什麼？"
    )
    timing = result["summaries"]["reference_segment_timing"]
    assert len(timing["segments"]) == len(rows)
    assert timing["segments"][0]["duration_minutes"]["p25"] == 7.5
    assert timing["segments"][0]["duration_minutes"]["min"] == 0
    assert timing["segments"][0]["duration_minutes"]["range"] == 25
    assert timing["segments"][-1]["duration_minutes"]["p25"] is None
    assert timing["source_ref"] == "timing.json"
    assert timing["runtime_safety_truth"] is False


@pytest.mark.parametrize("low,high,expected", [(5.2, 8.9, 3.7), (0, 0, 0), (None, 3, None), (9, 3, None), (-2, 3, None)])
def test_timing_range_is_computed_only_from_valid_bounds(tmp_path, low, high, expected):
    from scout_workspace_search_tools import _reference_segment_timing_summary

    (tmp_path / "timing.json").write_text(json.dumps({"segments": [
        {"segment_id": "test.segment", "duration_minutes": {"min": low, "max": high}}
    ]}))
    result = _reference_segment_timing_summary(tmp_path, {"reference_segment_timing_ref": "timing.json"})
    duration = result["segments"][0]["duration_minutes"]
    assert duration["range"] == expected
    assert duration["min"] == low
    assert duration["max"] == high
