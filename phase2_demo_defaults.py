from __future__ import annotations

from pathlib import Path


PHASE2_FIXTURE_ROOT = Path(__file__).parent / "tests" / "fixtures" / "phase2"

DEFAULT_TEAM_REPLAY_FIXTURE_PATH = (
    PHASE2_FIXTURE_ROOT / "team_replay" / "ridge_three_person_team_replay.json"
)
FOREST_TEAM_REPLAY_FIXTURE_PATH = (
    PHASE2_FIXTURE_ROOT / "team_replay" / "forest_traverse_two_person_team_replay.json"
)
DEFAULT_POLICY_PATH = PHASE2_FIXTURE_ROOT / "policies" / "same_day_loop.json"

DEFAULT_MISSION_REF = "mission.ridge_loop_20260513"
DEFAULT_ROUTE_REF = "route.ridge_loop_north"
DEFAULT_REMOTE_STATUS_REF = "remote_status.ridge_loop_20260513T100800"
DEFAULT_OPTION_SET_REF = "options.ridge_loop_hold_or_regroup.20260513T101520"
DEFAULT_REPLAY_OPTION_SET_REF = "options.ridge_loop_option_replay.20260513T101520"
DEFAULT_DELAY_MEASUREMENT_REF = "measurement.saddle_delay.team.20260513T095500"
DEFAULT_SEPARATION_EVENT_REF = "event.possible_separation.lin.20260513T101400"
DEFAULT_SKILL_RUN_REFS = (
    "skill_run.team_checkin_summary.20260513T100800",
    "skill_run.decision_options.20260513T101500",
)

FOREST_MISSION_REF = "mission.forest_traverse_20260513"
FOREST_ROUTE_REF = "route.forest_traverse_south"
FOREST_REMOTE_STATUS_REF = "remote_status.forest_traverse_20260513T082000"
FOREST_DELAY_MEASUREMENT_REF = "measurement.cedar_bridge_delay.team.20260513T081800"
FOREST_SKILL_RUN_REFS = ("skill_run.team_checkin_summary.forest_20260513T082000",)
