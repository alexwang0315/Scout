"""SLA enforcement wrapper for Scout AI OS model calls."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from typing import Any, Literal

from scout.agents.model_policy import ModelPolicy


ModelSlaStatus = Literal[
    "completed",
    "budget_fallback",
    "timeout_fallback",
    "error_fallback",
    "budget_blocked",
    "timed_out",
    "failed",
]


class ModelBudgetExceeded(RuntimeError):
    """Raised when a model call cannot fit inside the configured budget."""


@dataclass
class ModelCallLedger:
    """In-memory model call budget ledger for one smoke/API process."""

    max_cost_usd: float | None = None
    spent_usd: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    def can_spend(self, estimated_cost_usd: float) -> bool:
        if self.max_cost_usd is None:
            return True
        return self.spent_usd + estimated_cost_usd <= self.max_cost_usd

    def record(self, *, operation: str, estimated_cost_usd: float, status: str) -> None:
        if status == "completed":
            self.spent_usd += estimated_cost_usd
        self.events.append(
            {
                "operation": operation,
                "estimated_cost_usd": estimated_cost_usd,
                "spent_usd": self.spent_usd,
                "status": status,
            }
        )


@dataclass(frozen=True)
class ModelSlaCallResult:
    """Result envelope for an SLA-wrapped model call."""

    output: Any
    status: ModelSlaStatus
    elapsed_seconds: float
    timeout_seconds: float
    estimated_cost_usd: float
    spent_usd: float
    fallback_used: bool
    error: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "timeout_seconds": self.timeout_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
            "spent_usd": self.spent_usd,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


class ModelSlaGateway:
    """Apply timeout, budget, and fallback policy around model calls."""

    def __init__(
        self,
        policy: ModelPolicy,
        *,
        ledger: ModelCallLedger | None = None,
    ) -> None:
        self.policy = policy
        self.ledger = ledger or ModelCallLedger(max_cost_usd=policy.max_cost_usd)

    def run_sync(
        self,
        operation: str,
        call: Callable[[], Any],
        *,
        fallback_call: Callable[[], Any] | None = None,
        estimated_cost_usd: float | None = None,
    ) -> ModelSlaCallResult:
        estimated_cost = (
            self.policy.estimated_call_cost_usd
            if estimated_cost_usd is None
            else estimated_cost_usd
        )
        started_at = time.monotonic()
        if not self.ledger.can_spend(estimated_cost):
            return self._fallback_or_terminal(
                operation=operation,
                started_at=started_at,
                status_with_fallback="budget_fallback",
                terminal_status="budget_blocked",
                fallback_call=fallback_call,
                estimated_cost_usd=estimated_cost,
                error="model budget exceeded before provider call",
            )

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(call)
        try:
            output = future.result(timeout=self.policy.timeout_seconds)
        except TimeoutError:
            future.cancel()
            return self._fallback_or_terminal(
                operation=operation,
                started_at=started_at,
                status_with_fallback="timeout_fallback",
                terminal_status="timed_out",
                fallback_call=fallback_call,
                estimated_cost_usd=estimated_cost,
                error=f"model call exceeded {self.policy.timeout_seconds:g}s",
            )
        except Exception as exc:
            return self._fallback_or_terminal(
                operation=operation,
                started_at=started_at,
                status_with_fallback="error_fallback",
                terminal_status="failed",
                fallback_call=fallback_call,
                estimated_cost_usd=estimated_cost,
                error=str(exc),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        self.ledger.record(
            operation=operation,
            estimated_cost_usd=estimated_cost,
            status="completed",
        )
        return ModelSlaCallResult(
            output=output,
            status="completed",
            elapsed_seconds=time.monotonic() - started_at,
            timeout_seconds=self.policy.timeout_seconds,
            estimated_cost_usd=estimated_cost,
            spent_usd=self.ledger.spent_usd,
            fallback_used=False,
        )

    def _fallback_or_terminal(
        self,
        *,
        operation: str,
        started_at: float,
        status_with_fallback: ModelSlaStatus,
        terminal_status: ModelSlaStatus,
        fallback_call: Callable[[], Any] | None,
        estimated_cost_usd: float,
        error: str,
    ) -> ModelSlaCallResult:
        if fallback_call is None:
            self.ledger.record(
                operation=operation,
                estimated_cost_usd=estimated_cost_usd,
                status=terminal_status,
            )
            raise ModelBudgetExceeded(error) if terminal_status == "budget_blocked" else RuntimeError(error)
        output = fallback_call()
        self.ledger.record(
            operation=operation,
            estimated_cost_usd=estimated_cost_usd,
            status=status_with_fallback,
        )
        return ModelSlaCallResult(
            output=output,
            status=status_with_fallback,
            elapsed_seconds=time.monotonic() - started_at,
            timeout_seconds=self.policy.timeout_seconds,
            estimated_cost_usd=estimated_cost_usd,
            spent_usd=self.ledger.spent_usd,
            fallback_used=True,
            error=error,
        )


__all__ = [
    "ModelBudgetExceeded",
    "ModelCallLedger",
    "ModelSlaCallResult",
    "ModelSlaGateway",
    "ModelSlaStatus",
]
