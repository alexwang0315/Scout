"""Focused migration tests using local bare Git repositories."""

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
SCRIPT = ROOT / "scripts/migrate-mac-repo-to-scout.py"
SPEC = importlib.util.spec_from_file_location("migrate", SCRIPT)
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


class GitMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scout-local-git-migration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "mac-repo"
        self.remote = self.root / "scout-fusion.git"
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git(self.root, "init", "--bare", str(self.remote))
        self.git(self.root, "init", "--initial-branch=main", str(self.repo))
        self.git(self.repo, "config", "user.name", "Migration Test")
        self.git(self.repo, "config", "user.email", "migration@example.invalid")
        (self.repo / "README.txt").write_text("base\n")
        self.git(self.repo, "add", "README.txt")
        self.git(self.repo, "commit", "-m", "Base")

    def git(self, cwd: Path, *args: str, check=True):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              check=check, capture_output=True, text=True)

    def run_migration(self, *args):
        command = [sys.executable, str(SCRIPT), str(self.repo), "--remote-url", str(self.remote), *args]
        return subprocess.run(command, env=self.env, capture_output=True, text=True)

    def test_migrates_all_local_history_and_sets_push_default(self):
        (self.repo / "second.txt").write_text("second\n")
        self.git(self.repo, "add", "second.txt")
        self.git(self.repo, "commit", "-m", "Second")
        result = self.run_migration()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "migrated")
        self.assertEqual(self.git(self.repo, "config", "--get", "remote.pushDefault").stdout.strip(), "scout")
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/heads/main").stdout.strip(),
                         self.git(self.repo, "rev-parse", "HEAD").stdout.strip())
        self.assertIn("refs/heads/main", self.git(self.repo, "ls-remote", "scout").stdout)

    def test_dirty_checkout_is_blocked_before_remote_add(self):
        (self.repo / "uncommitted.txt").write_text("do not lose\n")
        result = self.run_migration()
        self.assertEqual(result.returncode, 2)
        self.assertIn("uncommitted", result.stderr)
        self.assertNotIn("scout", self.git(self.repo, "remote").stdout.splitlines())
        self.assertFalse((self.remote / "refs/heads/main").exists())

    def test_dry_run_does_not_push_or_change_push_default(self):
        result = self.run_migration("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "dry-run")
        self.assertFalse((self.remote / "refs/heads/main").exists())
        self.assertNotEqual(self.git(self.repo, "config", "--get", "remote.pushDefault", check=False).returncode, 0)

    def test_existing_different_remote_is_blocked_without_force(self):
        other = self.root / "other.git"
        self.git(self.root, "init", "--bare", str(other))
        self.git(self.repo, "remote", "add", "scout", str(other))
        result = self.run_migration()
        self.assertEqual(result.returncode, 2)
        self.assertIn("different URL", result.stderr)
        self.assertFalse((self.remote / "refs/heads/main").exists())

    def test_host_validation_rejects_shell_syntax(self):
        with self.assertRaises(migrate.MigrationError):
            migrate.remote_url("scout;touch nope", "alexwang0315", "/home/alexwang0315/git/scout-fusion.git")


if __name__ == "__main__":
    unittest.main()
