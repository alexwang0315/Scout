import unittest
from pathlib import Path

from pydantic import ValidationError

from case_replay import (
    VERDICT_LEVELS,
    CaseReplay,
    ReplayAssessment,
    TimelineCheckpoint,
    VerdictLevel,
    load_case_replay,
    score_case_replay,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2" / "cases"


class Phase2CaseReplayTests(unittest.TestCase):
    def test_verdict_levels_are_exactly_milestone_8_levels(self):
        self.assertEqual(
            [level.value for level in VERDICT_LEVELS],
            [
                "no_effect",
                "evidence_improvement",
                "earlier_awareness",
                "decision_window_created",
                "likely_outcome_improvement",
            ],
        )

    def test_loads_realistic_mountain_incident_timeline_fixture(self):
        case = load_case_replay(FIXTURE_DIR / "fog_delay_ridge_turnaround.json")

        self.assertEqual(case.timeline[0].label, "T-180")
        self.assertEqual(case.timeline[-1].label, "T-0")
        self.assertGreaterEqual(len(case.post_incident_evidence), 1)
        self.assertEqual(
            score_case_replay(case).level,
            VerdictLevel.DECISION_WINDOW_CREATED,
        )

    def test_scores_all_realistic_fixtures_with_bounded_verdicts(self):
        expected_levels = {
            "fog_delay_ridge_turnaround.json": VerdictLevel.DECISION_WINDOW_CREATED,
            "river_gorge_team_separation.json": VerdictLevel.EARLIER_AWARENESS,
            "cold_rain_bivouac_delay.json": VerdictLevel.LIKELY_OUTCOME_IMPROVEMENT,
        }

        for fixture_name, expected_level in expected_levels.items():
            with self.subTest(fixture_name=fixture_name):
                case = load_case_replay(FIXTURE_DIR / fixture_name)
                verdict = score_case_replay(case)

                self.assertEqual(verdict.level, expected_level)
                self.assertLessEqual(verdict.score, 4)
                self.assertNotIn("guaranteed", verdict.rationale.lower())
                self.assertNotIn("would have rescued", verdict.rationale.lower())

    def test_score_is_bounded_by_highest_supported_assessment_signal(self):
        case = CaseReplay(
            case_id="case.synthetic.no_effect",
            title="Synthetic no-effect replay",
            incident_type="navigation delay",
            location="test ridge",
            route_context="same-day loop",
            timeline=[
                TimelineCheckpoint(
                    label="T-0",
                    minutes_to_incident=0,
                    safety_level="L1",
                    summary="Incident declared with no useful new evidence.",
                )
            ],
            baseline_summary="Baseline already had the same signal.",
            replay_summary="Replay did not improve evidence or timing.",
            known_outcome_summary="No outcome change is claimed.",
            assessment=ReplayAssessment(),
        )

        verdict = score_case_replay(case)

        self.assertEqual(verdict.level, VerdictLevel.NO_EFFECT)
        self.assertEqual(verdict.score, 0)

    def test_rejects_checkpoint_label_offset_mismatch(self):
        with self.assertRaisesRegex(ValidationError, "does not match"):
            TimelineCheckpoint(
                label="T-60",
                minutes_to_incident=-30,
                safety_level="L1",
                summary="Bad fixture checkpoint.",
            )

    def test_rejects_guaranteed_outcome_claims(self):
        with self.assertRaisesRegex(ValidationError, "cannot claim guaranteed outcomes"):
            ReplayAssessment(
                likely_outcome_improvement=True,
                guaranteed_outcome=True,
            )


if __name__ == "__main__":
    unittest.main()
