from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import pytest

import scout_workspace_search_tools as workspace_tools


IDS = ["station.entry", "station.shelf", "station.saddle", "station.finish"]


def _checkpoints(ids: list[str] | None = None) -> list[dict]:
    return [{"candidate_id": value, "label": "Shared label"} for value in (ids or IDS)]


def _segments(pairs: list[tuple[str, str]] | None = None) -> list[dict]:
    pairs = list(zip(IDS, IDS[1:])) if pairs is None else pairs
    return [
        {
            "candidate_id": f"link.{index + 11}",
            "from_candidate_id": start,
            "to_candidate_id": end,
            "distance_m": 81.25 + index,
        }
        for index, (start, end) in enumerate(pairs)
    ]


def _continuity(checkpoints, segments) -> dict:
    return workspace_tools._checkpoint_quality_summary(checkpoints, segments)[
        "checkpoint_chain_continuity"
    ]


def test_legacy_count_check_can_match_disconnected_records() -> None:
    segments = _segments([(IDS[0], IDS[1]), (IDS[1], IDS[0]), (IDS[2], IDS[3])])
    result = workspace_tools._checkpoint_quality_summary(_checkpoints(), segments)

    assert result["segment_count_matches_checkpoint_chain"] is True
    assert result["segment_count_delta_from_expected"] == 0
    assert result["expected_segment_count_from_checkpoints"] == 3
    assert result["checkpoint_duplicate_label_groups"] == {"Shared label": IDS}


def test_legacy_count_field_is_explicitly_count_only() -> None:
    result = workspace_tools._checkpoint_quality_summary(_checkpoints(), _segments())

    assert result["segment_count_matches_checkpoint_chain"] is True
    assert result["segment_count_matches_checkpoint_chain_basis"] == "count_only"


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_valid_chain_is_independent_of_segment_array_order(order) -> None:
    segments = _segments()
    result = _continuity(_checkpoints(), [segments[index] for index in order])

    assert result["status"] == "valid"
    assert result["is_single_chain"] is True
    assert result["checkpoint_order"] == IDS
    assert result["segment_order"] == [segment["candidate_id"] for segment in segments]
    assert result["start_checkpoint_id"] == IDS[0]
    assert result["end_checkpoint_id"] == IDS[-1]
    assert result["component_count"] == 1
    assert result["has_cycle"] is False
    assert result["reason_codes"] == []


def test_chain_order_comes_from_endpoints_not_labels_or_checkpoint_array() -> None:
    checkpoints = list(reversed(_checkpoints()))
    result = _continuity(checkpoints, _segments())

    assert result["is_single_chain"] is True
    assert result["checkpoint_order"] == IDS
    assert result["scope"] == "provided_checkpoint_and_segment_identifier_graph"
    assert result["source_completeness"] == "not_assessed"


@pytest.mark.parametrize(
    ("pairs", "reason", "detail_key", "detail_value"),
    [
        ([(0, 1), (1, 0), (2, 3)], "disconnected", "component_count", 2),
        ([(0, 1), (1, 2), (2, 0)], "cycle", "has_cycle", True),
        ([(0, 1), (0, 2), (2, 3)], "branching", "branching_checkpoint_ids", [IDS[0]]),
        ([(0, 2), (1, 2), (2, 3)], "merging", "merging_checkpoint_ids", [IDS[2]]),
        ([(0, 0), (1, 2), (2, 3)], "cycle", "has_cycle", True),
        ([(0, 1), (0, 1), (2, 3)], "branching", "branching_checkpoint_ids", [IDS[0]]),
        ([(0, 1), (2, 1), (2, 3)], "merging", "merging_checkpoint_ids", [IDS[1]]),
    ],
    ids=["disconnected", "cycle", "branch", "merge", "self-loop", "parallel", "reversed-link"],
)
def test_same_counts_do_not_prove_endpoint_chain(pairs, reason, detail_key, detail_value) -> None:
    segments = _segments([(IDS[start], IDS[end]) for start, end in pairs])
    summary = workspace_tools._checkpoint_quality_summary(_checkpoints(), segments)
    result = summary["checkpoint_chain_continuity"]

    assert summary["segment_count_matches_checkpoint_chain"] is True
    assert result["status"] == "invalid"
    assert result["is_single_chain"] is False
    assert reason in result["reason_codes"]
    assert result[detail_key] == detail_value
    assert result["checkpoint_order"] is None
    assert result["physical_gpx_geometry_continuity"] is None


def test_unknown_endpoint_is_not_coerced_or_ignored() -> None:
    segments = _segments()
    segments[1]["to_candidate_id"] = "Station.Saddle"
    result = _continuity(_checkpoints(), segments)

    assert result["status"] == "invalid"
    assert result["is_single_chain"] is False
    assert result["unknown_endpoint_ids"] == ["Station.Saddle"]
    assert "unknown_endpoints" in result["reason_codes"]


@pytest.mark.parametrize("collection", ["checkpoints", "segments"])
def test_duplicate_record_ids_are_explicitly_invalid(collection) -> None:
    checkpoints, segments = _checkpoints(), _segments()
    records = checkpoints if collection == "checkpoints" else segments
    records[1]["candidate_id"] = records[0]["candidate_id"]
    result = _continuity(checkpoints, segments)
    key = "duplicate_checkpoint_ids" if collection == "checkpoints" else "duplicate_segment_ids"

    assert result["status"] == "invalid"
    assert result["is_single_chain"] is False
    assert result[key] == [records[0]["candidate_id"]]
    assert key in result["reason_codes"]


@pytest.mark.parametrize("value", [None, "", "   ", 0, False, [], {}, " padded "])
@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("checkpoints", "candidate_id"),
        ("segments", "candidate_id"),
        ("segments", "from_candidate_id"),
        ("segments", "to_candidate_id"),
    ],
)
def test_malformed_identifiers_are_unknown_not_a_valid_graph(collection, field, value) -> None:
    checkpoints, segments = _checkpoints(), _segments()
    records = checkpoints if collection == "checkpoints" else segments
    records[0][field] = value
    result = _continuity(checkpoints, segments)

    assert result["status"] == "unknown"
    assert result["is_single_chain"] is None
    assert result["has_cycle"] is None
    assert "malformed_records" in result["reason_codes"]
    assert {"collection": collection, "index": 0, "field": field} in result["malformed_records"]


@pytest.mark.parametrize("collection", ["checkpoints", "segments"])
@pytest.mark.parametrize("value", [None, "broken", 19, []])
def test_non_object_rows_are_not_silently_filtered(collection, value) -> None:
    checkpoints, segments = _checkpoints(), _segments()
    records = checkpoints if collection == "checkpoints" else segments
    records[0] = value
    result = _continuity(checkpoints, segments)

    assert result["status"] == "unknown"
    assert result["is_single_chain"] is None
    assert {"collection": collection, "index": 0, "field": "$record"} in result["malformed_records"]


@pytest.mark.parametrize(
    ("checkpoints", "segments"),
    [(None, []), ({}, []), ("bad", []), ([], None), ([], {})],
)
def test_missing_or_malformed_collections_are_unknown(checkpoints, segments) -> None:
    result = workspace_tools._checkpoint_chain_continuity(checkpoints, segments)

    assert result["status"] == "unknown"
    assert result["is_single_chain"] is None
    assert "malformed_collections" in result["reason_codes"]


@pytest.mark.parametrize(
    ("checkpoints", "segments", "status", "continuous", "reason"),
    [
        ([], [], "unknown", None, "no_checkpoint_records"),
        ([], _segments(), "unknown", None, "no_checkpoint_records"),
        ([{}], [], "unknown", None, "malformed_records"),
        (_checkpoints(["station.only"]), [], "valid", True, None),
        (_checkpoints(), [], "invalid", False, "disconnected"),
        (_checkpoints(), _segments()[:2], "invalid", False, "disconnected"),
        (_checkpoints(["station.only"]), _segments([("station.only", "station.only")]), "invalid", False, "cycle"),
    ],
)
def test_empty_singleton_and_missing_links_have_explicit_semantics(
    checkpoints, segments, status, continuous, reason,
) -> None:
    result = _continuity(checkpoints, segments)

    assert result["status"] == status
    assert result["is_single_chain"] is continuous
    assert result["physical_gpx_geometry_continuity"] is None
    if reason:
        assert reason in result["reason_codes"]
    if status == "valid":
        assert result["checkpoint_order"] == ["station.only"]
        assert result["segment_order"] == []
        assert result["start_checkpoint_id"] == result["end_checkpoint_id"] == "station.only"


def test_pure_helper_preserves_records_and_cannot_prove_physical_geometry() -> None:
    checkpoints, segments = _checkpoints(), _segments()
    checkpoints[0].update({"lat": 15.0, "lon": 20.0})
    checkpoints[1].update({"lat": -65.0, "lon": 110.0})
    segments[0]["display_geometry"] = None
    original = copy.deepcopy((checkpoints, segments))
    result = workspace_tools._checkpoint_chain_continuity(checkpoints, segments)

    assert (checkpoints, segments) == original
    assert result["is_single_chain"] is True
    assert result["physical_gpx_geometry_continuity"] is None
    assert result["source_completeness"] == "not_assessed"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("disconnected", [False, True])
def test_actual_route_tool_exposes_identifier_result_and_keeps_boundaries(
    tmp_path: Path, disconnected: bool,
) -> None:
    segments = _segments()
    if disconnected:
        segments = _segments([(IDS[0], IDS[1]), (IDS[1], IDS[0]), (IDS[2], IDS[3])])
    files = {
        "project.json": {
            "project_id": "synthetic_chain_check",
            "checkpoint_candidates_ref": "checkpoints.json",
            "segment_candidates_ref": "segments.json",
        },
        "checkpoints.json": _checkpoints(),
        "segments.json": list(reversed(segments)),
    }
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    before = {name: (tmp_path / name).read_bytes() for name in files}

    result = workspace_tools.search_project_route_structure(tmp_path, query="", limit=2)
    summary = result["summaries"]

    assert summary["segment_count_matches_checkpoint_chain"] is True
    assert summary["segment_count_matches_checkpoint_chain_basis"] == "count_only"
    assert summary["checkpoint_chain_continuity"]["is_single_chain"] is (not disconnected)
    assert summary["checkpoint_chain_continuity"]["physical_gpx_geometry_continuity"] is None
    assert result["boundary"] == {
        "read_only": True,
        "offline_only": True,
        "local_evidence_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
    }
    assert before == {name: (tmp_path / name).read_bytes() for name in files}


def test_actual_route_tool_without_checkpoint_sources_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    result = workspace_tools.search_project_route_structure(tmp_path)

    assert result["summaries"]["segment_count_matches_checkpoint_chain"] is True
    assert result["summaries"]["checkpoint_chain_continuity"]["status"] == "unknown"
