"""Read-only local resource monitor for Scout on macOS.

The monitor deliberately uses only short-lived, read-only system commands.  It
does not invoke ``powermetrics`` (which commonly needs elevated privileges),
does not persist samples, and does not expose raw process command lines.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = Path(__file__).with_name("macos_resource_monitor.html")
SCHEMA_VERSION = "scout.macos_resource_snapshot.v0.1"
COMMAND_TIMEOUT_SECONDS = 2.0
DEFAULT_SCOUT_PROCESS_MATCHES = (
    "scout-fusion",
    "scout_ai_os",
    "phase4_admin_runtime",
    "dashboard_workspace_app",
    "run_dashboard_workspace",
    "qgis_worker",
    "scout_pi_runtime",
    "ollama",
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Safe, bounded result from one local command."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str], timeout_seconds: float) -> CommandResult:
        ...


def _run_command(argv: Sequence[str], timeout_seconds: float) -> CommandResult:
    """Run one explicit executable without a shell or inherited input."""

    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(
            returncode=124,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


_TOP_CPU_RE = re.compile(
    r"CPU usage:\s*"
    r"(?P<user>[\d.]+)%\s+user,\s*"
    r"(?P<system>[\d.]+)%\s+sys,\s*"
    r"(?P<idle>[\d.]+)%\s+idle",
    re.IGNORECASE,
)
_PAGE_SIZE_RE = re.compile(r"page size of\s+(?P<size>\d+)\s+bytes", re.IGNORECASE)
_VM_PAGE_RE = re.compile(r"^\s*Pages\s+(?P<name>[^:]+):\s*(?P<count>[\d.,]+)", re.MULTILINE)
_MEMORY_FREE_RE = re.compile(
    r"free percentage:\s*(?P<percent>[\d.]+)%", re.IGNORECASE
)
_PS_THERMAL_RE = re.compile(r"^\s*(?P<name>[A-Za-z0-9_]+)\s*=\s*(?P<value>\d+)", re.MULTILINE)


def parse_top_cpu(text: str) -> dict[str, float] | None:
    """Parse the stable CPU summary emitted by macOS ``top``."""

    match = _TOP_CPU_RE.search(text)
    if not match:
        return None
    values = {name: round(float(value), 2) for name, value in match.groupdict().items()}
    values["active"] = round(max(0.0, 100.0 - values["idle"]), 2)
    return values


def parse_vm_stat(text: str) -> tuple[int, dict[str, int]]:
    """Return page size and normalized page counters from ``vm_stat``."""

    page_size_match = _PAGE_SIZE_RE.search(text)
    page_size = int(page_size_match.group("size")) if page_size_match else 4096
    pages: dict[str, int] = {}
    for match in _VM_PAGE_RE.finditer(text):
        raw_count = match.group("count").rstrip(".").replace(",", "")
        try:
            page_name = f"pages {match.group('name').strip()}"
            pages[page_name.casefold()] = int(float(raw_count))
        except ValueError:
            continue
    return page_size, pages


def parse_memory_pressure(text: str) -> float | None:
    """Parse the OS-reported free-memory percentage, when available."""

    match = _MEMORY_FREE_RE.search(text)
    if not match:
        return None
    return round(float(match.group("percent")), 2)


def parse_pmset_thermal(text: str) -> dict[str, int]:
    """Parse numeric thermal/limit fields from ``pmset -g therm``."""

    values: dict[str, int] = {}
    for match in _PS_THERMAL_RE.finditer(text):
        values[match.group("name")] = int(match.group("value"))
    return values


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value.strip()), 2)
    except (TypeError, ValueError):
        return None


def _bytes_from_pages(pages: Mapping[str, int], name: str, page_size: int) -> int:
    return int(pages.get(name.casefold(), 0)) * page_size


def _pressure_level(free_percent: float | None) -> str:
    if free_percent is None:
        return "unknown"
    if free_percent <= 15:
        return "critical"
    if free_percent <= 30:
        return "elevated"
    return "normal"


def _safe_process_label(command: str) -> str:
    """Derive a non-sensitive label without returning command arguments."""

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return "unknown"

    for index, token in enumerate(tokens):
        if token == "-m" and index + 1 < len(tokens):
            module = tokens[index + 1]
            if module == "uvicorn" and index + 2 < len(tokens):
                return tokens[index + 2].split(":", 1)[0]
            return module
        if token.endswith(".py"):
            return Path(token).stem
        if ":" in token and not token.startswith("-"):
            return token.split(":", 1)[0]
    return Path(tokens[0]).name or "unknown"


def _parse_process_row(line: str) -> dict[str, Any] | None:
    parts = line.strip().split(maxsplit=5)
    if len(parts) != 6:
        return None
    elapsed_and_command = parts[5].split(maxsplit=1)
    if len(elapsed_and_command) != 2:
        return None
    pid = _parse_int(parts[0])
    parent_pid = _parse_int(parts[1])
    cpu_percent = _parse_float(parts[2])
    memory_percent = _parse_float(parts[3])
    rss_kb = _parse_int(parts[4])
    if None in {pid, parent_pid, cpu_percent, memory_percent, rss_kb}:
        return None
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "rss_bytes": int(rss_kb) * 1024,
        "elapsed": elapsed_and_command[0],
        "command": elapsed_and_command[1],
    }


class MacResourceCollector:
    """Collect one point-in-time, best-effort macOS resource snapshot."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        repo_root: Path = ROOT,
        disk_path: str = "/",
        process_matches: Sequence[str] | None = None,
    ) -> None:
        self._runner = runner or _run_command
        self.repo_root = repo_root
        self.disk_path = disk_path
        configured_matches = os.getenv("SCOUT_MONITOR_PROCESS_MATCH", "")
        if process_matches is not None:
            matches = tuple(process_matches)
        elif configured_matches.strip():
            matches = tuple(
                item.strip() for item in configured_matches.split(",") if item.strip()
            )
        else:
            matches = DEFAULT_SCOUT_PROCESS_MATCHES
        root_name = repo_root.name.strip()
        if root_name and root_name.casefold() not in {item.casefold() for item in matches}:
            matches = (*matches, root_name)
        self.process_matches = tuple(matches)

    def _run_tool(self, tool: str, args: Sequence[str] = ()) -> CommandResult:
        executable = shutil.which(tool) or tool
        return self._runner(
            (executable, *args),
            COMMAND_TIMEOUT_SECONDS,
        )

    def _system_facts(self) -> dict[str, str]:
        keys = ("hw.ncpu", "hw.memsize", "hw.model", "kern.osproductversion")
        result = self._run_tool("sysctl", ("-n", *keys))
        lines = [line.strip() for line in result.stdout.splitlines()]
        return {key: value for key, value in zip(keys, lines) if value}

    def snapshot(self) -> dict[str, Any]:
        facts = self._system_facts()
        cpu = self._collect_cpu(facts)
        memory = self._collect_memory(facts)
        disk = self._collect_disk()
        power = self._collect_power()
        thermal = self._collect_thermal()
        scout = self._collect_scout_processes()
        return {
            "schema_version": SCHEMA_VERSION,
            "captured_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            ),
            "host": self._collect_host(facts),
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "power": power,
            "thermal": thermal,
            "scout": scout,
            "overall": self._overall_status(cpu, memory, disk, thermal),
            "boundary": {
                "read_only": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "external_effects": False,
                "scope": "local macOS resource observation",
            },
        }

    def _collect_host(self, facts: Mapping[str, str]) -> dict[str, Any]:
        return {
            "platform": platform.system(),
            "machine": platform.machine() or "unknown",
            "model": facts.get("hw.model") or "Mac model unavailable",
            "os_version": facts.get("kern.osproductversion") or platform.mac_ver()[0] or "unknown",
            "logical_cores": _parse_int(facts.get("hw.ncpu")),
            "name": platform.node() or "MacBook",
            "scout_scope": self.repo_root.name or "scout-fusion",
        }

    def _collect_cpu(self, facts: Mapping[str, str]) -> dict[str, Any]:
        result = self._run_tool("top", ("-l", "1", "-n", "0", "-s", "0"))
        parsed = parse_top_cpu(result.stdout) if result.ok else None
        load_average: dict[str, float] | None
        try:
            one, five, fifteen = os.getloadavg()
            load_average = {
                "one_minute": round(one, 2),
                "five_minutes": round(five, 2),
                "fifteen_minutes": round(fifteen, 2),
            }
        except OSError:
            load_average = None
        if parsed is None:
            return {
                "status": "unavailable",
                "active_percent": None,
                "user_percent": None,
                "system_percent": None,
                "idle_percent": None,
                "logical_cores": _parse_int(facts.get("hw.ncpu")),
                "load_average": load_average,
                "source": "top",
            }
        return {
            "status": "ok",
            "active_percent": parsed["active"],
            "user_percent": parsed["user"],
            "system_percent": parsed["system"],
            "idle_percent": parsed["idle"],
            "logical_cores": _parse_int(facts.get("hw.ncpu")),
            "load_average": load_average,
            "source": "top",
        }

    def _collect_memory(self, facts: Mapping[str, str]) -> dict[str, Any]:
        vm_result = self._run_tool("vm_stat")
        page_size, pages = parse_vm_stat(vm_result.stdout) if vm_result.ok else (4096, {})
        total_bytes = _parse_int(facts.get("hw.memsize"))
        if total_bytes is None or total_bytes <= 0 or not pages:
            return {
                "status": "unavailable",
                "total_bytes": total_bytes,
                "used_bytes": None,
                "available_bytes": None,
                "used_percent": None,
                "pressure": {
                    "status": "unavailable",
                    "level": "unknown",
                    "free_percent": None,
                    "estimated": False,
                    "source": "memory_pressure",
                },
                "source": "vm_stat",
            }

        # inactive pages already include the purgeable portion on macOS; do not
        # add purgeable a second time when estimating available memory.
        available_pages = (
            pages.get("pages free", 0)
            + pages.get("pages speculative", 0)
            + pages.get("pages inactive", 0)
        )
        available_bytes = min(total_bytes, available_pages * page_size)
        used_bytes = max(0, total_bytes - available_bytes)
        used_percent = round(used_bytes / total_bytes * 100.0, 2)

        pressure_result = self._run_tool("memory_pressure", ("-Q",))
        free_percent = parse_memory_pressure(pressure_result.stdout) if pressure_result.ok else None
        pressure_estimated = free_percent is None
        if free_percent is None:
            free_percent = round(available_bytes / total_bytes * 100.0, 2)
        return {
            "status": "ok",
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "available_bytes": available_bytes,
            "used_percent": used_percent,
            "page_size_bytes": page_size,
            "breakdown_bytes": {
                "free": _bytes_from_pages(pages, "pages free", page_size),
                "speculative": _bytes_from_pages(pages, "pages speculative", page_size),
                "active": _bytes_from_pages(pages, "pages active", page_size),
                "inactive": _bytes_from_pages(pages, "pages inactive", page_size),
                "wired": _bytes_from_pages(pages, "pages wired down", page_size),
                "compressed": _bytes_from_pages(
                    pages, "pages occupied by compressor", page_size
                ),
                "purgeable": _bytes_from_pages(pages, "pages purgeable", page_size),
            },
            "pressure": {
                "status": "ok" if not pressure_estimated else "estimated",
                "level": _pressure_level(free_percent),
                "free_percent": free_percent,
                "estimated": pressure_estimated,
                "source": "memory_pressure" if not pressure_estimated else "vm_stat_estimate",
            },
            "source": "vm_stat",
        }

    def _collect_disk(self) -> dict[str, Any]:
        try:
            usage = shutil.disk_usage(self.disk_path)
        except OSError as exc:
            return {
                "status": "unavailable",
                "path": self.disk_path,
                "total_bytes": None,
                "used_bytes": None,
                "free_bytes": None,
                "used_percent": None,
                "error": type(exc).__name__,
                "source": "disk_usage",
            }
        used_percent = round(usage.used / usage.total * 100.0, 2) if usage.total else None
        return {
            "status": "ok",
            "path": self.disk_path,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_percent": used_percent,
            "source": "disk_usage",
        }

    def _collect_power(self) -> dict[str, Any]:
        result = self._run_tool("pmset", ("-g", "batt"))
        if not result.ok:
            return {
                "status": "unavailable",
                "source": "pmset",
                "power_source": None,
                "battery_percent": None,
                "state": None,
            }
        source_match = re.search(r"Now drawing from '([^']+)'", result.stdout)
        battery_percent_match = re.search(r"(?P<percent>\d+)%", result.stdout)
        state = None
        state_match = re.search(
            r";\s*(?P<state>charging|discharging|charged|finishing charge)",
            result.stdout,
            re.IGNORECASE,
        )
        if state_match:
            state = state_match.group("state").lower()
        return {
            "status": "ok",
            "source": "pmset",
            "power_source": source_match.group(1) if source_match else None,
            "battery_percent": (
                int(battery_percent_match.group("percent"))
                if battery_percent_match
                else None
            ),
            "state": state,
        }

    def _collect_thermal(self) -> dict[str, Any]:
        result = self._run_tool("pmset", ("-g", "therm"))
        if not result.ok:
            return {
                "status": "unavailable",
                "thermal_level": None,
                "cpu_speed_limit_percent": None,
                "cpu_scheduler_limit_percent": None,
                "gpu_scheduler_limit_percent": None,
                "throttled": None,
                "temperature_c": None,
                "source": "pmset",
                "note": "Temperature telemetry is intentionally not collected.",
            }
        values = parse_pmset_thermal(result.stdout)
        thermal_level = values.get("Thermal_Level")
        cpu_speed_limit = values.get("CPU_Speed_Limit")
        cpu_scheduler_limit = values.get("CPU_Scheduler_Limit")
        gpu_scheduler_limit = values.get("GPU_Scheduler_Limit")
        limits = (cpu_speed_limit, cpu_scheduler_limit, gpu_scheduler_limit)
        throttled = (
            thermal_level is not None and thermal_level > 0
        ) or any(limit is not None and limit < 100 for limit in limits)
        return {
            "status": "ok",
            "thermal_level": thermal_level,
            "cpu_speed_limit_percent": cpu_speed_limit,
            "cpu_scheduler_limit_percent": cpu_scheduler_limit,
            "gpu_scheduler_limit_percent": gpu_scheduler_limit,
            "throttled": throttled,
            "temperature_c": None,
            "source": "pmset",
            "note": "Temperature telemetry is intentionally not collected.",
        }

    def _collect_scout_processes(self) -> dict[str, Any]:
        result = self._run_tool(
            "ps",
            ("-axo", "pid=,ppid=,%cpu=,%mem=,rss=,etime=,command="),
        )
        if not result.ok:
            return {
                "status": "unavailable",
                "process_count": 0,
                "cpu_percent": None,
                "memory_percent": None,
                "rss_bytes": None,
                "processes": [],
                "match_scope": list(self.process_matches),
                "source": "ps",
            }
        processes: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parsed = _parse_process_row(line)
            if parsed is None or int(parsed["pid"]) == os.getpid():
                continue
            command = str(parsed.pop("command"))
            if not any(term.casefold() in command.casefold() for term in self.process_matches):
                continue
            parsed["label"] = _safe_process_label(command)
            processes.append(parsed)
        processes.sort(key=lambda item: (float(item["cpu_percent"]), int(item["rss_bytes"])), reverse=True)
        visible_processes = processes[:12]
        return {
            "status": "detected" if processes else "not_detected",
            "process_count": len(processes),
            "cpu_percent": round(sum(float(item["cpu_percent"]) for item in processes), 2),
            "memory_percent": round(sum(float(item["memory_percent"]) for item in processes), 2),
            "rss_bytes": sum(int(item["rss_bytes"]) for item in processes),
            "processes": visible_processes,
            "match_scope": list(self.process_matches),
            "source": "ps",
        }

    @staticmethod
    def _overall_status(
        cpu: Mapping[str, Any],
        memory: Mapping[str, Any],
        disk: Mapping[str, Any],
        thermal: Mapping[str, Any],
    ) -> dict[str, Any]:
        observations: list[dict[str, str]] = []
        active = cpu.get("active_percent")
        if isinstance(active, (float, int)) and active >= 85:
            observations.append({"level": "attention", "code": "cpu_high", "label": "CPU 使用率偏高"})
        memory_pressure = memory.get("pressure", {})
        if memory_pressure.get("level") in {"elevated", "critical"}:
            observations.append(
                {
                    "level": "attention",
                    "code": "memory_pressure",
                    "label": f"記憶體壓力 {memory_pressure.get('level')}",
                }
            )
        disk_percent = disk.get("used_percent")
        if isinstance(disk_percent, (float, int)) and disk_percent >= 90:
            observations.append({"level": "attention", "code": "disk_high", "label": "系統磁碟使用率偏高"})
        if thermal.get("throttled") is True:
            observations.append({"level": "attention", "code": "thermal_limit", "label": "觀察到效能限制"})
        required_statuses = (cpu.get("status"), memory.get("status"), disk.get("status"))
        if observations:
            status = "attention"
        elif not all(status == "ok" for status in required_statuses):
            status = "partial"
        else:
            status = "nominal"
        return {
            "status": status,
            "observation_count": len(observations),
            "observations": observations,
            "summary": {
                "nominal": "目前沒有資源注意事項",
                "attention": "有資源注意事項，請檢視詳細數值",
                "partial": "部分系統資料無法取得",
            }[status],
        }


def create_resource_monitor_router(
    *,
    collector: MacResourceCollector | None = None,
    prefix: str = "",
) -> APIRouter:
    """Create read-only monitor routes for standalone or Dashboard hosting."""

    resource_collector = collector or MacResourceCollector()
    router = APIRouter(prefix=prefix, tags=["resource-monitor"])
    index_path = "/" if not prefix else ""

    @router.get(index_path, response_class=FileResponse)
    def index() -> FileResponse:
        return FileResponse(HTML_PATH, media_type="text/html")

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "scout-macos-resource-monitor",
            "read_only": True,
            "platform": platform.system(),
        }

    @router.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        return resource_collector.snapshot()

    return router


def create_resource_monitor_app(
    *,
    collector: MacResourceCollector | None = None,
) -> FastAPI:
    """Create the local read-only monitor application."""

    app = FastAPI(
        title="Scout macOS Resource Monitor",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(create_resource_monitor_router(collector=collector))
    return app


app = create_resource_monitor_app()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve a read-only local Scout macOS resource monitor."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8877, type=int)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CommandResult",
    "MacResourceCollector",
    "SCHEMA_VERSION",
    "app",
    "create_resource_monitor_router",
    "create_resource_monitor_app",
    "main",
    "parse_memory_pressure",
    "parse_pmset_thermal",
    "parse_top_cpu",
    "parse_vm_stat",
]
