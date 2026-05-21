from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/scout-phase4-5-live-activation-evidence-index.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_index_names_phase45_activation_artifact_chain() -> None:
    source = read_report()

    for token in (
        "Runtime Activation Preflight / runtime 啟動前檢查",
        "Runtime Activation Request / runtime 啟動請求",
        "Actual Runtime Activation / 實際啟動現場 runtime",
        "`runtime_activation_preflight_report`",
        "`runtime_activation_request`",
        "`runtime_activation_loader`",
        "`status=activation_ready`",
        "`status=requested_not_activated`",
        "`status=loaded_not_observing`",
        "`activation_performed=false`",
        "`starts_observation_processing=false`",
    ):
        assert token in source


def test_index_links_live_runtime_reports_and_evidence_dirs() -> None:
    source = read_report()

    for token in (
        "docs/admin/scout-live-runtime-operator-runbook.md",
        "docs/admin/scout-live-runtime-preflight-smoke.md",
        "docs/admin/scout-live-runtime-shadow-smoke.md",
        "docs/admin/scout-live-runtime-live-send-and-cutover.md",
        "docs/admin/scout-runtime-stream-post-cutover-smoke.md",
        "docs/admin/scout-runtime-stream-websocket-post-cutover-smoke.md",
        "docs/admin/scout-runtime-stream-control-post-cutover-smoke.md",
        "docs/admin/scout-live-runtime-post-cutover-soak.md",
        "docs/admin/scout-live-runtime-long-soak-automation.md",
        "docs/admin/scout-live-runtime-guard-update-and-signed-sample.md",
        "docs/admin/scout-provider-control-status-auth-smoke.md",
        "docs/admin/scout-live-runtime-rollback-drill.md",
        "`/data/scout/deployments/live-cutover-20260520T100435Z`",
        "`scout-fusion/pi-runtime:rollback-before-live-20260520T100435Z`",
        "`/data/scout/deployments/runtime-stream-admission-smoke-20260520T101957Z`",
        "`/data/scout/deployments/signed-http-push-sample-20260520T111146Z`",
        "`/data/scout/deployments/packaged-signed-sample-client-20260521T001534Z`",
        "`/data/scout/deployments/runtime-stream-control-auth-smoke-20260521T002445Z`",
        "`/data/scout/deployments/provider-control-status-auth-smoke-20260521T003406Z`",
        "`/data/scout/deployments/live-runtime-soak-overnight-20260520T152647Z`",
    ):
        assert token in source


def test_index_distinguishes_enablement_from_field_activation() -> None:
    source = read_report()

    for token in (
        "live runtime enablement is not field mission activation",
        "`activation_performed=false`",
        "`live_runtime_activation_count=0`",
        "`starts_observation_processing=false`",
        "`requires_runtime_operator_confirmation=true`",
        "not automatic field mission start",
    ):
        assert token in source


def test_index_preserves_safety_and_secret_boundaries() -> None:
    source = read_report()

    for token in (
        "`ingest_surface=safety_api_direct`",
        "`ingest_surface=runtime_stream_http_push`",
        "`ingest_surface=runtime_stream_websocket`",
        "Continuous Apple Watch/mobile streams should use `/runtime/streams/*`",
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no assistant safety mutation",
        "no incident bridge opt-in",
        "no Phase 2 Brain writeback",
        "no ObservedFact write",
        "no HumanReview or review decision mutation",
        "`secret_values_embedded=false`",
        "`raw_payloads_embedded=false`",
        "`token_value_exposed=false`",
        "signed HTTP samples must remain explicitly operator-approved",
    ):
        assert token in source


def test_index_records_remaining_intentional_non_goals() -> None:
    source = read_report()

    for token in (
        "Rollback is documented but not executed on production.",
        "Real Apple Watch/mobile continuous streaming is not yet evidenced.",
        "no physical driver invocation",
        "SOS/SMS/satellite and incident bridge live sends remain disabled",
    ):
        assert token in source
