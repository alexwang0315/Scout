from pathlib import Path


PLAN_PATH = Path("docs/specs/hardware-port-plan.md")


def test_hardware_port_plan_records_fixture_observation_smoke_status() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Fixture Observation Smoke Status",
        "operator-approved fixture `POST /safety/observations`",
        "moved `observations_processed` from `0` to `1`",
        "kept `safety_level=L0_NORMAL`",
        "produced no new incident files",
    ):
        assert token in source


def test_hardware_port_plan_next_slice_is_canonical_fixture_before_target_mutation() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "upgrade the hardware smoke fixture to canonical SensorLog keys",
        "route-aware local dry-run",
        "before any new target mutation",
        "stabilize Phase 4 dirty worktree groups",
    ):
        assert token in source
