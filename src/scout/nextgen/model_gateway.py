"""Executable Scout Model Gateway with typed routing and bounded inference."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, Literal, Protocol, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

from scout.nextgen.intelligence_gateway import ModelExecutionRecord
from scout.nextgen.model_runtime import (
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
    ModelRuntimeRequest,
    ModelRuntimeSelection,
    ModelRuntimeTier,
    ScoutModelRuntimeRouter,
)
from scout.nextgen.model_scheduler import (
    BoundedInferenceScheduler,
    InferenceSchedulerBackpressure,
    InferenceSchedulerCancelled,
    InferenceSchedulerClosed,
    InferenceSchedulerSnapshot,
    InferenceSchedulerTimeout,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

OutputT = TypeVar("OutputT", bound=BaseModel)
ModelThinkingSetting = bool | Literal["minimal", "low", "medium", "high", "xhigh"]


class ModelInferencePriority(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    BACKGROUND = "background"


_PRIORITY_RANK = {
    ModelInferencePriority.HIGH: 0,
    ModelInferencePriority.NORMAL: 10,
    ModelInferencePriority.BACKGROUND: 20,
}


class ModelGatewayError(RuntimeError):
    pass


class BackendInferenceFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        model_request_count: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        if model_request_count < 0:
            raise ValueError("failed backend model request count cannot be negative")
        self.model_request_count = model_request_count
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ModelRuntimeUnavailable(ModelGatewayError):
    pass


class ModelRequestBudgetExceeded(ModelGatewayError):
    def __init__(
        self,
        message: str,
        *,
        record: ModelExecutionRecord | None = None,
    ) -> None:
        super().__init__(message)
        self.record = record


class ModelSessionCancelled(ModelGatewayError):
    pass


class ModelGatewayExecutionError(ModelGatewayError):
    def __init__(self, message: str, *, record: ModelExecutionRecord) -> None:
        super().__init__(message)
        self.record = record


class ModelInferenceTimeout(ModelGatewayExecutionError):
    pass


class ModelInferenceBackpressure(ModelGatewayExecutionError):
    pass


class ModelInferenceCancelled(ModelGatewayExecutionError):
    pass


class ModelOutputValidationError(ModelGatewayExecutionError):
    pass


class ModelInferenceRequest(SchemaModel):
    inference_id: UUID = Field(default_factory=uuid4)
    parent_request_id: UUID
    task: NonEmptyStr
    prompt: NonEmptyStr
    structured_input: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: frozenset[ModelRuntimeCapability] = frozenset(
        {
            ModelRuntimeCapability.CHAT,
            ModelRuntimeCapability.STRUCTURED_OUTPUT,
        }
    )
    allowed_tiers: frozenset[ModelRuntimeTier] | None = None
    prefer_local: bool = True
    allow_cloud: bool = False
    requires_offline: bool = False
    privacy_sensitive: bool = True
    max_latency_ms: int | None = Field(default=None, ge=1)
    min_context_tokens: int = Field(default=1, ge=1)
    estimated_input_tokens: int = Field(default=1, ge=1)
    timeout_seconds: float | None = Field(default=30, ge=0.01)
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    thinking: ModelThinkingSetting | None = None
    priority: ModelInferencePriority = ModelInferencePriority.NORMAL
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


@dataclass(frozen=True)
class BackendInferenceResult:
    output: Any
    model_request_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    observed_model_id: str | None = None

    def __post_init__(self) -> None:
        if self.model_request_count < 1:
            raise ValueError("successful backend inference must use a model request")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("input_tokens cannot be negative")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("output_tokens cannot be negative")


class ModelRuntimeBackend(Protocol):
    runtime_id: str
    model_id: str

    def infer(
        self,
        *,
        request: ModelInferenceRequest,
        output_type: type[BaseModel],
        model_request_limit: int,
        cancellation_event: threading.Event,
    ) -> BackendInferenceResult: ...


@dataclass(frozen=True)
class ModelGatewayResult(Generic[OutputT]):
    output: OutputT
    selection: ModelRuntimeSelection
    execution_record: ModelExecutionRecord


class PydanticAIStructuredBackend:
    """Use one resident Pydantic AI model object for typed inference calls."""

    def __init__(
        self,
        *,
        runtime_id: str,
        model_id: str,
        model: Any,
        default_model_settings: Mapping[str, Any] | None = None,
    ) -> None:
        from pydantic_ai import Agent, UsageLimits

        self.runtime_id = runtime_id
        self.model_id = model_id
        self.resident_model = model
        self._default_model_settings = dict(default_model_settings or {})
        self._agent_type = Agent
        self._usage_limits_type = UsageLimits
        self._agents: dict[type[BaseModel], Any] = {}
        self._agent_lock = threading.Lock()

    def infer(
        self,
        *,
        request: ModelInferenceRequest,
        output_type: type[BaseModel],
        model_request_limit: int,
        cancellation_event: threading.Event,
    ) -> BackendInferenceResult:
        if cancellation_event.is_set():
            raise RuntimeError("model inference was cancelled before execution")
        from scout.agents.pydantic_ai_compat import pydantic_result_output

        agent = self._agent_for(output_type)
        requests_before = _resident_model_request_count(self.resident_model)
        request_scope = _begin_model_request_scope(self.resident_model)
        try:
            model_settings = dict(self._default_model_settings)
            if request.timeout_seconds is not None:
                model_settings["timeout"] = request.timeout_seconds
            if request.max_output_tokens is not None:
                model_settings["max_tokens"] = request.max_output_tokens
            if request.temperature is not None:
                model_settings["temperature"] = request.temperature
            if request.thinking is not None:
                model_settings["thinking"] = request.thinking
            result = agent.run_sync(
                request.prompt,
                model_settings=model_settings or None,
                usage_limits=self._usage_limits_type(
                    request_limit=model_request_limit,
                    tool_calls_limit=10,
                ),
                retries=10,
            )
            if cancellation_event.is_set():
                raise RuntimeError("model inference was cancelled during execution")
            output = output_type.model_validate(pydantic_result_output(result))
        except ValidationError:
            _finish_model_request_scope(
                self.resident_model,
                request_scope,
                requests_before,
            )
            raise
        except Exception as exc:
            raise BackendInferenceFailure(
                "Pydantic AI model execution failed",
                model_request_count=_finish_model_request_scope(
                    self.resident_model,
                    request_scope,
                    requests_before,
                ),
            ) from exc
        usage_value = getattr(result, "usage", None)
        usage = usage_value() if callable(usage_value) else usage_value
        observed_requests = _finish_model_request_scope(
            self.resident_model,
            request_scope,
            requests_before,
        )
        return BackendInferenceResult(
            output=output,
            model_request_count=max(
                1,
                observed_requests,
                int(getattr(usage, "requests", 1)),
            ),
            input_tokens=_optional_int(usage, "input_tokens"),
            output_tokens=_optional_int(usage, "output_tokens"),
            observed_model_id=_observed_model_id(result),
        )

    def _agent_for(self, output_type: type[BaseModel]) -> Any:
        with self._agent_lock:
            agent = self._agents.get(output_type)
            if agent is None:
                agent = self._agent_type(
                    self.resident_model,
                    output_type=output_type,
                    instructions=(
                        "Return only the requested typed candidate analysis. "
                        "Never claim mission, route, permission, emergency, "
                        "notification, hardware, or runtime safety authority. "
                        "Preserve unknown and conflict."
                    ),
                    retries=10,
                )
                self._agents[output_type] = agent
            return agent


class ScoutModelGateway:
    """Select one registered backend and execute it through bounded schedulers."""

    def __init__(
        self,
        *,
        profiles: Sequence[ModelRuntimeProfile],
        backends: Sequence[ModelRuntimeBackend],
        max_local_concurrency: int = 1,
        max_cloud_concurrency: int = 2,
        max_queue_size: int = 32,
    ) -> None:
        backend_map = {backend.runtime_id: backend for backend in backends}
        if len(backend_map) != len(backends):
            raise ValueError("model runtime backend ids must be unique")
        registered_profiles = tuple(
            profile for profile in profiles if profile.runtime_id in backend_map
        )
        if not registered_profiles:
            raise ValueError("at least one runtime profile must have a backend")
        profile_ids = {profile.runtime_id for profile in registered_profiles}
        unknown_backends = set(backend_map).difference(profile_ids)
        if unknown_backends:
            names = ", ".join(sorted(unknown_backends))
            raise ValueError(f"model backends have no runtime profile: {names}")
        for profile in registered_profiles:
            backend = backend_map[profile.runtime_id]
            if backend.model_id != profile.model_id:
                raise ValueError(
                    f"backend model_id does not match profile: {profile.runtime_id}"
                )
        self._router = ScoutModelRuntimeRouter(registered_profiles)
        self._backends: Mapping[str, ModelRuntimeBackend] = backend_map
        self._local_scheduler = BoundedInferenceScheduler(
            max_concurrency=max_local_concurrency,
            max_queue_size=max_queue_size,
            name="scout-local-model",
        )
        self._cloud_scheduler = BoundedInferenceScheduler(
            max_concurrency=max_cloud_concurrency,
            max_queue_size=max_queue_size,
            name="scout-cloud-model",
        )

    def __enter__(self) -> "ScoutModelGateway":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._local_scheduler.close()
        self._cloud_scheduler.close()
        for backend in self._backends.values():
            close_backend = getattr(backend, "close", None)
            if callable(close_backend):
                close_backend()

    def open_session(
        self,
        *,
        parent_request_id: UUID,
        max_model_requests: int = 10,
    ) -> "ModelGatewaySession":
        return ModelGatewaySession(
            gateway=self,
            parent_request_id=parent_request_id,
            max_model_requests=max_model_requests,
        )

    def scheduler_snapshots(
        self,
    ) -> tuple[InferenceSchedulerSnapshot, InferenceSchedulerSnapshot]:
        return self._local_scheduler.snapshot(), self._cloud_scheduler.snapshot()

    def _infer(
        self,
        *,
        request: ModelInferenceRequest,
        output_type: type[OutputT],
        model_request_limit: int,
        routing_model_request_ceiling: int,
        cancellation_event: threading.Event,
    ) -> ModelGatewayResult[OutputT]:
        selection = self._router.select(
            ModelRuntimeRequest(
                request_id=request.inference_id,
                task=request.task,
                required_capabilities=request.required_capabilities,
                allowed_tiers=request.allowed_tiers,
                prefer_local=request.prefer_local,
                allow_cloud=request.allow_cloud,
                requires_offline=request.requires_offline,
                privacy_sensitive=request.privacy_sensitive,
                max_latency_ms=request.max_latency_ms,
                min_context_tokens=max(
                    request.min_context_tokens,
                    request.estimated_input_tokens,
                ),
                max_model_requests=routing_model_request_ceiling,
            )
        )
        profile = selection.selected_runtime
        if profile is None:
            raise ModelRuntimeUnavailable(selection.reason)
        backend = self._backends[profile.runtime_id]
        scheduler = (
            self._cloud_scheduler
            if profile.locality is Locality.CLOUD
            else self._local_scheduler
        )
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        backend_result: BackendInferenceResult | None = None

        def operation() -> BackendInferenceResult:
            return backend.infer(
                request=request,
                output_type=output_type,
                model_request_limit=model_request_limit,
                cancellation_event=cancellation_event,
            )

        try:
            backend_result = scheduler.submit(
                operation,
                priority=_PRIORITY_RANK[request.priority],
                timeout_seconds=request.timeout_seconds,
                cancellation_event=cancellation_event,
            )
            if backend_result.model_request_count > model_request_limit:
                record = _execution_record(
                    request=request,
                    profile=profile,
                    selection=selection,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                    status="failed",
                    model_request_count=backend_result.model_request_count,
                    input_tokens=backend_result.input_tokens,
                    output_tokens=backend_result.output_tokens,
                    observed_model_id=backend_result.observed_model_id,
                    error_type="ModelRequestBudgetExceeded",
                )
                raise ModelRequestBudgetExceeded(
                    "backend exceeded the remaining model request budget",
                    record=record,
                )
            output = output_type.model_validate(backend_result.output)
        except InferenceSchedulerTimeout as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="timed_out",
                model_request_count=0,
                error_type=type(exc).__name__,
            )
            raise ModelInferenceTimeout(str(exc), record=record) from exc
        except InferenceSchedulerBackpressure as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="failed",
                model_request_count=0,
                error_type=type(exc).__name__,
            )
            raise ModelInferenceBackpressure(str(exc), record=record) from exc
        except (InferenceSchedulerCancelled, InferenceSchedulerClosed) as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="cancelled",
                model_request_count=0,
                error_type=type(exc).__name__,
            )
            raise ModelInferenceCancelled(str(exc), record=record) from exc
        except BackendInferenceFailure as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="failed",
                model_request_count=exc.model_request_count,
                input_tokens=exc.input_tokens,
                output_tokens=exc.output_tokens,
                error_type=type(exc.__cause__ or exc).__name__,
            )
            raise ModelGatewayExecutionError(
                "model backend execution failed",
                record=record,
            ) from exc
        except ValidationError as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="failed",
                model_request_count=(
                    backend_result.model_request_count if backend_result else 0
                ),
                input_tokens=backend_result.input_tokens if backend_result else None,
                output_tokens=backend_result.output_tokens if backend_result else None,
                observed_model_id=(
                    backend_result.observed_model_id if backend_result else None
                ),
                error_type=type(exc).__name__,
            )
            raise ModelOutputValidationError(
                "model output failed the requested Pydantic schema",
                record=record,
            ) from exc
        except ModelRequestBudgetExceeded:
            raise
        except Exception as exc:
            record = _execution_record(
                request=request,
                profile=profile,
                selection=selection,
                started_at=started_at,
                started_monotonic=started_monotonic,
                status="failed",
                model_request_count=(
                    backend_result.model_request_count if backend_result else 0
                ),
                input_tokens=backend_result.input_tokens if backend_result else None,
                output_tokens=backend_result.output_tokens if backend_result else None,
                observed_model_id=(
                    backend_result.observed_model_id if backend_result else None
                ),
                error_type=type(exc).__name__,
            )
            raise ModelGatewayExecutionError(
                "model backend execution failed",
                record=record,
            ) from exc
        record = _execution_record(
            request=request,
            profile=profile,
            selection=selection,
            started_at=started_at,
            started_monotonic=started_monotonic,
            status="completed",
            model_request_count=backend_result.model_request_count,
            input_tokens=backend_result.input_tokens,
            output_tokens=backend_result.output_tokens,
            observed_model_id=backend_result.observed_model_id,
        )
        return ModelGatewayResult(
            output=output,
            selection=selection,
            execution_record=record,
        )


class ModelGatewaySession:
    """One task-bound ledger shared by every specialist in an orchestration."""

    def __init__(
        self,
        *,
        gateway: ScoutModelGateway,
        parent_request_id: UUID,
        max_model_requests: int,
    ) -> None:
        if max_model_requests < 10:
            raise ValueError("model request ceiling cannot be below 10")
        self.gateway = gateway
        self.parent_request_id = parent_request_id
        self.max_model_requests = max_model_requests
        self._consumed_model_requests = 0
        self._records: list[ModelExecutionRecord] = []
        self._call_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cancellation_event = threading.Event()

    @property
    def records(self) -> tuple[ModelExecutionRecord, ...]:
        with self._state_lock:
            return tuple(self._records)

    @property
    def remaining_model_requests(self) -> int:
        with self._state_lock:
            return max(0, self.max_model_requests - self._consumed_model_requests)

    def cancel(self) -> None:
        self._cancellation_event.set()

    def infer(
        self,
        request: ModelInferenceRequest,
        *,
        output_type: type[OutputT],
    ) -> ModelGatewayResult[OutputT]:
        if request.parent_request_id != self.parent_request_id:
            raise ValueError("model inference request is bound to another parent task")
        with self._call_lock:
            if self._cancellation_event.is_set():
                raise ModelSessionCancelled("model gateway session is cancelled")
            remaining = self.remaining_model_requests
            if remaining < 1:
                raise ModelRequestBudgetExceeded(
                    "shared model request budget is exhausted"
                )
            try:
                result = self.gateway._infer(
                    request=request,
                    output_type=output_type,
                    model_request_limit=remaining,
                    routing_model_request_ceiling=self.max_model_requests,
                    cancellation_event=self._cancellation_event,
                )
            except ModelGatewayExecutionError as exc:
                self._record(exc.record)
                raise
            except ModelRequestBudgetExceeded as exc:
                if exc.record is not None:
                    self._record(exc.record)
                raise
            self._record(result.execution_record)
            return result

    def _record(self, record: ModelExecutionRecord) -> None:
        with self._state_lock:
            self._records.append(record)
            self._consumed_model_requests += record.model_request_count


def _execution_record(
    *,
    request: ModelInferenceRequest,
    profile: ModelRuntimeProfile,
    selection: ModelRuntimeSelection,
    started_at: datetime,
    started_monotonic: float,
    status: str,
    model_request_count: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    observed_model_id: str | None = None,
    error_type: str | None = None,
) -> ModelExecutionRecord:
    return ModelExecutionRecord(
        parent_request_id=request.parent_request_id,
        inference_id=request.inference_id,
        runtime_id=profile.runtime_id,
        provider=profile.provider,
        model_id=profile.model_id,
        observed_model_id=observed_model_id,
        locality=_record_locality(profile.locality),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        latency_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
        model_request_count=model_request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status=status,
        selection_reason=selection.reason,
        error_type=error_type,
    )


def _record_locality(locality: Locality) -> str:
    if locality is Locality.EDGE:
        return "edge"
    if locality is Locality.MAC_SERVER:
        return "local_server"
    return "cloud"


def _optional_int(value: Any, name: str) -> int | None:
    candidate = getattr(value, name, None) if value is not None else None
    return int(candidate) if isinstance(candidate, int) else None


def _observed_model_id(result: Any) -> str | None:
    all_messages = getattr(result, "all_messages", None)
    if not callable(all_messages):
        return None
    for message in reversed(all_messages()):
        value = getattr(message, "model_name", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resident_model_request_count(model: Any) -> int | None:
    value = getattr(model, "request_count", None)
    return value if isinstance(value, int) and value >= 0 else None


def _model_request_delta(model: Any, before: int | None) -> int:
    after = _resident_model_request_count(model)
    if before is None or after is None:
        return 0
    return max(0, after - before)


def _begin_model_request_scope(model: Any) -> Any | None:
    begin = getattr(model, "begin_request_scope", None)
    return begin() if callable(begin) else None


def _finish_model_request_scope(
    model: Any,
    scope: Any | None,
    before: int | None,
) -> int:
    finish = getattr(model, "finish_request_scope", None)
    if scope is not None and callable(finish):
        value = finish(scope)
        if isinstance(value, int) and value >= 0:
            return value
    return _model_request_delta(model, before)


__all__ = [
    "BackendInferenceResult",
    "BackendInferenceFailure",
    "ModelGatewayError",
    "ModelGatewayExecutionError",
    "ModelGatewayResult",
    "ModelGatewaySession",
    "ModelInferenceBackpressure",
    "ModelInferenceCancelled",
    "ModelInferencePriority",
    "ModelInferenceRequest",
    "ModelInferenceTimeout",
    "ModelOutputValidationError",
    "ModelRequestBudgetExceeded",
    "ModelSessionCancelled",
    "ModelRuntimeBackend",
    "ModelRuntimeUnavailable",
    "PydanticAIStructuredBackend",
    "ScoutModelGateway",
]
