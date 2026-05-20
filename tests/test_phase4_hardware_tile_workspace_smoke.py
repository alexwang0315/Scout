from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import phase4_hardware_tile_workspace_smoke
from phase4_hardware_tile_workspace_smoke import (
    build_phase4_hardware_tile_workspace_smoke_plan,
)


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_plan_defines_deployed_admin_preview_endpoints() -> None:
    plan = build_phase4_hardware_tile_workspace_smoke_plan(
        hardware_host="scout.local",
        host_port=9110,
        project_id="chilai_nanhua_day1",
    )

    assert plan["artifact_kind"] == "phase4_hardware_tile_workspace_smoke_plan"
    assert plan["status"] == "plan_only_ready"
    assert plan["execution_mode"] == "plan_only"
    assert plan["default_behavior"]["makes_live_network_calls"] is False
    assert plan["default_behavior"]["calls_scout_local"] is False
    assert plan["admin_auth"] == {
        "required": True,
        "supported_schemes": ["basic", "bearer"],
        "basic_username": "scout-admin",
        "token_file_on_hardware": "/data/scout/admin/secrets/phase4-admin-token",
        "token_value_embedded": False,
        "token_value_printed_by_plan": False,
    }

    endpoints = plan["endpoints"]
    assert endpoints["local_osm_tile"]["method"] == "GET"
    assert endpoints["local_osm_tile"]["path"] == "/admin/tiles/osm/5/26/13.png"
    assert endpoints["local_osm_tile"]["url"] == (
        "http://scout.local:9110/admin/tiles/osm/5/26/13.png"
    )
    assert endpoints["local_osm_tile"]["auth_required"] is True
    assert endpoints["local_osm_tile"]["live_network_allowed"] is False

    assert endpoints["local_imagery_tile"]["method"] == "GET"
    assert endpoints["local_imagery_tile"]["path"] == (
        "/admin/tiles/imagery/chilai_nanhua_day1/imagery/5/26/13.png"
    )
    assert endpoints["local_imagery_tile"]["expected_sources"] == [
        "local_cache",
        "transparent_fallback",
    ]
    assert endpoints["local_imagery_tile"]["auth_required"] is True

    assert endpoints["workspace_post"]["method"] == "POST"
    assert endpoints["workspace_post"]["path"] == (
        "/admin/pretrip/projects/chilai_nanhua_day1/workspace"
    )
    assert endpoints["workspace_post"]["expected_mutation_scope"] == (
        "local_pretrip_workspace_only"
    )
    assert endpoints["workspace_post"]["auth_required"] is True

    assert endpoints["review_decision_preview"]["method"] == "POST"
    assert endpoints["review_decision_preview"]["path"] == (
        "/admin/pretrip/projects/chilai_nanhua_day1/review-decisions"
    )
    assert endpoints["review_decision_preview"]["request_preview_fields"][
        "persist_to_workspace"
    ] is False
    assert endpoints["review_decision_preview"]["expected_mutation_scope"] == "none"
    assert endpoints["review_decision_preview"]["auth_required"] is True


def test_smoke_plan_records_forbidden_mutation_boundaries() -> None:
    plan = build_phase4_hardware_tile_workspace_smoke_plan()

    assert plan["forbidden_mutations"] == {
        "repo_fixture_write_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "safety_api_mutation_allowed": False,
        "external_tile_download_allowed": False,
    }
    assert plan["default_behavior"]["writes_repo_fixtures"] is False
    assert plan["default_behavior"]["mutates_phase1_runtime"] is False
    assert plan["default_behavior"]["writes_phase2_brain"] is False
    assert plan["allowed_mutations_when_operator_runs_against_deployed_admin"][
        "local_pretrip_workspace_write_allowed"
    ] is True
    assert plan["allowed_mutations_when_operator_runs_against_deployed_admin"][
        "review_decision_preview_writes_workspace"
    ] is False


def test_smoke_cli_outputs_ascii_json_without_calling_scout_local() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "phase4_hardware_tile_workspace_smoke.py"),
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
    completed.stdout.encode("ascii")
    payload = json.loads(completed.stdout)
    assert payload["default_behavior"]["calls_scout_local"] is False
    assert payload["admin_auth"]["required"] is True
    assert payload["admin_auth"]["token_value_embedded"] is False
    assert payload["endpoints"]["workspace_post"]["url"] == (
        "http://scout.local:9110/admin/pretrip/projects/"
        "chilai_nanhua_day1/workspace"
    )


def test_smoke_module_has_no_network_client_or_runtime_write_coupling() -> None:
    source = inspect.getsource(phase4_hardware_tile_workspace_smoke)

    forbidden_fragments = [
        "import requests",
        "import httpx",
        "urllib.request",
        "import socket",
        "FastAPI",
        "TestClient",
        "phase1_runtime.",
        "phase2_brain.",
        ".open(",
        ".write_text(",
        ".write_bytes(",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in source
