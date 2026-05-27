from __future__ import annotations

import hashlib
from typing import Any

from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy


def voice_cue_from_energy_projection(
    projection: dict[str, Any],
) -> VoiceCue:
    checkpoint = projection.get("possible_depletion_checkpoint_name")
    if checkpoint:
        text_zh = f"體能儲備提示：到 {checkpoint} 前，建議預留休息與折返檢查。"
        priority = "caution"
    else:
        text_zh = "體能儲備提示：目前只作為行前配速參考，不是安全狀態。"
        priority = "info"
    return VoiceCue(
        cue_id=f"voice_cue.energy_reserve.{_safe_token(checkpoint or projection.get('project_id', 'projection'))}",
        priority=priority,
        category="body",
        text_zh=text_zh,
        source_event_refs=[
            projection.get("source_path", "pretrip_energy_reserve_projection"),
            projection.get("energy_baseline_source_path", "scout_energy_reserve_baseline"),
        ],
        source_kind="deterministic_fact",
        confidence=0.68 if checkpoint else 0.5,
        repeat_policy=VoiceCueRepeatPolicy(
            dedupe_key=f"energy_reserve:{checkpoint or 'normal'}",
            min_interval_seconds=1800,
            max_repeats=1,
        ),
        require_ack=bool(checkpoint),
        spoken_allowed=True,
    )


def _safe_token(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    sanitized = "".join(
        char if char.isascii() and (char.isalnum() or char in "_.:-") else "_"
        for char in value
    )
    sanitized = sanitized.strip("_.:-")[:64] or "checkpoint"
    return f"{sanitized}.{digest}"
