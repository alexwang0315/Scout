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


def test_phase46_spec_defines_apple_scout_client_v0_first_step() -> None:
    source = read_spec()

    for token in (
        "The first Apple platform milestone is an Apple Scout Client, not a safety",
        "Apple Watch is the primary live sensor collector.",
        "iPhone is the Scout network bridge, signer, queue owner",
        "`POST /clients/apple/observations`",
        "`GET /clients/apple/status`",
        "HealthKit live workout data",
        "Core Motion data",
        "Barometer data",
        "Location route data",
        "WatchConnectivity",
        "The Watch should send compact frames to the iPhone companion",
        "The iPhone companion owns Scout-facing behavior",
        "`device_id_scoped_token_hmac_signature`",
        "enforces the 10 Hz client-side send cap",
        "retains the latest point after retry exhaustion",
        "Scout response summaries may include accepted/rejected counts",
    ):
        assert token in source


def test_phase46_spec_keeps_apple_client_v0_evidence_only_before_safety_bridge() -> None:
    source = read_spec()

    for token in (
        "Scout receives the stream as an evidence-only Apple client observation channel",
        "The endpoint pair is intentionally separate from `/safety/*`.",
        "Safety 通報、SOS、SMS、衛星或",
        "incident bridge 都是之後的互通層，不在 v0 自動啟用",
        "It must not own Scout credentials, send `/safety/*` requests",
        "Operator pause/resume from Scout remains server-side admission state",
        '"evidence_only": true',
        '"phase1_runtime_safety_truth": false',
        '"safety_api_called": false',
        '"assistant_safety_mutation_allowed": false',
        "They must not echo raw",
        "health payloads, raw tracks, tokens, signatures, or HMAC secrets",
    ):
        assert token in source


def test_phase46_spec_places_health_exports_in_admin_batch_not_live_stream() -> None:
    source = read_spec()

    for token in (
        "Health Auto Export is an admin/pre-trip batch source.",
        "prepares Apple Health",
        "metrics, workouts, and GPX route evidence",
        "they are not the live motion stream for Phase 4.6",
        "The first live Scout endpoint should therefore target SensorLog/Sensor Logger",
        "`POST /clients/apple/sensorlog/observations`",
        "`GET /clients/apple/sensorlog/status`",
    ):
        assert token in source


def test_phase46_spec_defines_sensorlog_and_sensor_logger_live_shapes() -> None:
    source = read_spec()

    for token in (
        "SensorLog snapshot rows",
        "`loggingTime`",
        "`heartRateBPM`",
        "`accelerometerAccelerationX`",
        "`motionQuaternionW`",
        "`pedometerDistance`",
        "Sensor Logger event rows",
        "`sensor` discriminator",
        "`Gyroscope`",
        "`WatchLocation`",
        "`WristMotion`",
        "need a small live frame assembler",
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
