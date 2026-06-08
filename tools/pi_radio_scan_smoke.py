from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio_scan_provider import (
    append_radio_scan_jsonl,
    radio_scan_payload,
    scan_radio_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Pi Wi-Fi + BLE radio scan.")
    parser.add_argument("--wifi-interface", default="wlan0")
    parser.add_argument("--wifi-source", choices=("auto", "iw", "nmcli"), default="auto")
    parser.add_argument("--ble-controller", default="hci0")
    parser.add_argument("--ble-duration-seconds", type=float, default=10.0)
    parser.add_argument("--no-wifi", action="store_true")
    parser.add_argument("--no-ble", action="store_true")
    parser.add_argument("--output-jsonl", type=Path)
    args = parser.parse_args()

    snapshot = scan_radio_environment(
        wifi_enabled=not args.no_wifi,
        ble_enabled=not args.no_ble,
        wifi_interface=args.wifi_interface,
        wifi_prefer_iw=args.wifi_source != "nmcli",
        ble_controller=args.ble_controller,
        ble_duration_seconds=args.ble_duration_seconds,
    )
    payload = radio_scan_payload(snapshot)
    wifi_payload = payload.get("wifi")
    if args.wifi_source == "iw" and (
        not isinstance(wifi_payload, dict) or wifi_payload.get("source") != "pi_wifi_scan.iw"
    ):
        raise SystemExit("iw Wi-Fi scan was requested but iw data was not available")
    if args.output_jsonl is not None:
        append_radio_scan_jsonl(snapshot, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
