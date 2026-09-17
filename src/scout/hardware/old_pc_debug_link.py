"""Old PC debug-agent link receipts for Scout hardware triage."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib import request
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import Field, ValidationError

from scout.schemas.base import NonEmptyStr, SchemaModel

DebugSignalStatus = Literal["ok", "degraded", "missing", "unknown", "critical"]
OldPcDebugTransport = Literal["usb_gadget_ethernet", "loopback_smoke", "manual_file"]
OldPcDisposition = Literal["USABLE_HEADLESS", "USABLE_WITH_LIMITS", "RETIRE", "INCONCLUSIVE"]
WatchdogStatus = Literal["report_received", "report_missing"]

ARTIFACT_KIND_REPORT = "scout_old_pc_debug_report.v0"
ARTIFACT_KIND_RECEIPT = "scout_old_pc_debug_receipt.v0"
ARTIFACT_KIND_WATCHDOG = "scout_old_pc_debug_watchdog_result.v0"
DEFAULT_OLD_PC_DEBUG_EVIDENCE_DIR = Path("/data/scout/admin/ingress/old_pc_debug")

OLD_PC_DEBUG_BOUNDARY: dict[str, bool] = {
    "evidence_only": True,
    "candidate_only": True,
    "not_safety_truth": True,
    "debug_evidence_write_allowed": True,
    "debug_evidence_write_performed": False,
    "local_usb_peer_send_performed": False,
    "external_internet_required": False,
    "third_party_send_performed": False,
    "hardware_control_allowed": False,
    "hardware_control_performed": False,
    "provider_control_allowed": False,
    "outbound_send_allowed": False,
    "outbound_sent": False,
    "phase1_l0_l4_state_mutation_allowed": False,
    "phase1_l0_l4_state_mutated": False,
    "phase1_runtime_safety_truth": False,
    "phase1_runtime_mutated": False,
    "safety_api_mutation_allowed": False,
    "safety_api_called": False,
    "runtime_ingest_performed": False,
    "provider_values_are_scout_truth": False,
    "secret_values_included": False,
}

_FORBIDDEN_TRUE_KEYS = {
    key
    for key, value in OLD_PC_DEBUG_BOUNDARY.items()
    if value is False
    and key
    not in {
        "debug_evidence_write_performed",
        "local_usb_peer_send_performed",
    }
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class OldPcDebugSignal(SchemaModel):
    """One bounded, source-tagged hardware signal from the old PC."""

    status: DebugSignalStatus
    summary: NonEmptyStr
    evidence: dict[str, Any] = Field(default_factory=dict)


class OldPcDebugReport(SchemaModel):
    """Report produced by the old PC debug agent."""

    artifact_kind: Literal["scout_old_pc_debug_report.v0"] = ARTIFACT_KIND_REPORT
    report_id: NonEmptyStr = Field(default_factory=lambda: f"old-pc-debug-report-{uuid4()}")
    subject_ref: NonEmptyStr
    captured_at: str = Field(default_factory=_now_iso)
    producer: NonEmptyStr = "old_pc_debug_agent"
    transport: OldPcDebugTransport
    agent: OldPcDebugSignal
    boot: OldPcDebugSignal
    usb_link: OldPcDebugSignal
    lan: OldPcDebugSignal
    display: OldPcDebugSignal
    storage: OldPcDebugSignal
    thermal: OldPcDebugSignal
    platform: dict[str, Any] = Field(default_factory=dict)
    observations: list[str] = Field(default_factory=list)
    boundary: dict[str, bool] = Field(default_factory=lambda: old_pc_debug_boundary())

    def assert_safe_boundary(self) -> None:
        assert_old_pc_debug_boundary(self.boundary)


class OldPcDebugReceipt(SchemaModel):
    """Scout-side receipt proving a debug report crossed the selected link."""

    artifact_kind: Literal["scout_old_pc_debug_receipt.v0"] = ARTIFACT_KIND_RECEIPT
    receipt_id: NonEmptyStr = Field(default_factory=lambda: f"old-pc-debug-receipt-{uuid4()}")
    received_at: str = Field(default_factory=_now_iso)
    transport_received: bool = True
    report: OldPcDebugReport
    disposition: OldPcDisposition
    decision_reasons: list[str]
    next_action: NonEmptyStr
    boundary: dict[str, bool] = Field(default_factory=lambda: old_pc_debug_boundary())

    def assert_safe_boundary(self) -> None:
        assert_old_pc_debug_boundary(self.boundary)


class OldPcDebugWatchdogResult(SchemaModel):
    """One-shot watchdog result for the old PC debug-agent trial."""

    artifact_kind: Literal["scout_old_pc_debug_watchdog_result.v0"] = ARTIFACT_KIND_WATCHDOG
    watchdog_id: NonEmptyStr = Field(default_factory=lambda: f"old-pc-debug-watchdog-{uuid4()}")
    subject_ref: NonEmptyStr
    observed_at: str = Field(default_factory=_now_iso)
    timeout_seconds: float
    status: WatchdogStatus
    receipt_id: str | None = None
    disposition: OldPcDisposition
    decision_reasons: list[str]
    next_action: NonEmptyStr
    boundary: dict[str, bool] = Field(default_factory=lambda: old_pc_debug_boundary())

    def assert_safe_boundary(self) -> None:
        assert_old_pc_debug_boundary(self.boundary)


class OldPcDebugReceiptStore:
    """Append-only Scout-side store for old PC debug receipts."""

    def __init__(self, evidence_dir: Path | str = DEFAULT_OLD_PC_DEBUG_EVIDENCE_DIR):
        self.evidence_dir = Path(evidence_dir).expanduser()

    @property
    def latest_receipt_path(self) -> Path:
        return self.evidence_dir / "old_pc_debug_latest_receipt.json"

    @property
    def receipt_jsonl_path(self) -> Path:
        return self.evidence_dir / "old_pc_debug_receipts.jsonl"

    @property
    def latest_watchdog_path(self) -> Path:
        return self.evidence_dir / "old_pc_debug_latest_watchdog.json"

    def ingest(self, payload: OldPcDebugReport | dict[str, Any]) -> OldPcDebugReceipt:
        receipt = build_old_pc_debug_receipt(payload, transport_received=True)
        boundary = old_pc_debug_boundary(
            debug_evidence_write_performed=True,
            local_usb_peer_send_performed=receipt.report.boundary.get(
                "local_usb_peer_send_performed",
                False,
            ),
        )
        receipt = receipt.model_copy(update={"boundary": boundary})
        receipt.assert_safe_boundary()
        self._write_json(self.latest_receipt_path, receipt.model_dump(mode="json"))
        self._append_jsonl(self.receipt_jsonl_path, receipt.model_dump(mode="json"))
        return receipt

    def latest_receipt(self) -> OldPcDebugReceipt | None:
        if not self.latest_receipt_path.exists():
            return None
        return OldPcDebugReceipt.model_validate(
            json.loads(self.latest_receipt_path.read_text(encoding="utf-8"))
        )

    def write_watchdog_result(self, result: OldPcDebugWatchdogResult) -> None:
        result.assert_safe_boundary()
        self._write_json(self.latest_watchdog_path, result.model_dump(mode="json"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def old_pc_debug_boundary(**overrides: bool) -> dict[str, bool]:
    boundary = dict(OLD_PC_DEBUG_BOUNDARY)
    boundary.update(overrides)
    assert_old_pc_debug_boundary(boundary)
    return boundary


def assert_old_pc_debug_boundary(boundary: dict[str, Any]) -> None:
    forbidden_true = {
        key: value
        for key, value in boundary.items()
        if key in _FORBIDDEN_TRUE_KEYS and value is True
    }
    if forbidden_true:
        raise ValueError(
            "old PC debug boundary cannot enable runtime effects: "
            f"{sorted(forbidden_true)}"
        )
    for required_true in ("evidence_only", "candidate_only", "not_safety_truth"):
        if boundary.get(required_true) is not True:
            raise ValueError(f"old PC debug boundary requires {required_true}=true")
    if boundary.get("secret_values_included") is True:
        raise ValueError("old PC debug reports must not include secret values")


def build_old_pc_debug_receipt(
    payload: OldPcDebugReport | dict[str, Any],
    *,
    transport_received: bool = True,
) -> OldPcDebugReceipt:
    report = payload if isinstance(payload, OldPcDebugReport) else OldPcDebugReport.model_validate(payload)
    report.assert_safe_boundary()
    disposition, decision_reasons, next_action = evaluate_old_pc_debug_report(
        report,
        transport_received=transport_received,
    )
    receipt = OldPcDebugReceipt(
        transport_received=transport_received,
        report=report,
        disposition=disposition,
        decision_reasons=decision_reasons,
        next_action=next_action,
    )
    receipt.assert_safe_boundary()
    return receipt


def build_old_pc_debug_watchdog_result(
    receipt: OldPcDebugReceipt | None,
    *,
    subject_ref: str,
    timeout_seconds: float,
) -> OldPcDebugWatchdogResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if receipt is None:
        result = OldPcDebugWatchdogResult(
            subject_ref=subject_ref,
            timeout_seconds=timeout_seconds,
            status="report_missing",
            disposition="RETIRE",
            decision_reasons=[
                "No old-PC debug-agent report reached Scout inside the watchdog window.",
                "Do not buy additional video, RJ45, capture, or adapter hardware only to keep qualifying this machine.",
            ],
            next_action="Retire the old PC candidate and move the replacement decision forward.",
        )
        result.assert_safe_boundary()
        return result

    result = OldPcDebugWatchdogResult(
        subject_ref=subject_ref,
        timeout_seconds=timeout_seconds,
        status="report_received",
        receipt_id=receipt.receipt_id,
        disposition=receipt.disposition,
        decision_reasons=list(receipt.decision_reasons),
        next_action=receipt.next_action,
    )
    result.assert_safe_boundary()
    return result


def evaluate_old_pc_debug_report(
    report: OldPcDebugReport,
    *,
    transport_received: bool,
) -> tuple[OldPcDisposition, list[str], str]:
    report.assert_safe_boundary()
    reasons: list[str] = []
    if transport_received:
        reasons.append("Scout received the old-PC debug-agent report over the configured local link.")

    fatal_required = [
        name
        for name, signal in (("boot", report.boot), ("agent", report.agent))
        if signal.status in {"missing", "critical"}
    ]
    if not transport_received and report.usb_link.status in {"missing", "critical"}:
        fatal_required.append("usb_link")
    if fatal_required:
        reasons.append(f"Required self-proof signal failed: {', '.join(fatal_required)}.")
        return (
            "RETIRE",
            reasons,
            "Stop qualifying this old PC and do not buy additional observation hardware for it.",
        )

    required_unknown = [
        name
        for name, signal in (("boot", report.boot), ("agent", report.agent))
        if signal.status == "unknown"
    ]
    if not transport_received and report.usb_link.status == "unknown":
        required_unknown.append("usb_link")
    if required_unknown:
        reasons.append(f"Required self-proof signal is unknown: {', '.join(required_unknown)}.")
        return (
            "INCONCLUSIVE",
            reasons,
            "Rerun the same USB/local-link trial once; retire if it remains inconclusive.",
        )

    critical_limits = [
        name
        for name, signal in (("storage", report.storage), ("thermal", report.thermal))
        if signal.status == "critical"
    ]
    if critical_limits:
        reasons.append(f"Critical post-boot hardware risk observed: {', '.join(critical_limits)}.")
        return (
            "RETIRE",
            reasons,
            "Retire the old PC candidate; the machine booted but is not a reliable Scout helper.",
        )

    if report.lan.status in {"missing", "degraded", "unknown"}:
        reasons.append("RJ45/LAN is not required for the headless USB debug role.")
    if report.display.status in {"missing", "degraded", "unknown"}:
        reasons.append("Display output is not required once Ubuntu and the debug agent self-report.")

    degraded_limits = [
        name
        for name, signal in (
            ("boot", report.boot),
            ("agent", report.agent),
            ("storage", report.storage),
            ("thermal", report.thermal),
        )
        if signal.status == "degraded"
    ]
    if degraded_limits:
        reasons.append(f"Usable, but degraded signal remains: {', '.join(degraded_limits)}.")
        return (
            "USABLE_WITH_LIMITS",
            reasons,
            "Keep this old PC only for bounded helper/debug work; do not promote it to a reliable base system.",
        )

    reasons.append("Ubuntu boot, debug-agent execution, and Scout receipt are enough self-proof for headless use.")
    return (
        "USABLE_HEADLESS",
        reasons,
        "Keep the old PC only as a USB/headless debug helper unless a future task proves broader reliability.",
    )


def build_simulated_old_pc_report(
    *,
    subject_ref: str = "old-pc-candidate",
    transport: OldPcDebugTransport = "loopback_smoke",
) -> OldPcDebugReport:
    return OldPcDebugReport(
        subject_ref=subject_ref,
        transport=transport,
        agent=OldPcDebugSignal(
            status="ok",
            summary="debug-agent process built and sent a bounded report",
            evidence={"agent_mode": "simulated_old_pc"},
        ),
        boot=OldPcDebugSignal(
            status="ok",
            summary="Ubuntu userspace equivalent reached the debug-agent entrypoint",
            evidence={"boot_path": "mac_loopback_smoke"},
        ),
        usb_link=OldPcDebugSignal(
            status="ok",
            summary="local loopback smoke stands in for the later USB gadget Ethernet route",
            evidence={"transport": transport},
        ),
        lan=OldPcDebugSignal(
            status="missing",
            summary="fixture represents the damaged or untrusted RJ45 path",
            evidence={"required_for_debug_role": False},
        ),
        display=OldPcDebugSignal(
            status="missing",
            summary="fixture represents no usable display output",
            evidence={"required_for_debug_role": False},
        ),
        storage=OldPcDebugSignal(
            status="ok",
            summary="fixture storage has enough space for debug-agent evidence",
            evidence={"free_percent": 50.0},
        ),
        thermal=OldPcDebugSignal(
            status="ok",
            summary="fixture thermal state is not critical",
            evidence={"max_celsius": 45.0},
        ),
        platform={
            "simulation": True,
            "host_system": platform.system(),
            "host_machine": platform.machine(),
        },
        observations=[
            "Mac loopback validates Scout ingest, receipt writing, and watchdog decision logic.",
            "A real old-PC trial still needs Ubuntu boot plus USB gadget Ethernet delivery.",
        ],
        boundary=old_pc_debug_boundary(local_usb_peer_send_performed=True),
    )


def collect_current_host_debug_report(
    *,
    subject_ref: str,
    transport: OldPcDebugTransport,
) -> OldPcDebugReport:
    platform_payload = _platform_payload()
    return OldPcDebugReport(
        subject_ref=subject_ref,
        transport=transport,
        agent=OldPcDebugSignal(
            status="ok",
            summary="debug-agent process reached the report builder",
            evidence={"python": platform.python_version()},
        ),
        boot=OldPcDebugSignal(
            status="ok",
            summary="operating system booted far enough to execute the debug agent",
            evidence={
                "system": platform_payload.get("system"),
                "uptime_seconds": _uptime_seconds(),
            },
        ),
        usb_link=OldPcDebugSignal(
            status="unknown",
            summary="Scout receipt proves the link after the HTTP post completes",
            evidence={"transport": transport},
        ),
        lan=_linux_lan_signal(),
        display=_linux_display_signal(),
        storage=_storage_signal(),
        thermal=_linux_thermal_signal(),
        platform=platform_payload,
        observations=[
            "Report is read-only and intentionally omits environment variables and raw logs.",
            "Receipt arrival is the proof that the local Scout link worked.",
        ],
        boundary=old_pc_debug_boundary(local_usb_peer_send_performed=True),
    )


def post_old_pc_debug_report(
    report: OldPcDebugReport,
    *,
    ingest_url: str,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    report.assert_safe_boundary()
    body = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode("utf-8")
    req = request.Request(
        ingest_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8")
    payload = json.loads(response_body)
    if not isinstance(payload, dict):
        raise ValueError("Scout old-PC debug ingest returned a non-object response")
    return payload


def create_old_pc_debug_router(
    *,
    store: OldPcDebugReceiptStore | None = None,
    evidence_dir: Path | str | None = None,
) -> APIRouter:
    resolved_store = store or OldPcDebugReceiptStore(
        evidence_dir or os.getenv("SCOUT_OLD_PC_DEBUG_EVIDENCE_DIR") or DEFAULT_OLD_PC_DEBUG_EVIDENCE_DIR
    )
    router = APIRouter(prefix="/hardware/old-pc-debug", tags=["old-pc-debug"])

    @router.post("/reports")
    def ingest_report(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            receipt = resolved_store.ingest(payload)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return receipt.model_dump(mode="json")

    @router.get("/latest")
    def latest_report() -> dict[str, Any]:
        receipt = resolved_store.latest_receipt()
        if receipt is None:
            raise HTTPException(status_code=404, detail="old PC debug receipt not found")
        return receipt.model_dump(mode="json")

    return router


def create_old_pc_debug_app(
    *,
    store: OldPcDebugReceiptStore | None = None,
    evidence_dir: Path | str | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Old PC Debug Link")
    app.include_router(create_old_pc_debug_router(store=store, evidence_dir=evidence_dir))
    return app


def _platform_payload() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": _truncate(platform.version(), limit=160),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "boot_id": _read_text(Path("/proc/sys/kernel/random/boot_id")),
    }


def _linux_lan_signal() -> OldPcDebugSignal:
    net_root = Path("/sys/class/net")
    if not net_root.exists():
        return OldPcDebugSignal(
            status="unknown",
            summary="Linux network sysfs is unavailable on this host",
            evidence={"sysfs": str(net_root)},
        )
    interfaces: list[dict[str, Any]] = []
    for iface in sorted(net_root.iterdir()):
        name = iface.name
        if name == "lo" or (iface / "wireless").exists():
            continue
        type_value = _read_text(iface / "type")
        if type_value not in {"1", None}:
            continue
        carrier = _read_text(iface / "carrier")
        operstate = _read_text(iface / "operstate")
        interfaces.append(
            {
                "name": name,
                "carrier": carrier,
                "operstate": operstate,
                "driver_bound": (iface / "device" / "driver").exists(),
            }
        )
    if not interfaces:
        return OldPcDebugSignal(
            status="missing",
            summary="no wired Ethernet interface appeared in Linux sysfs",
            evidence={"interface_count": 0},
        )
    if any(item.get("carrier") == "1" for item in interfaces):
        status: DebugSignalStatus = "ok"
        summary = "at least one wired Ethernet interface reports carrier"
    else:
        status = "degraded"
        summary = "wired Ethernet interface exists but no carrier is reported"
    return OldPcDebugSignal(
        status=status,
        summary=summary,
        evidence={"interfaces": interfaces[:8]},
    )


def _linux_display_signal() -> OldPcDebugSignal:
    drm_root = Path("/sys/class/drm")
    connectors: list[dict[str, Any]] = []
    if drm_root.exists():
        for connector in sorted(drm_root.glob("card*-*")):
            status = _read_text(connector / "status")
            if status is None:
                continue
            connectors.append({"name": connector.name, "status": status})
    display_controller_count = _pci_display_controller_count()
    if any(item.get("status") == "connected" for item in connectors):
        return OldPcDebugSignal(
            status="ok",
            summary="DRM reports at least one connected display connector",
            evidence={
                "connectors": connectors[:12],
                "pci_display_controller_count": display_controller_count,
            },
        )
    if connectors or display_controller_count > 0:
        return OldPcDebugSignal(
            status="degraded",
            summary="display controller exists but no connected display output is reported",
            evidence={
                "connectors": connectors[:12],
                "pci_display_controller_count": display_controller_count,
            },
        )
    return OldPcDebugSignal(
        status="missing",
        summary="no DRM connector or PCI display controller was observed",
        evidence={
            "connectors": [],
            "pci_display_controller_count": display_controller_count,
        },
    )


def _storage_signal() -> OldPcDebugSignal:
    usage = shutil.disk_usage("/")
    free_percent = round((usage.free / usage.total) * 100, 2) if usage.total else 0.0
    evidence = {
        "mount": "/",
        "total_gb": round(usage.total / (1024**3), 2),
        "free_gb": round(usage.free / (1024**3), 2),
        "free_percent": free_percent,
        "smart_read": False,
    }
    if free_percent < 5:
        return OldPcDebugSignal(
            status="critical",
            summary="root filesystem has critically low free space",
            evidence=evidence,
        )
    if free_percent < 15:
        return OldPcDebugSignal(
            status="degraded",
            summary="root filesystem free space is low",
            evidence=evidence,
        )
    return OldPcDebugSignal(
        status="ok",
        summary="root filesystem has enough free space for debug evidence",
        evidence=evidence,
    )


def _linux_thermal_signal() -> OldPcDebugSignal:
    thermal_root = Path("/sys/class/thermal")
    temps: list[float] = []
    if thermal_root.exists():
        for temp_path in sorted(thermal_root.glob("thermal_zone*/temp"))[:16]:
            raw = _read_text(temp_path)
            if raw is None:
                continue
            try:
                temps.append(float(raw) / 1000.0)
            except ValueError:
                continue
    if not temps:
        return OldPcDebugSignal(
            status="unknown",
            summary="no Linux thermal zone temperatures were readable",
            evidence={"thermal_zone_count": 0},
        )
    max_celsius = round(max(temps), 1)
    evidence = {"thermal_zone_count": len(temps), "max_celsius": max_celsius}
    if max_celsius >= 85:
        return OldPcDebugSignal(
            status="critical",
            summary="thermal reading is critical",
            evidence=evidence,
        )
    if max_celsius >= 75:
        return OldPcDebugSignal(
            status="degraded",
            summary="thermal reading is high",
            evidence=evidence,
        )
    return OldPcDebugSignal(
        status="ok",
        summary="thermal readings are not critical",
        evidence=evidence,
    )


def _pci_display_controller_count() -> int:
    pci_root = Path("/sys/bus/pci/devices")
    if not pci_root.exists():
        return 0
    count = 0
    for class_path in pci_root.glob("*/class"):
        text = _read_text(class_path)
        if text and text.lower().startswith("0x03"):
            count += 1
    return count


def _uptime_seconds() -> float | None:
    text = _read_text(Path("/proc/uptime"))
    if text is None:
        return None
    try:
        return round(float(text.split()[0]), 1)
    except (IndexError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:
        return None


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


__all__ = [
    "ARTIFACT_KIND_RECEIPT",
    "ARTIFACT_KIND_REPORT",
    "ARTIFACT_KIND_WATCHDOG",
    "DEFAULT_OLD_PC_DEBUG_EVIDENCE_DIR",
    "OLD_PC_DEBUG_BOUNDARY",
    "DebugSignalStatus",
    "OldPcDebugReceipt",
    "OldPcDebugReceiptStore",
    "OldPcDebugReport",
    "OldPcDebugSignal",
    "OldPcDebugTransport",
    "OldPcDebugWatchdogResult",
    "OldPcDisposition",
    "WatchdogStatus",
    "assert_old_pc_debug_boundary",
    "build_old_pc_debug_receipt",
    "build_old_pc_debug_watchdog_result",
    "build_simulated_old_pc_report",
    "collect_current_host_debug_report",
    "create_old_pc_debug_app",
    "create_old_pc_debug_router",
    "evaluate_old_pc_debug_report",
    "old_pc_debug_boundary",
    "post_old_pc_debug_report",
]
