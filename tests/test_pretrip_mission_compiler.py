import json
from pathlib import Path

import pytest

from mission_models import MissionGraph
from pretrip_mission_compiler import compile_pretrip_mission_graph


ROOT = Path(__file__).resolve().parents[1]
CHILAI_PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "pretrip_package.json"
)
CHILAI_COMPILED_CANDIDATE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "compiled_mission_graph.candidate.json"
)
CHILAI_REVIEWED_PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "pretrip_package.reviewed.json"
)
CHILAI_COMPILED_REVIEWED = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "compiled_mission_graph.reviewed.json"
)


def test_compile_chilai_candidate_fixture_when_unreviewed_is_explicitly_allowed():
    package = json.loads(CHILAI_PACKAGE.read_text())

    graph = compile_pretrip_mission_graph(package, allow_unreviewed=True)

    validated = MissionGraph.model_validate(graph.model_dump(mode="json"))
    assert validated.mission_id == "mission.chilai_nanhua_day1.0.1.0"
    assert validated.name == package["route_summary"]["route_name"]
    assert validated.route_source == package["source_artifacts"][0]["uri"]
    assert len(validated.checkpoints) == len(package["checkpoint_candidates"])
    assert len(validated.segments) == len(package["segment_candidates"])
    assert validated.control_zones[0].zone_id == "zone_pretrip_default"
    assert validated.recording_policies[0].policy_id == "policy_pretrip_conservative"
    assert all(segment.requirement.requires_daylight for segment in validated.segments)


def test_default_compile_rejects_unreviewed_chilai_candidates():
    package = json.loads(CHILAI_PACKAGE.read_text())

    with pytest.raises(ValueError, match="allow_unreviewed=True"):
        compile_pretrip_mission_graph(package)


def test_chilai_compiled_candidate_fixture_validates_as_mission_graph():
    payload = json.loads(CHILAI_COMPILED_CANDIDATE.read_text())
    graph = MissionGraph.model_validate(payload)

    assert graph.mission_id == "mission.chilai_nanhua_day1.0.1.0"
    assert len(graph.checkpoints) == 11
    assert len(graph.segments) == 10
    assert [point.diversion_id for point in graph.diversion_points] == [
        "retreat.chilai_nanhua_day1.return_to_entry"
    ]
    assert any(segment.requirement.retreat_available for segment in graph.segments)


def test_chilai_reviewed_package_compiles_without_allow_unreviewed():
    package = json.loads(CHILAI_REVIEWED_PACKAGE.read_text())

    graph = compile_pretrip_mission_graph(package)
    fixture_graph = MissionGraph.model_validate(json.loads(CHILAI_COMPILED_REVIEWED.read_text()))

    assert package["status"] == "reviewed"
    assert graph.model_dump(mode="json") == fixture_graph.model_dump(mode="json")
    assert all(candidate["review_state"] == "accepted" for candidate in package["checkpoint_candidates"])
    assert all(candidate["review_state"] == "accepted" for candidate in package["segment_candidates"])


def test_compile_small_reviewed_package_with_diversion_and_retreat_candidates():
    package = _small_package()

    graph = compile_pretrip_mission_graph(
        package,
        diversion_points=[
            {
                "candidate_id": "div.water.001",
                "label": "Trailside water source",
                "review_state": "accepted",
                "diversion_type": "water",
                "lat": 24.001,
                "lon": 121.001,
            }
        ],
    )

    assert graph.route_source == "/tmp/synthetic-route.gpx"
    assert [checkpoint.checkpoint_id for checkpoint in graph.checkpoints] == [
        "cp.start",
        "cp.finish",
    ]
    assert [segment.segment_id for segment in graph.segments] == ["seg.001"]
    assert graph.segments[0].requirement.retreat_available is True
    assert [point.diversion_id for point in graph.diversion_points] == [
        "div.water.001",
        "retreat.001",
    ]
    MissionGraph.model_validate(graph.model_dump(mode="json"))


def _small_package() -> dict:
    return {
        "package_id": "pretrip.synthetic.v0",
        "project_id": "synthetic",
        "version": "v0",
        "status": "reviewed",
        "route_summary": {
            "artifact_id": "artifact.gpx.synthetic",
            "route_name": "Synthetic reviewed route",
            "point_count": 2,
            "distance_m": 100.0,
            "bbox_wgs84": {
                "min_lat": 24.0,
                "min_lon": 121.0,
                "max_lat": 24.001,
                "max_lon": 121.001,
            },
        },
        "source_artifacts": [
            {
                "artifact_id": "artifact.gpx.synthetic",
                "kind": "gpx",
                "uri": "/tmp/synthetic-route.gpx",
                "media_type": "application/gpx+xml",
                "provenance": {
                    "source_ref": "artifact.gpx.synthetic",
                    "source_kind": "gpx",
                    "uri": "/tmp/synthetic-route.gpx",
                    "method": "pytest",
                },
            }
        ],
        "checkpoint_candidates": [
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "review_state": "accepted",
                "confidence": "high",
                "lat": 24.0,
                "lon": 121.0,
                "route_point_index": 0,
                "checkpoint_type": "start",
                "source_refs": ["artifact.gpx.synthetic"],
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "review_state": "accepted",
                "confidence": "high",
                "lat": 24.001,
                "lon": 121.001,
                "route_point_index": 1,
                "checkpoint_type": "finish",
                "source_refs": ["artifact.gpx.synthetic"],
            },
        ],
        "segment_candidates": [
            {
                "candidate_id": "seg.001",
                "label": "Segment 001",
                "review_state": "accepted",
                "confidence": "high",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.finish",
                "route_point_start_index": 0,
                "route_point_end_index": 1,
                "distance_m": 100.0,
                "elevation_gain_m": 20.0,
                "elevation_loss_m": 0.0,
                "source_refs": ["artifact.gpx.synthetic"],
            }
        ],
        "retreat_route_candidates": [
            {
                "candidate_id": "retreat.001",
                "label": "Return to start",
                "review_state": "accepted",
                "confidence": "medium",
                "entry_checkpoint_candidate_id": "cp.start",
                "trigger_checkpoint_candidate_id": "cp.finish",
                "distance_m": 100.0,
                "expected_use": "retreat",
            }
        ],
    }
