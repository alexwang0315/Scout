#!/usr/bin/env python3
"""Install the separate loopback API without changing the hardware sampler."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys


JOB = "scout-hardware-monitor-api"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-only", type=Path)
    args = parser.parse_args()
    if not all(importlib.util.find_spec(name) for name in ("fastapi", "uvicorn", "pydantic")):
        parser.error("Use the existing Scout venv Python with FastAPI, Uvicorn and Pydantic installed")
    account = Path.home()
    installed = account / ".local/lib/scout-hardware-monitor/api.py"
    directory = args.render_only or account / ".config/systemd/user"
    unit = directory / (JOB + ".service")
    if unit.exists() or unit.is_symlink() or (not args.render_only and installed.exists()):
        parser.error("API installation already exists; inspect it before replacing anything")
    assets = installed.parent / "static"
    command = [sys.executable, str(installed), "--static-dir", str(assets)]
    def quote(value: str) -> str:
        return json.dumps(value.replace("%", "%%").replace("$", "$$"))
    text = ("[Unit]\nDescription=Scout hardware monitor read-only loopback API\n"
            "Wants=scout-hardware-monitor.service scout-hardware-monitor.timer\n"
            "After=scout-hardware-monitor.service\n\n"
            "[Service]\nType=simple\nUMask=0077\nNoNewPrivileges=true\n"
            "Environment=PYTHONDONTWRITEBYTECODE=1\nRestart=on-failure\nRestartSec=5\n"
            "ExecStart=" + " ".join(quote(arg) for arg in command) + "\n\n"
            "[Install]\nWantedBy=default.target\n")
    directory.mkdir(parents=True, exist_ok=True)
    if not args.render_only:
        installed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "scout_hardware_monitor_api.py", installed)
        installed.chmod(0o600)
        shutil.copytree(Path(__file__).resolve().parents[1] / "docs/admin/hardware-monitor", assets)
    unit.write_text(text)
    unit.chmod(0o600)
    if not args.render_only:
        for action in (["daemon-reload"], ["enable", "--now", JOB + ".service"]):
            subprocess.run(["systemctl", "--user", *action], check=True)
    print(json.dumps({"status": "rendered" if args.render_only else "installed",
                      "unit": str(unit), "base_url": "http://127.0.0.1:9151", "read_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
