#!/usr/bin/env python3
"""Push a clean local Git checkout to Scout's private SSH bare repository."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REMOTE_NAME = "scout"
DEFAULT_HOST = "scout.local"
DEFAULT_USER = "alexwang0315"
DEFAULT_SERVER_PATH = "/home/alexwang0315/git/scout-fusion.git"


class MigrationError(Exception):
    pass


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    environment["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace", timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MigrationError("Git command could not complete: " + str(error)) from error
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise MigrationError("Git command failed: " + detail[-1200:])
    return result


def output(repo: Path, *args: str, check: bool = True) -> str:
    return run(repo, *args, check=check).stdout.strip()


def validate_host(host: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise MigrationError("Host must be a hostname or IPv4 address")
    return host


def remote_url(host: str, user: str, server_path: str) -> str:
    validate_host(host)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", user):
        raise MigrationError("User must be a simple SSH account name")
    if not Path(server_path).is_absolute() or "\n" in server_path or "\r" in server_path:
        raise MigrationError("Server path must be an absolute path")
    return f"{user}@{host}:{server_path}"


def prepare(repo: Path, expected_repo: Path) -> tuple[str, str]:
    root = Path(output(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != expected_repo:
        raise MigrationError(f"Not the requested checkout: Git root is {root}")
    status = output(repo, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise MigrationError("Checkout has uncommitted or untracked work; save/commit it before migration")
    branch_result = run(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = branch_result.stdout.strip()
    if branch_result.returncode or not branch:
        raise MigrationError("Checkout is detached; switch to the intended branch before migration")
    if run(repo, "show-ref", "--verify", "--quiet", "refs/heads/" + branch, check=False).returncode:
        raise MigrationError("Current branch has no commit to migrate")
    return branch, output(repo, "rev-parse", "HEAD")


def ensure_remote(repo: Path, url: str) -> None:
    existing = run(repo, "remote", "get-url", "--all", REMOTE_NAME, check=False)
    if existing.returncode:
        run(repo, "remote", "add", REMOTE_NAME, url)
        return
    urls = existing.stdout.splitlines()
    pushes = run(repo, "remote", "get-url", "--push", "--all", REMOTE_NAME, check=False)
    push_urls = pushes.stdout.splitlines() if pushes.returncode == 0 else []
    if urls != [url] or (push_urls and push_urls != [url]):
        raise MigrationError(f"Remote '{REMOTE_NAME}' already exists with a different URL")


def push_all(repo: Path, branch: str, dry_run: bool) -> None:
    if dry_run:
        # Git cannot dry-run --all against an empty remote because there are no
        # common refs. Preview each explicit local ref instead.
        branches = output(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines()
        for local_branch in branches:
            run(repo, "push", "--dry-run", REMOTE_NAME, local_branch)
        tags = output(repo, "for-each-ref", "--format=%(refname:short)", "refs/tags/").splitlines()
        for tag in tags:
            run(repo, "push", "--dry-run", REMOTE_NAME, tag)
        return
    run(repo, "push", REMOTE_NAME, "--all")
    run(repo, "push", REMOTE_NAME, "--tags")
    run(repo, "push", "--set-upstream", REMOTE_NAME, branch)


def migrate(repo: Path, host: str, user: str, server_path: str,
            expected_repo: Path, dry_run: bool, url_override: str | None = None) -> dict:
    branch, head = prepare(repo, expected_repo)
    url = url_override or remote_url(host, user, server_path)
    ensure_remote(repo, url)
    before = output(repo, "ls-remote", REMOTE_NAME)
    push_all(repo, branch, dry_run)
    if dry_run:
        after = before
    else:
        branch_ref = output(repo, "ls-remote", REMOTE_NAME, "refs/heads/" + branch)
        if not branch_ref or branch_ref.split()[0] != head:
            raise MigrationError("Scout server did not advertise the migrated branch at the expected commit")
        run(repo, "config", "remote.pushDefault", REMOTE_NAME)
        after = output(repo, "ls-remote", REMOTE_NAME)
    return {
        "status": "dry-run" if dry_run else "migrated", "remote": REMOTE_NAME, "url": url,
        "branch": branch, "head": head, "refs_before": len(before.splitlines()),
        "refs_after": len(after.splitlines()),
        "push_default": None if dry_run else REMOTE_NAME,
        "note": "Mac working files were not transferred; Git does not push uncommitted changes.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--server-path", default=DEFAULT_SERVER_PATH)
    parser.add_argument("--remote-url", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        repo = args.repo.expanduser().resolve()
        if not repo.is_dir():
            raise MigrationError("Checkout directory does not exist: " + str(repo))
        report = migrate(repo, args.host, args.user, args.server_path, repo, args.dry_run, args.remote_url)
    except MigrationError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
