from pathlib import Path

import pytest

from geo_utils import haversine_m
from pretrip_candidate_generation import generate_pretrip_candidates_from_gpx
from pretrip_models import CandidateReviewState


ROOT = Path(__file__).resolve().parents[1]
NORMAL_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_generate_candidates_from_temp_gpx_includes_start_finish_and_spaced_checkpoint(tmp_path):
    route_path = _write_temp_gpx(
        tmp_path,
        [
            (25.0000, 121.0000, 100.0),
            (25.0045, 121.0000, 130.0),
            (25.0090, 121.0000, 120.0),
            (25.0135, 121.0000, 180.0),
        ],
    )

    result = generate_pretrip_candidates_from_gpx(
        route_path,
        checkpoint_spacing_m=700.0,
        source_ref="fixture-route",
    )

    checkpoints = result.checkpoint_candidates
    assert [checkpoint.candidate_id for checkpoint in checkpoints] == ["cp.start", "cp.001", "cp.finish"]
    assert [checkpoint.checkpoint_type for checkpoint in checkpoints] == ["start", "route_progress", "finish"]
    assert [checkpoint.route_point_index for checkpoint in checkpoints] == [0, 2, 3]
    assert all(checkpoint.review_state == CandidateReviewState.PROPOSED for checkpoint in checkpoints)
    assert all(checkpoint.source_refs == ["fixture-route"] for checkpoint in checkpoints)
    assert all(checkpoint.provenance[0].source_kind == "gpx" for checkpoint in checkpoints)


def test_generate_segments_between_adjacent_candidates_with_distance_elevation_and_indices(tmp_path):
    route_points = [
        (25.0000, 121.0000, 100.0),
        (25.0045, 121.0000, 130.0),
        (25.0090, 121.0000, 120.0),
        (25.0135, 121.0000, 180.0),
    ]
    route_path = _write_temp_gpx(tmp_path, route_points)

    result = generate_pretrip_candidates_from_gpx(route_path, checkpoint_spacing_m=700.0)

    segments = result.segment_candidates
    assert [segment.candidate_id for segment in segments] == ["seg.001", "seg.002"]
    assert [(segment.from_candidate_id, segment.to_candidate_id) for segment in segments] == [
        ("cp.start", "cp.001"),
        ("cp.001", "cp.finish"),
    ]
    assert [(segment.route_point_start_index, segment.route_point_end_index) for segment in segments] == [(0, 2), (2, 3)]
    assert segments[0].distance_m == pytest.approx(_distance(route_points, 0, 2), rel=0.001)
    assert segments[1].distance_m == pytest.approx(_distance(route_points, 2, 3), rel=0.001)
    assert segments[0].elevation_gain_m == pytest.approx(30.0)
    assert segments[0].elevation_loss_m == pytest.approx(10.0)
    assert segments[1].elevation_gain_m == pytest.approx(60.0)
    assert segments[1].elevation_loss_m == pytest.approx(0.0)


def test_generate_candidates_from_existing_fixture_without_dtm_data():
    result = generate_pretrip_candidates_from_gpx(NORMAL_ROUTE, checkpoint_spacing_m=1_000.0)

    assert result.checkpoint_candidates[0].candidate_id == "cp.start"
    assert result.checkpoint_candidates[-1].candidate_id == "cp.finish"
    assert len(result.checkpoint_candidates) >= 2
    assert len(result.segment_candidates) == len(result.checkpoint_candidates) - 1
    assert result.segment_candidates[0].route_point_start_index == 0
    assert result.segment_candidates[-1].route_point_end_index == result.checkpoint_candidates[-1].route_point_index


def test_checkpoint_spacing_must_be_positive(tmp_path):
    route_path = _write_temp_gpx(
        tmp_path,
        [
            (25.0000, 121.0000, 100.0),
            (25.0010, 121.0000, 110.0),
        ],
    )

    with pytest.raises(ValueError, match="checkpoint_spacing_m must be greater than 0"):
        generate_pretrip_candidates_from_gpx(route_path, checkpoint_spacing_m=0)


def _distance(points: list[tuple[float, float, float]], start_index: int, end_index: int) -> float:
    distance_m = 0.0
    for previous, current in zip(points[start_index:end_index], points[start_index + 1 : end_index + 1]):
        distance_m += haversine_m(previous[0], previous[1], current[0], current[1])
    return distance_m


def _write_temp_gpx(tmp_path: Path, points: list[tuple[float, float, float]]) -> Path:
    route_path = tmp_path / "route.gpx"
    track_points = "\n".join(
        f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}"><ele>{elevation:.1f}</ele></trkpt>'
        for lat, lon, elevation in points
    )
    route_path.write_text(
        "\n".join(
            [
                "<?xml version='1.0' encoding='utf-8'?>",
                '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="pytest">',
                "  <trk><trkseg>",
                track_points,
                "  </trkseg></trk>",
                "</gpx>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return route_path
