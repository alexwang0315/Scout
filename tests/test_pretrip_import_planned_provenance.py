"""P7: execute the real importer on exported Planned GPX, preserving its role."""
from __future__ import annotations

import builtins
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pytest

from pretrip_candidate_generation import generate_pretrip_candidates_from_gpx
from pretrip_gpx_corpus import build_checkpoint_event_candidates, gpx_provenance_role
from pretrip_import import PretripImportRequest, _source_record, run_pretrip_import
from scout_planned_route import compile_planned_route
from test_pretrip_gpx_corpus import _write_gpx
from test_scout_planned_route import planned_workspace


def _load(path):
    return json.loads(path.read_text())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def no_external_effects(monkeypatch):
    audit = {"network_attempts": 0, "env_read_attempts": 0}
    original_path_open = Path.open
    original_open = builtins.open

    def check(path, mode):
        if isinstance(path, (str, Path)) and Path(path).name.startswith(".env") and not any(flag in str(mode) for flag in "wax"):
            audit["env_read_attempts"] += 1
            raise AssertionError("Import fixture must never read a real .env file")

    def guarded_path_open(path, mode="r", *args, **kwargs):
        check(path, mode)
        return original_path_open(path, mode, *args, **kwargs)

    def guarded_open(path, mode="r", *args, **kwargs):
        check(path, mode)
        return original_open(path, mode, *args, **kwargs)

    def block_network(*args, **kwargs):
        audit["network_attempts"] += 1
        raise AssertionError("Import fixture must never contact a network service")

    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket, "create_connection", block_network)
    return audit


def _assert_no_recorded_or_runtime_claim(value, path="$"):
    false_fields = {"actual_user_track", "actual_user_track_available", "pretrip_actual_user_track",
                    "pretrip_actual_user_track_exists", "pretrip_actual_user_track_available",
                    "actual_user_recorded_activity", "runtime_safety_truth", "departure_approval_granted",
                    "phase1_runtime_mutation_allowed", "phase2_writeback_allowed", "safety_api_called"}
    if isinstance(value, dict):
        for key, item in value.items():
            if key in false_fields:
                assert item is not True, f"False activity/runtime claim at {path}.{key}"
            _assert_no_recorded_or_runtime_claim(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_recorded_or_runtime_claim(item, f"{path}[{index}]")


def test_planned_export_real_import_preserves_primary_reference_and_filtered_roles(tmp_path, no_external_effects):
    source_root = planned_workspace(tmp_path)
    source_hashes = {str(path.relative_to(source_root)): _sha(path)
                     for path in source_root.rglob("*") if path.is_file()}
    preview = compile_planned_route(source_root, {"departure_at": "2026-10-01T06:00:00+08:00",
        "human_text": "沿 Golden；在觀景點 C 多停 40 分鐘"})
    raw = tmp_path / "exported_planned.gpx"
    raw.write_text(preview["planned_gpx"])
    planned_ref = tmp_path / "reference_planned.gpx"
    planned_ref.write_text(preview["planned_gpx"])
    normal_ref = _write_gpx(tmp_path / "normal_reference.gpx", name="Observed reference", points=[
        (24.001, 121.0, 120, "2021-01-01T07:00:00+08:00"),
        (24.001, 121.001, 145, "2021-01-01T07:05:00+08:00"),
        (24.001, 121.002, 170, "2021-01-01T07:10:00+08:00"),
    ])
    workspace = tmp_path / "imported"
    request = PretripImportRequest(project_id="planned_reimport_fixture", primary_gpx=raw,
        reference_gpx_paths=(planned_ref, normal_ref), workspace_root=workspace, profile="pi-offline",
        import_timestamp="2026-09-10T00:00:00Z", resolve_default_material_root=False)
    manifest = run_pretrip_import(request)
    root = workspace / request.project_id
    project = _load(root / "project.json")
    package = _load(root / "outputs/pretrip_package.json")
    inbox = _load(root / "inbox/source_manifest.json")
    index = _load(root / "sources/historical_gpx_source_index.json")
    summary = _load(root / "outputs/reference_tracks.json")
    display = _load(root / "outputs/reference_track_display_geometry.json")
    route_bundle = _load(root / "normalized/routes/route_evidence_bundle.json")
    filtering = _load(root / "outputs/gpx_speed_filter_report.json")
    checkpoint_events = _load(root / "outputs/checkpoint_events.json")
    import_manifest = _load(root / "outputs/import_manifest.json")

    assert project["route_role"] == "planned_gpx_reference"
    assert project["gpx_provenance_role"] == "planned"
    assert project["actual_user_track_available"] is False
    assert project["checkpoint_naming_policy_version"] == "scout.checkpoint_naming.v1"
    assert project["checkpoint_naming_checkpoint_count"] == project["checkpoint_candidate_count"]
    assert project["checkpoint_naming_validation"]["status"] == "validated"
    assert project["checkpoint_naming_validation"]["dtm_mapping_basis"] == "segment_candidate_id_and_checkpoint_candidate_id"
    assert import_manifest["checkpoint_naming"]["report_ref"] == "outputs/checkpoint_naming.json"
    assert import_manifest["checkpoint_naming_validation"]["status"] == "validated"
    assert inbox["checkpoint_naming"]["report_sha256"] == _sha(root / "outputs/checkpoint_naming.json")
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "planned_gpx_reference"
    assert summary["golden_route"]["role"] == summary["primary_route"]["role"] == "planned_gpx_reference"
    assert summary["primary_route"]["time_role"] == "planned_estimate"
    assert summary["primary_route"]["timestamp_range"] == {"started_at": None, "ended_at": None}
    assert route_bundle["golden_route"]["role"] == "planned_gpx_reference"
    assert filtering["primary"]["gpx_provenance_role"] == filtering["primary"]["filtered_gpx_provenance_role"] == "planned"
    assert gpx_provenance_role(filtering["primary"]["output_path"]) == "planned"
    assert display["primary_gpx_provenance_role"] == "planned"
    assert checkpoint_events["source_gpx"]["gpx_provenance_role"] == "planned"
    assert all(event["observed_at"] is None and event["planned_at"] is None for event in checkpoint_events["events"])
    assert package["source_artifacts"][0]["metadata"]["role"] == "planned_gpx_reference"
    for collection in (inbox["sources"], index["sources"], summary["reference_tracks"],
                       display["reference_tracks"], route_bundle["reference_tracks"],
                       [artifact["metadata"] for artifact in package["source_artifacts"]]):
        planned_sources = [item for item in collection if item.get("gpx_provenance_role") == "planned"]
        assert planned_sources
        assert all(item["role"] == "planned_gpx_reference" for item in planned_sources)
        assert any(item.get("role") == "reference_track" for item in collection)
    assert _sha(root / inbox["sources"][0]["workspace_ref"]) == _sha(raw)
    output_hashes = {}
    for path in root.rglob("*.json"):
        _assert_no_recorded_or_runtime_claim(_load(path), path.relative_to(root).as_posix())
        output_hashes[path.relative_to(root).as_posix()] = _sha(path)
    for path in root.rglob("*.jsonl"):
        for line in path.read_text().splitlines():
            _assert_no_recorded_or_runtime_claim(json.loads(line), path.relative_to(root).as_posix())
    assert no_external_effects == {"network_attempts": 0, "env_read_attempts": 0}
    assert source_hashes == {str(path.relative_to(source_root)): _sha(path)
                            for path in source_root.rglob("*") if path.is_file()}
    before = {str(path.relative_to(root)): _sha(path) for path in root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="planned_gpx_is_not_recorded"):
        run_pretrip_import(replace(request, import_stage="post_analysis", overwrite=True))
    assert {str(path.relative_to(root)): _sha(path) for path in root.rglob("*") if path.is_file()} == before
    # Durable evidence when pytest is run with the qualification basetemp.
    (tmp_path / "planned-reimport-receipt.json").write_text(json.dumps({
        "status": "PASS", "entrypoint": "pretrip_import.run_pretrip_import", "project_id": request.project_id,
        "workspace_root": str(root), "source_planned_gpx_sha256": _sha(raw),
        "preview_sha256": preview["preview_sha256"], "output_hashes": output_hashes,
        "actual_user_track_available": False, "runtime_safety_truth": False,
        "post_analysis_rejected_before_write": True, **no_external_effects,
        "scope": "Real local import; connected map/DEM/weather preparation is outside this provenance test.",
    }, ensure_ascii=False, indent=2))


def test_planned_estimated_timestamps_are_never_checkpoint_observations(tmp_path, no_external_effects):
    source_root = planned_workspace(tmp_path)
    preview = compile_planned_route(source_root, {"departure_at": "2026-10-01T06:00:00+08:00"})
    tree = ET.fromstring(preview["planned_gpx"])
    points = list(tree.iter("{http://www.topografix.com/GPX/1/1}trkpt"))
    for index, point in enumerate(points):
        ET.SubElement(point, "{http://www.topografix.com/GPX/1/1}time").text = f"2026-10-01T06:{index * 10:02d}:00+08:00"
    planned = tmp_path / "renamed-plan.data"
    planned.write_bytes(ET.tostring(tree, encoding="utf-8"))
    assert gpx_provenance_role(planned) == "planned"
    generated = generate_pretrip_candidates_from_gpx(planned, checkpoint_spacing_m=100)
    result = build_checkpoint_event_candidates(project_id="planned_times", route_gpx_path=planned,
                                               checkpoint_candidates=generated.checkpoint_candidates)
    assert result["events"]
    assert all(event["observed_at"] is None and event["planned_at"] for event in result["events"])
    assert all(event["time_role"] == "planned_estimate" for event in result["events"])
    workspace = tmp_path / "imported-estimates"
    run_pretrip_import(PretripImportRequest(project_id="planned_estimates", primary_gpx=planned,
        workspace_root=workspace, resolve_default_material_root=False, import_timestamp="2026-09-10T00:00:00Z"))
    root = workspace / "planned_estimates"
    from pretrip_reference_segment_timing import build_reference_segment_timing
    from pretrip_historical_daily_departures import build_historical_daily_departures
    timing = build_reference_segment_timing(root)
    assert timing["counts"]["existing_source_file_count"] == timing["counts"]["planned_source_file_count"] == 1
    assert timing["counts"]["timed_source_file_count"] == 0
    assert timing["data_quality"]["measurement_count"] == 0
    assert timing["source_time_quality"][0]["status"] == "excluded_planned_source"
    # A stale/mislabelled source index must not turn the XML plan into history.
    index_path = root / "sources/historical_gpx_source_index.json"
    index = _load(index_path)
    index["sources"][0].update(role="golden_route_reference", route_role="golden_route", gpx_provenance_role="reference_observation")
    index_path.write_text(json.dumps(index))
    assert build_reference_segment_timing(root)["counts"]["timed_source_file_count"] == 0
    historical = build_historical_daily_departures(project_root=root, timezone=ZoneInfo("Asia/Taipei"), timezone_source="fixture")
    assert historical["status"] == "unavailable" and historical["days"] == []
    assert historical["reason"] == "planned_gpx_is_not_historical_recording"
    assert no_external_effects == {"network_attempts": 0, "env_read_attempts": 0}


def test_root_extension_after_track_cannot_bypass_planned_post_analysis_guard(tmp_path, no_external_effects):
    source_root = planned_workspace(tmp_path)
    preview = compile_planned_route(source_root, {"departure_at": "2026-10-01T06:00:00+08:00"})
    tree = ET.fromstring(preview["planned_gpx"])
    ns = "{http://www.topografix.com/GPX/1/1}"
    provenance = next(tree.iter("{https://scout.local/schemas/planned-route/v1}provenance"))
    for node in tree.iter():
        if provenance in list(node):
            node.remove(provenance)
            break
    ET.SubElement(tree, ns + "extensions").append(provenance)
    planned = tmp_path / "late-provenance.data"
    planned.write_bytes(ET.tostring(tree, encoding="utf-8"))
    assert gpx_provenance_role(planned) == "planned"
    workspace = tmp_path / "blocked-import"
    with pytest.raises(ValueError, match="planned_gpx_is_not_recorded"):
        run_pretrip_import(PretripImportRequest(project_id="late_plan", primary_gpx=planned,
            workspace_root=workspace, import_stage="post_analysis", resolve_default_material_root=False))
    assert not workspace.exists()


@pytest.mark.parametrize("name,data", [("evidence.json", b'{"evidence":true}'),
                                      ("terrain.tif", b"II*\x00\x08\x00"),
                                      ("document.xml", b'<document><provenance role="planned"/></document>')])
def test_source_record_non_gpx_preserves_its_role_without_xml_failure(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    result = _source_record(path, role="material_evidence")
    assert result["role"] == "material_evidence"
    assert result["gpx_provenance_role"] == "not_gpx"
    assert result["sha256"] == _sha(path)
