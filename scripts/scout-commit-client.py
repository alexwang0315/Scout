#!/usr/bin/env python3
"""Sync a Mac worktree to Scout, then optionally commit it on Scout."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


DEFAULT_SOURCE = "/Users/alexwang0315/scout-fusion"
DEFAULT_HOST = "scout.local"
DEFAULT_USER = "alexwang0315"
DEFAULT_STAGING = "/home/alexwang0315/work/scout-fusion-mac-commit"
DEFAULT_SERVER_SCRIPT = "/home/alexwang0315/.local/lib/scout-commit/scout-commit-server.py"
DEFAULT_BRANCH = "codex/scout-wip-transfer-20260822"
COMMAND_TIMEOUT_SECONDS = 1800


class ClientError(Exception):
    pass


def command(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise ClientError("Required command unavailable: " + name)
    return value


def check_source(source: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_dir() or source == Path.home().resolve() or source == Path("/"):
        raise ClientError("Source must be an existing project directory, not home or root")
    return source


def ssh_base(host: str, user: str) -> list[str]:
    if not host or any(char in host for char in "\r\n;|&`$"):
        raise ClientError("Invalid Scout host")
    if not user or any(char in user for char in "\r\n;|&`$"):
        raise ClientError("Invalid Scout user")
    return [command("ssh"), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", user + "@" + host]


def run(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, input=stdin, capture_output=True, text=True,
                                errors="replace", timeout=COMMAND_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClientError("Command could not complete: " + str(error)) from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ClientError(detail[-1600:])
    return result


def remote_probe(ssh: list[str], staging: str, user: str) -> None:
    if not staging.startswith("/home/" + user + "/") or "\n" in staging or "\r" in staging:
        raise ClientError("Staging path is outside the configured Scout home")
    remote = ("test \"$(id -un)\" = " + shlex.quote(user)
              + " && test -d " + shlex.quote(staging)
              + " && test ! -L " + shlex.quote(staging)
              + " && test -w " + shlex.quote(staging)
              + " && test -x " + shlex.quote(staging + "/.git"))
    run(ssh + [remote])


def rsync_source(source: Path, ssh: list[str], staging: str, *, dry_run: bool) -> str:
    excluded = [".git/", "artifacts/", "artifacts.internal-backup-*/", "node_modules/", "reports/", ".env", ".env.*/", ".env.*",
                ".venv/", "venv/", "__pycache__/", "*.pyc", ".DS_Store"]
    args = [command("rsync"), "-rlt", "--delete", "--partial", "--timeout=120",
            "--rsync-path=umask 077 && rsync"]
    for pattern in excluded:
        args.extend(["--exclude", pattern])
    args.extend(["-e", shlex.join(ssh[:-1])])
    if dry_run:
        args.append("--dry-run")
    args.extend(["--", str(source) + "/", ssh[-1] + ":" + staging + "/"])
    return run(args).stdout


def server_action(ssh: list[str], server_script: str, staging: str, branch: str,
                  action: str, message: str | None, *, allow_dirty: bool = False) -> dict:
    args = ["python3", server_script, action, "--repo", staging, "--branch", branch]
    if allow_dirty:
        args.append("--allow-dirty")
    if message is not None:
        args.extend(["--message", message])
    remote = " ".join(shlex.quote(item) for item in args)
    result = run(ssh + [remote])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ClientError("Scout returned a non-JSON gateway response") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "commit"))
    parser.add_argument("message", nargs="?")
    parser.add_argument("--source", type=Path, default=Path(DEFAULT_SOURCE))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--staging", default=DEFAULT_STAGING)
    parser.add_argument("--server-script", default=DEFAULT_SERVER_SCRIPT)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/scout-commit")
    args = parser.parse_args()
    try:
        source = check_source(args.source)
        if args.action == "commit" and not args.message:
            raise ClientError("commit requires a message")
        args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.state_dir.chmod(0o700)
        lock_path = args.state_dir / "client.lock"
        with lock_path.open("a") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ClientError("Another Mac -> Scout gateway run is active") from error
            ssh = ssh_base(args.host, args.user)
            remote_probe(ssh, args.staging, args.user)
            # The staging checkout is private to this client. Reusing it as
            # the rsync destination makes an interrupted transfer resumable;
            # the server-side commit still requires --allow-dirty explicitly.
            transfer = rsync_source(source, ssh, args.staging, dry_run=args.dry_run)
            if args.dry_run:
                result = {"status": "dry-run", "source": str(source),
                          "destination": ssh[-1] + ":" + args.staging, "rsync": transfer}
            else:
                result = server_action(ssh, args.server_script, args.staging, args.branch,
                                       args.action, args.message, allow_dirty=True)
                result["source"] = str(source)
                result["rsync"] = transfer
    except ClientError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
