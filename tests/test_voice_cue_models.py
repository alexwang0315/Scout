from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice_cue_models import VoiceCue


def test_voice_cue_defaults_keep_safety_and_outbound_boundaries_closed() -> None:
    cue = VoiceCue(
        cue_id="voice_cue.route.000001",
        priority="warning",
        category="route",
        text_zh="偏離路線，請停下確認方向。",
        source_event_refs=["debug_event.route_progress.000010"],
        confidence=0.92,
        require_ack=True,
    )

    assert cue.boundary.local_awareness_channel is True
    assert cue.boundary.safety_decision_change_allowed is False
    assert cue.boundary.phase1_safety_runtime_mutation_allowed is False
    assert cue.boundary.remote_outbound_allowed is False
    assert cue.boundary.hardware_control_allowed is False
    assert cue.boundary.sos_trigger_allowed is False
    assert cue.boundary.sms_send_allowed is False
    assert cue.boundary.satellite_send_allowed is False
    assert cue.boundary.endpoint_calls == []
    assert cue.dedupe_key == "route:偏離路線，請停下確認方向。"


def test_voice_cue_accepts_read_only_model_interpretation_label() -> None:
    cue = VoiceCue(
        cue_id="voice_cue.body.000001",
        priority="caution",
        category="body",
        text_zh="模型解讀：你的移動速度正在下降，請自行確認身體狀況。",
        source_kind="read_only_model_interpretation",
        confidence=0.6,
    )

    assert cue.source_kind == "read_only_model_interpretation"
    assert cue.boundary.model_interpretation_must_be_read_only is True


def test_voice_cue_rejects_boundary_mutation() -> None:
    payload = {
        "cue_id": "voice_cue.device.000001",
        "priority": "info",
        "category": "device",
        "text_zh": "電量正常。",
        "confidence": 1.0,
        "boundary": {"remote_outbound_allowed": True},
    }

    with pytest.raises(ValidationError) as exc_info:
        VoiceCue.model_validate(payload)

    assert "remote_outbound_allowed" in str(exc_info.value)


def test_voice_cue_rejects_endpoint_calls_and_bad_expiry() -> None:
    with pytest.raises(ValidationError, match="runtime endpoints"):
        VoiceCue(
            cue_id="voice_cue.team.000001",
            priority="info",
            category="team",
            text_zh="隊友狀態正常。",
            confidence=0.8,
            boundary={"endpoint_calls": ["/safety/observations"]},
        )

    with pytest.raises(ValidationError, match="expires_at"):
        VoiceCue(
            cue_id="voice_cue.weather.000001",
            priority="caution",
            category="weather",
            text_zh="午後降雨機率提高。",
            confidence=0.7,
            expires_at="not-a-date",
        )
