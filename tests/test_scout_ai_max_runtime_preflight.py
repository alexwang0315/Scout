from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from scout.nextgen.max_runtime_preflight import (
    MaxCliObservation,
    MaxEndpointObservation,
    MaxHostFacts,
    MaxReadinessCheckStatus,
    MaxRuntimeReadinessDisposition,
    max_runtime_readiness_report_hash,
    probe_max_endpoint,
    run_max_runtime_preflight,
)
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig


def _write_config(
    tmp_path: Path,
    *,
    base_url: str = "http://127.0.0.1:8000/v1",
    transport_scope: str = "loopback",
) -> Path:
    path = tmp_path / "max-runtime.json"
    path.write_text(
        json.dumps(
            {
                "runtime_id": "experimental.max.qualification",
                "provider": "max",
                "model_id": "Qwen/Qwen3-1.7B",
                "base_url": base_url,
                "transport_scope": transport_scope,
                "tier": "max_local_or_server",
                "locality": "mac_server",
                "accelerator": "gpu",
                "context_limit_tokens": 32768,
                "max_concurrency": 1,
                "offline_capable": False,
                "privacy_preserving": True,
                "api_key_env": None,
                "accepted_observed_model_ids": [],
                "experimental": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _intel_mac_host() -> MaxHostFacts:
    return MaxHostFacts(
        os_family="darwin",
        machine="x86_64",
        os_version="13.7.8",
        python_version="3.11.13",
        memory_bytes=8 * 1024**3,
    )


def _unavailable_endpoint() -> MaxEndpointObservation:
    return MaxEndpointObservation(
        health_status_code=None,
        health_path=None,
        model_status_code=None,
        observed_model_ids=(),
        error_type="ConnectError",
    )


def test_local_intel_mac_fails_before_any_model_qualification(
    tmp_path: Path,
) -> None:
    report = run_max_runtime_preflight(
        runtime_config_path=_write_config(tmp_path),
        host_facts=_intel_mac_host(),
        cli_observation=MaxCliObservation(available=False),
        endpoint_observation=_unavailable_endpoint(),
    )

    assert report.disposition is MaxRuntimeReadinessDisposition.HOST_INCOMPATIBLE
    assert report.model_request_count == 0
    assert report.provider_identity_verified is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["host_compatibility"].status is MaxReadinessCheckStatus.FAILED
    assert checks["cli_availability"].status is MaxReadinessCheckStatus.UNAVAILABLE
    assert checks["endpoint_health"].status is MaxReadinessCheckStatus.UNAVAILABLE
    assert checks["model_inventory"].status is MaxReadinessCheckStatus.NOT_RUN
    assert checks["authority_boundary"].status is MaxReadinessCheckStatus.PASSED
    assert report.candidate_only is True
    assert report.runtime_safety_truth is False
    assert max_runtime_readiness_report_hash(report) == report.report_hash


def test_external_endpoint_is_not_constrained_by_client_host(
    tmp_path: Path,
) -> None:
    report = run_max_runtime_preflight(
        runtime_config_path=_write_config(
            tmp_path,
            base_url="http://192.168.10.20:8000/v1",
            transport_scope="private_network",
        ),
        host_facts=_intel_mac_host(),
        cli_observation=MaxCliObservation(available=False),
        endpoint_observation=MaxEndpointObservation(
            health_status_code=200,
            health_path="/health",
            model_status_code=200,
            observed_model_ids=("Qwen/Qwen3-1.7B",),
        ),
    )

    assert (
        report.disposition
        is MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION
    )
    checks = {check.check_id: check for check in report.checks}
    assert (
        checks["host_compatibility"].status
        is MaxReadinessCheckStatus.NOT_APPLICABLE
    )
    assert checks["cli_availability"].status is MaxReadinessCheckStatus.NOT_APPLICABLE
    assert checks["endpoint_health"].status is MaxReadinessCheckStatus.PASSED
    assert checks["model_inventory"].status is MaxReadinessCheckStatus.PASSED
    assert report.provider_identity_verified is False


def test_endpoint_model_mismatch_fails_closed(tmp_path: Path) -> None:
    report = run_max_runtime_preflight(
        runtime_config_path=_write_config(
            tmp_path,
            base_url="http://192.168.10.20:8000/v1",
            transport_scope="private_network",
        ),
        host_facts=_intel_mac_host(),
        cli_observation=MaxCliObservation(available=False),
        endpoint_observation=MaxEndpointObservation(
            health_status_code=200,
            health_path="/health",
            model_status_code=200,
            observed_model_ids=("other/model",),
        ),
    )

    assert report.disposition is MaxRuntimeReadinessDisposition.MODEL_MISMATCH
    model_check = next(
        check for check in report.checks if check.check_id == "model_inventory"
    )
    assert model_check.status is MaxReadinessCheckStatus.FAILED
    assert report.model_request_count == 0


def test_probe_uses_max_health_and_model_inventory_routes(tmp_path: Path) -> None:
    config = OpenAICompatibleBackendConfig.from_json_file(_write_config(tmp_path))
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "id": "Qwen/Qwen3-1.7B",
                            "object": "model",
                            "owned_by": "",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected MAX probe path: {request.url.path}")

    observation = probe_max_endpoint(
        config,
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    assert requested_paths == ["/health", "/v1/models"]
    assert observation.health_status_code == 200
    assert observation.health_path == "/health"
    assert observation.model_status_code == 200
    assert observation.observed_model_ids == ("Qwen/Qwen3-1.7B",)


def test_report_hash_detects_tampering(tmp_path: Path) -> None:
    report = run_max_runtime_preflight(
        runtime_config_path=_write_config(tmp_path),
        host_facts=_intel_mac_host(),
        cli_observation=MaxCliObservation(available=False),
        endpoint_observation=_unavailable_endpoint(),
    )
    tampered = report.model_copy(update={"requested_model_id": "other/model"})

    assert max_runtime_readiness_report_hash(tampered) != tampered.report_hash


def test_preflight_binds_frozen_qualification_inputs(tmp_path: Path) -> None:
    case_path = tmp_path / "case.json"
    evidence_path = tmp_path / "evidence.json"
    launcher_path = tmp_path / "launcher.py"
    case_path.write_text('{"case":"frozen"}\n', encoding="utf-8")
    evidence_path.write_text('{"evidence":"frozen"}\n', encoding="utf-8")
    launcher_path.write_text("# frozen launcher\n", encoding="utf-8")

    report = run_max_runtime_preflight(
        runtime_config_path=_write_config(tmp_path),
        host_facts=_intel_mac_host(),
        cli_observation=MaxCliObservation(available=False),
        endpoint_observation=_unavailable_endpoint(),
        case_path=case_path,
        evidence_catalog_path=evidence_path,
        qualification_launcher_path=launcher_path,
    )

    assert report.qualification_inputs is not None
    assert report.qualification_inputs.case_sha256 == hashlib.sha256(
        case_path.read_bytes()
    ).hexdigest()
    assert report.qualification_inputs.evidence_catalog_sha256 == hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()
    assert report.qualification_inputs.required_checks[-2:] == (
        "praison_mcp",
        "authority_boundary",
    )
