import json
from pathlib import Path

from pretrip_models import DtmCoverageSummary, PreTripPackage, PreTripRouteSummary
from pretrip_source_ingest import scan_dtm_coverage, wgs84_to_twd97


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_chilai_pretrip_package_fixture_validates():
    payload = json.loads((FIXTURE_ROOT / "outputs" / "pretrip_package.json").read_text())
    package = PreTripPackage.model_validate(payload)

    assert package.package_id == "pretrip.chilai_nanhua_day1.v0"
    assert package.status == "candidate"
    assert package.route_summary.route_name == "奇萊南華-能高越嶺步道Day1"
    assert package.route_summary.point_count == 2211
    assert package.route_summary.distance_m > 14_000
    assert {artifact.kind for artifact in package.source_artifacts} == {"gpx", "photo"}
    assert len(package.planning_references) == 3
    assert all(reference.not_observed_fact for reference in package.planning_references)
    assert len(package.route_guide_timing_candidates) == 19
    timing = package.route_guide_timing_candidates[0]
    assert timing.route_guide_segment_time_minutes is None
    assert timing.personal_route_guide_multiplier is None
    assert timing.team_route_guide_multiplier is None
    assert timing.pace_multiplier_basis == "mixed_unknown"
    assert timing.readiness_eta_policy == "total_elapsed_time_including_normal_rest"
    g11_timing = package.route_guide_timing_candidates[1]
    assert g11_timing.from_node_name == "霧社"
    assert g11_timing.to_node_name == "廬山部落"
    assert g11_timing.route_guide_segment_time_minutes == 30
    assert g11_timing.review_state == "needs_review"
    assert len(package.checkpoint_candidates) == 11
    assert len(package.segment_candidates) == 10
    assert len(package.retreat_route_candidates) == 1
    assert package.retreat_route_candidates[0].retreat_type == "return_to_entry"
    assert package.retreat_route_candidates[0].expected_use == "both"
    assert package.checkpoint_candidates[0].candidate_id == "cp.start"
    assert package.checkpoint_candidates[-1].candidate_id == "cp.finish"
    assert package.segment_candidates[0].from_candidate_id == "cp.start"

    assert package.dtm_coverage_summary is not None
    assert package.dtm_coverage_summary.scanned_header_count == 1411
    assert package.dtm_coverage_summary.missing_grid_count == 0
    assert len(package.dtm_coverage_summary.candidate_tiles) == 10
    assert {tile.county for tile in package.dtm_coverage_summary.candidate_tiles} == {"南投縣", "花蓮縣"}


def test_chilai_candidate_fixture_files_match_package():
    package = PreTripPackage.model_validate(
        json.loads((FIXTURE_ROOT / "outputs" / "pretrip_package.json").read_text())
    )
    checkpoints = json.loads((FIXTURE_ROOT / "candidates" / "checkpoints.json").read_text())
    segments = json.loads((FIXTURE_ROOT / "candidates" / "segments.json").read_text())
    retreat_routes = json.loads((FIXTURE_ROOT / "candidates" / "retreat_routes.json").read_text())
    planning_references = json.loads((FIXTURE_ROOT / "candidates" / "planning_references.json").read_text())
    route_guide_timing = json.loads((FIXTURE_ROOT / "candidates" / "route_guide_timing.json").read_text())

    assert checkpoints == [candidate.model_dump(mode="json") for candidate in package.checkpoint_candidates]
    assert segments == [candidate.model_dump(mode="json") for candidate in package.segment_candidates]
    assert retreat_routes == [candidate.model_dump(mode="json") for candidate in package.retreat_route_candidates]
    assert planning_references == [reference.model_dump(mode="json") for reference in package.planning_references]
    assert route_guide_timing == [
        candidate.model_dump(mode="json") for candidate in package.route_guide_timing_candidates
    ]
    assert all(candidate["review_state"] == "proposed" for candidate in checkpoints)
    assert all(candidate["review_state"] == "proposed" for candidate in segments)


def test_dtm_coverage_summary_fixture_is_standalone_metadata():
    payload = json.loads((FIXTURE_ROOT / "normalized" / "terrain" / "dtm_coverage_summary.json").read_text())
    summary = DtmCoverageSummary.model_validate(payload)

    assert summary.route_bbox_wgs84.min_lon < summary.route_bbox_wgs84.max_lon
    assert summary.route_bbox_twd97.min_x < summary.route_bbox_twd97.max_x
    assert summary.candidate_tiles
    assert all(tile.header_uri.endswith("dem.hdr") for tile in summary.candidate_tiles)
    assert all(tile.grid_uri and tile.grid_uri.endswith("dem.grd") for tile in summary.candidate_tiles)


def test_twd97_projection_has_expected_central_meridian_origin():
    x, y = wgs84_to_twd97(0.0, 121.0)

    assert round(x, 3) == 250000.0
    assert round(y, 3) == 0.0


def test_scan_dtm_coverage_matches_only_intersecting_temp_headers(tmp_path):
    dtm_dir = tmp_path / "分幅_南投縣20MDEM(2025)"
    dtm_dir.mkdir()
    _write_header(dtm_dir / "inside_dem.hdr", tile_id="inside", origin_x=271000, origin_y=2659800)
    (dtm_dir / "inside_dem.grd").write_bytes(b"fixture")
    _write_header(dtm_dir / "outside_dem.hdr", tile_id="outside", origin_x=100000, origin_y=100000)
    (dtm_dir / "outside_dem.grd").write_bytes(b"fixture")

    route_summary = PreTripRouteSummary.model_validate(
        json.loads((FIXTURE_ROOT / "normalized" / "routes" / "route_summary.json").read_text())
    )
    summary = scan_dtm_coverage(
        route_summary=route_summary,
        source_dirs=[dtm_dir],
        summary_id="dtm_coverage.test",
    )

    assert summary.scanned_header_count == 2
    assert summary.missing_grid_count == 0
    assert [tile.tile_id for tile in summary.candidate_tiles] == ["inside"]
    assert summary.candidate_tiles[0].county == "南投縣"


def _write_header(path: Path, *, tile_id: str, origin_x: int, origin_y: int) -> None:
    path.write_text(
        "\n".join(
            [
                "fixture tile",
                tile_id,
                "TWD97[2010]",
                "TWVD2001",
                "5000",
                "20",
                "20",
                "0",
                "144",
                "144",
                str(origin_x),
                str(origin_y),
                "10",
            ]
        )
        + "\n",
        encoding="big5",
    )
