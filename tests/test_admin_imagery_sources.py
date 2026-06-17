from pathlib import Path

import pytest

from admin_imagery_sources import (
    build_imagery_source_registry_contract,
    imagery_source_for_project,
    imagery_tile_url,
    load_imagery_source_registry,
)


def test_default_registry_exposes_allowlisted_sources_without_raw_urls():
    contract = build_imagery_source_registry_contract()

    assert contract["artifact_kind"] == "scout_imagery_source_registry_contract"
    assert contract["status"] == "registry_ready"
    assert contract["default_source_id"] == "nlsc_photo2"
    assert contract["remote_fetch_requires_explicit_enable"] is True
    assert contract["remote_fetch_env"] == "SCOUT_ADMIN_IMAGERY_REMOTE_FETCH"
    assert {source["source_id"] for source in contract["sources"]} >= {
        "nlsc_photo2",
        "nlsc_photo_mix",
        "happyman_atis",
        "happyman_rudy",
        "happyman_rudy_twmap",
        "happyman_colorrelief",
        "happyman_geo2016",
        "happyman_tw5k2000",
        "happyman_forest",
    }
    assert all("url_template" not in source for source in contract["sources"])
    assert all(source["url_template_sha256"] for source in contract["sources"])
    rudy = next(source for source in contract["sources"] if source["source_id"] == "happyman_rudy")
    assert rudy["source_kind"] == "wmts_kvp_tile"
    assert rudy["wmts_layer"] == "rudy"
    assert rudy["wmts_tile_matrix_set"] == "gm_grid"
    assert rudy["wmts_endpoint_sha256"]
    assert rudy["raw_wmts_endpoint_embedded"] is False
    assert rudy["ocr_capable"] is True
    assert rudy["label_extraction_roles"] == [
        "trail_mileage_k_anchor",
        "road_mileage_stone",
        "trail_name_label",
        "named_place_label",
        "cellular_communication_point",
        "trail_annotation_label",
        "contour_elevation_label",
        "hazard_annotation_label",
    ]
    assert rudy["map_label_evidence_policy"] == "candidate_only_review_required"
    rudy_twmap = next(
        source
        for source in contract["sources"]
        if source["source_id"] == "happyman_rudy_twmap"
    )
    assert rudy_twmap["ocr_capable"] is True
    assert rudy_twmap["map_label_source_priority"] == "highest"
    assert "trail_mileage_k_anchor" in rudy_twmap["label_extraction_roles"]
    assert "road_mileage_stone" in rudy_twmap["label_extraction_roles"]
    assert "cellular_communication_point" in rudy_twmap["label_extraction_roles"]
    assert "trail_name_label" in rudy_twmap["label_extraction_roles"]


def test_imagery_tile_url_preserves_source_specific_tile_order():
    nlsc = imagery_source_for_project({"imagery_source_id": "nlsc_photo2"})
    atis = imagery_source_for_project({"imagery_source_id": "happyman_atis"})
    rudy = imagery_source_for_project({"imagery_source_id": "happyman_rudy"})

    assert imagery_tile_url(nlsc, 14, 13708, 7063).endswith(
        "/EPSG:3857/14/7063/13708"
    )
    assert imagery_tile_url(atis, 14, 13708, 7063).endswith(
        "/map/atis/14/13708/7063.png"
    )
    rudy_url = imagery_tile_url(rudy, 13, 6853, 3534)
    assert "LAYER=rudy" in rudy_url
    assert "TILEMATRIX=13" in rudy_url
    assert "TILEROW=3534" in rudy_url
    assert "TILECOL=6853" in rudy_url
    assert "TILEMATRIX=05" in imagery_tile_url(rudy, 5, 26, 13)


def test_custom_registry_can_override_default_source(tmp_path: Path):
    registry_path = tmp_path / "imagery_sources.json"
    registry_path.write_text(
        """
{
  "artifact_kind": "scout_imagery_source_registry",
  "default_source_id": "local_test",
  "sources": {
    "local_test": {
      "source_id": "local_test",
      "label": "Local test",
      "label_zh": "本機測試圖磚",
      "provider": "test",
      "source_kind": "xyz_tile",
      "url_template": "https://example.test/tiles/{z}/{x}/{y}.png",
      "tile_order": "z_x_y",
      "media_type": "image/png",
      "min_zoom": 0,
      "max_zoom": 20
    }
  }
}
""",
        encoding="utf-8",
    )

    registry = load_imagery_source_registry(registry_path)
    source = imagery_source_for_project({}, registry_path=registry_path)

    assert registry["default_source_id"] == "local_test"
    assert source["source_id"] == "local_test"
    assert imagery_tile_url(source, 3, 6, 4) == "https://example.test/tiles/3/6/4.png"


def test_unknown_project_source_is_rejected():
    with pytest.raises(ValueError, match="unknown imagery source_id"):
        imagery_source_for_project({"imagery_source_id": "not-allowlisted"})
