"""Own factory-created model resources for one synchronous worker invocation."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import AsyncExitStack, contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

_T = TypeVar("_T")
_ModelResources = tuple[asyncio.AbstractEventLoop, AsyncExitStack, list[Future[Any]]]
_active_model_resources: ContextVar[_ModelResources | None] = ContextVar(
    "scout_model_resources", default=None
)


@contextmanager
def pydantic_model_resources(loop: asyncio.AbstractEventLoop) -> Iterator[None]:
    """Close models created inside this scope before its owner's loop closes.

    Models or clients supplied from outside this scope retain their original
    ownership. Pydantic's public model context closes only provider-owned clients.
    """
    stack = AsyncExitStack()
    pending: list[Future[Any]] = []
    token = _active_model_resources.set((loop, stack, pending))

    async def close_resources() -> None:
        try:
            await asyncio.gather(*(asyncio.wrap_future(entry) for entry in pending))
        finally:
            await stack.aclose()

    try:
        yield
    finally:
        _active_model_resources.reset(token)
        loop.run_until_complete(close_resources())


def manage_new_chat_model(model: _T) -> _T:
    """Register only a newly constructed Scout factory model with the owner."""
    resources = _active_model_resources.get()
    if resources is not None:
        loop, stack, pending = resources
        if loop.is_running():
            # A synchronous factory may also be called from an SDK async/tool
            # callback. Enter on the owning loop without nesting run_until_complete.
            pending.append(
                asyncio.run_coroutine_threadsafe(stack.enter_async_context(model), loop)
            )
        else:
            loop.run_until_complete(stack.enter_async_context(model))
    return model


def run_in_model_worker(call: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run only in a fresh worker; preserve all stages on one owned loop."""
    with asyncio.Runner() as runner:
        with pydantic_model_resources(runner.get_loop()):
            return call(*args, **kwargs)


def _existing_event_loop() -> asyncio.AbstractEventLoop | None:
    """Inspect the caller's loop without implicitly creating one on Python 3.13."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    if sys.version_info < (3, 14):
        policy = asyncio.get_event_loop_policy()
        if type(policy).get_event_loop is asyncio.DefaultEventLoopPolicy.get_event_loop:
            # Python <=3.13's default public getter creates a loop on the main
            # thread and emits a deprecation warning. Read its stored reference
            # only; creating it here would make ownership impossible to identify.
            return policy._local._loop
        try:
            return policy.get_event_loop()
        except RuntimeError:
            return None

    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


@contextmanager
def pydantic_model_session() -> Iterator[None]:
    """Own a missing sync-session loop, or borrow a caller's existing idle loop."""
    previous = _existing_event_loop()
    if previous is not None and previous.is_running():
        # Keep the SDK's own invalid/nested sync-call guard unchanged.
        yield
    elif previous is not None and not previous.is_closed():
        with pydantic_model_resources(previous):
            yield
    else:
        try:
            with asyncio.Runner() as runner:
                with pydantic_model_resources(runner.get_loop()):
                    yield
        finally:
            if previous is not None:
                asyncio.set_event_loop(previous)


def build_owned_openai_provider(*, base_url: str, api_key: Any) -> Any:
    """Own NVIDIA's original AsyncOpenAI client without changing its defaults."""
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openai import OpenAIProvider

    class OwnedOpenAIProvider(OpenAIProvider):
        def __init__(self) -> None:
            self._scout_context_count = 0
            super().__init__(openai_client=self._new_owned_client())

        def _new_owned_client(self) -> Any:
            return AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)

        async def __aenter__(self) -> Any:
            if self._scout_context_count == 0 and self.client.is_closed():
                self._client = self._new_owned_client()
            result = await super().__aenter__()
            self._scout_context_count += 1
            return result

        async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            try:
                await super().__aexit__(exc_type, exc, traceback)
            finally:
                self._scout_context_count -= 1
                if self._scout_context_count == 0:
                    await self.client.close()

    return OwnedOpenAIProvider()
