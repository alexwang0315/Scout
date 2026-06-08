from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Iterable

from phase2_brain_models import ConfidenceLevel, RemoteStatusArtifact


@dataclass(frozen=True)
class MemberStatus:
    member_id: str
    display_name: str
    last_seen_at: str
    latest_checkpoint: str | None = None
    next_checkpoint: str | None = None
    delay_seconds: int = 0
    possible_separation: bool = False


def generate_remote_status_artifact(
    *,
    mission_id: str,
    generated_at: str,
    members: Iterable[MemberStatus],
    stale_after_seconds: int = 600,
    delayed_after_seconds: int = 600,
) -> RemoteStatusArtifact:
    member_list = list(members)
    if not member_list:
        raise ValueError("remote status requires at least one member status")

    freshness_seconds = max(_age_seconds(generated_at, member.last_seen_at) for member in member_list)
    stale_members = [
        member
        for member in member_list
        if _age_seconds(generated_at, member.last_seen_at) > stale_after_seconds
    ]
    delayed_members = [
        member for member in member_list if member.delay_seconds > delayed_after_seconds
    ]
    separation_members = [member for member in member_list if member.possible_separation]

    latest_checkpoint = _most_common_present(member.latest_checkpoint for member in member_list)
    next_checkpoint = _most_common_present(member.next_checkpoint for member in member_list)

    status, safety_level, uncertainty, message = _classify_status(
        member_count=len(member_list),
        freshness_seconds=freshness_seconds,
        stale_members=stale_members,
        delayed_members=delayed_members,
        separation_members=separation_members,
    )

    return RemoteStatusArtifact(
        id=f"remote_status.{_compact_timestamp(generated_at)}",
        mission_id=mission_id,
        generated_at=generated_at,
        freshness_seconds=freshness_seconds,
        status=status,
        team_summary={
            "member_count": len(member_list),
            "freshness_state": "stale" if stale_members else "fresh",
            "stale_member_count": len(stale_members),
            "delayed_member_count": len(delayed_members),
            "possible_separation_member_count": len(separation_members),
            "members": [_summarize_member(generated_at, member, stale_after_seconds) for member in member_list],
        },
        latest_checkpoint=latest_checkpoint,
        next_checkpoint=next_checkpoint,
        safety_level=safety_level,
        uncertainty=uncertainty,
        message=message,
    )


def _classify_status(
    *,
    member_count: int,
    freshness_seconds: int,
    stale_members: list[MemberStatus],
    delayed_members: list[MemberStatus],
    separation_members: list[MemberStatus],
) -> tuple[str, str, ConfidenceLevel, str]:
    if separation_members:
        return (
            "possible_team_separation",
            "L2",
            ConfidenceLevel.LOW,
            (
                f"Possible team separation: {len(separation_members)} of {member_count} "
                "members need attention. Status is uncertain until refreshed."
            ),
        )
    if stale_members:
        return (
            "stale_uncertain",
            "L1",
            ConfidenceLevel.LOW,
            (
                f"Stale data: {len(stale_members)} of {member_count} members have old updates. "
                "Remote status is uncertain until the next check-in."
            ),
        )
    if delayed_members:
        return (
            "delayed_but_moving",
            "L1",
            ConfidenceLevel.MEDIUM,
            f"Delayed but moving: {len(delayed_members)} of {member_count} members are behind plan.",
        )
    return (
        "on_track",
        "L0",
        ConfidenceLevel.HIGH,
        f"Team status is current within {_minutes_label(freshness_seconds)} and on track.",
    )


def _summarize_member(
    generated_at: str,
    member: MemberStatus,
    stale_after_seconds: int,
) -> dict[str, str]:
    age = _age_seconds(generated_at, member.last_seen_at)
    return {
        "member_id": member.member_id,
        "display_name": member.display_name,
        "freshness_state": "stale" if age > stale_after_seconds else "fresh",
        "checkpoint_state": _checkpoint_state(member.latest_checkpoint, member.next_checkpoint),
    }


def _checkpoint_state(latest_checkpoint: str | None, next_checkpoint: str | None) -> str:
    if latest_checkpoint and next_checkpoint:
        return f"{latest_checkpoint} -> {next_checkpoint}"
    if latest_checkpoint:
        return f"at {latest_checkpoint}"
    if next_checkpoint:
        return f"approaching {next_checkpoint}"
    return "unknown"


def _most_common_present(values: Iterable[str | None]) -> str | None:
    present = [value for value in values if value]
    if not present:
        return None
    return Counter(present).most_common(1)[0][0]


def _age_seconds(generated_at: str, observed_at: str) -> int:
    generated = _parse_datetime(generated_at)
    observed = _parse_datetime(observed_at)
    return max(0, int((generated - observed).total_seconds()))


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _compact_timestamp(value: str) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%Y%m%dT%H%M%S")


def _minutes_label(seconds: int) -> str:
    minutes = max(1, ceil(seconds / 60))
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
