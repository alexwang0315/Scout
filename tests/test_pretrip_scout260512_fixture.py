import json
from pathlib import Path

from pretrip_models import PreTripPackage
from pretrip_scout260512_fixture import (
    PROJECT_ID,
    build_scout_260512_pretrip_fixture,
    load_scout_260512_pretrip_fixture,
    write_scout_260512_pretrip_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "scout_260512_field_regression"
)
CHILAI_PROJECT = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "project.json"
)


def test_scout_260512_pretrip_regression_package_validates():
    fixture = load_scout_260512_pretrip_fixture(FIXTURE_ROOT)
    package = PreTripPackage.model_validate(fixture["package"])
    project = fixture["project"]

    assert package.package_id == "pretrip.scout_260512_field_regression.v0"
    assert package.project_id == PROJECT_ID
    assert package.status == "candidate"
    assert package.route_summary.artifact_id == "artifact.route.scout_260512_field_route_gpx"
    assert package.route_summary.distance_m > 4_000
    assert package.route_summary.point_count > 1_000
    assert len(package.source_artifacts) == 3
    assert len(package.checkpoint_candidates) == project["checkpoint_candidate_count"] == 6
    assert len(package.segment_candidates) == project["segment_candidate_count"] == 5
    assert len(package.retreat_route_candidates) == 1
    assert all(candidate.review_state == "needs_review" for candidate in package.checkpoint_candidates)
    assert all(candidate.review_state == "needs_review" for candidate in package.segment_candidates)
    assert package.planning_references[0].not_observed_fact is True
    assert any("field-data-to-fixtures regression" in note for note in package.readiness_notes)
    assert any("not the primary mountain calibration" in note for note in package.readiness_notes)


def test_scout_260512_project_indexes_metadata_and_candidate_refs():
    fixture = load_scout_260512_pretrip_fixture(FIXTURE_ROOT)
    project = fixture["project"]
    map_summary = fixture["map_summary"]
    map_candidates = fixture["map_candidates"]

    assert project["fixture_kind"] == "field-data-to-fixtures-regression"
    assert project["field_data_to_fixtures_regression"] is True
    assert project["primary_mountain_calibration"] is False
    assert project["compiled_into_mountain_calibration"] is False
    assert project["phase1_live_runtime_touched"] is False
    assert project["raw_payloads_embedded"] is False
    assert project["package_ref"] == "outputs/pretrip_package.json"
    assert project["map_summary_ref"] == "normalized/map/map_summary.json"
    assert project["map_candidates_ref"] == "candidates/map_candidates.json"
    assert project["source_case_id"] == "scout_260512_field_golden"
    assert map_summary["corridor_count"] == 684
    assert map_summary["raw_payload_embedded"] is False
    assert map_candidates["status"] == "candidate_only"
    assert map_candidates["raw_payloads_embedded"] is False
    assert len(map_candidates["corridor_candidates"]) == 1
    assert len(map_candidates["poi_candidates"]) == 1
    assert len(map_candidates["hazard_candidates"]) == 1


def test_scout_260512_candidate_files_match_package():
    fixture = load_scout_260512_pretrip_fixture(FIXTURE_ROOT)
    package = PreTripPackage.model_validate(fixture["package"])

    assert fixture["route_summary"] == package.route_summary.model_dump(mode="json")
    assert fixture["checkpoints"] == [
        candidate.model_dump(mode="json") for candidate in package.checkpoint_candidates
    ]
    assert fixture["segments"] == [
        candidate.model_dump(mode="json") for candidate in package.segment_candidates
    ]


def test_scout_260512_fixture_contains_no_raw_payloads_or_local_raw_files():
    raw_suffixes = {".gpx", ".geojson", ".grd", ".hdr", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".zip"}
    raw_files = [
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in raw_suffixes
    ]
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(FIXTURE_ROOT.rglob("*.json"))
    )

    assert raw_files == []
    for forbidden in [
        "PdrSample/",
        "representative_samples",
        "raw_samples",
        "sensor_records",
        "imu_records",
        "heart_rate_records",
        '"features"',
        '"coordinates"',
        "<trkpt",
    ]:
        assert forbidden not in serialized


def test_scout_260512_fixture_regenerates_deterministically_to_tmp_path(tmp_path):
    regenerated = build_scout_260512_pretrip_fixture(ROOT)
    fixture = load_scout_260512_pretrip_fixture(FIXTURE_ROOT)

    assert regenerated == fixture

    write_scout_260512_pretrip_fixture(ROOT, project_root=tmp_path / "scout_260512_field_regression")
    tmp_fixture = load_scout_260512_pretrip_fixture(tmp_path / "scout_260512_field_regression")

    assert tmp_fixture == fixture


def test_scout_260512_is_not_compiled_into_mountain_calibration_fixture():
    scout_project = load_scout_260512_pretrip_fixture(FIXTURE_ROOT)["project"]
    chilai_project = json.loads(CHILAI_PROJECT.read_text(encoding="utf-8"))
    compiled_outputs = sorted(
        path.relative_to(FIXTURE_ROOT).as_posix()
        for path in FIXTURE_ROOT.rglob("*compiled_mission_graph*")
    )

    assert scout_project["mountain_calibration_project_id"] == "chilai_nanhua_day1"
    assert scout_project["compiled_into_mountain_calibration"] is False
    assert scout_project["compiled_mission_graph_ref"] is None
    assert compiled_outputs == []
    assert chilai_project["project_id"] == "chilai_nanhua_day1"
    assert chilai_project["package_ref"] == "outputs/pretrip_package.json"
