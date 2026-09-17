"""Trusted Dashboard entrypoint and real imagery guards; no provider execution."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError

import pytest

import dashboard_connected_preparation as connected
import dashboard_workspace_preparation as workspace
import pretrip_layer_preparation as preparation
import radar_satellite_risk_extractor as imagery
from scout_env import ScoutEnvLoadResult


CAPABILITY = "SCOUT_CWA_SERVER_IMAGERY_CAPABLE"
NOW = "2026-09-09T08:00:00+00:00"


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def capability_route(tmp_path, monkeypatch):
    # Track the key even when absent so a trusted entrypoint grant is undone
    # after this test and cannot change another test's default-denial case.
    monkeypatch.setenv(CAPABILITY, "")
    root = tmp_path / "workspace/route"
    project = {"project_id": "route", "segment_display_geometry_ref": "outputs/segments.json"}
    _write(root / "project.json", project)
    _write(root / project["segment_display_geometry_ref"], {
        "artifact_kind": "pretrip_segment_display_geometry", "project_id": "route",
        "route_artifact_id": "artifact.gpx.route",
        "segments": [{"coordinate_segments": [[
            {"lat": 23.0, "lon": 121.0}, {"lat": 23.01, "lon": 121.01},
        ]]}],
    })
    monkeypatch.setattr(imagery.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(imagery, "_is_raspberry_pi_host", lambda: False)
    calls = []

    def processing_after_guards(**kwargs):
        calls.append(kwargs)
        return {"fixture_processing_reached": True}

    monkeypatch.setattr(imagery, "_run_server_side_cwa_imagery_job_unlocked", processing_after_guards)

    def pipeline(request):
        return preparation._maybe_prepare_cwa_imagery_server_job(
            project_root=root, project=project, request=request, prepared_at=NOW,
        )

    monkeypatch.setattr(workspace, "run_layer_preparation", pipeline)
    options = {"layers": ["cwa-weather"], "profile": "mac-workstation",
               "network_mode": "explicit-fetch", "allow_network_fetch": True,
               "prepare_cwa_imagery": True}
    return root, project, options, calls


def test_direct_preparation_defaults_to_capability_denial(capability_route):
    root, project, options, calls = capability_route
    request = workspace.build_workspace_preparation_request(root, preparation_options=options)
    result = preparation._maybe_prepare_cwa_imagery_server_job(
        project_root=root, project=project, request=request, prepared_at=NOW,
    )
    assert result["cwa_weather_imagery_status"] == "fetch_or_processing_failed"
    assert result["cwa_weather_imagery_error"]["error_code"] == "CWA_IMAGERY_SERVER_CAPABILITY_REQUIRED"
    assert not calls
    assert not (root / "cache/cwa-weather-imagery/.server-job.lock").exists()
    assert os.environ[CAPABILITY] == ""


def test_full_dashboard_path_attests_eligible_server_and_reaches_real_job_guard(capability_route):
    root, _project, options, calls = capability_route
    result = workspace.prepare_imported_workspace(root, preparation_options=options)
    assert result["cwa_weather_imagery_status"] == "ready"
    assert result["fixture_processing_reached"] is True
    assert len(calls) == 1
    assert calls[0]["processing_profile"] == "mac-workstation"
    assert calls[0]["allow_network_fetch"] is True
    assert calls[0]["route_identity"]["projectId"] == "route"
    assert (root / "cache/cwa-weather-imagery/.server-job.lock").is_file()
    assert os.environ[CAPABILITY] == "1"


@pytest.mark.parametrize("architecture,is_pi", [("arm64", False), ("aarch64", False), ("x86_64", True)])
def test_trusted_dashboard_does_not_bypass_actual_host_denial(capability_route, monkeypatch, architecture, is_pi):
    root, _project, options, calls = capability_route
    monkeypatch.setattr(imagery.platform, "machine", lambda: architecture)
    monkeypatch.setattr(imagery, "_is_raspberry_pi_host", lambda: is_pi)
    result = workspace.prepare_imported_workspace(root, preparation_options=options)
    assert result["cwa_weather_imagery_error"]["error_code"] == "CWA_IMAGERY_HOST_UNSUPPORTED"
    assert not calls
    assert not (root / "cache/cwa-weather-imagery/.server-job.lock").exists()


@pytest.mark.parametrize("overrides,blocker", [
    ({"profile": "pi-online-explicit"}, "profile_must_be_mac_workstation"),
    ({"network_mode": "no-network"}, "explicit_fetch_and_allow_network_fetch_required"),
    ({"allow_network_fetch": False}, "explicit_fetch_and_allow_network_fetch_required"),
])
def test_full_preparation_keeps_profile_and_both_network_guards(capability_route, overrides, blocker):
    root, _project, options, calls = capability_route
    result = workspace.prepare_imported_workspace(root, preparation_options={**options, **overrides})
    assert result["cwa_weather_imagery_blocker"] == blocker
    assert not calls
    assert os.environ[CAPABILITY] == ""


def test_disabled_imagery_does_not_attest_or_run(capability_route):
    root, _project, options, calls = capability_route
    result = workspace.prepare_imported_workspace(root, preparation_options={**options, "prepare_cwa_imagery": False})
    assert result == {"cwa_weather_imagery_status": "not_requested"}
    assert not calls and os.environ[CAPABILITY] == ""


@pytest.mark.parametrize("key", [CAPABILITY, "server_capability_attested", "environ"])
def test_caller_cannot_supply_capability_override(capability_route, key):
    root, _project, options, calls = capability_route
    with pytest.raises(ValueError, match="unsupported preparation options"):
        workspace.prepare_imported_workspace(root, preparation_options={**options, key: True})
    assert not calls and os.environ[CAPABILITY] == ""


def test_real_job_rate_limit_has_fixed_safe_error_code(capability_route):
    root, _project, options, calls = capability_route
    cache = root / "cache/cwa-weather-imagery"
    cache.mkdir(parents=True)
    (cache / ".server-job-completed-at").write_text(str(time.time()))
    result = workspace.prepare_imported_workspace(root, preparation_options=options)
    assert result["cwa_weather_imagery_error"]["error_code"] == "CWA_IMAGERY_JOB_RATE_LIMITED"
    assert not calls


@pytest.mark.parametrize("message,code", [
    ("trusted server imagery capability attestation is required", "CWA_IMAGERY_SERVER_CAPABILITY_REQUIRED"),
    ("CWA imagery processing is server-side only; Pi/mobile consume prepared artifacts", "CWA_IMAGERY_SERVER_PROFILE_REQUIRED"),
    ("CWA imagery processing is disabled on ARM and Raspberry Pi hosts", "CWA_IMAGERY_HOST_UNSUPPORTED"),
    ("CWA imagery processing is disabled on actual Raspberry Pi hosts", "CWA_IMAGERY_HOST_UNSUPPORTED"),
    ("explicit network approval is required for the CWA imagery server job", "CWA_IMAGERY_EXPLICIT_NETWORK_REQUIRED"),
    ("a CWA imagery server job is already running", "CWA_IMAGERY_JOB_BUSY"),
    ("CWA imagery server job rate limit is active", "CWA_IMAGERY_JOB_RATE_LIMITED"),
])
def test_known_guard_diagnostics_are_fixed_codes(message, code):
    result = preparation._safe_cwa_imagery_exception_summary(RuntimeError(message))
    assert result == {"error_type": "RuntimeError", "http_status": None,
                      "error_code": code, "reason": code, "secret_value_embedded": False}


@pytest.mark.parametrize("error", [
    RuntimeError("fixture-secret-value https://example.invalid/?token=fixture-secret-value"),
    RuntimeError({"credential": "fixture-secret-value"}),
    HTTPError("https://example.invalid/?token=fixture-secret-value", 503,
              "fixture-secret-value", {}, None),
])
def test_unrecognized_exception_text_is_never_persisted(error):
    result = preparation._safe_cwa_imagery_exception_summary(error)
    assert result["error_code"] == result["reason"] == "CWA_IMAGERY_PREPARATION_FAILED"
    assert "fixture-secret-value" not in json.dumps(result)
    assert "example.invalid" not in json.dumps(result)
    assert result["http_status"] == (503 if isinstance(error, HTTPError) else None)


def test_connected_preparation_attestation_and_request_remain_unchanged(tmp_path, monkeypatch):
    environ = {}
    loads = []
    def mocked_environment_loader(**kwargs):
        loads.append(kwargs)
        return ScoutEnvLoadResult(loaded_files=(), loaded_keys=())
    monkeypatch.setattr(connected, "load_scout_env_files", mocked_environment_loader)
    manager = connected.DashboardConnectedPreparationManager(
        workspace_root=tmp_path / "workspaces", repo_root=tmp_path / "repo", environ=environ,
    )
    root = tmp_path / "workspaces/route"
    manager._prepare_environment(root)
    assert len(loads) == 1 and loads[0]["environ"] is environ
    assert environ[CAPABILITY] == "1"
    assert (root / "cache/cwa-weather-imagery").is_dir()
    request = manager._build_request("route", prepared_at=manager._now())
    assert request.profile == "mac-workstation"
    assert request.network_mode == "explicit-fetch" and request.allow_network_fetch
    assert request.prepare_cwa_imagery is True
    assert request.run_post_layer_enrichments is request.publish_preparation_outputs is False
    assert not manager._timers
