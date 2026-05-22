from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/admin/scout-phase4-6-real-device-stream-slices.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_phase46_real_device_stream_slices_doc_records_b_c_d_tools() -> None:
    source = read_doc()

    for token in (
        "`runtime_stream_real_device_harness.py`",
        "`real-device-continuous-stream-summary.json`",
        "`runtime_stream_real_device_policy_drill.py`",
        "`real-device-policy-drill-summary.json`",
        "`runtime_stream_real_device_control_drill.py`",
        "`real-device-control-drill-summary.json`",
        "final status restored to `observing`",
        "tooling status: `closed`",
        "live run status: `deferred_to_next_operator_approved_milestone`",
        "`docs/admin/scout-phase4-6-tooling-milestone-closeout.md`",
    ):
        assert token in source


def test_phase46_real_device_stream_slices_doc_preserves_safety_boundary() -> None:
    source = read_doc()

    for token in (
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no incident bridge enablement",
        "no Phase 2 Brain writeback",
        "不是遙控 Apple Watch 或手機停止感測",
        "operator token is used only in Authorization header and is not serialized",
        "不能當作\noperator approval",
        "`--operator-approve-live-send`",
        "`--operator-approve-control-drill`",
    ):
        assert token in source
