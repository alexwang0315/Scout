from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from phase4_admin_runtime import create_phase4_admin_runtime_app
from phase4_hardware_admin_preview import prepare_phase4_hardware_admin_preview


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase4_admin_runtime_serves_pretrip_and_mock_assistant_on_lan_profile() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_DATA_ROOT": "/data/scout",
            "SCOUT_PRETRIP_WORKSPACE_ROOT": "/data/scout/admin/pretrip-workspaces",
            "SCOUT_SAFETY_INCIDENT_STORE": "/data/scout/incidents",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
            "SCOUT_WEATHER_API_ENABLED": "false",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    health_payload = health.json()
    assert health_payload["status"] == "ok"
    assert health_payload["runtime_profile"] == "pi-phase4-admin-preview"
    assert health_payload["boundaries"]["phase1_field_runtime_started"] is False
    assert health_payload["boundaries"]["safety_api_mutation_allowed"] is False
    assert health_payload["boundaries"]["local_pretrip_workspace_write_allowed"] is True
    assert health_payload["auth"]["required"] is False
    assert health_payload["auth"]["token_value_exposed"] is False

    pretrip = client.get("/admin/pretrip")
    assert pretrip.status_code == 200
    assert 'id="map"' in pretrip.text
    assert "/admin/pretrip/projects/${PROJECT_ID}" in pretrip.text

    status = client.get("/assistant/status")
    assert status.status_code == 200
    assert status.json()["provider"] == "mock"
    assert status.json()["token_values_exposed"] is False


def test_phase4_admin_runtime_can_require_basic_or_bearer_auth() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_ADMIN_BASIC_USERNAME": "scout-admin",
            "SCOUT_ADMIN_ACCESS_TOKEN": "test-token",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["auth"]["required"] is True
    assert health.json()["auth"]["token_configured"] is True
    assert health.json()["auth"]["token_value_exposed"] is False
    assert "test-token" not in json.dumps(health.json())

    unauthenticated = client.get("/admin/pretrip")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"].startswith("Basic ")

    bearer = client.get(
        "/admin/pretrip",
        headers={"Authorization": "Bearer test-token"},
    )
    assert bearer.status_code == 200

    basic = client.get(
        "/assistant/status",
        auth=("scout-admin", "test-token"),
    )
    assert basic.status_code == 200
    assert basic.json()["provider"] == "mock"


def test_phase4_admin_runtime_fails_closed_when_auth_required_without_token() -> None:
    app = create_phase4_admin_runtime_app(
        environ={
            "SCOUT_ADMIN_AUTH_REQUIRED": "true",
            "SCOUT_AI_ASSISTANT_ENABLED": "1",
        }
    )
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["auth"]["misconfigured"] is True

    blocked = client.get("/admin/pretrip")
    assert blocked.status_code == 503
    assert blocked.json()["auth"]["misconfigured"] is True


def test_phase4_hardware_admin_preview_plan_uses_lan_url_and_separate_port() -> None:
    plan = prepare_phase4_hardware_admin_preview(
        hardware_host="scout.local",
        host_port=9110,
    )

    assert plan["artifact_kind"] == "phase4_hardware_admin_preview_plan"
    assert plan["status"] == "ready_to_deploy"
    assert plan["compose_file"] == "docker-compose.pi.admin.yml"
    assert plan["urls"]["pretrip_admin"] == "http://scout.local:9110/admin/pretrip"
    assert plan["urls"]["pretrip_admin_local_tiles"].endswith(
        "/admin/pretrip?tileSource=local"
    )
    assert plan["runtime_port_policy"]["existing_runtime_host_port"] == 9099
    assert plan["runtime_port_policy"]["admin_preview_host_port"] == 9110
    assert plan["runtime_port_policy"]["shares_existing_runtime_port"] is False
    assert plan["boundaries"]["does_not_replace_pi_runtime_service"] is True
    assert plan["boundaries"]["admin_auth_required"] is True
    assert plan["boundaries"]["admin_token_value_embedded"] is False
    assert plan["boundaries"]["phase1_runtime_mutation_allowed"] is False
    assert plan["boundaries"]["phase2_writeback_allowed"] is False
    assert plan["tile_cache"]["capacity_limit_bytes"] == 10 * 1024 * 1024 * 1024
    assert plan["network_expectations"]["open_meteo_live_weather_enabled"] is False


def test_phase4_hardware_admin_preview_cli_outputs_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "phase4_hardware_admin_preview.py"),
            "--hardware-host",
            "scout.local",
            "--host-port",
            "9110",
            "--pretty",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["urls"]["health"] == "http://scout.local:9110/health"
    assert payload["environment"]["SCOUT_SAFETY_ENABLED"] == "false"
    assert payload["environment"]["SCOUT_AI_ASSISTANT_PROVIDER"] == "mock"
    assert payload["environment"]["SCOUT_ADMIN_AUTH_REQUIRED"] == "true"
    assert "phase4-admin-token" in payload["operator_commands"]["create_token"]


def test_phase4_admin_dockerfile_runs_admin_app_not_field_runtime() -> None:
    source = read("Dockerfile.pi.admin")

    assert "ARG TARGETPLATFORM=linux/arm64" in source
    assert "FROM --platform=$TARGETPLATFORM python:3.12-slim-bookworm" in source
    assert "SCOUT_RUNTIME_PROFILE=pi-phase4-admin-preview" in source
    assert "SCOUT_SAFETY_ENABLED=false" in source
    assert "SCOUT_PRETRIP_WORKSPACE_ROOT=/data/scout/admin/pretrip-workspaces" in source
    assert "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT=/data/scout/osm-tiles" in source
    assert "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT=/data/scout/raster-tiles" in source
    assert "SCOUT_ADMIN_AUTH_REQUIRED=true" in source
    assert "SCOUT_ADMIN_ACCESS_TOKEN_FILE=/data/scout/admin/secrets/phase4-admin-token" in source
    assert "phase4_admin_runtime.py" in source
    assert "docs/admin/phase4-pretrip-planning.html" in source
    assert "tests/fixtures/pretrip/projects/chilai_nanhua_day1/" in source
    assert 'CMD ["python", "-m", "uvicorn", "phase4_admin_runtime:app"' in source
    assert "scout_pi_runtime:app" not in source
    assert "COPY *.py" not in source


def test_phase4_admin_compose_keeps_runtime_9099_free_for_existing_service() -> None:
    source = read("docker-compose.pi.admin.yml")

    assert "scout-phase4-admin:" in source
    assert "dockerfile: Dockerfile.pi.admin" in source
    assert "image: scout-fusion/pi-phase4-admin:preview" in source
    assert 'SCOUT_SAFETY_ENABLED: "false"' in source
    assert "SCOUT_PRETRIP_WORKSPACE_ROOT: /data/scout/admin/pretrip-workspaces" in source
    assert "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT: /data/scout/osm-tiles" in source
    assert "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT: /data/scout/raster-tiles" in source
    assert 'SCOUT_ADMIN_AUTH_REQUIRED: "${SCOUT_ADMIN_AUTH_REQUIRED:-true}"' in source
    assert "SCOUT_ADMIN_ACCESS_TOKEN_FILE: /data/scout/admin/secrets/phase4-admin-token" in source
    assert '- "9110:9099"' in source
    assert '- "9099:9099"' not in source
    assert "depends_on:" not in source


def test_phase4_admin_docker_context_whitelists_only_metadata_and_admin_assets() -> None:
    dockerignore = read(".dockerignore")

    assert "!Dockerfile.pi.admin" in dockerignore
    assert "!requirements.pi.admin.txt" in dockerignore
    assert "!phase4_admin_runtime.py" in dockerignore
    assert "!admin_api.py" in dockerignore
    assert "!docs/admin/phase4-pretrip-planning.html" in dockerignore
    assert "!tests/fixtures/pretrip/projects/chilai_nanhua_day1/**" in dockerignore
    assert "!*.py" not in dockerignore
    assert "!catographydata/" not in dockerignore
    assert "!PdrSample/" not in dockerignore


def test_hardware_plan_documents_phase4_admin_lan_preview_boundary() -> None:
    source = read("docs/specs/hardware-port-plan.md")

    assert "## Phase 4 Admin LAN Preview Profile" in source
    assert "`scout-phase4-admin`" in source
    assert "`http://scout.local:9110/admin/pretrip`" in source
    assert "`phase4_hardware_demo_smoke.py`" in source
    assert "`phase4_hardware_tile_workspace_smoke.py`" in source
    assert "`SCOUT_ADMIN_AUTH_REQUIRED=true`" in source
    assert "`/data/scout/admin/secrets/phase4-admin-token`" in source
    assert "admin token values are never embedded" in source
    assert "runs read-only HTTP GET checks" in source
    assert "is plan-only" in source
    assert "does not call" in source
    assert "`scout.local`" in source
    assert "no Phase 1 field runtime is started by this profile" in source
    assert "不是現場安全 runtime" in source
