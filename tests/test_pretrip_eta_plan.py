import json
from pathlib import Path

from pretrip_eta_plan import PreTripEtaPlan, build_chilai_day1_eta_plan
from pretrip_models import PreTripPackage


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
CHILAI_PACKAGE = FIXTURE_ROOT / "outputs" / "pretrip_package.json"
PLANNED_ETA = FIXTURE_ROOT / "outputs" / "planned_eta.json"


def _package() -> PreTripPackage:
    return PreTripPackage.model_validate(json.loads(CHILAI_PACKAGE.read_text()))


def test_planned_start_is_gpx_first_point_time_plus_one_hour_in_taipei():
    eta_plan = build_chilai_day1_eta_plan(_package())

    assert eta_plan.assumption.planned_start_time == "2026-05-03T08:55:35+08:00"
    assert eta_plan.assumption.planned_start_source == "route_summary.started_at_plus_offset"
    assert eta_plan.assumption.planned_start_offset_minutes == 60


def test_chilai_day1_target_and_turnback_eta_use_route_guide_timing():
    eta_plan = build_chilai_day1_eta_plan(
        _package(),
        day1_target_node_name="天池山莊",
        turn_back_checkpoint_node_name="雲海保線所",
    )

    assert [estimate.to_node_name for estimate in eta_plan.estimates] == [
        "廬山部落",
        "屯原登山口",
        "雲海保線所",
        "天池山莊",
    ]
    assert eta_plan.assumption.turn_back_checkpoint_eta == "2026-05-03T11:55:35+08:00"
    assert eta_plan.assumption.target_eta == "2026-05-03T15:25:35+08:00"
    assert (
        eta_plan.assumption.return_to_entry_eta_if_turn_back_at_checkpoint
        == "2026-05-03T13:35:35+08:00"
    )
    assert eta_plan.assumption.daylight_policy_status == "not_evaluated_requires_sun_window"


def test_human_stats_are_absent_when_scope_is_not_part_of_this_gpx_fixture():
    eta_plan = build_chilai_day1_eta_plan(_package())

    assert eta_plan.assumption.human_provided_route_stats is None
    assert eta_plan.assumption.team_multiplier_status == "not_derived_no_human_stats"


def test_planned_eta_fixture_matches_deterministic_generation():
    package = _package()
    expected = build_chilai_day1_eta_plan(
        package,
        start_offset_minutes=60,
        day1_target_node_name="天池山莊",
        turn_back_checkpoint_node_name="雲海保線所",
    )

    payload = json.loads(PLANNED_ETA.read_text())

    assert payload == expected.model_dump(mode="json")
    PreTripEtaPlan.model_validate(payload)
