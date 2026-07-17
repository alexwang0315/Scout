#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Scout Emergency Mobile Closed-Loop Sandbox v0 through the "
            "local Scout admin API"
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9099")
    parser.add_argument(
        "--scenario-id",
        default="sandbox-ridge-distress-v0",
    )
    parser.add_argument("--project-id", default="chilai_nanhua_day1_scoutAI")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--complete-loop",
        action="store_true",
        help="Record agree_send approval and a simulated verified receipt.",
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    _require_loopback_base_url(base_url)
    run_id = args.run_id or _default_run_id()
    living_path = "/admin/dashboard/living"
    steps: list[dict[str, Any]] = []

    try:
        projection = _post_json(
            base_url,
            f"{living_path}/scenarios/run",
            {
                "scenario_id": args.scenario_id,
                "run_id": run_id,
                "project_id": args.project_id,
                "source_mode": "synthetic_replay",
                "profile": "ridge_distress",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "confirm_sandbox_run": True,
            },
        )
        steps.append(_step_summary("scenario", projection))

        if args.complete_loop:
            packet = projection.get("alert_packet") or {}
            projection = _post_json(
                base_url,
                f"{living_path}/approvals",
                {
                    "scenario_id": args.scenario_id,
                    "packet_id": packet.get("packet_id"),
                    "packet_sha256": packet.get("sha256"),
                    "decision": "agree_send",
                    "idempotency_key": f"cli-approve-{run_id}",
                    "confirm_sandbox_action": True,
                },
            )
            steps.append(_step_summary("approval", projection))
            approval = projection.get("approval") or {}
            projection = _post_json(
                base_url,
                f"{living_path}/transport/receipts",
                {
                    "scenario_id": args.scenario_id,
                    "approval_id": approval.get("approval_id"),
                    "outcome": "simulated_verified",
                    "idempotency_key": f"cli-receipt-{run_id}",
                    "confirm_simulated_transport": True,
                },
            )
            steps.append(_step_summary("receipt", projection))

        final_projection = _get_json(base_url, living_path)
    except (HTTPError, URLError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": _safe_error(exc),
                    "base_url": base_url,
                    "production_send_performed": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    result = {
        "artifact_kind": "scout_emergency_mobile_closed_loop_cli_result",
        "artifact_version": "emergency_mobile_closed_loop_cli_result.v0",
        "status": "completed",
        "base_url": base_url,
        "scenario_id": args.scenario_id,
        "run_id": run_id,
        "complete_loop": bool(args.complete_loop),
        "steps": steps,
        "final_projection": final_projection,
        "boundary": {
            "loopback_http_only": True,
            "external_network_calls_made": False,
            "runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "real_outbound_send_performed": False,
            "hardware_control_invoked": False,
        },
    }
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _require_loopback_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base URL must use http or https")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "sandbox runner is loopback-only; remote Scout targets are not allowed in v0"
        )


def _post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    return _request_json(request)


def _get_json(base_url: str, path: str) -> dict[str, Any]:
    return _request_json(
        Request(
            f"{base_url}{path}",
            headers={"Accept": "application/json"},
            method="GET",
        )
    )


def _request_json(request: Request) -> dict[str, Any]:
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _step_summary(step: str, projection: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": step,
        "status": projection.get("status"),
        "revision": projection.get("revision"),
        "timeline_event_count": len(projection.get("timeline") or []),
        "production_send_performed": bool(
            (projection.get("boundary") or {}).get(
                "real_outbound_send_performed", False
            )
        ),
    }


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("cli-run-%Y%m%dT%H%M%SZ")


def _safe_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = None
        return f"HTTP {error.code}: {detail or error.reason}"
    return str(error)


if __name__ == "__main__":
    raise SystemExit(main())
