#!/usr/bin/env python3
"""Run a local end-to-end old-PC debug link smoke against Scout ingest."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

from scout.hardware.old_pc_debug_link import (  # noqa: E402
    OldPcDebugReceipt,
    OldPcDebugReceiptStore,
    build_old_pc_debug_watchdog_result,
    build_simulated_old_pc_report,
    create_old_pc_debug_app,
    post_old_pc_debug_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start a local Scout old-PC ingest endpoint, send one report, and verify the watchdog result."
    )
    parser.add_argument(
        "--evidence-dir",
        default=str(ROOT / "artifacts" / "old-pc-debug-link" / "mac-loopback-smoke"),
        help="Directory where Scout writes old-PC debug receipts.",
    )
    parser.add_argument(
        "--subject-ref",
        default="old-pc-candidate",
        help="Non-secret old PC candidate label.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=5.0,
        help="Watchdog and local HTTP timeout.",
    )
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    evidence_dir = Path(args.evidence_dir).expanduser()
    store = OldPcDebugReceiptStore(evidence_dir)
    app = create_old_pc_debug_app(store=store)
    host = "127.0.0.1"
    port = _free_port(host)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    ingest_url = f"http://{host}:{port}/hardware/old-pc-debug/reports"
    try:
        _wait_for_port(host, port, timeout_seconds=args.timeout_seconds)
        report = build_simulated_old_pc_report(
            subject_ref=args.subject_ref,
            transport="loopback_smoke",
        )
        receipt_payload = post_old_pc_debug_report(
            report,
            ingest_url=ingest_url,
            timeout_seconds=args.timeout_seconds,
        )
        receipt = OldPcDebugReceipt.model_validate(receipt_payload)
        watchdog = build_old_pc_debug_watchdog_result(
            receipt,
            subject_ref=args.subject_ref,
            timeout_seconds=args.timeout_seconds,
        )
        store.write_watchdog_result(watchdog)
        status = "passed" if receipt.disposition == "USABLE_HEADLESS" else "failed"
        print(
            json.dumps(
                {
                    "status": status,
                    "ingest_url": ingest_url,
                    "receipt_id": receipt.receipt_id,
                    "disposition": receipt.disposition,
                    "watchdog_status": watchdog.status,
                    "receipt_path": str(store.latest_receipt_path),
                    "watchdog_path": str(store.latest_watchdog_path),
                    "jsonl_path": str(store.receipt_jsonl_path),
                    "decision_reasons": receipt.decision_reasons,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if status == "passed" else 1
    finally:
        server.should_exit = True
        thread.join(timeout=3)


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"Scout old-PC debug ingest did not open on {host}:{port}: {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
