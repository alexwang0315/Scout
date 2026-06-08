import unittest

from phase2_refs import Phase2RefKind, classify_phase2_ref


class Phase2RefTests(unittest.TestCase):
    def test_classifies_phase2_refs(self):
        cases = {
            "artifact.route_gpx.loop_01": Phase2RefKind.ARTIFACT,
            "remote_status.20260513T100000": Phase2RefKind.BRAIN_NODE,
            "options.ridge_loop_hold_or_regroup.20260513T101520": Phase2RefKind.BRAIN_NODE,
            "option.hold_saddle_20min": Phase2RefKind.BRAIN_NODE,
            "option_set.turnaround_ridge_fog": Phase2RefKind.BRAIN_NODE,
            "skill_run.team_checkin_summary.20260513T100800": Phase2RefKind.BRAIN_NODE,
            "skill.team_checkin_summary.0_2_0": Phase2RefKind.BRAIN_NODE,
            "event.possible_separation.lin.20260513T101400": Phase2RefKind.BRAIN_NODE,
            "measurement.cp2_delay": Phase2RefKind.BRAIN_NODE,
            "mission.ridge_loop_20260513": Phase2RefKind.BRAIN_NODE,
            "route.loop_01": Phase2RefKind.BRAIN_NODE,
            "person.member_lin": Phase2RefKind.BRAIN_NODE,
            "case.phase2.ridge_loop_brain_persisted_replay": Phase2RefKind.BRAIN_NODE,
            "checkpoint.saddle": Phase2RefKind.BRAIN_NODE,
            "fact.weather_rain_segment_2": Phase2RefKind.BRAIN_NODE,
            "https://example.invalid/scout/artifact.json": Phase2RefKind.EXTERNAL,
            "s3://scout-fixtures/team-replay.json": Phase2RefKind.EXTERNAL,
            "skills/scout/team-checkin-summary.yaml": Phase2RefKind.EXTERNAL,
            "artifact": Phase2RefKind.UNKNOWN,
            "option": Phase2RefKind.UNKNOWN,
            "unqualified-ref": Phase2RefKind.UNKNOWN,
            "": Phase2RefKind.UNKNOWN,
        }

        for ref, expected in cases.items():
            with self.subTest(ref=ref):
                self.assertEqual(classify_phase2_ref(ref), expected)


if __name__ == "__main__":
    unittest.main()
