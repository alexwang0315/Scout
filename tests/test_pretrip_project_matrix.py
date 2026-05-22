import json
from pathlib import Path

from pretrip_project_matrix import build_pretrip_project_matrix


ROOT = Path(__file__).resolve().parents[1]
MATRIX_FIXTURE = ROOT / "tests" / "fixtures" / "pretrip" / "project_matrix.json"


def test_builds_deterministic_project_matrix_fixture():
    first = build_pretrip_project_matrix(ROOT)
    second = build_pretrip_project_matrix(ROOT)

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")
    assert first.to_dict() == json.loads(MATRIX_FIXTURE.read_text(encoding="utf-8"))


def test_matrix_summarizes_primary_mountain_and_field_regression_roles():
    matrix = build_pretrip_project_matrix(ROOT).to_dict()
    projects = {project["project_id"]: project for project in matrix["projects"]}
    chilai = projects["chilai_nanhua_day1"]
    scout = projects["scout_260512_field_regression"]

    assert chilai["role"] == "primary_mountain_calibration"
    assert chilai["refs"]["project"] == (
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
    )
    assert chilai["refs"]["package"] == (
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/pretrip_package.json"
    )
    assert chilai["refs"]["reviewed_package"] == (
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/pretrip_package.reviewed.json"
    )
    assert chilai["candidate_counts"]["checkpoint"] == 110
    assert chilai["candidate_counts"]["segment"] == 109
    assert chilai["candidate_counts"]["retreat_route"] == 1
    assert chilai["release_check_boundary_flags"]["primary_mountain_calibration"] is True
    assert chilai["release_check_boundary_flags"]["field_data_to_fixtures_regression"] is False

    assert scout["role"] == "field_data_to_fixtures_regression"
    assert scout["refs"]["project"] == (
        "tests/fixtures/pretrip/projects/scout_260512_field_regression/project.json"
    )
    assert scout["refs"]["package"] == (
        "tests/fixtures/pretrip/projects/scout_260512_field_regression/outputs/pretrip_package.json"
    )
    assert scout["refs"]["reviewed_package"] is None
    assert scout["candidate_counts"]["checkpoint"] == 6
    assert scout["candidate_counts"]["segment"] == 5
    assert scout["candidate_counts"]["map_poi"] == 1
    assert scout["candidate_counts"]["map_hazard"] == 1
    assert scout["release_check_boundary_flags"]["primary_mountain_calibration"] is False
    assert scout["release_check_boundary_flags"]["field_data_to_fixtures_regression"] is True


def test_matrix_is_reference_only_and_keeps_runtime_boundaries_closed():
    matrix = build_pretrip_project_matrix(ROOT).to_dict()
    serialized = json.dumps(matrix, sort_keys=True)

    for project in matrix["projects"]:
        flags = project["release_check_boundary_flags"]
        assert flags["fixture_only"] is True
        assert flags["phase1_live_runtime_touched"] is False
        assert flags["phase2_bridge_touched"] is False
        assert flags["safety_api_calls_allowed"] is False
        assert flags["raw_payloads_embedded"] is False
        assert project["raw_payload_embedding"] == {
            "embedded": False,
            "policy": "refs_and_counts_only",
        }

    for forbidden in [
        "checkpoint_candidates",
        "segment_candidates",
        "retreat_route_candidates",
        "source_artifacts",
        "coordinates",
        "features",
        "trkpt",
        "PdrSample",
        "sensor_records",
        "imu_records",
    ]:
        assert forbidden not in serialized
