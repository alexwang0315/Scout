#!/usr/bin/env python3
"""Install/run a per-user Mac -> Scout workspace sync without Git operations or stored passwords."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys


LABEL = "com.scout.workspace-sync"
ACCOUNT = "alexwang0315"
DESTINATION = "/home/alexwang0315/workspace"
REMOTE_STATE = "/home/alexwang0315/.local/state/scout-workspace-sync"
BACKUPS = REMOTE_STATE + "/backups"


class SyncError(Exception):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_source(source: Path) -> Path:
    source = source.expanduser().resolve()
    account_root = Path.home().resolve()
    if source == account_root or source in account_root.parents or source.parent == source:
        raise SyncError("Source must be a workspace directory, not a home or filesystem root")
    if not source.is_dir():
        raise SyncError("Source workspace directory does not exist: " + str(source))
    return source


def endpoint(host: str) -> str:
    # This first slice deliberately supports a hostname/IPv4 only, not shell expressions.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise SyncError("Host must be a hostname or IPv4 address")
    return ACCOUNT + "@" + host


def binary(name: str) -> str:
    result = shutil.which(name)
    if not result:
        raise SyncError("Required command is unavailable: " + name)
    return result


def ssh_command(host: str) -> list[str]:
    return [binary("ssh"), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", endpoint(host)]


def checked(command: list[str], *, timeout: int | None = None, stdin: str | None = None):
    result = subprocess.run(command, input=stdin, capture_output=True, text=True,
                            errors="replace", timeout=timeout)
    if result.returncode:
        raise SyncError("Command failed (exit " + str(result.returncode) + "): "
                        + result.stderr.strip()[-1000:])
    return result


def remote_probe(host: str, *, prepare: bool) -> None:
    # Fixed, reviewed receiver paths; source filenames never enter a shell expression.
    command = ("test \"$(id -un)\" = " + shlex.quote(ACCOUNT)
               + " && test -d " + shlex.quote(DESTINATION)
               + " && test ! -L " + shlex.quote(DESTINATION)
               + " && test -w " + shlex.quote(DESTINATION)
               + " && command -v rsync >/dev/null && command -v python3 >/dev/null")
    if prepare:
        command += (" && test ! -L " + shlex.quote(REMOTE_STATE)
                    + " && test ! -L " + shlex.quote(BACKUPS)
                    + " && umask 077 && mkdir -p " + shlex.quote(BACKUPS)
                    + " && chmod 700 " + shlex.quote(REMOTE_STATE) + " " + shlex.quote(BACKUPS))
    checked(ssh_command(host) + [command], timeout=30)


def rsync_command(source: Path, host: str, backup_dir: str, *, dry_run: bool = False) -> list[str]:
    command = [binary("rsync"), "-rlt", "--backup", "--backup-dir=" + backup_dir,
               "--partial-dir=.scout-sync-partial", "--delay-updates", "--timeout=120",
               "--stats", "--out-format=%i", "--rsync-path=umask 077 && rsync",
               "-e", shlex.join(ssh_command(host)[:-1])]
    if dry_run:
        command.append("--dry-run")
    return command + ["--", str(source) + "/", endpoint(host) + ":" + DESTINATION + "/"]


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def receipt(host: str, value: dict) -> None:
    # A receipt on Scout lets us verify a real Mac run without logging into the Mac.
    program = ("import json,os,pathlib,sys; os.umask(0o077); "
               "p=pathlib.Path(" + repr(REMOTE_STATE + "/last-success.json") + "); "
               "v=json.load(sys.stdin); t=p.with_suffix('.tmp'); "
               "t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\\n'); "
               "t.chmod(0o600); t.replace(p)")
    checked(ssh_command(host) + ["python3 -c " + shlex.quote(program)],
            timeout=30, stdin=json.dumps(value))


def sync_once(source: Path, host: str, state: Path) -> int:
    source = source.expanduser()
    endpoint(host)
    os.umask(0o077)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    with (state / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # Another launchd/manual run still owns the transfer.
        previous = {}
        try:
            previous = json.loads((state / "status.json").read_text())
        except (OSError, ValueError):
            pass
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + str(os.getpid())
        backup_dir = BACKUPS + "/" + run_id
        status = {"status": "running", "started_at": timestamp(), "source": str(source),
                  "destination": endpoint(host) + ":" + DESTINATION,
                  "last_success_at": previous.get("last_success_at")}
        write_json(state / "status.json", status)
        code = 0
        try:
            source = validate_source(source)
            status["source"] = str(source)
            remote_probe(host, prepare=True)
            # No whole-run deadline. The rsync timeout is an idle-connection timeout.
            result = checked(rsync_command(source, host, backup_dir))
            (state / "last-rsync.log").write_text(result.stdout + result.stderr)
            changes = sum(bool(re.match(r"^[<>ch][fdL]", line)) for line in result.stdout.splitlines())
            status.update(status="synced", last_success_at=timestamp(), changed_items=changes,
                          backup_directory=backup_dir)
            try:
                receipt(host, status)
                status["scout_receipt"] = "updated"
            except (SyncError, OSError, subprocess.TimeoutExpired):
                status["scout_receipt"] = "failed"
                status["action"] = "Data copied; Scout receipt failed. Check connection on the next run."
        except (SyncError, OSError, subprocess.TimeoutExpired) as error:
            code = 1
            status.update(status="failed", error=str(error),
                          action="Check Mac status.json, network, and noninteractive SSH; next interval retries.",
                          backup_directory=backup_dir)
        status["finished_at"] = timestamp()
        write_json(state / "status.json", status)
        event_keys = ("status", "error", "scout_receipt")
        if any(previous.get(key) != status.get(key) for key in event_keys) or status.get("changed_items"):
            print(json.dumps(status, ensure_ascii=False), flush=True)
        return code


def launch_agent(source: Path, host: str, minutes: int, installed: Path, state: Path) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(installed), "run", "--source", str(source), "--host", host],
        "StartInterval": minutes * 60, "RunAtLoad": True, "ProcessType": "Background",
        "WorkingDirectory": str(Path.home()), "Umask": 0o077,
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")},
        "StandardOutPath": str(state / "events.log"),
        "StandardErrorPath": str(state / "errors.log"),
    })


def install(source: Path, host: str, minutes: int, render_only: Path | None) -> int:
    source = validate_source(source)
    endpoint(host)
    account_root = Path.home()
    installed = account_root / ".local/lib/scout-workspace-sync/sync-mac-workspace.py"
    state = account_root / ".local/state/scout-workspace-sync"
    directory = render_only or account_root / "Library/LaunchAgents"
    target = directory / (LABEL + ".plist")
    if target.exists() or target.is_symlink() or (not render_only and (installed.exists() or installed.is_symlink())):
        raise SyncError("Installation already exists; inspect it before changing the schedule")
    if not render_only:
        if sys.platform != "darwin":
            raise SyncError("Install this LaunchAgent on the Mac, not on Scout")
        active = subprocess.run(["launchctl", "print", "gui/" + str(os.getuid()) + "/" + LABEL],
                                capture_output=True)
        if active.returncode == 0:
            raise SyncError("This launchd label is already loaded; nothing was replaced")
        # Fail before installation if background SSH or the actual rsync options do not work.
        remote_probe(host, prepare=False)
        checked(rsync_command(source, host, BACKUPS + "/installation-check", dry_run=True))
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=True)
    if not render_only:
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        installed.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(Path(__file__), installed)
        installed.chmod(0o600)
    target.write_bytes(launch_agent(source, host, minutes, installed, state))
    target.chmod(0o600)
    if not render_only:
        try:
            checked(["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(target)], timeout=30)
        except (SyncError, OSError, subprocess.TimeoutExpired) as error:
            raise SyncError("Files installed, but schedule was not activated: " + str(error)) from error
    print(json.dumps({"status": "rendered" if render_only else "installed", "minutes": minutes,
                      "source": str(source), "destination": endpoint(host) + ":" + DESTINATION,
                      "plist": str(target), "state": str(state / "status.json"),
                      "note": "A synced status or Scout receipt is required to confirm the first real transfer."},
                     ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "run"))
    parser.add_argument("--source", type=Path, default=Path.home() / "workspace")
    parser.add_argument("--host", default="scout.local")
    parser.add_argument("--minutes", type=int, default=15, choices=(5, 10, 15, 20, 30, 60))
    parser.add_argument("--render-only", type=Path, help="Render a plist here without networking or activating")
    args = parser.parse_args()
    try:
        if args.action == "install":
            return install(args.source, args.host, args.minutes, args.render_only)
        if args.render_only:
            parser.error("--render-only is only valid with install")
        if sys.platform != "darwin":
            raise SyncError("Run this sender on the Mac, not on Scout")
        return sync_once(args.source, args.host, Path.home() / ".local/state/scout-workspace-sync")
    except (SyncError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
