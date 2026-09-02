from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from terrain_route_host_parity import (
    TerrainRouteParityError,
    compare_terrain_route_hosts,
)


def _receipt(host: str, architecture: str) -> dict:
    return {
        "schema_version": "scout_terrain_route_execution_receipt.v0_1",
        "status": "completed",
        "execution_host": host,
        "execution_architecture": architecture,
        "workflow_id": "terrain_route_hypothesis.v1",
        "source_dem_sha256s": ["a" * 64],
        "terrain_parent_manifest_sha256": "b" * 64,
        "input_contract_sha256": "c" * 64,
        "authority": "candidate_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
    }


def _hypothesis(grass_version: str, coordinate_offset: float = 0.0) -> dict:
    strategies = (
        "drainage_averse",
        "balanced",
        "terrain_only_baseline",
    )
    hypotheses = []
    for index, strategy in enumerate(strategies, start=1):
        hypotheses.append(
            {
                "id": f"R{index}",
                "strategy": strategy,
                "authority": "candidate_only",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "safe_or_walkable": "not_determined",
                "best_path": {
                    "coordinates": [
                        [121.0 + coordinate_offset, 23.0],
                        [121.01 + coordinate_offset, 23.01],
                    ]
                },
                "metrics": {
                    "relative_cost": 100.0 + index,
                    "distance_m": 1500.0,
                    "elevation_gain_m": 200.0,
                    "elevation_loss_m": 50.0,
                    "max_slope_degrees": 28.0,
                    "median_slope_degrees": 13.0,
                    "high_cost_fraction": 0.0,
                    "drainage_pressure_fraction": 0.01,
                },
                "corridor": (
                    {
                        "bands": [
                            {
                                "name": "top_5_percent_corridor",
                                "percentile": 5.0,
                                "cell_count": 1000,
                                "max_relative_corridor_cost": 25.0,
                            },
                            {
                                "name": "top_10_percent_corridor",
                                "percentile": 10.0,
                                "cell_count": 2000,
                                "max_relative_corridor_cost": 75.0,
                            },
                            {
                                "name": "top_20_percent_corridor",
                                "percentile": 20.0,
                                "cell_count": 4000,
                                "max_relative_corridor_cost": 200.0,
                            },
                        ]
                    }
                    if index == 1
                    else None
                ),
                "provenance": {
                    "dem_sha256": "a" * 64,
                    "qgis_version": "3.44.13-Solothurn",
                    "grass_version": grass_version,
                    "algorithm_version": "terrain_route_hypothesis.v0_3",
                    "cost_model_version": "terrain_routing_cost.v0_2",
                },
            }
        )
    return {
        "status": "completed",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "hypotheses": hypotheses,
    }


def test_host_parity_accepts_raster_precision_with_declared_engine_variance() -> None:
    left = _hypothesis("8.5.0")
    right = _hypothesis("8.4.1", coordinate_offset=1e-12)
    right["hypotheses"][0]["corridor"]["bands"][0]["cell_count"] = 990
    right["hypotheses"][0]["corridor"]["bands"][0][
        "max_relative_corridor_cost"
    ] = 24.5

    report = compare_terrain_route_hosts(
        left_receipt=_receipt("mac", "x86_64"),
        right_receipt=_receipt("scout", "aarch64"),
        left_hypothesis=left,
        right_hypothesis=right,
    )

    assert report["status"] == "passed_with_engine_variance"
    assert report["cross_host_execution_proven"] is True
    assert report["engine_versions_exact"] is False
    assert all(item["within_tolerance"] for item in report["route_comparisons"])
    assert report["corridor_comparison"]["within_tolerance"] is True
    assert report["authority"] == "candidate_only"
    assert report["runtime_safety_truth"] is False
    assert report["safe_or_walkable"] == "not_determined"


def test_host_parity_fails_closed_for_different_input_contract() -> None:
    right_receipt = _receipt("scout", "aarch64")
    right_receipt["input_contract_sha256"] = "d" * 64

    with pytest.raises(TerrainRouteParityError, match="input contract"):
        compare_terrain_route_hosts(
            left_receipt=_receipt("mac", "x86_64"),
            right_receipt=right_receipt,
            left_hypothesis=_hypothesis("8.5.0"),
            right_hypothesis=_hypothesis("8.4.1"),
        )


def test_host_parity_rejects_promoted_hypothesis() -> None:
    promoted = _hypothesis("8.4.1")
    promoted["hypotheses"][0]["authority"] = "official_trail"

    with pytest.raises(TerrainRouteParityError, match="candidate-only"):
        compare_terrain_route_hosts(
            left_receipt=_receipt("mac", "x86_64"),
            right_receipt=_receipt("scout", "aarch64"),
            left_hypothesis=_hypothesis("8.5.0"),
            right_hypothesis=promoted,
        )


def test_host_parity_reports_large_geometry_divergence_without_safety_claim() -> None:
    diverged = copy.deepcopy(_hypothesis("8.4.1"))
    diverged["hypotheses"][1]["best_path"]["coordinates"][1] = [121.02, 23.02]

    report = compare_terrain_route_hosts(
        left_receipt=_receipt("mac", "x86_64"),
        right_receipt=_receipt("scout", "aarch64"),
        left_hypothesis=_hypothesis("8.5.0"),
        right_hypothesis=diverged,
    )

    assert report["status"] == "diverged"
    assert report["route_comparisons"][1]["within_tolerance"] is False
    assert report["authority"] == "candidate_only"
    assert report["operational"] is False


def test_host_parity_cli_writes_machine_readable_receipt(tmp_path: Path) -> None:
    inputs = {
        "left-receipt": _receipt("mac", "x86_64"),
        "right-receipt": _receipt("scout", "aarch64"),
        "left-hypothesis": _hypothesis("8.5.0"),
        "right-hypothesis": _hypothesis("8.4.1"),
    }
    arguments = []
    for name, payload in inputs.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        arguments.extend((f"--{name}", str(path)))
    output = tmp_path / "parity.json"
    tool = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "compare_terrain_route_hosts.py"
    )

    completed = subprocess.run(
        [sys.executable, str(tool), *arguments, "--output", str(output)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed_with_engine_variance"
    assert report["candidate_only"] is True
