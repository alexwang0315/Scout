from __future__ import annotations

import pytest
from pydantic import ValidationError

from spatial_imprint_models import SpatialImprint, SpatialImprintSet


def test_spatial_imprint_defaults_keep_runtime_boundaries_closed() -> None:
    imprint = _imprint()

    assert imprint.boundary.advisory_cue is True
    assert imprint.boundary.runtime_safety_truth is False
    assert imprint.boundary.phase1_safety_mutation_allowed is False
    assert imprint.boundary.live_safety_api_calls_allowed is False
    assert imprint.boundary.model_output_is_trigger_truth is False
    assert imprint.boundary.remote_outbound_send_allowed is False
    assert imprint.boundary.hardware_control_allowed is False
    assert imprint.dedupe_key == "collapse.wall.017"


def test_spatial_imprint_rejects_boundary_mutation() -> None:
    payload = _imprint().model_dump(mode="json")
    payload["boundary"]["runtime_safety_truth"] = True

    with pytest.raises(ValidationError) as exc_info:
        SpatialImprint.model_validate(payload)

    assert "runtime_safety_truth" in str(exc_info.value)


def test_spatial_imprint_set_accepts_trip_local_imprints() -> None:
    imprint_set = SpatialImprintSet(trip_id="chilai_nanhua_day1", imprints=[_imprint()])

    assert imprint_set.artifact_kind == "spatial_imprint_set"
    assert imprint_set.imprints[0].payload.payload_type == "voice_cue"
    assert imprint_set.boundary.phase1_safety_mutation_allowed is False


def _imprint() -> SpatialImprint:
    return SpatialImprint.model_validate(
        {
            "imprint_id": "spatial_imprint.chilai.00042",
            "label": "前方大崩壁",
            "kind": "route_warning",
            "severity": "warning",
            "planting_source": "pretrip_reviewed",
            "created_at": "2026-05-26T12:00:00+08:00",
            "created_by": {"actor_type": "operator", "actor_ref": "trip_leader"},
            "anchor": {
                "anchor_type": "route_progress",
                "route_id": "chilai_nanhua_day1",
                "segment_ref": "segment_017",
                "cp_ref": "cp_018",
                "distance_m": 8420.0,
                "trigger_before_m": 50.0,
                "coordinate": {"lat": 24.0301, "lon": 121.2842, "altitude_m": 2890.0},
            },
            "trigger": {
                "operator": "all",
                "predicates": [
                    {
                        "type": "route_progress_window",
                        "start_distance_m": 8370.0,
                        "end_distance_m": 8420.0,
                    }
                ],
            },
            "payload": {
                "payload_type": "voice_cue",
                "text_zh": "前方約五十公尺有大崩壁，請靠內側通行。",
                "voice_priority": "warning",
                "voice_category": "environment",
            },
            "audience": {
                "scope": "registered_trip_clients",
                "client_group_refs": ["current_trip_party"],
            },
            "trigger_policy": {"dedupe_key": "collapse.wall.017"},
        }
    )
