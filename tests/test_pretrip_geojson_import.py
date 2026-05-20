import json

import pytest
from pathlib import Path

from pretrip_geojson_import import load_pretrip_geojson_candidates
from pretrip_models import CandidateReviewState

ROOT = Path(__file__).resolve().parents[1]
CHILAI_MAP_CANDIDATES = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "candidates"
    / "map_candidates.json"
)


def test_imports_geojson_features_as_review_required_map_candidates(tmp_path):
    geojson_path = tmp_path / "map_candidates.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "properties": {
                    "source": "field-team-draft",
                    "source_version": "2026-05-14",
                    "confidence": 0.7,
                    "last_verified_at": "2026-05-14T08:00:00Z",
                    "known_staleness_risk": "medium",
                    "license_note": "fixture only",
                },
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "id": "corridor-main",
                            "name": "Main Ridge",
                            "corridor_half_width_m": 8,
                            "route_level": "team-candidate",
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.0, 24.0], [121.001, 24.002]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "id": "poi-water",
                            "name": "Water Source",
                            "poi_type": "water",
                            "source": "ranger-note",
                            "source_version": "v2",
                            "confidence": 0.4,
                        },
                        "geometry": {"type": "Point", "coordinates": [121.0005, 24.001]},
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "id": "hazard-slide",
                            "name": "Old Slide",
                            "hazard_type": "landslide",
                            "l2_duration_s": 45,
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [121.0001, 24.0001],
                                    [121.0009, 24.0001],
                                    [121.0009, 24.0009],
                                    [121.0001, 24.0001],
                                ]
                            ],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_pretrip_geojson_candidates(geojson_path, source_ref="map-fixture")

    assert result.source_artifact.artifact_id == "geojson.map-fixture"
    assert result.source_artifact.kind == "other"
    assert result.source_artifact.provenance.source_ref == "map-fixture"
    assert result.source_artifact.provenance.license_note == "fixture only"

    assert [candidate.candidate_id for candidate in result.corridor_candidates] == ["map.corridor.corridor-main"]
    corridor = result.corridor_candidates[0]
    assert corridor.review_state == CandidateReviewState.NEEDS_REVIEW
    assert corridor.source_refs == ["map-fixture"]
    assert corridor.corridor.corridor_id == "corridor-main"
    assert corridor.corridor.name == "Main Ridge"
    assert corridor.corridor.coordinates[0].lat == 24.0
    assert corridor.corridor.coordinates[0].lon == 121.0
    assert corridor.corridor.corridor_half_width_m == 8.0
    assert corridor.corridor.route_level == "team-candidate"
    assert corridor.source_metadata.source == "field-team-draft"

    poi = result.poi_candidates[0]
    assert poi.candidate_id == "map.poi.poi-water"
    assert poi.review_state == CandidateReviewState.NEEDS_REVIEW
    assert poi.poi.poi_type == "water"
    assert poi.poi.coordinate.lat == 24.001
    assert poi.poi.source_metadata.source == "ranger-note"
    assert poi.poi.source_metadata.source_version == "v2"
    assert poi.poi.source_metadata.confidence == 0.4

    hazard = result.hazard_candidates[0]
    assert hazard.candidate_id == "map.hazard.hazard-slide"
    assert hazard.review_state == CandidateReviewState.NEEDS_REVIEW
    assert hazard.hazard.hazard_type == "landslide"
    assert hazard.hazard.l2_duration_s == 45.0
    assert hazard.source_metadata.source == "field-team-draft"

    assert result.counts == {"corridors": 1, "pois": 1, "hazards": 1}
    assert all(candidate.review_required for candidate in result.all_candidates())


def test_import_generates_deterministic_ids_when_geojson_ids_are_missing(tmp_path):
    geojson_path = tmp_path / "unnamed.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Camp"},
                        "geometry": {"type": "Point", "coordinates": [121.5, 24.5]},
                    },
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "LineString", "coordinates": [[121.0, 24.0], [121.1, 24.1]]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_pretrip_geojson_candidates(geojson_path)

    assert result.poi_candidates[0].candidate_id == "map.poi.feature-001"
    assert result.poi_candidates[0].poi.poi_id == "feature-001"
    assert result.poi_candidates[0].poi.name == "Camp"
    assert result.corridor_candidates[0].candidate_id == "map.corridor.feature-002"
    assert result.corridor_candidates[0].corridor.name == "feature-002"


def test_import_rejects_invalid_collection_and_unsupported_geometry(tmp_path):
    invalid_path = tmp_path / "invalid.geojson"
    invalid_path.write_text(json.dumps({"type": "Feature", "features": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="GeoJSON import must be a FeatureCollection"):
        load_pretrip_geojson_candidates(invalid_path)

    unsupported_path = tmp_path / "unsupported.geojson"
    unsupported_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"id": "multi"},
                        "geometry": {"type": "MultiPoint", "coordinates": [[121.0, 24.0]]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported GeoJSON geometry type"):
        load_pretrip_geojson_candidates(unsupported_path)


def test_chilai_map_candidate_fixture_is_review_required_metadata_only():
    payload = json.loads(CHILAI_MAP_CANDIDATES.read_text())

    assert payload["source_artifact"]["media_type"] == "application/geo+json"
    assert len(payload["corridor_candidates"]) == 1
    assert len(payload["poi_candidates"]) == 1
    assert len(payload["hazard_candidates"]) == 1
    assert payload["corridor_candidates"][0]["review_required"] is True
    assert payload["poi_candidates"][0]["review_state"] == "needs_review"
    assert payload["hazard_candidates"][0]["hazard"]["hazard_type"] == "limited_retreat_options"
    assert "features" not in json.dumps(payload)
