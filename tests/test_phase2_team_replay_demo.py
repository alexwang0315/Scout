import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from tempfile import TemporaryDirectory

from phase2_brain_models import BrainNodeType
from phase2_brain_store import BrainFileStore
from phase2_team_replay_demo import main, run_phase2_team_replay_demo


class Phase2TeamReplayDemoTests(unittest.TestCase):
    def test_demo_persists_fixture_remote_status_and_reports_compact_audit(self):
        with TemporaryDirectory() as tmpdir:
            summary = run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)

            self.assertEqual(summary.fixture_id, "phase2.team_replay.ridge_three_person_20260513")
            self.assertEqual(summary.counts["total_nodes"], 36)
            self.assertEqual(summary.counts["persisted_remote_status_artifacts"], 1)
            self.assertEqual(
                summary.remote_status_ids,
                ["remote_status.ridge_loop_20260513T100800"],
            )
            self.assertEqual(
                summary.persisted_remote_status_artifact_ids,
                ["artifact.remote_status_json.ridge_loop_20260513T100800"],
            )
            self.assertEqual(
                summary.option_set_ids,
                ["options.ridge_loop_hold_or_regroup.20260513T101520"],
            )
            self.assertEqual(
                summary.option_ids,
                ["option.hold_saddle_20min", "option.regroup_beacon_trend"],
            )
            self.assertEqual(summary.skill_audit["skill_runs"], 3)
            self.assertEqual(summary.skill_audit["activation_decisions"], {"allow": 2, "degrade": 1})
            self.assertIn(
                "skill_run.decision_options.20260513T101500",
                summary.skill_run_ids,
            )

            persisted_status = store.load_node("remote_status.ridge_loop_20260513T100800")
            self.assertEqual(persisted_status.type, BrainNodeType.REMOTE_STATUS_ARTIFACT)
            self.assertIn(
                "artifact.remote_status_json.ridge_loop_20260513T100800",
                persisted_status.artifact_refs,
            )

    def test_cli_prints_json_summary(self):
        with TemporaryDirectory() as tmpdir:
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--store-root", tmpdir])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["fixture_id"], "phase2.team_replay.ridge_three_person_20260513")
            self.assertEqual(payload["counts"]["decision_option_sets"], 1)
            self.assertEqual(payload["counts"]["skill_run_records"], 3)
            self.assertEqual(
                payload["key_ids"]["persisted_remote_status_artifacts"],
                ["artifact.remote_status_json.ridge_loop_20260513T100800"],
            )
            self.assertEqual(payload["skill_audit"]["manifest_refs_missing_locally"], 0)
            self.assertEqual(payload["skill_audit"]["missing_manifest_refs"], [])


if __name__ == "__main__":
    unittest.main()
