from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

from pydantic import ConfigDict, Field, model_validator

from scout.schemas.base import SchemaModel


ModelCall = Callable[..., tuple[str, dict[str, Any]]]
ContextualModelCall = Callable[..., tuple[str, dict[str, Any]]]


class ModelRunDeadlineExceeded(RuntimeError):
    """Raised when the complete Pydantic model run exceeds its deadline."""


class ModelRunCancellationRequested(RuntimeError):
    """Raised when an external cancellation signal stops model execution."""


class ModelRunCancellationReceipt(SchemaModel):
    """Candidate-only audit record for a stopped answer-model run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.model_run_cancellation_receipt.v0"] = (
        "scout.model_run_cancellation_receipt.v0"
    )
    status: Literal["timed_out", "cancelled"]
    reason_code: Literal[
        "total_run_deadline_exceeded",
        "cancellation_requested",
    ]
    checkpoint: Literal[
        "after_evidence_collection",
        "before_model_request",
        "after_model_request",
        "before_guided_retry",
    ]
    adapter_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    started_at: datetime
    recorded_at: datetime
    elapsed_ms: int = Field(ge=0)
    total_run_timeout_seconds: float | None = Field(default=None, gt=0)
    completed_model_attempts: int = Field(ge=0)
    interrupted_request_index: int | None = Field(default=None, ge=1)
    provider_cancellation_supported: bool
    late_provider_output_discarded: bool = False
    partial_trace_preserved: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def _validate_status_reason(self) -> "ModelRunCancellationReceipt":
        if self.status == "timed_out":
            if self.reason_code != "total_run_deadline_exceeded":
                raise ValueError("timed_out receipt requires deadline reason")
            if self.total_run_timeout_seconds is None:
                raise ValueError("timed_out receipt requires a total run timeout")
        elif self.reason_code != "cancellation_requested":
            raise ValueError("cancelled receipt requires cancellation reason")
        return self


@dataclass(frozen=True)
class ScoutModelExecutionAdapter:
    """Bind one model implementation to explicit, auditable route metadata."""

    adapter_id: str
    profile: Literal["cloud", "local"]
    provider: str
    transport: str
    invoke: ModelCall
    invoke_with_context: ContextualModelCall | None = None
    supports_run_controls: bool = False


__all__ = [
    "ContextualModelCall",
    "ModelCall",
    "ModelRunCancellationReceipt",
    "ModelRunCancellationRequested",
    "ModelRunDeadlineExceeded",
    "ScoutModelExecutionAdapter",
]
