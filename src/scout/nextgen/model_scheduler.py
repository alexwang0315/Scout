"""Bounded priority scheduler for model inference work."""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any


class InferenceSchedulerError(RuntimeError):
    pass


class InferenceSchedulerTimeout(InferenceSchedulerError):
    pass


class InferenceSchedulerBackpressure(InferenceSchedulerError):
    pass


class InferenceSchedulerClosed(InferenceSchedulerError):
    pass


class InferenceSchedulerCancelled(InferenceSchedulerError):
    pass


@dataclass(frozen=True)
class InferenceSchedulerSnapshot:
    max_concurrency: int
    queue_depth: int
    active_count: int
    completed_count: int
    rejected_count: int
    timed_out_count: int
    max_observed_concurrency: int


@dataclass(order=True)
class _WorkItem:
    priority: int
    sequence: int
    future: Future[Any] = field(compare=False)
    operation: Callable[[], Any] | None = field(compare=False)
    cancellation_event: threading.Event = field(compare=False)
    deadline_monotonic: float | None = field(compare=False)


class BoundedInferenceScheduler:
    """Execute queued inference calls with bounded concurrency and backpressure."""

    def __init__(
        self,
        *,
        max_concurrency: int,
        max_queue_size: int = 32,
        name: str = "scout-model",
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self.max_concurrency = max_concurrency
        self._queue: queue.PriorityQueue[_WorkItem] = queue.PriorityQueue(
            maxsize=max_queue_size
        )
        self._sequence = itertools.count()
        self._closed = False
        self._state_lock = threading.Lock()
        self._active_count = 0
        self._completed_count = 0
        self._rejected_count = 0
        self._timed_out_count = 0
        self._max_observed_concurrency = 0
        self._workers = tuple(
            threading.Thread(
                target=self._worker,
                name=f"{name}-{index}",
                daemon=True,
            )
            for index in range(max_concurrency)
        )
        for worker in self._workers:
            worker.start()

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        priority: int,
        timeout_seconds: float | None,
        cancellation_event: threading.Event,
    ) -> Any:
        with self._state_lock:
            if self._closed:
                raise InferenceSchedulerClosed("model inference scheduler is closed")
        if cancellation_event.is_set():
            raise InferenceSchedulerCancelled(
                "model inference was cancelled before it was queued"
            )
        deadline = (
            time.monotonic() + timeout_seconds
            if timeout_seconds is not None
            else None
        )
        future: Future[Any] = Future()
        item = _WorkItem(
            priority=priority,
            sequence=next(self._sequence),
            future=future,
            operation=operation,
            cancellation_event=cancellation_event,
            deadline_monotonic=deadline,
        )
        try:
            self._queue.put_nowait(item)
        except queue.Full as exc:
            with self._state_lock:
                self._rejected_count += 1
            raise InferenceSchedulerBackpressure(
                "model inference queue is full"
            ) from exc
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            cancellation_event.set()
            future.cancel()
            with self._state_lock:
                self._timed_out_count += 1
            raise InferenceSchedulerTimeout(
                "model inference exceeded its queue and execution timeout"
            ) from exc

    def snapshot(self) -> InferenceSchedulerSnapshot:
        with self._state_lock:
            return InferenceSchedulerSnapshot(
                max_concurrency=self.max_concurrency,
                queue_depth=self._queue.qsize(),
                active_count=self._active_count,
                completed_count=self._completed_count,
                rejected_count=self._rejected_count,
                timed_out_count=self._timed_out_count,
                max_observed_concurrency=self._max_observed_concurrency,
            )

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        for _ in self._workers:
            sentinel = _WorkItem(
                priority=10_000,
                sequence=next(self._sequence),
                future=Future(),
                operation=None,
                cancellation_event=threading.Event(),
                deadline_monotonic=None,
            )
            self._queue.put(sentinel)
        for worker in self._workers:
            worker.join(timeout=2)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item.operation is None:
                    return
                if item.future.cancelled():
                    continue
                if item.cancellation_event.is_set():
                    if not item.future.done():
                        item.future.set_exception(
                            InferenceSchedulerCancelled(
                                "model inference was cancelled before execution"
                            )
                        )
                    continue
                if (
                    item.deadline_monotonic is not None
                    and time.monotonic() >= item.deadline_monotonic
                ):
                    with self._state_lock:
                        self._timed_out_count += 1
                    if not item.future.done():
                        item.future.set_exception(
                            InferenceSchedulerTimeout(
                                "model inference expired before execution"
                            )
                        )
                    continue
                with self._state_lock:
                    self._active_count += 1
                    self._max_observed_concurrency = max(
                        self._max_observed_concurrency,
                        self._active_count,
                    )
                try:
                    result = item.operation()
                except BaseException as exc:
                    if not item.future.done():
                        item.future.set_exception(exc)
                else:
                    if not item.future.done():
                        item.future.set_result(result)
                finally:
                    with self._state_lock:
                        self._active_count -= 1
                        self._completed_count += 1
            finally:
                self._queue.task_done()


__all__ = [
    "BoundedInferenceScheduler",
    "InferenceSchedulerBackpressure",
    "InferenceSchedulerCancelled",
    "InferenceSchedulerClosed",
    "InferenceSchedulerError",
    "InferenceSchedulerSnapshot",
    "InferenceSchedulerTimeout",
]
