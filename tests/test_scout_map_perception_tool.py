import json
from pathlib import Path

from scout_map_perception_tool import (
    MAP_PERCEPTION_TOOL_ID,
    search_project_map_perception,
)


def test_search_project_map_perception_returns_ocr_label_with_named_point_context(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="雲海保線所 OCR annotation",
        limit=3,
    )

    assert result["tool_id"] == MAP_PERCEPTION_TOOL_ID
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["result_count"] >= 1
    top = result["results"][0]
    assert top["evidence_type"] == "ocr_label"
    assert top["label_text"] == "雲海保線所"
    assert top["named_point_id"] == "np.yunhai_station"
    assert top["lat"] == 24.001
    assert top["lon"] == 121.001
    assert top["full_source_image_embedded"] is False
    assert top["runtime_safety_truth"] is False


def test_search_project_map_perception_filters_contour_candidate_by_cp_ref(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="CP003 等高線 annotation",
        limit=3,
    )

    assert result["filters"]["cp"] == "cp.003"
    assert result["result_count"] == 1
    top = result["results"][0]
    assert top["evidence_type"] == "contour_interpretation"
    assert top["candidate_id"] == "contour.fixture.seg_001_003"
    assert "cp.003" in top["checkpoint_refs"]
    assert top["not_observed_fact"] is True
    assert top["review_required"] is True


def test_search_project_map_perception_exposes_layer_materials_without_vision_claims(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="森林 forest 圖層 material",
        limit=5,
    )

    assert result["result_count"] >= 1
    layer_ids = {item.get("layer_id") for item in result["results"]}
    assert "forest" in layer_ids
    forest = next(item for item in result["results"] if item.get("layer_id") == "forest")
    assert forest["evidence_type"] == "map_layer_material"
    assert forest["runtime_safety_truth"] is False
    assert forest["candidate_only"] is True


def test_search_project_map_perception_cp_nearby_annotation_uses_named_point_distance(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="CP001 附近有沒有標註",
        limit=3,
    )

    assert result["filters"]["cp"] == "cp.001"
    assert result["result_count"] >= 1
    top = result["results"][0]
    assert top["evidence_type"] == "ocr_label"
    assert top["anchor_distance_m"] <= 500
    assert top["label_text"] == "雲海保線所"


def _write_map_perception_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "map-perception-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "mcp").mkdir(parents=True)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)
    (workspace / "normalized" / "map").mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps(
            {
                "project_id": "map_perception_fixture",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "map_context_ref": "normalized/map/map_context.geojson",
                "mcp_ocr_labels_ref": "outputs/mcp/mcp_ocr_labels.json",
                "mcp_named_point_evidence_ref": "outputs/mcp/named_point_evidence.json",
                "contour_interpretation_candidates_ref": (
                    "outputs/contour_interpretation_candidates.json"
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {"candidate_id": "cp.001", "label": "CP 001", "lat": 24.001, "lon": 121.001},
                {"candidate_id": "cp.003", "label": "CP 003", "lat": 24.003, "lon": 121.003},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "mcp" / "mcp_ocr_labels.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_mcp_ocr_label_set",
                "candidate_only": True,
                "full_source_image_embedded": False,
                "runtime_safety_truth": False,
                "labels": [
                    {
                        "ocr_label_id": "ocr.yunhai_station.001",
                        "label_text": "雲海保線所",
                        "bbox": [120, 310, 184, 338],
                        "confidence": 0.87,
                        "named_point_id": "np.yunhai_station",
                        "source_ref": "local_map_tile.z15.x26142.y13991",
                        "source_image_hash": "sha256:fixture",
                        "review_required": True,
                        "candidate_only": True,
                        "full_source_image_embedded": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "mcp" / "named_point_evidence.json").write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_named_point_evidence_set",
                "named_points": [
                    {
                        "named_point_id": "np.yunhai_station",
                        "canonical_name": "雲海保線所",
                        "aliases": ["保線所"],
                        "point_class": ["camp_hut_structure"],
                        "route_position": {
                            "lat": 24.001,
                            "lon": 121.001,
                            "distance_m": 1000.0,
                            "coordinate_confidence": "medium",
                        },
                        "boundary": {
                            "candidate_only": True,
                            "phase1_runtime_safety_truth": False,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "contour_interpretation_candidates.json").write_text(
        json.dumps(
            {
                "artifact_id": "contour.fixture.v0",
                "candidates": [
                    {
                        "candidate_id": "contour.fixture.seg_001_003",
                        "status": "candidate",
                        "interpretation_mode": "ai_assisted",
                        "candidate_origin": "ai_assisted_model",
                        "confidence": "unknown",
                        "contour_density_notes": ["Potential close contour spacing near CP003."],
                        "terrain_shape_notes": ["Review image-map against DTM before use."],
                        "notes": "candidate-only interpretation prompt",
                        "human_review_required": True,
                        "not_observed_fact": True,
                        "source_artifact_refs": {
                            "image_artifact_ref": "artifact.photo.fixture",
                            "dtm_coverage_summary_ref": "dtm.fixture",
                        },
                        "target_refs": {
                            "route_artifact_ref": "artifact.gpx.fixture",
                            "checkpoint_candidate_refs": ["cp.001", "cp.003"],
                            "segment_candidate_refs": ["seg.001", "seg.002", "seg.003"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "normalized" / "map" / "map_context.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return workspace
