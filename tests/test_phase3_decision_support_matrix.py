import unittest
from pathlib import Path

from case_replay import load_case_replay, score_case_replay
from phase2_brain_models import DecisionOptionSet, RemoteStatusArtifact
from phase2_team_replay_store import load_team_replay_nodes


TEAM_REPLAY_DIR = Path(__file__).parent / "fixtures" / "phase2" / "team_replay"
CASE_DIR = Path(__file__).parent / "fixtures" / "phase2" / "cases"


class Phase3DecisionSupportMatrixTests(unittest.TestCase):
    def test_team_replay_matrix_covers_separation_and_stale_non_separation(self):
        ridge_nodes = _nodes_by_id(TEAM_REPLAY_DIR / "ridge_three_person_team_replay.json")
        forest_nodes = _nodes_by_id(TEAM_REPLAY_DIR / "forest_traverse_two_person_team_replay.json")

        ridge_remote = ridge_nodes["remote_status.ridge_loop_20260513T100800"]
        forest_remote = forest_nodes["remote_status.forest_traverse_20260513T082000"]

        self.assertIsInstance(ridge_remote, RemoteStatusArtifact)
        self.assertEqual(ridge_remote.status, "delayed_member_stale")
        self.assertEqual(
            ridge_remote.team_summary["possible_separation_member_ids"],
            ["person.member_lin"],
        )
        self.assertIn("separation is possible", ridge_remote.message)

        self.assertIsInstance(forest_remote, RemoteStatusArtifact)
        self.assertEqual(forest_remote.status, "nominal_short_delay")
        self.assertEqual(forest_remote.team_summary["possible_separation_member_ids"], [])
        self.assertNotIn("separation is possible", forest_remote.message)

    def test_option_fixture_covers_phase3_manual_decision_support_actions(self):
        nodes = _nodes_by_id(TEAM_REPLAY_DIR / "ridge_three_person_team_replay.json")
        option_set = nodes["options.ridge_loop_hold_or_regroup.20260513T101520"]

        self.assertIsInstance(option_set, DecisionOptionSet)
        actions = {option.action for option in option_set.options}
        self.assertTrue(
            {
                "hold_at_checkpoint",
                "activate_mock_beacon_and_move_only_on_improving_signal",
                "turn_back_to_previous_checkpoint",
                "wait_rest_reassess",
                "notify_remote_contact",
                "continue_with_degraded_confidence",
            }.issubset(actions)
        )
        self.assertIn("remote_status.ridge_loop_20260513T100800", option_set.input_refs)
        self.assertNotIn("phase1_live_state", option_set.input_refs)

    def test_case_replay_matrix_stays_bounded_and_avoids_guaranteed_claims(self):
        for path in sorted(CASE_DIR.glob("*.json")):
            with self.subTest(path=path.name):
                case = load_case_replay(path)
                verdict = score_case_replay(case)

                self.assertLessEqual(verdict.score, 4)
                self.assertFalse(case.assessment.guaranteed_outcome)
                combined_text = " ".join(
                    [
                        case.baseline_summary,
                        case.replay_summary,
                        case.known_outcome_summary,
                        case.assessment.rationale,
                        verdict.rationale,
                    ]
                ).lower()
                self.assertNotIn("guaranteed", combined_text)
                self.assertNotIn("would have rescued", combined_text)


def _nodes_by_id(path: Path) -> dict[str, object]:
    return {node.id: node for node in load_team_replay_nodes(path)}


if __name__ == "__main__":
    unittest.main()
