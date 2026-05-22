from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from voice_cue_models import VoiceCue, VoiceCueBoundary, VoiceCueCategory, VoiceCuePriority


VoiceCueSuppressionReason = Literal[
    "spoken_disabled",
    "expired",
    "acknowledged",
    "silenced",
    "rate_limited",
]

PRIORITY_RANK: dict[VoiceCuePriority, int] = {
    "info": 10,
    "caution": 20,
    "warning": 30,
    "urgent": 40,
}


@dataclass(frozen=True)
class SuppressedVoiceCue:
    cue_id: str
    reason: VoiceCueSuppressionReason


@dataclass(frozen=True)
class VoiceCuePolicyDecision:
    selected: VoiceCue | None
    suppressed: list[SuppressedVoiceCue]
    interrupted_cue_id: str | None = None
    boundary: VoiceCueBoundary = field(default_factory=VoiceCueBoundary)


@dataclass
class VoiceCuePolicyState:
    acknowledged_cue_ids: set[str] = field(default_factory=set)
    silence_until: datetime | None = None
    silenced_categories: set[VoiceCueCategory] = field(default_factory=set)
    played_counts: dict[str, int] = field(default_factory=dict)
    last_played_at_by_dedupe_key: dict[str, datetime] = field(default_factory=dict)


class VoiceCuePolicy:
    def __init__(self, state: VoiceCuePolicyState | None = None):
        self.state = state or VoiceCuePolicyState()

    def acknowledge(self, cue_id: str) -> None:
        self.state.acknowledged_cue_ids.add(cue_id)

    def silence(
        self,
        *,
        until: datetime,
        categories: set[VoiceCueCategory] | None = None,
    ) -> None:
        self.state.silence_until = until
        self.state.silenced_categories = set(categories or [])

    def record_played(self, cue: VoiceCue, *, played_at: datetime | None = None) -> None:
        timestamp = played_at or _utc_now()
        self.state.played_counts[cue.dedupe_key] = self.state.played_counts.get(cue.dedupe_key, 0) + 1
        self.state.last_played_at_by_dedupe_key[cue.dedupe_key] = timestamp

    def choose_next(
        self,
        cues: list[VoiceCue],
        *,
        active_cue: VoiceCue | None = None,
        now: datetime | None = None,
    ) -> VoiceCuePolicyDecision:
        timestamp = now or _utc_now()
        candidates: list[VoiceCue] = []
        suppressed: list[SuppressedVoiceCue] = []
        for cue in cues:
            reason = self._suppression_reason(cue, now=timestamp)
            if reason is None:
                candidates.append(cue)
            else:
                suppressed.append(SuppressedVoiceCue(cue_id=cue.cue_id, reason=reason))

        selected = max(candidates, key=lambda cue: PRIORITY_RANK[cue.priority], default=None)
        interrupted_cue_id = None
        if selected is not None and active_cue is not None:
            if selected.priority == "urgent" and active_cue.priority in {"info", "caution"}:
                interrupted_cue_id = active_cue.cue_id

        return VoiceCuePolicyDecision(
            selected=selected,
            suppressed=suppressed,
            interrupted_cue_id=interrupted_cue_id,
        )

    def _suppression_reason(
        self,
        cue: VoiceCue,
        *,
        now: datetime,
    ) -> VoiceCueSuppressionReason | None:
        if not cue.spoken_allowed:
            return "spoken_disabled"
        if cue.expires_at is not None and _parse_iso(cue.expires_at) <= now:
            return "expired"
        if cue.require_ack and cue.cue_id in self.state.acknowledged_cue_ids:
            return "acknowledged"
        if self._is_silenced(cue, now=now):
            return "silenced"
        if self._is_rate_limited(cue, now=now):
            return "rate_limited"
        return None

    def _is_silenced(self, cue: VoiceCue, *, now: datetime) -> bool:
        if cue.priority == "urgent":
            return False
        if self.state.silence_until is None or self.state.silence_until <= now:
            return False
        return not self.state.silenced_categories or cue.category in self.state.silenced_categories

    def _is_rate_limited(self, cue: VoiceCue, *, now: datetime) -> bool:
        if cue.priority in {"warning", "urgent"}:
            return False
        max_repeats = cue.repeat_policy.max_repeats
        played_count = self.state.played_counts.get(cue.dedupe_key, 0)
        if max_repeats is not None and played_count >= max_repeats:
            return True
        last_played_at = self.state.last_played_at_by_dedupe_key.get(cue.dedupe_key)
        if last_played_at is None:
            return False
        elapsed_seconds = (now - last_played_at).total_seconds()
        return elapsed_seconds < cue.repeat_policy.min_interval_seconds


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
