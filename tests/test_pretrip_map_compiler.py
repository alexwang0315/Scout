import json
from pathlib import Path

import pytest

from mission_models import DiversionPoint
from offline_map_models import HazardZone, TrailCorridor
from pretrip_map_compiler import (
    PreTripMapCompileResult,
    compile_pretrip_map_candidates,
    load_and_compile_pretrip_map_candidates,
)
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


def test_compile_reviewed_poi_to_phase1_diversion_point():
    payload = _map_candidates(
        poi_candidates=[
            _poi_candidate(
                candidate_id="map.poi.water",
                poi_id="water",
                poi_type="water",
                review_state="accepted",
            )
        ]
    )

    result = compile_pretrip_map_candidates(payload)

    assert result.counts == {
        "diversion_points": 1,
        "trail_corridors": 0,
        "hazard_zones": 0,
        "compiled_candidates": 1,
        "skipped_candidates": 0,
    }
    diversion = result.diversion_points[0]
    assert diversion == DiversionPoint(
        diversion_id="map.poi.water",
        name="Water",
        diversion_type="water",
        lat=24.001,
        lon=121.001,
        distance_from_route_m=0.0,
        required_energy=0.05,
        required_daylight_seconds=0,
        communication_available=False,
        risk_level=0.1,
    )
    assert result.compiled_candidates[0].compiled_as == ["diversion_point"]


def test_compile_reviewed_hazard_and_corridor_summary():
    payload = _map_candidates(
        corridor_candidates=[
            _corridor_candidate(
                candidate_id="map.corridor.main",
                corridor_id="main",
                review_state="accepted",
            )
        ],
        hazard_candidates=[
            _hazard_candidate(
                candidate_id="map.hazard.slide",
                hazard_id="slide",
                review_state="accepted",
            )
        ],
    )

    result = compile_pretrip_map_candidates(payload)

    assert [corridor.corridor_id for corridor in result.trail_corridors] == ["main"]
    assert [hazard.hazard_id for hazard in result.hazard_zones] == ["slide"]
    assert [record.compiled_as for record in result.compiled_candidates] == [
        ["trail_corridor"],
        ["hazard_zone"],
    ]
    TrailCorridor.model_validate(result.trail_corridors[0].model_dump(mode="json"))
    HazardZone.model_validate(result.hazard_zones[0].model_dump(mode="json"))


def test_default_compile_rejects_unreviewed_map_candidates():
    payload = _map_candidates(
        poi_candidates=[
            _poi_candidate(
                candidate_id="map.poi.unreviewed",
                poi_id="unreviewed",
                poi_type="water",
                review_state="needs_review",
            )
        ]
    )

    with pytest.raises(ValueError, match="allow_unreviewed=True"):
        compile_pretrip_map_candidates(payload)

    result = compile_pretrip_map_candidates(payload, allow_unreviewed=True)

    assert [point.diversion_id for point in result.diversion_points] == ["map.poi.unreviewed"]
    assert result.compiled_candidates[0].review_state == CandidateReviewState.NEEDS_REVIEW


def test_rejected_map_candidates_are_skipped_not_compiled():
    payload = _map_candidates(
        poi_candidates=[
            _poi_candidate(
                candidate_id="map.poi.rejected",
                poi_id="rejected",
                poi_type="water",
                review_state="rejected",
            )
        ],
        hazard_candidates=[
            _hazard_candidate(
                candidate_id="map.hazard.rejected",
                hazard_id="rejected",
                review_state="rejected",
            )
        ],
    )

    result = compile_pretrip_map_candidates(payload)

    assert result.diversion_points == []
    assert result.hazard_zones == []
    assert result.compiled_candidates == []
    assert [record.candidate_id for record in result.skipped_candidates] == [
        "map.hazard.rejected",
        "map.poi.rejected",
    ]
    assert all(record.skipped_reason == "candidate rejected by review" for record in result.skipped_candidates)


def test_chilai_map_fixture_can_compile_only_when_unreviewed_is_explicitly_allowed():
    payload = json.loads(CHILAI_MAP_CANDIDATES.read_text())

    with pytest.raises(ValueError, match="allow_unreviewed=True"):
        compile_pretrip_map_candidates(payload)

    result = load_and_compile_pretrip_map_candidates(CHILAI_MAP_CANDIDATES, allow_unreviewed=True)
    validated = PreTripMapCompileResult.model_validate(result.model_dump(mode="json"))

    assert validated.counts == {
        "diversion_points": 1,
        "trail_corridors": 1,
        "hazard_zones": 1,
        "compiled_candidates": 3,
        "skipped_candidates": 0,
    }
    assert validated.trail_corridors[0].corridor_id == "chilai_nanhua_primary_corridor"
    assert validated.hazard_zones[0].hazard_type == "limited_retreat_options"
    assert validated.diversion_points[0].diversion_type == "trailhead"


def _map_candidates(
    *,
    corridor_candidates: list[dict] | None = None,
    poi_candidates: list[dict] | None = None,
    hazard_candidates: list[dict] | None = None,
) -> dict:
    source_metadata = _source_metadata()
    return {
        "source_artifact": {
            "artifact_id": "geojson.test",
            "kind": "other",
            "uri": "/tmp/test.geojson",
            "media_type": "application/geo+json",
            "provenance": _provenance(),
            "metadata": {"candidate_layer": "pretrip_map", "review_required": True},
        },
        "source_metadata": source_metadata,
        "corridor_candidates": corridor_candidates or [],
        "poi_candidates": poi_candidates or [],
        "hazard_candidates": hazard_candidates or [],
    }


def _candidate_base(candidate_id: str, label: str, review_state: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "label": label,
        "source_refs": ["test-map"],
        "provenance": [_provenance()],
        "review_state": review_state,
        "review_required": True,
        "source_metadata": _source_metadata(),
    }


def _corridor_candidate(candidate_id: str, corridor_id: str, review_state: str) -> dict:
    return {
        **_candidate_base(candidate_id, "Main corridor", review_state),
        "corridor": {
            "corridor_id": corridor_id,
            "name": "Main corridor",
            "coordinates": [{"lat": 24.0, "lon": 121.0}, {"lat": 24.01, "lon": 121.01}],
            "corridor_half_width_m": 8.0,
            "route_level": "fixture",
            "source_metadata": _source_metadata(),
        },
    }


def _poi_candidate(candidate_id: str, poi_id: str, poi_type: str, review_state: str) -> dict:
    return {
        **_candidate_base(candidate_id, poi_id.title(), review_state),
        "poi": {
            "poi_id": poi_id,
            "poi_type": poi_type,
            "name": poi_id.title(),
            "coordinate": {"lat": 24.001, "lon": 121.001},
            "source_metadata": _source_metadata(),
        },
    }


def _hazard_candidate(candidate_id: str, hazard_id: str, review_state: str) -> dict:
    return {
        **_candidate_base(candidate_id, "Old slide", review_state),
        "hazard": {
            "hazard_id": hazard_id,
            "hazard_type": "landslide",
            "name": "Old slide",
            "polygon": [
                {"lat": 24.0, "lon": 121.0},
                {"lat": 24.0, "lon": 121.01},
                {"lat": 24.01, "lon": 121.01},
                {"lat": 24.0, "lon": 121.0},
            ],
            "l2_duration_s": 45.0,
            "source_metadata": _source_metadata(),
        },
    }


def _source_metadata() -> dict:
    return {
        "source": "pytest",
        "source_version": "v0",
        "confidence": 0.8,
        "last_verified_at": "2026-05-14",
        "known_staleness_risk": "low",
    }


def _provenance() -> dict:
    return {
        "source_ref": "test-map",
        "source_kind": "other",
        "uri": "/tmp/test.geojson",
        "method": "pytest",
    }
