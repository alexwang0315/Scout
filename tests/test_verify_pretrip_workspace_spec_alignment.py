from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pretrip_architecture_preparation import prepare_route_architecture_intelligence
from tools.verify_pretrip_workspace_spec_alignment import (
    _check_architecture_preparation,
    _check_layer_preparation,
    _check_layer_projection,
    _check_required_project_refs,
)

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools" / "verify_pretrip_workspace_spec_alignment.py"

def test_runtime_session_layout_contract_accepts_black_box_recorder(tmp_path: Path) -> None:
    session_root = tmp_path / "runtime" / "sessions"
    _write_runtime_session(session_root, "session.alpha")

    result = _run_verifier(
        "--skip-pretrip",
        "--runtime-session-root",
        str(session_root),
        "--runtime-session-id",
        "session.alpha",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["runtime_session"]["checked"] is True
    assert payload["summary"]["runtime_session"]["scout_svr_checked"] is True


def test_verifier_direct_execution_bootstraps_repo_import_path(
    tmp_path: Path,
) -> None:
    code = (
        "import runpy; "
        f"runpy.run_path({str(VERIFIER)!r}); "
        "import pretrip_architecture_preparation"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_session_layout_contract_rejects_credential_exposure(
    tmp_path: Path,
) -> None:
    session_root = tmp_path / "runtime" / "sessions"
    _write_runtime_session(session_root, "session.alpha", credential_exposed=True)

    result = _run_verifier(
        "--skip-pretrip",
        "--runtime-session-root",
        str(session_root),
        "--runtime-session-id",
        "session.alpha",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(
        "credential_value_exposed=false" in error
        for error in payload["errors"]
    )


def test_completed_trip_layout_contract_accepts_multi_gpx_and_runtime_import(
    tmp_path: Path,
) -> None:
    completed_root = tmp_path / "completed_trips"
    _write_completed_trip(completed_root, "trip.alpha")

    result = _run_verifier(
        "--skip-pretrip",
        "--completed-trip-root",
        str(completed_root),
        "--trip-id",
        "trip.alpha",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["completed_trip"]["recorded_gpx_count"] == 2
    assert payload["summary"]["completed_trip"]["runtime_import_checked"] is True


def test_black_box_export_layout_contract_accepts_sealed_export(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "black-box" / "session_exports"
    _write_black_box_export(export_root, "session.alpha")

    result = _run_verifier(
        "--skip-pretrip",
        "--black-box-export-root",
        str(export_root),
        "--black-box-session-id",
        "session.alpha",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"]["black_box_export"]["checked"] is True


def test_pretrip_verifier_accepts_wmts_runtime_imagery_contract(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = {
        "imagery_source_id": "nlsc_photo2",
        "imagery_source_registry_id": "scout.imagery_sources.default.v1",
    }
    for ref_key, ref in {
        "source_inbox_manifest_ref": "inbox/source_manifest.json",
        "historical_gpx_source_index_ref": "sources/historical_gpx_source_index.json",
        "route_evidence_bundle_ref": "normalized/routes/route_evidence_bundle.json",
        "normalized_route_note_candidates_ref": "normalized/notes/gpx_route_note_candidates.json",
        "route_note_candidates_ref": "candidates/route_note_candidates.json",
        "gpx_speed_filter_report_ref": "outputs/gpx_speed_filter_report.json",
        "layer_preparation_manifest_ref": "outputs/layers/layer_preparation_manifest.json",
        "layer_preparation_summary_ref": "outputs/layers/layer_preparation_summary.json",
        "map_preparation_summary_ref": "outputs/layers/map_preparation_summary.json",
        "layer_map_projection_ref": "outputs/layers/projections/pretrip_map_layers.json",
        "web_case_query_plan_ref": "outputs/layers/plans/web_case_query_plan.json",
        "raster_label_plan_ref": "outputs/layers/plans/raster_label_plan.json",
        "overpass_vector_evidence_ref": "outputs/layers/normalized/overpass_vector_evidence.geojson",
        "terrain_route_samples_ref": "outputs/layers/normalized/terrain_route_samples.geojson",
        "web_case_evidence_ref": "outputs/layers/normalized/web_case_evidence.json",
        "raster_label_evidence_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
        "gis_semantic_input_bundle_ref": "outputs/layers/semantic/gis_semantic_input_bundle.json",
        "gis_perception_ai_judgements_ref": "outputs/layers/semantic/gis_perception_ai_judgements.json",
        "gis_checkpoint_candidates_ref": "outputs/layers/candidates/gis_checkpoint_candidates.json",
        "ln_proposals_ref": "outputs/layers/candidates/ln_proposals.json",
        "poi_candidates_ref": "outputs/layers/candidates/poi_candidates.json",
        "terrain_risk_candidates_ref": "outputs/layers/candidates/terrain_risk_candidates.json",
        "detour_route_candidates_ref": "outputs/layers/candidates/detour_route_candidates.json",
        "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
        "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
        "calibrated_risk_heatmap_ref": "outputs/risk/calibrated_risk_heatmap.geojson",
        "reference_pace_energy_analysis_ref": (
            "outputs/reference_pace_energy_analysis.json"
        ),
        "reference_pace_energy_map_geojson_ref": (
            "outputs/reference_pace_energy_map.geojson"
        ),
        "architecture_preparation_manifest_ref": (
            "outputs/architecture_preparation_manifest.json"
        ),
    }.items():
        project[ref_key] = ref
        (project_root / ref).parent.mkdir(parents=True, exist_ok=True)
        (project_root / ref).write_text("{}", encoding="utf-8")

    errors: list[str] = []
    _check_required_project_refs(project_root, project, errors)
    assert not errors

    imagery_layer = {
        "layer_id": "imagery",
        "status": "wmts_runtime_only",
        "raster_tile_delivery": "direct_wmts_runtime",
        "imagery_source_kind": "wmts_tile",
        "source_refs": [{"source_kind": "wmts_tile"}],
        "counts": {"remote_imagery_source_registered": True},
        "lifecycle": {
            "import": {"source_ref_count": 1},
            "summarize": {"counts": {"remote_imagery_source_registered": True}},
        },
    }
    ready_layers = [
        {
            "layer_id": layer_id,
            "status": "ready",
            "source_refs": [],
            "counts": {},
            "lifecycle": {"summarize": {"counts": {}}},
        }
        for layer_id in (
            "risk-score",
            "risk-ribbon",
            "risk-heatmap",
            "risk-delta",
            "route",
            "segments",
            "checkpoints",
            "reference-tracks",
        )
    ]
    ready_layers.append(
        {
            "layer_id": "route-notes",
            "status": "ready",
            "source_refs": [
                {"project_ref_key": "normalized_route_note_candidates_ref"},
                {"project_ref_key": "route_note_candidates_ref"},
            ],
            "counts": {},
            "lifecycle": {"summarize": {"counts": {}}},
        }
    )
    errors = []
    warnings: list[str] = []
    _check_layer_preparation(
        {
            "boundary": {
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
            },
            "network_policy": {"network_calls_made": False},
            "layers": [imagery_layer, *ready_layers],
        },
        {"layers": []},
        errors,
        warnings,
    )
    assert not errors

    errors = []
    _check_layer_projection({"layers": [imagery_layer]}, errors)
    assert not errors


def test_pretrip_verifier_accepts_fresh_enriched_architecture_artifacts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    filtered_path = (
        project_root
        / "normalized/routes/filtered/primary.demo.speed_filtered.gpx"
    )
    raw_path = project_root / "inbox/gpx/primary.gpx"
    source_index_path = project_root / "sources/historical_gpx_source_index.json"
    risk_path = project_root / "outputs/risk/risk_score_points.geojson"
    pressure_path = project_root / "outputs/route_pressure_profile.json"
    for path in (filtered_path, raw_path, source_index_path, risk_path, pressure_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    gpx = """<?xml version="1.0" encoding="utf-8"?>
<gpx version="1.1"><trk><trkseg>
<trkpt lat="23.95" lon="121.0000"><ele>1000</ele><time>2026-01-01T00:00:00Z</time></trkpt>
<trkpt lat="23.95" lon="121.0005"><ele>1005</ele><time>2026-01-01T00:01:00Z</time></trkpt>
<trkpt lat="23.95" lon="121.0010"><ele>1010</ele><time>2026-01-01T00:02:00Z</time></trkpt>
</trkseg></trk></gpx>"""
    filtered_path.write_text(gpx, encoding="utf-8")
    raw_path.write_text(gpx, encoding="utf-8")
    source_index_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "gpx.source.demo",
                        "route_role": "golden_route",
                        "workspace_ref": "inbox/gpx/primary.gpx",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    risk_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.0 + index * 0.0005, 23.95],
                        },
                        "properties": {
                            "distance_m": index * 50.0,
                            "rs": 30.0,
                        },
                    }
                    for index in range(3)
                ],
            }
        ),
        encoding="utf-8",
    )
    pressure_path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "start_distance_m": 0.0,
                        "end_distance_m": 100.0,
                        "terrain": {
                            "distance_m": 100.0,
                            "elevation_gain_m": 10.0,
                            "elevation_loss_m": 0.0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "demo",
                "historical_gpx_source_index_ref": (
                    "sources/historical_gpx_source_index.json"
                ),
                "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
                "route_pressure_profile_ref": "outputs/route_pressure_profile.json",
            }
        ),
        encoding="utf-8",
    )

    result = prepare_route_architecture_intelligence(
        project_root,
        generated_at="2026-07-29T00:00:00+00:00",
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    errors: list[str] = []

    summary = _check_architecture_preparation(project_root, project, errors)

    assert result["status"] == "ready"
    assert summary["status"] == "ready"
    assert summary["fresh"] is True
    assert summary["observed_route_bin_count"] > 0
    assert not errors


def _run_verifier(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_runtime_session(
    runtime_session_root: Path,
    session_id: str,
    *,
    credential_exposed: bool = False,
) -> None:
    root = runtime_session_root / session_id
    for relative in (
        "events",
        "team",
        "recorder",
        "transports",
        "sensor_logs/journey.scout-svr",
        "hardware",
        "communications",
        "navigation",
        "black_box",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    _write_json(
        root / "session_manifest.json",
        {
            "workspace_kind": "runtime_session",
            "session_id": session_id,
            "pretrip_candidate_mutation_allowed": False,
        },
    )
    _write_json(
        root / "recorder" / "recorder_manifest.json",
        {"session_id": session_id, "append_only": True},
    )
    _write_json(
        root / "black_box" / "black_box_manifest.json",
        {"session_id": session_id, "source_of_safety_decisions": False},
    )
    _write_jsonl(
        root / "events" / "event_index.jsonl",
        [{"sequence": 1, "event_id": "evt.1", "recorded_at": "2026-06-15T00:00:00Z"}],
    )
    _write_jsonl(
        root / "team" / "team_status_events.jsonl",
        [
            {
                "sequence": 1,
                "member_ref": "member.self",
                "status": "ok",
                "recorded_at": "2026-06-15T00:00:01Z",
            }
        ],
    )
    _write_jsonl(
        root / "recorder" / "append_only_integrity_chain.jsonl",
        [{"sequence": 1, "recorded_at": "2026-06-15T00:00:02Z"}],
    )
    _write_jsonl(
        root / "transports" / "ingress_evidence_index.jsonl",
        [
            {
                "sequence": 1,
                "received_at": "2026-06-15T00:00:03Z",
                "ingress_transport": "wan_mqtt",
                "source_adapter": "sensorlogger",
                "payload_sha256": "a" * 64,
                "parse_status": "accepted",
                "credential_value_exposed": credential_exposed,
            }
        ],
    )
    _write_jsonl(
        root / "transports" / "egress_evidence_index.jsonl",
        [
            {
                "sequence": 1,
                "queued_at": "2026-06-15T00:00:04Z",
                "egress_transport": "lora_gateway",
                "payload_sha256": "b" * 64,
                "delivery_status": "queued",
                "credential_value_exposed": False,
            }
        ],
    )
    _write_jsonl(
        root / "hardware" / "hardware_resource_access_events.jsonl",
        [
            {
                "sequence": 1,
                "recorded_at": "2026-06-15T00:00:05Z",
                "hardware_interface": "gpio",
                "access_status": "read",
            }
        ],
    )
    _write_jsonl(
        root / "black_box" / "black_box_event_index.jsonl",
        [
            {
                "sequence": 1,
                "event_ref": "events/event_index.jsonl#1",
                "recorded_at": "2026-06-15T00:00:06Z",
            }
        ],
    )
    _write_scout_svr(root / "sensor_logs" / "journey.scout-svr")


def _write_scout_svr(root: Path) -> None:
    _write_json(
        root / "manifest.json",
        {
            "artifact_kind": "scout_sensor_vitals_record",
            "artifact_version": "scout_sensor_vitals_record.v0",
        },
    )
    _write_jsonl(
        root / "observations.jsonl",
        [{"sequence": 1, "timestamp": "2026-06-15T00:00:00Z"}],
    )
    for filename in (
        "application_routes.jsonl",
        "filter_outputs.jsonl",
        "navigation_estimates.jsonl",
        "vitals.jsonl",
        "transport_ingress_index.jsonl",
        "transport_egress_index.jsonl",
    ):
        _write_jsonl(root / filename, [])


def _write_completed_trip(completed_root: Path, trip_id: str) -> None:
    root = completed_root / trip_id
    for relative in (
        "recorded/primary_user",
        "recorded/participants/member.a",
        "runtime/events",
        "runtime/team",
        "runtime/recorder",
        "runtime/transports",
        "runtime/sensor_logs",
        "runtime/hardware",
        "runtime/communications",
        "runtime/navigation",
        "runtime/black_box",
        "outputs",
        "reviews",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "trip_manifest.json",
        {
            "workspace_kind": "completed_trip",
            "trip_id": trip_id,
            "pretrip_candidate_mutation_allowed": False,
        },
    )
    _write_json(
        root / "recorded" / "recording_set_manifest.json",
        {
            "trip_id": trip_id,
            "recording_set_storage_allows_multiple_gpx": True,
            "active_view_single_subject": True,
        },
    )
    _write_text(root / "recorded" / "primary_user" / "watch.gpx", _tiny_gpx())
    _write_text(
        root / "recorded" / "participants" / "member.a" / "phone.gpx",
        _tiny_gpx(),
    )
    _write_json(root / "runtime" / "imported_session_manifest.json", {})
    _write_json(root / "outputs" / "capability_timeline.json", {})
    _write_json(root / "outputs" / "capability_capsule.json", {})


def _write_black_box_export(export_root: Path, session_id: str) -> None:
    root = export_root / session_id
    for relative in (
        "bundle/recorder",
        "bundle/events",
        "bundle/team",
        "bundle/transports",
        "bundle/sensor_logs",
        "bundle/hardware",
        "bundle/communications",
        "bundle/navigation",
        "bundle/black_box",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    _write_json(
        root / "black_box_export_manifest.json",
        {
            "session_id": session_id,
            "source_runtime_session_ref": f"runtime/sessions/{session_id}",
            "pretrip_template_package": False,
        },
    )
    _write_json(
        root / "redaction_policy.json",
        {"audience": "support", "purpose": "incident_reconstruction"},
    )
    _write_text(root / "checksums.sha256", "a  bundle/session_manifest.json\n")
    _write_jsonl(
        root / "timeline_index.jsonl",
        [
            {
                "sequence": 1,
                "source_ref": "bundle/events/event_index.jsonl#1",
                "recorded_at": "2026-06-15T00:00:00Z",
            }
        ],
    )
    _write_json(root / "bundle" / "session_manifest.json", {"session_id": session_id})


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _tiny_gpx() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="scout-test">
  <trk><name>test</name><trkseg>
    <trkpt lat="24.0" lon="121.0"><time>2026-06-15T00:00:00Z</time></trkpt>
    <trkpt lat="24.0001" lon="121.0001"><time>2026-06-15T00:01:00Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""
