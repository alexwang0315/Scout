from __future__ import annotations

from pathlib import Path


SPEC_PATH = Path("docs/specs/phase-4-5-departure-runtime-handoff.md")


def read_spec() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def test_phase45_spec_names_direct_safety_api_ingest_surface() -> None:
    source = read_spec()

    for token in (
        "direct signed `/safety/observations` responses include",
        "`ingest_surface=safety_api_direct`",
        "`admission_transport=<envelope transport>`",
        "distinguish the signed envelope transport from the API surface",
    ):
        assert token in source


def test_phase45_spec_names_runtime_stream_ingest_surfaces() -> None:
    source = read_spec()

    for token in (
        "`ingest_surface=runtime_stream_http_push`",
        "`ingest_surface=runtime_stream_websocket`",
        "this transport surface does not enable incident bridge notifications",
        "does not write Phase 2 Brain state",
    ):
        assert token in source
