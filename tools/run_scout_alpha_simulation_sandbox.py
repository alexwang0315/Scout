from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout_alpha_simulation_sandbox import (  # noqa: E402
    AlphaSandboxRunRequest,
    AlphaSandboxStore,
    SandboxFaultInjection,
    SandboxPlaybackConfig,
    alpha_scenario_catalog,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local-only Scout Alpha phone/wearable GPX simulation sandbox."
        )
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--gpx-ref")
    parser.add_argument(
        "--profile",
        default="nominal_gpx",
        choices=[item.profile for item in alpha_scenario_catalog()],
    )
    parser.add_argument(
        "--ingress-mode",
        choices=("loopback_mqtt_broker", "synthetic_direct_feed"),
        default="loopback_mqtt_broker",
    )
    parser.add_argument("--run-id")
    parser.add_argument("--scenario-id")
    parser.add_argument("--output-root")
    parser.add_argument("--virtual-start-at", default="2026-07-20T08:00:00Z")
    parser.add_argument("--speed-multiplier", type=float, default=600.0)
    parser.add_argument("--max-frames", type=int, default=48)
    parser.add_argument("--faults-json")
    parser.add_argument("--scenario-matrix", action="store_true")
    parser.add_argument(
        "--simulate-approval-receipt",
        action="store_true",
        help=(
            "For alerting candidates, record a local agree_send action and a "
            "correlated simulated receipt. No production transport is invoked."
        ),
    )
    parser.add_argument("--result-output")
    parser.add_argument("--confirm-sandbox-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not args.confirm_sandbox_run:
        raise SystemExit("--confirm-sandbox-run is required")
    workspace = Path(args.workspace).expanduser().resolve()
    project = _read_json(workspace / "project.json")
    project_id = args.project_id or project.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise SystemExit("workspace project.json does not provide project_id")
    output_root = (
        Path(args.output_root).expanduser().resolve()
        if args.output_root
        else workspace / "outputs" / "sandbox" / "alpha"
    )
    faults = _faults(args.faults_json)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    profiles = (
        [item.profile for item in alpha_scenario_catalog()]
        if args.scenario_matrix
        else [args.profile]
    )
    results = []
    for index, profile in enumerate(profiles, start=1):
        run_id = (
            f"{args.run_id}-{profile}"
            if args.run_id and len(profiles) > 1
            else args.run_id or f"alpha-{profile}-{run_stamp}-{index:02d}"
        )
        scenario_id = (
            f"{args.scenario_id}-{profile}"
            if args.scenario_id and len(profiles) > 1
            else args.scenario_id or f"alpha-{profile}"
        )
        store = AlphaSandboxStore(output_root)
        projection = store.run_to_completion(
            AlphaSandboxRunRequest(
                scenario_id=scenario_id,
                run_id=run_id,
                project_id=project_id,
                workspace_root=str(workspace),
                gpx_ref=args.gpx_ref,
                scenario_profile=profile,
                ingress_mode=args.ingress_mode,
                playback=SandboxPlaybackConfig(
                    virtual_start_at=args.virtual_start_at,
                    speed_multiplier=args.speed_multiplier,
                    max_frames=args.max_frames,
                ),
                faults=faults,
                confirm_sandbox_run=True,
            )
        )
        if args.simulate_approval_receipt and projection.alert_candidate is not None:
            packet = projection.alert_candidate
            projection = store.record_approval(
                {
                    "scenario_id": projection.scenario.scenario_id,
                    "packet_id": packet.packet_id,
                    "packet_sha256": packet.sha256,
                    "decision": "agree_send",
                    "idempotency_key": f"cli-approval-{profile}",
                    "confirm_sandbox_action": True,
                }
            )
            attempt = projection.transport_attempt
            if attempt is None:
                raise RuntimeError("sandbox approval did not create a local attempt")
            projection = store.record_transport_simulation(
                {
                    "scenario_id": projection.scenario.scenario_id,
                    "attempt_id": attempt.attempt_id,
                    "attempt_sha256": attempt.sha256,
                    "packet_id": packet.packet_id,
                    "packet_sha256": packet.sha256,
                    "outcome": "simulated_receipt_recorded",
                    "idempotency_key": f"cli-receipt-{profile}",
                    "confirm_simulated_transport": True,
                }
            )
        results.append(_result_summary(projection, output_root=output_root))
    payload = {
        "artifact_kind": "scout_alpha_mobile_wearable_sandbox_cli_result",
        "schema_version": "scout.alpha.mobile_wearable_sandbox.cli_result.v0.1",
        "status": "success",
        "summary": f"Completed {len(results)} Alpha sandbox replay run(s).",
        "next_actions": ["inspect Living projection and replay evidence"],
        "project_id": project_id,
        "workspace_ref": workspace.name,
        "output_root": str(output_root),
        "scenario_count": len(results),
        "results": results,
        "verification": {
            "all_completed": all(item["status"] == "completed" for item in results),
            "all_broker_connections_verified": all(
                item["broker_connection_verified"] for item in results
            ),
            "all_candidate_only": all(item["candidate_only"] for item in results),
            "all_runtime_safety_truth_false": all(
                not item["runtime_safety_truth"] for item in results
            ),
            "all_phase1_mutation_false": all(
                not item["phase1_l0_l4_state_mutated"] for item in results
            ),
            "all_production_delivery_unverified": all(
                not item["production_delivery_verified"] for item in results
            ),
            "source_point_counts": sorted(
                {item["source_point_count"] for item in results}
            ),
            "gpx_sha256_values": sorted({item["gpx_sha256"] for item in results}),
            "alert_candidate_count": sum(
                bool(item["alert_candidate_created"]) for item in results
            ),
            "simulated_receipt_count": sum(
                bool(item["simulated_receipt_recorded"]) for item in results
            ),
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "external_network_calls_made": False,
            "real_outbound_send_performed": False,
            "hardware_control_invoked": False,
            "loopback_network_only": True,
        },
    }
    result_path = (
        Path(args.result_output).expanduser().resolve()
        if args.result_output
        else output_root / "last_cli_result.json"
    )
    _write_json(result_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _faults(path_text: str | None) -> list[SandboxFaultInjection]:
    if not path_text:
        return []
    payload = _read_json(Path(path_text).expanduser().resolve())
    items = payload.get("faults") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise SystemExit("faults JSON must be a list or an object with faults[]")
    return [SandboxFaultInjection.model_validate(item) for item in items]


def _result_summary(projection: Any, *, output_root: Path) -> dict[str, Any]:
    return {
        "scenario_id": projection.scenario.scenario_id,
        "run_id": projection.scenario.run_id,
        "profile": projection.scenario.profile,
        "status": projection.status,
        "frame_count": projection.playback.total_frames,
        "source_point_count": projection.playback.total_source_points,
        "gpx_ref": projection.scenario.gpx_ref,
        "gpx_sha256": projection.source_hashes["gpx_sha256"],
        "accepted_message_count": projection.ingress.accepted_message_count,
        "dropped_message_count": projection.ingress.dropped_message_count,
        "broker_connection_verified": projection.ingress.broker_connection_verified,
        "selected_gate_id": projection.safety.selected_gate_id,
        "ln_level_candidate": projection.safety.ln_level_candidate,
        "fault_kinds": projection.fault_summary.applied_by_kind,
        "alert_candidate_created": projection.alert_candidate is not None,
        "approval_recorded": projection.approval is not None,
        "simulated_transport_attempted": projection.transport_attempt is not None,
        "simulated_receipt_recorded": projection.transport_receipt is not None,
        "production_delivery_verified": (
            projection.transport_receipt.production_delivery_verified
            if projection.transport_receipt is not None
            else False
        ),
        "run_dir": str(output_root / "runs" / projection.scenario.run_id),
        "candidate_only": projection.boundary.candidate_only,
        "runtime_safety_truth": projection.boundary.runtime_safety_truth,
        "phase1_l0_l4_state_mutated": (
            projection.boundary.phase1_l0_l4_state_mutated
        ),
        "safety_api_called": projection.boundary.safety_api_called,
        "real_outbound_send_performed": (
            projection.boundary.real_outbound_send_performed
        ),
        "local_loopback_mqtt_publish_performed": (
            projection.boundary.local_loopback_mqtt_publish_performed
        ),
    }


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"required JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
