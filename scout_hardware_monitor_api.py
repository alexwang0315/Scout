"""Read-only HTTP interface to the independent Scout hardware monitor.

Reading this API never samples hardware, sends notifications, or changes state.
Run on loopback; a Dashboard backend can proxy the fixed API routes to its UI.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware


PREFIX = "/api/v1/hardware-monitor"
SCHEMA_VERSION = "scout.hardware-monitor.api.v1"
DEFAULT_STATE = Path.home() / ".local/state/scout-hardware-monitor"
PORT = 9151
STALE_AFTER_SECONDS = 150
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_HISTORY_BYTES = 8 * 1024 * 1024
Health = Literal["ok", "warning", "critical"]
Percent = Annotated[float, Field(ge=0, le=100)]
NonNegative = Annotated[int, Field(ge=0)]


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class Power(PublicModel):
    status: Literal["ok", "unavailable"]
    captured_at: AwareDatetime | None = None
    age_seconds: float | None = None
    battery_percent: Percent | None = None
    flow: Literal["charging", "discharging", "idle"] | None = None
    battery_power_w: float | None = None
    battery_voltage_mv: NonNegative | None = None
    battery_current_ma: int | None = None
    remaining_capacity_mah: NonNegative | None = None
    cell_voltage_mv: list[NonNegative] | None = None
    ups_vbus_power_mw: NonNegative | None = None
    ext5v_v: float | None = None
    throttled_hex: str | None = None
    active_throttle_bits: NonNegative | None = None
    historical_throttle_bits: NonNegative | None = None

    @model_validator(mode="after")
    def require_ok_metrics(self) -> Power:
        if self.status == "ok" and any(getattr(self, field) is None for field in (
            "captured_at", "battery_percent", "flow", "battery_power_w", "battery_voltage_mv",
            "battery_current_ma", "cell_voltage_mv", "ext5v_v", "active_throttle_bits",
        )):
            raise ValueError("healthy power telemetry requires its measured fields")
        return self


class Memory(PublicModel):
    total_bytes: NonNegative
    used_bytes: NonNegative
    available_bytes: NonNegative
    used_percent: Percent
    swap_total_bytes: NonNegative
    swap_used_bytes: NonNegative


class Disk(PublicModel):
    mount: str
    device: str
    total_bytes: NonNegative
    used_bytes: NonNegative
    available_bytes: NonNegative
    used_percent: Percent
    inode_used_percent: Percent | None = None
    read_only: bool


class Sensor(PublicModel):
    name: str
    source: str
    temperature_c: float | None = None
    rpm: NonNegative | None = None


class Alert(PublicModel):
    severity: Literal["warning", "critical"]
    message: str


class Threshold(PublicModel):
    warning: float
    critical: float


class Snapshot(PublicModel):
    captured_at: AwareDatetime
    host: str
    status: Health
    uptime_seconds: Annotated[float, Field(ge=0)]
    cpu_count: Annotated[int, Field(gt=0)]
    cpu_used_percent: Percent | None = None
    load_average: tuple[float, float, float]
    power: Power
    memory: Memory | None = None
    disks: list[Disk]
    sensors: list[Sensor]
    alerts: dict[str, Alert]
    errors: dict[str, str]
    thresholds: dict[str, Threshold | float]


class Freshness(PublicModel):
    state: Literal["fresh", "stale", "missing", "invalid", "unreadable"]
    captured_at: AwareDatetime | None = None
    age_seconds: float | None = None
    sample_interval_seconds: int = 60
    stale_after_seconds: int = STALE_AFTER_SECONDS


class StatusResponse(PublicModel):
    schema_version: str = SCHEMA_VERSION
    server_time: AwareDatetime
    status: Literal["ok", "warning", "critical", "stale", "unavailable"]
    summary: str
    freshness: Freshness
    data: Snapshot | None
    next_steps: list[str]
    read_only: bool = True


class Event(PublicModel):
    captured_at: AwareDatetime
    events: list[str]


class ListMeta(PublicModel):
    limit: int
    count: int
    order: Literal["oldest_first"] = "oldest_first"
    has_more: bool = False
    scan_truncated: bool = False
    skipped_invalid_records: int = 0


class HistoryResponse(PublicModel):
    schema_version: str = SCHEMA_VERSION
    server_time: AwareDatetime
    status: Literal["ok", "partial", "unavailable"]
    summary: str
    items: list[Snapshot]
    meta: ListMeta


class EventsResponse(PublicModel):
    schema_version: str = SCHEMA_VERSION
    server_time: AwareDatetime
    status: Literal["ok", "partial", "unavailable"]
    summary: str
    items: list[Event]
    meta: ListMeta


def read_status(state_dir: Path, now: datetime | None = None) -> StatusResponse:
    now = now or datetime.now(timezone.utc)
    try:
        with (state_dir / "status.json").open("rb") as stream:
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot too large")
        snapshot = Snapshot.model_validate_json(raw)
        age = (now - snapshot.captured_at).total_seconds()
        if age < -5:
            raise ValueError("future snapshot")
    except FileNotFoundError:
        reason = "missing"
    except OSError:
        reason = "unreadable"
    except ValueError:
        reason = "invalid"
    else:
        stale = age > STALE_AFTER_SECONDS
        status = "stale" if stale else snapshot.status
        summaries = {"ok": "Scout 硬體指標正常", "warning": "Scout 有硬體警告",
                     "critical": "Scout 有嚴重硬體告警", "stale": "監控資料已過期，以下為最後一次採樣"}
        return StatusResponse(
            server_time=now, status=status, summary=summaries[status], data=snapshot,
            freshness=Freshness(state="stale" if stale else "fresh", captured_at=snapshot.captured_at,
                                age_seconds=round(max(0, age), 3)),
            next_steps=["檢查 Scout 監控排程是否仍在執行"] if stale
            else [a.message for a in snapshot.alerts.values()],
        )
    return StatusResponse(server_time=now, status="unavailable", data=None,
                          summary="目前無法取得有效監控結果", freshness=Freshness(state=reason),
                          next_steps=["檢查監控排程與本機狀態檔"])


def read_records(state_dir: Path, filename: str, model: type[Snapshot] | type[Event], limit: int) -> tuple[list, ListMeta]:
    """Latest records across rotation, with a fixed read budget and honest gaps."""
    records = []
    seen = set()
    budget = MAX_HISTORY_BYTES
    meta = ListMeta(limit=limit, count=0)
    paths = [state_dir / (filename + suffix) for suffix in ("", ".1", ".2", ".3")]
    for index, path in enumerate(paths):
        try:
            with path.open("rb") as stream:
                size = stream.seek(0, 2)
                offset = max(0, size - budget)
                stream.seek(offset)
                content = stream.read(budget)
        except FileNotFoundError:
            continue
        budget -= len(content)
        lines = content.split(b"\n")[:-1]  # Concurrent unfinished appends are not records.
        if offset:
            lines = lines[1:]
        for line in reversed(lines):
            try:
                record = model.model_validate_json(line)
            except ValueError:
                meta.skipped_invalid_records += 1
                continue
            identity = record.captured_at
            if identity in seen:
                continue
            seen.add(identity)
            records.append(record)
            if len(records) > limit:
                meta.has_more = True
                records = records[:limit]
                break
        if meta.has_more:
            break
        if offset or (budget == 0 and index < len(paths) - 1):
            meta.scan_truncated = meta.has_more = True
            break
    records.sort(key=lambda record: record.captured_at)
    meta.count = len(records)
    return records, meta


def create_hardware_monitor_router(*, state_dir: Path = DEFAULT_STATE) -> APIRouter:
    router = APIRouter(prefix=PREFIX, tags=["hardware-monitor"])
    root = Path(state_dir).expanduser().resolve()

    @router.get("/status", response_model=StatusResponse,
                responses={503: {"model": StatusResponse, "description": "Missing, invalid, or stale monitor data"}})
    def status(response: Response) -> StatusResponse:
        """Last sampled values. HTTP reads never trigger a new hardware sample."""
        result = read_status(root)
        response.headers["Cache-Control"] = "no-store"
        if result.status in {"stale", "unavailable"}:
            response.status_code = 503
            response.headers["Retry-After"] = "60"
        return result

    def listing(filename: str, model: type[Snapshot] | type[Event], limit: int, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        try:
            items, meta = read_records(root, filename, model, limit)
            status = "partial" if meta.skipped_invalid_records or meta.scan_truncated else "ok"
            summary = f"已讀取 {len(items)} 筆紀錄" + ("，部分紀錄不可用" if status == "partial" else "")
        except OSError:
            response.status_code = 503
            items, meta, status, summary = [], ListMeta(limit=limit, count=0), "unavailable", "無法讀取監控紀錄"
        return {"server_time": datetime.now(timezone.utc), "status": status,
                "summary": summary, "items": items, "meta": meta}

    @router.get("/history", response_model=HistoryResponse, responses={503: {"model": HistoryResponse}})
    def history(response: Response, limit: Annotated[int, Query(ge=1, le=1440)] = 60) -> dict:
        """Latest N samples in chronological order; retention and gaps are explicit."""
        return listing("history.jsonl", Snapshot, limit, response)

    @router.get("/events", response_model=EventsResponse, responses={503: {"model": EventsResponse}})
    def events(response: Response, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
        """Latest N event batches in chronological order. No events is an empty list."""
        return listing("events.jsonl", Event, limit, response)

    return router


def create_hardware_monitor_app(*, state_dir: Path = DEFAULT_STATE) -> FastAPI:
    app = FastAPI(title="Scout Hardware Monitor API", version="1.0.0",
                  description="Read-only monitor snapshots, history and events. Loopback access; proxy through the Dashboard backend.")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
    app.include_router(create_hardware_monitor_router(state_dir=state_dir))

    @app.get("/healthz")
    def healthz(response: Response) -> dict:
        """API liveness only. Use /status to assess the hardware monitor."""
        response.headers["Cache-Control"] = "no-store"
        return {"status": "ok", "service": "scout-hardware-monitor-api", "read_only": True}

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    import uvicorn

    uvicorn.run(create_hardware_monitor_app(state_dir=args.state_dir), host="127.0.0.1",
                port=args.port, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
