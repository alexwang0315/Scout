from pathlib import Path


DOC_PATH = Path("docs/admin/scout-runtime-canonical-fixture-local-dry-run.md")


def test_canonical_fixture_local_dry_run_doc_records_capability_and_route_scope() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "manual_observation_smoke.canonical.example.json",
        "`locationLatitude`",
        "`batteryLevel`",
        "`locationLatitude(WGS84)`",
        "`batteryLevel(%)`",
        "checkpoint: `cp_01`",
        "`gps`",
        "`imu`",
        "`battery`",
    ):
        assert token in source


def test_canonical_fixture_local_dry_run_doc_keeps_target_read_only() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "target network calls: none",
        "target `/safety/*` mutation: none",
        "local temporary runtime mutation: one fixture POST",
        "local model: not started",
        "hardware provider control: none",
    ):
        assert token in source


def test_canonical_fixture_local_dry_run_doc_links_followup_target_smoke() -> None:
    source = DOC_PATH.read_text(encoding="utf-8")

    for token in (
        "## Follow-Up Target Smoke",
        "`observations_processed` moved from `1` to `2`",
        "`checkpoint_hits` moved from `0` to `1`",
        "checkpoint `cp_01` was hit",
        "canonical-fixture-observation-20260520T035132Z",
    ):
        assert token in source
