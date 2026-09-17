#!/usr/bin/env python3
"""Synchronize committed work on one pinned branch; never reconcile divergence."""

from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class SyncBlocked(Exception):
    def __init__(self, reason: str, summary: str):
        self.reason = reason
        self.summary = summary


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=10")
    # Never include Git stderr in receipts: remote URLs can contain credentials.
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "-c", "credential.interactive=false", *args],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise SyncBlocked("git_timeout", "Git timed out; check connectivity and authentication.") from exc
    if check and result.returncode:
        raise SyncBlocked("git_failed", "Git failed; check repository, connectivity and authentication manually.")
    return result


def clean_head(repo: Path, branch: str, expected: str | None = None) -> str:
    actual = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if actual.returncode or actual.stdout.strip() != branch:
        raise SyncBlocked("branch_mismatch", "Checkout is detached or on a different branch; no branch switch attempted.")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_LOG"):
        location = Path(git(repo, "rev-parse", "--git-path", marker).stdout.strip())
        if (repo / location).exists():
            raise SyncBlocked("operation_in_progress", "Finish the existing Git operation before synchronizing.")
    if git(repo, "status", "--porcelain", "--untracked-files=normal", "--ignore-submodules=none").stdout:
        raise SyncBlocked("dirty", "Uncommitted work preserved; review and commit it to resume synchronization.")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    if expected is not None and head != expected:
        raise SyncBlocked("checkout_changed", "Checkout changed during synchronization; retry on the next interval.")
    return head


def sync(repo: Path, branch: str, remote: str, expected_url: str) -> dict:
    if remote.startswith("-") or branch.startswith("-"):
        raise SyncBlocked("invalid_target", "Invalid branch or remote.")
    git(repo, "check-ref-format", "refs/heads/" + branch)
    head = clean_head(repo, branch)
    for flags in ((), ("--push",)):
        urls = git(repo, "remote", "get-url", "--all", *flags, remote).stdout.splitlines()
        if urls != [expected_url]:
            raise SyncBlocked("remote_mismatch", "Remote destination changed; review and reinstall the schedule.")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    if upstream.returncode or upstream.stdout.strip() != remote + "/" + branch:
        raise SyncBlocked("upstream_mismatch", "Upstream differs from the pinned synchronization branch.")
    tracking_ref = "refs/remotes/" + remote + "/" + branch
    git(repo, "fetch", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
        remote, "+refs/heads/" + branch + ":" + tracking_ref)
    remote_head = git(repo, "rev-parse", tracking_ref).stdout.strip()
    clean_head(repo, branch, head)
    report = {"status": "synced", "summary": "Already synchronized.", "head": head}
    if head == remote_head:
        return report
    if git(repo, "merge-base", "--is-ancestor", head, remote_head, check=False).returncode == 0:
        git(repo, "-c", "merge.autoStash=false", "-c", "submodule.recurse=false",
            "merge", "--ff-only", "--no-edit", remote_head)
        report.update(status="pulled", summary="Fast-forwarded committed changes from the remote.", head=remote_head)
    elif git(repo, "merge-base", "--is-ancestor", remote_head, head, check=False).returncode == 0:
        # Push only the already-checked commit, never a moving HEAD or extra tags.
        clean_head(repo, branch, head)
        git(repo, "-c", "push.followTags=false", "push", "--porcelain",
            "--recurse-submodules=no", remote, head + ":refs/heads/" + branch)
        report.update(status="pushed", summary="Pushed committed changes to the pinned remote branch.")
    else:
        raise SyncBlocked("diverged", "Both sides have different commits; manual integration is required.")
    return report


def notify(summary: str) -> str:
    if sys.platform == "darwin":
        command = ["/usr/bin/osascript", "-e",
                   "on run argv\ndisplay notification (item 1 of argv) with title \"Scout Git sync\"\nend run", summary]
    elif shutil.which("notify-send"):
        command = ["notify-send", "Scout Git sync", summary]
    else:
        return "unavailable"
    try:
        result = subprocess.run(command, capture_output=True, timeout=10)
        return "sent" if result.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--expected-url", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            report = sync(args.repo.resolve(), args.branch, args.remote, args.expected_url)
        except SyncBlocked as exc:
            report = {"status": "blocked", "reason": exc.reason, "summary": exc.summary}
        except OSError:
            report = {"status": "blocked", "reason": "environment_error", "summary": "Check Git installation and repository permissions."}
        status_path = args.state_dir / "status.json"
        try:
            previous = json.loads(status_path.read_text()) if status_path.exists() else {}
            if not isinstance(previous, dict):
                previous = {}
        except (OSError, ValueError):
            previous = {}
        signature = {key: report.get(key) for key in ("status", "reason", "head")}
        changed = signature != previous.get("signature")
        report.update(
            signature=signature, repo=str(args.repo.resolve()), branch=args.branch,
            checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
        # Only notify changes, successful transfers, or recovery from a blockage.
        actionable = report["status"] != "synced" or previous.get("status") == "blocked"
        report["notification"] = "not_requested"
        if args.notify and changed and actionable:
            report["notification"] = notify(report["summary"])
        with tempfile.NamedTemporaryFile(mode="w", dir=args.state_dir, delete=False) as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(output.name, status_path)
        if changed or args.verbose:
            print(json.dumps(report, ensure_ascii=False))
    # A blocked checkout is an expected condition, not a failed scheduler process.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
