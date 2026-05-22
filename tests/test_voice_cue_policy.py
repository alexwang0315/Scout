from __future__ import annotations

from datetime import datetime, timedelta, timezone

from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy
from voice_cue_policy import VoiceCuePolicy


NOW = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)


def test_policy_orders_by_priority() -> None:
    policy = VoiceCuePolicy()
    info = _cue("voice_cue.info", "info", "device", "電量正常。")
    warning = _cue("voice_cue.warning", "warning", "weather", "天氣正在轉差。")
    caution = _cue("voice_cue.caution", "caution", "route", "前方路徑不明。")

    decision = policy.choose_next([info, warning, caution], now=NOW)

    assert decision.selected == warning
    assert decision.boundary.remote_outbound_allowed is False
    assert decision.boundary.hardware_control_allowed is False


def test_policy_rate_limits_low_priority_duplicate_cues() -> None:
    policy = VoiceCuePolicy()
    cue = _cue(
        "voice_cue.info",
        "info",
        "device",
        "電量正常。",
        repeat_policy=VoiceCueRepeatPolicy(dedupe_key="device.battery.ok", min_interval_seconds=300),
    )

    policy.record_played(cue, played_at=NOW)
    decision = policy.choose_next([cue], now=NOW + timedelta(seconds=60))

    assert decision.selected is None
    assert [(item.cue_id, item.reason) for item in decision.suppressed] == [
        ("voice_cue.info", "rate_limited")
    ]


def test_policy_silence_suppresses_non_urgent_but_urgent_can_interrupt() -> None:
    policy = VoiceCuePolicy()
    policy.silence(until=NOW + timedelta(minutes=10))
    info = _cue("voice_cue.info", "info", "device", "電量正常。")
    urgent = _cue("voice_cue.urgent", "urgent", "route", "立即停下，前方路線風險升高。")
    active = _cue("voice_cue.active", "info", "team", "隊友狀態正常。")

    decision = policy.choose_next([info, urgent], active_cue=active, now=NOW)

    assert decision.selected == urgent
    assert decision.interrupted_cue_id == active.cue_id
    assert [(item.cue_id, item.reason) for item in decision.suppressed] == [
        ("voice_cue.info", "silenced")
    ]
    assert decision.boundary.remote_outbound_allowed is False


def test_policy_acknowledge_and_expiry_suppress_cues() -> None:
    policy = VoiceCuePolicy()
    ack = _cue("voice_cue.ack", "warning", "route", "需要確認路線。", require_ack=True)
    expired = _cue(
        "voice_cue.expired",
        "caution",
        "weather",
        "十分鐘前的天氣提醒。",
        expires_at="2026-05-21T09:59:00Z",
    )
    policy.acknowledge(ack.cue_id)

    decision = policy.choose_next([ack, expired], now=NOW)

    assert decision.selected is None
    assert [(item.cue_id, item.reason) for item in decision.suppressed] == [
        ("voice_cue.ack", "acknowledged"),
        ("voice_cue.expired", "expired"),
    ]


def _cue(
    cue_id: str,
    priority: str,
    category: str,
    text_zh: str,
    *,
    repeat_policy: VoiceCueRepeatPolicy | None = None,
    require_ack: bool = False,
    expires_at: str | None = None,
) -> VoiceCue:
    return VoiceCue(
        cue_id=cue_id,
        priority=priority,
        category=category,
        text_zh=text_zh,
        confidence=0.9,
        repeat_policy=repeat_policy or VoiceCueRepeatPolicy(max_repeats=None),
        require_ack=require_ack,
        expires_at=expires_at,
    )
