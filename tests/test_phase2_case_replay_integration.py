import unittest
from tempfile import TemporaryDirectory

from case_replay import VerdictLevel
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import (
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_SEPARATION_EVENT_REF,
    DEFAULT_SKILL_RUN_REFS,
    MissingBrainReferenceError,
    build_case_replay_from_brain,
    persist_team_replay_and_score_case,
)
from phase2_team_replay_store import persist_team_replay_to_brain_store


class Phase2CaseReplayIntegrationTests(unittest.TestCase):
    def test_persists_team_replay_and_scores_case_from_brain_refs(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = persist_team_replay_and_score_case(store)

            self.assertIn(DEFAULT_REMOTE_STATUS_REF, result.persisted.node_ids)
            self.assertIn(DEFAULT_OPTION_SET_REF, result.persisted.node_ids)
            self.assertIn(DEFAULT_SEPARATION_EVENT_REF, result.persisted.node_ids)
            for skill_run_ref in DEFAULT_SKILL_RUN_REFS:
                self.assertIn(skill_run_ref, result.persisted.node_ids)

            self.assertEqual(result.verdict.level, VerdictLevel.DECISION_WINDOW_CREATED)
            self.assertEqual(result.verdict.score, 3)
            self.assertNotIn("guaranteed", result.verdict.rationale.lower())
            self.assertNotIn("would have rescued", result.verdict.rationale.lower())
            self.assertFalse(result.case.assessment.guaranteed_outcome)

            remote_checkpoint = result.case.timeline[1]
            option_checkpoint = result.case.timeline[2]
            final_checkpoint = result.case.timeline[-1]

            self.assertEqual(remote_checkpoint.remote_status_ref, DEFAULT_REMOTE_STATUS_REF)
            self.assertIn(DEFAULT_REMOTE_STATUS_REF, remote_checkpoint.evidence_refs)
            self.assertEqual(option_checkpoint.option_set_ref, DEFAULT_OPTION_SET_REF)
            self.assertIn(DEFAULT_SEPARATION_EVENT_REF, option_checkpoint.evidence_refs)
            self.assertIn(DEFAULT_SKILL_RUN_REFS[1], option_checkpoint.evidence_refs)
            self.assertIn(DEFAULT_OPTION_SET_REF, final_checkpoint.evidence_refs)

            artifact_refs = set(final_checkpoint.artifact_refs)
            self.assertEqual(artifact_refs, {"artifact.remote_status_json.20260513T100800"})
            for artifact_ref in artifact_refs:
                self.assertIn(artifact_ref, result.persisted.node_ids)

    def test_build_fails_when_required_brain_ref_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            store.path_for_node(store.load_node(DEFAULT_REMOTE_STATUS_REF)).unlink()
            store.index_path.unlink()

            with self.assertRaisesRegex(
                MissingBrainReferenceError,
                f"required Brain ref is missing: {DEFAULT_REMOTE_STATUS_REF}",
            ):
                build_case_replay_from_brain(store)

    def test_build_fails_when_required_artifact_ref_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            artifact = store.load_node("artifact.remote_status_json.20260513T100800")
            store.path_for_node(artifact).unlink()
            store.index_path.unlink()

            with self.assertRaisesRegex(
                MissingBrainReferenceError,
                "required Brain ref is missing: artifact.remote_status_json.20260513T100800",
            ):
                build_case_replay_from_brain(store)

    def test_build_fails_when_skill_run_is_not_linked_to_case_refs(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)

            with self.assertRaisesRegex(
                MissingBrainReferenceError,
                "is not linked to required case replay Brain refs",
            ):
                build_case_replay_from_brain(
                    store,
                    skill_run_refs=(
                        "skill_run.team_checkin_summary.20260513T100800",
                        "skill_run.beacon_trend_mock.20260513T101900",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
