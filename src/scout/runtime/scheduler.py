"""Scheduler tick wrapper for Scout AI OS MVP."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime

from scout.runtime.executor import RuntimeExecutor, RuntimeTickResult


class Scheduler:
    """Small scheduler facade for manual Phase 4 ticks."""

    def __init__(self, executor: RuntimeExecutor) -> None:
        self._executor = executor

    def tick(self, now: datetime | None = None) -> RuntimeTickResult:
        return self._executor.tick(now)


class BackgroundScheduler:
    """Optional async loop for server-managed scheduler ticks."""

    def __init__(self, scheduler: Scheduler, *, interval_seconds: float = 60.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("background scheduler interval must be positive")
        self._scheduler = scheduler
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.tick_count = 0
        self.last_result: RuntimeTickResult | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="scout-ai-os-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "running": self.running,
            "interval_seconds": self._interval_seconds,
            "tick_count": self.tick_count,
            "last_error": self.last_error,
            "last_result": (
                {
                    "checked": self.last_result.checked,
                    "ran": self.last_result.ran,
                    "paused": self.last_result.paused,
                    "failed": self.last_result.failed,
                }
                if self.last_result
                else None
            ),
        }

    async def _run(self) -> None:
        while self._running:
            try:
                self.last_result = self._scheduler.tick()
                self.tick_count += 1
                self.last_error = None
            except Exception as exc:  # pragma: no cover - defensive loop guard
                self.last_error = str(exc)
            await asyncio.sleep(self._interval_seconds)


__all__ = ["BackgroundScheduler", "Scheduler"]
