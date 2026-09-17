"""Real local Git repositories exercise the scheduled-sync safety boundary."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/sync-project-git.py"
INSTALLER = ROOT / "scripts/install-scout-git-sync.py"


class ProjectGitSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scout-git-sync-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.remote = self.root / "remote.git"
        self.mac = self.root / "mac"
        self.scout = self.root / "scout"
        self.git(self.root, "init", "--bare", str(self.remote))
        self.git(self.root, "init", "--initial-branch=shared", str(self.mac))
        self.git(self.mac, "config", "user.name", "Sync Test")
        self.git(self.mac, "config", "user.email", "sync@example.invalid")
        self.commit(self.mac, "base.txt", "base")
        self.git(self.mac, "remote", "add", "origin", str(self.remote))
        self.git(self.mac, "push", "--set-upstream", "origin", "shared")
        self.git(self.root, "clone", "--branch", "shared", str(self.remote), str(self.scout))
        self.git(self.scout, "config", "user.name", "Sync Test")
        self.git(self.scout, "config", "user.email", "sync@example.invalid")

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, repo, filename, content):
        (repo / filename).write_text(content)
        self.git(repo, "add", filename)
        self.git(repo, "commit", "-m", "Update " + filename)

    def run_sync(self, repo):
        state = self.root / (repo.name + "-state")
        output = subprocess.run(
            [sys.executable, str(RUNNER), "--repo", str(repo), "--branch", "shared",
             "--expected-url", str(self.remote), "--state-dir", str(state)],
            env=self.env, capture_output=True, text=True, check=True,
        )
        return json.loads((state / "status.json").read_text()), output.stdout

    def test_commits_travel_in_both_directions(self):
        self.commit(self.mac, "from-mac.txt", "Mac work")
        self.assertEqual(self.run_sync(self.mac)[0]["status"], "pushed")
        self.assertEqual(self.run_sync(self.scout)[0]["status"], "pulled")
        self.assertEqual((self.scout / "from-mac.txt").read_text(), "Mac work")
        self.commit(self.scout, "from-scout.txt", "Scout work")
        self.assertEqual(self.run_sync(self.scout)[0]["status"], "pushed")
        self.assertEqual(self.run_sync(self.mac)[0]["status"], "pulled")
        self.assertEqual(self.git(self.mac, "rev-parse", "HEAD"), self.git(self.scout, "rev-parse", "HEAD"))

    def test_dirty_work_blocks_pull_and_push_without_stashing(self):
        self.commit(self.mac, "incoming.txt", "incoming")
        self.git(self.mac, "push")
        original = self.git(self.scout, "rev-parse", "HEAD")
        (self.scout / "base.txt").write_text("unsaved work")
        (self.scout / "new.txt").write_text("untracked work")
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "dirty")
        self.assertEqual(self.git(self.scout, "rev-parse", "HEAD"), original)
        self.assertEqual((self.scout / "base.txt").read_text(), "unsaved work")
        self.assertEqual((self.scout / "new.txt").read_text(), "untracked work")
        self.assertFalse(self.git(self.scout, "stash", "list"))

    def test_staged_work_is_not_committed_or_pushed(self):
        original = self.git(self.remote, "rev-parse", "refs/heads/shared")
        (self.scout / "base.txt").write_text("staged work")
        self.git(self.scout, "add", "base.txt")
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "dirty")
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/heads/shared"), original)
        self.assertIn("staged work", self.git(self.scout, "diff", "--cached"))

    def test_divergence_does_not_merge_or_rewrite(self):
        self.commit(self.mac, "mac.txt", "Mac")
        self.git(self.mac, "push")
        self.commit(self.scout, "scout.txt", "Scout")
        head = self.git(self.scout, "rev-parse", "HEAD")
        remote = self.git(self.remote, "rev-parse", "refs/heads/shared")
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "diverged")
        self.assertEqual(self.git(self.scout, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git(self.remote, "rev-parse", "refs/heads/shared"), remote)
        self.assertFalse((self.scout / ".git/MERGE_HEAD").exists())

    def test_detached_or_different_branch_is_not_switched(self):
        self.git(self.scout, "switch", "-c", "other")
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "branch_mismatch")
        self.assertEqual(self.git(self.scout, "branch", "--show-current"), "other")
        self.git(self.scout, "checkout", "--detach")
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "branch_mismatch")

    def test_changed_push_destination_is_rejected(self):
        self.git(self.scout, "remote", "set-url", "--push", "origin", str(self.root / "another.git"))
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "remote_mismatch")

    def test_in_progress_operation_is_preserved(self):
        marker = self.scout / ".git/rebase-merge"
        marker.mkdir()
        self.assertEqual(self.run_sync(self.scout)[0]["reason"], "operation_in_progress")
        self.assertTrue(marker.exists())

    def test_push_does_not_publish_extra_tags(self):
        self.commit(self.scout, "scout.txt", "Scout")
        self.git(self.scout, "tag", "-a", "private-tag", "-m", "Local tag")
        self.git(self.scout, "config", "push.followTags", "true")
        self.assertEqual(self.run_sync(self.scout)[0]["status"], "pushed")
        self.assertFalse(self.git(self.remote, "tag", "--list"))

    def test_unchanged_status_is_quiet_and_lock_prevents_overlap(self):
        self.run_sync(self.scout)
        self.assertEqual(self.run_sync(self.scout)[1], "")
        lock_path = self.root / "scout-state/sync.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_sync(self.scout)[1], "")

    def test_mac_and_linux_schedules_render_without_activation(self):
        for platform in ("darwin", "linux"):
            target = self.root / platform
            result = subprocess.run(
                [sys.executable, str(INSTALLER), str(self.scout), "--branch", "shared",
                 "--expected-url", str(self.remote), "--render-only", str(target), "--platform", platform],
                env=self.env, capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(result.stdout)["status"], "rendered")
            if platform == "darwin":
                job = plistlib.loads((target / "com.scout.fusion.git-sync.plist").read_bytes())
                self.assertEqual(job["StartInterval"], 900)
                self.assertIn(str(self.scout), job["ProgramArguments"])
                self.assertEqual(job["ProgramArguments"][0], sys.executable)
            else:
                self.assertIn("OnCalendar=*-*-* *:00/15:00", (target / "scout-fusion-git-sync.timer").read_text())


if __name__ == "__main__":
    unittest.main()
