from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import admin_api
import cwa_route_identity


NOW = datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("evaluated_at", "approved_at", "message"),
    (
        (NOW.replace(tzinfo=None), NOW, "timezone"),
        (NOW, NOW + timedelta(minutes=6), "future"),
        (NOW, NOW - timedelta(days=8), "stale"),
    ),
)
def test_location_approval_window_rejects_invalid_clock_ranges(
    evaluated_at: datetime,
    approved_at: datetime,
    message: str,
) -> None:
    request = SimpleNamespace(location_approved_at=approved_at)

    with pytest.raises(ValueError, match=message):
        admin_api._validate_location_approval_window(
            request,
            evaluated_at=evaluated_at,
        )


def test_compact_risk_segments_preserves_non_contract_payloads() -> None:
    assert admin_api._compact_risk_segment_collection("raw") == "raw"
    assert admin_api._compact_risk_segment_collection({"status": "ready"}) == {
        "status": "ready"
    }


def test_rainfall_projection_cell_counts_skip_invalid_features() -> None:
    assert admin_api._rainfall_projection_available_cell_counts(
        {
            "features": [
                "invalid",
                {},
                {"properties": {"gridKind": "qpe_past_1h"}},
                {"properties": {"gridKind": "qpe_past_1h"}},
            ]
        }
    ) == {"qpe_past_1h": 2}


def test_rainfall_projection_loader_rejects_missing_and_invalid_contracts(
    tmp_path: Path,
) -> None:
    project = {
        "cwa_rainfall_route_projection_ref": "outputs/cwa/projection.json"
    }

    with pytest.raises(HTTPException) as missing:
        admin_api._load_pretrip_rainfall_projection(
            tmp_path,
            project,
            required=True,
        )
    assert missing.value.status_code == 404

    projection_path = tmp_path / "outputs" / "cwa" / "projection.json"
    projection_path.parent.mkdir(parents=True)
    projection_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(HTTPException) as malformed:
        admin_api._load_pretrip_rainfall_projection(
            tmp_path,
            project,
            required=True,
        )
    assert malformed.value.status_code == 422

    projection_path.write_text(json.dumps({"artifactKind": "wrong"}), encoding="utf-8")
    with pytest.raises(HTTPException) as wrong_kind:
        admin_api._load_pretrip_rainfall_projection(
            tmp_path,
            project,
            required=True,
        )
    assert wrong_kind.value.status_code == 422


def test_cwa_api_identity_wrapper_rejects_invalid_project_contract(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "project.json"
    project_path.write_text("[]", encoding="utf-8")
    with pytest.raises(HTTPException) as non_mapping:
        admin_api._validate_cwa_artifact_route_identity(
            tmp_path,
            requested_project_id="fixture",
            artifact={},
            artifact_label="rainfall projection",
        )
    assert non_mapping.value.status_code == 422

    project_path.write_text(json.dumps({"project_id": "other"}), encoding="utf-8")
    with pytest.raises(HTTPException) as wrong_project:
        admin_api._validate_cwa_artifact_route_identity(
            tmp_path,
            requested_project_id="fixture",
            artifact={},
            artifact_label="rainfall projection",
        )
    assert wrong_project.value.status_code == 422


def test_location_approval_issue_rejects_naive_clock_and_invalid_registry(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="timezone"):
        admin_api._issue_rainfall_location_approval(
            tmp_path,
            project_id="fixture",
            scope="current_trip_rainfall_sampling",
            operator_alias="tester",
            ttl_minutes=30,
            issued_at=NOW.replace(tzinfo=None),
        )

    _, registry_path = admin_api._rainfall_location_approval_registry_path(tmp_path)
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid rainfall location approval registry"):
        admin_api._issue_rainfall_location_approval(
            tmp_path,
            project_id="fixture",
            scope="current_trip_rainfall_sampling",
            operator_alias="tester",
            ttl_minutes=30,
            issued_at=NOW,
        )


def _write_approval_registry(project_root: Path, approvals: object) -> Path:
    _, registry_path = admin_api._rainfall_location_approval_registry_path(project_root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps({"approvals": approvals}),
        encoding="utf-8",
    )
    return registry_path


def _verify_approval(project_root: Path, *, approved_at: datetime = NOW) -> str:
    return admin_api._verify_rainfall_location_approval(
        project_root,
        project_id="fixture",
        approval_reference="approval.fixture",
        approved_at=approved_at,
        scope="current_trip_rainfall_sampling",
        evaluated_at=NOW,
    )


def test_location_approval_verifier_rejects_corrupt_registry_and_records(
    tmp_path: Path,
) -> None:
    registry_path = _write_approval_registry(tmp_path, [])
    registry_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid rainfall location approval registry"):
        _verify_approval(tmp_path)

    _write_approval_registry(tmp_path, [{"reference": "approval.fixture"}])
    with pytest.raises(ValueError, match="invalid rainfall location approval record"):
        _verify_approval(tmp_path)

    _write_approval_registry(
        tmp_path,
        [
            {
                "reference": "approval.fixture",
                "approvedAt": "2026-07-13T04:00:00",
                "expiresAt": "2026-07-13T05:00:00",
            }
        ],
    )
    with pytest.raises(ValueError, match="timezone is missing"):
        _verify_approval(tmp_path)


def test_location_approval_verifier_rejects_mismatch_and_revocation(
    tmp_path: Path,
) -> None:
    base_record = {
        "reference": "approval.fixture",
        "projectId": "fixture",
        "scope": "current_trip_rainfall_sampling",
        "approvedAt": NOW.isoformat(),
        "expiresAt": (NOW + timedelta(minutes=30)).isoformat(),
        "revoked": False,
    }
    _write_approval_registry(tmp_path, [base_record])
    with pytest.raises(ValueError, match="timestamp mismatch"):
        _verify_approval(tmp_path, approved_at=NOW - timedelta(minutes=1))

    _write_approval_registry(tmp_path, [{**base_record, "revoked": True}])
    with pytest.raises(ValueError, match="is not valid"):
        _verify_approval(tmp_path)


def test_location_approval_verifier_legacy_mode_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCOUT_ALLOW_LEGACY_CALLER_LOCATION_ATTESTATION", "true")
    assert _verify_approval(tmp_path) == "caller_attestation_legacy"


@pytest.mark.parametrize("failure", (OSError("missing"), ValueError("invalid")))
def test_pretrip_route_loader_translates_identity_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    (tmp_path / "project.json").write_text(
        json.dumps({"project_id": "fixture"}),
        encoding="utf-8",
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise failure

    monkeypatch.setattr(cwa_route_identity, "load_cwa_route_identity", fail)
    with pytest.raises(HTTPException) as raised:
        admin_api._pretrip_rainfall_project_and_route(tmp_path)
    assert raised.value.status_code == (404 if isinstance(failure, OSError) else 422)
