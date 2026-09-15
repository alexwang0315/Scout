"""Regressions for host GDAL lookup during unrelated Admin/Permission operations."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import admin_api
from scout_terrain_route_hypothesis_tool import TerrainRouteToolUnavailable
from tests.test_terrain_route_guidance_workspace import (
    NARRATIVE,
    ROUTE_START,
    ROUTE_DESTINATION,
    _FakeElevationSampler,
    _MapReviewSampler,
    _file_snapshot,
    _map_review_workspace,
    _workspace,
)

BASE = "/admin/pretrip/projects/guidance_demo/terrain-route-guidance"


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_api, "load_scout_env_files", lambda **kwargs: None)
    monkeypatch.setenv("SCOUT_PERSISTENT_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "isolated-data"))


def _client(tmp_path, **kwargs):
    return TestClient(admin_api.create_admin_app(
        pretrip_workspace_root=tmp_path,
        runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
        alpha_sandbox_enabled=False,
        **kwargs,
    ))


def _interpret(client):
    response = client.post(BASE + "/interpret", json={
        "narrative": NARRATIVE,
        "source_id": "sampler-lifecycle-fixture",
        "requested_by": "test_operator",
    })
    assert response.status_code == 201, response.text
    return response.json()["guidance_plan"]


def _resolve(client, plan):
    return client.post(BASE + "/resolve", json={
        "guidance_id": plan["guidance_id"],
        "route_start": ROUTE_START.model_dump(mode="json"),
        "route_destination": ROUTE_DESTINATION.model_dump(mode="json"),
        "search_margin_m": 200,
    })


def test_router_and_non_sampling_guidance_operations_do_not_probe_host_tools(tmp_path, monkeypatch):
    _workspace(tmp_path)

    def unexpected_discovery():
        raise AssertionError("Unrelated registration/read/interpret probed host GDAL")

    monkeypatch.setattr(admin_api.GdalLocationInfoSampler, "discover", unexpected_discovery)
    with _client(tmp_path) as client:
        assert client.get("/admin/dashboard").status_code == 200
        assert client.get(BASE).status_code == 200
        plan = _interpret(client)
        state = client.get(BASE)
        assert state.status_code == 200
        assert state.json()["guidance_plan"]["guidance_id"] == plan["guidance_id"]


@pytest.mark.parametrize("available", [False, True])
def test_auto_sampler_is_discovered_on_resolve_with_existing_available_unavailable_results(
    tmp_path, monkeypatch, available,
):
    _workspace(tmp_path)
    calls = []

    def discover():
        calls.append("discover")
        if available:
            return _FakeElevationSampler()
        raise TerrainRouteToolUnavailable("gdal_unavailable", "No fixture GDAL executable")

    monkeypatch.setattr(admin_api.GdalLocationInfoSampler, "discover", discover)
    with _client(tmp_path) as client:
        assert calls == []
        plan = _interpret(client)
        assert calls == []
        response = _resolve(client, plan)
        assert response.status_code == 200, response.text
        feature_index = response.json()["feature_index"]
        assert calls == ["discover"]
        assert feature_index["elevation_sampling_status"] == ("completed" if available else "unavailable")
        if available:
            assert feature_index["elevation_sampling_backend"] == _FakeElevationSampler.backend_id
            assert feature_index["elevation_sample_count"] > 0
            assert feature_index["derived_saddle_count"] > 0
        else:
            assert feature_index["elevation_sampling_backend"] is None
            assert feature_index["elevation_sample_count"] == 0
        assert response.headers["x-scout-candidate-only"] == "true"


@pytest.mark.parametrize("explicit", [None, _FakeElevationSampler()])
def test_explicit_sampler_and_explicit_disable_never_autodiscover(tmp_path, monkeypatch, explicit):
    _workspace(tmp_path)

    def unexpected_discovery():
        raise AssertionError("Explicit sampler/None was replaced by auto discovery")

    monkeypatch.setattr(admin_api.GdalLocationInfoSampler, "discover", unexpected_discovery)
    with _client(tmp_path, terrain_guidance_elevation_sampler=explicit) as client:
        response = _resolve(client, _interpret(client))
        assert response.status_code == 200, response.text
        assert response.json()["feature_index"]["elevation_sampling_status"] == (
            "unavailable" if explicit is None else "completed"
        )


@pytest.mark.parametrize("available", [False, True])
def test_auto_map_review_scope_preserves_read_only_success_and_unavailable_contract(
    tmp_path, monkeypatch, available,
):
    root = _map_review_workspace(tmp_path, manual=True)
    calls = []

    def discover():
        calls.append("discover")
        if available:
            return _MapReviewSampler()
        raise TerrainRouteToolUnavailable("gdal_unavailable", "No fixture GDAL executable")

    monkeypatch.setattr(admin_api.GdalLocationInfoSampler, "discover", discover)
    with _client(tmp_path) as client:
        state = client.get(BASE)
        assert state.status_code == 200
        assert calls == []
        before = _file_snapshot(root)
        response = client.get(BASE + "/map-review-scope", params={
            "reference_hypothesis_id": "active-cccccccccccc",
            "corridor_band_name": "top_5_percent_corridor",
        })
        assert response.status_code == (200 if available else 409), response.text
        assert calls == ["discover"]
        payload = response.json()
        assert payload["runtime_safety_truth"] is False
        if available:
            assert payload["status"] == "ready"
            assert payload["execution_eligible"] is False
            assert payload["routing_effect"] == "none"
        else:
            assert payload["status"] == "unavailable"
            assert payload["constraints"] == []
        assert _file_snapshot(root) == before


def test_gdal_permission_error_is_not_swallowed_during_requested_sampling(tmp_path, monkeypatch):
    _workspace(tmp_path)
    calls = []

    def blocked_discovery():
        calls.append("discover")
        raise PermissionError("host GDAL lookup denied by caller boundary")

    monkeypatch.setattr(admin_api.GdalLocationInfoSampler, "discover", blocked_discovery)
    with _client(tmp_path) as client:
        plan = _interpret(client)
        assert calls == []
        response = _resolve(client, plan)
        assert response.status_code == 409, response.text
        assert "host GDAL lookup denied" in response.text
        assert calls == ["discover"]
