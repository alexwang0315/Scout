from pathlib import Path


DOC_PATH = Path("docs/admin/scout-runtime-canonical-fixture-target-smoke.md")


def test_canonical_fixture_target_smoke_records_route_aware_target_result() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "Smoke id: `20260520T035132Z`",
        "`POST /safety/observations`",
        "response status: `accepted`",
        "`observations_processed`: `1 -> 2`",
        "`checkpoint_hits`: `0 -> 1`",
        "checkpoint ids: `cp_01`",
        "`safety_level`: `L0_NORMAL -> L0_NORMAL`",
        "no new incident files",
        "No rollback was required.",
    ):
        assert token in source


def test_canonical_fixture_target_smoke_records_available_capabilities() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "`gps`",
        "`gps_horizontal_accuracy`",
        "`imu`",
        "`battery`",
        "`pedometer_distance`",
        "`pedometer_steps`",
    ):
        assert token in source


def test_canonical_fixture_target_smoke_preserves_boundaries() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "`SCOUT_ENABLE_LIVE_HARDWARE=0`",
        "`SCOUT_ENABLE_AI_INFERENCE=0`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`SCOUT_EVENT_BUS=none`",
        "no outbound/SOS/SMS/satellite send",
        "no local model request",
        "no live hardware provider control",
        "`scout-ollama` remained present",
    ):
        assert token in source
