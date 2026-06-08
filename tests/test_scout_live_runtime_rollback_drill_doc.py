from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-live-runtime-rollback-drill.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_rollback_drill_records_current_live_and_target_runtime() -> None:
    source = read_report()

    for token in (
        "`scout-pi-runtime-live`",
        "`scout-fusion/pi-runtime:live`",
        "`pi-field-live`",
        "`/home/alexwang0315/scout-fusion-live`",
        "`docker-compose.pi.live.yml`",
        "`scout-pi-runtime`",
        "`scout-fusion/pi-runtime:local`",
        "`pi-field`",
        "`/home/alexwang0315/scout-fusion-runtime`",
        "`docker-compose.pi.yml`",
        "`scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`",
        "`/data/scout/deployments/live-cutover-20260520T100435Z`",
    ):
        assert token in source


def test_rollback_drill_records_command_sequence_and_verification() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-rollback-${ROLLBACK_ID}`",
        "docker compose -f docker-compose.pi.live.yml stop scout-live",
        "docker tag scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z scout-fusion/pi-runtime:local",
        "docker compose -f docker-compose.pi.yml up -d --no-build scout",
        "`runtime_profile=pi-field`",
        "`SCOUT_ENABLE_LIVE_HARDWARE=0`",
        "`SCOUT_ENABLE_AI_INFERENCE=0`",
        "`SCOUT_ENABLE_LOCAL_MODEL=0`",
        "`runtime_stream_transport_enabled` is absent or false",
        "`remote_provider_live_send_enabled` is absent or false",
        "`hardware_provider_control_enabled` is absent or false",
    ):
        assert token in source


def test_rollback_drill_records_restore_and_operator_only_boundary() -> None:
    source = read_report()

    for token in (
        "docker compose -f docker-compose.pi.yml stop scout",
        "docker compose -f docker-compose.pi.live.yml up -d --no-build scout-live",
        "`runtime_profile=pi-field-live`",
        "`read_only=true`",
        "`read_only_surface=true`",
        "`allowed_actions=[read_provider_status]`",
        "Rollback remains an operator-only action.",
    ):
        assert token in source


def test_rollback_drill_explicitly_says_it_was_not_executed() -> None:
    source = read_report()

    for token in (
        "本 slice 沒有實際 rollback",
        "no container stop",
        "no production rollback",
        "no production restore",
        "no new observation",
        "no stream control mutation",
        "no remote provider send",
        "no Telegram send",
        "no SOS send",
        "no hardware control action",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
