"""Scheduler tick wrapper for Scout AI OS MVP."""

from __future__ import annotations

from datetime import datetime

from scout.runtime.executor import RuntimeExecutor, RuntimeTickResult


class Scheduler:
    """Small scheduler facade for manual Phase 4 ticks."""

    def __init__(self, executor: RuntimeExecutor) -> None:
        self._executor = executor

    def tick(self, now: datetime | None = None) -> RuntimeTickResult:
        return self._executor.tick(now)


__all__ = ["Scheduler"]
