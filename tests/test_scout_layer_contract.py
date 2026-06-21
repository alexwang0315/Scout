from __future__ import annotations

import json
from pathlib import Path

from scout_layer_contract import (
    SCOUT_LAYER_IDS,
    SCOUT_SURFACE_LAYER_IDS,
)
from tools.verify_scout_layer_contract import run_checks


ROOT = Path(__file__).resolve().parents[1]


def test_scout_layer_contract_static_gate_passes() -> None:
    result = run_checks(repo_root=ROOT)

    assert result["ok"], result["errors"]
    assert result["layer_count"] == len(SCOUT_LAYER_IDS)
    assert tuple(result["layers"].keys()) == SCOUT_LAYER_IDS


def test_completed_track_is_after_action_only_but_still_in_contract() -> None:
    assert "completed-track" in SCOUT_LAYER_IDS
    assert "completed-track" not in SCOUT_SURFACE_LAYER_IDS["pretrip"]
    assert "completed-track" not in SCOUT_SURFACE_LAYER_IDS["debug"]
    assert "completed-track" in SCOUT_SURFACE_LAYER_IDS["after-action"]


def test_browser_smoke_lists_every_layer_for_toggle_check() -> None:
    smoke_script = (ROOT / "tools" / "admin_ui_visual_smoke.js").read_text()

    for layer_id in SCOUT_LAYER_IDS:
        assert f'"{layer_id}"' in smoke_script
    assert "layerControlChecks" in smoke_script
    assert "failedToggles" in smoke_script


def test_workspace_gate_accepts_top_level_project_refs_and_counts(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "terrain_visualization_ref": "outputs/layers/terrain.geojson",
                "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
                "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
                "calibrated_risk_heatmap_ref": (
                    "outputs/risk/calibrated_risk_heatmap.geojson"
                ),
                "overpass_evidence_ref": "candidates/overpass_evidence.json",
                "route_summary_ref": "normalized/routes/route_summary.json",
                "reference_tracks_ref": "outputs/reference_tracks.json",
                "reference_track_display_geometry_ref": (
                    "outputs/reference_track_display_geometry.json"
                ),
                "segment_candidates_ref": "candidates/segments.json",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
                "boss_points_ref": "outputs/boss_points.json",
                "boss_points_geojson_ref": "outputs/boss_points.geojson",
                "risk_score_point_count": 2,
                "risk_ribbon_count": 2,
                "calibrated_risk_heatmap_point_count": 2,
                "segment_count": 2,
                "checkpoint_count": 2,
                "mcp_candidate_count": 2,
                "boss_point_count": 2,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = run_checks(
        repo_root=ROOT,
        project_root=project_root,
        require_workspace=True,
    )

    assert result["ok"], result["errors"]
