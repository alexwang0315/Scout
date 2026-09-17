from __future__ import annotations

import json

from scout_runtime_safety_live_qualification import (
    CwaLiveQualificationConfig,
    build_cwa_live_config_from_target_profile,
    load_cwa_live_qualification_report,
    main,
    run_cwa_live_qualification,
    write_cwa_live_qualification_report,
)


def _config(*, allow_live_provider_call: bool = True) -> CwaLiveQualificationConfig:
    return CwaLiveQualificationConfig(
        source_path="prod://qualification/cwa/live-run-001",
        run_id="cwa-live-run-001",
        execution_host_ref="prod://runtime/test-host",
        route_scope_ref="runtime://route/chilai-nanhua/day1",
        route_id="runtime.route.chilai-nanhua",
        segment_id="seg.001",
        location_name="南投縣",
        credential_ref="secret://scout/cwa/opendata-api-token",
        operator_identity_ref="operator://identity/scout-owner",
        operator_role="scout_owner",
        allow_live_provider_call=allow_live_provider_call,
    )


def _successful_payload() -> dict[str, object]:
    return {
        "success": "true",
        "records": {
            "datasetDescription": "36-hour forecast",
            "location": [{"locationName": "南投縣"}],
        },
    }


def _target_profile() -> dict[str, object]:
    return {
        "source_path": "prod://qualification/scout-safety-production-20260831/target-profile",
        "route_scope_ref": "runtime://route/chilai-nanhua/day1",
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
        },
        "runtime_target": {"host_ref": "pi://scout/runtime"},
        "provider_target": {
            "provider_id": "cwa_opendata",
            "connector_id": "connector.cwa.weather",
            "forecast_dataset_id": "F-C0032-001",
            "location_name": "南投縣",
            "credential_ref": "secret://scout/cwa/opendata-api-token",
        },
        "operator_authorization": {
            "operator_identity_ref": "operator://identity/scout-owner",
            "operator_role": "scout_owner",
            "cwa_live_read_authorized": True,
        },
    }


def test_cwa_live_qualification_uses_existing_guards_and_sanitizes_output(tmp_path) -> None:
    calls: list[str] = []

    def fetcher(dataset_id: str, **kwargs: object) -> dict[str, object]:
        calls.append(dataset_id)
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["SCOUT_CWA_API_KEY"] == "test-secret-value"
        return _successful_payload()

    report = run_cwa_live_qualification(
        _config(),
        env={"SCOUT_CWA_API_KEY": "test-secret-value"},
        fetcher=fetcher,
    )
    output = tmp_path / "cwa-live-report.json"
    write_cwa_live_qualification_report(report, output)
    loaded = load_cwa_live_qualification_report(output)
    serialized = json.dumps(loaded.model_dump(mode="json"), sort_keys=True)

    assert calls == ["F-C0032-001", "F-C0032-001"]
    assert loaded.status == "cwa_live_chain_verified"
    assert loaded.credential_ref_resolved_without_value is True
    assert loaded.connector_health_status == "connector_health_receipt_emitted"
    assert loaded.connector_manifest_status == "connector_manifest_prepared"
    assert loaded.provider_request_status == "provider_request_boundary_authorized"
    assert loaded.provider_executor_status == (
        "ready_for_reviewed_provider_effect_boundary"
    )
    assert loaded.provider_invocation_status == (
        "provider_executor_invocation_authorized"
    )
    assert loaded.provider_execution_status == "provider_effect_receipt_emitted"
    assert loaded.provider_effect_intake_status == (
        "provider_response_receipt_prepared"
    )
    assert loaded.provider_response_intake_status == "live_observation_prepared"
    assert loaded.connector_health_evidence_ready is True
    assert loaded.live_provider_api_evidence_ready is True
    assert loaded.external_provider_calls_performed is True
    assert loaded.credential_material_used_by_executor is True
    assert loaded.credential_material_embedded is False
    assert loaded.raw_provider_payload_persisted is False
    assert loaded.runtime_ingest_performed is False
    assert loaded.safety_api_called is False
    assert loaded.phase1_l0_l4_state_mutated is False
    assert loaded.outbound_transport_invoked is False
    assert loaded.hardware_control_performed is False
    assert "test-secret-value" not in serialized
    assert "datasetDescription" not in serialized
    assert loaded == report


def test_cwa_live_qualification_blocks_before_resolving_credentials_without_authorization() -> None:
    calls: list[str] = []

    report = run_cwa_live_qualification(
        _config(allow_live_provider_call=False),
        env={"SCOUT_CWA_API_KEY": "test-secret-value"},
        fetcher=lambda dataset_id, **_kwargs: calls.append(dataset_id) or {},
    )

    assert report.status == "blocked_live_call_not_authorized"
    assert report.credential_ref_resolved_without_value is False
    assert report.external_provider_calls_performed is False
    assert calls == []


def test_cwa_live_qualification_blocks_missing_credential_without_calling_provider() -> None:
    calls: list[str] = []

    report = run_cwa_live_qualification(
        _config(),
        env={},
        fetcher=lambda dataset_id, **_kwargs: calls.append(dataset_id) or {},
    )

    assert report.status == "blocked_credential_ref_unresolved"
    assert report.credential_ref_resolved_without_value is False
    assert report.external_provider_calls_performed is False
    assert calls == []


def test_cwa_live_qualification_fails_closed_when_health_probe_errors() -> None:
    calls: list[str] = []

    def failing_fetcher(dataset_id: str, **_kwargs: object) -> dict[str, object]:
        calls.append(dataset_id)
        raise TimeoutError("provider timeout with sensitive URL omitted")

    report = run_cwa_live_qualification(
        _config(),
        env={"SCOUT_CWA_API_KEY": "test-secret-value"},
        fetcher=failing_fetcher,
    )

    assert report.status == "blocked_connector_health"
    assert report.connector_health_status == (
        "blocked_connector_health_client_result_invalid"
    )
    assert report.connector_health_evidence_ready is False
    assert report.live_provider_api_evidence_ready is False
    assert report.external_provider_calls_performed is True
    assert report.runtime_ingest_performed is False
    assert report.outbound_transport_invoked is False
    assert calls == ["F-C0032-001"]


def test_target_profile_requires_both_profile_and_cli_live_authorization() -> None:
    blocked = build_cwa_live_config_from_target_profile(
        _target_profile(),
        allow_live_provider_call=False,
    )
    allowed = build_cwa_live_config_from_target_profile(
        _target_profile(),
        allow_live_provider_call=True,
    )

    assert blocked.allow_live_provider_call is False
    assert allowed.allow_live_provider_call is True
    assert allowed.execution_host_ref == "pi://scout/runtime"
    assert allowed.credential_ref == "secret://scout/cwa/opendata-api-token"


def test_cwa_live_qualification_cli_writes_blocked_report_without_allow_flag(
    tmp_path,
) -> None:
    profile_path = tmp_path / "target-profile.json"
    output_path = tmp_path / "report.json"
    profile_path.write_text(json.dumps(_target_profile()), encoding="utf-8")

    exit_code = main(
        [
            "--target-profile",
            str(profile_path),
            "--env-root",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )
    report = load_cwa_live_qualification_report(output_path)

    assert exit_code == 2
    assert report.status == "blocked_live_call_not_authorized"
    assert report.external_provider_calls_performed is False
