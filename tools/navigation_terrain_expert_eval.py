#!/usr/bin/env python3
"""Deterministic expert-reading eval for Navigation & Terrain Intelligence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from navigation_route_terrain_events import build_route_terrain_events  # noqa: E402
from navigation_terrain_annotations import (  # noqa: E402
    normalize_expert_terrain_annotations,
)
from navigation_terrain_skeleton import (  # noqa: E402
    build_terrain_hierarchy_from_grid,
)


def run_eval() -> dict[str, Any]:
    cases = [
        _annotation_case(),
        _hierarchy_case(),
        _event_case(),
    ]
    passed_count = sum(case["passed"] is True for case in cases)
    return {
        "schema_version": "scout_navigation_terrain_expert_eval.v0",
        "artifact_kind": "navigation_terrain_expert_eval",
        "status": "pass" if passed_count == len(cases) else "fail",
        "case_count": len(cases),
        "passed_case_count": passed_count,
        "cases": cases,
        "boundary": _boundary(),
    }


def _annotation_case() -> dict[str, Any]:
    result = normalize_expert_terrain_annotations(
        {
            "annotation_set_id": "eval-expert-image",
            "source_refs": ["eval-expert-image.jpg"],
            "georeference": {"status": "unreferenced"},
            "annotations": [
                {
                    "id": "ridge",
                    "semantic_role": "main_ridge",
                    "geometry_type": "LineString",
                    "image_coordinates": [[0, 0], [10, 10]],
                    "source_refs": ["eval-expert-image.jpg"],
                },
                {
                    "id": "traverse",
                    "semantic_role": "contour_traverse_band",
                    "geometry_type": "LineString",
                    "image_coordinates": [[0, 8], [10, 8]],
                    "source_refs": ["eval-expert-image.jpg"],
                },
            ],
        }
    )
    kinds = [item.get("terrain_edge_kind") for item in result["annotations"]]
    passed = (
        result["status"] == "semantic_training_only"
        and kinds == ["main_ridge_candidate", "contour_traverse_band"]
        and result["geometry_ground_truth_eligible"] is False
    )
    return {
        "case_id": "expert-semantic-annotation",
        "passed": passed,
        "checks": {
            "unreferenced_is_semantic_only": (
                result["status"] == "semantic_training_only"
            ),
            "traverse_not_promoted_to_ridge": kinds[0] != kinds[1],
            "geometry_truth_rejected": (
                result["geometry_ground_truth_eligible"] is False
            ),
        },
    }


def _hierarchy_case() -> dict[str, Any]:
    result = build_terrain_hierarchy_from_grid(
        _branched_terrain(),
        resolution_m=20,
        source_refs=["eval-synthetic-dem"],
        relief_threshold_m=6,
        minimum_component_cells=3,
    )
    edge_kinds = {item["kind"] for item in result["edges"]}
    node_kinds = {item["kind"] for item in result["nodes"]}
    required_edges = {
        "main_ridge_candidate",
        "spur_ridge_candidate",
        "drainage_trunk",
    }
    passed = (
        required_edges <= edge_kinds
        and "ridge_divide_node" in node_kinds
        and "headwater_node" in node_kinds
        and result["boundary"]["candidate_only"] is True
        and result["boundary"]["runtime_safety_truth"] is False
    )
    return {
        "case_id": "dem-hierarchy-topology",
        "passed": passed,
        "checks": {
            "required_edge_kinds": sorted(required_edges & edge_kinds),
            "ridge_divide_present": "ridge_divide_node" in node_kinds,
            "headwater_present": "headwater_node" in node_kinds,
            "candidate_boundary": (
                result["boundary"]["candidate_only"] is True
                and result["boundary"]["runtime_safety_truth"] is False
            ),
        },
    }


def _event_case() -> dict[str, Any]:
    result = build_route_terrain_events(
        [
            {"x_twd97": 0, "y_twd97": 0, "distance_m": 0},
            {"x_twd97": 100, "y_twd97": 0, "distance_m": 100},
        ],
        {
            "nodes": [
                {
                    "id": "saddle",
                    "kind": "saddle_node",
                    "x_twd97": 80,
                    "y_twd97": 1,
                    "source_refs": ["eval-dem"],
                }
            ],
            "edges": [
                {
                    "id": "ridge",
                    "kind": "main_ridge_candidate",
                    "coordinates_twd97": [[30, -20], [30, 20]],
                    "source_refs": ["eval-dem"],
                },
                {
                    "id": "drainage",
                    "kind": "drainage_trunk",
                    "coordinates_twd97": [[60, -20], [60, 20]],
                    "source_refs": ["eval-dem"],
                },
            ],
            "source_refs": ["eval-dem"],
            "boundary": _boundary(),
        },
        proximity_tolerance_m=5,
    )
    event_types = [item["event_type"] for item in result["events"]]
    distances = [item["route_distance_m"] for item in result["events"]]
    required_prompts = all(
        item["observation_prompt"] and item["wrong_way_cue"] and item["recovery_prompt"]
        for item in result["events"]
    )
    passed = (
        event_types == ["watershed_crossing", "drainage_crossing", "saddle_passage"]
        and distances == sorted(distances)
        and required_prompts
        and all(item["source_refs"] for item in result["events"])
    )
    return {
        "case_id": "ordered-route-terrain-events",
        "passed": passed,
        "checks": {
            "event_types": event_types,
            "distances_m": distances,
            "ordered": distances == sorted(distances),
            "all_prompts_present": required_prompts,
            "all_events_sourced": all(item["source_refs"] for item in result["events"]),
        },
    }


def _branched_terrain() -> dict[tuple[int, int], float]:
    elevations = {}
    for row in range(15):
        for col in range(15):
            ridge = 80.0 - abs(col - 7) * 12.0
            spur = 42.0 - abs(row - 8) * 12.0 if col <= 7 and 4 <= row <= 12 else -100.0
            basin = (
                -28.0 + abs(col - 3) * 9.0 if col < 7 else -25.0 + abs(col - 11) * 9.0
            )
            elevations[(col * 20, row * 20)] = (
                1000.0 + row * 2.0 + max(ridge, spur, basin)
            )
    return elevations


def _boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Run deterministic candidate-only expert terrain reading evals.")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_eval()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
