from __future__ import annotations

from pathlib import Path


SPEC_PATH = Path("docs/specs/phase-4-6-real-device-continuous-stream.md")


def read_spec() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def test_phase46_spec_defines_real_device_stream_semantics() -> None:
    source = read_spec()

    for token in (
        "Phase 4.6 moves Scout from signed sample stream admission to real Apple Watch",
        "`RuntimeStreamDeviceIdentity`",
        "`device_id` 只能當識別",
        "`device_id_scoped_token_hmac_signature`",
        "sequence numbers must be monotonic",
        "The maximum accepted cadence is 10 Hz",
        "disconnected submissions are recorded as `queued_disconnected`",
        "status becomes `latest_point_retained`",
        "`pause` 不是遙控手錶停止感測",
    ):
        assert token in source


def test_phase46_spec_preserves_phase45_live_safety_boundary() -> None:
    source = read_spec()

    for token in (
        "no automatic SOS send",
        "no SMS send",
        "no satellite send",
        "no incident bridge opt-in or remote notification send",
        "no assistant safety mutation",
        "no Phase 2 Brain writeback",
        "Secret values and raw payloads must not be written",
        "All live action requires an evidence directory",
    ):
        assert token in source
