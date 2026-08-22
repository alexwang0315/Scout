from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from scout_companion_match_models import build_companion_capability_capsule
from scout_energy_baseline import build_energy_reserve_baseline
from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyReserveBaseline,
    ScoutEnergyReserveExplanation,
    ScoutEnergyPrivacy,
    WearableActivitySummary,
    aggregate_sha256,
    load_wearable_activity_summaries,
    sha256_file,
)
from scout_wearable_adapters import write_normalized_wearable_imports
from scout_wearable_live_frames import write_field_observations_from_live_frame_fixture
from scout_wearable_provider_transport import (
    assert_provider_live_connector_reference_safe,
    assert_provider_live_credential_vault_reference_safe,
    assert_provider_live_network_policy_reference_safe,
    assert_provider_live_phase1_safety_boundary_reference_safe,
    assert_provider_live_runtime_ingest_boundary_reference_safe,
    load_provider_live_connector_reference,
    load_provider_live_credential_vault_reference,
    load_provider_live_network_policy_reference,
    load_provider_live_phase1_safety_boundary_reference,
    load_provider_live_runtime_ingest_boundary_reference,
    write_provider_live_connector_reference,
    write_provider_live_credential_vault_reference,
    write_provider_live_network_policy_reference,
    write_provider_live_phase1_safety_boundary_reference,
    write_provider_live_runtime_ingest_boundary_reference,
    write_provider_live_executor_fixture_replay,
    write_provider_live_executor_handoff_package,
    write_provider_live_executor_handoff_outbox_index,
    write_provider_live_executor_handoff_pickup_manifest,
    write_provider_live_executor_handoff_fixture_replay,
    write_provider_live_executor_pickup_response_manifest,
    write_provider_live_executor_registration,
    write_provider_live_executor_readiness,
    write_provider_live_executor_response_inbox_index,
    write_provider_live_executor_response_manifest,
    write_provider_live_transport_materialization,
    write_provider_live_transport_response_admission_from_executor_response_manifest,
    write_provider_live_transport_response_admission_from_fixture_replay,
    write_provider_live_transport_preflight,
    write_provider_live_transport_response_admission,
    write_provider_live_transport_request_plan,
    write_provider_live_transport_sync_package,
)
from scout_wearable_raw_importers import (
    inspect_provider_archive,
    write_sanitized_import_batch_from_provider_api_fixture,
    write_sanitized_import_batch_from_provider_archive,
    write_sanitized_import_batch_from_raw_file,
    write_sanitized_import_from_raw_file,
)


ENERGY_BASELINE_FILENAME = "scout_energy_reserve_baseline.json"
ENERGY_EXPLANATION_FILENAME = "scout_energy_reserve_explanation.json"
COMPANION_CAPSULE_FILENAME = "scout_companion_capability_capsule.json"


def build_energy_reserve_from_fixture_paths(
    paths: list[Path],
    *,
    reference_date: date | None = None,
    root: Path | None = None,
) -> ScoutEnergyReserveBaseline:
    activities = load_wearable_activity_summaries(paths, root=root)
    return build_energy_reserve_baseline(activities, reference_date=reference_date)


def write_energy_reserve_artifacts(
    activities: list[WearableActivitySummary],
    *,
    output_dir: Path,
    reference_date: date | None = None,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = build_energy_reserve_baseline(activities, reference_date=reference_date)
    explanation = build_energy_reserve_explanation(baseline)
    companion_capsule = build_companion_capability_capsule(activities)

    baseline_path = output_dir / ENERGY_BASELINE_FILENAME
    explanation_path = output_dir / ENERGY_EXPLANATION_FILENAME
    companion_path = output_dir / COMPANION_CAPSULE_FILENAME
    _write_json(baseline_path, baseline.model_dump(mode="json"))
    _write_json(explanation_path, explanation.model_dump(mode="json"))
    _write_json(companion_path, companion_capsule.model_dump(mode="json"))
    return {
        "artifact_kind": "scout_energy_reserve_artifact_export",
        "source_provider": baseline.source_provider,
        "source_path": baseline.source_path,
        "sha256": baseline.sha256,
        "baseline_path": str(baseline_path),
        "explanation_path": str(explanation_path),
        "companion_capsule_path": str(companion_path),
        "baseline": baseline.model_dump(mode="json"),
        "explanation": explanation.model_dump(mode="json"),
        "companion_capsule": companion_capsule.model_dump(mode="json"),
        "data_quality": baseline.data_quality.model_dump(mode="json"),
        "privacy": baseline.privacy.model_dump(mode="json"),
        "boundary": baseline.boundary.model_dump(mode="json"),
    }


def write_energy_reserve_artifacts_from_paths(
    paths: list[Path],
    *,
    output_dir: Path,
    reference_date: date | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    activities = load_wearable_activity_summaries(paths, root=root)
    return write_energy_reserve_artifacts(
        activities,
        output_dir=output_dir,
        reference_date=reference_date,
    )


def write_energy_reserve_artifacts_from_provider_sync_package(
    sync_package_path: Path,
    *,
    output_dir: Path,
    reference_date: date | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    sync_package = _load_provider_sync_package(sync_package_path)
    _assert_provider_sync_package_safe(sync_package)
    activity_paths = _activity_paths_from_provider_sync_package(
        sync_package,
        root=root,
    )
    energy_artifacts = write_energy_reserve_artifacts_from_paths(
        activity_paths,
        output_dir=output_dir,
        reference_date=reference_date,
        root=root,
    )
    data_quality = ScoutEnergyDataQuality.model_validate(energy_artifacts["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "energy artifacts were built from a local provider sync package",
            "provider sync package is a local handoff and not a network sync",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    output_sha = aggregate_sha256(
        [
            sync_package["sha256"],
            energy_artifacts["sha256"],
            {
                "artifact": "energy_reserve_provider_sync_package_build",
                "activity_count": len(activity_paths),
            },
        ]
    )
    return {
        "artifact_kind": "scout_energy_reserve_provider_sync_package_build_result",
        "artifact_version": "energy_reserve_provider_sync_package_build_result.v1",
        "source_provider": sync_package["source_provider"],
        "source_path": str(sync_package_path),
        "sha256": output_sha,
        "sync_package": {
            "artifact_kind": sync_package["artifact_kind"],
            "source_provider": sync_package["source_provider"],
            "source_path": str(sync_package_path),
            "sha256": sync_package["sha256"],
            "normalized_summary_count": sync_package["normalized_summary_count"],
        },
        "activity_paths": [str(path) for path in activity_paths],
        "baseline_path": energy_artifacts["baseline_path"],
        "explanation_path": energy_artifacts["explanation_path"],
        "companion_capsule_path": energy_artifacts["companion_capsule_path"],
        "energy_artifacts": energy_artifacts,
        "transport": {
            "transport_mode": "local_sync_package_energy_build_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_rehearsal(
    *,
    request_plan_path: Path,
    executor_registration_path: Path,
    response_fixture_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    reference_date: date | None = None,
    root: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    readiness_result = write_provider_live_executor_readiness(
        request_plan_path=request_plan_path,
        executor_registration_path=executor_registration_path,
        output_path=output_dir / "provider_live_executor_readiness.json",
    )
    readiness = readiness_result["executor_readiness"]
    if "live_provider_executor_not_registered" in readiness["execution_blockers"]:
        raise ValueError("provider live executor rehearsal requires registered executor metadata")

    handoff_result = write_provider_live_executor_handoff_package(
        request_plan_path=request_plan_path,
        executor_registration_path=executor_registration_path,
        output_path=output_dir / "provider_live_executor_handoff.json",
    )
    response_manifest_result = write_provider_live_executor_response_manifest(
        handoff_package_path=Path(handoff_result["executor_handoff_path"]),
        response_payload_path=response_fixture_path,
        output_path=output_dir / "provider_live_executor_response_manifest.json",
    )
    fixture_replay_result = write_provider_live_executor_handoff_fixture_replay(
        handoff_package_path=Path(handoff_result["executor_handoff_path"]),
        response_fixture_path=response_fixture_path,
        output_path=output_dir / "provider_live_executor_fixture_replay.json",
    )
    admission_result = write_provider_live_transport_response_admission_from_executor_response_manifest(
        executor_response_manifest_path=Path(response_manifest_result["executor_response_manifest_path"]),
        output_dir=output_dir / "sanitized-imports",
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        admission_output_path=output_dir / "provider_live_response_admission.json",
        activity_type=activity_type,
        overwrite=overwrite,
    )
    materialization_result = write_provider_live_transport_materialization(
        admission_path=Path(admission_result["admission_path"]),
        output_dir=output_dir / "normalized",
        materialization_output_path=output_dir / "provider_live_materialization.json",
        root=root,
        overwrite=overwrite,
    )
    sync_package_result = write_provider_live_transport_sync_package(
        materialization_path=Path(materialization_result["materialization_path"]),
        package_output_path=output_dir / "provider_live_sync_package.json",
        root=root,
    )
    energy_build_result = write_energy_reserve_artifacts_from_provider_sync_package(
        Path(sync_package_result["sync_package_path"]),
        output_dir=output_dir / "energy",
        reference_date=reference_date,
        root=root,
    )
    rehearsal = _provider_live_executor_rehearsal_artifact(
        readiness=readiness,
        fixture_replay=fixture_replay_result["executor_fixture_replay"],
        response_manifest=response_manifest_result["executor_response_manifest"],
        admission=admission_result["admission"],
        materialization=materialization_result["materialization"],
        sync_package=sync_package_result["sync_package"],
        energy_build=energy_build_result,
        paths={
            "executor_readiness_path": readiness_result["executor_readiness_path"],
            "executor_handoff_path": handoff_result["executor_handoff_path"],
            "executor_response_manifest_path": response_manifest_result["executor_response_manifest_path"],
            "executor_fixture_replay_path": fixture_replay_result["executor_fixture_replay_path"],
            "admission_path": admission_result["admission_path"],
            "materialization_path": materialization_result["materialization_path"],
            "sync_package_path": sync_package_result["sync_package_path"],
            "baseline_path": energy_build_result["baseline_path"],
            "explanation_path": energy_build_result["explanation_path"],
            "companion_capsule_path": energy_build_result["companion_capsule_path"],
        },
    )
    rehearsal_path = output_dir / "provider_live_executor_rehearsal.json"
    _write_json(rehearsal_path, rehearsal)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_rehearsal_result",
        "artifact_version": "wearable_provider_live_executor_rehearsal_result.v1",
        "source_provider": rehearsal["source_provider"],
        "source_path": rehearsal["source_path"],
        "sha256": rehearsal["sha256"],
        "executor_rehearsal_path": str(rehearsal_path),
        "executor_readiness_path": readiness_result["executor_readiness_path"],
        "executor_handoff_path": handoff_result["executor_handoff_path"],
        "executor_response_manifest_path": response_manifest_result["executor_response_manifest_path"],
        "executor_fixture_replay_path": fixture_replay_result["executor_fixture_replay_path"],
        "admission_path": admission_result["admission_path"],
        "materialization_path": materialization_result["materialization_path"],
        "sync_package_path": sync_package_result["sync_package_path"],
        "baseline_path": energy_build_result["baseline_path"],
        "explanation_path": energy_build_result["explanation_path"],
        "companion_capsule_path": energy_build_result["companion_capsule_path"],
        "executor_rehearsal": rehearsal,
        "data_quality": rehearsal["data_quality"],
        "privacy": rehearsal["privacy"],
        "boundary": rehearsal["boundary"],
        "mutation": {
            "executor_rehearsal_artifact_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_consumption(
    *,
    executor_response_manifest_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    reference_date: date | None = None,
    root: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    admission_result = write_provider_live_transport_response_admission_from_executor_response_manifest(
        executor_response_manifest_path=executor_response_manifest_path,
        output_dir=output_dir / "sanitized-imports",
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        admission_output_path=output_dir / "provider_live_executor_response_admission.json",
        activity_type=activity_type,
        overwrite=overwrite,
    )
    materialization_result = write_provider_live_transport_materialization(
        admission_path=Path(admission_result["admission_path"]),
        output_dir=output_dir / "normalized",
        materialization_output_path=output_dir / "provider_live_executor_response_materialization.json",
        root=root,
        overwrite=overwrite,
    )
    sync_package_result = write_provider_live_transport_sync_package(
        materialization_path=Path(materialization_result["materialization_path"]),
        package_output_path=output_dir / "provider_live_executor_response_sync_package.json",
        root=root,
    )
    energy_build_result = write_energy_reserve_artifacts_from_provider_sync_package(
        Path(sync_package_result["sync_package_path"]),
        output_dir=output_dir / "energy",
        reference_date=reference_date,
        root=root,
    )
    consumption = _provider_live_executor_response_consumption_artifact(
        executor_response_manifest=admission_result["executor_response_manifest"],
        admission=admission_result["admission"],
        materialization=materialization_result["materialization"],
        sync_package=sync_package_result["sync_package"],
        energy_build=energy_build_result,
        paths={
            "executor_response_manifest_path": str(executor_response_manifest_path),
            "admission_path": admission_result["admission_path"],
            "materialization_path": materialization_result["materialization_path"],
            "sync_package_path": sync_package_result["sync_package_path"],
            "baseline_path": energy_build_result["baseline_path"],
            "explanation_path": energy_build_result["explanation_path"],
            "companion_capsule_path": energy_build_result["companion_capsule_path"],
        },
    )
    consumption_path = output_dir / "provider_live_executor_response_consumption.json"
    _write_json(consumption_path, consumption)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_consumption_result",
        "artifact_version": "wearable_provider_live_executor_response_consumption_result.v1",
        "source_provider": consumption["source_provider"],
        "source_path": consumption["source_path"],
        "sha256": consumption["sha256"],
        "executor_response_consumption_path": str(consumption_path),
        "executor_response_manifest_path": str(executor_response_manifest_path),
        "admission_path": admission_result["admission_path"],
        "materialization_path": materialization_result["materialization_path"],
        "sync_package_path": sync_package_result["sync_package_path"],
        "baseline_path": energy_build_result["baseline_path"],
        "explanation_path": energy_build_result["explanation_path"],
        "companion_capsule_path": energy_build_result["companion_capsule_path"],
        "executor_response_consumption": consumption,
        "data_quality": consumption["data_quality"],
        "privacy": consumption["privacy"],
        "boundary": consumption["boundary"],
        "mutation": {
            "executor_response_consumption_artifact_written": True,
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_pickup_response_consumption(
    *,
    executor_response_manifest_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    reference_date: date | None = None,
    root: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    manifest = _load_pickup_bound_executor_response_manifest(executor_response_manifest_path)
    _assert_pickup_bound_executor_response_manifest_safe(manifest)
    consumption_result = write_provider_live_executor_response_consumption(
        executor_response_manifest_path=executor_response_manifest_path,
        output_dir=output_dir,
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        reference_date=reference_date,
        root=root,
        activity_type=activity_type,
        overwrite=overwrite,
    )
    pickup_consumption = _provider_live_executor_pickup_response_consumption_artifact(
        manifest=manifest,
        manifest_path=executor_response_manifest_path,
        consumption=consumption_result["executor_response_consumption"],
        consumption_path=consumption_result["executor_response_consumption_path"],
    )
    pickup_consumption_path = output_dir / "provider_live_executor_pickup_response_consumption.json"
    _write_json(pickup_consumption_path, pickup_consumption)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_response_consumption_result",
        "artifact_version": "wearable_provider_live_executor_pickup_response_consumption_result.v1",
        "source_provider": pickup_consumption["source_provider"],
        "source_path": pickup_consumption["source_path"],
        "sha256": pickup_consumption["sha256"],
        "executor_pickup_response_consumption_path": str(pickup_consumption_path),
        "executor_response_consumption_path": consumption_result["executor_response_consumption_path"],
        "executor_response_manifest_path": str(executor_response_manifest_path),
        "admission_path": consumption_result["admission_path"],
        "materialization_path": consumption_result["materialization_path"],
        "sync_package_path": consumption_result["sync_package_path"],
        "baseline_path": consumption_result["baseline_path"],
        "explanation_path": consumption_result["explanation_path"],
        "companion_capsule_path": consumption_result["companion_capsule_path"],
        "executor_pickup_response_consumption": pickup_consumption,
        "executor_response_consumption": consumption_result["executor_response_consumption"],
        "data_quality": pickup_consumption["data_quality"],
        "privacy": pickup_consumption["privacy"],
        "boundary": pickup_consumption["boundary"],
        "mutation": {
            "executor_pickup_response_consumption_artifact_written": True,
            "executor_response_consumption_artifact_written": True,
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_pickup_response_consumption_receipt(
    *,
    pickup_response_consumption_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    pickup_consumption = _load_executor_pickup_response_consumption(
        pickup_response_consumption_path
    )
    _assert_executor_pickup_response_consumption_safe(pickup_consumption)
    output_path = output_path or (
        pickup_response_consumption_path.parent
        / "provider_live_executor_pickup_response_consumption_receipt.json"
    )
    if output_path.resolve() == pickup_response_consumption_path.resolve():
        raise ValueError("pickup response consumption receipt cannot overwrite consumption artifact")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = _provider_live_executor_pickup_response_consumption_receipt_artifact(
        pickup_consumption=pickup_consumption,
        pickup_consumption_path=pickup_response_consumption_path,
    )
    _write_json(output_path, receipt)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_response_consumption_receipt_result",
        "artifact_version": "wearable_provider_live_executor_pickup_response_consumption_receipt_result.v1",
        "source_provider": receipt["source_provider"],
        "source_path": receipt["source_path"],
        "sha256": receipt["sha256"],
        "executor_pickup_response_consumption_receipt_path": str(output_path),
        "executor_pickup_response_consumption_receipt": receipt,
        "data_quality": receipt["data_quality"],
        "privacy": receipt["privacy"],
        "boundary": receipt["boundary"],
        "mutation": {
            "executor_pickup_response_consumption_receipt_artifact_written": True,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_pickup_status_snapshot(
    *,
    pickup_manifest_path: Path,
    executor_response_manifest_path: Path | None = None,
    pickup_response_consumption_path: Path | None = None,
    pickup_response_receipt_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    pickup_manifest = _load_executor_handoff_pickup_manifest(pickup_manifest_path)
    _assert_executor_handoff_pickup_manifest_safe_for_status(pickup_manifest)

    response_manifest = None
    if executor_response_manifest_path is not None:
        response_manifest = _load_pickup_bound_executor_response_manifest(
            executor_response_manifest_path
        )
        _assert_pickup_bound_executor_response_manifest_safe(response_manifest)
        if response_manifest["pickup_manifest"]["sha256"] != pickup_manifest["sha256"]:
            raise ValueError("pickup status snapshot response manifest pickup sha256 mismatch")

    pickup_consumption = None
    if pickup_response_consumption_path is not None:
        if response_manifest is None:
            raise ValueError("pickup status snapshot consumption requires response manifest evidence")
        pickup_consumption = _load_executor_pickup_response_consumption(
            pickup_response_consumption_path
        )
        _assert_executor_pickup_response_consumption_safe(pickup_consumption)
        if pickup_consumption["pickup_manifest"]["sha256"] != pickup_manifest["sha256"]:
            raise ValueError("pickup status snapshot consumption pickup sha256 mismatch")
        if pickup_consumption["executor_response_manifest"]["sha256"] != response_manifest["sha256"]:
            raise ValueError("pickup status snapshot consumption response manifest sha256 mismatch")

    pickup_receipt = None
    if pickup_response_receipt_path is not None:
        if pickup_consumption is None:
            raise ValueError("pickup status snapshot receipt requires consumption evidence")
        pickup_receipt = _load_executor_pickup_response_consumption_receipt(
            pickup_response_receipt_path
        )
        _assert_executor_pickup_response_consumption_receipt_safe(pickup_receipt)
        if pickup_receipt["pickup_manifest"]["sha256"] != pickup_manifest["sha256"]:
            raise ValueError("pickup status snapshot receipt pickup sha256 mismatch")
        if (
            pickup_receipt["pickup_response_consumption"]["sha256"]
            != pickup_consumption["sha256"]
        ):
            raise ValueError("pickup status snapshot receipt consumption sha256 mismatch")

    output_path = output_path or (
        pickup_manifest_path.parent / "provider_live_executor_pickup_status_snapshot.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = _provider_live_executor_pickup_status_snapshot_artifact(
        pickup_manifest=pickup_manifest,
        pickup_manifest_path=pickup_manifest_path,
        response_manifest=response_manifest,
        response_manifest_path=executor_response_manifest_path,
        pickup_consumption=pickup_consumption,
        pickup_consumption_path=pickup_response_consumption_path,
        pickup_receipt=pickup_receipt,
        pickup_receipt_path=pickup_response_receipt_path,
    )
    _write_json(output_path, snapshot)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_status_snapshot_result",
        "artifact_version": "wearable_provider_live_executor_pickup_status_snapshot_result.v1",
        "source_provider": snapshot["source_provider"],
        "source_path": snapshot["source_path"],
        "sha256": snapshot["sha256"],
        "executor_pickup_status_snapshot_path": str(output_path),
        "pickup_lifecycle_status": snapshot["status"]["pickup_lifecycle_status"],
        "executor_pickup_status_snapshot": snapshot,
        "data_quality": snapshot["data_quality"],
        "privacy": snapshot["privacy"],
        "boundary": snapshot["boundary"],
        "mutation": {
            "executor_pickup_status_snapshot_artifact_written": True,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_lifecycle_audit(
    *,
    pickup_status_snapshot_path: Path,
    inbox_status_snapshot_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    pickup_status = _load_executor_pickup_status_snapshot(pickup_status_snapshot_path)
    _assert_executor_pickup_status_snapshot_safe(pickup_status)
    inbox_status = None
    if inbox_status_snapshot_path is not None:
        inbox_status = _load_executor_response_inbox_status_snapshot(inbox_status_snapshot_path)
        _assert_executor_response_inbox_status_snapshot_safe(inbox_status)
        if inbox_status["source_provider"] != pickup_status["source_provider"]:
            raise ValueError("executor lifecycle audit provider mismatch")
    output_path = output_path or (
        pickup_status_snapshot_path.parent / "provider_live_executor_lifecycle_audit.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit = _provider_live_executor_lifecycle_audit_artifact(
        pickup_status=pickup_status,
        pickup_status_path=pickup_status_snapshot_path,
        inbox_status=inbox_status,
        inbox_status_path=inbox_status_snapshot_path,
    )
    _write_json(output_path, audit)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_lifecycle_audit_result",
        "artifact_version": "wearable_provider_live_executor_lifecycle_audit_result.v1",
        "source_provider": audit["source_provider"],
        "source_path": audit["source_path"],
        "sha256": audit["sha256"],
        "executor_lifecycle_audit_path": str(output_path),
        "local_executor_lifecycle_status": audit["lifecycle"][
            "local_executor_lifecycle_status"
        ],
        "executor_lifecycle_audit": audit,
        "data_quality": audit["data_quality"],
        "privacy": audit["privacy"],
        "boundary": audit["boundary"],
        "mutation": {
            "executor_lifecycle_audit_artifact_written": True,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_production_readiness_gate(
    *,
    lifecycle_audit_path: Path,
    connector_reference_path: Path | None = None,
    credential_vault_reference_path: Path | None = None,
    network_policy_reference_path: Path | None = None,
    runtime_ingest_boundary_reference_path: Path | None = None,
    phase1_safety_boundary_reference_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    lifecycle_audit = _load_executor_lifecycle_audit(lifecycle_audit_path)
    _assert_executor_lifecycle_audit_safe(lifecycle_audit)
    connector_reference = None
    if connector_reference_path is not None:
        connector_reference = load_provider_live_connector_reference(connector_reference_path)
        assert_provider_live_connector_reference_safe(connector_reference)
        if connector_reference["source_provider"] != lifecycle_audit["source_provider"]:
            raise ValueError("executor production readiness gate provider mismatch")
    credential_vault_reference = None
    if credential_vault_reference_path is not None:
        credential_vault_reference = load_provider_live_credential_vault_reference(
            credential_vault_reference_path
        )
        assert_provider_live_credential_vault_reference_safe(credential_vault_reference)
        if credential_vault_reference["source_provider"] != lifecycle_audit["source_provider"]:
            raise ValueError("executor production readiness gate provider mismatch")
    network_policy_reference = None
    if network_policy_reference_path is not None:
        network_policy_reference = load_provider_live_network_policy_reference(
            network_policy_reference_path
        )
        assert_provider_live_network_policy_reference_safe(network_policy_reference)
        if network_policy_reference["source_provider"] != lifecycle_audit["source_provider"]:
            raise ValueError("executor production readiness gate provider mismatch")
    runtime_ingest_boundary_reference = None
    if runtime_ingest_boundary_reference_path is not None:
        runtime_ingest_boundary_reference = load_provider_live_runtime_ingest_boundary_reference(
            runtime_ingest_boundary_reference_path
        )
        assert_provider_live_runtime_ingest_boundary_reference_safe(
            runtime_ingest_boundary_reference
        )
        if runtime_ingest_boundary_reference["source_provider"] != lifecycle_audit["source_provider"]:
            raise ValueError("executor production readiness gate provider mismatch")
    phase1_safety_boundary_reference = None
    if phase1_safety_boundary_reference_path is not None:
        phase1_safety_boundary_reference = load_provider_live_phase1_safety_boundary_reference(
            phase1_safety_boundary_reference_path
        )
        assert_provider_live_phase1_safety_boundary_reference_safe(
            phase1_safety_boundary_reference
        )
        if phase1_safety_boundary_reference["source_provider"] != lifecycle_audit["source_provider"]:
            raise ValueError("executor production readiness gate provider mismatch")
    output_path = output_path or (
        lifecycle_audit_path.parent / "provider_live_executor_production_readiness_gate.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gate = _provider_live_executor_production_readiness_gate_artifact(
        lifecycle_audit=lifecycle_audit,
        lifecycle_audit_path=lifecycle_audit_path,
        connector_reference=connector_reference,
        connector_reference_path=connector_reference_path,
        credential_vault_reference=credential_vault_reference,
        credential_vault_reference_path=credential_vault_reference_path,
        network_policy_reference=network_policy_reference,
        network_policy_reference_path=network_policy_reference_path,
        runtime_ingest_boundary_reference=runtime_ingest_boundary_reference,
        runtime_ingest_boundary_reference_path=runtime_ingest_boundary_reference_path,
        phase1_safety_boundary_reference=phase1_safety_boundary_reference,
        phase1_safety_boundary_reference_path=phase1_safety_boundary_reference_path,
    )
    _write_json(output_path, gate)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_production_readiness_gate_result",
        "artifact_version": "wearable_provider_live_executor_production_readiness_gate_result.v1",
        "source_provider": gate["source_provider"],
        "source_path": gate["source_path"],
        "sha256": gate["sha256"],
        "executor_production_readiness_gate_path": str(output_path),
        "production_provider_execution_ready": gate["readiness"][
            "production_provider_execution_ready"
        ],
        "production_blockers": gate["readiness"]["production_blockers"],
        "executor_production_readiness_gate": gate,
        "data_quality": gate["data_quality"],
        "privacy": gate["privacy"],
        "boundary": gate["boundary"],
        "mutation": {
            "executor_production_readiness_gate_artifact_written": True,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_inbox_consumption(
    *,
    inbox_index_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    manifest_source_path: Path | None = None,
    reference_date: date | None = None,
    root: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    inbox_index = _load_executor_response_inbox_index(inbox_index_path)
    _assert_executor_response_inbox_index_safe(inbox_index)
    selected_entry = _select_executor_response_inbox_entry(
        inbox_index,
        manifest_source_path=manifest_source_path,
    )
    selected_manifest_path = Path(selected_entry["source_path"])
    if sha256_file(selected_manifest_path) != selected_entry["file_sha256"]:
        raise ValueError("executor response inbox manifest file sha256 mismatch")
    consumption_result = write_provider_live_executor_response_consumption(
        executor_response_manifest_path=selected_manifest_path,
        output_dir=output_dir,
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        reference_date=reference_date,
        root=root,
        activity_type=activity_type,
        overwrite=overwrite,
    )
    inbox_consumption = _provider_live_executor_response_inbox_consumption_artifact(
        inbox_index=inbox_index,
        inbox_index_path=inbox_index_path,
        selected_entry=selected_entry,
        consumption=consumption_result["executor_response_consumption"],
        consumption_path=consumption_result["executor_response_consumption_path"],
    )
    inbox_consumption_path = output_dir / "provider_live_executor_response_inbox_consumption.json"
    _write_json(inbox_consumption_path, inbox_consumption)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_consumption_result",
        "artifact_version": "wearable_provider_live_executor_response_inbox_consumption_result.v1",
        "source_provider": inbox_consumption["source_provider"],
        "source_path": inbox_consumption["source_path"],
        "sha256": inbox_consumption["sha256"],
        "executor_response_inbox_consumption_path": str(inbox_consumption_path),
        "executor_response_consumption_path": consumption_result["executor_response_consumption_path"],
        "executor_response_manifest_path": str(selected_manifest_path),
        "admission_path": consumption_result["admission_path"],
        "materialization_path": consumption_result["materialization_path"],
        "sync_package_path": consumption_result["sync_package_path"],
        "baseline_path": consumption_result["baseline_path"],
        "explanation_path": consumption_result["explanation_path"],
        "companion_capsule_path": consumption_result["companion_capsule_path"],
        "executor_response_inbox_consumption": inbox_consumption,
        "executor_response_consumption": consumption_result["executor_response_consumption"],
        "data_quality": inbox_consumption["data_quality"],
        "privacy": inbox_consumption["privacy"],
        "boundary": inbox_consumption["boundary"],
        "mutation": {
            "executor_response_inbox_consumption_artifact_written": True,
            "executor_response_consumption_artifact_written": True,
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_inbox_batch_consumption(
    *,
    inbox_index_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    reference_date: date | None = None,
    root: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    inbox_index = _load_executor_response_inbox_index(inbox_index_path)
    _assert_executor_response_inbox_index_safe(inbox_index)
    entries = _eligible_executor_response_inbox_entries(inbox_index)
    if not entries:
        raise ValueError("executor response inbox index has no eligible manifests to batch consume")
    output_dir.mkdir(parents=True, exist_ok=True)
    consumption_results: list[dict[str, Any]] = []
    for entry in entries:
        manifest_path = Path(entry["source_path"])
        if sha256_file(manifest_path) != entry["file_sha256"]:
            raise ValueError("executor response inbox manifest file sha256 mismatch")
        suffix = entry["file_sha256"][:12]
        result = write_provider_live_executor_response_consumption(
            executor_response_manifest_path=manifest_path,
            output_dir=output_dir / f"manifest-{suffix}",
            activity_id_prefix=f"{activity_id_prefix}.{suffix}",
            admitted_capabilities=admitted_capabilities,
            reference_date=reference_date,
            root=root,
            activity_type=activity_type,
            overwrite=overwrite,
        )
        consumption_results.append(result)
    batch = _provider_live_executor_response_inbox_batch_consumption_artifact(
        inbox_index=inbox_index,
        inbox_index_path=inbox_index_path,
        consumption_results=consumption_results,
    )
    batch_path = output_dir / "provider_live_executor_response_inbox_batch_consumption.json"
    _write_json(batch_path, batch)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_batch_consumption_result",
        "artifact_version": "wearable_provider_live_executor_response_inbox_batch_consumption_result.v1",
        "source_provider": batch["source_provider"],
        "source_path": batch["source_path"],
        "sha256": batch["sha256"],
        "executor_response_inbox_batch_consumption_path": str(batch_path),
        "consumed_manifest_count": batch["batch"]["consumed_manifest_count"],
        "executor_response_consumption_paths": [
            result["executor_response_consumption_path"]
            for result in consumption_results
        ],
        "baseline_paths": [result["baseline_path"] for result in consumption_results],
        "executor_response_inbox_batch_consumption": batch,
        "data_quality": batch["data_quality"],
        "privacy": batch["privacy"],
        "boundary": batch["boundary"],
        "mutation": {
            "executor_response_inbox_batch_consumption_artifact_written": True,
            "executor_response_consumption_artifacts_written": True,
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_inbox_batch_receipt(
    *,
    batch_consumption_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    batch_consumption = _load_executor_response_inbox_batch_consumption(batch_consumption_path)
    _assert_executor_response_inbox_batch_consumption_safe(batch_consumption)
    output_path = output_path or (
        batch_consumption_path.parent / "provider_live_executor_response_inbox_batch_receipt.json"
    )
    if output_path.resolve() == batch_consumption_path.resolve():
        raise ValueError("executor response inbox batch receipt cannot overwrite batch consumption artifact")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = _provider_live_executor_response_inbox_batch_receipt_artifact(
        batch_consumption=batch_consumption,
        batch_consumption_path=batch_consumption_path,
    )
    _write_json(output_path, receipt)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_batch_receipt_result",
        "artifact_version": "wearable_provider_live_executor_response_inbox_batch_receipt_result.v1",
        "source_provider": receipt["source_provider"],
        "source_path": receipt["source_path"],
        "sha256": receipt["sha256"],
        "executor_response_inbox_batch_receipt_path": str(output_path),
        "consumed_manifest_count": receipt["batch_consumption"]["consumed_manifest_count"],
        "executor_response_inbox_batch_receipt": receipt,
        "data_quality": receipt["data_quality"],
        "privacy": receipt["privacy"],
        "boundary": receipt["boundary"],
        "mutation": {
            "executor_response_inbox_batch_receipt_artifact_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_inbox_status_snapshot(
    *,
    inbox_index_path: Path,
    batch_consumption_path: Path | None = None,
    batch_receipt_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    inbox_index = _load_executor_response_inbox_index(inbox_index_path)
    _assert_executor_response_inbox_index_safe(inbox_index)
    batch_consumption = None
    if batch_consumption_path is not None:
        batch_consumption = _load_executor_response_inbox_batch_consumption(batch_consumption_path)
        _assert_executor_response_inbox_batch_consumption_safe(batch_consumption)
    batch_receipt = None
    if batch_receipt_path is not None:
        batch_receipt = _load_executor_response_inbox_batch_receipt(batch_receipt_path)
        _assert_executor_response_inbox_batch_receipt_safe(batch_receipt)
    output_path = output_path or (
        inbox_index_path.parent / "provider_live_executor_response_inbox_status_snapshot.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = _provider_live_executor_response_inbox_status_snapshot_artifact(
        inbox_index=inbox_index,
        inbox_index_path=inbox_index_path,
        batch_consumption=batch_consumption,
        batch_consumption_path=batch_consumption_path,
        batch_receipt=batch_receipt,
        batch_receipt_path=batch_receipt_path,
    )
    _write_json(output_path, snapshot)
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_status_snapshot_result",
        "artifact_version": "wearable_provider_live_executor_response_inbox_status_snapshot_result.v1",
        "source_provider": snapshot["source_provider"],
        "source_path": snapshot["source_path"],
        "sha256": snapshot["sha256"],
        "executor_response_inbox_status_snapshot_path": str(output_path),
        "manifest_status_counts": snapshot["manifest_status_counts"],
        "executor_response_inbox_status_snapshot": snapshot,
        "data_quality": snapshot["data_quality"],
        "privacy": snapshot["privacy"],
        "boundary": snapshot["boundary"],
        "mutation": {
            "executor_response_inbox_status_snapshot_artifact_written": True,
            "source_file_mutated": False,
            "inbox_file_mutated": False,
            "inbox_file_moved": False,
            "inbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def run_energy_reserve_cli(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "normalize":
        result = write_normalized_wearable_imports(
            list(args.input),
            output_dir=args.output_dir,
            root=args.root,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-raw":
        result = write_sanitized_import_from_raw_file(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id=args.activity_id,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-raw-batch":
        result = write_sanitized_import_batch_from_raw_file(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "summarize-provider-archive":
        result = write_sanitized_import_batch_from_provider_archive(
            args.input,
            source_format=args.source_format,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "inspect-provider-archive":
        result = inspect_provider_archive(
            args.input,
            source_format=args.source_format,
        )
        return 0, result
    if args.command == "summarize-provider-api-fixture":
        result = write_sanitized_import_batch_from_provider_api_fixture(
            args.input,
            provider=args.provider,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            activity_type=args.activity_type,
            explicit_consent=args.explicit_consent,
            auth_token_ref=args.auth_token_ref,
            scopes=list(args.scope or []),
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-preflight":
        result = write_provider_live_transport_preflight(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            account_ref=args.account_ref,
            device_ref=args.device_ref,
            auth_token_ref=args.auth_token_ref,
            scopes=list(args.scope or []),
            requested_capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-credential-vault-reference":
        result = write_provider_live_credential_vault_reference(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            vault_ref=args.vault_ref,
            account_ref=args.account_ref,
            device_ref=args.device_ref,
            token_ref=args.token_ref,
            scopes=list(args.scope or []),
            capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-connector-reference":
        result = write_provider_live_connector_reference(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            connector_kind=args.connector_kind,
            connector_ref=args.connector_ref,
            connector_version=args.connector_version,
            connector_binary_ref=args.connector_binary_ref,
            supported_capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-network-policy-reference":
        result = write_provider_live_network_policy_reference(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            policy_ref=args.policy_ref,
            endpoint_ref=args.endpoint_ref,
            egress_profile_ref=args.egress_profile_ref,
            tls_profile_ref=args.tls_profile_ref,
            allowed_capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-runtime-ingest-boundary-reference":
        result = write_provider_live_runtime_ingest_boundary_reference(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            runtime_boundary_ref=args.runtime_boundary_ref,
            runtime_channel_ref=args.runtime_channel_ref,
            allowed_artifact_kinds=list(args.artifact_kind or []),
            handoff_mode=args.handoff_mode,
        )
        return 0, result
    if args.command == "provider-live-phase1-safety-boundary-reference":
        result = write_provider_live_phase1_safety_boundary_reference(
            provider=args.provider,
            output_path=args.output,
            explicit_consent=args.explicit_consent,
            phase1_boundary_ref=args.phase1_boundary_ref,
            phase1_state_ref=args.phase1_state_ref,
            advisory_channel_ref=args.advisory_channel_ref,
            allowed_artifact_kinds=list(args.artifact_kind or []),
            handoff_mode=args.handoff_mode,
        )
        return 0, result
    if args.command == "provider-live-request-plan":
        result = write_provider_live_transport_request_plan(
            preflight_path=args.preflight,
            output_path=args.output,
            window_start_date=args.window_start_date,
            window_end_date=args.window_end_date,
            requested_capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-register-executor":
        result = write_provider_live_executor_registration(
            preflight_path=args.preflight,
            output_path=args.output,
            executor_kind=args.executor_kind,
            executor_ref=args.executor_ref,
            supported_capabilities=list(args.capability or []),
        )
        return 0, result
    if args.command == "provider-live-executor-readiness":
        result = write_provider_live_executor_readiness(
            request_plan_path=args.request_plan,
            executor_registration_path=args.executor_registration,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-handoff":
        result = write_provider_live_executor_handoff_package(
            request_plan_path=args.request_plan,
            executor_registration_path=args.executor_registration,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-index-executor-handoff-outbox":
        result = write_provider_live_executor_handoff_outbox_index(
            outbox_dir=args.outbox_dir,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-handoff-pickup-manifest":
        result = write_provider_live_executor_handoff_pickup_manifest(
            outbox_index_path=args.outbox_index,
            output_path=args.output,
            handoff_source_path=args.handoff_source_path,
        )
        return 0, result
    if args.command == "provider-live-fixture-replay":
        result = write_provider_live_executor_fixture_replay(
            request_plan_path=args.request_plan,
            executor_registration_path=args.executor_registration,
            response_fixture_path=args.response_fixture,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-handoff-fixture-replay":
        result = write_provider_live_executor_handoff_fixture_replay(
            handoff_package_path=args.executor_handoff,
            response_fixture_path=args.response_fixture,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-pickup-response-manifest":
        result = write_provider_live_executor_pickup_response_manifest(
            pickup_manifest_path=args.pickup_manifest,
            response_payload_path=args.response_payload,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-response-manifest":
        result = write_provider_live_executor_response_manifest(
            handoff_package_path=args.executor_handoff,
            response_payload_path=args.response_payload,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-index-executor-response-inbox":
        result = write_provider_live_executor_response_inbox_index(
            inbox_dir=args.inbox_dir,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-response-admit":
        result = write_provider_live_transport_response_admission_from_executor_response_manifest(
            executor_response_manifest_path=args.executor_response_manifest,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            admission_output_path=args.output,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-consume-executor-response":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_provider_live_executor_response_consumption(
            executor_response_manifest_path=args.executor_response_manifest,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            reference_date=reference_date,
            root=args.root,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-consume-executor-pickup-response":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_provider_live_executor_pickup_response_consumption(
            executor_response_manifest_path=args.executor_response_manifest,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            reference_date=reference_date,
            root=args.root,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-executor-pickup-response-consumption-receipt":
        result = write_provider_live_executor_pickup_response_consumption_receipt(
            pickup_response_consumption_path=args.pickup_response_consumption,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-pickup-status-snapshot":
        result = write_provider_live_executor_pickup_status_snapshot(
            pickup_manifest_path=args.pickup_manifest,
            executor_response_manifest_path=args.executor_response_manifest,
            pickup_response_consumption_path=args.pickup_response_consumption,
            pickup_response_receipt_path=args.pickup_response_receipt,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-lifecycle-audit":
        result = write_provider_live_executor_lifecycle_audit(
            pickup_status_snapshot_path=args.pickup_status_snapshot,
            inbox_status_snapshot_path=args.inbox_status_snapshot,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-production-readiness-gate":
        result = write_provider_live_executor_production_readiness_gate(
            lifecycle_audit_path=args.lifecycle_audit,
            connector_reference_path=args.connector_reference,
            credential_vault_reference_path=args.credential_vault_reference,
            network_policy_reference_path=args.network_policy_reference,
            runtime_ingest_boundary_reference_path=args.runtime_ingest_boundary_reference,
            phase1_safety_boundary_reference_path=args.phase1_safety_boundary_reference,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-consume-executor-response-inbox":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_provider_live_executor_response_inbox_consumption(
            inbox_index_path=args.inbox_index,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            manifest_source_path=args.manifest_source_path,
            reference_date=reference_date,
            root=args.root,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-consume-executor-response-inbox-batch":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_provider_live_executor_response_inbox_batch_consumption(
            inbox_index_path=args.inbox_index,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            reference_date=reference_date,
            root=args.root,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-executor-response-inbox-batch-receipt":
        result = write_provider_live_executor_response_inbox_batch_receipt(
            batch_consumption_path=args.batch_consumption,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-executor-response-inbox-status-snapshot":
        result = write_provider_live_executor_response_inbox_status_snapshot(
            inbox_index_path=args.inbox_index,
            batch_consumption_path=args.batch_consumption,
            batch_receipt_path=args.batch_receipt,
            output_path=args.output,
        )
        return 0, result
    if args.command == "provider-live-replay-admit":
        result = write_provider_live_transport_response_admission_from_fixture_replay(
            fixture_replay_path=args.fixture_replay,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            admission_output_path=args.output,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-rehearse-executor":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_provider_live_executor_rehearsal(
            request_plan_path=args.request_plan,
            executor_registration_path=args.executor_registration,
            response_fixture_path=args.response_fixture,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            reference_date=reference_date,
            root=args.root,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-response-admit":
        result = write_provider_live_transport_response_admission(
            request_plan_path=args.request_plan,
            response_fixture_path=args.response_fixture,
            output_dir=args.output_dir,
            activity_id_prefix=args.activity_id_prefix,
            admitted_capabilities=list(args.capability or []),
            admission_output_path=args.output,
            activity_type=args.activity_type,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-materialize":
        result = write_provider_live_transport_materialization(
            admission_path=args.admission,
            output_dir=args.output_dir,
            materialization_output_path=args.output,
            root=args.root,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "provider-live-sync-package":
        result = write_provider_live_transport_sync_package(
            materialization_path=args.materialization,
            package_output_path=args.output,
            root=args.root,
        )
        return 0, result
    if args.command == "provider-live-build-energy":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_energy_reserve_artifacts_from_provider_sync_package(
            args.sync_package,
            output_dir=args.output_dir,
            reference_date=reference_date,
            root=args.root,
        )
        return 0, result
    if args.command == "summarize-live-frame-fixture":
        result = write_field_observations_from_live_frame_fixture(
            args.input,
            provider=args.provider,
            output_dir=args.output_dir,
            stream_id=args.stream_id,
            route_segment_ref=args.route_segment_ref,
            expected_baseline_bpm=args.expected_baseline_bpm,
            overwrite=args.overwrite,
        )
        return 0, result
    if args.command == "build":
        reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = write_energy_reserve_artifacts_from_paths(
            list(args.activity),
            output_dir=args.output_dir,
            reference_date=reference_date,
            root=args.root,
        )
        return 0, result
    parser.error("missing command")


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, payload = run_energy_reserve_cli(argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return exit_code


def build_energy_reserve_explanation(
    baseline: ScoutEnergyReserveBaseline,
) -> ScoutEnergyReserveExplanation:
    band = baseline.reserve_trend.current_band
    route_review_cues = [
        "Treat this as a personal baseline-relative advisory, not route approval.",
        "Route choice still needs GPX or structured route review, daylight and weather checks, equipment and retreat-gate planning, and human review of personal constraints.",
        "Do not choose a route from scenery popularity or a single video recommendation.",
    ]
    headlines = {
        "normal": "Reserve is within the recent personal baseline.",
        "watch": "Reserve is mildly below the recent personal baseline.",
        "rest_suggested": "Reserve trend suggests slowing down or planning extra rest.",
        "stop_and_check": "Reserve trend suggests stopping and checking how you feel.",
    }
    cues = {
        "normal": ["Keep normal pacing and review conditions as usual.", *route_review_cues],
        "watch": ["Use a quieter pace and keep rest options visible.", *route_review_cues],
        "rest_suggested": ["Add a rest buffer before harder checkpoints.", "Avoid treating this as a safety state.", *route_review_cues],
        "stop_and_check": [
            "Pause and ask the user for a manual condition check.",
            "Escalation still requires the normal Scout safety/SOS flow.",
            *route_review_cues,
        ],
    }
    return ScoutEnergyReserveExplanation(
        source_provider=baseline.source_provider,
        source_path=baseline.source_path,
        sha256=aggregate_sha256(
            [
                baseline.sha256,
                baseline.reserve_trend.model_dump(mode="json"),
                baseline.data_quality.model_dump(mode="json"),
            ]
        ),
        reserve_band=band,
        headline=headlines[band],
        advisory_cues=cues[band],
        forbidden_interpretations=[
            "medical diagnosis",
            "medical condition inference",
            "physiological condition inference",
            "provider-value truth promotion",
            "Phase 1 runtime safety truth",
        ],
        data_quality=baseline.data_quality,
    )


def _provider_live_executor_rehearsal_artifact(
    *,
    readiness: dict[str, Any],
    fixture_replay: dict[str, Any],
    response_manifest: dict[str, Any],
    admission: dict[str, Any],
    materialization: dict[str, Any],
    sync_package: dict[str, Any],
    energy_build: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(energy_build["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "provider live executor rehearsal uses local response fixtures only",
            "executor registration is metadata only and no live provider request is performed",
            "external executor response manifest is admitted through the sanitized import path",
            "network execution remains disabled by local contract",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    rehearsal_sha = aggregate_sha256(
        [
            readiness["sha256"],
            fixture_replay["sha256"],
            response_manifest["sha256"],
            admission["sha256"],
            materialization["sha256"],
            sync_package["sha256"],
            energy_build["sha256"],
            {
                "artifact": "provider_live_executor_rehearsal",
                "transport_mode": "executor_rehearsal_only",
                "ready_for_live_execution": readiness["ready_for_live_execution"],
                "execution_blockers": readiness["execution_blockers"],
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_rehearsal",
        "artifact_version": "wearable_provider_live_executor_rehearsal.v1",
        "source_provider": readiness["source_provider"],
        "source_path": paths["executor_readiness_path"],
        "sha256": rehearsal_sha,
        "paths": paths,
        "readiness": {
            "artifact_kind": readiness["artifact_kind"],
            "source_provider": readiness["source_provider"],
            "source_path": readiness["source_path"],
            "sha256": readiness["sha256"],
            "ready_for_live_execution": readiness["ready_for_live_execution"],
            "execution_blockers": readiness["execution_blockers"],
            "executor_registered": readiness["executor_registration"]["executor_registered"],
        },
        "fixture_replay": {
            "artifact_kind": fixture_replay["artifact_kind"],
            "source_provider": fixture_replay["source_provider"],
            "source_path": fixture_replay["source_path"],
            "sha256": fixture_replay["sha256"],
            "raw_response_embedded": fixture_replay["response_fixture"]["raw_response_embedded"],
            "handoff_package_sha256": (
                fixture_replay.get("handoff_package", {}).get("sha256")
            ),
        },
        "executor_response_manifest": {
            "artifact_kind": response_manifest["artifact_kind"],
            "source_provider": response_manifest["source_provider"],
            "source_path": response_manifest["source_path"],
            "sha256": response_manifest["sha256"],
            "handoff_package_sha256": response_manifest["handoff_package"]["sha256"],
            "response_payload_sha256": response_manifest["response_payload"]["sha256"],
            "raw_response_embedded": response_manifest["response_payload"]["raw_response_embedded"],
        },
        "admission": {
            "artifact_kind": admission["artifact_kind"],
            "source_provider": admission["source_provider"],
            "source_path": admission["source_path"],
            "sha256": admission["sha256"],
            "admitted_capabilities": admission["admitted_capabilities"],
        },
        "materialization": {
            "artifact_kind": materialization["artifact_kind"],
            "source_provider": materialization["source_provider"],
            "source_path": materialization["source_path"],
            "sha256": materialization["sha256"],
            "activity_count": materialization["normalization"]["activity_count"],
        },
        "sync_package": {
            "artifact_kind": sync_package["artifact_kind"],
            "source_provider": sync_package["source_provider"],
            "source_path": sync_package["source_path"],
            "sha256": sync_package["sha256"],
            "normalized_summary_count": sync_package["normalized_summary_count"],
        },
        "energy_artifacts": energy_build["energy_artifacts"],
        "transport": {
            "transport_mode": "executor_rehearsal_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_response_consumption_artifact(
    *,
    executor_response_manifest: dict[str, Any],
    admission: dict[str, Any],
    materialization: dict[str, Any],
    sync_package: dict[str, Any],
    energy_build: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(energy_build["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "executor response manifest was consumed through local sanitized import only",
            "provider response payload stayed path-and-sha referenced and was not embedded",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    consumption_sha = aggregate_sha256(
        [
            executor_response_manifest["sha256"],
            admission["sha256"],
            materialization["sha256"],
            sync_package["sha256"],
            energy_build["sha256"],
            {
                "artifact": "provider_live_executor_response_consumption",
                "transport_mode": "executor_response_consumption_only",
            },
        ]
    )
    artifact = {
        "artifact_kind": "scout_wearable_provider_live_executor_response_consumption",
        "artifact_version": "wearable_provider_live_executor_response_consumption.v1",
        "source_provider": executor_response_manifest["source_provider"],
        "source_path": paths["executor_response_manifest_path"],
        "sha256": consumption_sha,
        "paths": paths,
        "executor_response_manifest": {
            "artifact_kind": executor_response_manifest["artifact_kind"],
            "source_provider": executor_response_manifest["source_provider"],
            "source_path": executor_response_manifest["source_path"],
            "sha256": executor_response_manifest["sha256"],
            "handoff_package_sha256": executor_response_manifest["handoff_package_sha256"],
            "response_payload_sha256": executor_response_manifest["response_payload_sha256"],
        },
        "admission": {
            "artifact_kind": admission["artifact_kind"],
            "source_provider": admission["source_provider"],
            "source_path": admission["source_path"],
            "sha256": admission["sha256"],
            "admitted_capabilities": admission["admitted_capabilities"],
        },
        "materialization": {
            "artifact_kind": materialization["artifact_kind"],
            "source_provider": materialization["source_provider"],
            "source_path": materialization["source_path"],
            "sha256": materialization["sha256"],
            "activity_count": materialization["normalization"]["activity_count"],
        },
        "sync_package": {
            "artifact_kind": sync_package["artifact_kind"],
            "source_provider": sync_package["source_provider"],
            "source_path": sync_package["source_path"],
            "sha256": sync_package["sha256"],
            "normalized_summary_count": sync_package["normalized_summary_count"],
        },
        "energy_artifacts": energy_build["energy_artifacts"],
        "transport": {
            "transport_mode": "executor_response_consumption_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if "pickup_manifest_sha256" in executor_response_manifest:
        artifact["executor_response_manifest"]["pickup_manifest_sha256"] = (
            executor_response_manifest["pickup_manifest_sha256"]
        )
        artifact["executor_response_manifest"]["pickup_manifest_source_path"] = (
            executor_response_manifest["pickup_manifest_source_path"]
        )
    return artifact


def _provider_live_executor_pickup_response_consumption_artifact(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    consumption: dict[str, Any],
    consumption_path: str,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(consumption["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "pickup-bound executor response manifest was consumed through local sanitized import only",
            "pickup manifest provenance was preserved through local Energy Reserve artifact generation",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    pickup_sha = aggregate_sha256(
        [
            manifest["sha256"],
            manifest["pickup_manifest"]["sha256"],
            consumption["sha256"],
            {
                "artifact": "provider_live_executor_pickup_response_consumption",
                "transport_mode": "executor_pickup_response_consumption_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_response_consumption",
        "artifact_version": "wearable_provider_live_executor_pickup_response_consumption.v1",
        "source_provider": manifest["source_provider"],
        "source_path": str(manifest_path),
        "sha256": pickup_sha,
        "pickup_manifest": {
            "artifact_kind": manifest["pickup_manifest"]["artifact_kind"],
            "source_provider": manifest["pickup_manifest"]["source_provider"],
            "source_path": manifest["pickup_manifest"]["source_path"],
            "sha256": manifest["pickup_manifest"]["sha256"],
            "pickup_status": manifest["pickup_manifest"]["pickup_status"],
            "external_execution_authorized": manifest["pickup_manifest"][
                "external_execution_authorized"
            ],
            "network_execution_disabled_by_local_contract": manifest["pickup_manifest"][
                "network_execution_disabled_by_local_contract"
            ],
        },
        "executor_response_manifest": {
            "artifact_kind": manifest["artifact_kind"],
            "source_provider": manifest["source_provider"],
            "source_path": str(manifest_path),
            "sha256": manifest["sha256"],
            "handoff_package_sha256": manifest["handoff_package"]["sha256"],
            "response_payload_sha256": manifest["response_payload"]["sha256"],
        },
        "executor_response_consumption": {
            "artifact_kind": consumption["artifact_kind"],
            "source_provider": consumption["source_provider"],
            "source_path": consumption_path,
            "sha256": consumption["sha256"],
            "baseline_path": consumption["paths"]["baseline_path"],
            "explanation_path": consumption["paths"]["explanation_path"],
            "companion_capsule_path": consumption["paths"]["companion_capsule_path"],
        },
        "transport": {
            "transport_mode": "executor_pickup_response_consumption_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_pickup_response_consumption_receipt_artifact(
    *,
    pickup_consumption: dict[str, Any],
    pickup_consumption_path: Path,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(pickup_consumption["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "pickup response consumption receipt records local artifact references and file hashes only",
            "pickup, response, and energy artifacts are not moved, deleted, uploaded, or synced",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    response_consumption = pickup_consumption["executor_response_consumption"]
    response_consumption_path = Path(response_consumption["source_path"])
    pickup_receipt_sha = aggregate_sha256(
        [
            pickup_consumption["sha256"],
            sha256_file(pickup_consumption_path),
            pickup_consumption["pickup_manifest"]["sha256"],
            pickup_consumption["executor_response_manifest"]["sha256"],
            response_consumption["sha256"],
            sha256_file(response_consumption_path),
            {
                "artifact": "provider_live_executor_pickup_response_consumption_receipt",
                "transport_mode": "executor_pickup_response_consumption_receipt_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_response_consumption_receipt",
        "artifact_version": "wearable_provider_live_executor_pickup_response_consumption_receipt.v1",
        "source_provider": pickup_consumption["source_provider"],
        "source_path": str(pickup_consumption_path),
        "sha256": pickup_receipt_sha,
        "pickup_response_consumption": {
            "artifact_kind": pickup_consumption["artifact_kind"],
            "source_provider": pickup_consumption["source_provider"],
            "source_path": str(pickup_consumption_path),
            "sha256": pickup_consumption["sha256"],
            "file_sha256": sha256_file(pickup_consumption_path),
        },
        "pickup_manifest": pickup_consumption["pickup_manifest"],
        "executor_response_manifest": pickup_consumption["executor_response_manifest"],
        "executor_response_consumption": {
            "artifact_kind": response_consumption["artifact_kind"],
            "source_provider": response_consumption["source_provider"],
            "source_path": response_consumption["source_path"],
            "sha256": response_consumption["sha256"],
            "file_sha256": sha256_file(response_consumption_path),
            "baseline_path": response_consumption["baseline_path"],
            "explanation_path": response_consumption["explanation_path"],
            "companion_capsule_path": response_consumption["companion_capsule_path"],
        },
        "receipt": {
            "receipt_status": "locally_recorded",
            "pickup_response_consumed": True,
            "energy_artifacts_recorded": True,
            "raw_payload_recorded": False,
            "remote_acknowledgement": False,
        },
        "transport": {
            "transport_mode": "executor_pickup_response_consumption_receipt_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_pickup_status_snapshot_artifact(
    *,
    pickup_manifest: dict[str, Any],
    pickup_manifest_path: Path,
    response_manifest: dict[str, Any] | None,
    response_manifest_path: Path | None,
    pickup_consumption: dict[str, Any] | None,
    pickup_consumption_path: Path | None,
    pickup_receipt: dict[str, Any] | None,
    pickup_receipt_path: Path | None,
) -> dict[str, Any]:
    data_quality_source = pickup_receipt or pickup_consumption or response_manifest or pickup_manifest
    data_quality = ScoutEnergyDataQuality.model_validate(data_quality_source["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "pickup lifecycle status is derived from local artifacts only",
            "status snapshot is audit evidence, not runtime safety truth",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    lifecycle_status = _pickup_lifecycle_status(
        response_manifest=response_manifest,
        pickup_consumption=pickup_consumption,
        pickup_receipt=pickup_receipt,
    )
    snapshot_sha = aggregate_sha256(
        [
            pickup_manifest["sha256"],
            response_manifest["sha256"] if response_manifest else None,
            pickup_consumption["sha256"] if pickup_consumption else None,
            pickup_receipt["sha256"] if pickup_receipt else None,
            {
                "artifact": "provider_live_executor_pickup_status_snapshot",
                "transport_mode": "executor_pickup_status_snapshot_only",
                "pickup_lifecycle_status": lifecycle_status,
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_status_snapshot",
        "artifact_version": "wearable_provider_live_executor_pickup_status_snapshot.v1",
        "source_provider": pickup_manifest["source_provider"],
        "source_path": str(pickup_manifest_path),
        "sha256": snapshot_sha,
        "pickup_manifest": {
            "artifact_kind": pickup_manifest["artifact_kind"],
            "source_provider": pickup_manifest["source_provider"],
            "source_path": str(pickup_manifest_path),
            "sha256": pickup_manifest["sha256"],
            "file_sha256": sha256_file(pickup_manifest_path),
            "pickup_status": pickup_manifest["pickup"]["pickup_status"],
            "selected_handoff_sha256": pickup_manifest["selected_handoff"]["sha256"],
            "selected_handoff_source_path": pickup_manifest["selected_handoff"]["source_path"],
            "external_execution_authorized": pickup_manifest["pickup"][
                "external_execution_authorized"
            ],
            "network_execution_disabled_by_local_contract": pickup_manifest["pickup"][
                "network_execution_disabled_by_local_contract"
            ],
        },
        "executor_response_manifest": _optional_response_manifest_status_ref(
            response_manifest,
            response_manifest_path,
        ),
        "pickup_response_consumption": _optional_pickup_consumption_status_ref(
            pickup_consumption,
            pickup_consumption_path,
        ),
        "pickup_response_receipt": _optional_pickup_receipt_status_ref(
            pickup_receipt,
            pickup_receipt_path,
        ),
        "status": {
            "pickup_lifecycle_status": lifecycle_status,
            "response_manifest_recorded": response_manifest is not None,
            "pickup_response_consumed": pickup_consumption is not None,
            "receipt_recorded": pickup_receipt is not None,
            "local_evidence_complete": pickup_receipt is not None,
            "runtime_safety_truth": False,
            "external_execution_authorized": False,
            "network_execution_disabled_by_local_contract": True,
        },
        "transport": {
            "transport_mode": "executor_pickup_status_snapshot_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _pickup_lifecycle_status(
    *,
    response_manifest: dict[str, Any] | None,
    pickup_consumption: dict[str, Any] | None,
    pickup_receipt: dict[str, Any] | None,
) -> str:
    if pickup_receipt is not None:
        return "receipt_recorded"
    if pickup_consumption is not None:
        return "consumed_without_receipt"
    if response_manifest is not None:
        return "response_manifest_recorded"
    return "awaiting_executor_response"


def _optional_response_manifest_status_ref(
    response_manifest: dict[str, Any] | None,
    response_manifest_path: Path | None,
) -> dict[str, Any] | None:
    if response_manifest is None or response_manifest_path is None:
        return None
    return {
        "artifact_kind": response_manifest["artifact_kind"],
        "source_provider": response_manifest["source_provider"],
        "source_path": str(response_manifest_path),
        "sha256": response_manifest["sha256"],
        "file_sha256": sha256_file(response_manifest_path),
        "handoff_package_sha256": response_manifest["handoff_package"]["sha256"],
        "response_payload_sha256": response_manifest["response_payload"]["sha256"],
    }


def _optional_pickup_consumption_status_ref(
    pickup_consumption: dict[str, Any] | None,
    pickup_consumption_path: Path | None,
) -> dict[str, Any] | None:
    if pickup_consumption is None or pickup_consumption_path is None:
        return None
    response_consumption = pickup_consumption["executor_response_consumption"]
    return {
        "artifact_kind": pickup_consumption["artifact_kind"],
        "source_provider": pickup_consumption["source_provider"],
        "source_path": str(pickup_consumption_path),
        "sha256": pickup_consumption["sha256"],
        "file_sha256": sha256_file(pickup_consumption_path),
        "executor_response_consumption_path": response_consumption["source_path"],
        "executor_response_consumption_sha256": response_consumption["sha256"],
        "baseline_path": response_consumption["baseline_path"],
        "explanation_path": response_consumption["explanation_path"],
        "companion_capsule_path": response_consumption["companion_capsule_path"],
    }


def _optional_pickup_receipt_status_ref(
    pickup_receipt: dict[str, Any] | None,
    pickup_receipt_path: Path | None,
) -> dict[str, Any] | None:
    if pickup_receipt is None or pickup_receipt_path is None:
        return None
    return {
        "artifact_kind": pickup_receipt["artifact_kind"],
        "source_provider": pickup_receipt["source_provider"],
        "source_path": str(pickup_receipt_path),
        "sha256": pickup_receipt["sha256"],
        "file_sha256": sha256_file(pickup_receipt_path),
        "receipt_status": pickup_receipt["receipt"]["receipt_status"],
        "pickup_response_consumption_sha256": pickup_receipt[
            "pickup_response_consumption"
        ]["sha256"],
    }


def _provider_live_executor_lifecycle_audit_artifact(
    *,
    pickup_status: dict[str, Any],
    pickup_status_path: Path,
    inbox_status: dict[str, Any] | None,
    inbox_status_path: Path | None,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(pickup_status["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "executor lifecycle audit is derived from local status snapshot artifacts",
            "audit status is operator evidence, not runtime safety truth",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    lifecycle = _executor_lifecycle_summary(
        pickup_status=pickup_status,
        inbox_status=inbox_status,
    )
    audit_sha = aggregate_sha256(
        [
            pickup_status["sha256"],
            sha256_file(pickup_status_path),
            inbox_status["sha256"] if inbox_status else None,
            sha256_file(inbox_status_path) if inbox_status and inbox_status_path else None,
            lifecycle,
            {
                "artifact": "provider_live_executor_lifecycle_audit",
                "transport_mode": "executor_lifecycle_audit_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_lifecycle_audit",
        "artifact_version": "wearable_provider_live_executor_lifecycle_audit.v1",
        "source_provider": pickup_status["source_provider"],
        "source_path": str(pickup_status_path),
        "sha256": audit_sha,
        "inputs": {
            "pickup_status_snapshot": {
                "artifact_kind": pickup_status["artifact_kind"],
                "source_provider": pickup_status["source_provider"],
                "source_path": str(pickup_status_path),
                "sha256": pickup_status["sha256"],
                "file_sha256": sha256_file(pickup_status_path),
                "pickup_lifecycle_status": pickup_status["status"][
                    "pickup_lifecycle_status"
                ],
                "local_evidence_complete": pickup_status["status"][
                    "local_evidence_complete"
                ],
            },
            "inbox_status_snapshot": (
                {
                    "artifact_kind": inbox_status["artifact_kind"],
                    "source_provider": inbox_status["source_provider"],
                    "source_path": str(inbox_status_path),
                    "sha256": inbox_status["sha256"],
                    "file_sha256": sha256_file(inbox_status_path),
                    "manifest_status_counts": inbox_status["manifest_status_counts"],
                }
                if inbox_status and inbox_status_path
                else None
            ),
        },
        "lifecycle": lifecycle,
        "transport": {
            "transport_mode": "executor_lifecycle_audit_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _executor_lifecycle_summary(
    *,
    pickup_status: dict[str, Any],
    inbox_status: dict[str, Any] | None,
) -> dict[str, Any]:
    pickup_complete = pickup_status["status"]["local_evidence_complete"] is True
    counts = (inbox_status or {}).get("manifest_status_counts", {})
    inbox_provided = inbox_status is not None
    inbox_complete = (
        inbox_provided
        and counts.get("eligible_manifest_count", 0)
        == counts.get("receipt_recorded_manifest_count", 0)
        and counts.get("eligible_pending_manifest_count", 0) == 0
        and counts.get("consumed_without_receipt_manifest_count", 0) == 0
    )
    if pickup_complete and inbox_complete:
        lifecycle_status = "local_evidence_complete"
    elif pickup_complete and not inbox_provided:
        lifecycle_status = "pickup_complete_inbox_not_provided"
    elif pickup_complete:
        lifecycle_status = "pickup_complete_inbox_pending"
    else:
        lifecycle_status = pickup_status["status"]["pickup_lifecycle_status"]
    return {
        "local_executor_lifecycle_status": lifecycle_status,
        "pickup_lifecycle_status": pickup_status["status"]["pickup_lifecycle_status"],
        "pickup_local_evidence_complete": pickup_complete,
        "inbox_status_snapshot_provided": inbox_provided,
        "inbox_local_evidence_complete": inbox_complete if inbox_provided else None,
        "inbox_manifest_status_counts": counts if inbox_provided else None,
        "production_provider_execution": False,
        "runtime_safety_truth": False,
        "remote_upload_performed": False,
        "network_request_performed": False,
    }


def _provider_live_executor_production_readiness_gate_artifact(
    *,
    lifecycle_audit: dict[str, Any],
    lifecycle_audit_path: Path,
    connector_reference: dict[str, Any] | None = None,
    connector_reference_path: Path | None = None,
    credential_vault_reference: dict[str, Any] | None = None,
    credential_vault_reference_path: Path | None = None,
    network_policy_reference: dict[str, Any] | None = None,
    network_policy_reference_path: Path | None = None,
    runtime_ingest_boundary_reference: dict[str, Any] | None = None,
    runtime_ingest_boundary_reference_path: Path | None = None,
    phase1_safety_boundary_reference: dict[str, Any] | None = None,
    phase1_safety_boundary_reference_path: Path | None = None,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(lifecycle_audit["data_quality"])
    connector_limitations = (
        [
            "live provider connector reference is present as a local digest-only contract",
        ]
        if connector_reference is not None
        else [
            "live provider connector is not implemented by this contract",
        ]
    )
    credential_limitations = (
        [
            "credential vault reference is present as digests only and does not load credential values",
        ]
        if credential_vault_reference is not None
        else [
            "credential vault is not integrated by this contract",
        ]
    )
    network_policy_limitations = (
        [
            "network policy reference is present as a local digest-only contract",
        ]
        if network_policy_reference is not None
        else [
            "network execution policy is not integrated by this contract",
        ]
    )
    runtime_ingest_limitations = (
        [
            "runtime ingest boundary reference is present but runtime ingest remains disabled",
        ]
        if runtime_ingest_boundary_reference is not None
        else [
            "runtime ingest is disabled by this contract",
        ]
    )
    phase1_safety_limitations = (
        [
            "Phase 1 safety boundary reference is present but safety truth mutation remains forbidden",
        ]
        if phase1_safety_boundary_reference is not None
        else [
            "Phase 1 safety truth mutation is disabled by this contract",
        ]
    )
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            *connector_limitations,
            *credential_limitations,
            *network_policy_limitations,
            *runtime_ingest_limitations,
            *phase1_safety_limitations,
            "production readiness gate is a local blocker report, not authorization to execute provider calls",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    readiness = _executor_production_readiness_summary(
        lifecycle_audit,
        connector_reference=connector_reference,
        credential_vault_reference=credential_vault_reference,
        network_policy_reference=network_policy_reference,
        runtime_ingest_boundary_reference=runtime_ingest_boundary_reference,
        phase1_safety_boundary_reference=phase1_safety_boundary_reference,
    )
    connector_ref_input = None
    connector_sha_inputs: list[Any] = []
    if connector_reference is not None and connector_reference_path is not None:
        connector_ref_input = {
            "artifact_kind": connector_reference["artifact_kind"],
            "source_provider": connector_reference["source_provider"],
            "source_path": str(connector_reference_path),
            "sha256": connector_reference["sha256"],
            "file_sha256": sha256_file(connector_reference_path),
            "connector_kind": connector_reference["connector"]["connector_kind"],
            "connector_version": connector_reference["connector"]["connector_version"],
            "connector_process_started": connector_reference["connector"][
                "connector_process_started"
            ],
            "connector_health_check_performed": connector_reference["connector"][
                "connector_health_check_performed"
            ],
            "connector_live_request_performed": connector_reference["connector"][
                "connector_live_request_performed"
            ],
            "connector_execution_bound": connector_reference["connector"][
                "connector_execution_bound"
            ],
            "credential_values_loaded": connector_reference["connector"][
                "credential_values_loaded"
            ],
            "credential_values_exposed": connector_reference["connector"][
                "credential_values_exposed"
            ],
            "supported_capabilities": connector_reference["connector"][
                "supported_capabilities"
            ],
        }
        connector_sha_inputs = [
            connector_reference["sha256"],
            sha256_file(connector_reference_path),
        ]
    credential_ref_input = None
    credential_sha_inputs: list[Any] = []
    if credential_vault_reference is not None and credential_vault_reference_path is not None:
        credential_ref_input = {
            "artifact_kind": credential_vault_reference["artifact_kind"],
            "source_provider": credential_vault_reference["source_provider"],
            "source_path": str(credential_vault_reference_path),
            "sha256": credential_vault_reference["sha256"],
            "file_sha256": sha256_file(credential_vault_reference_path),
            "credential_values_loaded": credential_vault_reference["credential_vault"][
                "credential_values_loaded"
            ],
            "credential_values_exposed": credential_vault_reference["credential_vault"][
                "credential_values_exposed"
            ],
            "vault_lookup_performed": credential_vault_reference["credential_vault"][
                "vault_lookup_performed"
            ],
            "vault_write_performed": credential_vault_reference["credential_vault"][
                "vault_write_performed"
            ],
            "normalized_scopes": credential_vault_reference["authorization"][
                "normalized_scopes"
            ],
            "allowed_capabilities": credential_vault_reference["authorization"][
                "allowed_capabilities"
            ],
        }
        credential_sha_inputs = [
            credential_vault_reference["sha256"],
            sha256_file(credential_vault_reference_path),
        ]
    network_policy_ref_input = None
    network_policy_sha_inputs: list[Any] = []
    if network_policy_reference is not None and network_policy_reference_path is not None:
        network_policy_ref_input = {
            "artifact_kind": network_policy_reference["artifact_kind"],
            "source_provider": network_policy_reference["source_provider"],
            "source_path": str(network_policy_reference_path),
            "sha256": network_policy_reference["sha256"],
            "file_sha256": sha256_file(network_policy_reference_path),
            "dns_lookup_performed": network_policy_reference["network_policy"][
                "dns_lookup_performed"
            ],
            "network_socket_opened": network_policy_reference["network_policy"][
                "network_socket_opened"
            ],
            "tls_handshake_performed": network_policy_reference["network_policy"][
                "tls_handshake_performed"
            ],
            "http_request_performed": network_policy_reference["network_policy"][
                "http_request_performed"
            ],
            "network_request_performed": network_policy_reference["network_policy"][
                "network_request_performed"
            ],
            "real_provider_api_called": network_policy_reference["network_policy"][
                "real_provider_api_called"
            ],
            "remote_upload_performed": network_policy_reference["network_policy"][
                "remote_upload_performed"
            ],
            "runtime_ingest_performed": network_policy_reference["network_policy"][
                "runtime_ingest_performed"
            ],
            "allowed_capabilities": network_policy_reference["network_policy"][
                "allowed_capabilities"
            ],
        }
        network_policy_sha_inputs = [
            network_policy_reference["sha256"],
            sha256_file(network_policy_reference_path),
        ]
    runtime_ingest_ref_input = None
    runtime_ingest_sha_inputs: list[Any] = []
    if (
        runtime_ingest_boundary_reference is not None
        and runtime_ingest_boundary_reference_path is not None
    ):
        runtime_ingest_ref_input = {
            "artifact_kind": runtime_ingest_boundary_reference["artifact_kind"],
            "source_provider": runtime_ingest_boundary_reference["source_provider"],
            "source_path": str(runtime_ingest_boundary_reference_path),
            "sha256": runtime_ingest_boundary_reference["sha256"],
            "file_sha256": sha256_file(runtime_ingest_boundary_reference_path),
            "handoff_mode": runtime_ingest_boundary_reference["runtime_ingest_boundary"][
                "handoff_mode"
            ],
            "runtime_ingest_authorized": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["runtime_ingest_authorized"],
            "runtime_ingest_performed": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["runtime_ingest_performed"],
            "runtime_write_performed": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["runtime_write_performed"],
            "phase1_runtime_mutated": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["phase1_runtime_mutated"],
            "phase1_runtime_safety_truth": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["phase1_runtime_safety_truth"],
            "safety_api_called": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["safety_api_called"],
            "allowed_artifact_kinds": runtime_ingest_boundary_reference[
                "runtime_ingest_boundary"
            ]["allowed_artifact_kinds"],
        }
        runtime_ingest_sha_inputs = [
            runtime_ingest_boundary_reference["sha256"],
            sha256_file(runtime_ingest_boundary_reference_path),
        ]
    phase1_safety_ref_input = None
    phase1_safety_sha_inputs: list[Any] = []
    if (
        phase1_safety_boundary_reference is not None
        and phase1_safety_boundary_reference_path is not None
    ):
        phase1_safety_ref_input = {
            "artifact_kind": phase1_safety_boundary_reference["artifact_kind"],
            "source_provider": phase1_safety_boundary_reference["source_provider"],
            "source_path": str(phase1_safety_boundary_reference_path),
            "sha256": phase1_safety_boundary_reference["sha256"],
            "file_sha256": sha256_file(phase1_safety_boundary_reference_path),
            "handoff_mode": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["handoff_mode"],
            "advisory_only": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["advisory_only"],
            "not_safety_truth": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["not_safety_truth"],
            "phase1_runtime_safety_truth": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["phase1_runtime_safety_truth"],
            "phase1_runtime_mutated": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["phase1_runtime_mutated"],
            "phase1_l0_l4_state_mutated": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["phase1_l0_l4_state_mutated"],
            "phase1_safety_state_mutation_allowed": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["phase1_safety_state_mutation_allowed"],
            "safety_api_called": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["safety_api_called"],
            "runtime_ingest_performed": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["runtime_ingest_performed"],
            "provider_values_are_scout_truth": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["provider_values_are_scout_truth"],
            "allowed_artifact_kinds": phase1_safety_boundary_reference[
                "phase1_safety_boundary"
            ]["allowed_artifact_kinds"],
        }
        phase1_safety_sha_inputs = [
            phase1_safety_boundary_reference["sha256"],
            sha256_file(phase1_safety_boundary_reference_path),
        ]
    gate_sha = aggregate_sha256(
        [
            lifecycle_audit["sha256"],
            sha256_file(lifecycle_audit_path),
            *connector_sha_inputs,
            *credential_sha_inputs,
            *network_policy_sha_inputs,
            *runtime_ingest_sha_inputs,
            *phase1_safety_sha_inputs,
            readiness,
            {
                "artifact": "provider_live_executor_production_readiness_gate",
                "transport_mode": "executor_production_readiness_gate_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_production_readiness_gate",
        "artifact_version": "wearable_provider_live_executor_production_readiness_gate.v1",
        "source_provider": lifecycle_audit["source_provider"],
        "source_path": str(lifecycle_audit_path),
        "sha256": gate_sha,
        "inputs": {
            "lifecycle_audit": {
                "artifact_kind": lifecycle_audit["artifact_kind"],
                "source_provider": lifecycle_audit["source_provider"],
                "source_path": str(lifecycle_audit_path),
                "sha256": lifecycle_audit["sha256"],
                "file_sha256": sha256_file(lifecycle_audit_path),
                "local_executor_lifecycle_status": lifecycle_audit["lifecycle"][
                    "local_executor_lifecycle_status"
                ],
            },
            "connector_reference": connector_ref_input,
            "credential_vault_reference": credential_ref_input,
            "network_policy_reference": network_policy_ref_input,
            "runtime_ingest_boundary_reference": runtime_ingest_ref_input,
            "phase1_safety_boundary_reference": phase1_safety_ref_input,
        },
        "readiness": readiness,
        "transport": {
            "transport_mode": "executor_production_readiness_gate_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "inbox_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _executor_production_readiness_summary(
    lifecycle_audit: dict[str, Any],
    *,
    connector_reference: dict[str, Any] | None = None,
    credential_vault_reference: dict[str, Any] | None = None,
    network_policy_reference: dict[str, Any] | None = None,
    runtime_ingest_boundary_reference: dict[str, Any] | None = None,
    phase1_safety_boundary_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_evidence_complete = (
        lifecycle_audit["lifecycle"]["local_executor_lifecycle_status"]
        == "local_evidence_complete"
    )
    live_provider_connector_reference_present = connector_reference is not None
    credential_vault_reference_present = credential_vault_reference is not None
    network_policy_reference_present = network_policy_reference is not None
    runtime_ingest_boundary_reference_present = runtime_ingest_boundary_reference is not None
    phase1_safety_boundary_reference_present = phase1_safety_boundary_reference is not None
    blockers = []
    if not local_evidence_complete:
        blockers.append("local_executor_lifecycle_evidence_incomplete")
    if not live_provider_connector_reference_present:
        blockers.append("live_provider_connector_not_implemented")
    if not credential_vault_reference_present:
        blockers.append("credential_vault_not_integrated")
    if not network_policy_reference_present:
        blockers.append("network_execution_disabled_by_local_contract")
    blockers.extend(
        [
            "runtime_ingest_disabled_by_boundary",
            "phase1_runtime_safety_truth_mutation_forbidden",
        ]
    )
    return {
        "readiness_status": "blocked",
        "production_provider_execution_ready": False,
        "local_executor_lifecycle_status": lifecycle_audit["lifecycle"][
            "local_executor_lifecycle_status"
        ],
        "local_evidence_complete": local_evidence_complete,
        "live_provider_connector_reference_present": live_provider_connector_reference_present,
        "connector_process_started": False,
        "connector_health_check_performed": False,
        "connector_live_request_performed": False,
        "connector_execution_bound": False,
        "credential_vault_reference_present": credential_vault_reference_present,
        "credential_values_loaded": False,
        "credential_values_exposed": False,
        "vault_lookup_performed": False,
        "vault_write_performed": False,
        "network_policy_reference_present": network_policy_reference_present,
        "dns_lookup_performed": False,
        "network_socket_opened": False,
        "tls_handshake_performed": False,
        "http_request_performed": False,
        "network_request_performed": False,
        "real_provider_api_called": False,
        "remote_upload_performed": False,
        "runtime_ingest_boundary_reference_present": runtime_ingest_boundary_reference_present,
        "runtime_ingest_authorized": False,
        "runtime_ingest_performed": False,
        "runtime_write_performed": False,
        "phase1_runtime_mutated": False,
        "phase1_runtime_safety_truth": False,
        "phase1_safety_boundary_reference_present": phase1_safety_boundary_reference_present,
        "phase1_l0_l4_state_mutated": False,
        "phase1_safety_state_mutation_allowed": False,
        "safety_api_called": False,
        "provider_values_are_scout_truth": False,
        "production_blockers": blockers,
        "may_run_live_provider_request": False,
        "may_load_credentials": False,
        "may_open_network_transport": False,
        "may_remote_upload": False,
        "may_runtime_ingest": False,
        "may_mutate_phase1_runtime_safety_truth": False,
        "may_call_safety_api": False,
        "medical_diagnosis": False,
    }


def _provider_live_executor_response_inbox_consumption_artifact(
    *,
    inbox_index: dict[str, Any],
    inbox_index_path: Path,
    selected_entry: dict[str, Any],
    consumption: dict[str, Any],
    consumption_path: str,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(consumption["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "executor response manifest was selected from a local inbox index",
            "inbox index file sha256 was rechecked before local consumption",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    inbox_consumption_sha = aggregate_sha256(
        [
            inbox_index["sha256"],
            selected_entry["file_sha256"],
            consumption["sha256"],
            {
                "artifact": "provider_live_executor_response_inbox_consumption",
                "transport_mode": "executor_response_inbox_consumption_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_consumption",
        "artifact_version": "wearable_provider_live_executor_response_inbox_consumption.v1",
        "source_provider": consumption["source_provider"],
        "source_path": str(inbox_index_path),
        "sha256": inbox_consumption_sha,
        "inbox_index": {
            "artifact_kind": inbox_index["artifact_kind"],
            "source_provider": inbox_index["source_provider"],
            "source_path": str(inbox_index_path),
            "sha256": inbox_index["sha256"],
            "eligible_manifest_count": inbox_index["inbox"]["eligible_manifest_count"],
        },
        "selected_manifest": {
            "source_path": selected_entry["source_path"],
            "file_sha256": selected_entry["file_sha256"],
            "manifest_sha256": selected_entry["manifest_sha256"],
            "handoff_package_sha256": selected_entry["handoff_package_sha256"],
            "response_payload_sha256": selected_entry["response_payload_sha256"],
            "eligible_for_consumption_precheck": selected_entry["eligible_for_consumption_precheck"],
        },
        "executor_response_consumption": {
            "artifact_kind": consumption["artifact_kind"],
            "source_provider": consumption["source_provider"],
            "source_path": consumption_path,
            "sha256": consumption["sha256"],
            "baseline_path": consumption["paths"]["baseline_path"],
            "explanation_path": consumption["paths"]["explanation_path"],
            "companion_capsule_path": consumption["paths"]["companion_capsule_path"],
        },
        "transport": {
            "transport_mode": "executor_response_inbox_consumption_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_response_inbox_batch_consumption_artifact(
    *,
    inbox_index: dict[str, Any],
    inbox_index_path: Path,
    consumption_results: list[dict[str, Any]],
) -> dict[str, Any]:
    first_result = consumption_results[0]
    data_quality = ScoutEnergyDataQuality.model_validate(first_result["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "all eligible executor response manifests were consumed from a local inbox index",
            "each manifest file sha256 was rechecked before local consumption",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    batch_sha = aggregate_sha256(
        [
            inbox_index["sha256"],
            [
                {
                    "manifest_path": result["executor_response_manifest_path"],
                    "consumption_sha256": result["sha256"],
                }
                for result in consumption_results
            ],
            {
                "artifact": "provider_live_executor_response_inbox_batch_consumption",
                "transport_mode": "executor_response_inbox_batch_consumption_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_batch_consumption",
        "artifact_version": "wearable_provider_live_executor_response_inbox_batch_consumption.v1",
        "source_provider": first_result["source_provider"],
        "source_path": str(inbox_index_path),
        "sha256": batch_sha,
        "inbox_index": {
            "artifact_kind": inbox_index["artifact_kind"],
            "source_provider": inbox_index["source_provider"],
            "source_path": str(inbox_index_path),
            "sha256": inbox_index["sha256"],
            "eligible_manifest_count": inbox_index["inbox"]["eligible_manifest_count"],
        },
        "batch": {
            "eligible_manifest_count": inbox_index["inbox"]["eligible_manifest_count"],
            "consumed_manifest_count": len(consumption_results),
            "selection_policy": "all_eligible_sorted_by_source_path",
        },
        "consumptions": [
            {
                "artifact_kind": result["executor_response_consumption"]["artifact_kind"],
                "source_provider": result["source_provider"],
                "source_path": result["executor_response_consumption_path"],
                "sha256": result["executor_response_consumption"]["sha256"],
                "executor_response_manifest_path": result["executor_response_manifest_path"],
                "baseline_path": result["baseline_path"],
                "explanation_path": result["explanation_path"],
                "companion_capsule_path": result["companion_capsule_path"],
            }
            for result in consumption_results
        ],
        "transport": {
            "transport_mode": "executor_response_inbox_batch_consumption_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_response_inbox_batch_receipt_artifact(
    *,
    batch_consumption: dict[str, Any],
    batch_consumption_path: Path,
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality.model_validate(batch_consumption["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "batch receipt records local artifact references and file hashes only",
            "executor response inbox files are not moved, deleted, uploaded, or synced",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    receipt_entries = _executor_response_inbox_batch_receipt_entries(batch_consumption)
    receipt_sha = aggregate_sha256(
        [
            batch_consumption["sha256"],
            sha256_file(batch_consumption_path),
            [
                {
                    "executor_response_manifest_path": entry["executor_response_manifest_path"],
                    "executor_response_manifest_file_sha256": entry[
                        "executor_response_manifest_file_sha256"
                    ],
                    "executor_response_consumption_sha256": entry[
                        "executor_response_consumption_sha256"
                    ],
                    "executor_response_consumption_file_sha256": entry[
                        "executor_response_consumption_file_sha256"
                    ],
                }
                for entry in receipt_entries
            ],
            {
                "artifact": "provider_live_executor_response_inbox_batch_receipt",
                "transport_mode": "executor_response_inbox_batch_receipt_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_batch_receipt",
        "artifact_version": "wearable_provider_live_executor_response_inbox_batch_receipt.v1",
        "source_provider": batch_consumption["source_provider"],
        "source_path": str(batch_consumption_path),
        "sha256": receipt_sha,
        "batch_consumption": {
            "artifact_kind": batch_consumption["artifact_kind"],
            "source_provider": batch_consumption["source_provider"],
            "source_path": str(batch_consumption_path),
            "sha256": batch_consumption["sha256"],
            "file_sha256": sha256_file(batch_consumption_path),
            "consumed_manifest_count": batch_consumption["batch"]["consumed_manifest_count"],
        },
        "inbox_index": batch_consumption["inbox_index"],
        "receipts": receipt_entries,
        "transport": {
            "transport_mode": "executor_response_inbox_batch_receipt_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "inbox_file_mutated": False,
            "inbox_file_moved": False,
            "inbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _executor_response_inbox_batch_receipt_entries(
    batch_consumption: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in batch_consumption.get("consumptions", []):
        consumption_path = Path(item["source_path"])
        consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
        manifest_path = Path(item["executor_response_manifest_path"])
        entries.append(
            {
                "executor_response_manifest_path": item["executor_response_manifest_path"],
                "executor_response_manifest_file_sha256": sha256_file(manifest_path),
                "executor_response_consumption_path": item["source_path"],
                "executor_response_consumption_sha256": item["sha256"],
                "executor_response_consumption_file_sha256": sha256_file(consumption_path),
                "baseline_path": item["baseline_path"],
                "explanation_path": item["explanation_path"],
                "companion_capsule_path": item["companion_capsule_path"],
                "consumption_artifact_kind": consumption["artifact_kind"],
                "receipt_status": "locally_recorded",
            }
        )
    return entries


def _provider_live_executor_response_inbox_status_snapshot_artifact(
    *,
    inbox_index: dict[str, Any],
    inbox_index_path: Path,
    batch_consumption: dict[str, Any] | None,
    batch_consumption_path: Path | None,
    batch_receipt: dict[str, Any] | None,
    batch_receipt_path: Path | None,
) -> dict[str, Any]:
    _assert_executor_response_inbox_status_inputs_match(
        inbox_index=inbox_index,
        batch_consumption=batch_consumption,
        batch_receipt=batch_receipt,
    )
    data_quality = ScoutEnergyDataQuality.model_validate(inbox_index["data_quality"])
    data_quality.limitations = sorted(
        {
            *data_quality.limitations,
            "inbox status snapshot is local operator evidence, not runtime safety truth",
            "manifest status is derived from local index, consumption, and receipt artifacts",
            "executor response inbox files are not moved, deleted, uploaded, or synced",
            "no live provider request, network sync, remote upload, or runtime ingest is performed",
        }
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    manifest_statuses = _executor_response_inbox_status_entries(
        inbox_index=inbox_index,
        batch_consumption=batch_consumption,
        batch_receipt=batch_receipt,
    )
    manifest_status_counts = _manifest_status_counts(manifest_statuses)
    snapshot_sha = aggregate_sha256(
        [
            inbox_index["sha256"],
            batch_consumption["sha256"] if batch_consumption else None,
            batch_receipt["sha256"] if batch_receipt else None,
            manifest_statuses,
            {
                "artifact": "provider_live_executor_response_inbox_status_snapshot",
                "transport_mode": "executor_response_inbox_status_snapshot_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_status_snapshot",
        "artifact_version": "wearable_provider_live_executor_response_inbox_status_snapshot.v1",
        "source_provider": inbox_index["source_provider"],
        "source_path": str(inbox_index_path),
        "sha256": snapshot_sha,
        "inputs": {
            "inbox_index": {
                "artifact_kind": inbox_index["artifact_kind"],
                "source_provider": inbox_index["source_provider"],
                "source_path": str(inbox_index_path),
                "sha256": inbox_index["sha256"],
                "file_sha256": sha256_file(inbox_index_path),
                "eligible_manifest_count": inbox_index["inbox"]["eligible_manifest_count"],
                "rejected_manifest_count": inbox_index["inbox"]["rejected_manifest_count"],
            },
            "batch_consumption": (
                {
                    "artifact_kind": batch_consumption["artifact_kind"],
                    "source_provider": batch_consumption["source_provider"],
                    "source_path": str(batch_consumption_path),
                    "sha256": batch_consumption["sha256"],
                    "file_sha256": sha256_file(batch_consumption_path),
                    "consumed_manifest_count": batch_consumption["batch"]["consumed_manifest_count"],
                }
                if batch_consumption and batch_consumption_path
                else None
            ),
            "batch_receipt": (
                {
                    "artifact_kind": batch_receipt["artifact_kind"],
                    "source_provider": batch_receipt["source_provider"],
                    "source_path": str(batch_receipt_path),
                    "sha256": batch_receipt["sha256"],
                    "file_sha256": sha256_file(batch_receipt_path),
                    "receipt_recorded_manifest_count": len(batch_receipt["receipts"]),
                }
                if batch_receipt and batch_receipt_path
                else None
            ),
        },
        "manifest_status_counts": manifest_status_counts,
        "manifest_statuses": manifest_statuses,
        "transport": {
            "transport_mode": "executor_response_inbox_status_snapshot_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "inbox_file_mutated": False,
            "inbox_file_moved": False,
            "inbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _executor_response_inbox_status_entries(
    *,
    inbox_index: dict[str, Any],
    batch_consumption: dict[str, Any] | None,
    batch_receipt: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    consumed_by_manifest = {
        item["executor_response_manifest_path"]: item
        for item in (batch_consumption or {}).get("consumptions", [])
    }
    receipt_by_manifest = {
        item["executor_response_manifest_path"]: item
        for item in (batch_receipt or {}).get("receipts", [])
    }
    statuses: list[dict[str, Any]] = []
    for entry in inbox_index.get("manifests", []):
        manifest_path = entry["source_path"]
        status = "eligible_pending"
        if entry.get("eligible_for_consumption_precheck") is not True:
            status = "rejected_by_precheck"
        elif manifest_path in receipt_by_manifest:
            status = "receipt_recorded"
        elif manifest_path in consumed_by_manifest:
            status = "consumed_without_receipt"

        item: dict[str, Any] = {
            "source_path": manifest_path,
            "file_sha256": entry["file_sha256"],
            "artifact_kind": entry.get("artifact_kind"),
            "source_provider": entry.get("source_provider"),
            "manifest_sha256": entry.get("manifest_sha256"),
            "handoff_package_sha256": entry.get("handoff_package_sha256"),
            "response_payload_sha256": entry.get("response_payload_sha256"),
            "handoff_ref_valid": entry.get("handoff_ref_valid") is True,
            "response_payload_ref_valid": entry.get("response_payload_ref_valid") is True,
            "eligible_for_consumption_precheck": entry.get("eligible_for_consumption_precheck") is True,
            "rejection_reason": entry.get("rejection_reason"),
            "manifest_status": status,
        }
        if manifest_path in consumed_by_manifest:
            consumed = consumed_by_manifest[manifest_path]
            item["executor_response_consumption_path"] = consumed["source_path"]
            item["executor_response_consumption_sha256"] = consumed["sha256"]
            item["baseline_path"] = consumed["baseline_path"]
            item["explanation_path"] = consumed["explanation_path"]
            item["companion_capsule_path"] = consumed["companion_capsule_path"]
        if manifest_path in receipt_by_manifest:
            receipt = receipt_by_manifest[manifest_path]
            item["receipt_status"] = receipt["receipt_status"]
            item["executor_response_consumption_file_sha256"] = receipt[
                "executor_response_consumption_file_sha256"
            ]
            item["executor_response_manifest_file_sha256"] = receipt[
                "executor_response_manifest_file_sha256"
            ]
        statuses.append(item)
    return statuses


def _manifest_status_counts(manifest_statuses: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total_manifest_count": len(manifest_statuses),
        "eligible_manifest_count": 0,
        "rejected_manifest_count": 0,
        "eligible_pending_manifest_count": 0,
        "consumed_without_receipt_manifest_count": 0,
        "receipt_recorded_manifest_count": 0,
    }
    for status in manifest_statuses:
        if status["eligible_for_consumption_precheck"]:
            counts["eligible_manifest_count"] += 1
        if status["manifest_status"] == "rejected_by_precheck":
            counts["rejected_manifest_count"] += 1
        elif status["manifest_status"] == "eligible_pending":
            counts["eligible_pending_manifest_count"] += 1
        elif status["manifest_status"] == "consumed_without_receipt":
            counts["consumed_without_receipt_manifest_count"] += 1
        elif status["manifest_status"] == "receipt_recorded":
            counts["receipt_recorded_manifest_count"] += 1
    return counts


def _load_provider_sync_package(sync_package_path: Path) -> dict[str, Any]:
    payload = json.loads(sync_package_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_transport_sync_package":
        raise ValueError("provider live energy build requires a sync-package artifact")
    return payload


def _load_executor_response_inbox_index(inbox_index_path: Path) -> dict[str, Any]:
    payload = json.loads(inbox_index_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_inbox_index":
        raise ValueError("executor response inbox consumption requires an inbox-index artifact")
    return payload


def _load_executor_response_inbox_batch_consumption(batch_consumption_path: Path) -> dict[str, Any]:
    payload = json.loads(batch_consumption_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_inbox_batch_consumption":
        raise ValueError("executor response inbox batch receipt requires a batch-consumption artifact")
    return payload


def _load_executor_response_inbox_batch_receipt(batch_receipt_path: Path) -> dict[str, Any]:
    payload = json.loads(batch_receipt_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_inbox_batch_receipt":
        raise ValueError("executor response inbox status snapshot requires a batch-receipt artifact")
    return payload


def _load_pickup_bound_executor_response_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_manifest":
        raise ValueError("pickup response consumption requires an executor response manifest artifact")
    if "pickup_manifest" not in payload:
        raise ValueError("pickup response consumption requires pickup-manifest provenance")
    return payload


def _load_executor_handoff_pickup_manifest(pickup_manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(pickup_manifest_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_handoff_pickup_manifest":
        raise ValueError("pickup status snapshot requires a handoff pickup manifest artifact")
    return payload


def _load_executor_pickup_response_consumption(
    pickup_response_consumption_path: Path,
) -> dict[str, Any]:
    payload = json.loads(pickup_response_consumption_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_pickup_response_consumption":
        raise ValueError("pickup response consumption receipt requires a pickup-consumption artifact")
    return payload


def _load_executor_pickup_response_consumption_receipt(
    pickup_response_receipt_path: Path,
) -> dict[str, Any]:
    payload = json.loads(pickup_response_receipt_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_pickup_response_consumption_receipt":
        raise ValueError("pickup status snapshot requires a pickup response consumption receipt artifact")
    return payload


def _load_executor_pickup_status_snapshot(pickup_status_snapshot_path: Path) -> dict[str, Any]:
    payload = json.loads(pickup_status_snapshot_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_pickup_status_snapshot":
        raise ValueError("executor lifecycle audit requires a pickup status snapshot artifact")
    return payload


def _load_executor_response_inbox_status_snapshot(inbox_status_snapshot_path: Path) -> dict[str, Any]:
    payload = json.loads(inbox_status_snapshot_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_inbox_status_snapshot":
        raise ValueError("executor lifecycle audit requires an inbox status snapshot artifact")
    return payload


def _load_executor_lifecycle_audit(lifecycle_audit_path: Path) -> dict[str, Any]:
    payload = json.loads(lifecycle_audit_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_lifecycle_audit":
        raise ValueError("executor production readiness gate requires a lifecycle audit artifact")
    return payload


def _assert_executor_response_inbox_index_safe(inbox_index: dict[str, Any]) -> None:
    transport = inbox_index.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_inbox_index_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor response inbox consumption requires local-only inbox index transport")
    privacy = inbox_index.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor response inbox consumption requires sanitized inbox index privacy")
    boundary = inbox_index.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor response inbox consumption cannot use medical or Phase 1 safety truth inbox index")


def _assert_pickup_bound_executor_response_manifest_safe(manifest: dict[str, Any]) -> None:
    pickup = manifest.get("pickup_manifest", {})
    if not pickup.get("source_path") or not pickup.get("sha256"):
        raise ValueError("pickup response consumption requires pickup manifest refs")
    if pickup.get("external_execution_authorized"):
        raise ValueError("pickup response consumption cannot use externally authorized execution")
    if not pickup.get("network_execution_disabled_by_local_contract"):
        raise ValueError("pickup response consumption requires disabled network execution")
    response_payload = manifest.get("response_payload", {})
    if (
        not response_payload.get("source_path")
        or not response_payload.get("sha256")
        or response_payload.get("raw_response_embedded")
        or response_payload.get("raw_response_committed")
        or response_payload.get("request_body_exposed")
        or response_payload.get("credential_value_exposed")
    ):
        raise ValueError("pickup response consumption requires sanitized response payload refs")
    transport = manifest.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_manifest_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("pickup response consumption requires response-manifest-only transport")
    privacy = manifest.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("pickup response consumption requires sanitized response manifest privacy")
    boundary = manifest.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("pickup response consumption cannot use medical or Phase 1 safety truth manifest")
    pickup_path = Path(pickup["source_path"])
    pickup_payload = json.loads(pickup_path.read_text(encoding="utf-8"))
    if pickup_payload.get("sha256") != pickup["sha256"]:
        raise ValueError("pickup response consumption pickup manifest sha256 mismatch")


def _assert_executor_handoff_pickup_manifest_safe_for_status(
    pickup_manifest: dict[str, Any],
) -> None:
    selected_handoff = pickup_manifest.get("selected_handoff", {})
    if (
        not selected_handoff.get("source_path")
        or not selected_handoff.get("sha256")
        or not selected_handoff.get("file_sha256")
        or selected_handoff.get("eligible_for_executor_pickup_precheck") is not True
    ):
        raise ValueError("pickup status snapshot requires eligible selected handoff refs")
    pickup = pickup_manifest.get("pickup", {})
    if pickup.get("pickup_status") != "ready_for_external_executor_review":
        raise ValueError("pickup status snapshot requires review-ready pickup status")
    if pickup.get("external_execution_authorized"):
        raise ValueError("pickup status snapshot cannot use externally authorized execution")
    if not pickup.get("network_execution_disabled_by_local_contract"):
        raise ValueError("pickup status snapshot requires disabled network execution")
    transport = pickup_manifest.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_handoff_pickup_manifest_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("pickup status snapshot requires local-only pickup manifest transport")
    privacy = pickup_manifest.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("pickup status snapshot requires sanitized pickup manifest privacy")
    boundary = pickup_manifest.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("pickup status snapshot cannot use medical or Phase 1 safety truth")
    if sha256_file(Path(selected_handoff["source_path"])) != selected_handoff["file_sha256"]:
        raise ValueError("pickup status snapshot selected handoff file sha256 mismatch")


def _assert_executor_pickup_response_consumption_safe(pickup_consumption: dict[str, Any]) -> None:
    transport = pickup_consumption.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_pickup_response_consumption_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("pickup response consumption receipt requires local-only consumption transport")
    privacy = pickup_consumption.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("pickup response consumption receipt requires sanitized consumption privacy")
    boundary = pickup_consumption.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("pickup response consumption receipt cannot use medical or Phase 1 safety truth")

    pickup = pickup_consumption.get("pickup_manifest", {})
    if not pickup.get("source_path") or not pickup.get("sha256"):
        raise ValueError("pickup response consumption receipt requires pickup manifest refs")
    if pickup.get("external_execution_authorized"):
        raise ValueError("pickup response consumption receipt cannot use externally authorized execution")
    if not pickup.get("network_execution_disabled_by_local_contract"):
        raise ValueError("pickup response consumption receipt requires disabled network execution")
    pickup_payload = json.loads(Path(pickup["source_path"]).read_text(encoding="utf-8"))
    if pickup_payload.get("sha256") != pickup["sha256"]:
        raise ValueError("pickup response consumption receipt pickup manifest sha256 mismatch")

    response_manifest = pickup_consumption.get("executor_response_manifest", {})
    if not response_manifest.get("source_path") or not response_manifest.get("sha256"):
        raise ValueError("pickup response consumption receipt requires response manifest refs")
    response_manifest_payload = json.loads(
        Path(response_manifest["source_path"]).read_text(encoding="utf-8")
    )
    if response_manifest_payload.get("sha256") != response_manifest["sha256"]:
        raise ValueError("pickup response consumption receipt response manifest sha256 mismatch")
    if response_manifest_payload.get("pickup_manifest", {}).get("sha256") != pickup["sha256"]:
        raise ValueError("pickup response consumption receipt pickup provenance mismatch")

    response_consumption = pickup_consumption.get("executor_response_consumption", {})
    if not response_consumption.get("source_path") or not response_consumption.get("sha256"):
        raise ValueError("pickup response consumption receipt requires response consumption refs")
    response_consumption_payload = json.loads(
        Path(response_consumption["source_path"]).read_text(encoding="utf-8")
    )
    if response_consumption_payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_consumption":
        raise ValueError("pickup response consumption receipt requires response consumption artifacts")
    if response_consumption_payload.get("sha256") != response_consumption["sha256"]:
        raise ValueError("pickup response consumption receipt response consumption sha256 mismatch")
    response_paths = response_consumption_payload.get("paths", {})
    if response_paths.get("baseline_path") != response_consumption.get("baseline_path"):
        raise ValueError("pickup response consumption receipt baseline path mismatch")
    if response_paths.get("explanation_path") != response_consumption.get("explanation_path"):
        raise ValueError("pickup response consumption receipt explanation path mismatch")
    if response_paths.get("companion_capsule_path") != response_consumption.get("companion_capsule_path"):
        raise ValueError("pickup response consumption receipt companion capsule path mismatch")
    Path(response_consumption["baseline_path"]).read_text(encoding="utf-8")
    Path(response_consumption["explanation_path"]).read_text(encoding="utf-8")
    Path(response_consumption["companion_capsule_path"]).read_text(encoding="utf-8")


def _assert_executor_pickup_response_consumption_receipt_safe(
    pickup_receipt: dict[str, Any],
) -> None:
    transport = pickup_receipt.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_pickup_response_consumption_receipt_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("pickup status snapshot requires local-only receipt transport")
    privacy = pickup_receipt.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("pickup status snapshot requires sanitized receipt privacy")
    boundary = pickup_receipt.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("pickup status snapshot cannot use medical or Phase 1 safety truth receipt")
    if pickup_receipt.get("receipt", {}).get("receipt_status") != "locally_recorded":
        raise ValueError("pickup status snapshot requires locally recorded receipt status")
    consumption_ref = pickup_receipt.get("pickup_response_consumption", {})
    if not consumption_ref.get("source_path") or not consumption_ref.get("sha256"):
        raise ValueError("pickup status snapshot requires receipt consumption refs")
    consumption_path = Path(consumption_ref["source_path"])
    if sha256_file(consumption_path) != consumption_ref.get("file_sha256"):
        raise ValueError("pickup status snapshot receipt consumption file sha256 mismatch")
    consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
    if consumption.get("sha256") != consumption_ref["sha256"]:
        raise ValueError("pickup status snapshot receipt consumption sha256 mismatch")


def _assert_executor_pickup_status_snapshot_safe(pickup_status: dict[str, Any]) -> None:
    transport = pickup_status.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_pickup_status_snapshot_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor lifecycle audit requires local-only pickup status transport")
    privacy = pickup_status.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor lifecycle audit requires sanitized pickup status privacy")
    boundary = pickup_status.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor lifecycle audit cannot use medical or Phase 1 safety truth pickup status")
    status = pickup_status.get("status", {})
    if status.get("runtime_safety_truth") or status.get("external_execution_authorized"):
        raise ValueError("executor lifecycle audit requires advisory pickup status")
    pickup_manifest = pickup_status.get("pickup_manifest", {})
    if not pickup_manifest.get("source_path") or not pickup_manifest.get("sha256"):
        raise ValueError("executor lifecycle audit requires pickup manifest refs")
    if sha256_file(Path(pickup_manifest["source_path"])) != pickup_manifest.get("file_sha256"):
        raise ValueError("executor lifecycle audit pickup manifest file sha256 mismatch")


def _assert_executor_response_inbox_status_snapshot_safe(inbox_status: dict[str, Any]) -> None:
    transport = inbox_status.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_inbox_status_snapshot_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor lifecycle audit requires local-only inbox status transport")
    privacy = inbox_status.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor lifecycle audit requires sanitized inbox status privacy")
    boundary = inbox_status.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor lifecycle audit cannot use medical or Phase 1 safety truth inbox status")
    inputs = inbox_status.get("inputs", {})
    inbox_index = inputs.get("inbox_index", {})
    if not inbox_index.get("source_path") or not inbox_index.get("file_sha256"):
        raise ValueError("executor lifecycle audit requires inbox index refs")
    if sha256_file(Path(inbox_index["source_path"])) != inbox_index["file_sha256"]:
        raise ValueError("executor lifecycle audit inbox index file sha256 mismatch")


def _assert_executor_lifecycle_audit_safe(lifecycle_audit: dict[str, Any]) -> None:
    transport = lifecycle_audit.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_lifecycle_audit_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor production readiness gate requires local-only lifecycle audit transport")
    privacy = lifecycle_audit.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor production readiness gate requires sanitized lifecycle audit privacy")
    boundary = lifecycle_audit.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor production readiness gate cannot use medical or Phase 1 safety truth audit")
    lifecycle = lifecycle_audit.get("lifecycle", {})
    if (
        lifecycle.get("production_provider_execution")
        or lifecycle.get("runtime_safety_truth")
        or lifecycle.get("remote_upload_performed")
        or lifecycle.get("network_request_performed")
    ):
        raise ValueError("executor production readiness gate requires non-production lifecycle audit")
    pickup_status = lifecycle_audit.get("inputs", {}).get("pickup_status_snapshot", {})
    if not pickup_status.get("source_path") or not pickup_status.get("file_sha256"):
        raise ValueError("executor production readiness gate requires pickup status refs")
    if sha256_file(Path(pickup_status["source_path"])) != pickup_status["file_sha256"]:
        raise ValueError("executor production readiness gate pickup status file sha256 mismatch")
    inbox_status = lifecycle_audit.get("inputs", {}).get("inbox_status_snapshot")
    if inbox_status is not None:
        if not inbox_status.get("source_path") or not inbox_status.get("file_sha256"):
            raise ValueError("executor production readiness gate requires inbox status refs")
        if sha256_file(Path(inbox_status["source_path"])) != inbox_status["file_sha256"]:
            raise ValueError("executor production readiness gate inbox status file sha256 mismatch")


def _assert_executor_response_inbox_batch_consumption_safe(batch_consumption: dict[str, Any]) -> None:
    transport = batch_consumption.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_inbox_batch_consumption_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor response inbox batch receipt requires local-only batch consumption transport")
    privacy = batch_consumption.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor response inbox batch receipt requires sanitized batch consumption privacy")
    boundary = batch_consumption.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor response inbox batch receipt cannot use medical or Phase 1 safety truth")
    consumptions = batch_consumption.get("consumptions", [])
    if not consumptions:
        raise ValueError("executor response inbox batch receipt requires consumed manifest entries")
    if len(consumptions) != batch_consumption.get("batch", {}).get("consumed_manifest_count"):
        raise ValueError("executor response inbox batch receipt consumed count mismatch")
    for item in consumptions:
        consumption_path = Path(item["source_path"])
        consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
        if consumption.get("artifact_kind") != "scout_wearable_provider_live_executor_response_consumption":
            raise ValueError("executor response inbox batch receipt requires consumption artifacts")
        if consumption.get("sha256") != item["sha256"]:
            raise ValueError("executor response inbox batch receipt consumption sha256 mismatch")
        paths = consumption.get("paths", {})
        if paths.get("executor_response_manifest_path") != item["executor_response_manifest_path"]:
            raise ValueError("executor response inbox batch receipt manifest path mismatch")
        if paths.get("baseline_path") != item["baseline_path"]:
            raise ValueError("executor response inbox batch receipt baseline path mismatch")
        if paths.get("explanation_path") != item["explanation_path"]:
            raise ValueError("executor response inbox batch receipt explanation path mismatch")
        if paths.get("companion_capsule_path") != item["companion_capsule_path"]:
            raise ValueError("executor response inbox batch receipt companion capsule path mismatch")
        Path(item["executor_response_manifest_path"]).read_text(encoding="utf-8")


def _assert_executor_response_inbox_batch_receipt_safe(batch_receipt: dict[str, Any]) -> None:
    transport = batch_receipt.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_inbox_batch_receipt_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("executor response inbox status snapshot requires local-only receipt transport")
    privacy = batch_receipt.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("executor response inbox status snapshot requires sanitized receipt privacy")
    boundary = batch_receipt.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("executor response inbox status snapshot cannot use medical or Phase 1 safety truth")
    receipts = batch_receipt.get("receipts", [])
    if not receipts:
        raise ValueError("executor response inbox status snapshot requires receipt entries")
    if len(receipts) != batch_receipt.get("batch_consumption", {}).get("consumed_manifest_count"):
        raise ValueError("executor response inbox status snapshot receipt count mismatch")
    for item in receipts:
        if item.get("receipt_status") != "locally_recorded":
            raise ValueError("executor response inbox status snapshot requires locally recorded receipts")
        Path(item["executor_response_manifest_path"]).read_text(encoding="utf-8")
        consumption_path = Path(item["executor_response_consumption_path"])
        consumption = json.loads(consumption_path.read_text(encoding="utf-8"))
        if consumption.get("sha256") != item["executor_response_consumption_sha256"]:
            raise ValueError("executor response inbox status snapshot receipt consumption sha256 mismatch")


def _assert_executor_response_inbox_status_inputs_match(
    *,
    inbox_index: dict[str, Any],
    batch_consumption: dict[str, Any] | None,
    batch_receipt: dict[str, Any] | None,
) -> None:
    indexed_manifest_paths = {
        entry["source_path"] for entry in inbox_index.get("manifests", [])
    }
    if batch_consumption is not None:
        if batch_consumption.get("inbox_index", {}).get("sha256") != inbox_index["sha256"]:
            raise ValueError("executor response inbox status snapshot batch consumption inbox sha256 mismatch")
        consumed_manifest_paths = {
            item["executor_response_manifest_path"]
            for item in batch_consumption.get("consumptions", [])
        }
        if consumed_manifest_paths - indexed_manifest_paths:
            raise ValueError("executor response inbox status snapshot batch consumption contains unknown manifest")
    if batch_receipt is not None:
        if batch_receipt.get("inbox_index", {}).get("sha256") != inbox_index["sha256"]:
            raise ValueError("executor response inbox status snapshot receipt inbox sha256 mismatch")
        receipt_manifest_paths = {
            item["executor_response_manifest_path"]
            for item in batch_receipt.get("receipts", [])
        }
        if receipt_manifest_paths - indexed_manifest_paths:
            raise ValueError("executor response inbox status snapshot receipt contains unknown manifest")
    if batch_consumption is not None and batch_receipt is not None:
        if batch_receipt.get("batch_consumption", {}).get("sha256") != batch_consumption["sha256"]:
            raise ValueError("executor response inbox status snapshot receipt batch sha256 mismatch")


def _select_executor_response_inbox_entry(
    inbox_index: dict[str, Any],
    *,
    manifest_source_path: Path | None,
) -> dict[str, Any]:
    entries = _eligible_executor_response_inbox_entries(inbox_index)
    if manifest_source_path is not None:
        manifest_source = str(manifest_source_path)
        entries = [
            entry for entry in entries if entry.get("source_path") == manifest_source
        ]
        if not entries:
            raise ValueError("requested executor response manifest is not eligible in inbox index")
    if not entries:
        raise ValueError("executor response inbox index has no eligible manifest to consume")
    return entries[0]


def _eligible_executor_response_inbox_entries(inbox_index: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            entry
            for entry in inbox_index.get("manifests", [])
            if entry.get("eligible_for_consumption_precheck") is True
        ],
        key=lambda entry: entry["source_path"],
    )


def _assert_provider_sync_package_safe(sync_package: dict[str, Any]) -> None:
    if not sync_package.get("normalized_summaries"):
        raise ValueError("provider live energy build requires normalized summaries")
    if not all(summary.get("valid") is True for summary in sync_package["normalized_summaries"]):
        raise ValueError("provider live energy build requires valid normalized summaries")
    transport = sync_package.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live energy build requires local-only sync package transport")
    privacy = sync_package.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live energy build requires sanitized sync package privacy")
    boundary = sync_package.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live energy build cannot use medical or Phase 1 safety truth sync package")


def _activity_paths_from_provider_sync_package(
    sync_package: dict[str, Any],
    *,
    root: Path | None = None,
) -> list[Path]:
    paths: list[Path] = []
    for summary in sync_package["normalized_summaries"]:
        source_path = Path(summary["source_path"])
        if source_path.is_absolute():
            paths.append(source_path)
        elif root is not None:
            paths.append(root / source_path)
        else:
            raise ValueError("root is required when sync package summary paths are relative")
    return paths


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Scout Energy Reserve fixture-backed baseline artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize sanitized provider/file-derived wearable imports into Scout summaries.",
    )
    normalize_parser.add_argument(
        "--input",
        action="append",
        type=Path,
        required=True,
        help="Sanitized wearable import envelope JSON. Repeat for multiple inputs.",
    )
    normalize_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for normalized wearable activity summary JSON files.",
    )
    normalize_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root used to render source_path values as privacy-preserving relative paths.",
    )
    normalize_parser.add_argument("--overwrite", action="store_true")
    raw_parser = subparsers.add_parser(
        "summarize-raw",
        help="Summarize local Apple Health, Garmin Connect, or GPX/FIT/TCX files into sanitized import envelopes.",
    )
    raw_parser.add_argument("--input", type=Path, required=True)
    raw_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export", "gpx", "fit", "tcx"],
        required=True,
    )
    raw_parser.add_argument("--output-dir", type=Path, required=True)
    raw_parser.add_argument("--activity-id", required=True)
    raw_parser.add_argument("--activity-type", default="hiking")
    raw_parser.add_argument("--overwrite", action="store_true")
    raw_batch_parser = subparsers.add_parser(
        "summarize-raw-batch",
        help="Summarize local Apple Health or Garmin Connect export batches into sanitized import envelopes.",
    )
    raw_batch_parser.add_argument("--input", type=Path, required=True)
    raw_batch_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    raw_batch_parser.add_argument("--output-dir", type=Path, required=True)
    raw_batch_parser.add_argument("--activity-id-prefix", required=True)
    raw_batch_parser.add_argument("--activity-type", default="hiking")
    raw_batch_parser.add_argument("--overwrite", action="store_true")
    archive_parser = subparsers.add_parser(
        "summarize-provider-archive",
        help="Discover a local Apple Health or Garmin Connect export file in a directory/zip and summarize it.",
    )
    archive_parser.add_argument("--input", type=Path, required=True)
    archive_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    archive_parser.add_argument("--output-dir", type=Path, required=True)
    archive_parser.add_argument("--activity-id-prefix", required=True)
    archive_parser.add_argument("--activity-type", default="hiking")
    archive_parser.add_argument("--overwrite", action="store_true")
    inspect_archive_parser = subparsers.add_parser(
        "inspect-provider-archive",
        help="Map supported and deferred local Apple Health or Garmin export archive members without importing raw payloads.",
    )
    inspect_archive_parser.add_argument("--input", type=Path, required=True)
    inspect_archive_parser.add_argument(
        "--source-format",
        choices=["apple_health_export", "garmin_connect_export"],
        required=True,
    )
    provider_api_parser = subparsers.add_parser(
        "summarize-provider-api-fixture",
        help="Summarize an offline account-authorized provider API response fixture without live network calls.",
    )
    provider_api_parser.add_argument("--input", type=Path, required=True)
    provider_api_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_api", "garmin_health_api"],
        required=True,
    )
    provider_api_parser.add_argument("--output-dir", type=Path, required=True)
    provider_api_parser.add_argument("--activity-id-prefix", required=True)
    provider_api_parser.add_argument("--activity-type", default="hiking")
    provider_api_parser.add_argument("--scope", action="append", default=[])
    provider_api_parser.add_argument("--auth-token-ref", default=None)
    provider_api_parser.add_argument("--explicit-consent", action="store_true")
    provider_api_parser.add_argument("--overwrite", action="store_true")
    provider_live_preflight_parser = subparsers.add_parser(
        "provider-live-preflight",
        help="Write a local account-authorized provider live transport preflight artifact without calling a live API.",
    )
    provider_live_preflight_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_preflight_parser.add_argument("--output", type=Path, required=True)
    provider_live_preflight_parser.add_argument("--account-ref", required=True)
    provider_live_preflight_parser.add_argument("--device-ref", default=None)
    provider_live_preflight_parser.add_argument("--auth-token-ref", required=True)
    provider_live_preflight_parser.add_argument("--scope", action="append", required=True)
    provider_live_preflight_parser.add_argument("--capability", action="append", required=True)
    provider_live_preflight_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_credential_vault_reference_parser = subparsers.add_parser(
        "provider-live-credential-vault-reference",
        help="Write a local credential-vault reference artifact without loading or exposing credential values.",
    )
    provider_live_credential_vault_reference_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_credential_vault_reference_parser.add_argument("--output", type=Path, required=True)
    provider_live_credential_vault_reference_parser.add_argument("--vault-ref", required=True)
    provider_live_credential_vault_reference_parser.add_argument("--account-ref", required=True)
    provider_live_credential_vault_reference_parser.add_argument("--device-ref", default=None)
    provider_live_credential_vault_reference_parser.add_argument("--token-ref", required=True)
    provider_live_credential_vault_reference_parser.add_argument("--scope", action="append", required=True)
    provider_live_credential_vault_reference_parser.add_argument("--capability", action="append", required=True)
    provider_live_credential_vault_reference_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_connector_reference_parser = subparsers.add_parser(
        "provider-live-connector-reference",
        help="Write a local provider connector reference artifact without starting a connector or opening network transport.",
    )
    provider_live_connector_reference_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_connector_reference_parser.add_argument("--output", type=Path, required=True)
    provider_live_connector_reference_parser.add_argument(
        "--connector-kind",
        choices=["apple_healthkit_local_bridge_connector", "garmin_health_api_connector"],
        required=True,
    )
    provider_live_connector_reference_parser.add_argument("--connector-ref", required=True)
    provider_live_connector_reference_parser.add_argument("--connector-version", required=True)
    provider_live_connector_reference_parser.add_argument("--connector-binary-ref", default=None)
    provider_live_connector_reference_parser.add_argument("--capability", action="append", required=True)
    provider_live_connector_reference_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_network_policy_reference_parser = subparsers.add_parser(
        "provider-live-network-policy-reference",
        help="Write a local network policy reference artifact without DNS, socket, TLS, HTTP, or provider API calls.",
    )
    provider_live_network_policy_reference_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_network_policy_reference_parser.add_argument("--output", type=Path, required=True)
    provider_live_network_policy_reference_parser.add_argument("--policy-ref", required=True)
    provider_live_network_policy_reference_parser.add_argument("--endpoint-ref", required=True)
    provider_live_network_policy_reference_parser.add_argument("--egress-profile-ref", default=None)
    provider_live_network_policy_reference_parser.add_argument("--tls-profile-ref", default=None)
    provider_live_network_policy_reference_parser.add_argument("--capability", action="append", required=True)
    provider_live_network_policy_reference_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_runtime_ingest_boundary_reference_parser = subparsers.add_parser(
        "provider-live-runtime-ingest-boundary-reference",
        help="Write a local runtime ingest boundary reference without runtime writes or safety truth mutation.",
    )
    provider_live_runtime_ingest_boundary_reference_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_runtime_ingest_boundary_reference_parser.add_argument("--output", type=Path, required=True)
    provider_live_runtime_ingest_boundary_reference_parser.add_argument("--runtime-boundary-ref", required=True)
    provider_live_runtime_ingest_boundary_reference_parser.add_argument("--runtime-channel-ref", required=True)
    provider_live_runtime_ingest_boundary_reference_parser.add_argument(
        "--handoff-mode",
        choices=["post_analysis_reference_only", "advisory_energy_reference_only"],
        default="post_analysis_reference_only",
    )
    provider_live_runtime_ingest_boundary_reference_parser.add_argument("--artifact-kind", action="append", required=True)
    provider_live_runtime_ingest_boundary_reference_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_phase1_safety_boundary_reference_parser = subparsers.add_parser(
        "provider-live-phase1-safety-boundary-reference",
        help="Write a local Phase 1 safety boundary reference without safety truth mutation or safety API calls.",
    )
    provider_live_phase1_safety_boundary_reference_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live", "garmin_health_api_live"],
        required=True,
    )
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--output", type=Path, required=True)
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--phase1-boundary-ref", required=True)
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--phase1-state-ref", required=True)
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--advisory-channel-ref", required=True)
    provider_live_phase1_safety_boundary_reference_parser.add_argument(
        "--handoff-mode",
        choices=[
            "advisory_reference_only",
            "post_analysis_reference_only",
            "advisory_energy_reference_only",
        ],
        default="advisory_reference_only",
    )
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--artifact-kind", action="append", required=True)
    provider_live_phase1_safety_boundary_reference_parser.add_argument("--explicit-consent", action="store_true")
    provider_live_request_plan_parser = subparsers.add_parser(
        "provider-live-request-plan",
        help="Write a provider live transport request-plan artifact from a local preflight artifact.",
    )
    provider_live_request_plan_parser.add_argument("--preflight", type=Path, required=True)
    provider_live_request_plan_parser.add_argument("--output", type=Path, required=True)
    provider_live_request_plan_parser.add_argument("--window-start-date", required=True)
    provider_live_request_plan_parser.add_argument("--window-end-date", required=True)
    provider_live_request_plan_parser.add_argument("--capability", action="append", required=True)
    provider_live_register_executor_parser = subparsers.add_parser(
        "provider-live-register-executor",
        help="Write local provider executor metadata without loading credentials or opening network transport.",
    )
    provider_live_register_executor_parser.add_argument("--preflight", type=Path, required=True)
    provider_live_register_executor_parser.add_argument("--output", type=Path, required=True)
    provider_live_register_executor_parser.add_argument(
        "--executor-kind",
        choices=["apple_healthkit_local_bridge", "garmin_health_api_client"],
        required=True,
    )
    provider_live_register_executor_parser.add_argument("--executor-ref", required=True)
    provider_live_register_executor_parser.add_argument("--capability", action="append", required=True)
    provider_live_executor_readiness_parser = subparsers.add_parser(
        "provider-live-executor-readiness",
        help="Write a local readiness gate for a future provider live executor without network calls.",
    )
    provider_live_executor_readiness_parser.add_argument("--request-plan", type=Path, required=True)
    provider_live_executor_readiness_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_readiness_parser.add_argument(
        "--executor-registration",
        type=Path,
        default=None,
    )
    provider_live_executor_handoff_parser = subparsers.add_parser(
        "provider-live-executor-handoff",
        help="Write a local provider executor handoff package without credentials or network calls.",
    )
    provider_live_executor_handoff_parser.add_argument("--request-plan", type=Path, required=True)
    provider_live_executor_handoff_parser.add_argument("--executor-registration", type=Path, required=True)
    provider_live_executor_handoff_parser.add_argument("--output", type=Path, required=True)
    provider_live_index_executor_handoff_outbox_parser = subparsers.add_parser(
        "provider-live-index-executor-handoff-outbox",
        help="Index local executor handoff packages without binding an executor or network transport.",
    )
    provider_live_index_executor_handoff_outbox_parser.add_argument("--outbox-dir", type=Path, required=True)
    provider_live_index_executor_handoff_outbox_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_handoff_pickup_manifest_parser = subparsers.add_parser(
        "provider-live-executor-handoff-pickup-manifest",
        help="Create a local pickup manifest for an indexed executor handoff package.",
    )
    provider_live_executor_handoff_pickup_manifest_parser.add_argument("--outbox-index", type=Path, required=True)
    provider_live_executor_handoff_pickup_manifest_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_handoff_pickup_manifest_parser.add_argument(
        "--handoff-source-path",
        type=Path,
        default=None,
    )
    provider_live_fixture_replay_parser = subparsers.add_parser(
        "provider-live-fixture-replay",
        help="Write a local provider executor fixture-replay artifact without network calls.",
    )
    provider_live_fixture_replay_parser.add_argument("--request-plan", type=Path, required=True)
    provider_live_fixture_replay_parser.add_argument("--executor-registration", type=Path, required=True)
    provider_live_fixture_replay_parser.add_argument("--response-fixture", type=Path, required=True)
    provider_live_fixture_replay_parser.add_argument("--output", type=Path, required=True)
    provider_live_handoff_fixture_replay_parser = subparsers.add_parser(
        "provider-live-handoff-fixture-replay",
        help="Replay a local provider executor handoff package against a response fixture without network calls.",
    )
    provider_live_handoff_fixture_replay_parser.add_argument(
        "--executor-handoff",
        "--handoff-package",
        dest="executor_handoff",
        type=Path,
        required=True,
    )
    provider_live_handoff_fixture_replay_parser.add_argument("--response-fixture", type=Path, required=True)
    provider_live_handoff_fixture_replay_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_pickup_response_manifest_parser = subparsers.add_parser(
        "provider-live-executor-pickup-response-manifest",
        help="Write a local response manifest bound to a handoff pickup manifest.",
    )
    provider_live_executor_pickup_response_manifest_parser.add_argument(
        "--pickup-manifest",
        type=Path,
        required=True,
    )
    provider_live_executor_pickup_response_manifest_parser.add_argument(
        "--response-payload",
        type=Path,
        required=True,
    )
    provider_live_executor_pickup_response_manifest_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_response_manifest_parser = subparsers.add_parser(
        "provider-live-executor-response-manifest",
        help="Write a local external-executor response manifest without embedding raw provider payloads.",
    )
    provider_live_executor_response_manifest_parser.add_argument(
        "--executor-handoff",
        "--handoff-package",
        dest="executor_handoff",
        type=Path,
        required=True,
    )
    provider_live_executor_response_manifest_parser.add_argument("--response-payload", type=Path, required=True)
    provider_live_executor_response_manifest_parser.add_argument("--output", type=Path, required=True)
    provider_live_index_executor_response_inbox_parser = subparsers.add_parser(
        "provider-live-index-executor-response-inbox",
        help="Index local external-executor response manifests without consuming or uploading them.",
    )
    provider_live_index_executor_response_inbox_parser.add_argument("--inbox-dir", type=Path, required=True)
    provider_live_index_executor_response_inbox_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_response_admit_parser = subparsers.add_parser(
        "provider-live-executor-response-admit",
        help="Admit a local external-executor response manifest into sanitized imports.",
    )
    provider_live_executor_response_admit_parser.add_argument(
        "--executor-response-manifest",
        type=Path,
        required=True,
    )
    provider_live_executor_response_admit_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_response_admit_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_executor_response_admit_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_executor_response_admit_parser.add_argument("--capability", action="append", required=True)
    provider_live_executor_response_admit_parser.add_argument("--activity-type", default="hiking")
    provider_live_executor_response_admit_parser.add_argument("--overwrite", action="store_true")
    provider_live_consume_executor_response_parser = subparsers.add_parser(
        "provider-live-consume-executor-response",
        help="Consume a local external-executor response manifest through Energy Reserve artifacts.",
    )
    provider_live_consume_executor_response_parser.add_argument(
        "--executor-response-manifest",
        type=Path,
        required=True,
    )
    provider_live_consume_executor_response_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_consume_executor_response_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_consume_executor_response_parser.add_argument("--capability", action="append", required=True)
    provider_live_consume_executor_response_parser.add_argument("--reference-date", default=None)
    provider_live_consume_executor_response_parser.add_argument("--root", type=Path, default=None)
    provider_live_consume_executor_response_parser.add_argument("--activity-type", default="hiking")
    provider_live_consume_executor_response_parser.add_argument("--overwrite", action="store_true")
    provider_live_consume_executor_pickup_response_parser = subparsers.add_parser(
        "provider-live-consume-executor-pickup-response",
        help="Consume a pickup-bound executor response manifest through Energy Reserve artifacts.",
    )
    provider_live_consume_executor_pickup_response_parser.add_argument(
        "--executor-response-manifest",
        type=Path,
        required=True,
    )
    provider_live_consume_executor_pickup_response_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_consume_executor_pickup_response_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_consume_executor_pickup_response_parser.add_argument("--capability", action="append", required=True)
    provider_live_consume_executor_pickup_response_parser.add_argument("--reference-date", default=None)
    provider_live_consume_executor_pickup_response_parser.add_argument("--root", type=Path, default=None)
    provider_live_consume_executor_pickup_response_parser.add_argument("--activity-type", default="hiking")
    provider_live_consume_executor_pickup_response_parser.add_argument("--overwrite", action="store_true")
    provider_live_executor_pickup_response_consumption_receipt_parser = subparsers.add_parser(
        "provider-live-executor-pickup-response-consumption-receipt",
        help="Write a local receipt for a pickup-bound executor response consumption artifact.",
    )
    provider_live_executor_pickup_response_consumption_receipt_parser.add_argument(
        "--pickup-response-consumption",
        type=Path,
        required=True,
    )
    provider_live_executor_pickup_response_consumption_receipt_parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    provider_live_executor_pickup_status_snapshot_parser = subparsers.add_parser(
        "provider-live-executor-pickup-status-snapshot",
        help="Write a local status snapshot for the executor handoff pickup lifecycle.",
    )
    provider_live_executor_pickup_status_snapshot_parser.add_argument(
        "--pickup-manifest",
        type=Path,
        required=True,
    )
    provider_live_executor_pickup_status_snapshot_parser.add_argument(
        "--executor-response-manifest",
        type=Path,
        default=None,
    )
    provider_live_executor_pickup_status_snapshot_parser.add_argument(
        "--pickup-response-consumption",
        type=Path,
        default=None,
    )
    provider_live_executor_pickup_status_snapshot_parser.add_argument(
        "--pickup-response-receipt",
        type=Path,
        default=None,
    )
    provider_live_executor_pickup_status_snapshot_parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    provider_live_executor_lifecycle_audit_parser = subparsers.add_parser(
        "provider-live-executor-lifecycle-audit",
        help="Write a local audit summary for pickup and inbox executor lifecycle status snapshots.",
    )
    provider_live_executor_lifecycle_audit_parser.add_argument(
        "--pickup-status-snapshot",
        type=Path,
        required=True,
    )
    provider_live_executor_lifecycle_audit_parser.add_argument(
        "--inbox-status-snapshot",
        type=Path,
        default=None,
    )
    provider_live_executor_lifecycle_audit_parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    provider_live_executor_production_readiness_gate_parser = subparsers.add_parser(
        "provider-live-executor-production-readiness-gate",
        help="Write a local production readiness gate from executor lifecycle audit evidence.",
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--lifecycle-audit",
        type=Path,
        required=True,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--connector-reference",
        type=Path,
        default=None,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--credential-vault-reference",
        type=Path,
        default=None,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--network-policy-reference",
        type=Path,
        default=None,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--runtime-ingest-boundary-reference",
        type=Path,
        default=None,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--phase1-safety-boundary-reference",
        type=Path,
        default=None,
    )
    provider_live_executor_production_readiness_gate_parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    provider_live_consume_executor_response_inbox_parser = subparsers.add_parser(
        "provider-live-consume-executor-response-inbox",
        help="Consume the first eligible local executor response manifest from an inbox index.",
    )
    provider_live_consume_executor_response_inbox_parser.add_argument("--inbox-index", type=Path, required=True)
    provider_live_consume_executor_response_inbox_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_consume_executor_response_inbox_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_consume_executor_response_inbox_parser.add_argument("--capability", action="append", required=True)
    provider_live_consume_executor_response_inbox_parser.add_argument(
        "--manifest-source-path",
        type=Path,
        default=None,
    )
    provider_live_consume_executor_response_inbox_parser.add_argument("--reference-date", default=None)
    provider_live_consume_executor_response_inbox_parser.add_argument("--root", type=Path, default=None)
    provider_live_consume_executor_response_inbox_parser.add_argument("--activity-type", default="hiking")
    provider_live_consume_executor_response_inbox_parser.add_argument("--overwrite", action="store_true")
    provider_live_consume_executor_response_inbox_batch_parser = subparsers.add_parser(
        "provider-live-consume-executor-response-inbox-batch",
        help="Consume all eligible local executor response manifests from an inbox index.",
    )
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--inbox-index", type=Path, required=True)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--capability", action="append", required=True)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--reference-date", default=None)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--root", type=Path, default=None)
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--activity-type", default="hiking")
    provider_live_consume_executor_response_inbox_batch_parser.add_argument("--overwrite", action="store_true")
    provider_live_executor_response_inbox_batch_receipt_parser = subparsers.add_parser(
        "provider-live-executor-response-inbox-batch-receipt",
        help="Write a local receipt for an executor response inbox batch consumption artifact.",
    )
    provider_live_executor_response_inbox_batch_receipt_parser.add_argument(
        "--batch-consumption",
        type=Path,
        required=True,
    )
    provider_live_executor_response_inbox_batch_receipt_parser.add_argument("--output", type=Path, required=True)
    provider_live_executor_response_inbox_status_snapshot_parser = subparsers.add_parser(
        "provider-live-executor-response-inbox-status-snapshot",
        help="Write a local status snapshot for executor response inbox manifests.",
    )
    provider_live_executor_response_inbox_status_snapshot_parser.add_argument(
        "--inbox-index",
        type=Path,
        required=True,
    )
    provider_live_executor_response_inbox_status_snapshot_parser.add_argument(
        "--batch-consumption",
        type=Path,
        default=None,
    )
    provider_live_executor_response_inbox_status_snapshot_parser.add_argument(
        "--batch-receipt",
        type=Path,
        default=None,
    )
    provider_live_executor_response_inbox_status_snapshot_parser.add_argument("--output", type=Path, required=True)
    provider_live_replay_admit_parser = subparsers.add_parser(
        "provider-live-replay-admit",
        help="Admit a local provider executor fixture-replay artifact into sanitized imports.",
    )
    provider_live_replay_admit_parser.add_argument("--fixture-replay", type=Path, required=True)
    provider_live_replay_admit_parser.add_argument("--output", type=Path, required=True)
    provider_live_replay_admit_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_replay_admit_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_replay_admit_parser.add_argument("--capability", action="append", required=True)
    provider_live_replay_admit_parser.add_argument("--activity-type", default="hiking")
    provider_live_replay_admit_parser.add_argument("--overwrite", action="store_true")
    provider_live_rehearse_executor_parser = subparsers.add_parser(
        "provider-live-rehearse-executor",
        help="Run a local registered-executor rehearsal from response fixture to Energy Reserve artifacts.",
    )
    provider_live_rehearse_executor_parser.add_argument("--request-plan", type=Path, required=True)
    provider_live_rehearse_executor_parser.add_argument("--executor-registration", type=Path, required=True)
    provider_live_rehearse_executor_parser.add_argument("--response-fixture", type=Path, required=True)
    provider_live_rehearse_executor_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_rehearse_executor_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_rehearse_executor_parser.add_argument("--capability", action="append", required=True)
    provider_live_rehearse_executor_parser.add_argument("--reference-date", default=None)
    provider_live_rehearse_executor_parser.add_argument("--root", type=Path, default=None)
    provider_live_rehearse_executor_parser.add_argument("--activity-type", default="hiking")
    provider_live_rehearse_executor_parser.add_argument("--overwrite", action="store_true")
    provider_live_response_admit_parser = subparsers.add_parser(
        "provider-live-response-admit",
        help="Admit a local provider response fixture through a request-plan-gated sanitized import path.",
    )
    provider_live_response_admit_parser.add_argument("--request-plan", type=Path, required=True)
    provider_live_response_admit_parser.add_argument("--response-fixture", type=Path, required=True)
    provider_live_response_admit_parser.add_argument("--output", type=Path, required=True)
    provider_live_response_admit_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_response_admit_parser.add_argument("--activity-id-prefix", required=True)
    provider_live_response_admit_parser.add_argument("--capability", action="append", required=True)
    provider_live_response_admit_parser.add_argument("--activity-type", default="hiking")
    provider_live_response_admit_parser.add_argument("--overwrite", action="store_true")
    provider_live_materialize_parser = subparsers.add_parser(
        "provider-live-materialize",
        help="Normalize admitted provider live response sanitized imports into local wearable summaries.",
    )
    provider_live_materialize_parser.add_argument("--admission", type=Path, required=True)
    provider_live_materialize_parser.add_argument("--output", type=Path, required=True)
    provider_live_materialize_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_materialize_parser.add_argument("--root", type=Path, default=None)
    provider_live_materialize_parser.add_argument("--overwrite", action="store_true")
    provider_live_sync_package_parser = subparsers.add_parser(
        "provider-live-sync-package",
        help="Wrap materialized provider live summaries into a local-only sync package.",
    )
    provider_live_sync_package_parser.add_argument("--materialization", type=Path, required=True)
    provider_live_sync_package_parser.add_argument("--output", type=Path, required=True)
    provider_live_sync_package_parser.add_argument("--root", type=Path, default=None)
    provider_live_build_energy_parser = subparsers.add_parser(
        "provider-live-build-energy",
        help="Build local Energy Reserve artifacts from a provider live sync package.",
    )
    provider_live_build_energy_parser.add_argument("--sync-package", type=Path, required=True)
    provider_live_build_energy_parser.add_argument("--output-dir", type=Path, required=True)
    provider_live_build_energy_parser.add_argument("--reference-date", default=None)
    provider_live_build_energy_parser.add_argument("--root", type=Path, default=None)
    live_frame_parser = subparsers.add_parser(
        "summarize-live-frame-fixture",
        help="Normalize local Apple/Garmin live-like frame fixtures into sanitized field observations.",
    )
    live_frame_parser.add_argument("--input", type=Path, required=True)
    live_frame_parser.add_argument(
        "--provider",
        choices=["apple_healthkit_live_fixture", "garmin_live_fixture"],
        required=True,
    )
    live_frame_parser.add_argument("--output-dir", type=Path, required=True)
    live_frame_parser.add_argument("--stream-id", required=True)
    live_frame_parser.add_argument("--route-segment-ref", default=None)
    live_frame_parser.add_argument("--expected-baseline-bpm", type=int, default=None)
    live_frame_parser.add_argument("--overwrite", action="store_true")
    build_parser = subparsers.add_parser(
        "build",
        help="Build local baseline, explanation, and companion capability capsule artifacts.",
    )
    build_parser.add_argument(
        "--activity",
        action="append",
        type=Path,
        required=True,
        help="Provider-neutral wearable activity summary JSON. Repeat for multiple activities.",
    )
    build_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for Scout Energy Reserve output artifacts.",
    )
    build_parser.add_argument(
        "--reference-date",
        default=None,
        help="Reference date for 7/28/90-day windows, formatted YYYY-MM-DD.",
    )
    build_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root used to render source_path values as privacy-preserving relative paths.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
