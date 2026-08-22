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


def test_search_project_map_perception_does_not_treat_confidence_as_query_match(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="這個谷地有沒有自然出口，還是三面封閉？",
        limit=3,
    )

    assert result["answerability"] == "map_perception_no_matching_material"
    assert result["result_count"] == 0
    assert result["missing_fields"] == ["matching_map_perception_results"]


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


def test_search_project_map_perception_reads_raster_label_evidence_geojson(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    result = search_project_map_perception(
        workspace,
        query="924m OCR raster label",
        limit=5,
    )

    assert result["answerability"] == "map_perception_evidence_available"
    labels = {item.get("label_text") for item in result["results"]}
    assert "924m" in labels
    raster_label = next(item for item in result["results"] if item.get("label_text") == "924m")
    assert raster_label["source_path"] == "outputs/layers/normalized/raster_label_evidence.geojson"
    assert raster_label["label_role"] == "named_place_label"
    assert raster_label["lat"] == 23.5759308
    assert raster_label["lon"] == 121.54724121
    assert raster_label["candidate_only"] is True
    assert raster_label["runtime_safety_truth"] is False


def test_map_perception_answers_mileage_anchor_inventory_and_maximum(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    inventory = search_project_map_perception(
        workspace,
        query="route mileage K anchors 目前辨識出哪些 K 標記？",
    )
    maximum = search_project_map_perception(
        workspace,
        query="mileage tag alignment 中最大的 K 標記是多少？",
    )

    assert "1K、3K、15K、92.3K" in inventory["field_answer"]
    assert "92.3K" in maximum["field_answer"]
    assert inventory["field_answer_priority"] == 100
    assert inventory["field_answer_source_ref"] == (
        "candidates/route_mileage_k_anchors.json"
    )


def test_map_perception_answers_mileage_ocr_alignment_and_source_questions(
    tmp_path: Path,
) -> None:
    workspace = _write_map_perception_workspace(tmp_path)

    unaligned = search_project_map_perception(
        workspace,
        query="有哪些 OCR mileage label 尚未成功對齊 GPX？",
    )
    delta = search_project_map_perception(
        workspace,
        query="mileage alignment 與 GPX 累積里程最大的差值是多少？",
    )
    anomaly = search_project_map_perception(
        workspace,
        query="哪些 K anchors 之間出現明顯缺號或排序異常？",
    )
    ocr = search_project_map_perception(
        workspace,
        query="raster label OCR output 總共有多少筆 label，低信心項目有哪些？",
    )
    linked = search_project_map_perception(
        workspace,
        query="MCP OCR labels 中哪些文字已連結到 named point evidence？",
    )
    sources = search_project_map_perception(
        workspace,
        query="route mileage alignment 的來源影像、OCR 與 route refs 是什麼？",
    )

    assert "20K" in unaligned["field_answer"]
    assert "59300.0 m" in delta["field_answer"]
    assert "15K" in anomaly["field_answer"]
    assert "15K→92.3K" in anomaly["field_answer"]
    assert "3 筆" in ocr["field_answer"]
    assert "ocr.low/blur/0.4" in ocr["field_answer"]
    assert "雲海保線所→np.yunhai_station" in linked["field_answer"]
    assert "alignment artifact=outputs/mileage_tag_alignment.json" in sources[
        "field_answer"
    ]
    assert "來源影像識別符=z15.x1.y1" in sources["field_answer"]
    assert "來源影像為 outputs/mileage_tag_alignment.json" not in sources[
        "field_answer"
    ]
    assert "outputs/layers/raster_label_ocr_output.json" in sources["field_answer"]
    assert "candidates/route_mileage_k_anchors.json" in sources["field_answer"]
    assert sources["field_answer_source_refs"] == [
        "outputs/mileage_tag_alignment.json",
        "outputs/layers/raster_label_ocr_output.json",
        "candidates/route_mileage_k_anchors.json",
        "candidates/route_context_points.json",
        "outputs/risk/risk_ribbon.geojson",
    ]


def _write_map_perception_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "map-perception-workspace"
    (workspace / "candidates").mkdir(parents=True)
    (workspace / "outputs" / "mcp").mkdir(parents=True)
    (workspace / "outputs" / "layers" / "normalized").mkdir(parents=True)
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
                "raster_label_evidence_ref": (
                    "outputs/layers/normalized/raster_label_evidence.geojson"
                ),
                "contour_interpretation_candidates_ref": (
                    "outputs/contour_interpretation_candidates.json"
                ),
                "route_mileage_k_anchors_ref": (
                    "candidates/route_mileage_k_anchors.json"
                ),
                "mileage_tag_alignment_ref": "outputs/mileage_tag_alignment.json",
                "raster_label_ocr_output_ref": (
                    "outputs/layers/raster_label_ocr_output.json"
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
    (workspace / "candidates" / "route_mileage_k_anchors.json").write_text(
        json.dumps(
            {
                "normalized_mileage_k_values": ["1K", "3K", "15K", "92.3K"],
                "anchors": [
                    {"normalized_mileage_k": "1K", "mileage_k": 1.0},
                    {"normalized_mileage_k": "3K", "mileage_k": 3.0},
                    {"normalized_mileage_k": "15K", "mileage_k": 15.0},
                    {"normalized_mileage_k": "92.3K", "mileage_k": 92.3},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "mileage_tag_alignment.json").write_text(
        json.dumps(
            {
                "route_mileage_alignment": {
                    "projected_anchors": [
                        {
                            "normalized_mileage_k": "1K",
                            "mileage_m": 1000.0,
                            "route_distance_m": 1000.0,
                            "usable_for_interpolation": True,
                            "rejected_reasons": [],
                        },
                        {
                            "normalized_mileage_k": "3K",
                            "mileage_m": 3000.0,
                            "route_distance_m": 3200.0,
                            "usable_for_interpolation": True,
                            "rejected_reasons": [],
                        },
                        {
                            "normalized_mileage_k": "15K",
                            "mileage_m": 15000.0,
                            "route_distance_m": 20000.0,
                            "usable_for_interpolation": False,
                            "rejected_reasons": [
                                "non_monotonic_with_main_trail_k_sequence"
                            ],
                        },
                        {
                            "normalized_mileage_k": "92.3K",
                            "mileage_m": 92300.0,
                            "route_distance_m": 33000.0,
                            "usable_for_interpolation": False,
                            "rejected_reasons": [
                                "non_monotonic_with_main_trail_k_sequence"
                            ],
                        },
                    ]
                },
                "source_refs": {
                    "route_mileage_k_anchors": (
                        "candidates/route_mileage_k_anchors.json"
                    ),
                    "route_context_points": "candidates/route_context_points.json",
                    "route_centerline": "outputs/risk/risk_ribbon.geojson",
                    "raster_label_ocr_output": (
                        "outputs/layers/raster_label_ocr_output.json"
                    ),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (workspace / "outputs" / "layers" / "raster_label_ocr_output.json").write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "id": "ocr.15k",
                        "label_text": "15K",
                        "confidence": 0.9,
                        "tile_id": "z15.x1.y1",
                    },
                    {
                        "id": "ocr.20k",
                        "label_text": "20K",
                        "confidence": 0.8,
                        "tile_id": "z15.x1.y2",
                    },
                    {
                        "id": "ocr.low",
                        "label_text": "blur",
                        "confidence": 0.4,
                        "tile_id": "z15.x1.y3",
                    },
                ]
            },
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
    (
        workspace / "outputs" / "layers" / "normalized" / "raster_label_evidence.geojson"
    ).write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_raster_label_evidence",
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "ocr_label.fixture.924m",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.54724121, 23.5759308],
                        },
                        "properties": {
                            "candidate_id": "ocr_label.fixture.924m",
                            "candidate_only": True,
                            "confidence": 0.95,
                            "evidence_type": "named_place_label",
                            "label": "924m",
                            "label_role": "named_place_label",
                            "label_text": "924m",
                            "review_required": True,
                            "review_state": "needs_human_review",
                            "runtime_safety_truth": False,
                            "source_payload_ref": (
                                "outputs/layers/raster_label_ocr_output.json"
                            ),
                            "source_ref": "local_raster_tile.z6.x53.y27",
                            "tile_id": "z6.x53.y27",
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
