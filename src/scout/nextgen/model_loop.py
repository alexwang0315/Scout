"""A persistent asyncio owner for one resident model and its managed clients."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

_Result = TypeVar('_Result')


class OwnedModelLoop:
    """Keep resident async resources on one loop, including final cancellation."""

    def __init__(self, *, name: str, close_resources: Callable[[], Awaitable[None]]) -> None:
        self._close_resources = close_resources
        self._state_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._ready = threading.Event()
        self._closing = False
        self._closed = False
        self._startup_error: BaseException | None = None
        self._close_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            self._thread.join()
            raise RuntimeError('model event loop initialization failed') from self._startup_error

    def _serve(self) -> None:
        try:
            with asyncio.Runner() as runner:
                self._loop = runner.get_loop()
                self._ready.set()
                self._loop.run_forever()
        except BaseException as exc:
            self._startup_error = exc
        finally:
            self._ready.set()

    def run(self, operation: Callable[[], Awaitable[_Result]]) -> _Result:
        if threading.current_thread() is self._thread:
            raise RuntimeError('cannot synchronously reenter the resident model event loop')

        async def invoke() -> _Result:
            return await operation()

        with self._state_lock:
            if self._closing or self._closed:
                raise RuntimeError('resident model event loop is closed')
            assert self._loop is not None
            coroutine = invoke()
            try:
                result = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except BaseException:
                coroutine.close()
                raise
        return result.result()

    async def _shutdown(self) -> None:
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        loop = asyncio.get_running_loop()
        await loop.shutdown_asyncgens()
        await loop.shutdown_default_executor()
        await self._close_resources()

    def close(self) -> None:
        if threading.current_thread() is self._thread:
            raise RuntimeError('cannot synchronously close the resident model event loop from itself')
        with self._close_lock:
            if self._closed:
                if self._close_error is not None:
                    raise self._close_error
                return
            with self._state_lock:
                self._closing = True
            assert self._loop is not None
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result()
            except BaseException as exc:
                self._close_error = exc
                raise
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join()
                self._closed = True


async def await_model_operation(
    operation: Awaitable[_Result], cancellation_event: threading.Event,
) -> _Result:
    """Observe the existing cancellation signal before releasing an owner slot."""
    task = asyncio.ensure_future(operation)
    try:
        while not task.done():
            if cancellation_event.is_set():
                raise asyncio.CancelledError('model inference cancellation requested')
            await asyncio.wait({task}, timeout=0.05)
        if cancellation_event.is_set():
            raise asyncio.CancelledError('model inference cancellation requested')
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
