import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import BrainNodeType, SkillRunRecord
from phase2_brain_store import BrainFileStore
from phase2_writeback_policy import WritebackPolicyError
from skill_runtime_integration import record_and_ingest_mock_skill_run


REPO_ROOT = Path(__file__).resolve().parents[1]


class SkillRuntimeIntegrationTests(unittest.TestCase):
    def test_registry_runtime_record_is_explicitly_ingested_into_file_brain(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            run = record_and_ingest_mock_skill_run(
                store,
                "remote-status-json",
                input_refs=["remote_status.remote_contact.status_request.20260513T100000"],
                output_refs=["remote_status.20260513T100000"],
                preflight_results={
                    "device-capability-check": {"status": "passed"},
                    "communication-state-check": {"status": "passed"},
                    "latest-team-position-check": {"status": "passed"},
                },
                activation_decision="allow",
                started_at="2026-05-13T10:00:00+08:00",
                ended_at="2026-05-13T10:00:03+08:00",
                mission_id="mission.hehuan_20260513",
                registry_dir=REPO_ROOT / "skills" / "scout",
            )

            loaded = store.load_node(run.id)
            skill_runs = store.list_nodes(BrainNodeType.SKILL_RUN_RECORD)

            self.assertIsInstance(run, SkillRunRecord)
            self.assertEqual(run.skill_id, "remote-status-json")
            self.assertEqual(run.skill_version, "0.1.0")
            self.assertEqual(run.failure_policy["on_error"], "record_failure")
            self.assertEqual(run.failure_policy["degrade_to"], "team-checkin-summary")
            self.assertEqual(loaded, run)
            self.assertEqual([node.id for node in skill_runs], [run.id])
            self.assertTrue(store.path_for_node(run).exists())

    def test_automatic_ingest_rejects_skill_run_record_from_runtime_integration(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            with self.assertRaisesRegex(
                WritebackPolicyError,
                "explicit audit record, not an automatic fact",
            ):
                record_and_ingest_mock_skill_run(
                    store,
                    "remote-status-json",
                    input_refs=["remote_status.remote_contact.status_request.20260513T100000"],
                    output_refs=["remote_status.20260513T100000"],
                    preflight_results={
                        "device-capability-check": {"status": "passed"},
                        "communication-state-check": {"status": "passed"},
                        "latest-team-position-check": {"status": "passed"},
                    },
                    activation_decision="allow",
                    started_at="2026-05-13T10:00:00+08:00",
                    run_id="skill_run.remote-status-json.rejected_auto_ingest",
                    registry_dir=REPO_ROOT / "skills" / "scout",
                    automatic=True,
                )

            self.assertEqual(store.list_nodes(BrainNodeType.SKILL_RUN_RECORD), [])
            self.assertFalse(
                (
                    Path(tmpdir)
                    / "skill-runs"
                    / "skill_run.remote-status-json.rejected_auto_ingest.json"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()
