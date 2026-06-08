from pathlib import Path


REVIEW_PATH = Path("docs/admin/runtime-stream-live-provider-boundary-review.md")


def test_runtime_stream_live_provider_review_blocks_live_mounts_by_default() -> None:
    source = REVIEW_PATH.read_text(encoding="utf-8")

    for token in (
        "Do not mount runtime stream transport routes",
        "Do not enable remote provider live send by default",
        "Do not let assistant responses pause, resume, drain, or end runtime streams",
        "Do not let assistant responses enqueue, approve, or send provider payloads",
        "Do not call `/safety/*` mutation from runtime stream smoke",
    ):
        assert token in source


def test_runtime_stream_live_provider_review_names_required_gates() -> None:
    source = REVIEW_PATH.read_text(encoding="utf-8")

    for token in (
        "Operator policy",
        "Authentication and replay-protection",
        "Backpressure/drop behavior",
        "Manual provider-send authorization",
        "Rollback plan",
        "read-only stream status surface",
    ):
        assert token in source


def test_runtime_stream_live_provider_review_records_status_surface_slice() -> None:
    source = REVIEW_PATH.read_text(encoding="utf-8")

    for token in (
        "## Read-Only Status Surface",
        "runtime_stream_status_surface.py",
        "tests/test_runtime_stream_status_surface.py",
        "tests/test_server_runtime_stream_status_mount.py",
        "GET /runtime/streams/status-read-only",
        "SCOUT_RUNTIME_STREAM_STATUS_ENABLED=1",
        "default server does not mount this route",
        "independent from signed admission startup",
        "RuntimeStreamPolicyManifest",
        "RuntimeStreamTelemetrySnapshot",
        "RuntimeStreamControlSnapshot",
        "RuntimeRemoteProviderPolicyContract",
        "transport_routes_mounted=false",
        "observation_ingest_allowed=false",
        "stream_control_mutation_allowed=false",
        "live_provider_send_allowed=false",
        "safety_mutation_allowed=false",
        "phase2_writeback_allowed=false",
        "raw_payloads_embedded=false",
        "/runtime/streams/http-push/observations",
        "WebSocket ingest",
        "remote provider send route",
    ):
        assert token in source
