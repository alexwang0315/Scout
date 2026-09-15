"""Focused tests for the Scout-side commit gateway."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts/scout-commit-server.py"
SPEC = importlib.util.spec_from_file_location("gateway", SERVER)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)


class CommitGatewayTests(unittest.TestCase):
    branch = "main"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scout-commit-gateway-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bare = self.root / "bare.git"
        self.staging = self.root / "staging"
        self.lock = self.root / "state/commit.lock"
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git(self.root, "init", "--bare", str(self.bare))
        source = self.root / "source"
        self.git(self.root, "init", "--initial-branch", self.branch, str(source))
        self.git(source, "config", "user.name", "Gateway Test")
        self.git(source, "config", "user.email", "gateway@example.invalid")
        (source / "README.md").write_text("base\n")
        self.git(source, "add", "README.md")
        self.git(source, "commit", "-m", "Base")
        self.git(source, "remote", "add", "origin", str(self.bare))
        self.git(source, "push", "--set-upstream", "origin", self.branch)
        self.git(self.root, "clone", "--branch", self.branch, str(self.bare), str(self.staging))
        self.git(self.staging, "config", "user.name", "Gateway Test")
        self.git(self.staging, "config", "user.email", "gateway@example.invalid")
        exclude = self.staging / ".git/info/exclude"
        exclude.write_text(exclude.read_text() + "\nnode_modules/\nreports/\n.env\n")

    def git(self, cwd: Path, *args: str, check=True):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              check=check, capture_output=True, text=True)

    def gateway_run(self, action, message=None, allow_dirty=False):
        command = [sys.executable, str(SERVER), action, "--repo", str(self.staging),
                   "--branch", self.branch, "--lock", str(self.lock)]
        if message is not None:
            command.extend(["--message", message])
        if allow_dirty:
            command.append("--allow-dirty")
        return subprocess.run(command, env=self.env, capture_output=True, text=True)

    def test_status_is_ready_when_staging_is_clean(self):
        result = self.gateway_run("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["changed_items"], [])

    def test_commit_pushes_snapshot_and_excludes_local_artifacts(self):
        (self.staging / "new.py").write_text("print('new')\n")
        (self.staging / "node_modules").mkdir()
        (self.staging / "node_modules/package.js").write_text("dependency\n")
        (self.staging / "reports").mkdir()
        (self.staging / "reports/result.json").write_text("local report\n")
        (self.staging / ".env").write_text("SECRET=never-commit\n")
        result = self.gateway_run("commit", "Sync Mac project snapshot", allow_dirty=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "committed")
        remote_head = self.git(self.bare, "rev-parse", "refs/heads/main").stdout.strip()
        self.assertEqual(remote_head, report["head"])
        files = self.git(self.bare, "ls-tree", "-r", "--name-only", "refs/heads/main").stdout.splitlines()
        self.assertIn("new.py", files)
        self.assertNotIn("node_modules/package.js", files)
        self.assertNotIn("reports/result.json", files)
        self.assertNotIn(".env", files)

    def test_no_changes_does_not_create_commit(self):
        before = self.git(self.staging, "rev-parse", "HEAD").stdout.strip()
        result = self.gateway_run("commit", "No-op")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "no_changes")
        self.assertEqual(self.git(self.staging, "rev-parse", "HEAD").stdout.strip(), before)

    def test_pending_staging_changes_are_blocked_without_commit(self):
        (self.staging / "pending.txt").write_text("pending\n")
        self.git(self.staging, "add", "pending.txt")
        result = self.gateway_run("commit", "Should not run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("pending changes", result.stderr)
        self.assertEqual(self.git(self.bare, "rev-parse", "refs/heads/main").stdout.strip(),
                         self.git(self.staging, "rev-parse", "HEAD").stdout.strip())

    def test_empty_message_is_blocked(self):
        (self.staging / "new.py").write_text("change\n")
        result = self.gateway_run("commit", "   ")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be empty", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
