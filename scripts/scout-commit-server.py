#!/usr/bin/env python3
"""Commit a Mac-synced worktree on Scout and push it to the local bare server."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_REPO = "/home/alexwang0315/work/scout-fusion-mac-commit"
DEFAULT_BRANCH = "codex/scout-wip-transfer-20260822"
DEFAULT_LOCK = "/home/alexwang0315/.local/state/scout-commit/commit.lock"


class CommitGatewayError(Exception):
    pass


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace", timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CommitGatewayError("Git command could not complete: " + str(error)) from error
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CommitGatewayError("Git command failed: " + detail[-1200:])
    return result


def text(repo: Path, *args: str, check: bool = True) -> str:
    return git(repo, *args, check=check).stdout.strip()


def ensure_repo(repo: Path, branch: str, *, allow_dirty: bool = False) -> None:
    if not repo.is_dir() or (repo / ".git").is_symlink():
        raise CommitGatewayError("Staging checkout is missing or is a symlink")
    root = Path(text(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != repo.resolve():
        raise CommitGatewayError("Staging checkout resolved outside the configured path")
    current = text(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if current != branch:
        raise CommitGatewayError("Staging checkout is not on the configured branch")
    # The bare server is a local path remote. Fetching gives a deterministic
    # fast-forward point without touching the synced worktree files.
    git(repo, "fetch", "--no-tags", "origin", branch)
    upstream = "refs/remotes/origin/" + branch
    local_head = text(repo, "rev-parse", "HEAD")
    remote_head = text(repo, "rev-parse", upstream)
    if local_head != remote_head:
        if git(repo, "merge-base", "--is-ancestor", local_head, remote_head, check=False).returncode == 0:
            git(repo, "merge", "--ff-only", "--no-edit", remote_head)
        else:
            raise CommitGatewayError("Staging checkout diverged from Scout bare server")
    if not allow_dirty and text(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise CommitGatewayError("Staging checkout has pending changes before Mac sync")


def report(repo: Path, branch: str, status: str, **extra: object) -> dict:
    changed = text(repo, "status", "--short", "--untracked-files=normal")
    return {
        "status": status,
        "branch": branch,
        "repo": str(repo),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "changed_items": changed.splitlines() if changed else [],
        **extra,
    }


def commit(repo: Path, branch: str, message: str, *, allow_dirty: bool = False) -> dict:
    if not message.strip():
        raise CommitGatewayError("Commit message cannot be empty")
    ensure_repo(repo, branch, allow_dirty=allow_dirty)
    git(repo, "add", "--all", "--", ".")
    check = git(repo, "diff", "--cached", "--check", check=False)
    if check.returncode:
        raise CommitGatewayError("Staged diff has whitespace errors; no commit was created")
    staged = text(repo, "diff", "--cached", "--name-status")
    if not staged:
        return report(repo, branch, "no_changes", message=message)
    commit_result = git(repo, "commit", "-m", message)
    head = text(repo, "rev-parse", "HEAD")
    git(repo, "push", "origin", "HEAD:refs/heads/" + branch)
    remote_head = text(repo, "ls-remote", "origin", "refs/heads/" + branch).split()[0]
    if remote_head != head:
        raise CommitGatewayError("Push completed but the bare server did not advertise the new HEAD")
    return report(repo, branch, "committed", head=head, message=message,
                  committed_files=staged.splitlines(), git_output=commit_result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "commit"))
    parser.add_argument("--repo", type=Path, default=Path(DEFAULT_REPO))
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--message")
    parser.add_argument("--lock", type=Path, default=Path(DEFAULT_LOCK))
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow the already-synced staging snapshot to contain changes",
    )
    args = parser.parse_args()
    try:
        args.repo = args.repo.expanduser().resolve()
        if args.action == "commit" and not (args.message or "").strip():
            raise CommitGatewayError("Commit message cannot be empty")
        args.lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.lock.parent.chmod(0o700)
        with args.lock.open("a") as lock:
            os.chmod(args.lock, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CommitGatewayError("Another Scout commit gateway run is active") from error
            ensure_repo(args.repo, args.branch, allow_dirty=args.allow_dirty)
            if args.action == "status":
                result = report(args.repo, args.branch, "ready")
            else:
                result = commit(args.repo, args.branch, args.message or "",
                                allow_dirty=args.allow_dirty)
    except CommitGatewayError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
