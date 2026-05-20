import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_runtime_handoff_metadata
from pretrip_runtime_handoff_metadata import (
    PreTripRuntimeHandoffMetadata,
    build_chilai_runtime_handoff_metadata,
    load_runtime_handoff_metadata,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = FIXTURE_ROOT / "outputs" / "runtime_handoff_metadata.candidate.json"


def test_builds_deterministic_candidate_runtime_handoff_metadata():
    first = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT)
    second = build_chilai_runtime_handoff_metadata(ROOT)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")

    payload = first.model_dump(mode="json")
    assert payload["manifest_id"] == "runtime_handoff_metadata.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_runtime_handoff_metadata"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "candidate_metadata_only"
    assert payload["plan_version_id"] == "pretrip.chilai_nanhua_day1.v0:0.1.0"
    assert payload["package"]["package_id"] == "pretrip.chilai_nanhua_day1.v0"
    assert payload["package"]["version"] == "0.1.0"
    assert payload["package"]["status"] == "reviewed"
    assert payload["counts"] == {
        "readiness_ref_count": 3,
        "route_ref_count": 4,
        "route_source_count": 1,
        "runtime_write_count": 0,
        "safety_call_count": 0,
        "bridge_mutation_count": 0,
    }


def test_runtime_handoff_metadata_refs_reviewed_graph_readiness_and_route_sources():
    manifest = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT).model_dump(mode="json")

    graph_ref = manifest["reviewed_mission_graph_ref"]
    assert graph_ref["ref_key"] == "compiled_mission_graph_reviewed_ref"
    assert graph_ref["ref"] == "outputs/compiled_mission_graph.reviewed.json"
    assert graph_ref["summary"] == {
        "mission_id": "mission.chilai_nanhua_day1.0.1.0",
        "name": "奇萊南華-能高越嶺步道Day1",
        "checkpoint_count": 11,
        "segment_count": 10,
        "diversion_point_count": 1,
        "route_source": "artifact:gpx:chilai_nanhua_day1",
    }

    assert [ref["ref_key"] for ref in manifest["readiness_refs"]] == [
        "readiness_report_ref",
        "plan_validation_candidates_ref",
        "poi_readiness_candidates_ref",
    ]
    assert manifest["readiness_refs"][0]["summary"] == {
        "status": "ready",
        "finding_count": 0,
    }
    assert manifest["readiness_refs"][1]["summary"]["hard_readiness_status"] == "ready"
    assert (
        manifest["readiness_refs"][1]["summary"]["hard_readiness_mutation_allowed"]
        is False
    )

    assert [ref["ref_key"] for ref in manifest["route_refs"]] == [
        "route_summary_ref",
        "route_comparison_ref",
        "planning_references_ref",
        "route_guide_timing_ref",
    ]
    assert manifest["route_refs"][0]["summary"]["artifact_id"] == (
        "artifact:gpx:chilai_nanhua_day1"
    )
    assert manifest["route_refs"][0]["summary"]["point_count"] == 2211
    assert manifest["route_source_refs"] == [
        {
            "artifact_id": "artifact:gpx:chilai_nanhua_day1",
            "kind": "gpx",
            "sha256": "3c1f4843ecea5cb2fc85f92934d3d1a220738c900576e4976d4c09975673956c",
            "media_type": "application/gpx+xml",
            "size_bytes": 275392,
            "source_ref": "artifact:gpx:chilai_nanhua_day1",
        }
    ]

    for group in (
        [
            manifest["package"]["package_ref"],
            manifest["package"]["reviewed_package_ref"],
            manifest["reviewed_mission_graph_ref"],
        ]
        + manifest["readiness_refs"]
        + manifest["route_refs"]
    ):
        assert group["exists"] is True
        assert len(group["sha256"]) == 64
        assert (FIXTURE_ROOT / group["ref"]).exists()


def test_runtime_handoff_metadata_is_candidate_only_and_has_no_runtime_side_effects():
    before = _fixture_hashes(FIXTURE_ROOT)
    manifest = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT)
    after = _fixture_hashes(FIXTURE_ROOT)

    assert after == before
    assert manifest.boundary.model_dump(mode="json") == {
        "candidate_metadata_only": True,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "bridge_mutation_allowed": False,
        "final_runtime_write_allowed": False,
        "live_runtime_read_allowed": False,
        "incident_package_imported": False,
        "phase2_writeback_allowed": False,
        "external_api_calls_made": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Candidate metadata handoff only; no Phase 1 runtime state is mutated.",
            "No safety endpoint is called and no Phase 3 bridge behavior is changed.",
            "No final runtime manifest or MissionGraph write is performed by this builder.",
        ],
    }

    serialized = manifest.to_json()
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
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
    ]:
        assert fragment not in serialized

    source = inspect.getsource(pretrip_runtime_handoff_metadata)
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "os.environ" not in source
    assert "requests." not in source
    assert "httpx." not in source


def test_runtime_handoff_metadata_fixture_matches_builder_output():
    fixture_payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture = load_runtime_handoff_metadata(MANIFEST_PATH)
    regenerated = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")
    PreTripRuntimeHandoffMetadata.model_validate(fixture_payload)


def test_runtime_handoff_metadata_rejects_runtime_write_claims():
    payload = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT).model_dump(mode="json")
    payload["boundary"]["final_runtime_write_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripRuntimeHandoffMetadata.model_validate(payload)

    payload = build_chilai_runtime_handoff_metadata(FIXTURE_ROOT).model_dump(mode="json")
    payload["integration_notes"].append("POST /safety/incidents would be called")

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        PreTripRuntimeHandoffMetadata.model_validate(payload)


def _fixture_hashes(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
