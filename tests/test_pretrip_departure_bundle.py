import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from phase4_pretrip_release_check import build_release_check
from pretrip_departure_bundle import (
    PreTripDepartureBundleManifest,
    build_chilai_departure_bundle,
    load_departure_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"
BUNDLE_PATH = FIXTURE_ROOT / "outputs" / "departure_bundle_manifest.json"


def test_builds_deterministic_departure_bundle_manifest():
    first = build_chilai_departure_bundle(FIXTURE_ROOT)
    second = build_chilai_departure_bundle(ROOT)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")

    payload = first.model_dump(mode="json")
    assert payload["bundle_id"] == "departure_bundle.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_departure_bundle_manifest"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "frozen_candidate"
    assert payload["package"] == {
        "package_id": "pretrip.chilai_nanhua_day1.v0",
        "project_id": "chilai_nanhua_day1",
        "version": "0.1.0",
        "status": "reviewed",
        "reviewed_package_ref": "outputs/pretrip_package.reviewed.json",
        "source_artifact_count": 2,
        "checkpoint_candidate_count": 11,
        "segment_candidate_count": 10,
        "retreat_route_candidate_count": 1,
    }
    assert payload["counts"] == {
        "required_ref_count": 24,
        "source_checksum_count": 2,
        "readiness_finding_count": 0,
        "remote_conservative_note_count": 3,
        "resource_warning_candidate_count": 3,
        "resource_blocker_candidate_count": 0,
        "route_ref_count": 7,
        "terrain_ref_count": 3,
        "audit_ref_count": 6,
    }


def test_departure_bundle_preserves_required_refs_and_checksums():
    bundle = build_chilai_departure_bundle(FIXTURE_ROOT).model_dump(mode="json")

    assert bundle["reviewed_mission_graph"]["ref_key"] == (
        "compiled_mission_graph_reviewed_ref"
    )
    assert bundle["reviewed_mission_graph"]["ref"] == (
        "outputs/compiled_mission_graph.reviewed.json"
    )
    assert bundle["reviewed_mission_graph"]["sha256"] == (
        "c2b42fee4feffbf7bca18d0262cc38a07b629df83e9dc8b4ac166bdf10a3015e"
    )
    assert bundle["reviewed_mission_graph"]["summary"] == {
        "mission_id": "mission.chilai_nanhua_day1.0.1.0",
        "name": "奇萊南華-能高越嶺步道Day1",
        "checkpoint_count": 11,
        "segment_count": 10,
        "diversion_point_count": 1,
    }
    assert [ref["ref_key"] for ref in bundle["readiness_refs"]] == [
        "readiness_report_ref",
        "plan_validation_candidates_ref",
        "poi_readiness_candidates_ref",
        "segment_policy_candidates_ref",
        "weather_daylight_evidence_ref",
    ]
    assert [ref["ref_key"] for ref in bundle["route_refs"]] == [
        "route_summary_ref",
        "route_comparison_ref",
        "checkpoint_candidates_ref",
        "segment_candidates_ref",
        "retreat_routes_ref",
        "map_context_ref",
        "map_candidates_ref",
    ]
    assert [ref["ref_key"] for ref in bundle["terrain_refs"]] == [
        "dtm_coverage_summary_ref",
        "segment_dtm_coverage_ref",
        "contour_interpretation_candidates_ref",
    ]
    assert [ref["ref_key"] for ref in bundle["audit_refs"]] == [
        "human_reviews_ref",
        "review_draft_log_ref",
        "planning_skill_audit_ref",
        "runtime_audit_manifest_ref",
        "after_action_next_plan_candidates_ref",
        "brain_seed_nodes_ref",
    ]
    review_draft_ref = next(
        ref for ref in bundle["audit_refs"] if ref["ref_key"] == "review_draft_log_ref"
    )
    assert review_draft_ref["ref"] == "reviews/review_draft_log.json"
    assert review_draft_ref["status"] == "draft_only"
    assert review_draft_ref["summary"]["draft_only"] is True
    assert review_draft_ref["summary"]["decisions_recorded"] is False
    assert review_draft_ref["summary"]["mutation_action_count"] == 0
    assert review_draft_ref["summary"]["runtime_mutation_allowed"] is False
    assert bundle["artifact_manifest"]["missing_ref_count"] == 0
    assert bundle["artifact_manifest"]["project_artifact_count"] == 42
    assert bundle["artifact_manifest"]["source_artifact_count"] == 2
    assert bundle["artifact_manifest"]["total_artifact_count"] == 44
    assert bundle["artifact_manifest"]["source_checksum_summaries"] == [
        {
            "artifact_kind": "gpx",
            "artifact_id": "artifact:gpx:chilai_nanhua_day1",
            "sha256": "3c1f4843ecea5cb2fc85f92934d3d1a220738c900576e4976d4c09975673956c",
            "media_type": "application/gpx+xml",
            "size_bytes": 275392,
        },
        {
            "artifact_kind": "photo",
            "artifact_id": "artifact:photo:g11_hiking",
            "sha256": "ff28bf2fd66c6f8a63e759800fcdb8363862832ebe7b87dc900e849f1c7a058d",
            "media_type": "image/jpeg",
            "size_bytes": 209877,
        },
    ]

    for group in (
        [bundle["reviewed_mission_graph"], bundle["remote_summary"], bundle["resource_plan"]]
        + bundle["readiness_refs"]
        + bundle["route_refs"]
        + bundle["terrain_refs"]
        + bundle["audit_refs"]
    ):
        assert group["exists"] is True
        assert len(group["sha256"]) == 64
        assert (FIXTURE_ROOT / group["ref"]).exists()


def test_departure_bundle_excludes_raw_payloads_and_runtime_mutation():
    before = _fixture_hashes(FIXTURE_ROOT)
    bundle = build_chilai_departure_bundle(FIXTURE_ROOT)
    after = _fixture_hashes(FIXTURE_ROOT)

    assert after == before
    assert bundle.boundary.not_departure_approval is True
    assert bundle.boundary.human_review_required_before_departure is True
    assert bundle.boundary.phase1_runtime_mutation_allowed is False
    assert bundle.boundary.phase2_writeback_allowed is False
    assert bundle.boundary.external_api_calls_made is False
    assert bundle.boundary.raw_payloads_embedded is False

    bundle_json = bundle.to_json()
    forbidden_fragments = [
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in bundle_json

    payload = bundle.model_dump(mode="json")
    payload["reviewed_mission_graph"]["summary"]["route_source"] = "raw_route.gpx"
    with pytest.raises(ValidationError, match="forbidden raw payload fragment"):
        PreTripDepartureBundleManifest.model_validate(payload)


def test_departure_bundle_fixture_matches_builder_and_release_gate_stays_compatible():
    expected = build_chilai_departure_bundle(FIXTURE_ROOT)
    fixture = load_departure_bundle(BUNDLE_PATH)

    assert fixture == expected
    assert json.loads(PROJECT_PATH.read_text())["departure_bundle_manifest_ref"] == (
        "outputs/departure_bundle_manifest.json"
    )

    summary = build_release_check(ROOT)
    assert summary["ok"]
    assert summary["failed_checks"] == []
    assert summary["checks"]["departure_bundle_manifest"]["status"] == "frozen_candidate"
    assert summary["checks"]["departure_bundle_manifest"]["required_ref_count"] == 24
    assert summary["checks"]["departure_bundle_manifest"]["audit_ref_count"] == 6
    assert summary["checks"]["departure_bundle_manifest"]["review_draft_log_ref_count"] == 1
    assert summary["checks"]["departure_bundle_manifest"]["review_draft_log_statuses"] == [
        "draft_only"
    ]
    assert summary["checks"]["departure_bundle_manifest"]["not_departure_approval"] is True
    assert summary["checks"]["departure_bundle_manifest"]["phase1_runtime_mutation_allowed"] is False


def test_departure_bundle_rejects_missing_required_refs(tmp_path):
    project_root = _copy_project_fixture(tmp_path)
    (project_root / "outputs" / "resource_plan.json").unlink()

    with pytest.raises(ValueError, match="complete artifact manifest"):
        build_chilai_departure_bundle(project_root)


def _copy_project_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _fixture_hashes(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
