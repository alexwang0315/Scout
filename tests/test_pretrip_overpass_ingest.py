import hashlib
import json
from pathlib import Path

from offline_map import load_offline_map_context
from pretrip_models import RouteBBox
from pretrip_overpass_ingest import (
    CONVERSION_RULE_VERSION,
    OverpassIngestResult,
    import_overpass_evidence_candidates,
    load_overpass_evidence_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "maps"
OVERPASS_RAW = FIXTURE_ROOT / "phase_a_overpass_raw.json"
OVERPASS_QUERY = FIXTURE_ROOT / "phase_a_overpass_query.ql"


def test_loads_fixture_backed_overpass_payload_and_preserves_provenance():
    result = _load_fixture()

    assert result.request.query_body == OVERPASS_QUERY.read_text(encoding="utf-8")
    assert result.request.endpoint == "https://overpass-api.de/api/interpreter"
    assert result.request.http_status == 200
    assert result.request.bbox_wgs84 == RouteBBox(
        min_lat=24.05,
        min_lon=121.21,
        max_lat=24.06,
        max_lon=121.23,
    )
    assert result.request.raw_response_sha256 == hashlib.sha256(OVERPASS_RAW.read_bytes()).hexdigest()
    assert result.request.normalized_artifact_path.endswith("phase_a_overpass_normalized.geojson")

    assert result.source_artifact.kind == "overpass_raw_payload"
    assert result.source_artifact.provenance.source_kind == "overpass_raw_payload"
    assert result.source_artifact.provenance.captured_at == "2026-05-20T00:00:00Z"
    assert result.source_artifact.metadata["runtime_truth"] is False
    assert result.source_artifact.metadata["conversion_rule_version"] == CONVERSION_RULE_VERSION
    OverpassIngestResult.model_validate(result.model_dump(mode="json"))


def test_overpass_node_way_relation_tags_become_phase_a_candidates():
    result = _load_fixture()

    assert result.counts["candidates"] == 8
    assert result.counts["skipped"] == 1
    assert {
        "trail_corridor_candidate",
        "hiking_route_candidate",
        "shelter_candidate",
        "water_source_candidate",
        "parking_candidate",
        "peak_candidate",
        "terrain_risk_candidate",
    }.issubset({candidate.candidate_type for candidate in result.candidates})

    relation = _candidate(result, "overpass.hiking_route_candidate.relation.2001")
    assert relation.osm_type == "relation"
    assert relation.geometry["type"] == "MultiLineString"
    assert relation.geometry["coordinates"] == [
        [
            [121.211, 24.051],
            [121.214, 24.052],
        ],
        [
            [121.214, 24.052],
            [121.222, 24.055],
        ],
    ]

    shelter = _candidate(result, "overpass.shelter_candidate.node.5001")
    assert shelter.feature_type == "poi"
    assert shelter.geojson_feature["properties"]["poi_type"] == "shelter"
    assert shelter.stale_risk == "high"

    terrain = _candidate(result, "overpass.terrain_risk_candidate.way.1003")
    assert terrain.feature_type == "hazard_zone"
    assert terrain.geojson_feature["properties"]["hazard_type"] == "landslide"
    assert terrain.geometry["type"] == "Polygon"


def test_overpass_way_and_relation_huts_and_other_poi_get_representative_points():
    payload = {
        "version": 0.6,
        "elements": [
            {
                "type": "way",
                "id": 7001,
                "tags": {"name": "天池山莊", "tourism": "alpine_hut"},
                "geometry": [
                    {"lat": 24.0420, "lon": 121.2790},
                    {"lat": 24.0420, "lon": 121.2792},
                    {"lat": 24.0422, "lon": 121.2792},
                    {"lat": 24.0420, "lon": 121.2790},
                ],
            },
            {
                "type": "relation",
                "id": 7002,
                "tags": {"name": "測試避難設施", "amenity": "shelter"},
                "members": [
                    {
                        "type": "way",
                        "ref": 7001,
                        "geometry": [
                            {"lat": 24.0420, "lon": 121.2790},
                            {"lat": 24.0422, "lon": 121.2792},
                        ],
                    }
                ],
            },
            {
                "type": "node",
                "id": 7003,
                "lat": 24.041,
                "lon": 121.278,
                "tags": {"name": "天池", "place": "locality"},
            },
            {
                "type": "node",
                "id": 7004,
                "lat": 24.043,
                "lon": 121.280,
                "tags": {"name": "公廁", "amenity": "toilets"},
            },
        ],
    }

    result = import_overpass_evidence_candidates(
        payload,
        query_body="fixture",
        bbox_wgs84=RouteBBox(
            min_lat=24.03,
            min_lon=121.27,
            max_lat=24.05,
            max_lon=121.29,
        ),
        request_timestamp="2026-07-28T00:00:00Z",
        endpoint="fixture://overpass",
        http_status=200,
        raw_payload_uri="fixture.json",
        normalized_artifact_path="normalized.geojson",
        source_ref="fixture",
    )

    assert result.counts["shelter_candidate"] == 2
    assert result.counts["other_poi_candidate"] == 2
    assert all(candidate.geometry["type"] == "Point" for candidate in result.candidates)
    other = next(
        candidate
        for candidate in result.candidates
        if candidate.candidate_type == "other_poi_candidate"
    )
    assert other.geojson_feature["properties"]["poi_type"] == "other"


def test_incomplete_overpass_geometry_is_marked_and_skipped_without_crash():
    result = _load_fixture()

    skipped = result.skipped_objects[0]
    assert skipped.osm_type == "way"
    assert skipped.osm_id == 1004
    assert skipped.candidate_type == "trail_corridor_candidate"
    assert skipped.skipped_reason == "Line candidate requires complete Overpass geometry coordinates"
    assert "1004" not in json.dumps(result.normalized_geojson)


def test_normalized_overpass_geojson_loads_as_existing_scout_map_context(tmp_path):
    result = _load_fixture()
    normalized_path = tmp_path / "phase_a_overpass_normalized.geojson"
    normalized_path.write_text(
        json.dumps(result.normalized_geojson, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    context = load_offline_map_context(normalized_path)

    assert len(context.corridors) == 4
    assert {
        corridor.corridor_id
        for corridor in context.corridors
        if corridor.corridor_id.startswith("overpass.hiking_route_candidate.relation.2001")
    } == {
        "overpass.hiking_route_candidate.relation.2001.part_001",
        "overpass.hiking_route_candidate.relation.2001.part_002",
    }
    assert len(context.hazards) == 1
    assert len(context.pois) == 4
    assert {poi.poi_type for poi in context.pois} == {"shelter", "water_source", "parking", "peak"}
    assert context.source_metadata.source == "overpass_osm"
    assert context.source_metadata.known_staleness_risk == "medium"


def test_normalized_geojson_features_keep_evidence_chain_metadata():
    result = _load_fixture()

    assert result.normalized_geojson["artifact_kind"] == "pretrip_overpass_vector_evidence"
    assert result.normalized_geojson["schema_version"] == "route_corridor_map_preparation.v1"
    assert result.normalized_geojson["route_scope_ref"] == "normalized/routes/route_evidence_bundle.json"
    assert result.normalized_geojson["boundary"] == {
        "candidate_only": True,
        "runtime_truth": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "raw_gpx_embedded_in_json": False,
    }
    feature = result.normalized_geojson["features"][0]
    properties = feature["properties"]

    assert properties["query_body"] == OVERPASS_QUERY.read_text(encoding="utf-8")
    assert properties["bbox_wgs84"]["min_lat"] == 24.05
    assert properties["route_corridor"] == {"route_ref": "route.fixture.phase_a", "corridor_width_m": 100}
    assert properties["endpoint"] == "https://overpass-api.de/api/interpreter"
    assert properties["http_status"] == 200
    assert properties["raw_payload_uri"].endswith("phase_a_overpass_raw.json")
    assert properties["raw_response_sha256"] == result.request.raw_response_sha256
    assert properties["normalized_artifact_path"].endswith("phase_a_overpass_normalized.geojson")
    assert properties["conversion_rule_version"] == CONVERSION_RULE_VERSION
    assert properties["linked_route_ref"] is None
    assert properties["linked_segment_ref"] is None
    assert properties["linked_checkpoint_ref"] is None
    assert properties["runtime_truth"] is False


def _load_fixture() -> OverpassIngestResult:
    return load_overpass_evidence_candidates(
        OVERPASS_RAW,
        query_body=OVERPASS_QUERY.read_text(encoding="utf-8"),
        bbox_wgs84=RouteBBox(min_lat=24.05, min_lon=121.21, max_lat=24.06, max_lon=121.23),
        route_corridor={"route_ref": "route.fixture.phase_a", "corridor_width_m": 100},
        request_timestamp="2026-05-20T00:00:00Z",
        endpoint="https://overpass-api.de/api/interpreter",
        http_status=200,
        normalized_artifact_path="tests/fixtures/maps/phase_a_overpass_normalized.geojson",
        source_ref="phase_a_overpass_fixture",
    )


def _candidate(result: OverpassIngestResult, candidate_id: str):
    return next(candidate for candidate in result.candidates if candidate.candidate_id == candidate_id)
