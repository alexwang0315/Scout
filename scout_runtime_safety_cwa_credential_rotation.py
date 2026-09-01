from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from scout_energy_models import aggregate_sha256
from scout_runtime_safety_live_qualification import (
    CwaLiveQualificationReport,
    load_cwa_live_qualification_report,
)


class CwaCredentialRotationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_cwa_credential_rotation_receipt"
    artifact_version: str = "cwa_credential_rotation_receipt.v0"
    source_provider: str = "scout_runtime_safety_cwa_credential_rotation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    credential_ref: str = Field(min_length=1)
    credential_scope: Literal["cwa_open_data_read_only"] = (
        "cwa_open_data_read_only"
    )
    provider_management_ref: str = Field(min_length=1)
    operator_identity_ref: str = Field(min_length=1)
    execution_host_ref: str = Field(min_length=1)
    post_rotation_live_report_ref: str = Field(min_length=1)
    post_rotation_live_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    post_rotation_live_report_observed_at: datetime
    provider_rotation_observed: bool = False
    previous_credential_invalidated: bool = False
    credential_scope_verified: bool = False
    mac_secret_refs_updated: bool = False
    pi_secret_ref_updated: bool = False
    pi_runtime_credential_refs_configured: bool = False
    secret_file_permissions_verified: bool = False
    post_rotation_pi_live_call_verified: bool = False
    credential_material_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    production_database_mutated: bool = False
    safety_api_called: bool = False
    runtime_safety_truth_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_receipt(self) -> "CwaCredentialRotationReceipt":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        report_time = self.post_rotation_live_report_observed_at
        if report_time.tzinfo is None or report_time.utcoffset() is None:
            raise ValueError("live report observation must be timezone-aware")
        if report_time > self.observed_at:
            raise ValueError("rotation receipt cannot predate the post-rotation run")
        if not self.source_path.startswith("prod://"):
            raise ValueError("source_path must use prod://")
        if not self.credential_ref.startswith(("secret://", "vault://", "kms://")):
            raise ValueError("credential_ref must be opaque")
        if self.provider_management_ref != "https://opendata.cwa.gov.tw/user/authkey":
            raise ValueError("provider management ref must identify the CWA authkey page")
        if not self.operator_identity_ref.startswith("operator://"):
            raise ValueError("operator identity must use operator://")
        if not self.execution_host_ref.startswith("pi://"):
            raise ValueError("credential rotation receipt requires Pi execution")
        if not self.post_rotation_live_report_ref.startswith("prod://"):
            raise ValueError("post-rotation live report ref must use prod://")
        if any(
            (
                self.credential_material_embedded,
                self.raw_provider_payload_embedded,
                self.production_database_mutated,
                self.safety_api_called,
                self.runtime_safety_truth_mutated,
                self.outbound_transport_invoked,
                self.hardware_control_performed,
            )
        ):
            raise ValueError("credential rotation receipt must remain sanitized")
        return self

    @computed_field
    @property
    def ready_for_credential_qualification(self) -> bool:
        return all(
            (
                self.provider_rotation_observed,
                self.previous_credential_invalidated,
                self.credential_scope_verified,
                self.mac_secret_refs_updated,
                self.pi_secret_ref_updated,
                self.pi_runtime_credential_refs_configured,
                self.secret_file_permissions_verified,
                self.post_rotation_pi_live_call_verified,
            )
        )


def build_cwa_credential_rotation_receipt(
    *,
    source_path: str,
    observed_at: datetime,
    credential_ref: str,
    provider_management_ref: str,
    operator_identity_ref: str,
    live_report: CwaLiveQualificationReport,
    provider_rotation_observed: bool,
    previous_credential_invalidated: bool,
    credential_scope_verified: bool,
    mac_secret_refs_updated: bool,
    pi_secret_ref_updated: bool,
    pi_runtime_credential_refs_configured: bool,
    secret_file_permissions_verified: bool,
) -> CwaCredentialRotationReceipt:
    post_rotation_verified = bool(
        live_report.status == "cwa_live_chain_verified"
        and live_report.execution_host_ref.startswith("pi://")
        and live_report.credential_ref_resolved_without_value
        and live_report.connector_health_evidence_ready
        and live_report.live_provider_api_evidence_ready
    )
    receipt = CwaCredentialRotationReceipt(
        source_path=source_path,
        sha256="0" * 64,
        observed_at=observed_at,
        credential_ref=credential_ref,
        provider_management_ref=provider_management_ref,
        operator_identity_ref=operator_identity_ref,
        execution_host_ref=live_report.execution_host_ref,
        post_rotation_live_report_ref=live_report.source_path,
        post_rotation_live_report_sha256=live_report.sha256,
        post_rotation_live_report_observed_at=live_report.observed_at,
        provider_rotation_observed=provider_rotation_observed,
        previous_credential_invalidated=previous_credential_invalidated,
        credential_scope_verified=credential_scope_verified,
        mac_secret_refs_updated=mac_secret_refs_updated,
        pi_secret_ref_updated=pi_secret_ref_updated,
        pi_runtime_credential_refs_configured=(
            pi_runtime_credential_refs_configured
        ),
        secret_file_permissions_verified=secret_file_permissions_verified,
        post_rotation_pi_live_call_verified=post_rotation_verified,
        limitations=[
            "Contains opaque references and reviewed booleans only; no credential value or raw CWA payload is embedded.",
            "Does not authorize production cutover or any outbound emergency effect.",
        ],
    )
    return receipt.model_copy(update={"sha256": _receipt_sha256(receipt)})


def write_cwa_credential_rotation_receipt(
    receipt: CwaCredentialRotationReceipt,
    path: str | Path,
) -> Path:
    if _receipt_sha256(receipt) != receipt.sha256:
        raise ValueError("credential rotation receipt sha256 mismatch")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        receipt.model_dump_json(
            indent=2,
            exclude={"ready_for_credential_qualification"},
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def load_cwa_credential_rotation_receipt(
    path: str | Path,
) -> CwaCredentialRotationReceipt:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    receipt = CwaCredentialRotationReceipt.model_validate(payload)
    if _receipt_sha256(receipt) != receipt.sha256:
        raise ValueError("credential rotation receipt sha256 mismatch")
    return receipt


def _receipt_sha256(receipt: CwaCredentialRotationReceipt) -> str:
    payload = receipt.model_dump(
        mode="json",
        exclude={"sha256", "ready_for_credential_qualification"},
    )
    return aggregate_sha256([payload])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind reviewed CWA credential-rotation facts to a sanitized "
            "post-rotation Pi live report."
        )
    )
    parser.add_argument("--live-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--operator-identity-ref", required=True)
    parser.add_argument(
        "--provider-management-ref",
        default="https://opendata.cwa.gov.tw/user/authkey",
    )
    parser.add_argument("--observed-at")
    parser.add_argument("--provider-rotation-observed", action="store_true")
    parser.add_argument("--previous-credential-invalidated", action="store_true")
    parser.add_argument("--credential-scope-verified", action="store_true")
    parser.add_argument("--mac-secret-refs-updated", action="store_true")
    parser.add_argument("--pi-secret-ref-updated", action="store_true")
    parser.add_argument(
        "--pi-runtime-credential-refs-configured",
        action="store_true",
    )
    parser.add_argument("--secret-file-permissions-verified", action="store_true")
    args = parser.parse_args(argv)

    report = load_cwa_live_qualification_report(args.live_report)
    observed_at = (
        datetime.fromisoformat(args.observed_at.replace("Z", "+00:00"))
        if args.observed_at
        else datetime.now(timezone.utc)
    )
    receipt = build_cwa_credential_rotation_receipt(
        source_path=args.source_path,
        observed_at=observed_at,
        credential_ref=report.credential_ref,
        provider_management_ref=args.provider_management_ref,
        operator_identity_ref=args.operator_identity_ref,
        live_report=report,
        provider_rotation_observed=args.provider_rotation_observed,
        previous_credential_invalidated=args.previous_credential_invalidated,
        credential_scope_verified=args.credential_scope_verified,
        mac_secret_refs_updated=args.mac_secret_refs_updated,
        pi_secret_ref_updated=args.pi_secret_ref_updated,
        pi_runtime_credential_refs_configured=(
            args.pi_runtime_credential_refs_configured
        ),
        secret_file_permissions_verified=args.secret_file_permissions_verified,
    )
    output_path = write_cwa_credential_rotation_receipt(receipt, args.output)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "post_rotation_pi_live_call_verified": (
                    receipt.post_rotation_pi_live_call_verified
                ),
                "ready_for_credential_qualification": (
                    receipt.ready_for_credential_qualification
                ),
                "status": (
                    "credential_rotation_verified"
                    if receipt.ready_for_credential_qualification
                    else "credential_rotation_incomplete"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
