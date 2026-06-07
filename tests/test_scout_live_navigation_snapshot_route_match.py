from __future__ import annotations

import json
from pathlib import Path

from route_matching import load_gpx_route
from scout_live_navigation_snapshot_route_match import (
    enrich_live_navigation_snapshot_with_route_match,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_enrich_live_navigation_snapshot_adds_route_and_checkpoint_fields(
    tmp_path: Path,
) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    project_root = _write_route_match_project(tmp_path, anchor_lat=anchor.lat, anchor_lon=anchor.lon)

    enriched, report = enrich_live_navigation_snapshot_with_route_match(
        {
            "observed_at": "2026-06-07T08:00:00Z",
            "lat": anchor.lat,
            "lon": anchor.lon,
            "source": "fixture",
        },
        route_path=ROUTE_PATH,
        project_root=project_root,
    )

    assert enriched["nearest_route_distance_m"] <= 0.001
    assert enriched["route_progress_m"] == round(anchor.progress_m, 3)
    assert enriched["nearest_cp_id"] == "cp.anchor"
    assert report["status"] == "enriched"
    assert report["nearest_route_distance_m"] <= 0.001
    assert report["matched_route_progress_m"] == round(anchor.progress_m, 3)
    assert report["checkpoint_match"]["status"] == "matched"
    assert report["checkpoint_match"]["nearest_cp_id"] == "cp.anchor"
    assert report["runtime_safety_truth"] is False
    assert report["safety_api_called"] is False
    assert report["outbound_send_performed"] is False


def test_enrich_live_navigation_snapshot_preserves_existing_route_fields(
    tmp_path: Path,
) -> None:
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]
    project_root = _write_route_match_project(tmp_path, anchor_lat=anchor.lat, anchor_lon=anchor.lon)

    enriched, _report = enrich_live_navigation_snapshot_with_route_match(
        {
            "lat": anchor.lat,
            "lon": anchor.lon,
            "nearest_route_distance_m": 12.4,
            "route_progress_m": 99.0,
            "nearest_cp_id": "cp.existing",
        },
        route_path=ROUTE_PATH,
        project_root=project_root,
    )

    assert enriched["nearest_route_distance_m"] == 12.4
    assert enriched["route_progress_m"] == 99.0
    assert enriched["nearest_cp_id"] == "cp.existing"


def _write_route_match_project(tmp_path: Path, *, anchor_lat: float, anchor_lon: float) -> Path:
    project_root = tmp_path / "project"
    (project_root / "candidates").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"checkpoint_candidates_ref": "candidates/checkpoints.json"}),
        encoding="utf-8",
    )
    (project_root / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cp.anchor",
                    "lat": anchor_lat,
                    "lon": anchor_lon,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
                {
                    "candidate_id": "cp.far",
                    "lat": anchor_lat + 0.01,
                    "lon": anchor_lon + 0.01,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root
