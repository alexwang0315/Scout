from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.historical_dem_gpx_route_inference import (
    InferenceInputError,
    compile_route_hypothesis,
    d8_flow_accumulation,
    enumerate_topology_paths,
    trace_downstream,
    twd67_to_twd97,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "historical_dem_gpx_route_inference.py"


def sample_payload() -> dict:
    return {
        "project_id": "iroko-reconstruction",
        "route_name": "登山口至異祿閣駐在所候選拓撲",
        "coordinate_context": {
            "map_crs": "EPSG:3826",
            "historical_crs": "EPSG:3828",
        },
        "sources": [
            {
                "id": "official-survey",
                "tier": "P0",
                "family": "official_historical_survey",
                "retrieved_at": "2026-07-23",
                "claims": ["station coordinate is TWD67"],
            },
            {
                "id": "public-gpx",
                "tier": "P1",
                "family": "public_completed_trip_gpx",
                "retrieved_at": "2026-07-23",
                "claims": ["trailhead to 1115 m camp is observed"],
            },
            {
                "id": "copernicus-dem",
                "tier": "P0",
                "family": "dem_baseline",
                "retrieved_at": "2026-07-23",
                "claims": ["30 m elevation surface"],
            },
        ],
        "anchors": [
            {
                "id": "station",
                "name": "異祿閣駐在所",
                "x": 272734,
                "y": 2583555,
                "crs": "EPSG:3828",
                "source_refs": ["official-survey"],
            }
        ],
        "nodes": [
            {"id": "A", "source_refs": ["public-gpx"]},
            {"id": "switch", "source_refs": ["copernicus-dem"]},
            {"id": "B", "source_refs": ["official-survey"]},
        ],
        "edges": [
            {
                "id": "H5",
                "from": "A",
                "to": "switch",
                "kind": "gpx_observed",
                "coordinates": [[277200, 2581265], [275100, 2582400]],
                "source_refs": ["public-gpx"],
                "cost": 1,
            },
            {
                "id": "H4",
                "from": "switch",
                "to": "B",
                "kind": "dem_horizontal_band",
                "coordinates": [[275100, 2582400], [273563, 2583348]],
                "source_refs": ["copernicus-dem", "official-survey"],
                "cost": 1,
            },
            {
                "id": "V1",
                "from": "A",
                "to": "switch",
                "kind": "dem_valley_transfer",
                "coordinates": [[277200, 2581265], [275100, 2582400]],
                "source_refs": ["copernicus-dem"],
                "cost": 3,
            },
        ],
        "start_node": "A",
        "end_node": "B",
        "contradictions": [
            {
                "claim": "The historical point cannot be plotted directly on TWD97.",
                "source_refs": ["official-survey"],
                "resolution": "Apply datum review before map matching.",
            }
        ],
    }


def test_twd67_conversion_matches_iroko_station_30m_dem_anchor() -> None:
    easting, northing = twd67_to_twd97(272734, 2583555)

    assert easting == pytest.approx(273562.872, abs=0.01)
    assert northing == pytest.approx(2583348.198, abs=0.01)


def test_d8_accumulation_builds_a_shared_downstream_channel() -> None:
    elevations = [
        [9, 8, 7],
        [8, 6, 5],
        [7, 5, 1],
    ]

    accumulation, downstream = d8_flow_accumulation(elevations)

    assert downstream[0][0] == (1, 1)
    assert accumulation[2][2] == 9
    assert trace_downstream(downstream, (0, 0)) == [(0, 0), (1, 1), (2, 2)]


def test_compiler_preserves_candidate_boundary_and_shared_topology() -> None:
    payload = sample_payload()
    payload["route_option_labels_by_edge_signature"] = {
        "H5|H4": "Observed approach",
        "V1|H4": "DEM transfer candidate",
    }
    result = compile_route_hypothesis(payload)

    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False
    assert result["safe_or_walkable"] == "not_determined"
    assert result["topology"]["route_option_count"] == 2
    assert result["topology"]["shared_edge_ids"] == ["H4"]
    assert result["topology"]["route_option_labels"] == [
        "Observed approach",
        "DEM transfer candidate",
    ]
    assert result["anchors"][0]["converted"]["survey_grade"] is False


def test_compiler_rejects_unsourced_edges() -> None:
    payload = sample_payload()
    payload["edges"][0]["source_refs"] = []

    with pytest.raises(InferenceInputError, match="must have source_refs"):
        compile_route_hypothesis(payload)


def test_compiler_reports_missing_evidence_families() -> None:
    payload = sample_payload()
    payload["sources"] = [payload["sources"][1]]
    payload["anchors"] = []
    payload["nodes"][1]["source_refs"] = ["public-gpx"]
    payload["nodes"][2]["source_refs"] = ["public-gpx"]
    payload["edges"] = [payload["edges"][0]]
    payload["edges"][0]["to"] = "B"
    payload["contradictions"] = []

    result = compile_route_hypothesis(payload)

    assert "No P0 official or baseline source is attached." in result["evidence_gaps"]
    assert "No DEM-derived terrain edge is attached." in result["evidence_gaps"]


def test_compiler_measures_epsg4326_geometry_in_metres() -> None:
    payload = sample_payload()
    payload["coordinate_context"] = {"geometry_crs": "EPSG:4326"}
    payload["edges"][0]["coordinates"] = [
        [121.0, 24.0],
        [121.01, 24.0],
    ]

    result = compile_route_hypothesis(payload)

    measured = result["topology"]["edges"][0]
    assert measured["length_m"] == pytest.approx(1016.0, abs=5)
    assert measured["max_adjacent_spacing_m"] == pytest.approx(1016.0, abs=5)


def test_cli_compiles_json_package(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "compiled.json"
    input_path.write_text(json.dumps(sample_payload()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "compile",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert str(output_path) in completed.stdout
    assert result["status"] == "candidate_route_hypothesis_compiled"
    assert result["topology"]["lowest_cost_option_edge_ids"] == ["H5", "H4"]


def test_enumeration_recombines_shared_edges_instead_of_flat_route_copies() -> None:
    edges = sample_payload()["edges"]

    paths = enumerate_topology_paths(edges, "A", "B")

    assert paths == [["H5", "H4"], ["V1", "H4"]]
