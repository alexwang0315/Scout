from __future__ import annotations

from navigation_route_terrain_events import build_route_terrain_events


def test_route_terrain_join_emits_ordered_navigation_events() -> None:
    route = [
        {"x_twd97": 0, "y_twd97": 0, "distance_m": 0, "elevation_m": 1000},
        {"x_twd97": 100, "y_twd97": 0, "distance_m": 100, "elevation_m": 980},
    ]
    hierarchy = {
        "schema_version": "scout_navigation_terrain_hierarchy.v0",
        "nodes": [
            {
                "id": "saddle-1",
                "kind": "saddle_node",
                "x_twd97": 80,
                "y_twd97": 2,
                "source_refs": ["dem"],
            }
        ],
        "edges": [
            {
                "id": "ridge-main-1",
                "kind": "main_ridge_candidate",
                "coordinates_twd97": [[30, -20], [30, 20]],
                "source_refs": ["dem"],
            },
            {
                "id": "drainage-1",
                "kind": "drainage_trunk",
                "coordinates_twd97": [[60, -20], [60, 20]],
                "source_refs": ["dem"],
            },
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }

    result = build_route_terrain_events(
        route,
        hierarchy,
        proximity_tolerance_m=8,
    )

    assert result["status"] == "candidate_events"
    assert result["schema_version"] == "scout_navigation_route_terrain_events.v1"
    assert [event["event_type"] for event in result["events"]] == [
        "watershed_crossing",
        "drainage_crossing",
        "saddle_passage",
    ]
    assert [event["sequence"] for event in result["events"]] == [1, 2, 3]
    assert [event["route_distance_m"] for event in result["events"]] == [
        30.0,
        60.0,
        80.0,
    ]
    assert all(event["wrong_way_cue"] for event in result["events"])
    assert all(event["source_refs"] == ["dem"] for event in result["events"])
    assert all(
        event["output_role"] == "shadow_event_candidate"
        and event["gate_mode"] == "shadow_only"
        and event["operational_authority"] is False
        and event["effect_scope"] == "none"
        for event in result["events"]
    )
    assert result["validation_state"] == "blocked_pending_reference"
    assert result["gate_mode"] == "shadow_only"
    assert result["operational_authority"] is False
    assert result["blocked_reason"] == "geometry_reference_validation_missing"
    assert result["lineage"]["source_hierarchy_schema_version"] == (
        "scout_navigation_terrain_hierarchy.v0"
    )
    assert result["lineage"]["event_semantics"] == (
        "shadow_route_terrain_event_semantics.v1"
    )
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["shadow_only"] is True
    assert result["boundary"]["effect_scope"] == "none"


def test_route_terrain_join_classifies_aligned_ridge_as_transition() -> None:
    route = [
        {"x_twd97": 0, "y_twd97": 0},
        {"x_twd97": 100, "y_twd97": 0},
    ]
    hierarchy = {
        "nodes": [],
        "edges": [
            {
                "id": "spur-1",
                "kind": "spur_ridge_candidate",
                "coordinates_twd97": [[20, 2], [70, 2]],
                "source_refs": ["dem"],
            }
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }

    result = build_route_terrain_events(
        route,
        hierarchy,
        proximity_tolerance_m=5,
    )

    assert len(result["events"]) == 1
    assert result["events"][0]["event_type"] == "route_terrain_transition"
    assert result["events"][0]["terrain_relation"] == "aligned_with_spur_ridge"


def test_route_terrain_join_rejects_non_candidate_hierarchy() -> None:
    hierarchy = {
        "nodes": [],
        "edges": [],
        "boundary": {
            "candidate_only": False,
            "runtime_safety_truth": True,
        },
    }

    result = build_route_terrain_events(
        [{"x_twd97": 0, "y_twd97": 0}, {"x_twd97": 1, "y_twd97": 0}],
        hierarchy,
    )

    assert result["status"] == "rejected_boundary"
    assert result["events"] == []
    assert result["gate_mode"] == "shadow_only"
    assert result["operational_authority"] is False
