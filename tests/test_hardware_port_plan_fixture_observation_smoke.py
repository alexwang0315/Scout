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


def test_hardware_port_plan_fixture_smoke_points_to_canonical_target_smoke() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Canonical Fixture Local Dry Run Status",
        "manual_observation_smoke.canonical.example.json",
        "verified GPS, horizontal accuracy, IMU, battery",
        "target network calls and target `/safety/*` mutation at zero",
        "## Canonical Fixture Target Smoke Status",
        "freeze the Scout machine Step 1 deployment runbook and evidence index",
        "stabilize Phase 4 dirty worktree groups",
    ):
        assert token in source
