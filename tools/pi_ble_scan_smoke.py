from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ble_scan_provider import scan_ble, server_signal_snapshot_from_ble_scan


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Pi BLE RSSI scan.")
    parser.add_argument("--controller", default="hci0")
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    args = parser.parse_args()

    snapshot = scan_ble(controller=args.controller, duration_seconds=args.duration_seconds)
    print(json.dumps(server_signal_snapshot_from_ble_scan(snapshot), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
