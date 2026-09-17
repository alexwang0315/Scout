"""Real rsync fixtures plus launchd/SSH safety checks, without touching real workspaces."""

from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).resolve().parents[1] / "scripts/sync-mac-workspace.py"
SPEC = importlib.util.spec_from_file_location("workspace_sync", RUNNER)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


@unittest.skipUnless(shutil.which("rsync"), "rsync is required for real transfer verification")
class WorkspaceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scout-workspace-sync-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Mac workspace"
        self.destination = self.root / "Scout workspace"
        self.backups = self.root / "backups"
        self.state = self.root / "state"
        self.source.mkdir()
        self.destination.mkdir(mode=0o700)
        # Keep process-global umask changes from leaking into other test modules.
        current_umask = os.umask(0o077)
        self.addCleanup(os.umask, current_umask)

    def local_rsync(self, run_id="first", dry_run=False):
        command = sync.rsync_command(self.source, "scout.local", str(self.backups / run_id), dry_run=dry_run)
        # Same real receiver/options as production, using local transport for the fixture.
        command[-1] = str(self.destination) + "/"
        return subprocess.run(command, capture_output=True, text=True, check=True)

    def test_incremental_transfer_retains_destination_only_files_and_backs_up_overwrites(self):
        (self.source / "route.txt").write_text("Mac version 1")
        (self.source / ".hidden-data").write_text("hidden workspace data")
        (self.destination / "scout-only.txt").write_text("Scout work")
        self.local_rsync()
        self.assertEqual((self.destination / "route.txt").read_text(), "Mac version 1")
        self.assertTrue((self.destination / ".hidden-data").exists())
        unchanged_mtime = (self.destination / "route.txt").stat().st_mtime_ns
        self.local_rsync("unchanged")
        self.assertEqual((self.destination / "route.txt").stat().st_mtime_ns, unchanged_mtime)
        self.assertFalse((self.backups / "unchanged" / "route.txt").exists())
        (self.destination / "route.txt").write_text("independent Scout edits that must remain recoverable")
        (self.source / "route.txt").write_text("Mac version 2 is updated")
        self.local_rsync("second")
        self.assertEqual((self.destination / "route.txt").read_text(), "Mac version 2 is updated")
        self.assertEqual((self.backups / "second" / "route.txt").read_text(),
                         "independent Scout edits that must remain recoverable")
        (self.source / "route.txt").unlink()
        self.local_rsync("third")
        self.assertTrue((self.destination / "route.txt").exists())
        self.assertEqual((self.destination / "scout-only.txt").read_text(), "Scout work")
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)

    def test_dry_run_does_not_change_destination_or_create_backup(self):
        (self.source / "route.txt").write_text("Mac update")
        (self.destination / "route.txt").write_text("Scout")
        self.local_rsync(dry_run=True)
        self.assertEqual((self.destination / "route.txt").read_text(), "Scout")
        self.assertFalse(self.backups.exists())

    def test_symlinks_are_not_followed_and_file_names_are_not_shell_commands(self):
        outside = self.root / "outside.txt"
        outside.write_text("do not follow this link")
        (self.source / "reference").symlink_to(outside)
        name = "route; $(touch not-a-command) '台灣'.txt"
        (self.source / name).write_text("normal data")
        self.local_rsync()
        self.assertTrue((self.destination / "reference").is_symlink())
        self.assertEqual(os.readlink(self.destination / "reference"), str(outside))
        self.assertEqual((self.destination / name).read_text(), "normal data")
        self.assertFalse((self.root / "not-a-command").exists())

    def test_commands_require_verified_noninteractive_ssh_and_no_delete(self):
        command = sync.rsync_command(self.source, "scout.local", str(self.backups))
        transport = command[command.index("-e") + 1]
        self.assertIn("BatchMode=yes", transport)
        self.assertIn("StrictHostKeyChecking=yes", transport)
        self.assertNotIn("--delete", " ".join(command))
        self.assertNotIn("--inplace", command)
        self.assertIn("--delay-updates", command)
        self.assertEqual(command[-1], "alexwang0315@scout.local:/home/alexwang0315/workspace/")

    def test_invalid_hosts_and_broad_or_missing_sources_are_rejected(self):
        for host in ("-oProxyCommand=anything", "scout; touch nope", "user@scout", "$(hostname)"):
            with self.assertRaises(sync.SyncError):
                sync.endpoint(host)
        for source in (Path("/"), Path.home(), self.root / "missing"):
            with self.assertRaises(sync.SyncError):
                sync.validate_source(source)

    def test_active_lock_skips_without_network_or_status_replacement(self):
        self.state.mkdir()
        with (self.state / "run.lock").open("w") as lock, patch.object(sync, "remote_probe") as remote:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(sync.sync_once(self.source, "scout.local", self.state), 0)
            remote.assert_not_called()
            self.assertFalse((self.state / "status.json").exists())

    def test_connection_failure_is_recorded_and_rsync_is_not_started(self):
        with patch.object(sync, "remote_probe", side_effect=sync.SyncError("SSH unavailable")), \
                patch.object(sync, "checked") as transfer, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.sync_once(self.source, "scout.local", self.state), 1)
            transfer.assert_not_called()
        status = json.loads((self.state / "status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertIn("SSH unavailable", status["error"])
        self.assertEqual((self.state / "status.json").stat().st_mode & 0o777, 0o600)

    def test_missing_source_records_failure_and_preserves_last_success(self):
        self.state.mkdir()
        sync.write_json(self.state / "status.json", {"status": "synced", "last_success_at": "prior-success"})
        with patch.object(sync, "remote_probe") as remote, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.sync_once(self.root / "missing", "scout.local", self.state), 1)
            remote.assert_not_called()
        status = json.loads((self.state / "status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["last_success_at"], "prior-success")

    def test_receipt_receiver_writes_private_json_without_shell_interpolation(self):
        receiver_state = self.root / "receiver state"
        receiver_state.mkdir()
        payload = {"status": "synced", "source": "/fake/workspace; $(not-a-command)", "changed_items": 2}
        with patch.object(sync, "REMOTE_STATE", str(receiver_state)), \
                patch.object(sync, "ssh_command", return_value=["/bin/sh", "-c"]):
            sync.receipt("scout.local", payload)
        saved = receiver_state / "last-success.json"
        self.assertEqual(json.loads(saved.read_text()), payload)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertFalse(saved.with_suffix(".tmp").exists())

    def test_runner_real_transfer_and_unchanged_runs_are_quiet(self):
        original_builder = sync.rsync_command

        def local_command(source, host, backup_dir):
            command = original_builder(source, host, backup_dir)
            command[-1] = str(self.destination) + "/"
            return command

        (self.source / "project.json").write_text('{"name":"fixture"}')
        with patch.object(sync, "BACKUPS", str(self.backups)), patch.object(sync, "remote_probe"), \
                patch.object(sync, "receipt") as receipt, \
                patch.object(sync, "rsync_command", side_effect=local_command):
            with contextlib.redirect_stdout(io.StringIO()) as first:
                self.assertEqual(sync.sync_once(self.source, "scout.local", self.state), 0)
            self.assertIn('"status": "synced"', first.getvalue())
            self.assertEqual((self.destination / "project.json").read_text(), '{"name":"fixture"}')
            with contextlib.redirect_stdout(io.StringIO()) as second:
                self.assertEqual(sync.sync_once(self.source, "scout.local", self.state), 0)
            self.assertEqual(second.getvalue(), "")
            self.assertEqual(receipt.call_count, 2)

    def test_rendered_launchagent_has_interval_and_fixed_installed_runner(self):
        result = subprocess.run([sys.executable, str(RUNNER), "install", "--source", str(self.source),
                                 "--render-only", str(self.root / "rendered")],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["status"], "rendered")
        plist = self.root / "rendered" / (sync.LABEL + ".plist")
        job = plistlib.loads(plist.read_bytes())
        self.assertEqual(job["StartInterval"], 900)
        self.assertTrue(job["RunAtLoad"])
        self.assertEqual(job["Umask"], 0o077)
        self.assertIn(".local/lib/scout-workspace-sync/", job["ProgramArguments"][1])
        self.assertEqual(job["ProgramArguments"][4], str(self.source))
        self.assertEqual(plist.stat().st_mode & 0o777, 0o600)

    def test_failed_install_preflight_does_not_install_or_activate(self):
        fake_account = self.root / "account"
        with patch.object(sync.Path, "home", return_value=fake_account), \
                patch.object(sync.sys, "platform", "darwin"), \
                patch.object(sync.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(sync, "remote_probe", side_effect=sync.SyncError("SSH unavailable")):
            with self.assertRaises(sync.SyncError):
                sync.install(self.source, "scout.local", 15, None)
        self.assertFalse(fake_account.exists())

    def test_existing_schedule_is_not_overwritten(self):
        rendered = self.root / "rendered"
        rendered.mkdir()
        target = rendered / (sync.LABEL + ".plist")
        target.write_text("existing user schedule")
        with self.assertRaises(sync.SyncError):
            sync.install(self.source, "scout.local", 15, rendered)
        self.assertEqual(target.read_text(), "existing user schedule")


if __name__ == "__main__":
    unittest.main()
