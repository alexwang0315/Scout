from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wifi_scan_provider import scan_wifi, server_signal_snapshot_from_wifi_scan


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Pi Wi-Fi RSSI scan.")
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--source", choices=("auto", "iw", "nmcli"), default="auto")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()

    snapshot = scan_wifi(
        interface=args.interface,
        prefer_iw=args.source != "nmcli",
        timeout_seconds=args.timeout_seconds,
    )
    if args.source == "iw" and snapshot.source != "iw":
        raise SystemExit("iw scan was requested but only nmcli data was available")
    print(json.dumps(server_signal_snapshot_from_wifi_scan(snapshot), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
