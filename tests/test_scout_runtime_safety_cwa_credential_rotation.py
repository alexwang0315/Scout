from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scout_runtime_safety_cwa_credential_rotation import (
    build_cwa_credential_rotation_receipt,
    load_cwa_credential_rotation_receipt,
    main,
    write_cwa_credential_rotation_receipt,
)
from scout_runtime_safety_live_qualification import (
    CwaLiveQualificationConfig,
    run_cwa_live_qualification,
    write_cwa_live_qualification_report,
)


def _pi_report():
    config = CwaLiveQualificationConfig(
        source_path="prod://qualification/run-001/cwa-live",
        run_id="run-001-cwa-live",
        execution_host_ref="pi://scout/runtime",
        route_scope_ref="runtime://route/chilai-nanhua/day1",
        route_id="runtime.route.chilai-nanhua",
        segment_id="seg.001",
        location_name="南投縣",
        credential_ref="secret://scout/cwa/opendata-api-token",
        operator_identity_ref="operator://identity/scout-owner",
        operator_role="scout_owner",
        allow_live_provider_call=True,
    )
    return run_cwa_live_qualification(
        config,
        env={"SCOUT_CWA_API_KEY": "test-secret-value"},
        fetcher=lambda _dataset_id, **_kwargs: {
            "success": "true",
            "records": {"location": [{"locationName": "南投縣"}]},
        },
        now=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
    )


def test_rotation_receipt_is_ready_without_embedding_credentials(tmp_path) -> None:
    report = _pi_report()
    receipt = build_cwa_credential_rotation_receipt(
        source_path="prod://qualification/run-001/cwa-credential-rotation",
        observed_at=report.observed_at + timedelta(minutes=1),
        credential_ref=report.credential_ref,
        provider_management_ref="https://opendata.cwa.gov.tw/user/authkey",
        operator_identity_ref="operator://identity/scout-owner",
        live_report=report,
        provider_rotation_observed=True,
        previous_credential_invalidated=True,
        credential_scope_verified=True,
        mac_secret_refs_updated=True,
        pi_secret_ref_updated=True,
        pi_runtime_credential_refs_configured=True,
        secret_file_permissions_verified=True,
    )
    path = write_cwa_credential_rotation_receipt(receipt, tmp_path / "receipt.json")
    loaded = load_cwa_credential_rotation_receipt(path)

    assert loaded.ready_for_credential_qualification is True
    assert loaded.post_rotation_pi_live_call_verified is True
    assert loaded.credential_material_embedded is False
    assert loaded.raw_provider_payload_embedded is False


def test_rotation_receipt_fails_closed_when_pi_secret_update_is_missing() -> None:
    report = _pi_report()
    receipt = build_cwa_credential_rotation_receipt(
        source_path="prod://qualification/run-001/cwa-credential-rotation",
        observed_at=report.observed_at + timedelta(minutes=1),
        credential_ref=report.credential_ref,
        provider_management_ref="https://opendata.cwa.gov.tw/user/authkey",
        operator_identity_ref="operator://identity/scout-owner",
        live_report=report,
        provider_rotation_observed=True,
        previous_credential_invalidated=True,
        credential_scope_verified=True,
        mac_secret_refs_updated=True,
        pi_secret_ref_updated=False,
        pi_runtime_credential_refs_configured=True,
        secret_file_permissions_verified=True,
    )

    assert receipt.ready_for_credential_qualification is False


def test_rotation_receipt_loader_rejects_tampered_lineage(tmp_path) -> None:
    report = _pi_report()
    receipt = build_cwa_credential_rotation_receipt(
        source_path="prod://qualification/run-001/cwa-credential-rotation",
        observed_at=report.observed_at + timedelta(minutes=1),
        credential_ref=report.credential_ref,
        provider_management_ref="https://opendata.cwa.gov.tw/user/authkey",
        operator_identity_ref="operator://identity/scout-owner",
        live_report=report,
        provider_rotation_observed=True,
        previous_credential_invalidated=True,
        credential_scope_verified=True,
        mac_secret_refs_updated=True,
        pi_secret_ref_updated=True,
        pi_runtime_credential_refs_configured=True,
        secret_file_permissions_verified=True,
    )
    path = write_cwa_credential_rotation_receipt(receipt, tmp_path / "receipt.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pi_runtime_credential_refs_configured"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_cwa_credential_rotation_receipt(path)


def test_cli_writes_ready_receipt_from_pi_report(tmp_path) -> None:
    report = _pi_report()
    report_path = write_cwa_live_qualification_report(
        report,
        tmp_path / "live-report.json",
    )
    receipt_path = tmp_path / "rotation-receipt.json"

    exit_code = main(
        [
            "--live-report",
            str(report_path),
            "--output",
            str(receipt_path),
            "--source-path",
            "prod://qualification/run-001/cwa-credential-rotation",
            "--operator-identity-ref",
            "operator://identity/scout-owner",
            "--observed-at",
            (report.observed_at + timedelta(minutes=1)).isoformat(),
            "--provider-rotation-observed",
            "--previous-credential-invalidated",
            "--credential-scope-verified",
            "--mac-secret-refs-updated",
            "--pi-secret-ref-updated",
            "--pi-runtime-credential-refs-configured",
            "--secret-file-permissions-verified",
        ]
    )

    assert exit_code == 0
    assert (
        load_cwa_credential_rotation_receipt(
            receipt_path
        ).ready_for_credential_qualification
        is True
    )
