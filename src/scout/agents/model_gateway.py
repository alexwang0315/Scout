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
    "circuit_fallback",
    "timeout_fallback",
    "error_fallback",
    "budget_blocked",
    "circuit_blocked",
    "timed_out",
    "failed",
]

ModelProviderHealthState = Literal["healthy", "degraded", "open_circuit"]


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

    def record(
        self,
        *,
        operation: str,
        estimated_cost_usd: float,
        status: str,
        attempts: int = 1,
        provider_health_state: str | None = None,
    ) -> None:
        if status == "completed":
            self.spent_usd += estimated_cost_usd
        self.events.append(
            {
                "operation": operation,
                "estimated_cost_usd": estimated_cost_usd,
                "spent_usd": self.spent_usd,
                "status": status,
                "attempts": attempts,
                "provider_health_state": provider_health_state,
            }
        )


@dataclass
class ModelProviderHealth:
    """Mutable health snapshot for an external model provider."""

    provider_id: str
    state: ModelProviderHealthState = "healthy"
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    circuit_open_until: float | None = None
    last_error: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "state": self.state,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "circuit_open": self.state == "open_circuit",
            "last_error": self.last_error,
        }


class ModelProviderHealthMonitor:
    """Track provider failures and open a local circuit when SLA failures repeat."""

    def __init__(
        self,
        *,
        provider_id: str = "external_model",
        failure_threshold: int = 2,
        recovery_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if recovery_seconds <= 0:
            raise ValueError("recovery_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock or time.monotonic
        self.health = ModelProviderHealth(provider_id=provider_id)

    def current_health(self) -> ModelProviderHealth:
        if (
            self.health.state == "open_circuit"
            and self.health.circuit_open_until is not None
            and self._clock() >= self.health.circuit_open_until
        ):
            self.health.state = "degraded"
            self.health.circuit_open_until = None
        return self.health

    def before_call_allowed(self) -> bool:
        return self.current_health().state != "open_circuit"

    def record_success(self) -> None:
        health = self.current_health()
        health.success_count += 1
        health.consecutive_failures = 0
        health.state = "healthy"
        health.circuit_open_until = None
        health.last_error = None

    def record_failure(self, error: str) -> None:
        health = self.current_health()
        health.failure_count += 1
        health.consecutive_failures += 1
        health.last_error = error
        if health.consecutive_failures >= self.failure_threshold:
            health.state = "open_circuit"
            health.circuit_open_until = self._clock() + self.recovery_seconds
        else:
            health.state = "degraded"


@dataclass(frozen=True)
class ModelSlaTelemetryRecord:
    """Serializable SLA telemetry for one wrapped model operation."""

    operation: str
    status: ModelSlaStatus
    elapsed_seconds: float
    estimated_cost_usd: float
    spent_usd: float
    attempts: int
    fallback_used: bool
    provider_health: dict[str, Any]
    error: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "estimated_cost_usd": self.estimated_cost_usd,
            "spent_usd": self.spent_usd,
            "attempts": self.attempts,
            "fallback_used": self.fallback_used,
            "provider_health": self.provider_health,
            "error": self.error,
        }


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
    attempts: int = 1
    provider_health: dict[str, Any] = field(default_factory=dict)
    telemetry: ModelSlaTelemetryRecord | None = None
    error: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "timeout_seconds": self.timeout_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
            "spent_usd": self.spent_usd,
            "fallback_used": self.fallback_used,
            "attempts": self.attempts,
            "provider_health": self.provider_health,
            "telemetry": self.telemetry.to_metadata() if self.telemetry else None,
            "error": self.error,
        }


class ModelSlaGateway:
    """Apply timeout, budget, and fallback policy around model calls."""

    def __init__(
        self,
        policy: ModelPolicy,
        *,
        ledger: ModelCallLedger | None = None,
        health_monitor: ModelProviderHealthMonitor | None = None,
    ) -> None:
        self.policy = policy
        self.ledger = ledger or ModelCallLedger(max_cost_usd=policy.max_cost_usd)
        self.health_monitor = health_monitor or ModelProviderHealthMonitor()

    def run_sync(
        self,
        operation: str,
        call: Callable[[], Any],
        *,
        fallback_call: Callable[[], Any] | None = None,
        estimated_cost_usd: float | None = None,
        max_retries: int = 0,
    ) -> ModelSlaCallResult:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        estimated_cost = (
            self.policy.estimated_call_cost_usd
            if estimated_cost_usd is None
            else estimated_cost_usd
        )
        started_at = time.monotonic()
        if not self.health_monitor.before_call_allowed():
            return self._fallback_or_terminal(
                operation=operation,
                started_at=started_at,
                status_with_fallback="circuit_fallback",
                terminal_status="circuit_blocked",
                fallback_call=fallback_call,
                estimated_cost_usd=estimated_cost,
                error="model provider circuit is open",
                attempts=0,
            )
        if not self.ledger.can_spend(estimated_cost):
            return self._fallback_or_terminal(
                operation=operation,
                started_at=started_at,
                status_with_fallback="budget_fallback",
                terminal_status="budget_blocked",
                fallback_call=fallback_call,
                estimated_cost_usd=estimated_cost,
                error="model budget exceeded before provider call",
                attempts=0,
            )

        attempts = 0
        for attempt in range(max_retries + 1):
            attempts = attempt + 1
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(call)
            try:
                output = future.result(timeout=self.policy.timeout_seconds)
            except TimeoutError:
                future.cancel()
                error = f"model call exceeded {self.policy.timeout_seconds:g}s"
                self.health_monitor.record_failure(error)
                if attempt < max_retries and self.health_monitor.before_call_allowed():
                    executor.shutdown(wait=False, cancel_futures=True)
                    continue
                executor.shutdown(wait=False, cancel_futures=True)
                return self._fallback_or_terminal(
                    operation=operation,
                    started_at=started_at,
                    status_with_fallback="timeout_fallback",
                    terminal_status="timed_out",
                    fallback_call=fallback_call,
                    estimated_cost_usd=estimated_cost,
                    error=error,
                    attempts=attempts,
                )
            except Exception as exc:
                error = str(exc)
                self.health_monitor.record_failure(error)
                if attempt < max_retries and self.health_monitor.before_call_allowed():
                    executor.shutdown(wait=False, cancel_futures=True)
                    continue
                executor.shutdown(wait=False, cancel_futures=True)
                return self._fallback_or_terminal(
                    operation=operation,
                    started_at=started_at,
                    status_with_fallback="error_fallback",
                    terminal_status="failed",
                    fallback_call=fallback_call,
                    estimated_cost_usd=estimated_cost,
                    error=error,
                    attempts=attempts,
                )
            else:
                executor.shutdown(wait=False, cancel_futures=True)
                break

        self.health_monitor.record_success()
        provider_health = self.health_monitor.current_health().to_metadata()
        self.ledger.record(
            operation=operation,
            estimated_cost_usd=estimated_cost,
            status="completed",
            attempts=attempts,
            provider_health_state=provider_health["state"],
        )
        elapsed_seconds = time.monotonic() - started_at
        telemetry = ModelSlaTelemetryRecord(
            operation=operation,
            status="completed",
            elapsed_seconds=elapsed_seconds,
            estimated_cost_usd=estimated_cost,
            spent_usd=self.ledger.spent_usd,
            attempts=attempts,
            fallback_used=False,
            provider_health=provider_health,
        )
        return ModelSlaCallResult(
            output=output,
            status="completed",
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=self.policy.timeout_seconds,
            estimated_cost_usd=estimated_cost,
            spent_usd=self.ledger.spent_usd,
            fallback_used=False,
            attempts=attempts,
            provider_health=provider_health,
            telemetry=telemetry,
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
        attempts: int,
    ) -> ModelSlaCallResult:
        provider_health = self.health_monitor.current_health().to_metadata()
        if fallback_call is None:
            self.ledger.record(
                operation=operation,
                estimated_cost_usd=estimated_cost_usd,
                status=terminal_status,
                attempts=attempts,
                provider_health_state=provider_health["state"],
            )
            raise ModelBudgetExceeded(error) if terminal_status == "budget_blocked" else RuntimeError(error)
        output = fallback_call()
        self.ledger.record(
            operation=operation,
            estimated_cost_usd=estimated_cost_usd,
            status=status_with_fallback,
            attempts=attempts,
            provider_health_state=provider_health["state"],
        )
        elapsed_seconds = time.monotonic() - started_at
        telemetry = ModelSlaTelemetryRecord(
            operation=operation,
            status=status_with_fallback,
            elapsed_seconds=elapsed_seconds,
            estimated_cost_usd=estimated_cost_usd,
            spent_usd=self.ledger.spent_usd,
            attempts=attempts,
            fallback_used=True,
            provider_health=provider_health,
            error=error,
        )
        return ModelSlaCallResult(
            output=output,
            status=status_with_fallback,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=self.policy.timeout_seconds,
            estimated_cost_usd=estimated_cost_usd,
            spent_usd=self.ledger.spent_usd,
            fallback_used=True,
            attempts=attempts,
            provider_health=provider_health,
            telemetry=telemetry,
            error=error,
        )


__all__ = [
    "ModelBudgetExceeded",
    "ModelCallLedger",
    "ModelProviderHealth",
    "ModelProviderHealthMonitor",
    "ModelProviderHealthState",
    "ModelSlaCallResult",
    "ModelSlaGateway",
    "ModelSlaStatus",
    "ModelSlaTelemetryRecord",
]
