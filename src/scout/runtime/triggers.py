"""Trigger evaluators for Scout AI OS MVP runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from scout.schemas.workflow import TriggerSpec, TriggerType


class TriggerEvaluator:
    """Evaluate supported MVP triggers without side effects."""

    def is_satisfied(self, trigger: TriggerSpec, now: datetime) -> bool:
        if trigger.type is TriggerType.MANUAL:
            return True
        if trigger.type is TriggerType.TIME:
            run_at = trigger.config.get("run_at")
            if not run_at:
                return True
            return datetime.fromisoformat(run_at).astimezone(UTC) <= now.astimezone(UTC)
        return False


__all__ = ["TriggerEvaluator"]
