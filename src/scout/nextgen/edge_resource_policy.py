"""Deterministic resource admission for optional edge intelligence work."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


class EdgeResourceSnapshot(SchemaModel):
    schema_version: Literal["scout.edge_resource_snapshot.v0"] = (
        "scout.edge_resource_snapshot.v0"
    )
    observed_at: datetime
    available_memory_mb: int = Field(ge=0)
    swap_used_mb: int = Field(ge=0)
    cpu_temperature_c: float | None = Field(default=None, ge=-50, le=150)
    throttled: bool | None = None
    battery_percent: float | None = Field(default=None, ge=0, le=100)
    source: NonEmptyStr
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_timestamp(self) -> "EdgeResourceSnapshot":
        if self.observed_at.tzinfo is None:
            raise ValueError("edge resource snapshot timestamp must be aware")
        return self


class EdgeBackgroundResourcePolicy(SchemaModel):
    schema_version: Literal["scout.edge_background_resource_policy.v0"] = (
        "scout.edge_background_resource_policy.v0"
    )
    min_available_memory_mb: int = Field(default=2048, ge=0)
    max_swap_used_mb: int = Field(default=512, ge=0)
    max_cpu_temperature_c: float = Field(default=75.0, ge=0, le=150)
    min_battery_percent: float | None = Field(default=20.0, ge=0, le=100)
    max_snapshot_age_seconds: int = Field(default=30, ge=1)
    require_throttle_observation: bool = True
    runtime_safety_truth: Literal[False] = False

    def rejection_reasons(
        self,
        snapshot: EdgeResourceSnapshot,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise ValueError("resource policy evaluation time must be aware")
        reasons: list[str] = []
        age_seconds = (checked_at - snapshot.observed_at).total_seconds()
        if age_seconds < 0 or age_seconds > self.max_snapshot_age_seconds:
            reasons.append("edge resource snapshot is stale")
        if snapshot.available_memory_mb < self.min_available_memory_mb:
            reasons.append("available memory is below the background minimum")
        if snapshot.swap_used_mb > self.max_swap_used_mb:
            reasons.append("swap use exceeds the background maximum")
        if (
            snapshot.cpu_temperature_c is None
            or snapshot.cpu_temperature_c > self.max_cpu_temperature_c
        ):
            reasons.append("CPU temperature is unavailable or above the maximum")
        if snapshot.throttled is True:
            reasons.append("edge runtime is throttled")
        elif snapshot.throttled is None and self.require_throttle_observation:
            reasons.append("edge throttle state is unavailable")
        if (
            self.min_battery_percent is not None
            and snapshot.battery_percent is not None
            and snapshot.battery_percent < self.min_battery_percent
        ):
            reasons.append("battery is below the background minimum")
        return tuple(reasons)


class LinuxEdgeResourceMonitor:
    """Read Linux/Pi resource telemetry without changing hardware state."""

    def __init__(
        self,
        *,
        meminfo_path: Path = Path("/proc/meminfo"),
        thermal_path: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
        throttled_reader: Callable[[], bool | None] | None = None,
        battery_reader: Callable[[], float | None] | None = None,
    ) -> None:
        self._meminfo_path = meminfo_path
        self._thermal_path = thermal_path
        self._throttled_reader = throttled_reader or _read_pi_throttled
        self._battery_reader = battery_reader

    def snapshot(self) -> EdgeResourceSnapshot:
        memory = _read_meminfo(self._meminfo_path)
        return EdgeResourceSnapshot(
            observed_at=datetime.now(UTC),
            available_memory_mb=memory["MemAvailable"] // 1024,
            swap_used_mb=(memory["SwapTotal"] - memory["SwapFree"]) // 1024,
            cpu_temperature_c=_read_temperature(self._thermal_path),
            throttled=self._throttled_reader(),
            battery_percent=(
                self._battery_reader() if self._battery_reader is not None else None
            ),
            source="linux-edge-resource-monitor",
        )


def _read_meminfo(path: Path) -> dict[str, int]:
    required = {"MemAvailable", "SwapTotal", "SwapFree"}
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, raw_value = line.partition(":")
        if not separator or key not in required:
            continue
        values[key] = int(raw_value.strip().split()[0])
    missing = required.difference(values)
    if missing:
        raise RuntimeError(f"Linux meminfo is missing fields: {', '.join(sorted(missing))}")
    return values


def _read_temperature(path: Path) -> float | None:
    try:
        value = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value / 1000 if value > 1000 else value


def _read_pi_throttled() -> bool | None:
    try:
        completed = subprocess.run(
            ("vcgencmd", "get_throttled"),
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or "=" not in completed.stdout:
        return None
    try:
        value = int(completed.stdout.strip().split("=", 1)[1], 16)
    except ValueError:
        return None
    return value != 0


__all__ = [
    "EdgeBackgroundResourcePolicy",
    "EdgeResourceSnapshot",
    "LinuxEdgeResourceMonitor",
]
