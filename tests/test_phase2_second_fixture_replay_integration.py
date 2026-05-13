import unittest
from tempfile import TemporaryDirectory

from case_replay import VerdictLevel
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import (
    build_case_replay_from_brain,
    persist_team_replay_and_score_case,
)
from phase2_demo_defaults import (
    DEFAULT_REMOTE_STATUS_REF,
    FOREST_REMOTE_STATUS_REF,
    FOREST_SKILL_RUN_REFS,
    FOREST_TEAM_REPLAY_FIXTURE_PATH,
)
from phase2_team_replay_store import persist_team_replay_to_brain_store


FOREST_SKILL_RUN_REF = FOREST_SKILL_RUN_REFS[0]


class Phase2SecondFixtureReplayIntegrationTests(unittest.TestCase):
    def test_case_integration_scores_explicit_forest_fixture_as_nominal_replay(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            result = persist_team_replay_and_score_case(
                store,
                fixture_path=FOREST_TEAM_REPLAY_FIXTURE_PATH,
                remote_status_ref=FOREST_REMOTE_STATUS_REF,
                option_set_ref=None,
                separation_event_ref=None,
                skill_run_refs=(FOREST_SKILL_RUN_REF,),
            )

            self.assertEqual(store.load_node(FOREST_REMOTE_STATUS_REF).id, FOREST_REMOTE_STATUS_REF)
            self.assertEqual(result.verdict.level, VerdictLevel.EVIDENCE_IMPROVEMENT)
            self.assertEqual(result.verdict.score, 1)
            self.assertFalse(result.case.assessment.guaranteed_outcome)
            self.assertEqual(result.case.incident_type, "nominal team status")
            self.assertEqual(result.case.timeline[-1].safety_level, "L1")
            self.assertEqual(result.case.timeline[-1].remote_status_ref, FOREST_REMOTE_STATUS_REF)
            self.assertIsNone(result.case.timeline[-1].option_set_ref)
            self.assertIn(FOREST_REMOTE_STATUS_REF, result.case.timeline[-1].evidence_refs)
            self.assertIn(FOREST_SKILL_RUN_REF, result.case.timeline[-1].evidence_refs)
            self.assertEqual(
                result.case.timeline[-1].artifact_refs,
                ["artifact.remote_status_json.forest_20260513T082000"],
            )
            with self.assertRaises(KeyError):
                store.load_node(DEFAULT_REMOTE_STATUS_REF)

    def test_case_builder_accepts_explicit_forest_remote_ref_for_nominal_replay(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store, FOREST_TEAM_REPLAY_FIXTURE_PATH)

            case = build_case_replay_from_brain(
                store,
                remote_status_ref=FOREST_REMOTE_STATUS_REF,
                option_set_ref=None,
                separation_event_ref=None,
                skill_run_refs=(FOREST_SKILL_RUN_REF,),
            )

            self.assertEqual(
                case.case_id,
                "case.phase2.forest_traverse_20260513T082000.nominal_remote_status_replay",
            )
            self.assertEqual(
                case.timeline[-1].evidence_refs,
                [FOREST_REMOTE_STATUS_REF, FOREST_SKILL_RUN_REF],
            )
            self.assertIn("without inventing", case.replay_summary)


if __name__ == "__main__":
    unittest.main()
