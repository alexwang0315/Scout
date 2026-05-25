import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import pretrip_layer_preparation
from pretrip_layer_preparation import (
    LayerPreparationRequest,
    build_layer_preparation_preview,
    run_layer_preparation,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_layer_preparation_preview_is_metadata_only_and_no_write(tmp_path: Path) -> None:
    project_root = _copy_fixture_project(tmp_path)

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm", "overpass", "terrain", "imagery", "weather"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    assert preview["artifact_kind"] == "pretrip_layer_preparation_preview"
    assert preview["preview"] is True
    assert preview["persisted"] is False
    assert preview["counts"]["layer_count"] == 5
    assert preview["counts"]["ready_layer_count"] == 5
    assert preview["network_policy"]["network_calls_made"] is False
    assert preview["boundary"]["workspace_file_mutation_allowed"] is False
    assert preview["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert preview["boundary"]["phase2_brain_writeback_allowed"] is False
    assert not (project_root / "outputs" / "layers").exists()
    assert "<trkpt" not in json.dumps(preview, ensure_ascii=False).lower()


def test_layer_preparation_overpass_plan_uses_route_corridor_bbox(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            route_corridor_m=1_000.0,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    overpass_layer = preview["layers"][0]
    route_bbox = preview["route_bbox_wgs84"]
    query_bbox = preview["bbox_wgs84"]

    assert route_bbox == {
        "south": route_summary["bbox_wgs84"]["min_lat"],
        "west": route_summary["bbox_wgs84"]["min_lon"],
        "north": route_summary["bbox_wgs84"]["max_lat"],
        "east": route_summary["bbox_wgs84"]["max_lon"],
    }
    assert query_bbox["south"] < route_bbox["south"]
    assert query_bbox["west"] < route_bbox["west"]
    assert query_bbox["north"] > route_bbox["north"]
    assert query_bbox["east"] > route_bbox["east"]
    assert preview["route_corridor"]["route_ref"] == route_summary["artifact_id"]
    assert preview["route_corridor"]["corridor_m"] == 1_000.0
    assert preview["route_corridor"]["route_geometry_refs"][
        "segment_display_geometry_ref"
    ] == "outputs/segment_display_geometry.json"
    assert overpass_layer["route_corridor"] == preview["route_corridor"]
    assert overpass_layer["planned_request"]["source"] == "route_corridor_bbox"
    assert overpass_layer["planned_request"]["network_calls_made"] is False
    assert "way[\"highway\"" in overpass_layer["planned_request"]["query_body"]
    assert str(round(query_bbox["south"], 7)) in overpass_layer["planned_request"]["query_body"]
    assert "<trkpt" not in json.dumps(preview, ensure_ascii=False).lower()


def test_layer_preparation_run_writes_workspace_outputs_and_project_refs(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm", "overpass", "terrain", "imagery", "weather"),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    project = _load(project_root / "project.json")

    assert manifest["artifact_kind"] == "pretrip_layer_preparation_manifest"
    assert manifest["validation"]["status"] == "ready_with_warnings"
    assert manifest["counts"]["layer_count"] == 5
    assert manifest["counts"]["ready_layer_count"] == 5
    assert manifest["network_policy"]["network_calls_made"] is False
    assert manifest["boundary"]["runtime_safety_truth"] is False
    assert manifest["boundary"]["final_mission_graph_compiled"] is False
    assert project["layer_preparation_manifest_ref"] == (
        "outputs/layers/layer_preparation_manifest.json"
    )
    assert (project_root / project["layer_preparation_manifest_ref"]).is_file()
    assert (project_root / project["layer_preparation_job_ref"]).is_file()
    assert (project_root / project["layer_preparation_summary_ref"]).is_file()
    assert (project_root / project["layer_adapter_manifest_ref"]).is_file()
    assert (project_root / project["layer_validation_report_ref"]).is_file()
    assert (project_root / project["layer_map_projection_ref"]).is_file()
    assert (project_root / project["layer_debug_projection_events_ref"]).is_file()
    assert "<trkpt" not in (project_root / project["layer_preparation_manifest_ref"]).read_text(
        encoding="utf-8"
    ).lower()


def test_layer_preparation_explicit_fetch_normalizes_overpass_with_fixture_fetcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = _copy_fixture_project(tmp_path)
    project_path = project_root / "project.json"
    project = _load(project_path)
    for key in (
        "overpass_evidence_ref",
        "overpass_map_context_ref",
        "overpass_raw_payload_ref",
        "overpass_candidate_count",
        "overpass_skipped_object_count",
    ):
        project.pop(key, None)
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw_fixture = ROOT / "tests" / "fixtures" / "maps" / "phase_a_overpass_raw.json"
    captured: dict[str, str] = {}

    def fixture_fetcher(planned_request: dict) -> tuple[bytes, int]:
        captured["query_body"] = planned_request["query_body"]
        captured["endpoint"] = planned_request["endpoint"]
        return raw_fixture.read_bytes(), 200

    monkeypatch.setattr(
        pretrip_layer_preparation,
        "_fetch_overpass_raw_payload",
        fixture_fetcher,
    )

    manifest = run_layer_preparation(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("overpass",),
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            route_corridor_m=1_000.0,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )
    updated_project = _load(project_path)
    overpass = manifest["layers"][0]
    evidence = _load(project_root / updated_project["overpass_evidence_ref"])

    assert captured["endpoint"] == "https://overpass-api.de/api/interpreter"
    assert "way[\"highway\"" in captured["query_body"]
    assert overpass["status"] == "ready_from_project_ref"
    assert overpass["lifecycle"]["fetch"]["status"] == "completed_live_fetch"
    assert overpass["lifecycle"]["fetch"]["external_network_calls_made"] is True
    assert manifest["network_policy"]["network_calls_made"] is True
    assert manifest["boundary"]["external_api_calls_made"] is True
    assert evidence["counts"]["candidates"] == 8
    assert evidence["request"]["route_corridor"]["route_ref"] == (
        "artifact.gpx.chilai_nanhua_day1"
    )
    assert (project_root / updated_project["overpass_raw_payload_ref"]).is_file()
    assert (project_root / updated_project["overpass_map_context_ref"]).is_file()
    assert (project_root / "outputs" / "layers" / "plans" / "overpass_query.ql").is_file()
    assert "<trkpt" not in json.dumps(evidence, ensure_ascii=False).lower()


def test_layer_preparation_blocks_explicit_fetch_without_network_flag(
    tmp_path: Path,
) -> None:
    project_root = _copy_fixture_project(tmp_path)

    preview = build_layer_preparation_preview(
        LayerPreparationRequest(
            project_id="chilai_nanhua_day1",
            project_root=project_root,
            layers=("osm",),
            network_mode="explicit-fetch",
            allow_network_fetch=False,
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    assert preview["validation"]["status"] == "blocked"
    assert preview["validation"]["blocker_count"] == 1
    assert preview["network_policy"]["network_calls_made"] is False
    assert preview["boundary"]["network_calls_allowed"] is False


def test_layer_preparation_rejects_unknown_layer_id(tmp_path: Path) -> None:
    project_root = _copy_fixture_project(tmp_path)

    with pytest.raises(ValueError, match="unsupported layer id"):
        build_layer_preparation_preview(
            LayerPreparationRequest(
                project_id="chilai_nanhua_day1",
                project_root=project_root,
                layers=("osm", "mystery-layer"),
            )
        )


def test_layer_preparation_cli_writes_manifest(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = _copy_fixture_project(tmp_path, workspace_root=workspace_root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_layer_preparation",
            "--project-id",
            "chilai_nanhua_day1",
            "--workspace-root",
            str(workspace_root),
            "--layers",
            "osm,dtm,reference-tracks",
            "--prepared-at",
            "2026-05-22T00:00:00+00:00",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(result.stdout)
    project = _load(project_root / "project.json")

    assert manifest["artifact_kind"] == "pretrip_layer_preparation_manifest"
    assert manifest["normalized_layers"] == ["osm", "terrain", "reference-tracks"]
    assert project["layer_preparation_manifest_ref"] == (
        "outputs/layers/layer_preparation_manifest.json"
    )
    assert (project_root / project["layer_debug_projection_events_ref"]).is_file()


def _copy_fixture_project(
    tmp_path: Path,
    *,
    workspace_root: Path | None = None,
) -> Path:
    workspace = workspace_root or (tmp_path / "workspaces")
    project_root = workspace / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_PROJECT_ROOT, project_root)
    return project_root


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
