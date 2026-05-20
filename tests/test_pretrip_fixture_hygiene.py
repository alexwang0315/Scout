import json
from pathlib import Path

from pretrip_fixture_hygiene import build_pretrip_fixture_hygiene_manifest
from pretrip_fixture_hygiene import find_repo_fixture_workspace_output_artifacts


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FIXTURE = ROOT / "tests" / "fixtures" / "pretrip" / "fixture_hygiene_manifest.json"


def test_builds_deterministic_hygiene_manifest_fixture():
    first = build_pretrip_fixture_hygiene_manifest(ROOT)
    second = build_pretrip_fixture_hygiene_manifest(ROOT)

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")
    assert first.to_dict() == json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))


def test_current_pretrip_fixture_tree_has_no_raw_payload_hygiene_issues():
    manifest = build_pretrip_fixture_hygiene_manifest(ROOT).to_dict()

    assert manifest["phase"] == "phase_4_pretrip_fixture_hygiene"
    assert manifest["fixture_root"] == "tests/fixtures/pretrip"
    assert manifest["policy"]["fixture_only"] is True
    assert manifest["policy"]["no_ui_or_runtime"] is True
    assert manifest["policy"]["raw_payload_policy"] == "refs_and_counts_only"
    assert manifest["policy"]["raw_dtm_gpx_jpg_repo_fixture_policy"] == "forbidden"
    assert manifest["counts"]["files_scanned"] > 0
    assert manifest["counts"]["json_files_scanned"] == manifest["counts"]["files_scanned"]
    assert manifest["counts"]["raw_suffix_files"] == 0
    assert manifest["counts"]["raw_route_suffix_files"] == 0
    assert manifest["counts"]["oversized_files"] == 0
    assert manifest["counts"]["json_parse_errors"] == 0
    assert manifest["counts"]["forbidden_fragments"] == 0
    assert manifest["counts"]["total_issues"] == 0
    assert manifest["issues"] == {
        "forbidden_fragments": [],
        "json_parse_errors": [],
        "oversized_files": [],
        "raw_suffix_files": [],
    }
    assert find_repo_fixture_workspace_output_artifacts(ROOT) == []


def test_hygiene_builder_flags_raw_files_bad_json_and_embedded_payload_fragments(tmp_path):
    fixture_root = tmp_path / "tests" / "fixtures" / "pretrip"
    fixture_root.mkdir(parents=True)
    (fixture_root / "route.gpx").write_text("<gpx><trkpt /></gpx>", encoding="utf-8")
    (fixture_root / "bad.json").write_text("{", encoding="utf-8")
    (fixture_root / "oversized.json").write_text(
        json.dumps({"summary": "x" * 25}),
        encoding="utf-8",
    )
    (fixture_root / "embedded.json").write_text(
        json.dumps(
            {
                "PdrSample": "local-only raw capture",
                "raw_samples": [],
                "features": [],
                "coordinates": [],
                "trkpt": [],
            }
        ),
        encoding="utf-8",
    )

    manifest = build_pretrip_fixture_hygiene_manifest(
        tmp_path,
        max_file_bytes=20,
    ).to_dict()

    assert manifest["counts"]["files_scanned"] == 4
    assert manifest["counts"]["json_files_scanned"] == 3
    assert manifest["counts"]["raw_suffix_files"] == 1
    assert manifest["counts"]["raw_route_suffix_files"] == 1
    assert manifest["counts"]["oversized_files"] == 2
    assert manifest["counts"]["json_parse_errors"] == 1
    assert manifest["counts"]["forbidden_fragments"] == 5
    assert manifest["counts"]["total_issues"] == 9

    assert manifest["issues"]["raw_suffix_files"][0]["path"] == (
        "tests/fixtures/pretrip/route.gpx"
    )
    assert manifest["issues"]["json_parse_errors"][0]["path"] == (
        "tests/fixtures/pretrip/bad.json"
    )
    forbidden = {
        issue["fragment"] for issue in manifest["issues"]["forbidden_fragments"]
    }
    assert forbidden == {"PdrSample", "coordinates", "features", "raw_samples", "trkpt"}


def test_hygiene_flags_workspace_only_outputs_under_repo_fixtures(tmp_path):
    fixture_root = (
        tmp_path
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
        / "outputs"
    )
    fixture_root.mkdir(parents=True)
    for name in [
        "expert_contribution_apply_plan.json",
        "expert_contribution_workspace_apply_result.json",
        "route_note_reviewed_assumptions.json",
    ]:
        (fixture_root / name).write_text("{}", encoding="utf-8")

    assert find_repo_fixture_workspace_output_artifacts(tmp_path) == [
        (
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/"
            "expert_contribution_apply_plan.json"
        ),
        (
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/"
            "expert_contribution_workspace_apply_result.json"
        ),
        (
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/"
            "route_note_reviewed_assumptions.json"
        ),
    ]
