from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout_contextual_permission_initialization import (
    SEED_REF,
    ensure_contextual_permission_authoring,
)
from scout_contextual_permission_workbench import ContextualPermissionWorkbenchSeed
from scout_contextual_permission_workbench_api import (
    create_contextual_permission_workbench_router,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _workspace(tmp_path: Path, *, project_id: str, route_days: int | None = None) -> Path:
    project_root = tmp_path / "workspace" / project_id
    (project_root / "inbox").mkdir(parents=True)
    (project_root / "outputs").mkdir()
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1" creator="test">'
        '<trk><trkseg><trkpt lat="24.0" lon="121.0" />'
        '<trkpt lat="24.1" lon="121.1" /></trkseg></trk></gpx>'
    )
    (project_root / "inbox" / "golden.gpx").write_text(gpx, encoding="utf-8")
    (project_root / "inbox" / "source_manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "role": "golden_route_reference",
                        "workspace_ref": "inbox/golden.gpx",
                        "sha256": _sha(gpx),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    project = {
        "project_id": project_id,
        "route_name": "Initialization Fixture",
        "source_inbox_manifest_ref": "inbox/source_manifest.json",
    }
    if route_days is not None:
        project["route_days"] = route_days
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    return project_root


def _client(project_root: Path, tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_contextual_permission_workbench_router(
            pretrip_workspace_root=project_root.parent,
            store_root=tmp_path / "store",
        ),
        prefix="/admin",
    )
    return TestClient(app)


def test_initializes_single_day_authoring_seed_and_ref_gpx_generate(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_single")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "initialized"
    assert result["authoring_ready"] is True
    assert result["projection_ready"] is False
    assert result["reviewed"] is False
    assert result["runtime_safety_truth"] is False
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert project["planned_eta_ref"] == "outputs/planned_eta.json"
    assert "reviewed_mission_baseline_ref" not in project
    seed = ContextualPermissionWorkbenchSeed.model_validate(
        json.loads((project_root / SEED_REF).read_text(encoding="utf-8"))
    )
    assert seed.baseline.accepted_by_human is False
    assert seed.baseline.contextual_permission_rules_reviewed_by_human is False
    assert seed.baseline.departure_approval_granted is False
    assert {node.adjustment_policy for node in seed.remaining_plan} == {"review_only"}

    response = _client(project_root, tmp_path).post(
        "/admin/pretrip/projects/permission_init_single/mission-baseline/generate-draft",
        json={"mode": "reference_gpx", "reference_route_ref": "inbox/golden.gpx"},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["source_mode"] == "reference_gpx"
    assert draft["candidate_only"] is True
    assert draft["runtime_safety_truth"] is False
    assert draft["departure_approval_granted"] is False


def test_initializes_multiday_metadata_without_reviewed_days_or_camps(tmp_path: Path) -> None:
    project_root = _workspace(
        tmp_path,
        project_id="permission_init_multiday",
        route_days=3,
    )

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "initialized"
    assert result["mission_day_ids"] == ["D1", "D2", "D3"]
    seed = ContextualPermissionWorkbenchSeed.model_validate(
        json.loads((project_root / SEED_REF).read_text(encoding="utf-8"))
    )
    assert sorted({node.mission_day_id for node in seed.remaining_plan}) == [
        "D1",
        "D2",
        "D3",
    ]
    baseline_ref = result["baseline_candidate_ref"]
    baseline = json.loads((project_root / baseline_ref).read_text(encoding="utf-8"))
    assert [day["mission_day_id"] for day in baseline["days"]] == ["D1", "D2", "D3"]
    assert all(not day["resolved_targets"] for day in baseline["days"])
    assert all("Camp" not in " ".join(day["ordered_place_mentions"]) for day in baseline["days"])
    assert baseline["review_ready"] is False
    assert baseline["runtime_safety_truth"] is False


def test_initializer_is_idempotent_and_does_not_replace_existing_seed(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_idempotent")
    first = ensure_contextual_permission_authoring(project_root)
    seed_path = project_root / SEED_REF
    seed_before = seed_path.read_bytes()

    second = ensure_contextual_permission_authoring(project_root)

    assert first["status"] == "initialized"
    assert second["status"] == "already_initialized"
    assert seed_path.read_bytes() == seed_before
    assert second["writes_performed"] is False


def test_initializer_blocks_hash_mismatch_without_writes(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_hash_mismatch")
    manifest_path = project_root / "inbox" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["authoring_ready"] is False
    assert result["root_causes"] == ["golden_route_reference_unavailable"]
    assert not (project_root / SEED_REF).exists()


def test_initializer_preserves_existing_review_selection(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_reviewed_guard")
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["reviewed_mission_baseline_ref"] = "outputs/mission_baselines/existing.json"
    project["reviewed_mission_baseline_sha256"] = "a" * 64
    project_path.write_text(json.dumps(project), encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["root_causes"] == ["reviewed_baseline_exists_without_authoring_seed"]
    assert json.loads(project_path.read_text(encoding="utf-8"))["reviewed_mission_baseline_ref"] == (
        "outputs/mission_baselines/existing.json"
    )
    assert not (project_root / SEED_REF).exists()

from geo_utils import haversine_m
from scout_contextual_permission_initialization import (
    JOURNAL_REF,
    _make_journal,
    _resolve_ref,
    _write_new_json,
)

FILTERED_PRIMARY_REF = "normalized/routes/filtered/primary.fixture.speed_filtered.gpx"


def _write_valid_planned_eta(project_root: Path, project_id: str) -> None:
    path = project_root / "outputs" / "planned_eta.fullprep.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "plan_id": f"eta.{project_id}.fullprep.v1",
                "project_id": project_id,
                "assumption": {
                    "assumption_id": f"eta_assumption.{project_id}.day1.v0",
                    "planned_start_time": "2026-07-29T06:00:00+08:00",
                    "planned_start_source": "fixture",
                    "planned_start_offset_minutes": 0,
                    "day1_target_node_name": "Reviewed camp",
                    "turn_back_checkpoint_node_name": "Reviewed junction",
                    "elapsed_time_policy": "fixture_total_elapsed_time",
                    "notes": [],
                },
                "estimates": [],
            }
        ),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["planned_eta_ref"] = "outputs/planned_eta.fullprep.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")


def test_initializer_recovers_from_frozen_journal_without_new_timestamp(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_recovery")
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    journal = _make_journal(project_root, project)
    assert journal["artifact_kind"] == "contextual_permission_initialization_transaction"
    _write_new_json(_resolve_ref(project_root, JOURNAL_REF, required=False), journal)
    first_two = journal["write_plan"][:2]
    for item in first_two:
        _write_new_json(_resolve_ref(project_root, item["ref"], required=False), item["payload"])

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "initialized"
    assert result["recovered_from_journal"] is True
    assert (project_root / SEED_REF).is_file()
    receipt = json.loads((project_root / "reviews/contextual_permission_bootstrap_receipt.json").read_text())
    assert receipt["recorded_at"] == journal["created_at"]
    assert json.loads((project_root / "project.json").read_text())["contextual_permission_bootstrap_ref"] == SEED_REF


def test_initializer_blocks_changed_source_during_journal_recovery(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_recovery_stale")
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    journal = _make_journal(project_root, project)
    _write_new_json(_resolve_ref(project_root, JOURNAL_REF, required=False), journal)
    (project_root / "inbox" / "golden.gpx").write_text("<gpx>changed</gpx>", encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["root_causes"] == ["contextual_permission_initialization_source_stale"]
    assert not (project_root / SEED_REF).exists()


def test_existing_seed_validation_blocks_wrong_project_without_writes(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_wrong_project")
    ensure_contextual_permission_authoring(project_root)
    (project_root / JOURNAL_REF).unlink()
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["project_id"] = "other_project"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["root_causes"] == ["existing_contextual_permission_seed_project_mismatch"]
    assert result["writes_performed"] is False


def test_existing_seed_validation_blocks_stale_source_and_missing_candidate(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_existing_guard")
    ensure_contextual_permission_authoring(project_root)
    (project_root / JOURNAL_REF).unlink()
    (project_root / "inbox" / "golden.gpx").write_text("<gpx>changed</gpx>", encoding="utf-8")
    stale = ensure_contextual_permission_authoring(project_root)
    assert stale["status"] == "blocked"
    assert stale["root_causes"] == ["contextual_permission_seed_source_hash_mismatch"]

    fresh_root = _workspace(tmp_path, project_id="permission_init_missing_candidate")
    initialized = ensure_contextual_permission_authoring(fresh_root)
    (fresh_root / JOURNAL_REF).unlink()
    candidate_path = fresh_root / initialized["baseline_candidate_ref"]
    candidate_path.unlink()
    missing = ensure_contextual_permission_authoring(fresh_root)
    assert missing["status"] == "blocked"
    assert missing["root_causes"] == ["contextual_permission_baseline_candidate_missing"]
    assert missing["writes_performed"] is False


def test_initializer_reuses_existing_fullprep_planned_eta(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_existing_eta")
    _write_valid_planned_eta(project_root, "permission_init_existing_eta")
    original_eta = (project_root / "outputs" / "planned_eta.fullprep.json").read_bytes()

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "initialized"
    assert "outputs/planned_eta.json" not in result["written_refs"]
    assert json.loads((project_root / "project.json").read_text())["planned_eta_ref"] == (
        "outputs/planned_eta.fullprep.json"
    )
    assert (project_root / "outputs" / "planned_eta.fullprep.json").read_bytes() == original_eta


def test_initializer_blocks_invalid_existing_planned_eta_without_writes(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_bad_eta")
    eta_path = project_root / "outputs" / "planned_eta.fullprep.json"
    eta_path.write_text(json.dumps({"not": "eta"}), encoding="utf-8")
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["planned_eta_ref"] = "outputs/planned_eta.fullprep.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["root_causes"] == ["planned_eta_ref_invalid_or_missing"]
    assert not (project_root / SEED_REF).exists()


def _timed_gpx(points: list[tuple[float, float, str]]) -> str:
    body = "".join(
        f'<trkpt lat="{lat}" lon="{lon}"><time>{stamp}</time></trkpt>'
        for lat, lon, stamp in points
    )
    return (
        '<?xml version="1.0"?><gpx version="1.1" creator="test" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        f"{body}</trkseg></trk></gpx>"
    )


def _write_reconstruction_workspace(
    tmp_path: Path,
    *,
    project_id: str,
    points: list[tuple[float, float, str]],
) -> Path:
    project_root = tmp_path / "workspace" / project_id
    primary_path = project_root / FILTERED_PRIMARY_REF
    primary_path.parent.mkdir(parents=True, exist_ok=True)
    gpx = _timed_gpx(points)
    primary_path.write_text(gpx, encoding="utf-8")
    source_sha = hashlib.sha256(primary_path.read_bytes()).hexdigest()
    axis = [0.0]
    for first, second in zip(points, points[1:]):
        axis.append(axis[-1] + haversine_m(first[0], first[1], second[0], second[1]))
    source_manifest = project_root / "inbox" / "source_manifest.json"
    source_manifest.parent.mkdir(parents=True, exist_ok=True)
    source_manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "role": "golden_route_reference",
                        "workspace_ref": FILTERED_PRIMARY_REF,
                        "sha256": source_sha,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint_events = []
    for index in range(len(points)):
        checkpoint_events.append(
            {
                "checkpoint_candidate_id": f"cp.{index:03d}",
                "label": f"CP {index:03d}",
                "route_point_index": index,
                "progress_m": axis[index],
                "lat": points[index][0],
                "lon": points[index][1],
                "observed_at": points[index][2],
            }
        )
    checkpoint_path = project_root / "outputs" / "checkpoint_events.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps({"events": checkpoint_events}), encoding="utf-8")
    from pretrip_historical_daily_departures import build_historical_daily_departures
    from zoneinfo import ZoneInfo

    schedule = build_historical_daily_departures(
        project_root=project_root,
        timezone=ZoneInfo("Asia/Taipei"),
        timezone_source="fixture#timezone",
    )
    assert schedule["status"] == "ready"
    pace_path = project_root / "outputs" / "reference_pace_energy_analysis.json"
    pace_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_reference_pace_energy_analysis",
                "historical_route_timing": {
                    "daily_departures": {
                        "timezone": "Asia/Taipei",
                        "timezone_source": "fixture#timezone",
                        "source_ref": schedule["source_ref"],
                        "source_sha256": schedule["source_sha256"],
                        "days": schedule["days"],
                    }
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "route_name": "Historical Reconstruction Fixture",
                "source_inbox_manifest_ref": "inbox/source_manifest.json",
                "compiled_mission_graph_reviewed_ref": FILTERED_PRIMARY_REF,
                "reference_pace_energy_analysis_ref": "outputs/reference_pace_energy_analysis.json",
                "checkpoint_events_ref": "outputs/checkpoint_events.json",
            }
        ),
        encoding="utf-8",
    )
    return project_root


def test_historical_reconstruction_preview_and_generate_single_day(tmp_path: Path) -> None:
    project_root = _write_reconstruction_workspace(
        tmp_path,
        project_id="permission_init_reconstruct_single",
        points=[
            (23.0, 121.0, "2020-12-25T06:00:00+08:00"),
            (23.0, 121.01, "2020-12-25T09:00:00+08:00"),
            (23.0, 121.02, "2020-12-25T16:00:00+08:00"),
        ],
    )
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)
    request = {
        "mode": "reference_gpx",
        "reference_route_ref": FILTERED_PRIMARY_REF,
        "reference_strategy": "historical_reconstruction",
    }

    preview = client.post(
        "/admin/pretrip/projects/permission_init_reconstruct_single/mission-baseline/preview",
        json=request,
    )
    generated = client.post(
        "/admin/pretrip/projects/permission_init_reconstruct_single/mission-baseline/generate-draft",
        json=request,
    )

    assert preview.status_code == 200
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["proposal_strategy_id"] == "reference-gpx.historical-reconstruction"
    assert payload["proposal_profile"] == "ref_gpx_proposal_v1"
    assert payload["proposal_summary"]["reconstructed_day_count"] == 1
    assert payload["days"][0]["reference_replay"]["departure_clock"] == "06:00:00"
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False


def test_historical_reconstruction_preview_and_generate_multiday(tmp_path: Path) -> None:
    project_root = _write_reconstruction_workspace(
        tmp_path,
        project_id="permission_init_reconstruct_multi",
        points=[
            (23.0, 121.0, "2020-12-25T05:36:30+08:00"),
            (23.0, 121.01, "2020-12-25T16:00:00+08:00"),
            (23.0, 121.0102, "2020-12-26T06:00:00+08:00"),
            (23.0, 121.02, "2020-12-26T09:00:00+08:00"),
        ],
    )
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)
    request = {
        "mode": "reference_gpx",
        "reference_route_ref": FILTERED_PRIMARY_REF,
        "reference_strategy": "historical_reconstruction",
    }

    preview = client.post(
        "/admin/pretrip/projects/permission_init_reconstruct_multi/mission-baseline/preview",
        json=request,
    )
    generated = client.post(
        "/admin/pretrip/projects/permission_init_reconstruct_multi/mission-baseline/generate-draft",
        json=request,
    )

    assert preview.status_code == 200
    assert generated.status_code == 200
    payload = generated.json()
    assert [day["mission_day_id"] for day in payload["days"]] == ["D1", "D2"]
    assert payload["proposal_summary"]["reconstructed_day_count"] == 2
    assert payload["reference_reconstruction"]["overnight_gaps"]
    assert payload["days"][1]["reference_replay"]["departure_clock"] == "06:00:00"
    assert payload["departure_approval_granted"] is False


def test_saved_candidate_catalog_and_detail_restore_saved_ref_gpx_draft(
    tmp_path: Path,
) -> None:
    project_root = _write_reconstruction_workspace(
        tmp_path,
        project_id="permission_init_saved_catalog",
        points=[
            (23.0, 121.0, "2020-12-25T06:00:00+08:00"),
            (23.0, 121.01, "2020-12-25T09:00:00+08:00"),
            (23.0, 121.02, "2020-12-25T16:00:00+08:00"),
        ],
    )
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)
    prefix = "/admin/pretrip/projects/permission_init_saved_catalog/mission-baseline"
    request = {
        "mode": "reference_gpx",
        "reference_route_ref": FILTERED_PRIMARY_REF,
        "reference_strategy": "historical_reconstruction",
    }
    generated = client.post(f"{prefix}/generate-draft", json=request)
    assert generated.status_code == 200
    draft = generated.json()
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "permission-init-saved-catalog-001",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    receipt = saved.json()

    catalog = client.get(f"{prefix}/candidates")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["project_id"] == "permission_init_saved_catalog"
    assert payload["writes_performed"] is False
    saved_item = next(
        item
        for item in payload["candidates"]
        if item["version_ref"] == receipt["version_ref"]
    )
    assert saved_item["status"] == "current"
    assert saved_item["source_mode"] == "reference_gpx"
    assert saved_item["version_sha256"] == receipt["version_sha256"]
    assert saved_item["review_ready"] == receipt["review_ready"]
    assert saved_item["candidate_only"] is True
    assert saved_item["runtime_safety_truth"] is False

    detail = client.get(
        f"{prefix}/candidates/detail",
        params={"candidate_ref": receipt["version_ref"]},
    )
    assert detail.status_code == 200
    restored = detail.json()
    assert restored["project_id"] == "permission_init_saved_catalog"
    assert restored["status"] == "current"
    assert restored["writes_performed"] is False
    assert restored["draft"]["draft_id"] == draft["draft_id"]
    assert restored["draft"]["reference_reconstruction"] == draft["reference_reconstruction"]
    assert restored["saved_candidate"]["version_ref"] == receipt["version_ref"]
    assert restored["saved_candidate"]["writes_performed"] is False
    assert restored["saved_candidate"]["review_ready"] == receipt["review_ready"]


def test_initial_authoring_seed_is_not_listed_as_saved_candidate(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_empty_catalog")
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)

    catalog = client.get(
        "/admin/pretrip/projects/permission_init_empty_catalog/mission-baseline/candidates"
    )

    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["project_id"] == "permission_init_empty_catalog"
    assert payload["candidates"] == []
    assert payload["writes_performed"] is False


def test_candidate_catalog_marks_non_object_json_files_invalid(
    tmp_path: Path,
) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_non_object_catalog")
    ensure_contextual_permission_authoring(project_root)
    invalid_root = (
        project_root / "candidates" / "mission_baselines" / "baseline.saved-corrupt"
    )
    (invalid_root / "versions").mkdir(parents=True, exist_ok=True)
    (invalid_root / "versions" / "version.array.json").write_text(
        "[]",
        encoding="utf-8",
    )
    (invalid_root / "versions" / "version.null.json").write_text(
        "null",
        encoding="utf-8",
    )
    client = _client(project_root, tmp_path)

    catalog = client.get(
        "/admin/pretrip/projects/permission_init_non_object_catalog/mission-baseline/candidates"
    )

    assert catalog.status_code == 200
    items = catalog.json()["candidates"]
    assert [item["version_ref"] for item in items] == [
        "candidates/mission_baselines/baseline.saved-corrupt/versions/version.array.json",
        "candidates/mission_baselines/baseline.saved-corrupt/versions/version.null.json",
    ]
    assert {item["status"] for item in items} == {"invalid"}
    assert all(item["review_ready"] is False for item in items)


def test_saved_candidate_restore_marks_stale_source_not_review_ready(
    tmp_path: Path,
) -> None:
    project_root = _write_reconstruction_workspace(
        tmp_path,
        project_id="permission_init_saved_stale",
        points=[
            (23.0, 121.0, "2020-12-25T06:00:00+08:00"),
            (23.0, 121.01, "2020-12-25T09:00:00+08:00"),
            (23.0, 121.02, "2020-12-25T16:00:00+08:00"),
        ],
    )
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)
    prefix = "/admin/pretrip/projects/permission_init_saved_stale/mission-baseline"
    request = {
        "mode": "reference_gpx",
        "reference_route_ref": FILTERED_PRIMARY_REF,
        "reference_strategy": "historical_reconstruction",
    }
    generated = client.post(f"{prefix}/generate-draft", json=request)
    assert generated.status_code == 200
    draft = generated.json()
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "permission-init-saved-stale-001",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    receipt = saved.json()
    (project_root / FILTERED_PRIMARY_REF).write_text("<gpx>changed</gpx>", encoding="utf-8")

    catalog = client.get(f"{prefix}/candidates")
    assert catalog.status_code == 200
    saved_item = next(
        item
        for item in catalog.json()["candidates"]
        if item["version_ref"] == receipt["version_ref"]
    )
    assert saved_item["status"] == "stale"
    assert saved_item["review_ready"] is False
    assert "source_stale" in saved_item["reason"]

    detail = client.get(
        f"{prefix}/candidates/detail",
        params={"candidate_ref": receipt["version_ref"]},
    )
    assert detail.status_code == 200
    restored = detail.json()
    assert restored["status"] == "stale"
    assert restored["draft"]["draft_id"] == draft["draft_id"]
    assert restored["saved_candidate"]["version_ref"] == receipt["version_ref"]
    assert restored["saved_candidate"]["review_ready"] is False
    assert restored["saved_candidate"]["writes_performed"] is False
    assert "source_stale" in restored["source_issues"][0]


def test_candidate_catalog_rejects_forged_hash_and_symlink_escape(
    tmp_path: Path,
) -> None:
    project_root = _write_reconstruction_workspace(
        tmp_path,
        project_id="permission_init_candidate_guards",
        points=[
            (23.0, 121.0, "2020-12-25T06:00:00+08:00"),
            (23.0, 121.01, "2020-12-25T09:00:00+08:00"),
            (23.0, 121.02, "2020-12-25T16:00:00+08:00"),
        ],
    )
    ensure_contextual_permission_authoring(project_root)
    client = _client(project_root, tmp_path)
    prefix = "/admin/pretrip/projects/permission_init_candidate_guards/mission-baseline"
    request = {
        "mode": "reference_gpx",
        "reference_route_ref": FILTERED_PRIMARY_REF,
        "reference_strategy": "historical_reconstruction",
    }
    generated = client.post(f"{prefix}/generate-draft", json=request)
    assert generated.status_code == 200
    draft = generated.json()
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "permission-init-candidate-guards-001",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    receipt = saved.json()
    candidate_path = project_root / receipt["version_ref"]
    forged = json.loads(candidate_path.read_text(encoding="utf-8"))
    forged["version_sha256"] = "0" * 64
    candidate_path.write_text(json.dumps(forged), encoding="utf-8")
    outside = tmp_path / "outside_candidate.json"
    outside.write_text(json.dumps(forged), encoding="utf-8")
    symlink_ref = (
        "candidates/mission_baselines/baseline.escape/versions/version.escape.json"
    )
    symlink_path = project_root / symlink_ref
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.symlink_to(outside)

    catalog = client.get(f"{prefix}/candidates")
    assert catalog.status_code == 200
    items = catalog.json()["candidates"]
    forged_item = next(
        item for item in items if item["version_ref"] == receipt["version_ref"]
    )
    symlink_item = next(item for item in items if item["version_ref"] == symlink_ref)
    assert forged_item["status"] == "invalid"
    assert forged_item["review_ready"] is False
    assert forged_item["accepted"] is None
    assert symlink_item["status"] == "invalid"
    assert symlink_item["review_ready"] is False

    forged_detail = client.get(
        f"{prefix}/candidates/detail",
        params={"candidate_ref": receipt["version_ref"]},
    )
    assert forged_detail.status_code == 409
    assert forged_detail.json()["detail"]["code"] == "baseline_candidate_hash_mismatch"
    symlink_detail = client.get(
        f"{prefix}/candidates/detail",
        params={"candidate_ref": symlink_ref},
    )
    assert symlink_detail.status_code == 422
    assert symlink_detail.json()["detail"]["code"] == "unsafe_project_ref"


def test_unreviewed_initialization_refreshes_after_map_artifact_rerun(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_rerun_map")
    route_ref = "normalized/routes/route_summary.json"
    (project_root / "normalized/routes").mkdir(parents=True, exist_ok=True)
    (project_root / route_ref).write_text(
        json.dumps({"route_name": "before", "distance_m": 1}),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["route_summary_ref"] = route_ref
    project_path.write_text(json.dumps(project), encoding="utf-8")
    first = ensure_contextual_permission_authoring(project_root)
    first_ref = first["baseline_candidate_ref"]

    (project_root / route_ref).write_text(
        json.dumps({"route_name": "after", "distance_m": 2}),
        encoding="utf-8",
    )
    second = ensure_contextual_permission_authoring(project_root)
    third = ensure_contextual_permission_authoring(project_root)

    assert second["status"] == "initialized"
    assert second["reviewed"] is False
    assert second["baseline_candidate_ref"] != first_ref
    assert (project_root / first_ref).is_file()
    assert (project_root / second["baseline_candidate_ref"]).is_file()
    assert (project_root / "reviews/contextual_permission_bootstrap_receipt.json").is_file()
    assert (
        project_root
        / "reviews"
        / "contextual_permission_initialization_receipts"
        / f"{json.loads((project_root / second['baseline_candidate_ref']).read_text())['version_id']}.json"
    ).is_file()
    assert "reviewed_mission_baseline_ref" not in json.loads(
        project_path.read_text(encoding="utf-8")
    )
    assert third["status"] == "already_initialized"
    assert third["baseline_candidate_ref"] == second["baseline_candidate_ref"]


def test_unreviewed_refresh_does_not_cross_existing_review_boundary(tmp_path: Path) -> None:
    project_root = _workspace(tmp_path, project_id="permission_init_rerun_reviewed_guard")
    route_ref = "normalized/routes/route_summary.json"
    (project_root / "normalized/routes").mkdir(parents=True, exist_ok=True)
    (project_root / route_ref).write_text(json.dumps({"distance_m": 1}), encoding="utf-8")
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["route_summary_ref"] = route_ref
    project_path.write_text(json.dumps(project), encoding="utf-8")
    first = ensure_contextual_permission_authoring(project_root)
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["reviewed_mission_baseline_ref"] = "outputs/mission_baselines/reviewed.json"
    project["reviewed_mission_baseline_sha256"] = "b" * 64
    project_path.write_text(json.dumps(project), encoding="utf-8")
    (project_root / route_ref).write_text(json.dumps({"distance_m": 2}), encoding="utf-8")

    result = ensure_contextual_permission_authoring(project_root)

    assert result["status"] == "blocked"
    assert result["root_causes"] == ["reviewed_baseline_exists_without_authoring_seed"]
    assert json.loads(project_path.read_text(encoding="utf-8"))["contextual_permission_baseline_candidate_ref"] == first["baseline_candidate_ref"]
