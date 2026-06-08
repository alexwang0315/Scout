from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-runtime-ingest-surface-smoke.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_ingest_surface_smoke_records_stream_and_direct_surfaces() -> None:
    source = read_report()

    for token in (
        "`/data/scout/deployments/live-ingest-surface-20260521T004406Z`",
        "`/data/scout/deployments/ingest-surface-smoke-20260521T004438Z`",
        "`artifact_kind=scout_runtime_ingest_surface_smoke`",
        "`status=passed`",
        "`repo_commit=b95c3353`",
        "`runtime_profile=pi-field-live`",
        "`stream_response_ingest_surface=runtime_stream_http_push`",
        "`stream_response_transport_surface=http_push`",
        "`direct_ingest_surface=safety_api_direct`",
        "`direct_admission_transport=http_push`",
        "`direct_admission_status=admitted_not_forwarded`",
        "`stream_observations_accepted=1`",
        "`direct_observations_accepted=1`",
    ):
        assert token in source


def test_ingest_surface_smoke_records_boundaries() -> None:
    source = read_report()

    for token in (
        "`incident_file_delta=0`",
        "`stream_control_status=observing`",
        "`secret_values_embedded=false`",
        "`raw_payloads_embedded=false`",
        "`stream_control_mutation_performed=false`",
        "`remote_provider_send_performed=false`",
        "`hardware_control_performed=false`",
        "`phase2_writeback_performed=false`",
        "no Telegram send",
        "no SOS send",
        "no SMS send",
        "no satellite send",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
    ):
        assert token in source
