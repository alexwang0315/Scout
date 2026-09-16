"""Reference comparison rules for mutable Golden GPX workspaces."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ComparisonStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_RECORDED_DIFF = "PASS_WITH_RECORDED_DIFF"
    YELLOW = "YELLOW"
    FAIL = "FAIL"
    NEEDS_USER_REVIEW = "NEEDS_USER_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ComparisonResult:
    status: ComparisonStatus
    historical: float | int | None
    current: float | int | None
    difference_ratio: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "historical": self.historical,
            "current": self.current,
            "difference_ratio": self.difference_ratio,
            "reason": self.reason,
        }


def compare_reference_value(historical: Any, current: Any) -> ComparisonResult:
    """Compare mutable current output against a same-workspace reference."""
    h = _number(historical)
    c = _number(current)
    if h == 0 and c == 0:
        return ComparisonResult(ComparisonStatus.PASS, h, c, 0.0, "both_empty")
    if h > 0 and c == 0:
        return ComparisonResult(ComparisonStatus.FAIL, h, c, 1.0, "current_lost_reference_value")
    if h == 0 and c > 0:
        return ComparisonResult(ComparisonStatus.NEEDS_USER_REVIEW, h, c, None, "no_reference_denominator")
    ratio = abs(c - h) / h
    if ratio <= 0.5:
        status = ComparisonStatus.PASS if ratio == 0 else ComparisonStatus.PASS_WITH_RECORDED_DIFF
        return ComparisonResult(status, h, c, ratio, "within_tolerance")
    if c > h:
        return ComparisonResult(ComparisonStatus.YELLOW, h, c, ratio, "current_growth_over_tolerance")
    return ComparisonResult(ComparisonStatus.NEEDS_USER_REVIEW, h, c, ratio, "current_drop_over_tolerance")


def workspace_comparison_allowed(historical: dict[str, Any], current: dict[str, Any]) -> bool:
    """Historical is usable only for the same workspace and selected Golden."""
    keys = ("workspace_id", "project_id", "golden_gpx_sha256", "golden_gpx_uri")
    present = [key for key in keys if key in historical or key in current]
    return bool(present) and all(historical.get(key) == current.get(key) for key in present)


def _number(value: Any) -> int | float:
    if value in (None, ""):
        return 0
    return float(value)
