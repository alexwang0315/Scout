from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scout.schemas.workspace_query import (
    WorkspaceQueryLimits,
    parse_workspace_query_request,
)
from scout.services.workspace_query import WorkspaceQueryService
from scout_workspace_query_tool import workspace_query_request_json_schema


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    outputs = root / "outputs"
    outputs.mkdir(parents=True)
    project = {
        "project_id": "query-fixture",
        "checkpoint_candidates_ref": "outputs/checkpoints.json",
        "segment_candidates_ref": "outputs/segments.json",
        "calibrated_risk_heatmap_ref": "outputs/risk.geojson",
        "cwa_warning_layer_ref": "outputs/warnings.geojson",
        "human_reviews_ref": "outputs/reviews.json",
        "route_geometry_ref": "outputs/route.geojson",
        "water_points_ref": "outputs/water.json",
        "before_ref": "outputs/before.json",
        "after_ref": "outputs/after.json",
    }
    (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (outputs / "checkpoints.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": "cp.start",
                        "lat": 23.0000,
                        "lon": 121.0000,
                        "route_distance_m": 0.0,
                        "nullable_note": None,
                    },
                    {
                        "candidate_id": "cp.001",
                        "lat": 23.0000,
                        "lon": 121.0100,
                        "route_distance_m": 1024.0,
                    },
                    {
                        "candidate_id": "cp.finish",
                        "lat": 23.0000,
                        "lon": 121.0200,
                        "route_distance_m": 2048.0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "segments.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "candidate_id": "seg.001",
                        "from_candidate_id": "cp.start",
                        "to_candidate_id": "cp.001",
                        "distance_m": 1024.0,
                        "route_distance_start_m": 0.0,
                        "route_distance_end_m": 1024.0,
                    },
                    {
                        "candidate_id": "seg.002",
                        "from_candidate_id": "cp.001",
                        "to_candidate_id": "cp.finish",
                        "distance_m": 2008.6282038658276,
                        "route_distance_start_m": 1024.0,
                        "route_distance_end_m": 3032.6282038658276,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "risk.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.0102, 23.0]},
                        "properties": {
                            "candidate_id": "risk.001",
                            "score": 99.58,
                            "baseline_score": 79.7,
                            "risk_bucket": "extreme",
                            "route_distance_m": 1040.0,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.018, 23.0]},
                        "properties": {
                            "candidate_id": "risk.002",
                            "score": 78.0,
                            "baseline_score": 77.0,
                            "risk_bucket": "high",
                            "route_distance_m": 1840.0,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [121.005, 23.0]},
                        "properties": {
                            "candidate_id": "risk.003",
                            "score": 42.0,
                            "baseline_score": 40.0,
                            "risk_bucket": "moderate",
                            "route_distance_m": 510.0,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (outputs / "warnings.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    (outputs / "reviews.json").write_text(
        json.dumps({"reviews": []}), encoding="utf-8"
    )
    (outputs / "route.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [121.0000, 23.0000],
                                [121.0100, 23.0000],
                                [121.0200, 23.0000],
                            ],
                        },
                        "properties": {"route_id": "route.primary"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (outputs / "water.json").write_text(
        json.dumps(
            {
                "points": [
                    {
                        "candidate_id": "water.001",
                        "label": "First water",
                        "lat": 23.0,
                        "lon": 121.012,
                        "route_distance_m": 1228.0,
                        "confidence": "high",
                        "review_state": "candidate",
                        "stale_risk": "fresh",
                    },
                    {
                        "candidate_id": "water.002",
                        "label": "Second water",
                        "lat": 23.0,
                        "lon": 121.019,
                        "route_distance_m": 1945.0,
                        "confidence": "medium",
                        "review_state": "candidate",
                        "stale_risk": "unknown",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "before.json").write_text(
        json.dumps({"status": "draft", "count": 2}), encoding="utf-8"
    )
    (outputs / "after.json").write_text(
        json.dumps({"status": "reviewed", "count": 3}), encoding="utf-8"
    )
    return root


def _execute(workspace: Path, request: dict[str, object]):
    return WorkspaceQueryService(workspace).execute(request)


def test_request_contract_is_discriminated_and_rejects_unbounded_field_syntax() -> None:
    request = parse_workspace_query_request(
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        }
    )

    assert request.operation == "count"
    with pytest.raises(ValidationError):
        parse_workspace_query_request(
            {
                "operation": "argmax",
                "artifact": {"source_ref": "outputs/segments.json"},
                "field": "segments[?(@.distance_m)].distance_m",
            }
        )

    assert WorkspaceQueryLimits().max_artifact_bytes == 64 * 1024 * 1024
    with pytest.raises(ValidationError):
        WorkspaceQueryLimits(max_artifact_bytes=64 * 1024 * 1024 + 1)


def test_request_json_schema_exposes_operation_discriminator_and_variants() -> None:
    schema = workspace_query_request_json_schema()

    assert schema["discriminator"]["propertyName"] == "operation"
    assert len(schema["oneOf"]) == 13
    operation_values = {
        definition["properties"]["operation"]["const"]
        for definition in schema["$defs"].values()
        if "operation" in definition.get("properties", {})
    }
    assert operation_values == {
        "inspect",
        "exists",
        "count",
        "distinct",
        "filter",
        "group_by",
        "top_k",
        "argmax",
        "diff",
        "freshness",
        "nearest",
        "interval",
        "route_forward",
    }


def test_requested_fields_distinguish_explicit_null_from_missing(
    workspace: Path,
) -> None:
    inspected = _execute(
        workspace,
        {
            "operation": "inspect",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "fields": ["candidate_id", "nullable_note", "not_present"],
        },
    )
    filtered = _execute(
        workspace,
        {
            "operation": "filter",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "fields": ["candidate_id", "not_present"],
        },
    )

    assert inspected.status == "warning"
    assert inspected.answerability == "missing_required_fields"
    assert inspected.missing_fields == ["not_present"]
    assert inspected.results[0].data["sample_record"]["nullable_note"] is None
    assert filtered.status == "warning"
    assert filtered.answerability == "missing_required_fields"
    assert filtered.missing_fields == ["not_present"]
    assert filtered.results[0].data == {"candidate_id": "cp.start"}


def test_count_and_argmax_return_record_level_grounding(workspace: Path) -> None:
    count = _execute(
        workspace,
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        },
    )
    longest = _execute(
        workspace,
        {
            "operation": "argmax",
            "artifact": {"project_ref_key": "segment_candidates_ref"},
            "field": "distance_m",
            "fields": [
                "candidate_id",
                "from_candidate_id",
                "to_candidate_id",
                "distance_m",
            ],
        },
    )

    assert count.status == "success"
    assert count.answerability == "complete"
    assert count.result_count == 3
    assert count.summary == "count=3"
    assert count.source_refs == ["outputs/checkpoints.json"]
    assert count.results[0].data["first_record_id"] == "cp.start"
    assert count.results[0].data["last_record_id"] == "cp.finish"
    assert longest.results[0].record_id == "seg.002"
    assert longest.results[0].data["distance_m"] == pytest.approx(2008.6282)
    assert longest.results[0].evidence_id.startswith("ev_")
    assert longest.results[0].source_hash.startswith("sha256:")
    assert longest.results[0].locator == "/segments/1"
    assert longest.candidate_only is True
    assert longest.runtime_safety_truth is False


def test_argmax_supports_a_bounded_numeric_difference(workspace: Path) -> None:
    delta = _execute(
        workspace,
        {
            "operation": "argmax",
            "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
            "field": "properties.score",
            "subtract_field": "properties.baseline_score",
            "fields": [
                "properties.candidate_id",
                "properties.score",
                "properties.baseline_score",
            ],
        },
    )

    assert delta.results[0].record_id == "risk.001"
    assert delta.results[0].data["numeric_difference"] == pytest.approx(19.88)
    assert delta.results[0].data["numeric_difference_fields"] == [
        "properties.score",
        "properties.baseline_score",
    ]


def test_argmax_preserves_zero_numeric_difference(workspace: Path) -> None:
    zero_delta_path = workspace / "outputs" / "zero-delta.json"
    zero_delta_path.write_text(
        json.dumps(
            {
                "records": [
                    {"id": "same.001", "score": 5.0, "baseline": 5.0},
                    {"id": "same.002", "score": 3.0, "baseline": 3.0},
                ]
            }
        ),
        encoding="utf-8",
    )

    delta = _execute(
        workspace,
        {
            "operation": "argmax",
            "artifact": {
                "source_ref": "outputs/zero-delta.json",
                "collection_path": "records",
            },
            "field": "score",
            "subtract_field": "baseline",
            "fields": ["id", "score", "baseline"],
        },
    )

    assert delta.answerability == "complete"
    assert delta.results[0].record_id == "same.001"
    assert delta.results[0].data["numeric_difference"] == 0.0


@pytest.mark.parametrize(
    ("query_case", "expected"),
    [
        (
            {
                "operation": "distinct",
                "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
                "field": "properties.risk_bucket",
            },
            ["extreme", "high", "moderate"],
        ),
        (
            {
                "operation": "filter",
                "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
                "predicates": [
                    {"field": "properties.score", "operator": "gte", "value": 78}
                ],
                "fields": ["properties.candidate_id", "properties.score"],
                "limit": 5,
            },
            ["risk.001", "risk.002"],
        ),
        (
            {
                "operation": "group_by",
                "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
                "field": "properties.risk_bucket",
            },
            {"extreme": 1, "high": 1, "moderate": 1},
        ),
        (
            {
                "operation": "top_k",
                "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
                "field": "properties.score",
                "fields": ["properties.candidate_id", "properties.score"],
                "k": 2,
            },
            ["risk.001", "risk.002"],
        ),
    ],
)
def test_collection_operations_are_deterministic(
    workspace: Path,
    query_case: dict[str, object],
    expected: object,
) -> None:
    first = _execute(workspace, query_case)
    second = _execute(workspace, query_case)

    assert first.status == "success"
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [item.evidence_id for item in first.results] == [
        item.evidence_id for item in second.results
    ]
    if query_case["operation"] == "distinct":
        assert first.results[0].data["values"] == expected
    elif query_case["operation"] == "group_by":
        assert {item.data["group"]: item.data["count"] for item in first.results} == expected
    else:
        assert [item.record_id for item in first.results] == expected


def test_empty_collections_are_answerable_zero_not_missing(workspace: Path) -> None:
    warnings = _execute(
        workspace,
        {
            "operation": "count",
            "artifact": {"project_ref_key": "cwa_warning_layer_ref"},
        },
    )
    reviews = _execute(
        workspace,
        {
            "operation": "count",
            "artifact": {"project_ref_key": "human_reviews_ref"},
        },
    )

    assert warnings.answerability == "complete"
    assert warnings.result_count == 0
    assert reviews.answerability == "complete"
    assert reviews.result_count == 0

    no_match = _execute(
        workspace,
        {
            "operation": "filter",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "predicates": [
                {"field": "candidate_id", "operator": "eq", "value": "missing"}
            ],
        },
    )
    assert no_match.result_count == 0
    assert no_match.results[0].record_id == "empty"
    assert no_match.results[0].data == {
        "result_count": 0,
        "reason": "no_matching_records",
    }
    assert no_match.results[0].evidence_id.startswith("ev_")

    empty_groups = _execute(
        workspace,
        {
            "operation": "group_by",
            "artifact": {"project_ref_key": "human_reviews_ref"},
            "field": "status",
        },
    )
    assert empty_groups.result_count == 0
    assert empty_groups.results[0].record_id == "empty"


def test_inspect_exists_diff_and_freshness(workspace: Path) -> None:
    inspected = _execute(
        workspace,
        {
            "operation": "inspect",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "fields": ["candidate_id", "route_distance_m"],
        },
    )
    exists = _execute(
        workspace,
        {
            "operation": "exists",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "predicates": [
                {"field": "candidate_id", "operator": "eq", "value": "cp.finish"}
            ],
        },
    )
    diff = _execute(
        workspace,
        {
            "operation": "diff",
            "left_artifact": {"project_ref_key": "before_ref"},
            "right_artifact": {"project_ref_key": "after_ref"},
        },
    )
    freshness = _execute(
        workspace,
        {
            "operation": "freshness",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "now": "2030-07-14T00:00:00Z",
            "stale_after_seconds": 1,
        },
    )
    aggregate_diff = _execute(
        workspace,
        {
            "operation": "diff",
            "left_artifact": {"project_ref_key": "before_ref"},
            "right_artifact": {"project_ref_key": "after_ref"},
            "aggregation": "max",
            "left_field": "count",
            "right_field": "count",
        },
    )
    project_fields = _execute(
        workspace,
        {
            "operation": "inspect",
            "artifact": {"source_ref": "project.json"},
            "fields": ["project_id", "checkpoint_candidates_ref"],
        },
    )

    assert "candidates" in inspected.results[0].data["top_level_keys"]
    assert inspected.results[0].data["sample_record"] == {
        "candidate_id": "cp.start",
        "route_distance_m": 0.0,
    }
    assert project_fields.results[0].data["selected_fields"] == {
        "checkpoint_candidates_ref": "outputs/checkpoints.json",
        "project_id": "query-fixture",
    }
    assert project_fields.results[0].data["top_level_keys"] == [
        "checkpoint_candidates_ref",
        "project_id",
    ]
    assert list(project_fields.results[0].data).index("selected_fields") < list(
        project_fields.results[0].data
    ).index("top_level_keys")
    assert exists.results[0].data == {"exists": True, "matching_count": 1}
    assert diff.results[0].data["equal"] is False
    assert "/count" in diff.results[0].data["changed_paths"]
    assert "/status" in diff.results[0].data["changed_paths"]
    assert freshness.freshness["stale"] is True
    assert freshness.status == "warning"
    assert freshness.answerability == "stale"
    assert aggregate_diff.results[0].data["left_value"] == 2
    assert aggregate_diff.results[0].data["right_value"] == 3
    assert aggregate_diff.results[0].data["numeric_difference"] == 1


def test_nearest_interval_and_route_forward(workspace: Path) -> None:
    nearest = _execute(
        workspace,
        {
            "operation": "nearest",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "origin": {"lat": 23.0, "lon": 121.0102},
            "lat_field": "lat",
            "lon_field": "lon",
            "fields": ["candidate_id", "lat", "lon"],
            "k": 1,
        },
    )
    interval = _execute(
        workspace,
        {
            "operation": "interval",
            "artifact": {"project_ref_key": "calibrated_risk_heatmap_ref"},
            "value_field": "properties.route_distance_m",
            "start": 500,
            "end": 1100,
            "fields": ["properties.candidate_id", "properties.route_distance_m"],
        },
    )
    missing_live = _execute(
        workspace,
        {
            "operation": "route_forward",
            "artifact": {"project_ref_key": "water_points_ref"},
            "route_artifact": {"project_ref_key": "route_geometry_ref"},
            "route_distance_field": "route_distance_m",
        },
    )
    forward = _execute(
        workspace,
        {
            "operation": "route_forward",
            "artifact": {"project_ref_key": "water_points_ref"},
            "route_artifact": {"project_ref_key": "route_geometry_ref"},
            "route_distance_field": "route_distance_m",
            "current_route_distance_m": 900,
            "fields": ["candidate_id", "label", "route_distance_m"],
            "limit": 1,
        },
    )
    containing_interval = _execute(
        workspace,
        {
            "operation": "interval",
            "artifact": {"project_ref_key": "segment_candidates_ref"},
            "start_field": "route_distance_start_m",
            "end_field": "route_distance_end_m",
            "value": 1500,
            "fields": [
                "candidate_id",
                "from_candidate_id",
                "to_candidate_id",
                "route_distance_start_m",
                "route_distance_end_m",
            ],
        },
    )
    cumulative_interval = _execute(
        workspace,
        {
            "operation": "interval",
            "artifact": {"project_ref_key": "segment_candidates_ref"},
            "cumulative_field": "distance_m",
            "value": 1500,
            "fields": ["candidate_id", "from_candidate_id", "to_candidate_id"],
        },
    )
    projected_forward = _execute(
        workspace,
        {
            "operation": "route_forward",
            "artifact": {"project_ref_key": "water_points_ref"},
            "route_artifact": {"project_ref_key": "route_geometry_ref"},
            "route_distance_field": "route_distance_m",
            "current_position": {"lat": 23.0, "lon": 121.009},
            "fields": ["candidate_id", "label", "route_distance_m"],
            "limit": 1,
        },
    )

    assert nearest.results[0].record_id == "cp.001"
    assert nearest.results[0].data["distance_m"] < 30
    assert [item.record_id for item in interval.results] == ["risk.003", "risk.001"]
    assert missing_live.status == "warning"
    assert missing_live.answerability == "requires_live_state"
    assert missing_live.root_cause == "current_route_position_missing"
    assert missing_live.safe_retry is False
    assert forward.results[0].record_id == "water.001"
    assert forward.results[0].data["forward_distance_m"] == pytest.approx(328.0)
    assert containing_interval.results[0].record_id == "seg.002"
    assert cumulative_interval.results[0].record_id == "seg.002"
    assert cumulative_interval.results[0].data["computed_interval_start"] == 1024
    assert cumulative_interval.results[0].data["computed_interval_end"] == pytest.approx(
        3032.6282038658276
    )
    assert projected_forward.results[0].record_id == "water.001"
    assert projected_forward.results[0].data["straight_line_distance_m"] > 0
    assert projected_forward.results[0].data["off_route_distance_m"] < 1
    assert projected_forward.results[0].data["current_off_route_distance_m"] < 1
    assert projected_forward.results[0].data["confidence"] == "high"
    assert projected_forward.results[0].data["review_state"] == "candidate"
    assert projected_forward.results[0].data["stale_risk"] == "fresh"


def test_nearest_reports_missing_coordinate_fields_instead_of_empty_match(
    workspace: Path,
) -> None:
    response = _execute(
        workspace,
        {
            "operation": "nearest",
            "artifact": {"project_ref_key": "before_ref"},
            "origin": {"lat": 23.0, "lon": 121.0},
            "lat_field": "lat",
            "lon_field": "lon",
            "fields": ["status"],
        },
    )

    assert response.status == "warning"
    assert response.answerability == "missing_required_fields"
    assert response.root_cause == "coordinate_fields_missing"
    assert response.missing_fields == ["lat", "lon"]
    assert response.result_count == 0


def test_workspace_boundaries_reject_traversal_symlink_extensions_and_size(
    workspace: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    (workspace / "outputs" / "escape.json").symlink_to(outside)
    (workspace / "outputs" / "not-json.txt").write_text("[]", encoding="utf-8")
    (workspace / "outputs" / "large.json").write_text("[" + "0," * 100 + "0]", encoding="utf-8")

    traversal = _execute(
        workspace,
        {"operation": "count", "artifact": {"source_ref": "../outside.json"}},
    )
    symlink = _execute(
        workspace,
        {"operation": "count", "artifact": {"source_ref": "outputs/escape.json"}},
    )
    extension = _execute(
        workspace,
        {"operation": "count", "artifact": {"source_ref": "outputs/not-json.txt"}},
    )
    size = WorkspaceQueryService(
        workspace,
        limits=WorkspaceQueryLimits(max_artifact_bytes=32),
    ).execute(
        {"operation": "count", "artifact": {"source_ref": "outputs/large.json"}}
    )

    assert traversal.root_cause == "workspace_path_rejected"
    assert symlink.root_cause == "workspace_path_rejected"
    assert extension.root_cause == "artifact_extension_rejected"
    assert size.root_cause == "artifact_size_limit_exceeded"
    for result in (traversal, symlink, extension, size):
        assert result.status == "error"
        assert result.source_refs == []
        assert str(tmp_path) not in result.model_dump_json()


def test_project_manifest_obeys_artifact_size_and_json_bounds(workspace: Path) -> None:
    manifest_path = workspace / "project.json"
    manifest_path.write_text(
        json.dumps(
            {
                "checkpoint_candidates_ref": "outputs/checkpoints.json",
                "oversized": "x" * 256,
            }
        ),
        encoding="utf-8",
    )

    oversized = WorkspaceQueryService(
        workspace,
        limits=WorkspaceQueryLimits(max_artifact_bytes=64),
    ).execute(
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        }
    )

    assert oversized.status == "error"
    assert oversized.root_cause == "project_manifest_size_limit_exceeded"

    manifest_path.write_text(
        json.dumps(
            {
                "checkpoint_candidates_ref": "outputs/checkpoints.json",
                "nested": {"level": {"too": {"deep": True}}},
            }
        ),
        encoding="utf-8",
    )
    too_deep = WorkspaceQueryService(
        workspace,
        limits=WorkspaceQueryLimits(max_json_depth=2),
    ).execute(
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        }
    )

    assert too_deep.status == "error"
    assert too_deep.root_cause == "json_depth_limit_exceeded"


def test_scan_and_return_limits_fail_closed_or_truncate_explicitly(workspace: Path) -> None:
    scan_limited = WorkspaceQueryService(
        workspace,
        limits=WorkspaceQueryLimits(max_scanned_records=2),
    ).execute(
        {
            "operation": "count",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
        }
    )
    return_limited = WorkspaceQueryService(
        workspace,
        limits=WorkspaceQueryLimits(max_returned_records=1),
    ).execute(
        {
            "operation": "filter",
            "artifact": {"project_ref_key": "checkpoint_candidates_ref"},
            "limit": 10,
        }
    )

    assert scan_limited.status == "error"
    assert scan_limited.root_cause == "scan_limit_exceeded"
    assert return_limited.status == "warning"
    assert return_limited.answerability == "partial"
    assert return_limited.result_count == 1
    assert "return_limit_applied" in return_limited.limitations
