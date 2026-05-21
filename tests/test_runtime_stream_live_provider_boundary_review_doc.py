from __future__ import annotations

from pathlib import Path


REPORT_PATH = Path("docs/admin/runtime-stream-live-provider-boundary-review.md")


def read_report() -> str:
    return REPORT_PATH.read_text(encoding="utf-8")


def test_boundary_review_marks_historical_context_and_points_to_index() -> None:
    source = read_report()

    for token in (
        "Status as of 2026-05-21",
        "historical boundary context",
        "superseded by the Phase 4.5 live activation evidence index",
        "docs/admin/scout-phase4-5-live-activation-evidence-index.md",
        "live `pi-field-live` runtime is now deployed on `scout.local:9099`",
    ):
        assert token in source


def test_boundary_review_lists_validated_live_runtime_evidence() -> None:
    source = read_report()

    for token in (
        "live runtime cutover",
        "signed HTTP push admission",
        "signed WebSocket admission",
        "runtime stream pause/resume/drain controls",
        "runtime stream control operator auth",
        "provider control status operator auth",
        "packaged signed sample client smoke",
        "packaged soak checker smoke",
        "completed overnight read-only soak",
    ):
        assert token in source


def test_boundary_review_preserves_non_goals_after_live_enablement() -> None:
    source = read_report()

    for token in (
        "不代表自動 field mission activation",
        "incident bridge",
        "SOS/SMS/satellite send",
        "assistant safety mutation",
        "硬體 driver",
        "Phase 2 writeback",
        "either satisfied by dedicated evidence or kept as explicit non-goals",
    ):
        assert token in source
