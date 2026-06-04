from __future__ import annotations

from pathlib import Path


UI_PATH = Path("docs/admin/scout-apple-client-bare-ui.html")


def read_ui() -> str:
    return UI_PATH.read_text(encoding="utf-8")


def test_bare_ui_defines_apple_client_envelope_and_transport() -> None:
    source = read_ui()

    for token in (
        "Scout Apple Client Bare UI",
        "http://scout.local:9099/clients/apple/observations",
        "scout_apple_client_observation_envelope",
        "apple_client_observation_envelope.v0",
        "runtime_source.apple_watch.v0",
        "device_id_scoped_token_hmac_signature",
        "runtime:observation:write",
        "hmac_sha256",
        "payload_sha256",
        "sequence_no",
        "queued_disconnected",
        "latest_point_retained",
    ):
        assert token in source


def test_bare_ui_keeps_v0_evidence_only_and_safety_bridge_off() -> None:
    source = read_ui()

    for token in (
        "Evidence-only; safety bridge off.",
        "evidence_only: true",
        "medical_diagnosis: false",
        "phase1_runtime_safety_truth: false",
        "safety_api_called: false",
        "assistant_safety_mutation_allowed: false",
        "raw_health_payload_shared: false",
        "raw_track_shared_to_status: false",
    ):
        assert token in source

    assert "POST /safety" not in source
    assert "fetch(\"/safety" not in source


def test_bare_ui_is_standalone_without_external_assets() -> None:
    source = read_ui()

    assert "<script src=" not in source
    assert "<link rel=\"stylesheet\"" not in source
    assert "https://cdn" not in source
