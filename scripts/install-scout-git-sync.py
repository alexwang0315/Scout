#!/usr/bin/env python3
"""Install a per-user Scout Git synchronization schedule (Linux or macOS)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


JOB = "scout-fusion-git-sync"
LABEL = "com.scout.fusion.git-sync"
BRANCH = "codex/scout-wip-transfer-20260822"
SCOUT_URLS = {
    "https://github.com/alexwang0315/Scout.git",
    "git@github.com:alexwang0315/Scout.git",
    "ssh://git@github.com/alexwang0315/Scout.git",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--branch", default=BRANCH)
    parser.add_argument("--expected-url", help="Explicit alternative to the known Scout GitHub repository")
    parser.add_argument("--minutes", type=int, default=15, choices=(5, 10, 15, 20, 30, 60))
    parser.add_argument("--render-only", type=Path, help="Generate scheduler files here without installing or activating")
    parser.add_argument("--platform", choices=("linux", "darwin"), default=sys.platform)
    args = parser.parse_args()
    if not args.render_only and args.platform != sys.platform:
        parser.error("Can only activate a schedule on the current platform")
    repo = args.repo.expanduser().resolve()

    def git(*values: str) -> str:
        result = subprocess.run(["git", "-C", str(repo), *values], capture_output=True, text=True)
        if result.returncode:
            parser.error("Cannot inspect this Git checkout; verify the repository and branch first")
        return result.stdout.strip()

    url = git("remote", "get-url", "origin")
    if url not in ({args.expected_url} if args.expected_url else SCOUT_URLS):
        parser.error("Origin is not the expected Scout repository; no files were installed")
    if git("remote", "get-url", "--all", "origin") != url or git("remote", "get-url", "--push", "--all", "origin") != url:
        parser.error("Origin has multiple or different push destinations")
    if git("branch", "--show-current") != args.branch:
        parser.error("Switch to the requested branch explicitly before installing")
    if git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") != "origin/" + args.branch:
        parser.error("Set and review the branch upstream before installing")

    account_root = Path.home()
    installed = account_root / ".local/lib/scout-git-sync/sync-project-git.py"
    state = account_root / ".local/state" / JOB
    command = [sys.executable, str(installed), "--repo", str(repo), "--branch", args.branch,
               "--expected-url", url, "--state-dir", str(state), "--notify"]
    # Preserve the installing shell's helper paths for Git credential helpers.
    path_value = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if args.platform == "darwin":
        directory = args.render_only or account_root / "Library/LaunchAgents"
        target = directory / (LABEL + ".plist")
        data = plistlib.dumps({
            "Label": LABEL, "ProgramArguments": command, "StartInterval": args.minutes * 60,
            "RunAtLoad": True, "WorkingDirectory": str(repo),
            "EnvironmentVariables": {"PATH": path_value},
            "StandardOutPath": str(state / "events.log"),
            "StandardErrorPath": str(state / "errors.log"),
        })
        files = {target: data}
    else:
        directory = args.render_only or account_root / ".config/systemd/user"

        def quote(value: str) -> str:
            return json.dumps(value.replace("%", "%%").replace("$", "$$"))

        service = ("[Unit]\nDescription=Scout committed Git synchronization\n\n[Service]\n"
                   "Type=oneshot\nUMask=0077\nEnvironment=" + quote("PATH=" + path_value) + "\n"
                   "ExecStart=" + " ".join(quote(item) for item in command) + "\n")
        calendar = "*-*-* *:00:00" if args.minutes == 60 else "*-*-* *:00/" + str(args.minutes) + ":00"
        timer = ("[Unit]\nDescription=Periodic Scout Git synchronization\n\n[Timer]\n"
                 "OnCalendar=" + calendar + "\nPersistent=true\nRandomizedDelaySec=30\n"
                 "\n[Install]\nWantedBy=timers.target\n")
        files = {directory / (JOB + ".service"): service.encode(), directory / (JOB + ".timer"): timer.encode()}
    if any(target.exists() for target in files):
        parser.error("Schedule already exists; inspect it before changing or replacing it")
    directory.mkdir(parents=True, exist_ok=True)
    if not args.render_only:
        installed.parent.mkdir(parents=True, exist_ok=True)
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(Path(__file__).with_name("sync-project-git.py"), installed)
    for target, data in files.items():
        target.write_bytes(data)
        target.chmod(0o600)
    if not args.render_only:
        if args.platform == "darwin":
            subprocess.run(["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(target)], check=True)
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", JOB + ".timer"], check=True)
            subprocess.run(["systemctl", "--user", "start", JOB + ".service"], check=True)
    print(json.dumps({"status": "rendered" if args.render_only else "installed", "minutes": args.minutes,
                      "files": [str(path) for path in files], "state": str(state / "status.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
