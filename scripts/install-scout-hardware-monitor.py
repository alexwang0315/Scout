#!/usr/bin/env python3
"""Install the authorized per-user, one-minute Scout hardware monitor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


JOB = "scout-hardware-monitor"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notify-mac", action="store_true")
    parser.add_argument("--render-only", type=Path)
    args = parser.parse_args()
    account = Path.home()
    installed = account / ".local/lib" / JOB / "monitor.py"
    state = account / ".local/state" / JOB
    directory = args.render_only or account / ".config/systemd/user"
    command = ["/usr/bin/python3", str(installed), "--state-dir", str(state)]
    if args.notify_mac:
        command.append("--notify-mac")

    def quote(value: str) -> str:
        return json.dumps(value.replace("%", "%%").replace("$", "$$"))

    service = ("[Unit]\nDescription=Scout hardware status and change alerts\n\n[Service]\n"
               "Type=oneshot\nUMask=0077\nNoNewPrivileges=true\nTimeoutStartSec=45\n"
               "ExecStart=" + " ".join(quote(item) for item in command) + "\n")
    timer = ("[Unit]\nDescription=Check Scout hardware every minute\n\n[Timer]\n"
             "OnCalendar=*-*-* *:*:00\nAccuracySec=1\nPersistent=true\n"
             "\n[Install]\nWantedBy=timers.target\n")
    files = {directory / (JOB + ".service"): service, directory / (JOB + ".timer"): timer}
    if any(path.exists() or path.is_symlink() for path in files) or (not args.render_only and installed.exists()):
        parser.error("Monitor already exists; inspect it before replacing anything")
    directory.mkdir(parents=True, exist_ok=True)
    if not args.render_only:
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "tools/scout_hardware_monitor.py", installed)
        installed.chmod(0o600)
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path, value in files.items():
        path.write_text(value)
        path.chmod(0o600)
    if not args.render_only:
        for action in (["daemon-reload"], ["enable", "--now", JOB + ".timer"], ["start", JOB + ".service"]):
            subprocess.run(["systemctl", "--user", *action], check=True)
    print(json.dumps({"status": "rendered" if args.render_only else "installed", "interval_seconds": 60,
                      "mac_notifications": args.notify_mac, "state": str(state), "files": [str(p) for p in files]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
