from __future__ import annotations

import argparse
import json
from typing import Any


DEFAULT_HARDWARE_HOST = "scout.local"
DEFAULT_HOST_PORT = 9110
DEFAULT_PROJECT_ID = "chilai_nanhua_day1"
DEFAULT_ADMIN_BASIC_USERNAME = "scout-admin"
DEFAULT_ADMIN_TOKEN_FILE = "/data/scout/admin/secrets/phase4-admin-token"
DEFAULT_IMAGERY_LAYER_ID = "imagery"
DEFAULT_TILE_Z = 5
DEFAULT_TILE_X = 26
DEFAULT_TILE_Y = 13


def build_phase4_hardware_tile_workspace_smoke_plan(
    *,
    hardware_host: str = DEFAULT_HARDWARE_HOST,
    host_port: int = DEFAULT_HOST_PORT,
    project_id: str = DEFAULT_PROJECT_ID,
    admin_basic_username: str = DEFAULT_ADMIN_BASIC_USERNAME,
    admin_token_file: str = DEFAULT_ADMIN_TOKEN_FILE,
    imagery_layer_id: str | None = DEFAULT_IMAGERY_LAYER_ID,
    tile_z: int = DEFAULT_TILE_Z,
    tile_x: int = DEFAULT_TILE_X,
    tile_y: int = DEFAULT_TILE_Y,
) -> dict[str, Any]:
    base_url = f"http://{hardware_host}:{int(host_port)}"
    osm_path = f"/admin/tiles/osm/{int(tile_z)}/{int(tile_x)}/{int(tile_y)}.png"
    imagery_path = (
        f"/admin/tiles/imagery/{project_id}/{imagery_layer_id}/"
        f"{int(tile_z)}/{int(tile_x)}/{int(tile_y)}.png"
        if imagery_layer_id
        else None
    )
    workspace_path = f"/admin/pretrip/projects/{project_id}/workspace"
    review_decision_path = f"/admin/pretrip/projects/{project_id}/review-decisions"

    endpoints = {
        "local_osm_tile": {
            "method": "GET",
            "path": osm_path,
            "url": f"{base_url}{osm_path}",
            "required": True,
            "auth_required": True,
            "expected_sources": ["local_cache", "offline_fallback"],
            "live_network_allowed": False,
        },
        "local_imagery_tile": {
            "method": "GET",
            "path": imagery_path,
            "url": f"{base_url}{imagery_path}" if imagery_path else None,
            "required": imagery_layer_id is not None,
            "auth_required": imagery_layer_id is not None,
            "expected_sources": ["local_cache", "transparent_fallback"],
            "live_network_allowed": False,
        },
        "workspace_post": {
            "method": "POST",
            "path": workspace_path,
            "url": f"{base_url}{workspace_path}",
            "required": True,
            "auth_required": True,
            "expected_artifact_kind": "pretrip_workspace_copy",
            "expected_mutation_scope": "local_pretrip_workspace_only",
            "live_network_allowed": False,
        },
        "review_decision_preview": {
            "method": "POST",
            "path": review_decision_path,
            "url": f"{base_url}{review_decision_path}",
            "required": True,
            "auth_required": True,
            "request_preview_fields": {
                "decision": "accepted",
                "candidate_ref": "contour.g11.seg_004_006",
                "persist_to_workspace": False,
            },
            "expected_artifact_kind": "pretrip_review_decision_preview",
            "expected_mutation_scope": "none",
            "live_network_allowed": False,
        },
    }

    return {
        "artifact_kind": "phase4_hardware_tile_workspace_smoke_plan",
        "status": "plan_only_ready",
        "execution_mode": "plan_only",
        "hardware_host": hardware_host,
        "host_port": int(host_port),
        "project_id": project_id,
        "admin_auth": {
            "required": True,
            "supported_schemes": ["basic", "bearer"],
            "basic_username": admin_basic_username,
            "token_file_on_hardware": admin_token_file,
            "token_value_embedded": False,
            "token_value_printed_by_plan": False,
        },
        "tile_sample": {
            "z": int(tile_z),
            "x": int(tile_x),
            "y": int(tile_y),
        },
        "endpoints": endpoints,
        "operator_sequence": [
            "Load the admin token from the hardware secret file or an operator-provided local secret",
            "GET local_osm_tile",
            "GET local_imagery_tile when imagery cache is configured",
            "POST workspace_post against the deployed admin preview",
            "POST review_decision_preview with persist_to_workspace=false",
        ],
        "default_behavior": {
            "makes_live_network_calls": False,
            "calls_scout_local": False,
            "writes_repo_fixtures": False,
            "mutates_phase1_runtime": False,
            "writes_phase2_brain": False,
        },
        "forbidden_mutations": {
            "repo_fixture_write_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "safety_api_mutation_allowed": False,
            "external_tile_download_allowed": False,
        },
        "allowed_mutations_when_operator_runs_against_deployed_admin": {
            "local_pretrip_workspace_write_allowed": True,
            "workspace_route": workspace_path,
            "review_decision_preview_writes_workspace": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Print a plan-only Scout Phase 4 tile/workspace smoke contract. "
            "The CLI does not call scout.local or any external tile service."
        )
    )
    parser.add_argument("--hardware-host", default=DEFAULT_HARDWARE_HOST)
    parser.add_argument("--host-port", type=int, default=DEFAULT_HOST_PORT)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--admin-basic-username", default=DEFAULT_ADMIN_BASIC_USERNAME)
    parser.add_argument("--admin-token-file", default=DEFAULT_ADMIN_TOKEN_FILE)
    parser.add_argument("--imagery-layer-id", default=DEFAULT_IMAGERY_LAYER_ID)
    parser.add_argument("--tile-z", type=int, default=DEFAULT_TILE_Z)
    parser.add_argument("--tile-x", type=int, default=DEFAULT_TILE_X)
    parser.add_argument("--tile-y", type=int, default=DEFAULT_TILE_Y)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = build_phase4_hardware_tile_workspace_smoke_plan(
        hardware_host=args.hardware_host,
        host_port=args.host_port,
        project_id=args.project_id,
        admin_basic_username=args.admin_basic_username,
        admin_token_file=args.admin_token_file,
        imagery_layer_id=args.imagery_layer_id,
        tile_z=args.tile_z,
        tile_x=args.tile_x,
        tile_y=args.tile_y,
    )
    print(json.dumps(plan, ensure_ascii=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
