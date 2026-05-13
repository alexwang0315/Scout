import unittest

import phase2_case_replay_integration
import phase2_option_replay
import phase2_remote_status_replay
import phase2_team_replay_store
from phase2_demo_defaults import (
    DEFAULT_DELAY_MEASUREMENT_REF,
    DEFAULT_MISSION_REF,
    DEFAULT_OPTION_SET_REF,
    DEFAULT_POLICY_PATH,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_REPLAY_OPTION_SET_REF,
    DEFAULT_ROUTE_REF,
    DEFAULT_SEPARATION_EVENT_REF,
    DEFAULT_SKILL_RUN_REFS,
    DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
    FOREST_DELAY_MEASUREMENT_REF,
    FOREST_MISSION_REF,
    FOREST_REMOTE_STATUS_REF,
    FOREST_ROUTE_REF,
    FOREST_SKILL_RUN_REFS,
    FOREST_TEAM_REPLAY_FIXTURE_PATH,
)


class Phase2DemoDefaultsTests(unittest.TestCase):
    def test_owned_modules_reexport_shared_ridge_loop_defaults(self):
        self.assertEqual(
            phase2_team_replay_store.DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
            DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
        )
        self.assertEqual(
            phase2_remote_status_replay.TEAM_REPLAY_FIXTURE_PATH,
            DEFAULT_TEAM_REPLAY_FIXTURE_PATH,
        )

        self.assertEqual(
            phase2_case_replay_integration.DEFAULT_REMOTE_STATUS_REF,
            DEFAULT_REMOTE_STATUS_REF,
        )
        self.assertEqual(phase2_case_replay_integration.DEFAULT_OPTION_SET_REF, DEFAULT_OPTION_SET_REF)
        self.assertEqual(
            phase2_case_replay_integration.DEFAULT_SEPARATION_EVENT_REF,
            DEFAULT_SEPARATION_EVENT_REF,
        )
        self.assertEqual(
            phase2_case_replay_integration.DEFAULT_SKILL_RUN_REFS,
            DEFAULT_SKILL_RUN_REFS,
        )

        self.assertEqual(phase2_option_replay.DEFAULT_POLICY_PATH, DEFAULT_POLICY_PATH)
        self.assertEqual(
            phase2_option_replay.DEFAULT_FIXTURE_OPTION_SET_ID,
            DEFAULT_OPTION_SET_REF,
        )
        self.assertEqual(
            phase2_option_replay.DEFAULT_REPLAY_OPTION_SET_ID,
            DEFAULT_REPLAY_OPTION_SET_REF,
        )

    def test_shared_defaults_preserve_current_ridge_loop_refs(self):
        self.assertEqual(DEFAULT_MISSION_REF, "mission.ridge_loop_20260513")
        self.assertEqual(DEFAULT_ROUTE_REF, "route.ridge_loop_north")
        self.assertEqual(
            DEFAULT_REMOTE_STATUS_REF,
            "remote_status.ridge_loop_20260513T100800",
        )
        self.assertEqual(
            DEFAULT_OPTION_SET_REF,
            "options.ridge_loop_hold_or_regroup.20260513T101520",
        )
        self.assertEqual(
            DEFAULT_SEPARATION_EVENT_REF,
            "event.possible_separation.lin.20260513T101400",
        )
        self.assertEqual(
            DEFAULT_DELAY_MEASUREMENT_REF,
            "measurement.saddle_delay.team.20260513T095500",
        )
        self.assertEqual(
            DEFAULT_SKILL_RUN_REFS,
            (
                "skill_run.team_checkin_summary.20260513T100800",
                "skill_run.decision_options.20260513T101500",
            ),
        )
        self.assertEqual(
            DEFAULT_TEAM_REPLAY_FIXTURE_PATH.name,
            "ridge_three_person_team_replay.json",
        )
        self.assertEqual(DEFAULT_POLICY_PATH.name, "same_day_loop.json")

    def test_shared_defaults_include_second_fixture_refs_without_changing_demo_default(self):
        self.assertEqual(
            FOREST_TEAM_REPLAY_FIXTURE_PATH.name,
            "forest_traverse_two_person_team_replay.json",
        )
        self.assertEqual(FOREST_MISSION_REF, "mission.forest_traverse_20260513")
        self.assertEqual(FOREST_ROUTE_REF, "route.forest_traverse_south")
        self.assertEqual(
            FOREST_REMOTE_STATUS_REF,
            "remote_status.forest_traverse_20260513T082000",
        )
        self.assertEqual(
            FOREST_DELAY_MEASUREMENT_REF,
            "measurement.cedar_bridge_delay.team.20260513T081800",
        )
        self.assertEqual(
            FOREST_SKILL_RUN_REFS,
            ("skill_run.team_checkin_summary.forest_20260513T082000",),
        )
        self.assertNotEqual(DEFAULT_TEAM_REPLAY_FIXTURE_PATH, FOREST_TEAM_REPLAY_FIXTURE_PATH)


if __name__ == "__main__":
    unittest.main()
