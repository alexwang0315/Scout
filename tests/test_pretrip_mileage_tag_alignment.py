import json
from pathlib import Path

from pretrip_mileage_tag_alignment import (
    MILEAGE_TAG_ALIGNMENT_GEOJSON_REF,
    MILEAGE_TAG_ALIGNMENT_REF,
    align_pretrip_workspace_mileage_tags,
)


def test_aligns_workspace_mileage_tags_across_core_artifacts(tmp_path: Path):
    project_root = tmp_path / "demo_route"
    (project_root / "candidates").mkdir(parents=True)
    (project_root / "outputs" / "mcp").mkdir(parents=True)

    _write_json(
        project_root / "project.json",
        {
            "project_id": "demo_route",
            "route_summary_ref": "route_summary.json",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "route_note_candidates_ref": "candidates/route_note_candidates.json",
            "route_context_points_ref": "candidates/route_context_points.json",
            "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
            "risk_ribbon_ref": "outputs/risk_ribbon.geojson",
            "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
            "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
        },
    )
    _write_json(
        project_root / "route_summary.json",
        {"route_name": "Demo", "distance_m": 1000.0},
    )
    _write_json(
        project_root / "candidates" / "checkpoints.json",
        [
            _candidate("cp.start", "Start", 24.0, 121.0),
            _candidate("cp.001", "Mid CP", 24.0, 121.005),
            _candidate("cp.end", "End", 24.0, 121.01),
        ],
    )
    _write_json(
        project_root / "candidates" / "segments.json",
        [
            {
                "candidate_id": "seg.001",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.001",
                "distance_m": 500.0,
                "label": "Segment 001",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "candidate_id": "seg.002",
                "from_candidate_id": "cp.001",
                "to_candidate_id": "cp.end",
                "distance_m": 500.0,
                "label": "Segment 002",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ],
    )
    _write_json(
        project_root / "outputs" / "segment_display_geometry.json",
        {
            "segments": [
                {
                    "segment_candidate_id": "seg.001",
                    "coordinates": [
                        {"lat": 24.0, "lon": 121.0},
                        {"lat": 24.0, "lon": 121.005},
                    ],
                },
                {
                    "segment_candidate_id": "seg.002",
                    "coordinates": [
                        {"lat": 24.0, "lon": 121.005},
                        {"lat": 24.0, "lon": 121.01},
                    ],
                },
            ]
        },
    )
    _write_json(
        project_root / "outputs" / "risk_ribbon.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                _line_feature("risk.001", 0.0, 500.0, 121.0, 121.005),
                _line_feature("risk.002", 500.0, 1000.0, 121.005, 121.01),
            ],
        },
    )
    _write_json(
        project_root / "candidates" / "route_mileage_k_anchors.json",
        {
            "anchors": [
                {
                    "candidate_id": "anchor.0k",
                    "display_label": "0K",
                    "mileage_m": 0.0,
                    "lat": 24.0,
                    "lon": 121.0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "candidate_id": "anchor.1k",
                    "display_label": "1K",
                    "mileage_m": 1000.0,
                    "lat": 24.0,
                    "lon": 121.01,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ]
        },
    )
    _write_json(
        project_root / "outputs" / "mcp" / "mcp_candidates.json",
        {
            "mcp_candidates": [
                {
                    "mcp_id": "mcp.demo.001",
                    "label": "Demo Boss Seed",
                    "lat": 24.0,
                    "lon": 121.005,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ],
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
    )
    _write_json(
        project_root / "candidates" / "route_context_points.json",
        {
            "points": [
                {
                    "candidate_id": "route_context.demo.001",
                    "display_label": "Context Point",
                    "lat": 24.0,
                    "lon": 121.004,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ]
        },
    )
    _write_json(
        project_root / "candidates" / "route_note_candidates.json",
        {
            "candidates": [
                {
                    "candidate_id": "route_note.demo.001",
                    "name": "0.5K",
                    "note_category": "uncategorized_note",
                    "lat": 24.0,
                    "lon": 121.005,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "candidate_id": "route_note.demo.ignored",
                    "name": "timestamp only",
                    "note_category": "uncategorized_note",
                    "lat": 24.0,
                    "lon": 121.006,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ]
        },
    )

    result = align_pretrip_workspace_mileage_tags(
        project_root,
        generated_at="2099-01-01T00:00:00Z",
    )

    assert result["artifact_kind"] == "pretrip_workspace_mileage_tag_alignment"
    assert result["status"] == "completed"
    assert result["counts"]["usable_anchor_count"] == 2
    assert result["counts"]["runtime_safety_truth_count"] == 0
    assert result["raw_source_summary"]["route_note_candidate_count"] == 2
    assert result["raw_source_summary"]["route_note_mileage_tag_candidate_count"] == 1
    assert result["boundary"]["runtime_safety_truth"] is False
    source_kinds = result["counts"]["source_kind_counts"]
    assert source_kinds["checkpoint"] == 3
    assert source_kinds["segment"] == 2
    assert source_kinds["mcp_candidate"] == 1
    assert source_kinds["route_context_point"] == 1
    assert source_kinds["route_note_candidate"] == 1
    assert source_kinds["risk_ribbon_segment"] == 2
    mcp_tag = next(
        tag
        for tag in result["mileage_tags"]
        if tag["source_id"] == "mcp.demo.001"
    )
    assert mcp_tag["display_mileage"]["label"] == "0.5K"

    project = _load_json(project_root / "project.json")
    assert project["mileage_tag_alignment_ref"] == MILEAGE_TAG_ALIGNMENT_REF
    assert project["mileage_tag_alignment_geojson_ref"] == MILEAGE_TAG_ALIGNMENT_GEOJSON_REF
    assert (project_root / MILEAGE_TAG_ALIGNMENT_REF).is_file()
    geojson = _load_json(project_root / MILEAGE_TAG_ALIGNMENT_GEOJSON_REF)
    assert geojson["metadata"]["runtime_safety_truth"] is False
    assert geojson["metadata"]["feature_count"] == result["counts"]["tag_count"]


def _candidate(candidate_id: str, label: str, lat: float, lon: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "label": label,
        "lat": lat,
        "lon": lon,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _line_feature(
    segment_id: str,
    start_m: float,
    end_m: float,
    start_lon: float,
    end_lon: float,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[start_lon, 24.0], [end_lon, 24.0]],
        },
        "properties": {
            "segment_id": segment_id,
            "start_distance_m": start_m,
            "end_distance_m": end_m,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
