from pathlib import Path


DOC_PATH = Path("docs/admin/scout-runtime-fixture-observation-smoke.md")


def test_fixture_observation_smoke_records_runtime_mutation_result() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "Smoke id: `20260520T033354Z`",
        "`POST /safety/observations`",
        "response status: `accepted`",
        "observations accepted: `1`",
        "`observations_processed`: `0 -> 1`",
        "`safety_level`: `L0_NORMAL -> L0_NORMAL`",
        "no new incident files",
        "No rollback was required.",
    ):
        assert token in source


def test_fixture_observation_smoke_preserves_runtime_boundaries() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "`SCOUT_ENABLE_LIVE_HARDWARE=0`",
        "`SCOUT_ENABLE_AI_INFERENCE=0`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`SCOUT_EVENT_BUS=none`",
        "no outbound/SOS/SMS/satellite send",
        "no local model request",
        "no live hardware provider control",
        "no Phase 2 Brain or HumanReview write",
    ):
        assert token in source


def test_fixture_observation_smoke_names_canonical_fixture_followup() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "`locationLatitude(WGS84)`",
        "`batteryLevel(%)`",
        "`locationLatitude`",
        "`batteryLevel`",
        "runtime plumbing proof",
        "canonical SensorLog fixture",
    ):
        assert token in source
