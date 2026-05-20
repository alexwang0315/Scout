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
