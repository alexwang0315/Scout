from pathlib import Path


PLAN_PATH = Path("docs/specs/hardware-port-plan.md")


def test_hardware_port_plan_records_runtime_deployment_takeover() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "## Runtime Deployment Takeover Status",
        "`scout-runtime` service on `scout.local`",
        "`scout-fusion/pi-runtime:rollback-20260520T031746Z`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`SCOUT_EVENT_BUS=none`",
        "verified `/health`, `/runtime/status`, and `/providers/status`",
    ):
        assert token in source


def test_hardware_port_plan_next_slice_requires_operator_fixture_observation() -> None:
    source = PLAN_PATH.read_text(encoding="utf-8")

    assert "operator-approved fixture observation smoke" in source
    assert "no `/safety/*` mutation" in source
