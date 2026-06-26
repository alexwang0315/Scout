import json
from pathlib import Path

from pretrip_models import RouteBBox
from pretrip_osm_pbf_ingest import (
    build_osm_pbf_feature_index,
    build_osmium_extraction_plan,
    import_osm_pbf_evidence_candidates,
    osm_json_to_overpass_payload,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "maps" / "phase_a_osm_pbf_osmjson.json"


def test_osm_json_hydrates_way_and_relation_geometry_for_overpass_adapter() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    overpass_payload = osm_json_to_overpass_payload(payload)
    elements = {f"{item['type']}/{item['id']}": item for item in overpass_payload["elements"]}

    assert elements["way/100"]["geometry"] == [
        {"lat": 23.8701, "lon": 121.1701},
        {"lat": 23.8705, "lon": 121.1705},
        {"lat": 23.8709, "lon": 121.1709},
    ]
    assert "geometry" not in elements["way/102"]
    assert elements["relation/200"]["members"][0]["geometry"][0] == {
        "lat": 23.8701,
        "lon": 121.1701,
    }


def test_osm_pbf_json_import_preserves_local_source_and_skips_incomplete_geometry() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    evidence = import_osm_pbf_evidence_candidates(
        payload,
        query_body="fixture osmium extraction plan",
        bbox_wgs84=RouteBBox(
            min_lat=23.86,
            min_lon=121.16,
            max_lat=23.88,
            max_lon=121.18,
        ),
        route_corridor={"route_ref": "fixture.route", "corridor_m": 500},
        request_timestamp="2026-06-25T00:00:00+00:00",
        endpoint="local-osm-pbf:///tmp/taiwan.osm.pbf",
        raw_payload_uri="normalized/map/osm_pbf_phase_a_raw.osm.json",
        raw_response_sha256=None,
        normalized_artifact_path="normalized/map/overpass_vector_evidence.geojson",
        source_ref="normalized/map/osm_pbf_phase_a_raw.osm.json",
        pbf_source_uri="/tmp/taiwan.osm.pbf",
        pbf_download_url="http://download.geofabrik.de/asia/taiwan-latest.osm.pbf",
        pbf_source_sha256="sha256-fixture",
        pbf_cache_metadata={
            "cache_status": "fresh",
            "cache_ttl_days": 30,
            "refresh_required": False,
        },
        extraction_plan={"commands": [["osmium", "extract"]]},
    )

    candidate_types = {
        candidate["candidate_type"] for candidate in evidence["candidates"]
    }
    assert evidence["artifact_kind"] == "pretrip_osm_pbf_evidence"
    assert evidence["counts"]["candidates"] == 6
    assert evidence["counts"]["skipped"] >= 1
    assert "trail_corridor_candidate" in candidate_types
    assert "hiking_route_candidate" in candidate_types
    assert "peak_candidate" in candidate_types
    assert "shelter_candidate" in candidate_types
    assert "water_source_candidate" in candidate_types
    assert evidence["normalized_geojson"]["properties"]["source"] == "local_osm_pbf"
    assert evidence["normalized_geojson"]["properties"]["pbf_download_url"] == (
        "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
    )
    assert evidence["normalized_geojson"]["properties"]["pbf_source_sha256"] == "sha256-fixture"
    assert evidence["pbf_cache"]["cache_status"] == "fresh"
    assert evidence["normalized_geojson"]["properties"]["pbf_cache"][
        "cache_ttl_days"
    ] == 30
    assert evidence["source_artifact"]["metadata"]["pbf_download_url"] == (
        "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf"
    )
    assert evidence["source_artifact"]["metadata"]["pbf_cache"][
        "refresh_required"
    ] is False
    assert all(
        feature["properties"]["runtime_safety_truth"] is False
        for feature in evidence["normalized_geojson"]["features"]
    )
    assert any(
        item["skipped_reason"] == "Line candidate requires complete Overpass geometry coordinates"
        for item in evidence["skipped_objects"]
    )


def test_osmium_extraction_plan_uses_route_bbox_and_hiking_filters(tmp_path: Path) -> None:
    plan = build_osmium_extraction_plan(
        pbf_path=Path("/data/osm/taiwan.osm.pbf"),
        bbox_wgs84={
            "south": 23.86,
            "west": 121.16,
            "north": 23.88,
            "east": 121.18,
        },
        work_dir=tmp_path,
        raw_osm_json_path=tmp_path / "raw.osm.json",
        osmium_bin="osmium",
    )

    assert plan.bbox_arg == "121.1600000,23.8600000,121.1800000,23.8800000"
    assert plan.commands[0][:4] == ("osmium", "extract", "--overwrite", "--bbox")
    assert len(plan.commands) == 1
    assert "w/highway=path,footway,track,steps,bridleway,pedestrian" in plan.filter_specs
    assert "n/natural=spring,peak" in plan.filter_specs


def test_osm_pbf_feature_index_groups_render_features_for_map_risk_timeline() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "@type": "node",
                    "@id": 1,
                    "highway": "milestone",
                    "distance": "7K+000",
                    "network": "能高安東軍縱走",
                },
                "geometry": {"type": "Point", "coordinates": [121.17, 23.87]},
            },
            {
                "type": "Feature",
                "properties": {
                    "@type": "node",
                    "@id": 2,
                    "information": "mobile",
                    "name": "通訊點",
                },
                "geometry": {"type": "Point", "coordinates": [121.171, 23.871]},
            },
            {
                "type": "Feature",
                "properties": {
                    "@type": "way",
                    "@id": 10,
                    "highway": "path",
                    "name": "測試步道",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[121.17, 23.87], [121.18, 23.88]],
                },
            },
        ],
    }

    index = build_osm_pbf_feature_index(
        payload,
        source_ref="normalized/map/osm_pbf_route_bbox_full.geojson",
        render_source_ref="normalized/map/osm_pbf_route_bbox.osm.pbf",
        request_timestamp="2026-06-25T00:00:00+00:00",
    )

    assert index["artifact_kind"] == "pretrip_local_osm_pbf_feature_index"
    assert index["counts"]["item_count"] == 3
    assert index["counts"]["category_counts"] == {
        "milestone_route_marker": 1,
        "mobile_signal": 1,
        "trail_network": 1,
    }
    items = {item["category_id"]: item for item in index["items"]}
    assert items["milestone_route_marker"]["label"] == "7K+000 能高安東軍縱走"
    assert items["mobile_signal"]["lat"] == 23.871
    assert items["trail_network"]["geometry_summary"]["point_count"] == 2
    assert all(item["runtime_safety_truth"] is False for item in index["items"])
